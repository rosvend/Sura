# BQ_DASHBOARD_CONTRACTS — Esquema de Tablas BigQuery para el Dashboard

**Para:** equipo de dashboard (JS + Power BI).
**Proyecto:** `proyecto-sura-clustering-2026`
**Dataset:** `sura_clustering_processed`
**Refresh manual:** un solo comando republica todo, ver §3.

Este doc lista cada tabla que el dashboard puede consumir, su esquema y
una query de ejemplo. Todas las tablas son **idempotentes** (sobreescritas
con `--replace` por sus pipelines), así que un refresh nunca rompe lecturas.

---

## 1. Tablas disponibles

| # | Tabla | Filas | Granularidad |
|---:|---|---:|---|
| 1 | `clustering_input` | 5,449 | una fila por prestador activo |
| 2 | `feat_prestador` | 6,514 | una fila por prestador (toda la red) |
| 3 | `feat_empresa` | 2,175,102 | una fila por empresa cliente |
| 4 | `prestador_clusters` | 5,449 | DNI_PRESTADOR → cluster_id |
| 5 | `cluster_profile` | 5 | un resumen por cluster (incluye `-1`) |
| 6 | `assignments` | 439,256 | top-1 recomendado por orden (rule_based) |
| 7 | `recommendations_top10` | 2,792,168 | top-10 por orden (rule_based) |
| 8 | `assignments_lp` | 437,571 | top-1 por orden (lp_optimized) |
| 9 | `kpis_summary` | 8 | 4 KPIs × 2 escenarios |

---

## 2. Esquemas y queries de ejemplo

### 2.1 `prestador_clusters` (el corazón del dashboard)

```
DNI_PRESTADOR                 STRING       hash de 10 chars
bloque_principal              STRING       bloque temático más frecuente del prestador
tipo_perfil                   STRING       BASICO | INTERMEDIO | ... | ESPECIALISTA | OTROS
tipo_red                      STRING       ESTRATEGICA | APOYO | COMERCIAL | ESPECIALIZADA | ...
municipio_base                STRING       municipio de la oficina principal
sector_principal_atendido     STRING       (nullable — ver MODELO_TECNICO.md §7)
segmento_principal_atendido   STRING       (nullable — idem)
etapa_predominante            STRING       TRA | IDE | MON | EVA | ...
cluster_id                    INT64        -1, 0, 1, 2, 3 (ver ARCHETYPE_NAMES en cluster_profile)
distance_to_centroid          FLOAT64      0.0 para outliers; útil para hover "qué tan típico es"
```

**Query típica:** dropdown filtrable por arquetipo.
```sql
SELECT DNI_PRESTADOR, municipio_base, tipo_perfil, distance_to_centroid
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.prestador_clusters`
WHERE cluster_id = 0
ORDER BY distance_to_centroid ASC
LIMIT 100
```

### 2.2 `cluster_profile` (texto + medianas por cluster)

```
cluster_id                    INT64
archetype_name                STRING   "Generalistas Estratégicos de Alto Volumen" etc.
n_providers                   INT64
share_of_total                FLOAT64  0.0–1.0
pct_red_estrategica           FLOAT64
pct_solo_virtual              FLOAT64
pct_sin_capacidad             FLOAT64
top_bloque                    STRING
top_tipo_perfil               STRING
top_etapa                     STRING
top_tipo_red                  STRING
median_<feature>              FLOAT64  19 columnas (una por FEATURE_COL del modelo)
```

**Query típica:** card grid del dashboard de cluster overview.
```sql
SELECT cluster_id, archetype_name, n_providers, share_of_total,
       pct_red_estrategica, top_bloque,
       median_n_citas_total, median_utilizacion_capacidad,
       median_tasa_cancela_real_prestador
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.cluster_profile`
ORDER BY n_providers DESC
```

### 2.3 `assignments` (top-1 rule_based — el "default" del dashboard)

```
dni_empresa                   STRING
codigo_tarea                  STRING
cd_municipio_destino          STRING
rank                          INT64    siempre 1 en esta tabla
dni_prestador                 STRING   el recomendado
score_total                   FLOAT64  [0, 1]
score_specialization          FLOAT64
score_capacity                FLOAT64
score_geo                     FLOAT64
score_performance             FLOAT64
cluster_id                    INT64
archetype_name                STRING
tipo_perfil                   STRING
utilizacion_capacidad         FLOAT64
nombre_distribuidor           STRING
```

**Query típica:** vista de "asignador" en el dashboard.
```sql
SELECT dni_prestador, score_total, score_specialization, score_capacity,
       score_geo, score_performance, archetype_name,
       cd_municipio_destino, tipo_perfil, nombre_distribuidor
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.assignments`
WHERE dni_empresa = '<NIT>' AND codigo_tarea = '<TAREA>'
LIMIT 1
```

### 2.4 `recommendations_top10` (top-10 con desglose)

Mismas columnas que `assignments` pero con `rank ∈ [1, 10]`.

**Query típica:** card list de top-10 con score breakdown bars.
```sql
SELECT rank, dni_prestador, score_total,
       score_specialization, score_capacity, score_geo, score_performance,
       archetype_name, tipo_perfil, utilizacion_capacidad
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.recommendations_top10`
WHERE dni_empresa = '<NIT>'
  AND codigo_tarea = '<TAREA>'
  AND cd_municipio_destino = '<MUNI>'
ORDER BY rank
```

