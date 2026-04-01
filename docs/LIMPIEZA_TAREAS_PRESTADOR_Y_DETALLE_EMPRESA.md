# Limpieza Silver: Tareas_prestador_bloque.xlsx y Detalle_Empresa.txt

Este documento describe el proceso de limpieza de datos aplicado en la capa Silver para los archivos `Tareas_prestador_bloque.xlsx` y `Detalle_Empresa.txt`.

**Fecha:** 2026-03-31
**Archivos modificados:** `src/ingestion/extract.py`, `src/silver/extract.py`

---

## Corrección previa en ingesta Bronze

Antes de la limpieza Silver, se identificó un bug crítico en `src/ingestion/extract.py`.

### Problema

`pl.read_excel()` sin parámetros lee únicamente la **primera hoja** de un archivo Excel. El archivo `Tareas_prestador_bloque.xlsx` tiene 4 hojas (redes regionales). El parquet en GCS solo tenía los datos de CGR (~663K filas), ignorando el 76% restante.

### Solución

Se creó la función `_read_all_sheets()` que:

1. Usa `openpyxl` para obtener los nombres de todas las hojas
2. Lee cada hoja con `infer_schema_length=0` (todo String, consistente con Bronze)
3. Agrega la columna `_RED_ORIGEN` con el nombre de la hoja de origen
4. Concatena todas las hojas en un único DataFrame

```python
def _read_all_sheets(source: "io.BytesIO | Path") -> pl.DataFrame:
    import openpyxl
    if isinstance(source, io.BytesIO):
        raw = source.getvalue()
        get_source = lambda: io.BytesIO(raw)
    else:
        get_source = lambda: source

    wb = openpyxl.load_workbook(get_source(), read_only=True)
    sheet_names = wb.sheetnames
    wb.close()

    frames = []
    for sheet in sheet_names:
        df = pl.read_excel(get_source(), sheet_name=sheet, infer_schema_length=0)
        df = df.with_columns(pl.lit(sheet).alias("_RED_ORIGEN"))
        frames.append(df)
    return pl.concat(frames, how="diagonal_relaxed")
```

### ¿Por qué se agrega `_RED_ORIGEN`?

Cada hoja representa una red regional distinta (CGR, Red_otras_ofic, Red_med&Cali, Red_Bogota). Al concatenar las 4 hojas se pierde esa información. `_RED_ORIGEN` la preserva para que en análisis posteriores se pueda segmentar por red.

### Resultado

El parquet en GCS fue regenerado con las 4 redes: **2,812,076 filas** (antes: ~663,503).

---

## Archivo 1: `Tareas_prestador_bloque.xlsx`

**Función Silver:** `load_tareas_prestador()` en `src/silver/extract.py`

**Dimensiones originales:** 2,812,076 filas × 38 columnas (4 hojas concatenadas)

### Hallazgos de la inspección

Se ejecutaron dos scripts de inspección antes de escribir el código de limpieza:

| Hallazgo                | Detalle                                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Formato de fechas       | `'2017-10-02 19:00:00'` (con hora UTC) para la mayoría; `'2022-08-02T00:00:00.000Z'` (ISO 8601) para `FEC_INI_COS_TAR` |
| `FEC_FIN_COS_TAR`       | Valor `'3000-12-30'` es centinela "sin vencimiento" — se mantiene                                                      |
| `FEC_INI_COS_TAR`       | 98.6% nulo (2,774,087 de 2,812,076) — esperado, se mantiene                                                            |
| `FEVALIDACION`          | 57% nulo (1,605,253) — esperado, se mantiene                                                                           |
| `CAPACIDAD`             | Sin nulos, rango 0–240 horas, promedio 183.93                                                                          |
| `CAPACIDAD = 0`         | 28,279 filas (1%) — prestadores habilitados sin horas disponibles                                                      |
| 148 nulos críticos      | Mismos 148 registros sin `CDMUNICIPIO`, `NOMBRE_PRESTADOR` y `CDMUNICIPIO_ORIGEN_OC` simultáneamente                   |
| Duplicados              | 71 filas exactamente idénticas en todas las columnas                                                                   |
| `PERFIL_TARIFA`         | 8 valores encontrados vs 4 documentados (A, B, I, X). Valores E, O, P, T son extensiones no documentadas pero válidas  |
| `TIPO_DE_RED`           | 7 valores encontrados vs 1 documentado. El diccionario estaba desactualizado                                           |
| `SNCONTROLAR_HORAS_MES` | Confirmado solo `'S'` y `'N'`                                                                                          |

### Transformaciones aplicadas

#### 1. Normalización de Strings

#### 2. Parseo de fechas estándar a `Date`

**Columnas:** `FEALTA_PRESTADOR`, `FEC_FIN_COS_TAR`, `FEALTA_TAREA_PRESTADOR`, `FEALTA_DIST`, `FEVALIDACION`, `FECHA_CARGA`

