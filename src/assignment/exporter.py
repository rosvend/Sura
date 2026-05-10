"""Batch exporter del motor de asignación a BigQuery (Día 3).

Procesa de manera vectorizada cada (Dni_Empresa, Codigo_Tarea, Municipio_Entrega_Id)
único en Ordenado y escribe dos tablas:

    sura_clustering_processed.recommendations_top10
        Top-10 prestadores por orden con desglose del score. Insumo del
        dashboard JS para la vista "asignador".

    sura_clustering_processed.assignments
        Top-1 por orden — la recomendación del sistema. Insumo de la simulación
        de KPIs (Día 4) y del comparador con la asignación histórica.

Diseño:
  * Una sola join cross-product entre orders.Codigo_Tarea y catalog.CDTAREA.
    Sobre el resultado se aplica el mismo scoring que `score_providers`
    pero en columnas Polars (sin loop Python).
  * Particionar por chunks de N órdenes si la materialización completa
    excede memoria; por defecto procesamos todo de una vez (~150-300K
    órdenes únicas × ~30 candidatos/tarea = ~5M filas intermedias).

Uso:
    PYTHONPATH=. uv run python -m src.assignment.exporter
    # Modo sample:
    PYTHONPATH=. uv run python -m src.assignment.exporter --limit 5000
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time

import polars as pl

from src.config import (
    ASSIGNMENTS_PARQUET,
    BQ_DATASET_GOLD,
    BQ_PROJECT,
    BQ_TABLE_ASSIGNMENTS,
    BQ_TABLE_RECOMMENDATIONS_TOP10,
    CLUSTERS_PARQUET,
    GOLD_PARQUETS,
    RECOMMENDATIONS_TOP10_PARQUET,
)
from src.gold.cluster_profiles import ARCHETYPE_NAMES
from src.gold.clustering_input import build_clustering_input
from src.gold.feat_prestador import build_prestador_features
from src.silver.extract import load_ordenado, load_tareas_prestador

# Reutilizamos las constantes del scorer
from src.assignment.score import (
    CLUSTER_VIRTUAL,
    SENIORITY_THRESHOLD_COMPLEX,
    SENIORITY_THRESHOLD_DEFAULT,
    W_CAP,
    W_GEO,
    W_PERF,
    W_SPEC,
)


def _build_candidate_pool() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Devuelve (pool_tarea, muni_lookup).

    pool_tarea: una fila por (CDTAREA, DNI_PRESTADOR) con TODAS las features
    de scoring. Sin list-columns de municipios (esas viven en muni_lookup).

    muni_lookup: una fila por (CDTAREA, DNI_PRESTADOR, CDMUNICIPIO) — tabla
    plana usada con un hash-join semi para detectar match exacto de municipio
    y match de departamento. Mucho más eficiente que `list.contains` cuando
    se cruza con 500K órdenes.
    """
    catalog = (
        load_tareas_prestador()
        .select(["DNI_PRESTADOR", "CDTAREA", "CDMUNICIPIO", "CAPACIDAD"])
        .drop_nulls(["DNI_PRESTADOR", "CDTAREA", "CDMUNICIPIO"])
        .unique()
        .collect()
    )
    prestador = (
        build_prestador_features()
        .select([
            "DNI_PRESTADOR", "tipo_perfil", "capacidad", "sin_capacidad",
            "utilizacion_capacidad",
            "tasa_ejecucion", "tasa_aprobacion_informe",
            "tasa_cancela_real_prestador",
            "dni_distribuidor", "nombre_distribuidor",
        ])
        .collect()
    )
    ord_map = (
        build_clustering_input()
        .select(["DNI_PRESTADOR", "tipo_perfil_ord"])
        .collect()
    )
    clusters = pl.read_parquet(CLUSTERS_PARQUET).select(["DNI_PRESTADOR", "cluster_id"])

    # Pool por tarea (sin municipios)
    pool_tarea = (
        catalog
        .group_by(["CDTAREA", "DNI_PRESTADOR"])
        .agg(pl.col("CAPACIDAD").max().alias("capacidad_catalog"))
        .join(prestador, on="DNI_PRESTADOR", how="left")
        .join(ord_map,   on="DNI_PRESTADOR", how="left")
        .join(clusters,  on="DNI_PRESTADOR", how="left")
        .filter(
            pl.col("cluster_id").is_not_null()
            & (pl.col("cluster_id") != -1)
            & ~pl.col("sin_capacidad").fill_null(True)
            & (pl.col("utilizacion_capacidad").fill_null(0.0) <= 1.5)
        )
    )
    # Pre-anotar scores que no dependen de la orden (specialization base y performance)
    pool_tarea = pool_tarea.with_columns(
        pl.col("tipo_perfil_ord").fill_null(3.0).alias("_perfil_ord"),
        (
            (
                pl.col("tasa_ejecucion").fill_null(0.5)
                + pl.col("tasa_aprobacion_informe").fill_null(0.5)
                + (1.0 - pl.col("tasa_cancela_real_prestador").fill_null(0.5))
            ) / 3.0
        ).clip(0.0, 1.0).alias("score_performance"),
        pl.when(pl.col("utilizacion_capacidad").is_null())
        .then(pl.lit(0.5))
        .otherwise(
            pl.max_horizontal(
                pl.lit(0.0),
                pl.lit(1.0) - 1.3 * (pl.col("utilizacion_capacidad") - 0.7).abs(),
            )
        )
        .alias("score_capacity"),
    )

    # Lookup tabla plana: una fila por (tarea, prestador, municipio).
    # Pequeña — restringida a las parejas que sobrevivieron los hard filters.
    valid_pairs = pool_tarea.select(["CDTAREA", "DNI_PRESTADOR"])
    muni_lookup = (
        catalog
        .join(valid_pairs, on=["CDTAREA", "DNI_PRESTADOR"], how="inner")
        .select(["CDTAREA", "DNI_PRESTADOR", "CDMUNICIPIO"])
    )

    print(f"[exporter] pool_tarea: {pool_tarea.height:,} (CDTAREA × DNI_PRESTADOR) pairs")
    print(f"[exporter] muni_lookup: {muni_lookup.height:,} (CDTAREA × DNI_PRESTADOR × CDMUNICIPIO) rows")
    return pool_tarea, muni_lookup


