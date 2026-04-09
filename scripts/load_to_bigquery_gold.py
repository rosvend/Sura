"""Carga las tablas Gold a BigQuery (sura_clustering_processed).

Patrón: build_*() → Polars DataFrame → BigQuery (WRITE_TRUNCATE).
Las tablas se reemplazan completamente en cada ejecución.

Uso:
    python scripts/load_to_bigquery_gold.py

    # Solo una tabla específica:
    python scripts/load_to_bigquery_gold.py feat_prestador_performance

Tablas cargadas (en orden de dependencia):
    feat_prestador_performance  KPIs operativos por asesor (citas + OC)
    feat_prestador_perfil       Vector técnico por asesor (catálogo)
    feat_prestador              Tabla maestra gold por asesor (join prev)
    feat_empresa                Features de demanda por empresa
    clustering_input            Matriz de features lista para sklearn KMeans
"""

import io
import sys

import polars as pl
from google.cloud import bigquery

from src.config import BQ_PROJECT, BQ_DATASET_GOLD
from src.gold.feat_prestador_performance import build_performance_features
from src.gold.feat_prestador_perfil import build_perfil_features
from src.gold.feat_prestador import build_prestador_features
from src.gold.feat_empresa import build_empresa_features
from src.gold.clustering_input import build_clustering_input

# ── Registro de tablas disponibles ───────────────────────────────────────────
# Cada entrada: nombre_tabla → función que devuelve pl.LazyFrame.
# Agregar aquí cuando se creen nuevas tablas Gold.
_TABLES: dict[str, callable] = {
    "feat_prestador_performance": build_performance_features,
    "feat_prestador_perfil":      build_perfil_features,
    "feat_prestador":             build_prestador_features,
    "feat_empresa":               build_empresa_features,
    "clustering_input":           build_clustering_input,
}

CLIENT = bigquery.Client(project=BQ_PROJECT)

_JOB_CONFIG = bigquery.LoadJobConfig(
    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    source_format=bigquery.SourceFormat.PARQUET,
)


def _load_to_bq(table_name: str, df: pl.DataFrame) -> None:
    """Sube un DataFrame a BigQuery y reporta el resultado."""
    destination = f"{BQ_PROJECT}.{BQ_DATASET_GOLD}.{table_name}"
    print(f"  → BigQuery {destination} ({len(df):,} filas)...", end=" ", flush=True)
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    buffer.seek(0)
    job = CLIENT.load_table_from_file(buffer, destination, job_config=_JOB_CONFIG)
    job.result()
    table = CLIENT.get_table(destination)
    print(f"✓  ({table.num_rows:,} filas, {len(table.schema)} columnas)")


def process_table(table_name: str) -> None:
    """Computa y carga a BigQuery una tabla Gold."""
    if table_name not in _TABLES:
        raise ValueError(
            f"Tabla '{table_name}' no registrada en _TABLES. "
            f"Disponibles: {list(_TABLES)}"
        )

    print(f"\n[{table_name}]")
    print("  Computando features...", end=" ", flush=True)
    df = _TABLES[table_name]().collect()
    print(f"✓  ({len(df):,} filas, {len(df.columns)} columnas)")

    _load_to_bq(table_name, df)


def main(tables: list[str] | None = None) -> None:
    """Punto de entrada. Si `tables` es None, procesa todas las registradas."""
    targets = tables or list(_TABLES)

    print(f"=== Gold -> BigQuery ({BQ_DATASET_GOLD}) ===")
    print(f"Tablas a procesar: {targets}\n")

    for name in targets:
        process_table(name)

    print("\n=== Carga completada ===")


if __name__ == "__main__":
    # Uso: python scripts/load_to_bigquery_gold.py [tabla1 tabla2 ...]
    requested = sys.argv[1:] if len(sys.argv) > 1 else None
    main(requested)