**Nota:** `strict=False` permite que fechas mal formadas devuelvan `null` en lugar de romper el pipeline.

#### 3. Parseo de `FEC_INI_COS_TAR` a `Date`

Convierte `'2022-08-02T00:00:00.000Z'` a tipo `Date`.

Este campo tiene formato ISO 8601 con zona horaria explícita (`Z` = UTC), diferente al resto. Polars no permite `format=None` cuando hay timezone en los datos. Para este campo se decicó extraer los primeros 10 caracteres (`'2022-08-02'`) y parsear como `%Y-%m-%d`.

#### 4. Columnas numéricas a `Float64`

**Columnas:** `CAPACIDAD`, `PTCALIFICACION`, `PTVALOR_TAREA`

#### 5. Columnas booleanas a `Boolean`

**Columnas:** `SNCONTROLAR_HORAS_MES`, `SNVALIDADO`

#### 6. Eliminación de 148 registros sin municipio

Se filtraron y eliminaron las 148 filas donde `CDMUNICIPIO` era `null`.

**Por qué:** Los mismos 148 registros tenían `null` simultáneamente en `CDMUNICIPIO`, `NOMBRE_PRESTADOR` y `CDMUNICIPIO_ORIGEN_OC`. Sin municipio no es posible ubicar geográficamente al prestador, lo que los hace inutilizables para el modelo de clustering que requiere cobertura geográfica. Representan el 0.005% del total — impacto mínimo.

#### 7. Eliminación de 71 duplicados exactos

Se eliminaron filas donde todas las columnas eran idénticas usando `.unique()`.

**Por qué:** Son registros repetidos sin ninguna información adicional. Contaminarían conteos, promedios y el entrenamiento del modelo. Se aplica **después** de normalizar strings para que `"ASESOR "` y `"ASESOR"` cuenten como duplicados correctamente.

#### 8. Columna nueva: `FLAG_CAPACIDAD_CERO`

Columna `Boolean` que marca `True` cuando `CAPACIDAD == 0`.

**Por qué:** 28,279 prestadores (1%) tienen capacidad cero — están habilitados para ejecutar tareas pero sin horas disponibles en el periodo. No se eliminan porque pueden recuperar capacidad. El flag permite filtrarlos o incluirlos según el análisis.

### Resultado final

| Métrica                            | Valor                     |
| ---------------------------------- | ------------------------- |
| Filas originales (4 hojas)         | 2,812,076                 |
| Eliminadas por nulo en CDMUNICIPIO | 148                       |
| Eliminadas por duplicado exacto    | 71                        |
| **Filas finales**                  | **2,811,857**             |
| Columnas originales                | 38                        |
| Columnas agregadas                 | 1 (`FLAG_CAPACIDAD_CERO`) |
| **Columnas finales**               | **39**                    |

---

## Archivo 2: `Detalle_Empresa.txt`

**Función Silver:** `load_empresas()` en `src/silver/extract.py`

**Dimensiones originales:** 2,175,102 filas × 16 columnas

### Hallazgos de la inspección

| Hallazgo                   | Detalle                                                                  |
| -------------------------- | ------------------------------------------------------------------------ |
| Nulos                      | Ninguno en ninguna columna                                               |
| Duplicados                 | Ninguno en `Empresa_Id`                                                  |
| Formato de fechas          | `'2015-11-20'` — solo fecha, sin componente de hora                      |
| `Fecha_Fin_Cobertura`      | Valor `'3000-12-31'` es centinela "sin vencimiento" — se mantiene        |
| `ID_PROFESIONAL_PPAL`      | Min=-1, 349,211 negativos. `-1` es centinela "sin profesional asignado"  |
| `Numero_Afiliados`         | 1,526,105 ceros (70%). Coincide exactamente con "Sin Afiliados" — válido |
| `ESTADO_EMPRESA_CALCULADO` | Solo `'Activa'` e `'Inactiva'`                                           |
| `Ind_Multiregional`        | Solo `'S'` y `'N'`                                                       |
| `Ind_Afiliada`             | Tres valores: `'C'` (Cotizante), `'E'` (Empresa), `'V'` (Voluntario)     |
| `Afiliados`                | Solo `'Con Afiliados'` y `'Sin Afiliados'`                               |
| `Ruta_Atencion`            | 6 valores, todos coinciden con el diccionario                            |
| `Segmentacion_Arl_Desc`    | 10 valores, todos coinciden con el diccionario                           |

### Transformaciones aplicadas

#### 1. Normalización de Strings

#### 2. Parseo de fechas a `Date`

**Columnas:** `Fecha_Inicio_Cobertura`, `Fecha_Fin_Cobertura`

**Nota:** El valor `'3000-12-31'` en `Fecha_Fin_Cobertura` es un centinela que indica "sin fecha de vencimiento" — se mantiene intencionalmente.

