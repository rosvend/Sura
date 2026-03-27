import gcsfs
import time
from src.ingestion.extract import load_data

files = {
    "gs://sura-clustering-raw/Ordenado.txt": "gs://sura-clustering-raw/Ordenado.parquet",
    "gs://sura-clustering-raw/Detalle_Empresa.txt": "gs://sura-clustering-raw/Detalle_Empresa.parquet",
    "gs://sura-clustering-raw/Tareas_Programadas_canceladas_2025.txt": "gs://sura-clustering-raw/Tareas_Programadas_canceladas_2025.parquet",
    "gs://sura-clustering-raw/Tareas_prestador_bloque.xlsx": "gs://sura-clustering-raw/Tareas_prestador_bloque.parquet",
}

fs = gcsfs.GCSFileSystem()

for src, dst in files.items():
    try:
        if fs.exists(dst):
            print(f"  ✓ {dst} already exists, skipping.")
            continue
        start = time.time()
        print(f"Processing {src}...")
        df = load_data(src)
        with fs.open(dst, "wb") as f:
            df.write_parquet(f)
        elapsed = time.time() - start
        print(f"  ✓ Saved to {dst} — {df.shape[0]:,} rows, {df.shape[1]} cols ({elapsed:.1f}s)\n")
    except Exception as e:
        print(f"  ✗ Error processing {src}: {e}\n")