def _load_orders(limit: int | None) -> pl.DataFrame:
    """Carga (empresa, tarea, municipio, segmentación) únicos desde Ordenado."""
    lf = (
        load_ordenado()
        .select([
            "Dni_Empresa", "Codigo_Tarea", "Municipio_Entrega_Id",
            "Macrosegmentacion_Desc",
        ])
        .drop_nulls(["Dni_Empresa", "Codigo_Tarea", "Municipio_Entrega_Id"])
    )
    orders = lf.collect().unique()
    # Normalización del municipio: Ordenado guarda "586.0" (sufijo float), catálogo "586".
    orders = orders.with_columns(
        pl.when(pl.col("Municipio_Entrega_Id").str.ends_with(".0"))
        .then(pl.col("Municipio_Entrega_Id").str.slice(0, pl.col("Municipio_Entrega_Id").str.len_chars() - 2))
        .otherwise(pl.col("Municipio_Entrega_Id"))
        .alias("cd_municipio_destino")
    )
    if limit is not None:
        orders = orders.head(limit)
    print(f"[exporter] orders to score: {orders.height:,} unique (empresa, tarea, municipio)")
    return orders


def _score_chunk(
    orders: pl.DataFrame,
    pool_tarea: pl.DataFrame,
    muni_lookup: pl.DataFrame,
    archetype_df: pl.DataFrame,
) -> pl.DataFrame:
    """Scoring vectorizado para un chunk de órdenes.

    Pasos:
      1. Clasificación de segmento (is_complex / is_virtual_seg) ANTES del join
         para reducir tamaño.
      2. Inner-join orders × pool_tarea (sin list columns) en CDTAREA.
      3. Hard filter LIVIANA → cluster_id == 3.
      4. Hash-semi-join contra muni_lookup para `has_muni_match` (exacto)
         y `has_depto_match` (prefijo 2 chars).
      5. Combinación de scores y rank top-10.
    """
    if orders.is_empty():
        return pl.DataFrame()

    o = orders.with_columns(
        pl.col("Macrosegmentacion_Desc").fill_null("").str.to_uppercase().alias("_seg_up")
    ).with_columns([
        (
            pl.col("_seg_up").str.contains("GRAN")
            | pl.col("_seg_up").str.contains("MEDIANA")
            | pl.col("_seg_up").str.contains("CORPORATIVO")
        ).alias("is_complex"),
        (
            pl.col("_seg_up").str.contains("INDEPENDIENTE")
            | pl.col("_seg_up").str.contains("MICRO")
            | pl.col("_seg_up").str.contains("EMPRESA NUEVA")
        ).alias("is_virtual_seg"),
        pl.col("cd_municipio_destino").str.slice(0, 2).alias("_target_depto"),
    ]).drop("_seg_up")

    joined = o.join(pool_tarea, left_on="Codigo_Tarea", right_on="CDTAREA", how="inner")
    if joined.is_empty():
        return pl.DataFrame()

    # Hard filter cluster gating.
    joined = joined.filter(
        ~pl.col("is_virtual_seg") | (pl.col("cluster_id") == CLUSTER_VIRTUAL)
    )
    if joined.is_empty():
        return pl.DataFrame()

    # Hash-semi-join para has_muni_match: existe (Codigo_Tarea, DNI_PRESTADOR, CDMUNICIPIO)
    # exacto en muni_lookup.
    muni_match = joined.join(
        muni_lookup.rename({"CDTAREA": "Codigo_Tarea", "CDMUNICIPIO": "cd_municipio_destino"}),
        on=["Codigo_Tarea", "DNI_PRESTADOR", "cd_municipio_destino"],
        how="semi",
    ).select(["Dni_Empresa", "Codigo_Tarea", "cd_municipio_destino", "DNI_PRESTADOR"]) \
     .with_columns(pl.lit(True).alias("has_muni_match"))

    # Hash-semi-join para has_depto_match: existe (Codigo_Tarea, DNI_PRESTADOR, CDMUNICIPIO[:2])
    muni_lookup_dep = muni_lookup.with_columns(
        pl.col("CDMUNICIPIO").str.slice(0, 2).alias("_depto")
    ).select(["CDTAREA", "DNI_PRESTADOR", "_depto"]).unique()
    depto_match = joined.join(
        muni_lookup_dep.rename({"CDTAREA": "Codigo_Tarea", "_depto": "_target_depto"}),
        on=["Codigo_Tarea", "DNI_PRESTADOR", "_target_depto"],
        how="semi",
    ).select(["Dni_Empresa", "Codigo_Tarea", "cd_municipio_destino", "DNI_PRESTADOR"]) \
     .with_columns(pl.lit(True).alias("has_depto_match"))

    join_keys = ["Dni_Empresa", "Codigo_Tarea", "cd_municipio_destino", "DNI_PRESTADOR"]
    joined = joined.join(muni_match,  on=join_keys, how="left") \
                   .join(depto_match, on=join_keys, how="left")
    joined = joined.with_columns([
        pl.col("has_muni_match").fill_null(False),
        pl.col("has_depto_match").fill_null(False),
    ])

    # Specialization (depende de is_complex × _perfil_ord) y Geo.
    joined = joined.with_columns([
        pl.when(pl.col("is_complex"))
        .then(pl.col("_perfil_ord") >= SENIORITY_THRESHOLD_COMPLEX)
        .otherwise(pl.col("_perfil_ord") >= SENIORITY_THRESHOLD_DEFAULT)
        .alias("_seniority_ok"),
    ]).with_columns([
        (
            pl.lit(0.6) + pl.when(pl.col("_seniority_ok")).then(0.4).otherwise(0.0)
        ).alias("score_specialization"),
        pl.when(pl.col("has_muni_match")).then(pl.lit(1.0))
        .when(pl.col("has_depto_match")).then(pl.lit(0.4))
        .otherwise(pl.lit(0.0))
        .alias("score_geo"),
    ])

    joined = joined.with_columns(
        (
            W_SPEC * pl.col("score_specialization")
            + W_CAP  * pl.col("score_capacity")
            + W_GEO  * pl.col("score_geo")
            + W_PERF * pl.col("score_performance")
        ).alias("score_total")
    )

    joined = joined.with_columns(pl.col("cluster_id").cast(pl.Int32))
    joined = joined.join(archetype_df, on="cluster_id", how="left")

    order_keys = ["Dni_Empresa", "Codigo_Tarea", "cd_municipio_destino"]
    joined = joined.with_columns(
        pl.col("score_total").rank(method="ordinal", descending=True)
        .over(order_keys)
        .alias("rank")
    )
    # Reducir a top-10 y dropear columnas auxiliares para liberar memoria.
    return joined.filter(pl.col("rank") <= 10).select([
        "Dni_Empresa", "Codigo_Tarea", "cd_municipio_destino",
        "rank", "DNI_PRESTADOR",
        "score_total", "score_specialization", "score_capacity",
        "score_geo", "score_performance",
        "cluster_id", "archetype_name", "tipo_perfil",
        "utilizacion_capacidad", "nombre_distribuidor",
    ])


