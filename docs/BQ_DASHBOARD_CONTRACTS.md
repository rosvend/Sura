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
| 8 | `assignments_enriched` | 439,256 | igual que 6 + top_contributor + 4 shares |
| 9 | `recommendations_top10_enriched` | 2,792,168 | igual que 7 + top_contributor + 4 shares |
| 10 | `assignments_lp` | 437,571 | top-1 por orden (lp_optimized) |
| 11 | `kpis_summary` | 8 | 4 KPIs × 2 escenarios |
| 12 | `kpi_saturacion_cluster` | 4–8 | 1 fila por (cluster × escenario) — ISC + semáforo + prestadores_necesarios |
| 13 | `kpi_scenario_diff` | 1 | métricas globales del trade-off rule_based ↔ lp_optimized |
| 14 | `kpi_scenario_diff_by_cluster` | 4 | mismo trade-off pivoteado por cluster_id_rb |

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

### 2.5 `assignments_enriched` y `recommendations_top10_enriched`

Versiones enriquecidas de las tablas 2.3 y 2.4, producidas por
`scripts/enrich_assignments.py`. Mismas columnas base, más 5 adicionales:

```
top_contributor    STRING    componente con mayor contribución ponderada al score_total
                             Valores: "Especialización" | "Capacidad" | "Geográfico" | "Desempeño"
                             Fórmula: argmax(W_SPEC×score_spec, W_CAP×score_cap,
                                            W_GEO×score_geo, W_PERF×score_perf)
                             Ejemplo: "Especialización"
                             Power BI: etiqueta de tooltip "¿Por qué este prestador?"

spec_share         FLOAT64   fracción del score_total aportada por especialización
                             Fórmula: (0.45 × score_specialization) / score_total
                             Rango: [0, 1] · Null si score_total = 0
                             Ejemplo: 0.52
                             Power BI: barra de progreso en tooltip (ancho = spec_share × 100%)

cap_share          FLOAT64   fracción aportada por capacidad
                             Fórmula: (0.30 × score_capacity) / score_total
                             Ejemplo: 0.28
                             Power BI: barra de progreso secundaria

geo_share          FLOAT64   fracción aportada por cobertura geográfica
                             Fórmula: (0.15 × score_geo) / score_total
                             Ejemplo: 0.14
                             Power BI: indicador de match geográfico en tooltip

perf_share         FLOAT64   fracción aportada por desempeño operativo
                             Fórmula: (0.10 × score_performance) / score_total
                             Ejemplo: 0.06
                             Power BI: barra complementaria; spec+cap+geo+perf = 1.0
```

Las cuatro shares suman 1.0 por construcción. Las tablas originales
(`assignments`, `recommendations_top10`) no se modifican — estas son
tablas adicionales que se pueden unir por `(dni_empresa, codigo_tarea,
cd_municipio_destino, rank)`.

**Query típica:** tooltip de drill-through "¿por qué este prestador?".
```sql
SELECT r.rank, r.dni_prestador, r.score_total,
       r.top_contributor,
       ROUND(r.spec_share, 2) AS pct_especializacion,
       ROUND(r.cap_share,  2) AS pct_capacidad,
       ROUND(r.geo_share,  2) AS pct_geografico,
       ROUND(r.perf_share, 2) AS pct_desempeno,
       r.archetype_name, r.tipo_perfil
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.recommendations_top10_enriched` r
WHERE r.dni_empresa = '<NIT>'
  AND r.codigo_tarea = '<TAREA>'
  AND r.cd_municipio_destino = '<MUNI>'
ORDER BY r.rank
```

**Cómo actualizar:** `PYTHONPATH=. uv run python scripts/enrich_assignments.py`
(requiere que `assignments.parquet` y `recommendations_top10.parquet` en GCS
estén frescos — correr después de `exporter.py`).

---

### 2.6 `assignments_lp` (top-1 lp_optimized — alternativa balanceada)

Mismo esquema que `assignments` + columna extra:
```
scenario                      STRING   siempre "lp_optimized"
```

Útil para mostrar la diferencia con `assignments` y argumentar el trade-off
de capacidad.

### 2.7 `kpis_summary` (4 KPIs × 2 escenarios = 8 filas)

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

### 2.8 `kpi_saturacion_cluster` (ISC por cluster × escenario)

Métrica post-hoc de presión operativa por cluster. **Independiente** de
`kpis_summary` — su esquema (per-cluster) no es compatible con la forma
"1 fila por (KPI × escenario)" de aquella tabla, así que vive aparte.
Las páginas del dashboard que ya leen `kpis_summary` no se ven afectadas.

```
cluster_id            INT64    join key con prestador_clusters / cluster_profile
archetype_name        STRING   "Generalistas Estratégicos…" etc. (ARCHETYPE_NAMES)
scenario              STRING   "rule_based" | "lp_optimized"
n_providers           INT64    prestadores activos en el cluster (excluye sin_capacidad)
median_capacidad      FLOAT64  mediana de capacidad intra-cluster
capacidad_estimada    FLOAT64  n_providers * median_capacidad
tareas_asignadas      INT64    # filas en assignments(_lp) con ese cluster_id
isc                   FLOAT64  tareas_asignadas / capacidad_estimada
estado_saturacion     STRING   "Normal (Verde)"  ISC ≤ 0.85
                               "Alerta (Amarillo)"  0.85 < ISC ≤ 1.0
                               "Crítico (Rojo)"  ISC > 1.0
