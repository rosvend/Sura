"""Comparador entre nuestro clustering (KMeans+IF) y el del equipo
alternativo (VAE+HDBSCAN). Día 5.

Acepta cualquier parquet que contenga **DNI_PRESTADOR + cluster_id** y lo
compara contra nuestro `prestador_clusters.parquet`. Calcula:

  - Normalized Mutual Information (NMI): qué tan informativo es un
    clustering sobre el otro.
  - Adjusted Rand Index (ARI): acuerdo bilateral corregido por chance.
  - Confusion-matrix: cuántos prestadores de cada cluster nuestro
    caen en cada cluster del otro.
  - Cluster-size distribution overlap.

Si el parquet del otro equipo aún no existe, el script imprime las
estadísticas de nuestro modelo solo y termina sin error.

Uso:
    # Cuando llegue su parquet, decirles que lo escriban a:
    #   gs://sura-clustering-raw/data/processed/prestador_clusters_alt.parquet
    # con al menos las columnas DNI_PRESTADOR y cluster_id.
    PYTHONPATH=. uv run python -m src.monitoring.compare_models

    # O pasar un path custom:
    PYTHONPATH=. uv run python -m src.monitoring.compare_models \
        --alt gs://otro-bucket/clusters_vae.parquet
"""

from __future__ import annotations

import argparse
import sys

import gcsfs
import numpy as np
import polars as pl
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from src.config import CLUSTERS_PARQUET, GCS_BUCKET

DEFAULT_ALT_PARQUET = f"{GCS_BUCKET}/data/processed/prestador_clusters_alt.parquet"


def _gcs_exists(uri: str) -> bool:
    try:
        return gcsfs.GCSFileSystem().exists(uri)
    except Exception:
        return False


def _load_clusters(uri: str, label: str) -> pl.DataFrame:
    df = pl.read_parquet(uri)
    if "DNI_PRESTADOR" not in df.columns or "cluster_id" not in df.columns:
        raise ValueError(
            f"{label} parquet en {uri} debe contener columnas "
            f"DNI_PRESTADOR y cluster_id (encontradas: {df.columns})"
        )
    return df.select(["DNI_PRESTADOR", pl.col("cluster_id").alias(f"cluster_{label}")])


def _print_distribution(df: pl.DataFrame, col: str) -> None:
    counts = df.group_by(col).len().sort("len", descending=True)
    total = df.height
    print(f"  Distribution of {col}:")
    for row in counts.iter_rows(named=True):
        cid = row[col]
        n = row["len"]
        print(f"    cluster {cid!s:>4}: {n:>5,}  ({100 * n / total:5.1f} %)")


def _confusion(joined: pl.DataFrame) -> pl.DataFrame:
    return (
        joined
        .group_by(["cluster_ours", "cluster_alt"])
        .len()
        .pivot(values="len", index="cluster_ours", on="cluster_alt", aggregate_function="first")
        .fill_null(0)
        .sort("cluster_ours")
    )


def run(alt_parquet: str) -> None:
    print(f"[compare] ours: {CLUSTERS_PARQUET}")
    ours = _load_clusters(CLUSTERS_PARQUET, "ours")
    print(f"          {ours.height:,} rows")
    _print_distribution(ours, "cluster_ours")

    if not _gcs_exists(alt_parquet):
        print(f"\n[compare] alt parquet NOT FOUND at {alt_parquet}")
        print("[compare] (skipping comparison — the teammate's VAE+HDBSCAN output")
        print("[compare]  hasn't been published yet. Re-run once it's available.)")
        return

    print(f"\n[compare] alt: {alt_parquet}")
    alt = _load_clusters(alt_parquet, "alt")
    print(f"          {alt.height:,} rows")
    _print_distribution(alt, "cluster_alt")

    joined = ours.join(alt, on="DNI_PRESTADOR", how="inner")
    print(f"\n[compare] intersection: {joined.height:,} prestadores en ambos modelos")
    if joined.is_empty():
        print("[compare] ERROR: 0 prestadores comunes — los DNIs no coinciden, "
              "verificar formato de hash.", file=sys.stderr)
        return

    ours_labels = joined["cluster_ours"].to_numpy()
    alt_labels  = joined["cluster_alt"].to_numpy()

    nmi = normalized_mutual_info_score(ours_labels, alt_labels)
    ari = adjusted_rand_score(ours_labels, alt_labels)
    print()
    print(f"[compare] Normalized Mutual Information: {nmi:.4f}")
    print(f"          (0 = independent, 1 = identical clusterings)")
    print(f"[compare] Adjusted Rand Index:           {ari:.4f}")
    print(f"          (0 = random, 1 = perfect agreement)")

    cm = _confusion(joined)
    print()
    print("[compare] Confusion matrix (rows = ours, cols = alt):")
    print(cm)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alt", default=DEFAULT_ALT_PARQUET,
                        help=f"Path a parquet alternativo (default: {DEFAULT_ALT_PARQUET})")
    args = parser.parse_args()
    run(args.alt)


if __name__ == "__main__":
    main()