def _score_batch_chunked(
    orders: pl.DataFrame,
    pool_tarea: pl.DataFrame,
    muni_lookup: pl.DataFrame,
    chunk_size: int,
) -> pl.DataFrame:
    """Itera orders en chunks de `chunk_size`, llamando a _score_chunk."""
    archetype_df = pl.DataFrame({
        "cluster_id":     list(ARCHETYPE_NAMES.keys()),
        "archetype_name": list(ARCHETYPE_NAMES.values()),
    }).with_columns(pl.col("cluster_id").cast(pl.Int32))

    n = orders.height
    parts: list[pl.DataFrame] = []
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        chunk = orders.slice(start, end - start)
        t0 = time.perf_counter()
        out = _score_chunk(chunk, pool_tarea, muni_lookup, archetype_df)
        parts.append(out)
        print(f"[exporter]   chunk {start:,}–{end:,}/{n:,}  "
              f"out_rows={out.height:,}  ({time.perf_counter() - t0:.1f}s)")
    return pl.concat(parts) if parts else pl.DataFrame()


def _refresh_bq(table: str, gs_uri: str) -> None:
    if not shutil.which("bq"):
        print(f"[exporter] bq CLI no encontrado, omitiendo refresh de {table}")
        return
    cmd = [
        "bq", "load",
        "--replace",
        "--source_format=PARQUET",
        f"--project_id={BQ_PROJECT}",
        f"{BQ_PROJECT}:{table}",
        gs_uri,
    ]
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[exporter] BQ load FAILED for {table}:\n{result.stderr}")
        raise SystemExit(result.returncode)
    print(f"[exporter] BQ {table} refreshed in {time.perf_counter() - t0:.1f}s")


