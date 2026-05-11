"""Publica las tablas Gold "derivadas" a BigQuery para el dashboard (Día 5).

Las tablas core (clustering_input, feat_prestador, feat_empresa,
assignments, recommendations_top10, assignments_lp, kpis_summary) ya las
publican sus respectivos scripts. Lo que falta:

  - sura_clustering_processed.prestador_clusters   ← desde GCS parquet
  - sura_clustering_processed.cluster_profile      ← computado via cluster_profiles

Este script es idempotente: corre cuando quieras. Si no hay `bq` en PATH,
aborta con mensaje claro (correr en Colab o en un host con gcloud).

Uso:
    PYTHONPATH=. uv run python scripts/publish_to_bq.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time

import polars as pl

from src.config import (
    BQ_DATASET_GOLD,
    BQ_PROJECT,
    BQ_TABLE_CLUSTER_PROFILE,
    BQ_TABLE_PRESTADOR_CLUSTERS,
    CLUSTERS_PARQUET,
    GCS_BUCKET,
)
from src.gold.cluster_profiles import build_cluster_profile

CLUSTER_PROFILE_PARQUET = f"{GCS_BUCKET}/data/processed/cluster_profile.parquet"


def _check_bq() -> None:
    if not shutil.which("bq"):
        print("ERROR: bq CLI no encontrado en PATH. Corre este script en Colab "
              "Enterprise o instala gcloud SDK.", file=sys.stderr)
        sys.exit(2)


def _bq_load(table: str, gs_uri: str) -> None:
    cmd = [
        "bq", "load",
        "--replace",
        "--source_format=PARQUET",
        f"--project_id={BQ_PROJECT}",
        f"{BQ_PROJECT}:{table}",
        gs_uri,
    ]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[publish] BQ load FAILED for {table}:\n{res.stderr}", file=sys.stderr)
        sys.exit(res.returncode)
    print(f"[publish] BQ {table} refreshed in {time.perf_counter() - t0:.1f}s")


def publish_prestador_clusters() -> None:
    """prestador_clusters ya vive en GCS; sólo lo cargamos a BQ."""
    print(f"[publish] prestador_clusters ← {CLUSTERS_PARQUET}")
    _bq_load(BQ_TABLE_PRESTADOR_CLUSTERS, CLUSTERS_PARQUET)


def publish_cluster_profile() -> None:
    """cluster_profile se computa al vuelo (5 filas, ~30 cols)."""
    print(f"[publish] cluster_profile ← build_cluster_profile()")
    profile = build_cluster_profile()
    print(f"[publish]   {profile.height} rows × {profile.width} cols")
    profile.write_parquet(CLUSTER_PROFILE_PARQUET)
    _bq_load(BQ_TABLE_CLUSTER_PROFILE, CLUSTER_PROFILE_PARQUET)


def main() -> None:
    _check_bq()
    t0 = time.perf_counter()
    publish_prestador_clusters()
    publish_cluster_profile()
    print(f"\n[publish] done in {time.perf_counter() - t0:.1f}s")
    print(f"\nTables refreshed:")
    print(f"  {BQ_PROJECT}.{BQ_TABLE_PRESTADOR_CLUSTERS}")
    print(f"  {BQ_PROJECT}.{BQ_TABLE_CLUSTER_PROFILE}")


if __name__ == "__main__":
    main()
