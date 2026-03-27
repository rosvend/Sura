GCS_BUCKET = "gs://sura-clustering-raw"

PARQUET_FILES = {
    "ordenado": f"{GCS_BUCKET}/Ordenado.parquet",
    "detalle_empresa": f"{GCS_BUCKET}/Detalle_Empresa.parquet",
    "tareas_programadas": f"{GCS_BUCKET}/Tareas_Programadas_canceladas_2025.parquet",
    "tareas_prestador": f"{GCS_BUCKET}/Tareas_prestador_bloque.parquet",
}

RAW_FILES = {
    "ordenado": f"{GCS_BUCKET}/Ordenado.txt",
    "detalle_empresa": f"{GCS_BUCKET}/Detalle_Empresa.txt",
    "tareas_programadas": f"{GCS_BUCKET}/Tareas_Programadas_canceladas_2025.txt",
    "tareas_prestador": f"{GCS_BUCKET}/Tareas_prestador_bloque.xlsx",
}
