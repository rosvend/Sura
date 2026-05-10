"""Motor de scoring para asignación prestador ↔ orden (Día 3).

Para un (empresa_id, cdtarea, cd_municipio_destino) dado, devuelve el top-N de
prestadores compatibles con el desglose del score y una racional textual.

Diseño:
  * Hard filters: catálogo (CDTAREA), capacidad activa, cluster ≠ -1, cluster
    gating por Ruta_Atencion de la empresa (LIVIANA → solo cluster 3).
  * Score ponderado (0..1) con pesos del hierarchy SURA_QA §6:
        0.45 score_specialization  — match de catálogo + seniority vs. complejidad
        0.30 score_capacity        — tent function alrededor de util 0.7
        0.15 score_geo             — match exacto municipio > mismo departamento
        0.10 score_performance     — mezcla de tasas operativas 2025
  * Devuelve DataFrame de Polars ordenado por score_total descendente.

El módulo cachea las tablas de referencia (catalog, prestador, clusters) en
memoria al primer llamado. feat_empresa NO se cachea (2.17M filas); se hace
lookup lazy por Empresa_Id.

Uso:
    from src.assignment import score_providers
    top10 = score_providers("E000123", "T0042", "11001", top_n=10)
"""

from __future__ import annotations

from typing import Optional

import polars as pl

from src.config import CLUSTERS_PARQUET, GOLD_PARQUETS
from src.gold.cluster_profiles import ARCHETYPE_NAMES
from src.gold.clustering_input import build_clustering_input
from src.gold.feat_prestador import build_prestador_features
from src.silver.extract import load_tareas_prestador

# ── Pesos (SURA_QA §6, prioridades especialización → capacidad → geo) ─────────
W_SPEC = 0.45
W_CAP  = 0.30
W_GEO  = 0.15
W_PERF = 0.10

# ── Reglas de gating de cluster (DIAGNOSTICO §5.3) ────────────────────────────
CLUSTER_VIRTUAL = 3  # arquetipo "Virtuales Especializados (LIVIANA)"
RUTA_LIVIANA    = "LIVIANA"
RUTAS_COMPLEJAS = frozenset({"AVANZADA", "ESPECIALIZADA"})

# Segmentos considerados "complejos" para el match de seniority. Cubrimos los
# vocabularios de Detalle_Empresa.Segmentacion_Arl_Desc ("Gran Empresa",
# "Mediana") y de Ordenado.Macrosegmentacion_Desc ("GRAN EMPRESA",
# "MEDIANA EMPRESA", "CORPORATIVO"). El match es case-insensitive con prefijos.
COMPLEX_TOKENS = frozenset({"GRAN", "MEDIANA", "CORPORATIVO"})

# Segmentos que se atienden por canal virtual (ruta LIVIANA) cuando no tenemos
# Ruta_Atencion explícita. Confirmado en Q&A 2026-04-11: ruta liviana para
# independientes y microempresas.
VIRTUAL_TOKENS = frozenset({"INDEPENDIENTE", "MICRO", "EMPRESA NUEVA"})

# Umbral de seniority (tipo_perfil_ord) considerado adecuado para empresas
# complejas. Escala: BASICO=1 → ESPECIALISTA=7.
SENIORITY_THRESHOLD_COMPLEX = 5.0
SENIORITY_THRESHOLD_DEFAULT = 3.0


def _classify_segmentacion(segmentacion: str | None) -> tuple[bool, bool]:
    """Devuelve (is_complex, is_virtual_candidate) según el texto del segmento.

    Funciona para los vocabularios de Detalle_Empresa y Ordenado:
        is_complex            → seniority mínima alta
        is_virtual_candidate  → si no hay Ruta_Atencion explícita, asumir LIVIANA
    """
    if not segmentacion:
        return (False, False)
    up = segmentacion.upper()
    is_complex = any(tok in up for tok in COMPLEX_TOKENS)
    is_virtual = any(tok in up for tok in VIRTUAL_TOKENS)
    return (is_complex, is_virtual)


# ── Caché de datos de referencia ──────────────────────────────────────────────

