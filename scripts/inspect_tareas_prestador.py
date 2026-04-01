"""Inspección del archivo Tareas_prestador_bloque.xlsx antes de limpiar.

Ejecutar:
    python scripts/inspect_tareas_prestador.py
"""

import polars as pl

FILE = "data/Tareas_prestador_bloque.xlsx"
SHEETS = ["CGR", "Red_otras_ofic", "Red_med&Cali", "Red_Bogota"]

# Columnas que nos interesan verificar su formato/valores
DATE_COLS = ["FEALTA_PRESTADOR", "FEC_INI_COS_TAR", "FEC_FIN_COS_TAR"]
NUMERIC_COLS = ["CAPACIDAD"]
BOOL_COLS = ["SNCONTROLAR_HORAS_MES"]


def inspect():
    frames = []
    for sheet in SHEETS:
        df = pl.read_excel(FILE, sheet_name=sheet, infer_schema_length=0)
        df = df.with_columns(pl.lit(sheet).alias("_RED_ORIGEN"))
        frames.append(df)

    df = pl.concat(frames, how="diagonal_relaxed")

    print(f"\n{'='*60}")
    print(f"TOTAL FILAS: {len(df):,}")
    print(f"COLUMNAS: {len(df.columns)}")
    print(f"{'='*60}\n")

    print("--- COLUMNAS Y TIPOS RAW ---")
    for col in df.columns:
        print(f"  {col}: {df[col].dtype}")

    print(f"\n--- VALORES ÚNICOS EN BOOLEANAS (S/N) ---")
    for col in BOOL_COLS:
        if col in df.columns:
            print(f"  {col}: {df[col].unique().to_list()}")

    print(f"\n--- MUESTRA DE FECHAS ---")
    for col in DATE_COLS:
        if col in df.columns:
            muestra = df[col].drop_nulls().head(5).to_list()
            nulos = df[col].is_null().sum()
            print(f"  {col}: {muestra}  |  nulos={nulos:,}")

    print(f"\n--- MUESTRA DE CAPACIDAD ---")
    for col in NUMERIC_COLS:
        if col in df.columns:
            muestra = df[col].drop_nulls().head(5).to_list()
            nulos = df[col].is_null().sum()
            print(f"  {col}: {muestra}  |  nulos={nulos:,}")

    print(f"\n--- NULOS POR COLUMNA ---")
    null_counts = df.null_count().transpose(include_header=True, header_name="columna", column_names=["nulos"])
    print(null_counts.filter(pl.col("nulos") > 0))

    print(f"\n--- DISTRIBUCIÓN POR RED ---")
    print(df["_RED_ORIGEN"].value_counts())

    print(f"\n--- PRIMERAS 3 FILAS ---")
    print(df.head(3))


if __name__ == "__main__":
    inspect()
