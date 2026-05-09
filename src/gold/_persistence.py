"""Helper de materialización para la capa Gold.

Las tablas Gold son el resultado de joins pesados sobre Silver
(1.5M × 2.1M filas). Recomputarlas en cada llamada bloquea máquinas
con < 32 GB de RAM. Este módulo persiste el resultado a parquet (GCS o
disco local) y devuelve un LazyFrame que escanea ese archivo.

Uso típico desde un módulo Gold:

    from src.config import GOLD_PARQUETS
    from src.gold._persistence import read_or_build

    def build_clustering_input(force_rebuild: bool = False) -> pl.LazyFrame:
        return read_or_build(
            uri=GOLD_PARQUETS["clustering_input"],
            build_fn=_compute_clustering_input,
            force_rebuild=force_rebuild,
        )

`_compute_clustering_input` debe devolver un LazyFrame con la lógica original.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import polars as pl


def _exists(uri: str) -> bool:
    """True si el parquet existe en GCS o en disco local."""
    if uri.startswith("gs://"):
        import gcsfs  # dep transitiva ya disponible (gcsfs en pyproject)
        return gcsfs.GCSFileSystem().exists(uri)
    return Path(uri).exists()


def read_or_build(
    uri: str,
    build_fn: Callable[[], pl.LazyFrame],
    force_rebuild: bool = False,
) -> pl.LazyFrame:
    """Devuelve un LazyFrame que escanea `uri`.

    Si el archivo no existe (o force_rebuild=True), ejecuta build_fn(),
    materializa el resultado en `uri`, y luego devuelve un scan sobre él.
    """
    if force_rebuild or not _exists(uri):
        df = build_fn().collect()
        df.write_parquet(uri)
    return pl.scan_parquet(uri)