_DATA_CACHE: dict[str, pl.DataFrame] | None = None


def _load_reference_data() -> dict[str, pl.DataFrame]:
    """Carga las tablas estáticas a memoria. Llamada idempotente."""
    global _DATA_CACHE
    if _DATA_CACHE is not None:
        return _DATA_CACHE

    catalog = (
        load_tareas_prestador()
        .select([
            "DNI_PRESTADOR", "CDTAREA", "CDMUNICIPIO",
            "CAPACIDAD", "DSTIPO_PERFIL", "DSBLOQUE", "FUNCION_PRESTADOR",
        ])
        .collect()
    )
    prestador = (
        build_prestador_features()
        .select([
            "DNI_PRESTADOR", "tipo_perfil", "capacidad", "sin_capacidad",
            "utilizacion_capacidad",
            "tasa_ejecucion", "tasa_aprobacion_informe",
            "tasa_cancela_real_prestador",
            "nombre_distribuidor", "dni_distribuidor",
        ])
        .collect()
    )
    ord_map = (
        build_clustering_input()
        .select(["DNI_PRESTADOR", "tipo_perfil_ord"])
        .collect()
    )
    clusters = pl.read_parquet(CLUSTERS_PARQUET).select(["DNI_PRESTADOR", "cluster_id"])

    _DATA_CACHE = {
        "catalog":         catalog,
        "prestador":       prestador,
        "tipo_perfil_ord": ord_map,
        "clusters":        clusters,
    }
    return _DATA_CACHE


def _lookup_empresa(empresa_id: str) -> dict | None:
    """Búsqueda lazy en feat_empresa por Empresa_Id (2.17M filas, no se cachea)."""
    row = (
        pl.scan_parquet(GOLD_PARQUETS["feat_empresa"])
        .filter(pl.col("Empresa_Id") == empresa_id)
        .select(["Empresa_Id", "Segmentacion_Arl_Desc", "Ruta_Atencion"])
        .collect()
    )
    if row.height == 0:
        return None
    return row.row(0, named=True)


# ── API pública ──────────────────────────────────────────────────────────────

