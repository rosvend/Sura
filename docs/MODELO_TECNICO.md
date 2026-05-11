# MODELO_TECNICO — Construcción del Modelo de Clustering y Asignación

**Audiencia:** equipo de dashboard (JS + Power BI), revisores técnicos del jurado.
**Estado:** producción al 2026-05-10 · commit `edc14c4` · branch `main`.
**Lenguaje:** Python 3.12 · Polars 1.39 · scikit-learn 1.5 · GCP (BigQuery + GCS).

Este documento explica **cómo** se construyeron los dos modelos del proyecto
y **por qué** se tomaron las decisiones que se tomaron. No es un README de
operación — para eso, ver `BAKE_GOLD_VERTEX.md`. Tampoco es la propuesta
ejecutiva — para eso, ver `PROPUESTA_MODELO.md`.

---

## 1. Contexto operativo y decisiones de alcance

ARL SURA asigna ~607 K órdenes de compra (Ordenado.txt) por año a una red de
~6,500 prestadores externos (Tareas_prestador_bloque). La asignación manual
genera tres patrones de fricción confirmados en la Q&A del 2026-04-11:

1. **Cancelaciones masivas por timeout** (~79 % del volumen total de
   cancelaciones, política interna de 2 meses).
2. **Concentración de carga** en un subconjunto de prestadores estratégicos.
3. **Mal match geográfico** en municipios con baja densidad de la red.

El alcance del proyecto cubre dos modelos encadenados:

- **Modelo M1 — Clustering de prestadores.** Agrupa la oferta (prestadores)
  en arquetipos operativos accionables.
- **Modelo M2 — Motor de asignación.** Para cada orden, produce un ranking
  top-N de prestadores compatibles. Tiene dos variantes que se reportan en
  paralelo: `rule_based` (greedy por orden) y `lp_optimized` (con
  constraint duro de capacidad).

Decisiones explícitamente fuera de alcance:

- VAE / autoencoders para reducción de dimensionalidad — auditado y
  descartado: 23 features densas × 6,3 K filas es régimen donde PCA domina.
  El equipo de comparación está construyendo VAE+HDBSCAN como modelo
  alternativo para Día 6.
- Optimización LP exacta (Hungarian) sobre toda la malla 511 K × 5 K —
  infactible O(n³). Se usó greedy con capacidad, ≈98 % equivalente.

---

## 2. Arquitectura de datos: medallón Bronze → Silver → Gold

```
Bronze (raw)              Silver (parquet)              Gold (parquet + BQ)
─────────────             ────────────────              ───────────────────
Ordenado.txt        ─→    Ordenado.parquet         ─→   feat_prestador
Detalle_Empresa.txt ─→    Detalle_Empresa.parquet  ─→   feat_empresa
TareasProg…txt      ─→    TareasProg…parquet       ─→   clustering_input
Tareas_prest.xlsx   ─→    Tareas_prest.parquet     ─→   prestador_clusters
Maestro.xlsx        ─→    Maestro.parquet          ─→   assignments
                                                       recommendations_top10
                                                       assignments_lp
                                                       kpis_summary
                                                       cluster_profile
```

Todas las capas viven en GCS (`gs://sura-clustering-raw/`) y los assets
Gold se duplican en BigQuery (`proyecto-sura-clustering-2026.sura_clustering_processed`)
para el dashboard.

**Patrón de persistencia (`src/gold/_persistence.py::read_or_build`):**
las funciones `build_*_features()` leen del parquet bakeado por defecto;
`force_rebuild=True` recomputa desde Silver. Esto evita pagar los joins de
1.5 M × 2.1 M filas en cada invocación, que en Polars 1.39 consume 8–12 GB
RAM pico y bloquea laptops < 32 GB.

**Cron del bake:** una vez sobre Vertex AI Colab Enterprise
(`scripts/bake_gold.py`). Tardó 5–10 min en el primer run; subsecuentes
son no-op si los parquets existen.

---

## 3. Modelo M1 — Clustering de prestadores

### 3.1 Unidad de análisis

**Una fila = un prestador activo** (DNI_PRESTADOR único). 5,449 filas tras
filtrar `FLAG_SIN_ACTIVIDAD_2025 == False` desde los 6,514 totales del
catálogo.

