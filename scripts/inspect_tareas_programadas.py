"""Inspección de Tareas_Programadas_canceladas_2025.txt antes de limpiar.

Ejecutar:
    python scripts/inspect_tareas_programadas.py
"""

import polars as pl

FILE = "data/Tareas_Programadas_canceladas_2025.txt"

DATE_COLS = [
    "FEENTREGA_SERVICIO_INI",
    "FEENTREGA_SERVICIO_FIN",
    "FECREACION_OC",
    "FEPROGRAMACION",
    "FEINGRESO_CUMPLIMIENTO",
    "FECANCELACION",
    "FEENVIO_INFORME",
    "FEAPROBACION_INFORME",
    "FERECHAZO_INFORME",
    "FECHA_CARGA",
]

NUMERIC_COLS = [
    "NMCANTIDAD_PEDIDA",
    "NMCANTIDAD_PROGRAMADA",
    "DURACION",
    "CANTIDAD_PROGRAMADA_CITA",
    "NMCANTIDAD_EJECUTADA",
    "NMASISTENTES",
]

BOOL_COLS = [
    "SNREQUIERE_INFORME",
    "SNCANCELA_EMPRESA",
    "SNAPROBADO_AUTOMATICO",
    "SNPARCIAL",
]

CATEGORICAL_COLS = [
    "DSESTADO_PROGRAMACION",
    "DSESTADO_INFORME",
    "TIPO_PROGRAMACION",
    "CLASIFICACION",
]


def main():
    df = pl.read_csv(
        FILE, separator="\t", infer_schema_length=0, ignore_errors=True
    )

    print(f"\n{'='*60}")
    print(f"TOTAL FILAS: {len(df):,}")
    print(f"COLUMNAS:    {len(df.columns)}")
    print(f"{'='*60}\n")

    print("--- COLUMNAS ---")
    for col in df.columns:
        print(f"  {col}")

    print(f"\n--- NULOS POR COLUMNA ---")
    null_counts = df.null_count().transpose(
        include_header=True, header_name="columna", column_names=["nulos"]
    )
    tiene_nulos = null_counts.filter(pl.col("nulos") > 0)
    if len(tiene_nulos) > 0:
        print(tiene_nulos)
    else:
        print("  Sin nulos detectados.")

    print(f"\n--- MUESTRA DE FECHAS ---")
    for col in DATE_COLS:
        if col in df.columns:
            muestra = df[col].drop_nulls().head(3).to_list()
            nulos = df[col].is_null().sum()
            vacios = (df[col] == "").sum()
            print(f"  {col}:")
            print(f"    Muestra: {muestra}")
            print(f"    Nulos={nulos:,}  Vacíos={vacios:,}")

    print(f"\n--- NUMÉRICOS ---")
    for col in NUMERIC_COLS:
        if col in df.columns:
            serie = df[col].str.replace(",", ".").cast(pl.Float64, strict=False)
            print(f"  {col}:")
            print(f"    Min={serie.min()}  Max={serie.max()}  "
                  f"Ceros={(serie == 0).sum():,}  "
                  f"Negativos={(serie < 0).sum():,}  "
                  f"Nulos={serie.is_null().sum():,}")

    print(f"\n--- BOOLEANAS (valores únicos) ---")
    for col in BOOL_COLS:
        if col in df.columns:
            print(f"  {col}: {df[col].unique().sort().to_list()}")

    print(f"\n--- CATEGÓRICAS ---")
    for col in CATEGORICAL_COLS:
        if col in df.columns:
            vals = df[col].value_counts().sort("count", descending=True)
            print(f"\n  {col}:")
            print(vals)

    print(f"\n--- MOTIVO_CANCELACION ---")
    if "MOTIVO_CANCELACION" in df.columns:
        nulos = df["MOTIVO_CANCELACION"].is_null().sum()
        vacios = (df["MOTIVO_CANCELACION"] == "").sum()
        n_unicos = df["MOTIVO_CANCELACION"].n_unique()
        print(f"  Valores únicos: {n_unicos:,}")
        print(f"  Nulos:          {nulos:,}")
        print(f"  Vacíos '':      {vacios:,}")
        print(f"  Top 5 motivos:")
        print(df["MOTIVO_CANCELACION"].value_counts().sort("count", descending=True).head(5))

    print(f"\n--- DUPLICADOS ---")
    key_cols = ["NMCONSECUTIVO_ORDEN", "DNI_PRESTADOR", "FEPROGRAMACION"]
    dup_count = df.filter(df.select(key_cols).is_duplicated()).shape[0]
    print(f"  Filas duplicadas por {key_cols}: {dup_count:,}")
    exact_dup = df.filter(df.is_duplicated()).shape[0]
    print(f"  Filas exactamente duplicadas (todas las cols): {exact_dup:,}")

    print(f"\n--- PRIMERAS 3 FILAS ---")
    print(df.select(df.columns[:10]).head(3))


if __name__ == "__main__":
    main()