def score_providers(
    cdtarea: str,
    cd_municipio_destino: Optional[str] = None,
    *,
    empresa_id: Optional[str] = None,
    segmentacion: Optional[str] = None,
    ruta_atencion: Optional[str] = None,
    top_n: int = 10,
) -> pl.DataFrame:
    """Devuelve los top-N prestadores compatibles con la orden.

    Contexto de empresa (uno de estos modos, en orden de precedencia):
      1. `segmentacion` y/o `ruta_atencion` pasados explícitamente → se usan.
         Vía obligatoria para el batch sobre Ordenado, cuyo Dni_Empresa está
         hasheado y NO joinea contra Detalle_Empresa (ver auditoría 2026-05-09).
      2. `empresa_id` pasado, lookup exitoso en feat_empresa → se usan campos
         del parquet. Vía para dashboard JS con NIT real.
      3. Sin contexto → asume estándar / no-virtual (peor caso para LIVIANA,
         pero el filtro de catálogo igual restringe el candidate set).

    Devuelve un DataFrame vacío si ningún prestador pasa los filtros duros.
    """
    data = _load_reference_data()

    # Normalización: Municipio_Entrega_Id en Ordenado viene como "4959.0" (sufijo .0
    # del cast float→str), mientras que CDMUNICIPIO en tareas_prestador es "4959".
    if cd_municipio_destino and cd_municipio_destino.endswith(".0"):
        cd_municipio_destino = cd_municipio_destino[:-2]

    # Resolución de contexto de empresa.
    if segmentacion is None and ruta_atencion is None and empresa_id:
        empresa = _lookup_empresa(empresa_id)
        if empresa is not None:
            segmentacion  = segmentacion  or empresa.get("Segmentacion_Arl_Desc")
            ruta_atencion = ruta_atencion or empresa.get("Ruta_Atencion")

    is_complex, is_virtual_seg = _classify_segmentacion(segmentacion)
    ruta = (ruta_atencion or "").upper()
    # Si no hay Ruta_Atencion explícita, inferir LIVIANA por segmento.
    if not ruta and is_virtual_seg:
        ruta = RUTA_LIVIANA

    # ── Hard filter 1: prestadores con CDTAREA en catálogo ────────────────────
    cand_catalog = data["catalog"].filter(pl.col("CDTAREA") == cdtarea)
    if cand_catalog.height == 0:
        return pl.DataFrame()

    # Agregamos por prestador: lista de municipios donde tiene la tarea + deptos
    # (primeros 2 chars de CDMUNICIPIO = código DIVIPOLA del departamento).
    candidates = (
        cand_catalog
        .group_by("DNI_PRESTADOR")
        .agg([
            pl.col("CDMUNICIPIO").unique().alias("munis"),
            pl.col("CDMUNICIPIO").str.slice(0, 2).unique().alias("deptos"),
            pl.col("CAPACIDAD").max().alias("capacidad_catalog"),
        ])
    )

    df = (
        candidates
        .join(data["prestador"],       on="DNI_PRESTADOR", how="left")
        .join(data["tipo_perfil_ord"], on="DNI_PRESTADOR", how="left")
        .join(data["clusters"],        on="DNI_PRESTADOR", how="left")
    )

    # ── Hard filter 2: cluster válido, capacidad, no severamente sobrecargado ─
    df = df.filter(
        (pl.col("cluster_id").is_not_null() & (pl.col("cluster_id") != -1))
        & ~pl.col("sin_capacidad").fill_null(True)
        & (pl.col("utilizacion_capacidad").fill_null(0.0) <= 1.5)
    )

    # ── Hard filter 3: cluster gating por Ruta_Atencion ──────────────────────
    # Solo se enforza la regla LIVIANA → cluster 3 (canal virtual), confirmada
    # explícitamente en Q&A 2026-04-11. Para rutas presenciales no excluimos
    # cluster 3: la auditoría de 200 órdenes mostró ~5 % de misses por
    # exclusión sobre-restrictiva. El scoring se encarga de penalizar el match
    # incorrecto vía score_specialization.
    if ruta == RUTA_LIVIANA:
        df = df.filter(pl.col("cluster_id") == CLUSTER_VIRTUAL)

    if df.height == 0:
        return pl.DataFrame()

    # ── Componentes del score ────────────────────────────────────────────────
    target_depto = cd_municipio_destino[:2] if cd_municipio_destino else None

    if cd_municipio_destino:
        df = df.with_columns(
            pl.col("munis").list.contains(cd_municipio_destino).alias("has_muni_match")
        )
    else:
        df = df.with_columns(pl.lit(False).alias("has_muni_match"))

    if target_depto:
        df = df.with_columns(
            pl.col("deptos").list.contains(target_depto).alias("has_depto_match")
        )
    else:
        df = df.with_columns(pl.lit(False).alias("has_depto_match"))

    # 1. Specialization: catálogo (siempre true post-filtro) + seniority match
    seniority_thr = SENIORITY_THRESHOLD_COMPLEX if is_complex else SENIORITY_THRESHOLD_DEFAULT
    df = df.with_columns([
        pl.col("tipo_perfil_ord").fill_null(3.0).alias("_perfil_ord"),
    ]).with_columns([
        (
            pl.lit(0.6)
            + pl.when(pl.col("_perfil_ord") >= seniority_thr).then(0.4).otherwise(0.0)
        ).alias("score_specialization"),
    ])

    # 2. Capacity: tent alrededor de util = 0.7
    df = df.with_columns([
        pl.when(pl.col("utilizacion_capacidad").is_null())
        .then(pl.lit(0.5))
        .otherwise(
            pl.max_horizontal(
                pl.lit(0.0),
                pl.lit(1.0) - 1.3 * (pl.col("utilizacion_capacidad") - 0.7).abs()
            )
        )
        .alias("score_capacity"),
    ])

    # 3. Geo: 1.0 si municipio match, 0.4 si mismo depto, 0 en otro caso
    df = df.with_columns([
        pl.when(pl.col("has_muni_match")).then(pl.lit(1.0))
        .when(pl.col("has_depto_match")).then(pl.lit(0.4))
        .otherwise(pl.lit(0.0))
        .alias("score_geo"),
    ])

    # 4. Performance: media de (ejecución, aprobación informe, 1 - cancela)
    df = df.with_columns([
        (
            (
                pl.col("tasa_ejecucion").fill_null(0.5)
                + pl.col("tasa_aprobacion_informe").fill_null(0.5)
                + (1.0 - pl.col("tasa_cancela_real_prestador").fill_null(0.5))
            ) / 3.0
        ).clip(0.0, 1.0).alias("score_performance"),
    ])

    # ── Score total ───────────────────────────────────────────────────────────
    df = df.with_columns([
        (
            W_SPEC * pl.col("score_specialization")
            + W_CAP  * pl.col("score_capacity")
            + W_GEO  * pl.col("score_geo")
            + W_PERF * pl.col("score_performance")
        ).alias("score_total"),
    ])

    # ── Anotación: arquetipo + racional ──────────────────────────────────────
    archetype_map = pl.DataFrame({
        "cluster_id":     list(ARCHETYPE_NAMES.keys()),
        "archetype_name": list(ARCHETYPE_NAMES.values()),
    })
    df = df.join(archetype_map, on="cluster_id", how="left")

    df = df.with_columns(
        pl.format(
            "{} · perfil={} · util={} · exec={} · cancel={}",
            pl.col("archetype_name").fill_null(pl.lit("(sin nombre)")),
            pl.col("tipo_perfil").fill_null(pl.lit("?")),
            pl.col("utilizacion_capacidad").fill_null(0.0).round(2),
            pl.col("tasa_ejecucion").fill_null(0.0).round(2),
            pl.col("tasa_cancela_real_prestador").fill_null(0.0).round(2),
        ).alias("rationale"),
    )

    return (
        df
        .sort("score_total", descending=True)
        .head(top_n)
        .select([
            "DNI_PRESTADOR",
            "score_total",
            "score_specialization", "score_capacity", "score_geo", "score_performance",
            "cluster_id", "archetype_name",
            "tipo_perfil", "capacidad", "utilizacion_capacidad",
            "dni_distribuidor", "nombre_distribuidor",
            "rationale",
        ])
    )


