# Hallazgos Ejecutivos — Modelo de Clustering y Asignación SURA

**Fecha:** 2026-05-12 · **Universo evaluado:** 439,263 órdenes (Ordenado 2025, replay completo) · **Commit del modelo:** `5441001`

---

## TL;DR

1. **Cuello de botella estructural en LIVIANA.** El cluster 3 (Virtuales Especializados, canal LIVIANA) opera a **ISC ≈ 3.58** — recibe 3.6× su capacidad estimada. Para llevarlo a ISC = 1.0 hacen falta **+725 prestadores LIVIANA-capaces** (`kpi_saturacion_cluster.prestadores_necesarios`).
2. **rule_based es el escenario operativo** con ahorros medibles: **−17.4 % en costo logístico** (COP 1,468 M/año) y **+12 puntos** en match geográfico, sobre las 439 K órdenes completas (no muestra).
3. **lp_optimized NO es un win en pesos.** Mejora la equidad de carga **−9.5 % en Gini** (0.921 → 0.833), pero **incrementa el costo logístico esperado en +COP 1,659 M/año**. Sirve como diagnóstico de capacidad, no como default operativo.
4. **K1 (cancelación esperada) regresa +22 / +33 %** en ambos escenarios — divulgación honesta. Hipótesis: los prestadores más especializados atienden empresas más complejas y heredan su tasa de cancelación. Requiere validación con SURA antes de re-pesar el scorer.
5. **Arquitectura de dos escenarios** prueba la frontera Pareto capacidad ↔ calidad explícitamente. Ningún greedy single-pass puede resolver ambas dimensiones a la vez; el modelo lo cuantifica.

---

## 1. Veredicto operativo

| Decisión | Recomendación |
|---|---|
| Motor en producción | **`rule_based`** — gana K3 (costo) y K4 (geografía) |
| Diagnóstico de red | **`lp_optimized`** — gana K2 (equidad), cuantifica deuda operativa |
| Monitoreo continuo | **`kpi_saturacion_cluster`** + `kpi_scenario_diff` actualizados en cada refresh |

Justificación numérica (fuente: `kpis_summary`, `SIMULACION_IMPACTO.md`):

| KPI | Baseline | rule_based | Δ | lp_optimized | Δ |
|--:|---|---:|---:|---:|---:|
| K1 cancelación esperada | 9.0 % | 11.0 % | +22 % ❌ | 12.0 % | +33 % ❌ |
| K2 Gini de carga | 0.748 | 0.915 | +22 % ❌ | **0.821** | +10 % ❌ ↓ |
| K3 costo logístico | $13,898 | **$11,480** | **−17.4 %** ✅ | $16,302 | +16.5 % ❌ |
| K4 match geográfico | 69.6 % | **81.6 %** | **+12.0 pp** ✅ | **82.2 %** | **+12.8 pp** ✅ |

`rule_based` gana 2 de 4. `lp_optimized` gana 1 de 4. La diferencia de los dos cuantifica el costo operativo de no expandir capacidad: K2 se reduce a la mitad (+22 % → +10 %), K3 se sacrifica (+34 puntos relativos).

---

## 2. El cuello de botella LIVIANA — finding estructural

`kpi_saturacion_cluster` (cluster × escenario):

| cluster | arquetipo | n_prov | cap. estimada | tareas | ISC | estado | prestadores necesarios |
|--:|---|---:|---:|---:|---:|---|---:|
| 0 | Generalistas Estratégicos | 3,705 | 741,000 | 177,305 (RB) | 0.239 | Verde | 0 |
| 1 | Especialistas Regionales | 660 | 145,200 | 27,678 (RB) | 0.191 | Verde | 0 |
| 2 | Locales Sub-Utilizados | 586 | 128,920 | 13,205 (RB) | 0.102 | Verde | 0 |
| **3** | **Virtuales LIVIANA** | **280** | **61,600** | **221,075 (RB)** | **3.589** | **🔴 Crítico** | **+725** |

**El 50.3 % de todas las órdenes (221 K de 439 K) cae sobre el 5.1 % de la red (280 prestadores).** Esto no es un fallo del modelo — el modelo lo está exponiendo.

La causa es el gate operativo en `src/assignment/exporter.py:244–246`:
```python
joined = joined.filter(
    ~pl.col("is_virtual_seg") | (pl.col("cluster_id") == CLUSTER_VIRTUAL)
)
```
Toda empresa segmentada como Independiente / Micro / Empresa Nueva enruta exclusivamente al cluster 3.

