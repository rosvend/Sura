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


def _build_candidate_pool() -> pl.DataFrame:
    """Construye una fila por (DNI_PRESTADOR, CDTAREA) con lista de municipios
    y todas las features de scoring pre-joinadas.
    """
    catalog = (
        load_tareas_prestador()
        .select(["DNI_PRESTADOR", "CDTAREA", "CDMUNICIPIO", "CAPACIDAD", "DSTIPO_PERFIL"])
        .collect()
    )
    cand = (
        catalog
        .group_by(["CDTAREA", "DNI_PRESTADOR"])
        .agg([
            pl.col("CDMUNICIPIO").unique().alias("munis"),
            pl.col("CDMUNICIPIO").str.slice(0, 2).unique().alias("deptos"),
            pl.col("CAPACIDAD").max().alias("capacidad_catalog"),
        ])
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

    pool = (
        cand
        .join(prestador,   on="DNI_PRESTADOR", how="left")
        .join(ord_map,     on="DNI_PRESTADOR", how="left")
        .join(clusters,    on="DNI_PRESTADOR", how="left")
        .filter(
            pl.col("cluster_id").is_not_null()
            & (pl.col("cluster_id") != -1)
            & ~pl.col("sin_capacidad").fill_null(True)
            & (pl.col("utilizacion_capacidad").fill_null(0.0) <= 1.5)
        )
    )
    print(f"[exporter] candidate pool: {pool.height:,} rows ({pool['CDTAREA'].n_unique()} tareas, "
          f"{pool['DNI_PRESTADOR'].n_unique()} prestadores)")
    return pool


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


def _score_batch(orders: pl.DataFrame, pool: pl.DataFrame) -> pl.DataFrame:
    """Vectorización del scoring para todas las (empresa, tarea, muni) en `orders`."""
    # Cross join por tarea — explota a ~N × ~30 filas
    joined = orders.join(
        pool,
        left_on="Codigo_Tarea",
        right_on="CDTAREA",
        how="inner",
    )
    if joined.is_empty():
        return joined

    # Clasificación de segmento (case-insensitive, tolerante a vocabularios).
    joined = joined.with_columns(
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
    ])

    # Hard filter: LIVIANA → solo cluster 3 (Q&A 2026-04-11). Otras rutas no
    # excluyen cluster 3 (ver auditoría 2026-05-09: exclusión sobre-restrictiva).
    joined = joined.filter(
        ~pl.col("is_virtual_seg") | (pl.col("cluster_id") == CLUSTER_VIRTUAL)
    )

    # Geo flags
    joined = joined.with_columns([
        pl.col("munis").list.contains(pl.col("cd_municipio_destino")).alias("has_muni_match"),
        pl.col("deptos").list.contains(
            pl.col("cd_municipio_destino").str.slice(0, 2)
        ).alias("has_depto_match"),
    ])

    # 1. Specialization: catálogo (siempre true por inner join) + seniority match
    joined = joined.with_columns(
        pl.col("tipo_perfil_ord").fill_null(3.0).alias("_perfil_ord")
    ).with_columns(
        pl.when(pl.col("is_complex"))
        .then(pl.col("_perfil_ord") >= SENIORITY_THRESHOLD_COMPLEX)
        .otherwise(pl.col("_perfil_ord") >= SENIORITY_THRESHOLD_DEFAULT)
        .alias("_seniority_ok")
    ).with_columns(
        (
            pl.lit(0.6)
            + pl.when(pl.col("_seniority_ok")).then(0.4).otherwise(0.0)
        ).alias("score_specialization")
    )

    # 2. Capacity: tent alrededor de util = 0.7
    joined = joined.with_columns(
        pl.when(pl.col("utilizacion_capacidad").is_null())
        .then(pl.lit(0.5))
        .otherwise(
            pl.max_horizontal(
                pl.lit(0.0),
                pl.lit(1.0) - 1.3 * (pl.col("utilizacion_capacidad") - 0.7).abs(),
            )
        )
        .alias("score_capacity")
    )

    # 3. Geo
    joined = joined.with_columns(
        pl.when(pl.col("has_muni_match")).then(pl.lit(1.0))
        .when(pl.col("has_depto_match")).then(pl.lit(0.4))
        .otherwise(pl.lit(0.0))
        .alias("score_geo")
    )

    # 4. Performance: media de (exec, aprob_informe, 1-cancela)
    joined = joined.with_columns(
        (
            (
                pl.col("tasa_ejecucion").fill_null(0.5)
                + pl.col("tasa_aprobacion_informe").fill_null(0.5)
                + (1.0 - pl.col("tasa_cancela_real_prestador").fill_null(0.5))
            ) / 3.0
        ).clip(0.0, 1.0).alias("score_performance")
    )

    # Score total
    joined = joined.with_columns(
        (
            W_SPEC * pl.col("score_specialization")
            + W_CAP  * pl.col("score_capacity")
            + W_GEO  * pl.col("score_geo")
            + W_PERF * pl.col("score_performance")
        ).alias("score_total")
    )

    # Anotar arquetipo
    archetype_df = pl.DataFrame({
        "cluster_id":     list(ARCHETYPE_NAMES.keys()),
        "archetype_name": list(ARCHETYPE_NAMES.values()),
    }).with_columns(pl.col("cluster_id").cast(pl.Int32))
    joined = joined.with_columns(pl.col("cluster_id").cast(pl.Int32))
    joined = joined.join(archetype_df, on="cluster_id", how="left")

    # Top-10 por (Dni_Empresa, Codigo_Tarea, cd_municipio_destino)
    order_keys = ["Dni_Empresa", "Codigo_Tarea", "cd_municipio_destino"]
    joined = joined.with_columns(
        pl.col("score_total").rank(method="ordinal", descending=True)
        .over(order_keys)
        .alias("rank")
    )
    return joined.filter(pl.col("rank") <= 10)


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


def export(limit: int | None = None) -> dict:
    t0 = time.perf_counter()
    pool   = _build_candidate_pool()
    orders = _load_orders(limit=limit)

    print("[exporter] scoring batch...")
    t1 = time.perf_counter()
    top10 = _score_batch(orders, pool)
    print(f"[exporter] scoring done in {time.perf_counter() - t1:.1f}s — "
          f"{top10.height:,} (order × prestador) rows")

    recs = top10.select([
        pl.col("Dni_Empresa").alias("dni_empresa"),
        pl.col("Codigo_Tarea").alias("codigo_tarea"),
        pl.col("cd_municipio_destino"),
        pl.col("rank"),
        pl.col("DNI_PRESTADOR").alias("dni_prestador"),
        pl.col("score_total"),
        pl.col("score_specialization"),
        pl.col("score_capacity"),
        pl.col("score_geo"),
        pl.col("score_performance"),
        pl.col("cluster_id"),
        pl.col("archetype_name"),
        pl.col("tipo_perfil"),
        pl.col("utilizacion_capacidad"),
        pl.col("nombre_distribuidor"),
    ])
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
    args = parser.parse_args()
    export(limit=args.limit)


if __name__ == "__main__":
    main()
