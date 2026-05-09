"""Materializa las tablas Gold a parquet en GCS.

Corre una sola vez (en Vertex AI / Colab Enterprise con ≥ 16 GB RAM).
Después, todos los módulos descargan ~10 MB en lugar de recomputar joins
sobre 1.5M × 2.1M filas.

Uso:
    uv run python scripts/bake_gold.py              # bake las 3 tablas
    uv run python scripts/bake_gold.py feat_empresa # bake solo una

Salida:
    gs://sura-clustering-raw/gold/clustering_input.parquet
    gs://sura-clustering-raw/gold/feat_prestador.parquet
    gs://sura-clustering-raw/gold/feat_empresa.parquet
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from typing import Callable

import polars as pl

from src.config import BQ_DATASET_GOLD, BQ_PROJECT, GOLD_PARQUETS
from src.gold.feat_empresa import _compute_empresa_features
from src.gold.feat_prestador import _compute_prestador_features
from src.gold.clustering_input import _compute_clustering_input

# Orden importante: clustering_input depende de feat_prestador (vía build_prestador_features),
# pero como pasamos force_rebuild thread-through, podemos bakear cada uno independientemente.
# Bakeamos feat_prestador primero para que clustering_input lea de parquet en lugar de
# recomputar.
TARGETS: dict[str, Callable[[], pl.LazyFrame]] = {
    "feat_prestador":   _compute_prestador_features,
    "clustering_input": _compute_clustering_input,
    "feat_empresa":     _compute_empresa_features,
}


def _refresh_bq(name: str, gs_uri: str) -> None:
    """Sobrescribe la tabla BQ correspondiente con el parquet recién escrito.

    Usa el CLI `bq` (autenticado vía la cuenta de servicio del runtime de Colab
    Enterprise o `gcloud auth application-default login`). Si `bq` no está en
    PATH, se omite con un aviso — útil para corridas locales que no requieren
    refrescar BQ.
    """
    if not shutil.which("bq"):
        print(f"[bake] bq CLI no encontrado, omitiendo refresh de BQ para {name}")
        return

    table_ref = f"{BQ_PROJECT}:{BQ_DATASET_GOLD}.{name}"
    cmd = [
        "bq", "load",
        "--replace",
        "--source_format=PARQUET",
        f"--project_id={BQ_PROJECT}",
        table_ref,
        gs_uri,
    ]
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        print(f"[bake] BQ refresh FAILED for {name} ({elapsed:.1f}s):")
        print(result.stderr)
        raise SystemExit(result.returncode)
    print(f"[bake] BQ {table_ref} refreshed in {elapsed:.1f}s")


def bake(name: str) -> None:
    if name not in TARGETS:
        raise SystemExit(f"target desconocido: {name}. Disponibles: {list(TARGETS)}")

    uri = GOLD_PARQUETS[name]
    build_fn = TARGETS[name]
    print(f"\n[bake] {name} → {uri}")
    t0 = time.perf_counter()
    df = build_fn().collect()
    elapsed = time.perf_counter() - t0
    print(f"[bake] computed in {elapsed:.1f}s — {df.height:,} rows × {df.width} cols")

    t0 = time.perf_counter()
    df.write_parquet(uri)
    print(f"[bake] wrote parquet in {time.perf_counter() - t0:.1f}s")

    _refresh_bq(name, uri)


def main() -> None:
    targets = sys.argv[1:] or list(TARGETS)
    for name in targets:
        bake(name)
    print("\n[bake] done.")


if __name__ == "__main__":
    main()
