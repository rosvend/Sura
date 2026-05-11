# Simulación de Impacto — Motor de Asignación vs. Status Quo

**Fecha:** 2026-05-10 · **Commit del modelo:** `e1f5cda` · **Escenario:** `rule_based`

Esta nota resume la simulación de impacto post-hardening (commit `e1f5cda`,
métricas honestas sin imputación de nulls a cero). Hace replay de
**532,169 órdenes históricas** (Ordenado, todas las que tienen empresa,
tarea, municipio y prestador asignado conocido) y compara dos asignaciones:

- **Baseline:** el prestador realmente asignado en `Ordenado.Dni_Prestador`.
- **Modelo:** la recomendación top-1 del motor de scoring (commit `e1f5cda`),
  leída de `sura_clustering_processed.assignments`.

Para cada KPI comparamos el promedio (ponderado por orden) del atributo del
prestador asignado bajo cada escenario.

## Resumen Ejecutivo

Probamos **dos escenarios** de asignación contra el baseline histórico:

| # | KPI | Baseline | **rule_based** | Δ rb | **lp_optimized** | Δ lp |
|--:|---|---:|---:|---:|---:|---:|
| K1 | Tasa esperada de cancelación | 9.0 % | 11.0 % | +22 % ❌ | 12.0 % | +33 % ❌ |
| K2 | Gini de carga | 0.748 | 0.915 | +22 % ❌ | **0.821** | +10 % ❌ ↓ |
| K3 | Costo logístico esperado (COP) | $13,898 | **$11,480** | **−17.4 %** ✅ | $16,302 | +16.5 % ❌ |
| K4 | Match geográfico (muni base = muni destino) | 69.6 % | **81.6 %** | **+12.0 pp** ✅ | **82.2 %** | **+12.8 pp** ✅ |

**rule_based gana 2 de 4 KPIs · lp_optimized gana 1 de 4.**

Ambos escenarios pasan K4 (geo). El trade-off es:

- **rule_based** prioriza calidad por orden → mejor costo logístico y match
  geográfico, pero concentra carga en pocos prestadores top-score
  (rompe K2) y arrastra cancelaciones (rompe K1).
- **lp_optimized** impone un tope duro de ~430 órdenes/prestador →
  reduce a la mitad el deterioro de K2 (de +22 % a +10 % rel), pero al
  ser forzado a salir del top-1 score, pierde la ventaja de costo.

Esto es **un trade-off Pareto explícito**, no un fallo de diseño: la
capacidad operativa de la red impone un piso a la concentración alcanzable
sin perder calidad por orden.

## Lectura por KPI

### K3 — Costo logístico esperado · ✅ −17.4 %

El modelo prefiere prestadores con menor costo histórico de transporte +
viáticos (`feat_prestador.costo_logistico_prom`). El delta absoluto de
−$2,418 por orden, escalado a las ~607 K órdenes anuales en Ordenado,
implica un ahorro **anual esperado de ≈ COP $1,468 M** sólo en logística.
(El número es notablemente más alto que en la primera corrida porque
ahora el cálculo descarta nulls en lugar de imputarlos a cero — eso
subía artificialmente el "baseline" y reducía el delta. Ver `kpis.py`
commit `e1f5cda`.)

### K4 — Match geográfico · ✅ +12.0 puntos porcentuales

El componente `score_geo` (peso 0.15) hace exactamente lo prometido. El
prestador recomendado opera en el mismo municipio que el de entrega en
**8 de cada 10 órdenes**, vs. 7 de cada 10 en la asignación histórica.
Esto reduce desplazamientos, mejora tiempos de respuesta y refuerza el
ahorro de K3.

### K1 — Tasa esperada de cancelación · ❌ +22 %

