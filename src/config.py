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
    "maestro":           f"{GCS_BUCKET}/Maestro.xlsx",
}

# ── Silver: parquets limpios en GCS ──────────────────────────────────────────
PARQUET_FILES = {
    "ordenado":          f"{GCS_BUCKET}/Ordenado.parquet",
    "detalle_empresa":   f"{GCS_BUCKET}/Detalle_Empresa.parquet",
    "tareas_programadas": f"{GCS_BUCKET}/Tareas_Programadas_canceladas_2025.parquet",
    "tareas_prestador":  f"{GCS_BUCKET}/Tareas_prestador_bloque.parquet",
    "maestro":           f"{GCS_BUCKET}/Maestro.parquet",
}

# ── Gold: tablas materializadas (resultado de feature engineering) ───────────
# Persistir aquí evita re-correr Bronze→Silver→Gold (joins de 1.5M × 2.1M filas)
# en cada invocación. La bake corre una sola vez en Vertex AI; los notebooks,
# scripts y la app Streamlit leen de aquí en milisegundos.
GOLD_PARQUETS = {
    "clustering_input": f"{GCS_BUCKET}/gold/clustering_input.parquet",
    "feat_prestador":   f"{GCS_BUCKET}/gold/feat_prestador.parquet",
    "feat_empresa":     f"{GCS_BUCKET}/gold/feat_empresa.parquet",
}

# ── Artefactos del modelo de clustering (Día 1) ──────────────────────────────
# Persistidos en GCS para sobrevivir el shutdown del runtime de Colab Enterprise
# y permitir que la laptop (Días 2–6) los lea sin recomputar.
MODELS_DIR_GCS   = f"{GCS_BUCKET}/models"
CLUSTERS_PARQUET = f"{GCS_BUCKET}/data/processed/prestador_clusters.parquet"

# ── Artefactos del motor de asignación (Día 3) ───────────────────────────────
# El batch exporter escribe estos parquets y luego los carga a BQ
# (sura_clustering_processed.{assignments,recommendations_top10,kpis_summary}).
ASSIGNMENTS_PARQUET           = f"{GCS_BUCKET}/data/processed/assignments.parquet"
RECOMMENDATIONS_TOP10_PARQUET = f"{GCS_BUCKET}/data/processed/recommendations_top10.parquet"
KPIS_SUMMARY_PARQUET          = f"{GCS_BUCKET}/data/processed/kpis_summary.parquet"

# ── Tablas BigQuery que consume el dashboard (JS + Power BI) ─────────────────
BQ_TABLE_ASSIGNMENTS            = f"{BQ_DATASET_GOLD}.assignments"
BQ_TABLE_RECOMMENDATIONS_TOP10  = f"{BQ_DATASET_GOLD}.recommendations_top10"
BQ_TABLE_PRESTADOR_CLUSTERS     = f"{BQ_DATASET_GOLD}.prestador_clusters"
BQ_TABLE_CLUSTER_PROFILE        = f"{BQ_DATASET_GOLD}.cluster_profile"
BQ_TABLE_KPIS_SUMMARY           = f"{BQ_DATASET_GOLD}.kpis_summary"