def export(limit: int | None = None, chunk_size: int = 20_000) -> dict:
    t0 = time.perf_counter()
    pool_tarea, muni_lookup = _build_candidate_pool()
    orders = _load_orders(limit=limit)

    print(f"[exporter] scoring batch in chunks of {chunk_size:,}...")
    t1 = time.perf_counter()
    top10 = _score_batch_chunked(orders, pool_tarea, muni_lookup, chunk_size=chunk_size)
    print(f"[exporter] scoring done in {time.perf_counter() - t1:.1f}s — "
          f"{top10.height:,} (order × prestador) rows")

    recs = top10.rename({
        "Dni_Empresa":   "dni_empresa",
        "Codigo_Tarea":  "codigo_tarea",
        "DNI_PRESTADOR": "dni_prestador",
    })
    assignments = recs.filter(pl.col("rank") == 1)

    print(f"[exporter] writing parquet → {RECOMMENDATIONS_TOP10_PARQUET}")
    recs.write_parquet(RECOMMENDATIONS_TOP10_PARQUET)
    print(f"[exporter] writing parquet → {ASSIGNMENTS_PARQUET}")
    assignments.write_parquet(ASSIGNMENTS_PARQUET)

    _refresh_bq(BQ_TABLE_RECOMMENDATIONS_TOP10, RECOMMENDATIONS_TOP10_PARQUET)
    _refresh_bq(BQ_TABLE_ASSIGNMENTS,           ASSIGNMENTS_PARQUET)

    elapsed = time.perf_counter() - t0
    print(f"\n[exporter] done in {elapsed:.1f}s")
    print(f"           recommendations_top10: {recs.height:,} rows")
    print(f"           assignments:           {assignments.height:,} rows")
    return {"recommendations": recs.height, "assignments": assignments.height}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit number of unique orders to score (sample mode)")
    parser.add_argument("--chunk-size", type=int, default=20_000,
                        help="Orders per chunk (default 20000; reduce on low-RAM machines)")
    args = parser.parse_args()
    export(limit=args.limit, chunk_size=args.chunk_size)


if __name__ == "__main__":
    main()
