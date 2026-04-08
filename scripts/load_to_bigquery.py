"""Load clean Silver data into BigQuery (sura_clustering_cleaned).

Usage:
    python scripts/load_to_bigquery.py

Tables loaded:
    - sura_clustering_cleaned.tareas_prestador
    - sura_clustering_cleaned.detalle_empresa
    - sura_clustering_cleaned.ordenado
    - sura_clustering_cleaned.tareas_programadas

Existing tables are fully replaced (WRITE_TRUNCATE).
"""

import io
import polars as pl
from google.cloud import bigquery

from src.silver.extract import (
    load_empresas, load_tareas_prestador,
    load_ordenado, load_tareas_programadas,
)

PROJECT   = "proyecto-sura-clustering-2026"
DATASET   = "sura_clustering_cleaned"
CLIENT    = bigquery.Client(project=PROJECT)

JOB_CONFIG = bigquery.LoadJobConfig(
    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    source_format=bigquery.SourceFormat.PARQUET,
)


def load_table(table_name: str, df: pl.DataFrame) -> None:
    destination = f"{PROJECT}.{DATASET}.{table_name}"
    print(f"Loading {destination} ({len(df):,} rows)...")
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    buffer.seek(0)
    job = CLIENT.load_table_from_file(buffer, destination, job_config=JOB_CONFIG)
    job.result()
    table = CLIENT.get_table(destination)
    print(f"  ✓ {table.num_rows:,} rows, {len(table.schema)} columns\n")


def main():
    print("=== Silver → BigQuery load ===\n")

    print("Processing tareas_prestador...")
    load_table("tareas_prestador", load_tareas_prestador().collect())

    print("Processing detalle_empresa...")
    load_table("detalle_empresa", load_empresas().collect())

    print("Processing ordenado...")
    load_table("ordenado", load_ordenado().collect())

    print("Processing tareas_programadas...")
    load_table("tareas_programadas", load_tareas_programadas().collect())

    print("=== Load complete ===")


if __name__ == "__main__":
    main()