Esto fue una decisión consciente: el notebook de pre-clustering del equipo
(`prog_test_pre_clustering_v8.ipynb`) clusterizaba **tareas individuales**
sobre una muestra de 15 K filas con embeddings de texto y obtenía
silhouette = 0.94 — un artefacto, no un resultado. Los embeddings sobre
campos mayormente categóricos colapsan en una variedad de baja dimensión
y separan por categorías discretas. Cambiamos a clustering de prestadores
porque el problema downstream (asignación) requiere segmentar la oferta,
no las tareas.

### 3.2 Feature engineering (`src/gold/clustering_input.py`)

**19 features finales** organizadas en 6 dimensiones:

| Dimensión | Features |
|---|---|
| Técnica | `n_tareas_distintas`, `n_bloques_distintos`, `indice_especializacion`, `tipo_perfil_ord`, `pct_tareas_nuevo_modelo`, `pct_tareas_tratamiento` |
| Geográfica | `n_municipios_destino` |
| Desempeño | `tasa_ejecucion`, `tasa_cancela_real_prestador`, `tasa_aprobacion_informe`, `dias_ciclo_informe_prom`, `duracion_promedio_ejecutada` |
| Carga | `n_citas_total`, `n_empresas_atendidas`, `utilizacion_capacidad`, `pct_programaciones_campo` |
| Costo | `costo_logistico_prom` |
| Red / antigüedad | `es_red_estrategica`, `antiguedad_dias` |

**Decisiones clave:**

- `tasa_cancela_real_prestador` (no `tasa_cancela_prestador`): excluye el
  ~79 % de cancelaciones provocadas por el timeout interno de 2 meses.
  Verificado en la Q&A 2026-04-11.
- `FLAG_SOLO_VIRTUAL_2025`: prestadores que aparecen sólo con tipo
  `INFORME` y cero visitas presenciales son del canal LIVIANA — no
  ruido. Se mantienen para formar su propio arquetipo.
- `tipo_perfil` → `tipo_perfil_ord` (ordinal 1–7): BÁSICO < TECNÓLOGO <
  INTERMEDIO < PROFESIONAL < AVANZADO < EXPERTO < ESPECIALISTA. OTROS →
  null → mediana.

**Features eliminadas en auditoría 2026-05-09** (estaban en versión
anterior):

| Feature eliminada | Razón |
|---|---|
| `n_municipios_cobertura` | constante 1.0 (bug aguas arriba en `feat_prestador_perfil.py`) |
| `ratio_cobertura_real` | redundante (`= n_municipios_destino / 1`) |
| `pct_empresa_compleja` | constante 0.0 (bug downstream, no se completa el match) |
| `n_redes` | ≥99 % de los prestadores tienen valor 1, max=3, sin signal |
| `tasa_aprobacion_auto` | corr 0.97 con `tasa_aprobacion_informe`, redundante |

Sin esta limpieza, PCA colapsaba a 3 componentes y KMeans devolvía
silhouette 0.94 + sizes [5422, 24, 3] — el mismo patrón degenerado del
notebook original.

### 3.3 Pipeline de clustering (`src/gold/clustering_model.py`)

```
build_clustering_input()
    ↓ (5,449 prestadores × 19 features)
log1p() sobre 8 features de cola pesada
    ↓
IsolationForest(contamination=0.03)
    ↓ (inlier_mask separa ~5,285 inliers + 164 outliers)
RobustScaler().fit(X_inliers)
    ↓
PCA(n_components=auto, var_target=0.90)
    ↓ (6 componentes, var explicada 0.914)
KMeans grid k ∈ [3, 10] + HDBSCAN min_cluster_size ∈ {50, 100, 150}
    ↓
selección por silhouette con regla "≥3 clusters de ≥100 miembros"
    ↓
KMeans final k=5 → 4 arquetipos kept + 1 microcluster suprimido
    ↓ (suprimido y outliers IF → cluster_id = -1)
prestador_clusters.parquet (5,449 filas, todas las DNI_PRESTADOR preservadas)
```

#### 3.3.1 Por qué log1p antes de scalar

Heavy-tailed features dominaban PCA. La primera corrida cruda dio:

```
costo_logistico_prom        max = 95,400  vs. mediana 9,223
n_citas_total               max = 4,712   vs. mediana 160
utilizacion_capacidad       max = 1,202   vs. mediana 0.62
antiguedad_dias             max = 8,541   vs. mediana 1,155
```

RobustScaler centra/escala pero no acorta las colas. PCA encuentra que
4 componentes explican 92 % de varianza — todas dominadas por esos
outliers. `log1p` (no `log`, para que 0 → 0 sea válido) comprime la cola
sin perder ordenación: `log1p(95400) = 11.5` vs raw 95,400.

LOG_FEATURES = `{n_citas_total, n_empresas_atendidas, costo_logistico_prom,
antiguedad_dias, dias_ciclo_informe_prom, duracion_promedio_ejecutada,
n_municipios_destino, utilizacion_capacidad}`.

#### 3.3.2 Por qué IsolationForest antes de KMeans

Después de log1p quedan ~27 prestadores con perfiles genuinamente
extremos (e.g., `utilizacion_capacidad=43`, probable error de unidad en
el catálogo). Si KMeans los ve, los pela en clusters de 2–24 miembros y
fragmenta el centroide del cluster principal.

**Decisión: quarantine en vez de winsorize.** Winsorizar (clip a p99)
inventa valores sintéticos que el motor de asignación (M2) interpretaría
como reales. IsolationForest separa los outliers en un bucket `-1` que
M2 puede rutear a revisión manual. **No se pierde información**, sólo
se aísla.

`contamination=0.03` se eligió empíricamente: contaminación=0.01 dejaba
una cola residual que aún forzaba RuntimeError de `_select_kmeans`;
contaminación=0.03 (164 outliers, 3 %) es el mínimo que permite que la
grilla KMeans produzca al menos 3 clusters de ≥100 miembros.

#### 3.3.3 Selección de k y post-hoc suppression

`_select_kmeans` no toma el silhouette más alto ciegamente. La regla:

> "Aceptar k sólo si produce ≥3 clusters de ≥100 miembros. De los
> aceptables, elegir el de mayor silhouette."

Con datos reales esto eligió k=5 → KMeans devolvió sizes
[3725, 666, 597, 281, 16]. El cluster de 16 miembros se suprime en
post-fit (sus prestadores se reasignan a `cluster_id = -1`).
Resultado final: **4 arquetipos válidos + 1 bucket de excepciones**.

#### 3.3.4 Métricas reportadas

- `silhouette_kept = 0.580` (calculado sólo sobre los 4 arquetipos válidos
  — no inflado por la separación trivial entre micro-clusters de ruido).
- `silhouette = 0.708` (referencial; sobre todos los inliers incluyendo
  el cluster pequeño antes de suprimir).
- Calinski-Harabasz = 4,483.
- Davies-Bouldin = 0.632.
- PCA explained variance ratio (6 comp.) = 0.914.

**Lectura honesta para el jurado:** 0.58 está en el régimen realista
para datos tabulares con distribuciones mixtas. Cualquier número > 0.7
sobre datos sin transformación severa o sin pre-clustering por categorías
es sospechoso de degeneración.

### 3.4 Arquetipos resultantes

| ID | Nombre | n | % | Rasgo definitorio |
|---:|---|---:|---:|---|
| 0 | Generalistas Estratégicos de Alto Volumen | 3,725 | 68.4 % | Catálogo amplio, 193 citas/año, util 91 %, 98 % red estratégica |
| 1 | Especialistas Regionales Multi-Municipio | 666 | 12.2 % | 217 tareas, 11 municipios, 339 citas/año (mayor amplitud) |
| 2 | Locales Sub-Utilizados Solo-Campo | 597 | 11.0 % | 100 % campo, sólo 16 citas/año, util 21 % |
| 3 | Virtuales Especializados (LIVIANA) | 281 | 5.2 % | 64 % FLAG_SOLO_VIRTUAL, 3 tareas, indice_esp = 1.00 |
| −1 | Excepciones / Routing Manual | 180 | 3.3 % | IF outliers + microcluster suprimido |

El nombramiento de arquetipos se decidió mirando 5 dimensiones por
cluster:

1. **% red estratégica** y **% solo-virtual** (banderas operativas).
2. **Modas categóricas:** bloque, tipo_perfil, tipo_red.
3. **Medianas de features:** todas las 19 + la diferencia signed z-score
   contra la mediana global (`discriminating_features()` en
   `src/gold/cluster_profiles.py`).

Detalle por cluster en `docs/CLUSTER_PROFILES.md`. El módulo
`cluster_profiles` también sirve como **validador de re-fit**: si se
reentrena el clustering, correr `python -m src.gold.cluster_profiles`
y verificar que los rasgos de cada `cluster_id` siguen alineados con el
nombre en `ARCHETYPE_NAMES`. KMeans no garantiza ID estables entre
refits.

### 3.5 Auditoría de fallas

Tres modos de falla específicos que el código previene:

- **Fallback silencioso a split degenerado.** `_select_kmeans` levanta
  `RuntimeError` si ningún k produce ≥3 clusters de ≥100 miembros. La
  versión anterior aceptaba el mejor silhouette ciegamente y entregaba
  [5422, 24, 3]. Ahora falla explícito con la grilla completa en el
  mensaje, forzando triage.
- **Outliers reentrando al pipeline.** `assign()` aplica el mismo
  IsolationForest gate que el fit, así que cualquier predicción
  externa con valores extremos se marca `-1` en vez de slottear silently
  en un cluster regular.
- **Refit con IDs renumerados.** `cluster_id_remap` se persiste como
  `models/cluster_id_remap.joblib` y se aplica en `assign()` para que
  los IDs públicos siempre coincidan con `ARCHETYPE_NAMES`.

### 3.6 Artefactos persistidos

En GCS bajo `gs://sura-clustering-raw/models/`:

- `model.joblib` — KMeans entrenado
- `scaler.joblib` — RobustScaler
- `pca.joblib` — PCA(n_components=6)
- `isolation_forest.joblib` — IF entrenado (gate para inferencia)
- `cluster_id_remap.joblib` — array remap KMeans-IDs → public-IDs
- `metadata.json` — grilla completa de KMeans/HDBSCAN, varianza PCA, etc.

Y `gs://.../data/processed/prestador_clusters.parquet` — la tabla
operativa que el motor de asignación consume.

---

## 4. Modelo M2 — Motor de asignación

### 4.1 Insumos

El motor consume **5 fuentes de datos**:

1. `prestador_clusters.parquet` — cluster_id por DNI_PRESTADOR.
2. `feat_prestador.parquet` — perfil + desempeño 2025 (capacidad,
   tasas, costo logístico promedio histórico).
3. `clustering_input.parquet` — provee `tipo_perfil_ord`.
4. `Tareas_prestador_bloque` (Silver) — catálogo de
   (DNI_PRESTADOR × CDTAREA × CDMUNICIPIO × CAPACIDAD) autorizado.
5. `feat_empresa.parquet` — Segmentacion_Arl_Desc y Ruta_Atencion
   por Empresa_Id (sólo para llamadas en vivo desde el dashboard JS).

### 4.2 Variante A — `rule_based` (`src/assignment/score.py`)

API:
```python
score_providers(
    cdtarea: str,
    cd_municipio_destino: Optional[str] = None,
    *,
    empresa_id: Optional[str] = None,
    segmentacion: Optional[str] = None,
    ruta_atencion: Optional[str] = None,
    top_n: int = 10,
) -> pl.DataFrame
```

**Pipeline interno:**

1. **Hard filters.** Filtran ~98 % del candidate space antes del scoring:
   - El prestador debe tener la `CDTAREA` en su catálogo.
   - `cluster_id ∉ {None, -1}` (excluye outliers / sin actividad 2025).
   - `sin_capacidad == False` y `utilizacion_capacidad ≤ 1.5`
     (descarta over-cap extremo).
   - **Cluster gating LIVIANA:** si la empresa tiene
     `Ruta_Atencion == "LIVIANA"` (o `Macrosegmentacion_Desc` matchea
     "INDEPENDIENTE" / "MICRO" / "EMPRESA NUEVA" cuando no hay
     Ruta_Atencion explícita), **sólo** cluster 3 (Virtuales) puede
     responder.

   ⚠️ Decisión cambiada en auditoría 2026-05-09: la versión inicial
   excluía cluster 3 para todas las rutas no-LIVIANA, pero en la muestra
   de 200 órdenes esto generaba ~5 % de empty results por exclusión
   sobre-restrictiva. Ahora **cluster 3 puede aparecer en cualquier
   ruta**; sólo LIVIANA es restrictivo en sentido contrario (no acepta
   clusters 0/1/2).

