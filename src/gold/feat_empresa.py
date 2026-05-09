"""Gold layer — features de demanda por empresa cliente.

Caracteriza a cada empresa afiliada combinando:
  - Detalle_Empresa: atributos maestros (sector, segmento, afiliados, ruta)
  - Ordenado: historial de órdenes de compra recibidas
  - Tareas_Programadas: ejecución real de citas en 2025

Esta tabla representa el lado de la demanda del modelo de asignación.
Junto con feat_prestador (oferta) permite construir el motor de
compatibilidad empresa ↔ clúster de prestadores propuesto en el diagnóstico.

Uso:
    from src.gold.feat_empresa import build_empresa_features
    df = build_empresa_features().collect()
"""

import polars as pl

from src.config import GOLD_PARQUETS
from src.gold._persistence import read_or_build
from src.silver.extract import load_empresas, load_ordenado, load_tareas_programadas

# ── Constantes de dominio ────────────────────────────────────────────────────

# Rutas de atención confirmadas en el dataset (6 valores, inspeccionados)
# Orden ascendente de intensidad de servicio requerido:
#   SIN RUTA < LIVIANA < ESTÁNDAR < INTERVENCIÓN < AVANZADA < ESPECIALIZADA
_RUTAS_ESPECIALIZADAS = frozenset(["AVANZADA", "ESPECIALIZADA"])
_RUTAS_ESTANDAR       = frozenset(["ESTÁNDAR", "INTERVENCIÓN"])
# LIVIANA y SIN RUTA no están en los sets anteriores

_ESTADO_CITA_CANCELADA = "CITA CANCELADA"
_ESTADOS_EJECUTADA     = frozenset([
    "CITA EJECUTADA", "PARCIALMENTE EJECUTADO", "PARCIALMENTE COMPLETADO"
])


# ── Bloques internos ─────────────────────────────────────────────────────────

def _demanda_oc() -> pl.LazyFrame:
    """Historial de órdenes de compra recibidas por empresa.

    Fuente: Ordenado (historial completo, no solo 2025).
    Llave de join: Dni_Empresa → Empresa_Id.
    """
    # Clasificación predominante de tareas demandadas (patrón mode)
    clasificacion_top = (
        load_ordenado()
        .group_by(["Dni_Empresa", "Clasificacion_Desc"])
        .agg(pl.len().alias("_cnt"))
        .sort("_cnt", descending=True)
        .group_by("Dni_Empresa")
        .agg(
            pl.col("Clasificacion_Desc").first().alias("clasificacion_predominante_demanda")
        )
    )

    kpis = (
        load_ordenado()
        .group_by("Dni_Empresa")
        .agg([
            # Volumen de demanda
            pl.col("Numero_Consecutivo_Orden").n_unique().alias("n_oc_historicas"),
            pl.col("Codigo_Tarea").n_unique().alias("n_tareas_distintas_demandadas"),
            pl.col("Dni_Prestador").n_unique().alias("n_prestadores_distintos"),
            pl.col("Municipio_Entrega_Desc").n_unique().alias("n_municipios_servicio"),

            # Costos históricos acumulados
            pl.col("Valor_Costo_Total_Tarea").sum().alias("costo_total_acumulado"),
            pl.col("Valor_Costo_Total_Tarea").mean().alias("costo_total_prom_oc"),
            (
                pl.col("Valor_Costo_Transporte").fill_null(0.0)
                + pl.col("Valor_Costo_Viaticos").fill_null(0.0)
            )
            .sum()
            .alias("costo_logistico_acumulado"),

            # Ventana temporal de actividad
            pl.col("Fecha_Creacion_Orden").min().alias("fecha_primera_oc"),
            pl.col("Fecha_Creacion_Orden").max().alias("fecha_ultima_oc"),
        ])
        .rename({"Dni_Empresa": "Empresa_Id"})
    )

    return kpis.join(
        clasificacion_top.rename({"Dni_Empresa": "Empresa_Id"}),
        on="Empresa_Id",
        how="left",
    )