if __name__ == "__main__":
    # Smoke: 5 órdenes de Ordenado con contexto de empresa embebido.
    import polars as pl
    from src.silver.extract import load_ordenado, load_tareas_prestador

    # Solo tomamos órdenes cuya CDTAREA existe en el catálogo (filtro previo).
    catalog_tareas = set(
        load_tareas_prestador().select("CDTAREA").unique().collect().to_series().to_list()
    )
    sample = (
        load_ordenado()
        .select([
            "Dni_Empresa", "Codigo_Tarea", "Municipio_Entrega_Id",
            "Macrosegmentacion_Desc", "Dni_Prestador",
        ])
        .drop_nulls(["Dni_Empresa", "Codigo_Tarea", "Municipio_Entrega_Id"])
        .filter(pl.col("Codigo_Tarea").is_in(list(catalog_tareas)))
        .head(5)
        .collect()
    )
    for row in sample.iter_rows(named=True):
        print(
            f"\nEmpresa={row['Dni_Empresa']}  Tarea={row['Codigo_Tarea']}  "
            f"Muni={row['Municipio_Entrega_Id']}  Seg={row['Macrosegmentacion_Desc']}  "
            f"Actual={row['Dni_Prestador']}"
        )
        res = score_providers(
            cdtarea=row["Codigo_Tarea"],
            cd_municipio_destino=row["Municipio_Entrega_Id"],
            empresa_id=row["Dni_Empresa"],
            segmentacion=row["Macrosegmentacion_Desc"],
            top_n=5,
        )
        if res.is_empty():
            print("  (no candidates)")
        else:
            print(res.select([
                "DNI_PRESTADOR", "score_total", "score_specialization",
                "score_capacity", "score_geo", "score_performance", "cluster_id",
            ]))
            actual_in_top5 = row["Dni_Prestador"] in res["DNI_PRESTADOR"].to_list()
            print(f"  Actual prestador in top-5: {actual_in_top5}")