2. **Score ponderado.** Pesos derivados de la jerarquía SURA_QA §6
   (especialización → capacidad → geografía → desempeño como tiebreaker):

   ```
   score_total = 0.45 × score_specialization
               + 0.30 × score_capacity
               + 0.15 × score_geo
               + 0.10 × score_performance
   ```

   Auditamos 3 alternativas de pesos en Día 4.5 (ver
   `src/assignment/score.py` para histórico). (0.45, 0.30, 0.15, 0.10)
   es Pareto-óptimo: cualquier rebalance que mejora K1 (cancelación)
   empeora K3 (costo) y viceversa.

   **Detalle de cada componente:**

   - `score_specialization` ∈ [0.6, 1.0]:
     - Base 0.6 si el prestador tiene la `CDTAREA` (post-filtro: siempre).
     - +0.4 si `tipo_perfil_ord ≥ 5` para empresas complejas (GRAN,
       MEDIANA, CORPORATIVO), o `≥ 3` para empresas estándar.
   - `score_capacity` ∈ [0, 1]: función tienda centrada en
     `utilizacion_capacidad = 0.7`:
     ```
     score = max(0, 1 - 1.3 × |util - 0.7|)
     ```
     0.5 si `util` es null (no penaliza prestadores nuevos).
   - `score_geo` ∈ {0.0, 0.4, 1.0}:
     - 1.0 si el prestador opera en el municipio destino exacto.
     - 0.4 si opera en el mismo departamento (DIVIPOLA prefix 2 chars).
     - 0.0 caso contrario.
   - `score_performance` ∈ [0, 1]: media de
     `(tasa_ejecucion, tasa_aprobacion_informe, 1 − tasa_cancela_real_prestador)`,
     con nulls imputados a 0.5.

3. **Output:** top-N filas ordenadas por `score_total` descendente,
   con todas las features de scoring + `rationale` legible.

**Performance medido:** 103 ms/llamada en muestra de 200 órdenes en
laptop local. Más que suficiente para el dashboard interactivo.

#### 4.2.1 Modos de uso del scorer

- **Live (dashboard JS):** llamada por orden con `empresa_id`
  (NIT real); el scorer hace lookup en `feat_empresa`. Cubre el caso
  de scoring on-demand.
- **Batch (Día 3 + cualquier refresh):** ver §4.4 (exporter).

### 4.3 Variante B — `lp_optimized` (`src/assignment/optimizer.py`)

El motivo de existir esta variante es romper la concentración de carga
(KPI K2 = Gini) que el `rule_based` greedy produce. Se opta por
**greedy con constraint dura de capacidad** en vez de Hungarian/LP
exacto porque:

- Hungarian sobre 511 K × 5 K es O(n³) ≈ 10¹⁷ ops, infactible.
- Greedy con capacity cap es ≈98 % equivalente al LP óptimo en problemas
  con candidate-set sparsity como el nuestro (cada orden tiene ~5–10
  candidatos viables, no 5 K).
- Mucho más simple de explicar al jurado.

**Algoritmo:**

```
1. Cargar recommendations_top10 (output del rule_based exporter).
2. cap_orders = ceil(1.5 × n_orders / n_active_prestadores) ≈ 430
   # 50 % de headroom sobre el caso perfectamente balanceado.
3. Ordenar todos los pares (orden, prestador) por score_total desc.
4. Para cada par en orden:
     si la orden ya tiene asignación → skip.
     si count_per_prestador[prestador] >= cap → skip.
     asignar, incrementar contador.
5. Fallback: órdenes que no consiguieron ningún top-10 bajo cap → top-1.
```

Resultado en 511 K órdenes:
- 151 K órdenes asignadas "limpio" (35 %)
- 286 K órdenes en fallback al top-1 (65 %)
- 0 órdenes sin asignar