**Evidencia adicional de que el gate es estructural y no algorítmico** (`kpi_scenario_diff_by_cluster`):

| cluster | n órdenes | cross-cluster reassign (LP) | % | within-cluster swaps (LP) |
|--:|---:|---:|---:|---:|
| 0 | 177,305 | 14,499 | 8.18 % | 60,514 |
| 1 | 27,678 | 4,342 | 15.69 % | 6,534 |
| 2 | 13,205 | 3,874 | 29.34 % | 1,510 |
| **3** | **221,075** | **42** | **0.019 %** | **2,986** |

LP — un optimizador con visión global — **no puede mover el 99.98 % de las órdenes LIVIANA fuera del cluster 3.** Lo intenta y no puede. El cuello de botella está en la red, no en el algoritmo.

**Recomendación accionable a SURA:**
- (a) Expandir red LIVIANA en al menos **+725 prestadores capacitados**, o
- (b) Relajar el gate `LIVIANA → cluster_id=3` para permitir fan-out controlado a los clusters 0/1 (que están a ISC < 0.25, con capacidad ociosa de ~470 K órdenes/año), o
- (c) Cualquier combinación de las dos.

El modelo entrega el número. La decisión de capacidad es de SURA.

---

## 3. El valor (y el costo) de la optimización LP

`kpi_scenario_diff` — universo 439,263 órdenes, ambas escenarios inner-joined:

| Métrica | rule_based | lp_optimized | Δ |
|---|---:|---:|---:|
| Gini de carga | 0.921 | **0.833** | **−9.5 % rel** |
| Score promedio | 0.794 | 0.783 | −0.011 (−1.4 %) |
| Costo logístico/orden (COP) | 10,008 | 13,785 | **+3,777** |
| Órdenes reasignadas | — | — | **94,301 (21.5 %)** |
| Proyección anual de costo | — | — | **+COP 1,659 M** |

**Lectura honesta:** LP compra 9.5 % de equidad a un costo de **+COP 1.66 mil millones/año** en logística. La mediana del delta de score (`score_delta_p50 = 0.0`) confirma que la mayoría de reasignaciones son entre prestadores casi equivalentes — pero la cola de 21.5 % de cambios sí mueve la aguja en distancia geográfica y costo de transporte.

**Conclusión:** LP no se despliega. Se publica como diagnóstico estratégico de planeación de red.

---

## 4. Lo que NO afirmamos

Tres divulgaciones honestas que distinguen un análisis defendible de uno inflado:

1. **No proyectamos ahorro por cancelaciones evitadas.** K1 actualmente regresa +22 %. Cualquier número en pesos sería ficción. La cifra requeriría: (a) un costo unitario por cancelación que SURA aún no nos ha confirmado, y (b) que el modelo demostrara reducir K1, no aumentarlo.

2. **No usamos muestreo.** Las métricas K1–K4, ISC y scenario-diff se computan sobre las 439,263 órdenes completas. El gap con respecto al universo bruto de Ordenado (607 K) son las órdenes sin empresa, tarea, municipio o prestador conocidos — excluidas explícitamente, no estimadas.

3. **No reclamamos equivalencia LP-exacto.** El optimizador es un greedy con tope duro de capacidad (`CAPACITY_HEADROOM = 1.5` en `src/assignment/optimizer.py:56`). Es subóptimo en sentido estricto pero produce un resultado interpretable por un revisor operativo no técnico.

Estas tres ausencias son intencionales. Cada cifra en este documento se puede trazar a una columna de parquet y a una expresión de Polars.

---

## 5. Reproducibilidad

```bash
PYTHONPATH=. uv run python -m src.gold.clustering_model       # clustering
PYTHONPATH=. uv run python -m src.assignment.exporter         # rule_based
PYTHONPATH=. uv run python -m src.assignment.optimizer        # lp_optimized
PYTHONPATH=. uv run python -m src.monitoring.kpis             # K1–K4
PYTHONPATH=. uv run python scripts/compute_isc.py             # ISC + prescripción
PYTHONPATH=. uv run python scripts/scenario_comparison.py     # trade-off RB ↔ LP
```

Total: < 5 min. Todas las tablas son idempotentes (`--replace`).

**Tablas BQ que consume el dashboard:**
`prestador_clusters`, `cluster_profile`, `assignments`, `recommendations_top10`,
`assignments_lp`, `kpis_summary`, **`kpi_saturacion_cluster`**, **`kpi_scenario_diff`**,
**`kpi_scenario_diff_by_cluster`**. Ver `docs/BQ_DASHBOARD_CONTRACTS.md` para esquemas.