prestadores_necesarios INT64   # prestadores adicionales que llevarían el cluster
                               a ISC = 1.0 manteniendo la mediana de capacidad
                               actual. 0 para clusters Verde/Amarillo.
                               Fórmula: ceil(tareas / median_capacidad) - n_providers
                               cuando ISC > 1.0, else 0.
computed_at           TIMESTAMP UTC en el momento del refresh — pill de freshness
```

**Cluster `-1`** se excluye por construcción (exporter.py ya lo filtra; no
aparece en `assignments`/`assignments_lp` y no tiene capacidad agregable).

**Query típica:** matriz semáforo cluster × escenario.
```sql
SELECT cluster_id, archetype_name, scenario,
       ROUND(isc, 3) AS isc, estado_saturacion,
       tareas_asignadas, ROUND(capacidad_estimada, 0) AS capacidad_estimada
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.kpi_saturacion_cluster`
ORDER BY scenario, cluster_id
```

**Refresh:** `PYTHONPATH=. uv run python scripts/compute_isc.py` (segundos,
puramente post-hoc — no recalcula ni el clustering ni el scoring).

**Visual sugerido en Power BI:** gauge por cluster con color condicional
sobre `estado_saturacion`, o matriz heatmap `cluster_id × scenario` con
`isc` como valor. Complementa K2 (Gini global de carga) abriéndola por
arquetipo, lo que permite ver si `lp_optimized` redistribuye mejor que
`rule_based` a nivel cluster.

### 2.9 `kpi_scenario_diff` (trade-off rule_based ↔ lp_optimized · global)

Cuantifica QUÉ cambia LP frente a rule_based, sobre el universo de órdenes
en ambas asignaciones (inner-join). Una sola fila. Independiente de
`kpis_summary` — su granularidad es "una corrida de comparación", no
"un KPI con baseline/model".

```
n_orders_compared              INT64    inner-join sobre (empresa, tarea, muni)
n_orders_only_in_rule_based    INT64    órdenes RB que LP no logró fittear bajo cap (overflow)
n_reassigned                   INT64    filas donde dni_prestador_rb != dni_prestador_lp
pct_reassigned                 FLOAT64  n_reassigned / n_orders_compared
gini_load_rule_based           FLOAT64  Gini de # órdenes por prestador (RB)
gini_load_lp_optimized         FLOAT64  Gini de # órdenes por prestador (LP)
gini_delta_abs                 FLOAT64  gini_lp - gini_rb (negativo = LP más equitativo)
gini_delta_rel                 FLOAT64  delta relativo
score_total_mean_rule_based    FLOAT64  promedio score_total RB
score_total_mean_lp_optimized  FLOAT64  promedio score_total LP
score_delta_mean               FLOAT64  mean(score_lp - score_rb) (negativo = LP cede calidad)
score_delta_p25/p50/p75        FLOAT64  distribución del delta de score
costo_log_mean_rule_based      FLOAT64  costo_logistico_prom promedio del prestador asignado RB
costo_log_mean_lp_optimized    FLOAT64  idem LP
costo_log_delta_abs            FLOAT64  lp - rb (negativo = LP más barato/orden)
cost_savings_annual_cop        FLOAT64  costo_log_delta_abs * n_orders_compared
                                        (SIGNO PRESERVADO — puede ser negativo)
n_costo_log_null_rb            INT64    nulls en el lookup de costo (transparencia)
n_costo_log_null_lp            INT64    idem
computed_at                    TIMESTAMP UTC
```

**Visual sugerido en Power BI:** 4 cards en una fila (% reasignación,
Δ Gini relativo, Δ score medio, Δ costo anual). Tooltip de cada card
con la fórmula de la columna correspondiente.

### 2.10 `kpi_scenario_diff_by_cluster` (trade-off pivoteado por cluster RB)

Mismo análisis que 2.9 pero agregando por el cluster_id del prestador en
rule_based. Permite ver dónde LP efectivamente redistribuye y dónde está
bloqueado (e.g., el gate LIVIANA fuerza ~99% de cluster 3 a quedarse
con el mismo prestador).

```
cluster_id                                    INT64
archetype_name                                STRING
n_orders                                      INT64
n_reassigned_to_other_cluster                 INT64    cluster_id_lp != cluster_id_rb
pct_reassigned_to_other_cluster               FLOAT64
n_reassigned_to_same_cluster_diff_provider    INT64    mismo cluster, prestador distinto
mean_score_delta                              FLOAT64
mean_cost_delta                               FLOAT64
computed_at                                   TIMESTAMP
```

**Query típica:** mostrar qué clusters se beneficiaron de LP.
```sql
SELECT cluster_id, archetype_name, n_orders,
       ROUND(pct_reassigned_to_other_cluster, 4) AS pct_cross_cluster,
       n_reassigned_to_same_cluster_diff_provider AS within_cluster_swaps,
       ROUND(mean_score_delta, 4)  AS delta_score,
       ROUND(mean_cost_delta, 0)   AS delta_cost_cop
FROM `proyecto-sura-clustering-2026.sura_clustering_processed.kpi_scenario_diff_by_cluster`
ORDER BY cluster_id
```

**Refresh ambas tablas:** `PYTHONPATH=. uv run python scripts/scenario_comparison.py`.

### 2.11 Tablas de soporte: `clustering_input`, `feat_prestador`, `feat_empresa`

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
PYTHONPATH=. uv run python scripts/compute_isc.py           # ~5 s — ISC + prestadores_necesarios
PYTHONPATH=. uv run python scripts/scenario_comparison.py   # ~20 s — trade-off RB ↔ LP
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