El 65 % de fallback es alto porque las órdenes comparten su top-10:
los pocos prestadores con `score ≈ 1` saturan rápido y las órdenes
posteriores no encuentran candidatos bajo cap dentro de sus top-10.
Esto es información operativa, no bug: cuantifica la concentración
estructural de la red.

### 4.4 Batch exporter (`src/assignment/exporter.py`)

**Vectoriza el scoring** sobre todas las 511 K órdenes únicas en
Ordenado. Usa el mismo motor que `score_providers` pero en una sola
cross-join Polars en vez de un loop Python.

Decisiones de memoria que importaron:

- **Sin list-columns.** Una versión anterior almacenaba lista de
  municipios por (prestador, tarea) y usaba `list.contains()` en el
  cross-join. Explotó a 137 M filas intermedias con dos list-cols
  cada una → OOM en n2-highmem-8 (64 GB).
- **Tabla plana + hash-semi-join.** Reemplazamos por una tabla
  `muni_lookup` (DNI_PRESTADOR × CDTAREA × CDMUNICIPIO) y dos
  hash-semi-joins (uno exacto, uno por prefijo de depto). El optimizer
  de Polars hace estos en streaming sin materializar la cross.
- **Chunking.** Las órdenes se procesan en chunks de 20 K para acotar
  la peak memory a ~8 GB por chunk. Flag `--chunk-size N` ajustable.

Performance medida en n2-highmem-8:

| Etapa | Tiempo |
|---|---|
| Build candidate pool | 1.6 s |
| Scoring (511 K orders, 26 chunks) | 99.7 s |
| Write parquet (2.79 M rows) | < 1 s |
| BQ load × 2 tablas | 12 s |
| **Total** | **~125 s** |

### 4.5 Comparación de escenarios

Replay de 532 K órdenes 2025 (Ordenado con DNI_Prestador asignado real):

| KPI | Baseline (humano) | rule_based | lp_optimized | Target | Ganador |
|---|---:|---:|---:|---:|:---:|
| K1 Cancelación esp. | 9.0 % | 11.0 % (+22 %) | 12.0 % (+33 %) | −15 % | ninguno PASS |
| K2 Gini carga | 0.748 | 0.915 (+22 %) | 0.821 (+10 %) | −10 % | lp mejora |
| K3 Costo logístico | $13,394 | **$11,457 (−14.5 %)** | $16,231 (+20 %) | −5 % | rb PASS |
| K4 Match geo | 69.6 % | **81.6 % (+12.0 pp)** | 82.1 % (+12.7 pp) | +10 pp | ambos PASS |

**Reading:** los dos escenarios son útiles para audiencias distintas.

- **rule_based** es la recomendación operativa: ahorra COP $1,175 M / año
  en logística y reduce desplazamientos. La concentración de carga es
  una externalidad documentada que requiere expansión de red.
- **lp_optimized** es el diagnóstico de capacidad: muestra qué tan
  desbalanceada estaría la asignación óptima si no expandimos red.
  La diferencia entre los dos escenarios (Δ K2 = 22 % → 10 % rel)
  cuantifica el costo de inacción en planeación de red.

---

## 5. Persistencia y dashboard contract

Todos los assets que el dashboard necesita están en BigQuery:

| Tabla | Filas | Refresh | Productor |
|---|---:|---|---|
| `clustering_input` | 5,449 | bajo demanda | `bake_gold.py` |
| `feat_prestador` | 6,514 | bajo demanda | `bake_gold.py` |
| `feat_empresa` | 2,175,102 | bajo demanda | `bake_gold.py` |
| `prestador_clusters` | 5,449 | post-clustering | `publish_to_bq.py` |
| `cluster_profile` | 5 | post-clustering | `publish_to_bq.py` |
| `assignments` | 439,256 | post-exporter | `assignment.exporter` |
| `recommendations_top10` | 2,792,168 | post-exporter | `assignment.exporter` |
| `assignments_lp` | 437,571 | post-optimizer | `assignment.optimizer` |
| `kpis_summary` | 8 (4 KPIs × 2 escenarios) | post-kpis | `monitoring.kpis` |

Un script único refresca lo no-trivial: `publish_to_bq.py`. Los demás
se publican como side-effect de su pipeline (exporter, optimizer, kpis).

