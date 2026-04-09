GCS_BUCKET = "gs://sura-clustering-raw"

# ── BigQuery ─────────────────────────────────────────────────────────────────
BQ_PROJECT = "proyecto-sura-clustering-2026"
BQ_DATASET_SILVER = "sura_clustering_cleaned"
BQ_DATASET_GOLD   = "sura_clustering_processed"

# ── Bronze: archivos crudos en GCS ───────────────────────────────────────────
RAW_FILES = {
    "ordenado":          f"{GCS_BUCKET}/Ordenado.txt",
    "detalle_empresa":   f"{GCS_BUCKET}/Detalle_Empresa.txt",
    "tareas_programadas": f"{GCS_BUCKET}/Tareas_Programadas_canceladas_2025.txt",
    "tareas_prestador":  f"{GCS_BUCKET}/Tareas_prestador_bloque.xlsx",
}

# ── Silver: parquets limpios en GCS ──────────────────────────────────────────
PARQUET_FILES = {
    "ordenado":          f"{GCS_BUCKET}/Ordenado.parquet",
    "detalle_empresa":   f"{GCS_BUCKET}/Detalle_Empresa.parquet",
    "tareas_programadas": f"{GCS_BUCKET}/Tareas_Programadas_canceladas_2025.parquet",
    "tareas_prestador":  f"{GCS_BUCKET}/Tareas_prestador_bloque.parquet",
}

