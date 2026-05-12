# Sura — Motor de Clustering y Asignación de Prestadores

Estrategia de clústeres inteligentes para optimizar la atención y asignación de prestadores de salud en la cadena de servicios de ARL SURA.

Pipeline end-to-end: ingestión cruda → features → clustering → motor de asignación (dos escenarios) → KPIs accionables → contratos BigQuery para Power BI.

---

## TL;DR · Resultados

Medidos sobre las **439,263 órdenes completas** de `Ordenado.parquet` (no es una muestra).

- **Cuello de botella LIVIANA:** cluster 3 (Virtuales Especializados) opera a **ISC ≈ 3.58**; recibe 3.6× su capacidad. Requiere **+725 prestadores** o relajar el gate `LIVIANA → cluster_id=3` para llevarlo a ISC = 1.0.
- **`rule_based` ahorra COP ~1,468 M/año** en costo logístico (K3 = −17.4 %) y mejora el match geográfico en **+12 puntos** (K4 = 81.6 % vs baseline 69.6 %).
- **`lp_optimized` reduce la inequidad de carga 9.5 %** (Gini 0.921 → 0.833), pero a un costo de **+COP 1,659 M/año** en logística. Se publica como diagnóstico de red, no como default operativo.
- **K1 (cancelación esperada) regresa +22 %.** Divulgación honesta: los prestadores más especializados atienden empresas más complejas y heredan su tasa de cancelación. Open question pendiente con SURA.
- Arquitectura de **dos escenarios** prueba la frontera Pareto capacidad ↔ calidad explícitamente. Ningún greedy single-pass puede resolver ambas dimensiones a la vez.

**Ver detalle:** [`docs/EXECUTIVE_FINDINGS.md`](docs/EXECUTIVE_FINDINGS.md)

---

## Arquitectura

Pipeline medallion (Bronze → Silver → Gold) con dos escenarios de asignación corriendo en paralelo y una capa de KPIs post-hoc:

```
 RAW (GCS)                  SILVER                       GOLD                                CLUSTERING
 ─────────                  ──────────                   ──────────────                      ─────────────
 Ordenado.txt          ──►  load_ordenado()         ──►  feat_prestador        ──►  IsolationForest (c=0.03)
 Tareas_prestador.xlsx ──►  load_tareas_prestador() ──►  feat_empresa          ──►  PCA (var ≥ 0.90)
 Tareas_Programadas.txt──►  load_tareas_programadas()──► clustering_input      ──►  KMeans k ∈ [3, 11]
 Detalle_Empresa.txt   ──►  load_detalle_empresa()                                     │
 Maestro.xlsx          ──►  load_maestro()                                             ▼
                                                                                prestador_clusters
                                                                                cluster_profile
                                                                                       │
                                                                                       ▼
                                              ASSIGNMENT (dos escenarios)
                                              ──────────────────────────────
                                              exporter.py     ──► assignments        (rule_based, top-1)
                                                              ──► recommendations_top10 (rule_based, top-10)
                                              optimizer.py    ──► assignments_lp     (lp_optimized, greedy + cap dura)
                                              enrich_assignments.py ──► *_enriched   (+top_contributor, shares)
                                                                                       │
                                                                                       ▼
                                              MONITORING (post-hoc)
                                              ─────────────────────
                                              monitoring/kpis.py        ──► kpis_summary (K1–K4 × 2 escenarios)
                                              scripts/compute_isc.py    ──► kpi_saturacion_cluster (ISC + prescripción)
                                              scripts/scenario_comparison.py ──► kpi_scenario_diff (+ by_cluster)
                                                                                       │
                                                                                       ▼
                                              POWER BI · BigQuery (14 tablas)
```

Stack: **Polars** (eager + lazy) para data, **scikit-learn** para clustering, **greedy capacitado** para LP (sub-óptimo pero interpretable), **BigQuery + Power BI** para entrega.

---

## Cómo correr el pipeline

### Prerequisitos

```bash
uv sync                                          # instala dependencias (Python 3.12)
gcloud auth application-default login            # acceso a gs://sura-clustering-raw
gcloud config set project proyecto-sura-clustering-2026
```

### Secuencia completa (single source of truth: [`docs/BQ_DASHBOARD_CONTRACTS.md §3`](docs/BQ_DASHBOARD_CONTRACTS.md))

```bash
PYTHONPATH=. uv run python -m src.gold.clustering_model       # ~30 s · prestador_clusters, cluster_profile
PYTHONPATH=. uv run python -m src.assignment.exporter         # ~2 min · assignments, recommendations_top10
PYTHONPATH=. uv run python -m src.assignment.optimizer        # ~25 s  · assignments_lp
PYTHONPATH=. uv run python scripts/enrich_assignments.py      # ~15 s  · assignments_enriched + recs_enriched
PYTHONPATH=. uv run python -m src.monitoring.kpis             # ~30 s  · kpis_summary (K1–K4 × 2 escenarios)
PYTHONPATH=. uv run python scripts/compute_isc.py             # ~5 s   · kpi_saturacion_cluster (ISC + prescripción)
PYTHONPATH=. uv run python scripts/scenario_comparison.py     # ~20 s  · kpi_scenario_diff + by_cluster
PYTHONPATH=. uv run python scripts/publish_to_bq.py           # ~20 s  · refresh BQ
```

Total < 5 min. Todas las tablas son idempotentes (`bq load --replace`).

---

## Outputs · 14 tablas BigQuery