### 2.5 `assignments_lp` (top-1 lp_optimized — alternativa balanceada)

Mismo esquema que `assignments` + columna extra:
```
scenario                      STRING   siempre "lp_optimized"
```

Útil para mostrar la diferencia con `assignments` y argumentar el trade-off
de capacidad.

### 2.6 `kpis_summary` (4 KPIs × 2 escenarios = 8 filas)

```
name                          STRING   "K1_tasa_cancelacion_esperada" | "K2_gini_carga" | "K3_costo_logistico_esperado" | "K4_match_geografico"
baseline                      FLOAT64  valor en la asignación histórica
model                         FLOAT64  valor en el escenario del modelo
delta_abs                     FLOAT64  model - baseline
delta_rel                     FLOAT64  (model - baseline) / baseline (None si baseline ≈ 0)
target                        FLOAT64  -0.15 / -0.10 / -0.05 / +0.10 según KPI
target_kind                   STRING   "relative" | "absolute"
status                        STRING   "PASS" | "FAIL"
scenario                      STRING   "rule_based" | "lp_optimized"
n_orders                      INT64    tamaño de la muestra de replay
```

**Query típica:** semáforo de KPIs en el header.
```sql
SELECT name, scenario, status,
       ROUND(baseline, 4) AS baseline,
       ROUND(model, 4)    AS model,
       ROUND(delta_rel, 3) AS delta_rel
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.kpis_summary`
ORDER BY name, scenario
```

### 2.7 Tablas de soporte: `clustering_input`, `feat_prestador`, `feat_empresa`

Estos son los **insumos crudos** del modelo. El dashboard normalmente no
los consume directamente — usa `prestador_clusters` + `assignments`. Pero
están publicados por si necesitas detalles que las tablas derivadas no
exponen.

`feat_prestador` es la más útil de las tres para drill-down: una fila por
DNI_PRESTADOR con 73 columnas (perfil + desempeño 2025 + flags).

Esquemas completos: `bq show --format=prettyjson <tabla>` para cualquier
columna específica.

---

## 3. Cómo refrescar todo

Después de un re-fit del clustering o un re-export del motor:

```bash
# Una sola corrida en orden:
PYTHONPATH=. uv run python -m src.gold.clustering_model     # ~30 s
PYTHONPATH=. uv run python -m src.assignment.exporter       # ~2 min
PYTHONPATH=. uv run python -m src.assignment.optimizer      # ~25 s
PYTHONPATH=. uv run python -m src.monitoring.kpis           # ~30 s
PYTHONPATH=. uv run python scripts/publish_to_bq.py         # ~20 s
```

Total < 5 min. Todas las tablas quedan consistentes con el mismo
artefacto del modelo (`models/{model,scaler,pca,iforest,remap}.joblib`
en GCS).

Si sólo cambia el clustering, basta con re-correr todos los pasos.
Si sólo cambia el scoring (pesos), basta exporter + optimizer + kpis.

---

## 4. Convenciones y caveats

- **Hashing:** `DNI_PRESTADOR` y `dni_empresa` son hashes de 10 chars. No
  intentar joinear contra `feat_empresa.Empresa_Id` (es el NIT crudo,
  hash incompatible). Si necesitas atributos de empresa para el
  dashboard, usa `Macrosegmentacion_Desc` desde Ordenado o desde
  `recommendations_top10` (donde quedó embebido).
- **Munis con `.0`:** las órdenes nuevas del frontend deben pasar el
  `Municipio_Entrega_Id` como string (no float). El scorer normaliza
  `"4959.0" → "4959"` automáticamente.
- **`cluster_id = -1`:** prestadores que el motor enruta a revisión
  manual. El dashboard puede mostrarlos como tag "EXCEPCIÓN" en lugar
  de un arquetipo.
- **Timezone:** todas las fechas en BQ están como DATE (sin tz).
- **Particionado:** ninguna tabla está particionada (volumen pequeño,
  full-scan es rápido). Si en producción esto crece, considerar
  particionar `recommendations_top10` por `codigo_tarea` o
  `cd_municipio_destino`.

---

## 5. Contacto

- **Pipeline / scoring:** roy@sura-team (este repo).
- **Clustering alternativo (VAE+HDBSCAN):** teammate-X, parquet aún no
  publicado; cuando llegue lo publicamos como
  `sura_clustering_processed.prestador_clusters_vae` y exponemos
  comparación side-by-side en `kpis_summary` con `scenario =
  "vae_hdbscan"`.