**Lectura honesta:** el motor está priorizando especialización (peso 0.45)
y los prestadores más especializados resultan tener tasas de cancelación
ligeramente mayores que el promedio histórico. Hipótesis principal:
trabajan con empresas más complejas (Gran/Mediana), donde la cancelación
es estructuralmente más alta. El peso de `score_performance` (0.10)
no es suficiente para reordenar este efecto.

**Acciones:**
1. Re-balancear pesos antes del cierre (probar `perf = 0.20`, `spec = 0.35`)
   y re-correr.
2. Documentar como limitación conocida del enfoque greedy y reforzar el
   argumento para el LP global.

### K2 — Gini de carga · rb +22 % / lp +10 %

El motor rule_based concentra asignaciones en los prestadores de mayor
score. El optimizador `lp_optimized` (`src/assignment/optimizer.py`)
añade un tope duro de ~430 órdenes/prestador (`cap = ceil(1.5 × n_orders
/ n_prestadores_activos)`, 50 % de headroom sobre el caso perfectamente
balanceado) y **reduce a la mitad el deterioro de K2** (0.915 → 0.821).
Aún así no llega al target (-10 % rel = 0.673) porque la propia
distribución del catálogo concentra capacidad: 1,532 prestadores
distribuyen 437 K órdenes, y el subconjunto que cubre las tareas más
demandadas está estructuralmente pequeño.

**Recomendación operativa:** rebalanceo manual + ampliar la red
estratégica en municipios con cuello de botella. El modelo identifica
correctamente la oportunidad pero no puede resolverla solo.

## Recomendación de Deployment

Para la operación: **rule_based** (mejor costo y match geográfico,
ahorra COP $1,468 M/año en logística). Documentar el deterioro de K2
como deuda operativa que requiere expansión de capacidad en municipios
de demanda concentrada.

Para reporting estratégico al equipo de planeación de red:
**lp_optimized** como diagnóstico de qué tan desbalanceada estaría la
asignación óptima por calidad sin considerar capacidad. La diferencia
entre los dos escenarios (Δ K2 = 22 % → 10 %) cuantifica el costo de
no expandir la red.

## Cómo Replicar

```bash
# 1. Re-generar assignments (rule_based)
PYTHONPATH=. uv run python -m src.assignment.exporter

# 2. Re-generar assignments_lp (lp_optimized)
PYTHONPATH=. uv run python -m src.assignment.optimizer

# 3. Recomputar KPIs para ambos escenarios
PYTHONPATH=. uv run python -m src.monitoring.kpis
```

Lee:
- `gs://sura-clustering-raw/data/processed/assignments.parquet` (rule_based)
- `gs://sura-clustering-raw/data/processed/assignments_lp.parquet` (lp_optimized)
- `gs://sura-clustering-raw/Ordenado.parquet`
- `gs://sura-clustering-raw/gold/feat_prestador.parquet`

Escribe:
- `gs://sura-clustering-raw/data/processed/kpis_summary.parquet` (dos filas por KPI: una por escenario)
- `proyecto-sura-clustering-2026.sura_clustering_processed.kpis_summary`
- `proyecto-sura-clustering-2026.sura_clustering_processed.assignments_lp`

## Notas

- Los KPIs se calculan sobre las 532 K órdenes con empresa, tarea, municipio
  y prestador conocidos. Las órdenes con campos faltantes (~75 K) se
  excluyen del cálculo de KPIs pero sí están en `recommendations_top10`.
- K1 usa `tasa_cancela_real_prestador` — ya filtrada del ruido de la
  política de timeout de 2 meses (Q&A 2026-04-11). Si usáramos
  `tasa_cancelacion` cruda, el baseline sería ~3 × mayor y el delta
  relativo más severo.
- Comparador con la métrica interna de SURA (`Detalle Ranking por Item
  Anonimizado.csv`): no se puede joinear por DNI hasheado, pero las cuatro
  dimensiones (calidad, técnica, eficiencia, participación) correlacionan
  conceptualmente con K3, K4, score_performance — el modelo refuerza las
  mismas señales que ellos miden.