Todas en `proyecto-sura-clustering-2026.sura_clustering_processed`. Esquemas completos: [`docs/BQ_DASHBOARD_CONTRACTS.md`](docs/BQ_DASHBOARD_CONTRACTS.md).

**Gold (insumos):** `clustering_input` · `feat_prestador` · `feat_empresa`

**Clustering:** `prestador_clusters` (5,449 filas) · `cluster_profile` (5 arquetipos)

**Assignment (rule_based):** `assignments` (top-1, 439K) · `recommendations_top10` (2.79M) · `assignments_enriched` · `recommendations_top10_enriched` (+ `top_contributor` y shares)

**Assignment (lp_optimized):** `assignments_lp` (top-1 con cap dura, 437K)

**KPIs:**
- `kpis_summary` — K1 cancelación · K2 Gini · K3 costo · K4 geo, ambos escenarios
- `kpi_saturacion_cluster` — ISC + semáforo + `prestadores_necesarios` por cluster × escenario
- `kpi_scenario_diff` — métricas globales del trade-off RB ↔ LP
- `kpi_scenario_diff_by_cluster` — el mismo trade-off pivoteado por cluster

---

## Estructura del repo

```
Sura/
├── src/
│   ├── config.py             paths GCS, dataset/tabla BQ, constantes globales
│   ├── ingestion/            Bronze: carga raw resiliente a encoding/delimitador
│   ├── silver/               Silver: loaders LazyFrame por dataset
│   ├── gold/                 Gold: feature engineering + clustering + perfiles
│   ├── assignment/           motor de scoring (rule_based) + optimizador (LP-greedy)
│   ├── monitoring/           replay K1–K4 vs baseline histórico
│   └── simulations/          experimentos y comparadores de modelos
├── scripts/
│   ├── bake_gold.py          materialización Vertex AI de las parquets Gold
│   ├── compute_isc.py        ISC + prescripción (post-hoc)
│   ├── scenario_comparison.py  trade-off RB ↔ LP (post-hoc)
│   ├── enrich_assignments.py contribution decomposition (post-hoc)
│   ├── publish_to_bq.py      refresh BQ batch
│   └── ...                   inspectores, benchmarks, viz, sandbox
├── docs/                     ver "Documentación detallada" abajo
├── notebooks/                EDA y exploración
├── data/                     entradas crudas locales (mismas que en GCS)
├── models/                   artefactos del modelo (joblib en GCS)
├── viz/                      gráficas exportadas para los reportes
└── Dashboard_Analisis_SURA_2026.pbix    archivo Power BI
```

---

## Documentación detallada

### Para el negocio

- [`EXECUTIVE_FINDINGS.md`](docs/EXECUTIVE_FINDINGS.md) — síntesis ejecutiva de 2 páginas con K1–K4 + ISC + scenario-diff. **Empezar aquí.**
- [`SIMULACION_IMPACTO.md`](docs/SIMULACION_IMPACTO.md) — replay detallado de K1–K4 por escenario, lectura por KPI, recomendación de deployment.
- [`DIAGNOSTICO_ANALISIS.md`](docs/DIAGNOSTICO_ANALISIS.md) — diagnóstico de los 8 problemas estructurales del modelo actual.
- [`RETO.md`](docs/RETO.md) — especificación original del reto.

### Para ingeniería

- [`MODELO_TECNICO.md`](docs/MODELO_TECNICO.md) — diseño técnico de clustering + asignación, features, pesos del scorer, decisiones.
- [`BQ_DASHBOARD_CONTRACTS.md`](docs/BQ_DASHBOARD_CONTRACTS.md) — esquemas de las 14 tablas BQ, queries de ejemplo, secuencia de refresh.
- [`PROCESO_GOLD.md`](docs/PROCESO_GOLD.md) — pipeline de feature engineering bronze→silver→gold.
- [`BAKE_GOLD_VERTEX.md`](docs/BAKE_GOLD_VERTEX.md) — materialización one-off en Vertex AI (joins de 1.5M × 2.1M).

### Para datos

- [`DESCRIPCION_DATOS.md`](docs/DESCRIPCION_DATOS.md) — diccionario completo de los 5 datasets fuente.
- [`ER_DIAGRAMA.md`](docs/ER_DIAGRAMA.md) — diagrama entidad-relación de claves de integración.
- [`LIMPIEZA_TAREAS_PRESTADOR_Y_DETALLE_EMPRESA.md`](docs/LIMPIEZA_TAREAS_PRESTADOR_Y_DETALLE_EMPRESA.md) — decisiones de limpieza de datos crudos.
- [`CLUSTER_PROFILES.md`](docs/CLUSTER_PROFILES.md) — perfilado y naming de los 4 arquetipos.
- [`INSIGHTS_PRECLUSTERING.md`](docs/INSIGHTS_PRECLUSTERING.md) — hallazgos exploratorios antes del fit.

### Para experimentación

- [`EXPERIMENTO_UMAP_HDBSCAN.md`](docs/EXPERIMENTO_UMAP_HDBSCAN.md) — comparación UMAP+HDBSCAN vs PCA+KMeans (validación de la elección final).
- [`SURA_QA.md`](docs/SURA_QA.md) — Q&A consolidado con stakeholders.
- [`PREGUNTAS_ESTRATEGICAS_DANIEL.md`](docs/PREGUNTAS_ESTRATEGICAS_DANIEL.md) — preguntas abiertas y supuestos del modelo.

---
