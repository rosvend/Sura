"""Inspección de Detalle_Empresa.txt antes de limpiar.

Ejecutar:
    python scripts/inspect_detalle_empresa.py
"""

import polars as pl

FILE = "data/Detalle_Empresa.txt"

# Columnas numéricas según diccionario
NUMERIC_COLS = ["ID_PROFESIONAL_PPAL", "Numero_Afiliados"]

# Columnas de fecha según diccionario
DATE_COLS = ["Fecha_Inicio_Cobertura", "Fecha_Fin_Cobertura"]

# Columnas con dominio conocido (S/N u otras categorías fijas)
CATEGORICAL_COLS = [
    "ESTADO_EMPRESA_CALCULADO",
    "ESTADO_EMPRESA",
    "Ind_Multiregional",
    "Ind_Afiliada",
    "Afiliados",
    "Ruta_Atencion",
    "Segmentacion_Arl_Desc",
]


def main():
    df = pl.read_csv(FILE, separator="~", infer_schema_length=0, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"TOTAL FILAS: {len(df):,}")
    print(f"COLUMNAS:    {len(df.columns)}")
    print(f"{'='*60}\n")

    print("--- COLUMNAS Y TIPOS RAW ---")
    for col in df.columns:
        print(f"  {col}: {df[col].dtype}")

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
            muestra = df[col].drop_nulls().head(5).to_list()
            nulos = df[col].is_null().sum()
            print(f"  {col}: {muestra}  |  nulos={nulos:,}")

    print(f"\n--- MUESTRA DE NUMÉRICOS ---")
    for col in NUMERIC_COLS:
        if col in df.columns:
            serie = df[col].cast(pl.Float64, strict=False)
            print(f"  {col}:")
            print(f"    Min={serie.min()}  Max={serie.max()}  "
                  f"Ceros={(serie == 0).sum():,}  "
                  f"Negativos={(serie < 0).sum():,}  "
                  f"Nulos={serie.is_null().sum():,}")

    print(f"\n--- VALORES ÚNICOS EN CATEGÓRICAS ---")
    for col in CATEGORICAL_COLS:
        if col in df.columns:
            vals = df[col].unique().sort().to_list()
            print(f"\n  {col} ({len(vals)} únicos):")
            for v in vals:
                count = (df[col] == v).sum() if v is not None else df[col].is_null().sum()
                print(f"    '{v}': {count:,}")

    print(f"\n--- DUPLICADOS ---")
    total_dup = df.filter(df.select("Empresa_Id").is_duplicated()).shape[0]
    print(f"  Filas con Empresa_Id duplicado: {total_dup:,}")

    print(f"\n--- PRIMERAS 3 FILAS ---")
    print(df.head(3))


if __name__ == "__main__":
    main()
