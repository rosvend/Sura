"""Post-hoc enrichment: añade columnas de descomposición de contribución a
assignments y recommendations_top10 ya publicados.

Lee los parquets de GCS producidos por exporter.py, agrega 5 columnas
derivadas (top_contributor + 4 shares), y publica dos tablas nuevas en BQ:

    sura_clustering_processed.assignments_enriched
    sura_clustering_processed.recommendations_top10_enriched

No modifica las tablas originales ni ningún archivo del pipeline.

Uso:
    PYTHONPATH=. uv run python scripts/enrich_assignments.py
    PYTHONPATH=. uv run python scripts/enrich_assignments.py --dry-run
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
    ASSIGNMENTS_ENRICHED_PARQUET,
    BQ_PROJECT,
    BQ_TABLE_ASSIGNMENTS_ENRICHED,
    BQ_TABLE_RECOMMENDATIONS_ENRICHED,
    RECOMMENDATIONS_TOP10_PARQUET,
    RECOMMENDATIONS_ENRICHED_PARQUET,
)
from src.assignment.score import W_CAP, W_GEO, W_PERF, W_SPEC


def _add_contribution_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Añade top_contributor y {spec,cap,geo,perf}_share a un DataFrame que
    ya contiene score_total, score_specialization, score_capacity,
    score_geo, score_performance.

    - top_contributor: etiqueta del componente ponderado más alto.
    - *_share: fracción del score_total aportada por cada componente.
      Null si score_total es 0 o null (no ocurre en producción, guard defensivo).
    """
    df = df.with_columns([
        (W_SPEC * pl.col("score_specialization")).alias("_w_spec"),
        (W_CAP  * pl.col("score_capacity")).alias("_w_cap"),
        (W_GEO  * pl.col("score_geo")).alias("_w_geo"),
        (W_PERF * pl.col("score_performance")).alias("_w_perf"),
    ]).with_columns([
        pl.when(
            (pl.col("_w_spec") >= pl.col("_w_cap")) &
            (pl.col("_w_spec") >= pl.col("_w_geo")) &
            (pl.col("_w_spec") >= pl.col("_w_perf"))
        ).then(pl.lit("Especialización"))
        .when(
            (pl.col("_w_cap") >= pl.col("_w_geo")) &
            (pl.col("_w_cap") >= pl.col("_w_perf"))
        ).then(pl.lit("Capacidad"))
        .when(pl.col("_w_geo") >= pl.col("_w_perf"))
        .then(pl.lit("Geográfico"))
        .otherwise(pl.lit("Desempeño"))
        .alias("top_contributor"),

        pl.when(pl.col("score_total") > 0)
        .then((pl.col("_w_spec") / pl.col("score_total")).clip(0.0, 1.0))
        .alias("spec_share"),

        pl.when(pl.col("score_total") > 0)
        .then((pl.col("_w_cap") / pl.col("score_total")).clip(0.0, 1.0))
        .alias("cap_share"),

        pl.when(pl.col("score_total") > 0)
        .then((pl.col("_w_geo") / pl.col("score_total")).clip(0.0, 1.0))
        .alias("geo_share"),

        pl.when(pl.col("score_total") > 0)
        .then((pl.col("_w_perf") / pl.col("score_total")).clip(0.0, 1.0))
        .alias("perf_share"),
    ]).drop(["_w_spec", "_w_cap", "_w_geo", "_w_perf"])

    return df


def _load_to_bq(table: str, gs_uri: str) -> None:
    if not shutil.which("bq"):
        print(f"[enrich] bq CLI no encontrado, omitiendo carga de {table}")
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
        print(f"[enrich] BQ load FAILED for {table}:\n{result.stderr}")
        raise SystemExit(result.returncode)
    print(f"[enrich] BQ {table} cargado en {time.perf_counter() - t0:.1f}s")


def enrich(dry_run: bool = False) -> None:
    t0 = time.perf_counter()

    print(f"[enrich] leyendo {ASSIGNMENTS_PARQUET} ...")
    assignments = pl.read_parquet(ASSIGNMENTS_PARQUET)
    print(f"[enrich]   {assignments.height:,} filas · {assignments.width} columnas")

    print(f"[enrich] leyendo {RECOMMENDATIONS_TOP10_PARQUET} ...")
    top10 = pl.read_parquet(RECOMMENDATIONS_TOP10_PARQUET)
    print(f"[enrich]   {top10.height:,} filas · {top10.width} columnas")

    print("[enrich] calculando columnas de contribución ...")
    assignments_enriched = _add_contribution_columns(assignments)
    top10_enriched = _add_contribution_columns(top10)

    new_cols = ["top_contributor", "spec_share", "cap_share", "geo_share", "perf_share"]
    print(f"[enrich] columnas nuevas: {new_cols}")

    # Muestra representativa para verificación visual
    print("\n[enrich] sample assignments_enriched (3 filas):")
    print(assignments_enriched.select(
        ["score_total", "top_contributor", "spec_share", "cap_share", "geo_share", "perf_share"]
    ).head(3))

    if dry_run:
        print("\n[enrich] --dry-run: no se escriben parquets ni se carga BQ.")
        return

    print(f"\n[enrich] escribiendo {ASSIGNMENTS_ENRICHED_PARQUET} ...")
    assignments_enriched.write_parquet(ASSIGNMENTS_ENRICHED_PARQUET)

    print(f"[enrich] escribiendo {RECOMMENDATIONS_ENRICHED_PARQUET} ...")
    top10_enriched.write_parquet(RECOMMENDATIONS_ENRICHED_PARQUET)

    _load_to_bq(BQ_TABLE_ASSIGNMENTS_ENRICHED,        ASSIGNMENTS_ENRICHED_PARQUET)
    _load_to_bq(BQ_TABLE_RECOMMENDATIONS_ENRICHED,    RECOMMENDATIONS_ENRICHED_PARQUET)

    print(f"\n[enrich] completado en {time.perf_counter() - t0:.1f}s")
    print(f"         assignments_enriched:           {assignments_enriched.height:,} filas")
    print(f"         recommendations_top10_enriched: {top10_enriched.height:,} filas")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Añade top_contributor y *_share a assignments y recommendations_top10."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Calcula y muestra el resultado sin escribir parquets ni cargar BQ."
    )
    args = parser.parse_args()
    enrich(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