def _ejecucion_tp() -> pl.LazyFrame:
    """Métricas de ejecución de citas recibidas por empresa en 2025.

    Fuente: Tareas_Programadas_canceladas_2025.
    Llave de join: DNI_EMPRESA → Empresa_Id.

    tasa_cancela_como_cliente: fracción de citas que la propia empresa canceló.
    Distingue entre empresas que no ejecutan sus servicios por elección propia
    vs. prestadores que los cancelan.
    """
    tp = load_tareas_programadas()

    return (
        tp
        .group_by("DNI_EMPRESA")
        .agg([
            pl.len().alias("n_citas_recibidas_2025"),
            pl.col("DSESTADO_PROGRAMACION")
            .is_in(list(_ESTADOS_EJECUTADA))
            .sum()
            .alias("n_citas_ejecutadas_2025"),

            (pl.col("DSESTADO_PROGRAMACION") == _ESTADO_CITA_CANCELADA)
            .sum()
            .alias("n_citas_canceladas_2025"),

            # Cancelaciones iniciadas por la propia empresa
            (
                pl.col("SNCANCELA_EMPRESA")
                & (pl.col("DSESTADO_PROGRAMACION") == _ESTADO_CITA_CANCELADA)
            )
            .sum()
            .alias("n_cancela_como_cliente"),

            pl.col("DNI_PRESTADOR").n_unique().alias("n_prestadores_2025"),
            pl.col("CDTAREA").n_unique().alias("n_tareas_distintas_2025"),

            # Horas de servicio recibidas (solo citas ejecutadas)
            pl.col("DURACION")
            .filter(pl.col("DSESTADO_PROGRAMACION").is_in(list(_ESTADOS_EJECUTADA)))
            .sum()
            .alias("horas_servicio_recibidas_2025"),
        ])
        .rename({"DNI_EMPRESA": "Empresa_Id"})
    )


# ── API pública ──────────────────────────────────────────────────────────────

def build_empresa_features(force_rebuild: bool = False) -> pl.LazyFrame:
    """Tabla Gold de features de demanda por Empresa_Id.

    Por defecto lee de GOLD_PARQUETS["feat_empresa"]. Pasa force_rebuild=True
    para recomputar (caro: join sobre 2.175M empresas × 1.5M citas).

    Estrategia de join: left join desde Detalle_Empresa (catálogo maestro,
    2.175M empresas) hacia OC y citas 2025. Empresas sin actividad histórica
    aparecen con métricas en null y quedan marcadas con FLAG_SIN_DEMANDA_HISTORICA.

    Columna derivada clave
    ──────────────────────
    nivel_complejidad_calculado
        Simplificación de los 6 valores de Ruta_Atencion a 4 niveles para
        el modelo de asignación escalonado propuesto en el diagnóstico:

        INACTIVA     → SIN RUTA (empresa sin ruta de atención activa)
        LIVIANA      → LIVIANA (independientes, micro empresas)
        ESTÁNDAR     → ESTÁNDAR o INTERVENCIÓN
        ESPECIALIZADA → AVANZADA o ESPECIALIZADA (gran empresa, alto riesgo)

    tasa_cancela_como_cliente
        n_cancela_como_cliente / n_citas_canceladas_2025
        Empresas con tasa alta son un factor de riesgo en la asignación:
        el prestador más adecuado puede ser penalizado por cancelaciones
        que no son de su responsabilidad.

    FLAG_EMPRESA_ACTIVA
        True si ESTADO_EMPRESA != "RETIRADO".
        Confirmado en Q&A 2026-04-11: "Retirado = desafiliado; todo lo demás
        es afiliado (En mora = cobertura vigente con deuda)."
        Las empresas retiradas no deben ser objetivo del modelo de asignación.
    """
    return read_or_build(
        uri=GOLD_PARQUETS["feat_empresa"],
        build_fn=_compute_empresa_features,
        force_rebuild=force_rebuild,
    )