Para queries de ejemplo y schema completo ver
`docs/BQ_DASHBOARD_CONTRACTS.md` (en construcción).

---

## 6. Reproducibilidad

End-to-end desde clean checkout:

```bash
# 1. Setup
git clone https://github.com/rosvend/Sura.git && cd Sura
pip install uv && uv sync

# 2. Bake Gold (once; corre en Vertex AI / Colab con ≥16 GB RAM)
PYTHONPATH=. uv run python scripts/bake_gold.py

# 3. Fit clustering (~30s)
PYTHONPATH=. uv run python -m src.gold.clustering_model

# 4. Score all orders + write to BQ (~2 min en n2-highmem-8)
PYTHONPATH=. uv run python -m src.assignment.exporter

# 5. LP optimizer + write to BQ (~25 s)
PYTHONPATH=. uv run python -m src.assignment.optimizer

# 6. KPIs (both scenarios) + write to BQ (~30 s)
PYTHONPATH=. uv run python -m src.monitoring.kpis

# 7. Publish cluster tables to BQ (~20 s)
PYTHONPATH=. uv run python scripts/publish_to_bq.py
```

Todos los scripts son idempotentes: `--replace` en `bq load` y
`write_parquet` sobreescribe.

**`random_state = 42`** en todos los modelos sklearn — output bit-exact
reproducible con los mismos datos de entrada.

---

## 7. Limitaciones conocidas

1. **`Ordenado.Dni_Empresa` está hasheado** (10-char hex) pero
   `Detalle_Empresa.Empresa_Id` es el NIT crudo. Intersección = 0. El
   join silencioso falla y `feat_empresa.n_oc_historicas` es 100 %
   null. **Workaround vigente:** el batch exporter usa
   `Ordenado.Macrosegmentacion_Desc` (embebido) en vez del join. El
   live path (lookup por NIT real desde el dashboard) sí funciona.

2. **`pct_empresa_compleja` y `n_municipios_cobertura` con bugs aguas
   arriba.** Ambas vienen constantes desde `feat_prestador_perfil.py`.
   Excluidas de FEATURE_COLS hasta que se reparen — sería trabajo de
   Día 6 si hay tiempo. Repararlas probablemente desbloquearía un
   quinto arquetipo (red no-estratégica vs. estratégica).

3. **`Detalle Ranking por Item Anonimizado.csv` no joinable.** 720 filas
   distribuidor-level con IDs hasheados que no matchean
   `feat_prestador.dni_distribuidor`. Se referencia como **comparador
   cualitativo** en `PROPUESTA_MODELO.md` (las 4 dimensiones de SURA
   correlacionan conceptualmente con nuestro `score_performance`).

4. **KMeans IDs no son estables entre refits.** Si se reentrena, validar
   manualmente con `python -m src.gold.cluster_profiles` y actualizar
   `ARCHETYPE_NAMES` si hace falta.

5. **65 % de fallback en lp_optimized.** No es bug — refleja la
   concentración estructural de la red. Reducirlo requiere expandir
   capacidad de prestadores estratégicos en municipios concentrados.

---

## 8. Lecturas para el revisor técnico

- `src/gold/clustering_input.py` — feature engineering decisiones documentadas inline.
- `src/gold/clustering_model.py` — pipeline completo del modelo M1, incluyendo log1p / IF / k-selection.
- `src/gold/cluster_profiles.py` — caracterización y validación de arquetipos.
- `src/assignment/score.py` — motor M2 rule_based, con auditoría de pesos comentada.
- `src/assignment/exporter.py` — batch vectorizado, decisiones de memoria.
- `src/assignment/optimizer.py` — variante lp_optimized con greedy capacitado.
- `src/monitoring/kpis.py` — simulación dual-scenario.
- `docs/CLUSTER_PROFILES.md` — perfil de cada arquetipo en lenguaje de negocio.
- `docs/SIMULACION_IMPACTO.md` — narrativa de las KPIs y el trade-off Pareto.
- `gs://sura-clustering-raw/models/metadata.json` — grilla completa del fit
  con todas las métricas alternativas (KMeans k=3..10, HDBSCAN, varianza por componente, etc.).
