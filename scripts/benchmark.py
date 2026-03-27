import polars as pl
import pandas as pd
import gcsfs
import time
import io
from src.ingestion.extract import load_data
from google.cloud import bigquery

RESULTS = []

def bench(label: str, fn):
    print(f"Running: {label}...")
    start = time.time()
    result = fn()
    elapsed = time.time() - start
    if hasattr(result, "shape"):
        shape = result.shape
        print(f"  ✓ {elapsed:.2f}s — {shape[0]:,} rows, {shape[1]} cols\n")
    else:
        print(f"  ✓ {elapsed:.2f}s — result: {result}\n")  # for BQ ingest (returns row count)
    RESULTS.append({"approach": label, "seconds": round(elapsed, 2)})
    return result

#  1. Pandas local
bench("1. pandas - local txt",
    lambda: pd.read_csv("data/Ordenado.txt", sep="\t", encoding="latin-1",
                        low_memory=False, dtype=str))

#  2. Pandas GCS
def _pandas_gcs():
    fs = gcsfs.GCSFileSystem()
    with fs.open("gs://sura-clustering-raw/Ordenado.txt", "rb") as f:
        return pd.read_csv(f, sep="\t", encoding="latin-1",
                           low_memory=False, dtype=str)

bench("2. pandas - GCS txt", _pandas_gcs)

#  3. Polars local
bench("3. polars - local txt",
    lambda: pl.read_csv("data/Ordenado.txt", separator="\t", encoding="latin-1",
                        infer_schema_length=0, ignore_errors=True))

#  4. Polars GCS (raw txt)
bench("4. polars - GCS txt",
    lambda: load_data("gs://sura-clustering-raw/Ordenado.txt"))

#  5a. Polars parquet GCS - full collect
bench("5a. polars - GCS parquet (full)",
    lambda: pl.scan_parquet("gs://sura-clustering-raw/Ordenado.parquet").collect())

#  5b. Polars parquet GCS - lazy (5 cols only) 
bench("5b. polars - GCS parquet (lazy, 5 cols)",
    lambda: (
        pl.scan_parquet("gs://sura-clustering-raw/Ordenado.parquet")
          .select([
              "Ord_Plan_Vers_Act_Id",
              "Numero_Consecutivo_Orden",
              "Numero_Consecutivo_Plan",
              "Dni_Prestador_Externo",
              "Nombre_Prestador_Externo"
          ])
          .collect()
    ))

#  6. BigQuery External Table (Athena-Style) 
def _bq_athena_style(query_string):
    client = bigquery.Client()
    
    # 1. Define the GCS Parquet file as an external data source
    external_config = bigquery.ExternalConfig("PARQUET")
    external_config.source_uris = ["gs://sura-clustering-raw/Ordenado.parquet"]
    
    # 2. Map the external config to a temporary table name
    job_config = bigquery.QueryJobConfig(
        table_definitions={"ordenado_gcs": external_config}
    )
    
    # 3. Run the query directly against the bucket
    return client.query(query_string, job_config=job_config).to_arrow(create_bqstorage_client=True)

#  6a. BigQuery External - full collect 
bench("6a. BigQuery External - GCS parquet (full)", 
      lambda: _bq_athena_style("SELECT * FROM ordenado_gcs"))

#  6b. BigQuery External - subset (5 cols)
bench("6b. BigQuery External - GCS parquet (lazy, 5 cols)", 
      lambda: _bq_athena_style("""
          SELECT 
            Ord_Plan_Vers_Act_Id,
            Numero_Consecutivo_Orden,
            Numero_Consecutivo_Plan,
            Dni_Prestador_Externo,
            Nombre_Prestador_Externo
          FROM ordenado_gcs
      """))

print("\n Benchmark Summary (approaches sorted by time):")
for r in sorted(RESULTS, key=lambda x: x["seconds"]):
    bar = "█" * int(r["seconds"] / 5)
    print(f"  {r['approach']:<45} {r['seconds']:>8.2f}s  {bar}")