def _compute_empresa_features() -> pl.LazyFrame:
    oc   = _demanda_oc()
    tp   = _ejecucion_tp()

    return (
        load_empresas()
        .join(oc, on="Empresa_Id", how="left")
        .join(tp, on="Empresa_Id", how="left")
        # ── Nivel de complejidad calculado ───────────────────────────────────
        .with_columns(
            pl.when(pl.col("Ruta_Atencion") == "SIN RUTA")
            .then(pl.lit("INACTIVA"))
            .when(pl.col("Ruta_Atencion").is_in(list(_RUTAS_ESPECIALIZADAS)))
            .then(pl.lit("ESPECIALIZADA"))
            .when(pl.col("Ruta_Atencion").is_in(list(_RUTAS_ESTANDAR)))
            .then(pl.lit("ESTÁNDAR"))
            .otherwise(pl.lit("LIVIANA"))
            .alias("nivel_complejidad_calculado")
        )
        # ── Tasas derivadas de ejecución 2025 ────────────────────────────────
        .with_columns([
            pl.when(pl.col("n_citas_recibidas_2025") > 0)
            .then(
                pl.col("n_citas_ejecutadas_2025") / pl.col("n_citas_recibidas_2025")
            )
            .otherwise(None)
            .alias("tasa_ejecucion_recibida_2025"),

            pl.when(pl.col("n_citas_canceladas_2025") > 0)
            .then(
                pl.col("n_cancela_como_cliente") / pl.col("n_citas_canceladas_2025")
            )
            .otherwise(None)
            .alias("tasa_cancela_como_cliente"),
        ])
        # ── Flags ─────────────────────────────────────────────────────────────
        # FLAG_EMPRESA_ACTIVA: confirmado en Q&A 2026-04-11.
        # "Retirado significa desafiliado. Todo lo demás es afiliado."
        # "En mora" = en cobertura, debe plata → se considera activa para efectos del modelo.
        .with_columns([
            pl.col("n_oc_historicas").is_null().alias("FLAG_SIN_DEMANDA_HISTORICA"),
            (pl.col("ESTADO_EMPRESA") != "RETIRADO").alias("FLAG_EMPRESA_ACTIVA"),
        ])
        # ── Orden de columnas: identificación → perfil → demanda → flags ─────
        .select([
            # Identificación
            "Empresa_Id",

            # Estado y cobertura (maestro)
            "ESTADO_EMPRESA_CALCULADO",
            "ESTADO_EMPRESA",
            "Fecha_Inicio_Cobertura",
            "Fecha_Fin_Cobertura",

            # Segmentación y caracterización (maestro)
            "Segmentacion_Arl_Desc",
            "Sector_Economico_Desc",
            "Actividad_Economica_Desc",
            "Ind_Afiliada",
            "Afiliados",
            "Numero_Afiliados",
            "Ind_Multiregional",
            "Ruta_Atencion",
            "nivel_complejidad_calculado",
            "GRUPO_ECONOMICO_ARL_ID",
            "UEN_PPAL_ARL_ID",

            # Asesor principal asignado (maestro)
            "ID_PROFESIONAL_PPAL",
            "FLAG_SIN_PROFESIONAL",

            # Demanda histórica (Ordenado)
            "n_oc_historicas",
            "n_tareas_distintas_demandadas",
            "n_prestadores_distintos",
            "n_municipios_servicio",
            "clasificacion_predominante_demanda",
            "costo_total_acumulado",
            "costo_total_prom_oc",
            "costo_logistico_acumulado",
            "fecha_primera_oc",
            "fecha_ultima_oc",

            # Ejecución 2025 (Tareas_Programadas)
            "n_citas_recibidas_2025",
            "n_citas_ejecutadas_2025",
            "n_citas_canceladas_2025",
            "n_cancela_como_cliente",
            "n_prestadores_2025",
            "n_tareas_distintas_2025",
            "horas_servicio_recibidas_2025",
            "tasa_ejecucion_recibida_2025",
            "tasa_cancela_como_cliente",

            # Flags
            "FLAG_SIN_DEMANDA_HISTORICA",
            "FLAG_EMPRESA_ACTIVA",
        ])
    )
