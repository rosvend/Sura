"""Silver layer data loading.

Usage:
    from src.silver.extract import load_ordenado, load_empresas

Each function returns a Polars LazyFrame. Chain .select(), .filter(), then .collect().
"""

import polars as pl

from src.config import PARQUET_FILES


def load_ordenado() -> pl.LazyFrame:
    """Purchase orders (607K rows, 100 cols)."""
    return pl.scan_parquet(PARQUET_FILES["ordenado"])


def load_empresas() -> pl.LazyFrame:
    """Client company master (2.1M rows, 16 cols)."""
    return pl.scan_parquet(PARQUET_FILES["detalle_empresa"])


def load_tareas_programadas() -> pl.LazyFrame:
    """Scheduled tasks & cancellations (1.5M rows, 62 cols)."""
    return pl.scan_parquet(PARQUET_FILES["tareas_programadas"])


def load_tareas_prestador() -> pl.LazyFrame:
    """Provider capabilities catalog."""
    return pl.scan_parquet(PARQUET_FILES["tareas_prestador"])
