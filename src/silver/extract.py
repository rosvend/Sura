"""Silver layer data loading.

Usage:
    from src.silver.extract import load_ordenado, load_empresas

Each function returns a Polars LazyFrame. Chain .select(), .filter(), then .collect().
"""

import polars as pl

from src.config import PARQUET_FILES

_DATE_COLS_STANDARD = [
    "FEALTA_PRESTADOR",       # Registro del prestador
    "FEC_FIN_COS_TAR",        # Fin vigencia tarifa (valor '3000-12-30' = sin vencimiento)
    "FEALTA_TAREA_PRESTADOR", # Alta de la tarea para el prestador
    "FEALTA_DIST",            # Alta del distribuidor
    "FEVALIDACION",           # Fecha de validación (57% nulo)
    "FECHA_CARGA",            # Fecha de carga del registro
]

# Fecha con formato ISO 8601: '2022-08-02T00:00:00.000Z'
_DATE_COLS_ISO = [
    "FEC_INI_COS_TAR",  # Inicio vigencia tarifa (98.6% nulo)
]

# Columnas booleanas S/N
_BOOL_COLS = ["SNCONTROLAR_HORAS_MES", "SNVALIDADO"]

# Columnas numéricas (puntajes y capacidad)
_NUMERIC_COLS = ["CAPACIDAD", "PTCALIFICACION", "PTVALOR_TAREA"]


def load_ordenado() -> pl.LazyFrame:
    """Purchase orders (607K rows, 100 cols)."""
    return pl.scan_parquet(PARQUET_FILES["ordenado"])


def load_empresas() -> pl.LazyFrame:
    """Maestro de empresas clientes (Silver, limpio).

    Transformaciones aplicadas:
    - Strings: espacios extra eliminados, cadenas vacías a null
    - Fecha_Inicio_Cobertura, Fecha_Fin_Cobertura a Date
      (Fecha_Fin_Cobertura = 3000-12-31 es centinela "sin vencimiento", se mantiene)
    - ID_PROFESIONAL_PPAL a Int64 + FLAG_SIN_PROFESIONAL (-1 = sin asignar)
    - Numero_Afiliados a Int64 (0 es válido, representa empresa sin afiliados activos)
    - ESTADO_EMPRESA_CALCULADO: 'Activa' → True / 'Inactiva' → False
    - Ind_Multiregional: 'S' → True / 'N' → False
    - Afiliados: 'Con Afiliados' → True / 'Sin Afiliados' → False
    """
    return _clean_empresas(
        pl.scan_parquet(PARQUET_FILES["detalle_empresa"])
    )


def _clean_empresas(df: pl.LazyFrame) -> pl.LazyFrame:
    """Limpieza Silver para Detalle_Empresa."""
    return (
        df
        # 1. Normalizar strings: quitar espacios extremos y convertir vacíos a null
        .with_columns(
            pl.when(pl.col(pl.String).str.strip_chars() == "")
            .then(None)
            .otherwise(pl.col(pl.String).str.strip_chars())
            .name.keep()
        )
        # 2. Fechas formato 'YYYY-MM-DD' a Date
        .with_columns(
            pl.col("Fecha_Inicio_Cobertura").str.to_date(format="%Y-%m-%d", strict=False),
            pl.col("Fecha_Fin_Cobertura").str.to_date(format="%Y-%m-%d", strict=False),
        )
        # 3. ID_PROFESIONAL_PPAL a Int64
        #    -1 es centinela "sin profesional asignado" (349,211 registros)
        .with_columns(
            pl.col("ID_PROFESIONAL_PPAL").cast(pl.Int64, strict=False)
        )
        .with_columns(
            (pl.col("ID_PROFESIONAL_PPAL") == -1).alias("FLAG_SIN_PROFESIONAL")
        )
        # 4. Numero_Afiliados a Int64 (0 es válido: empresa sin afiliados activos)
        .with_columns(
            pl.col("Numero_Afiliados").cast(pl.Int64, strict=False)
        )
        # 5. Booleanos
        .with_columns(
            (pl.col("ESTADO_EMPRESA_CALCULADO") == "Activa").alias("ESTADO_EMPRESA_CALCULADO"),
            (pl.col("Ind_Multiregional") == "S").alias("Ind_Multiregional"),
            (pl.col("Afiliados") == "Con Afiliados").alias("Afiliados"),
        )
    )