#### 3. `ID_PROFESIONAL_PPAL` a `Int64`

#### 4. Columna nueva: `FLAG_SIN_PROFESIONAL`

Columna `Boolean` que marca `True` cuando `ID_PROFESIONAL_PPAL == -1`.

**Por qué:** El valor `-1` es un centinela que representa "empresa sin profesional principal asignado" (349,211 registros, 16% del total). No se elimina el registro porque la empresa existe — el flag permite identificar estas empresas en análisis de asignación de recursos.

#### 5. `Numero_Afiliados` a `Int64`

**Nota:** Los 1,526,105 ceros son válidos y representan empresas actualmente sin afiliados (coincide exactamente con la columna `Afiliados = 'Sin Afiliados'`).

#### 6. Columnas booleanas a `Boolean`

**Columnas y conversiones:**

- `ESTADO_EMPRESA_CALCULADO`: `'Activa'` → `True`, `'Inactiva'` → `False`
- `Ind_Multiregional`: `'S'` → `True`, `'N'` → `False`
- `Afiliados`: `'Con Afiliados'` → `True`, `'Sin Afiliados'` → `False`

**Nota:** `Ind_Afiliada` tiene 3 valores (`C`, `E`, `V`) — no es binaria, se mantiene como `String`.

### Resultado final

| Métrica              | Valor                                |
| -------------------- | ------------------------------------ |
| Filas originales     | 2,175,102                            |
| Filas eliminadas     | 0 (sin nulos críticos ni duplicados) |
| **Filas finales**    | **2,175,102**                        |
| Columnas originales  | 16                                   |
| Columnas agregadas   | 1 (`FLAG_SIN_PROFESIONAL`)           |
| **Columnas finales** | **17**                               |

---

## Ubicación de los datos limpios

Los datos limpios están materializados en **BigQuery** en el dataset `sura_clustering_cleaned`, así:

| Tabla              | Filas     | Columnas | Ruta                                                                     |
| ------------------ | --------- | -------- | ------------------------------------------------------------------------ |
| `tareas_prestador` | 2,811,857 | 39       | `proyecto-sura-clustering-2026.sura_clustering_cleaned.tareas_prestador` |
| `detalle_empresa`  | 2,175,102 | 17       | `proyecto-sura-clustering-2026.sura_clustering_cleaned.detalle_empresa`  |

Los parquets en GCS (`gs://sura-clustering-raw/`) son la capa **Bronze** y no fueron modificados por la limpieza, excepto `Tareas_prestador_bloque.parquet` que fue regenerado para incluir las 4 hojas.

Para consultar los datos limpios desde Python:

```python
from src.silver.extract import load_tareas_prestador, load_empresas

df_prestador = load_tareas_prestador().collect()  # lee GCS + aplica limpieza en memoria
df_empresas  = load_empresas().collect()          # lee GCS + aplica limpieza en memoria
```

Para consultar directamente desde BigQuery (SQL):

```sql
SELECT * FROM `proyecto-sura-clustering-2026.sura_clustering_cleaned.tareas_prestador` LIMIT 10;
SELECT * FROM `proyecto-sura-clustering-2026.sura_clustering_cleaned.detalle_empresa` LIMIT 10;
```

---

## Resumen de archivos modificados

| Archivo                    | Tipo de cambio    | Razón                                                                                                                                                                                                                 |
| -------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/ingestion/extract.py` | Corrección de bug | `pl.read_excel()` solo leía la primera hoja del Excel. Se reemplazó por `_read_all_sheets()` que lee todas las hojas y agrega `_RED_ORIGEN`.                                                                          |
| `src/silver/extract.py`    | Funciones nuevas  | Se agregaron `_clean_tareas_prestador()` y `_clean_empresas()` con todas las transformaciones descritas. Las funciones `load_tareas_prestador()` y `load_empresas()` ahora invocan estas funciones antes de retornar. |

## Archivos NO Modificados

| Archivo                                                     | Razón                                                                                    |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Parquets en GCS (excepto `Tareas_prestador_bloque.parquet`) | Los parquets son Bronze — la limpieza ocurre en memoria en Silver, no modifica la fuente |

---

## Cómo usar los datos limpios

```python
from src.silver.extract import load_tareas_prestador, load_empresas

# Tareas prestador — limpio y tipado
df_prestador = load_tareas_prestador().collect()

# Solo prestadores con capacidad disponible
df_activos = (
    load_tareas_prestador()
    .filter(~pl.col("FLAG_CAPACIDAD_CERO"))
    .collect()
)

# Empresas — limpio y tipado
df_empresas = load_empresas().collect()

# Solo empresas activas con afiliados
df_activas = (
    load_empresas()
    .filter(pl.col("ESTADO_EMPRESA_CALCULADO") & pl.col("Afiliados"))
    .collect()
)
```