def load_tareas_programadas() -> pl.LazyFrame:
    """Scheduled tasks & cancellations (1.5M rows, 62 cols)."""
    return pl.scan_parquet(PARQUET_FILES["tareas_programadas"])


def load_tareas_prestador() -> pl.LazyFrame:
    """Catálogo de capacidades de prestadores (Silver, limpio).

    Transformaciones aplicadas:
    - Strings: espacios extra eliminados, cadenas vacías a null
    - Fechas estándar ('YYYY-MM-DD HH:MM:SS') a Date (sin componente de hora)
    - FEC_INI_COS_TAR (ISO 8601 'YYYY-MM-DDTHH:MM:SS.mmmZ') a Date
    - CAPACIDAD, PTCALIFICACION, PTVALOR_TAREA a Float64
    - SNCONTROLAR_HORAS_MES, SNVALIDADO: 'S' → True / 'N' → False a Boolean
    """
    return _clean_tareas_prestador(
        pl.scan_parquet(PARQUET_FILES["tareas_prestador"])
    )


def _clean_tareas_prestador(df: pl.LazyFrame) -> pl.LazyFrame:
    """Limpieza Silver para Tareas_prestador_bloque."""
    return (
        df
        # 1. Normalizar strings: quitar espacios extremos y convertir vacíos a null
        .with_columns(
            pl.when(pl.col(pl.String).str.strip_chars() == "")
            .then(None)
            .otherwise(pl.col(pl.String).str.strip_chars())
            .name.keep()
        )
        # 2. Fechas formato estándar 'YYYY-MM-DD HH:MM:SS' a solo Date
        #    strict=False devuelve null si no puede parsear, sin romper el pipeline
        .with_columns([
            pl.col(col)
            .str.to_datetime(format="%Y-%m-%d %H:%M:%S", strict=False)
            .cast(pl.Date)
            .alias(col)
            for col in _DATE_COLS_STANDARD
        ])
        # 3. FEC_INI_COS_TAR: formato ISO 8601 'YYYY-MM-DDTHH:MM:SS.mmmZ' a Date
        #    Se extrae solo la parte de fecha (primeros 10 chars) antes de parsear
        #    para evitar conflictos con la zona horaria Z (UTC)
        .with_columns([
            pl.col(col)
            .str.slice(0, 10)
            .str.to_date(format="%Y-%m-%d", strict=False)
            .alias(col)
            for col in _DATE_COLS_ISO
        ])
        # 4. Columnas numéricas a Float64
        .with_columns([
            pl.col(col).cast(pl.Float64, strict=False)
            for col in _NUMERIC_COLS
        ])
        # 5. Columnas booleanas: 'S' → True, cualquier otro valor → False
        .with_columns([
            (pl.col(col) == "S").alias(col)
            for col in _BOOL_COLS
        ])
        # 6. Eliminar los 148 registros sin municipio: no ubicables geográficamente,
        #    inutilizables para clustering. Representan el 0.005% del total.
        .filter(pl.col("CDMUNICIPIO").is_not_null())
        # 7. Eliminar duplicados exactos.
        #    Se hace después de normalizar strings para que "ASESOR " y "ASESOR"
        #    cuenten como duplicados correctamente.
        .unique(maintain_order=False)
        # 8. Flag para prestadores habilitados pero sin capacidad disponible.
        #    28,279 filas con CAPACIDAD=0 (1% del total). Se conservan porque
        #    el prestador existe y puede recuperar capacidad; el flag permite
        #    filtrarlos en análisis posteriores.
        .with_columns(
            (pl.col("CAPACIDAD") == 0.0).alias("FLAG_CAPACIDAD_CERO")
        )
    )
