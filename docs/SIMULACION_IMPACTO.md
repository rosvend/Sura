# Simulación de Impacto — Motor de Asignación vs. Status Quo

**Fecha:** 2026-05-10 · **Commit del modelo:** `033a18d` · **Escenario:** `rule_based`

Esta nota resume la primera corrida de la simulación de impacto. Hace replay
de **532,155 órdenes históricas** (Ordenado, todas las que tienen empresa,
tarea, municipio y prestador asignado conocido) y compara dos asignaciones:

- **Baseline:** el prestador realmente asignado en `Ordenado.Dni_Prestador`.
- **Modelo:** la recomendación top-1 del motor de scoring (commit `033a18d`),
  leída de `sura_clustering_processed.assignments`.

Para cada KPI comparamos el promedio (ponderado por orden) del atributo del
prestador asignado bajo cada escenario.

## Resumen Ejecutivo

| # | KPI | Baseline | Modelo | Δ | Target | Status |
|--:|---|---:|---:|---:|---:|:---:|
| K1 | Tasa esperada de cancelación | 9.0 % | 11.0 % | **+22 % rel** | −15 % rel | ❌ FAIL |
| K2 | Gini de carga (#órdenes / prestador) | 0.748 | 0.915 | **+22 % rel** | −10 % rel | ❌ FAIL |
| K3 | Costo logístico esperado (COP) | $13,394 | $11,457 | **−14.5 % rel** | −5 % rel | ✅ **PASS** |
| K4 | Match geográfico (muni base = muni destino) | 69.6 % | 81.6 % | **+12.0 pp abs** | +10 pp | ✅ **PASS** |

**2 de 4 KPIs cumplen su target** (la barra de aceptación definida en el plan).
Los dos que fallan tienen una raíz común — la concentración propia de un
motor greedy por orden — que la fase Día 4.5 (optimizador LP global)
está diseñada para resolver.

## Lectura por KPI

### K3 — Costo logístico esperado · ✅ −14.5 %

El modelo prefiere prestadores con menor costo histórico de transporte +
viáticos (`feat_prestador.costo_logistico_prom`). El delta absoluto de
−$1,937 por orden, escalado a las ~607 K órdenes anuales en Ordenado,
implica un ahorro **anual esperado de ≈ COP $1,175 M** sólo en logística.

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

### K2 — Gini de carga · ❌ +22 %

El motor concentra asignaciones en los prestadores de mayor score. El
status quo, aunque imperfecto, dispersa carga porque las decisiones se
toman manualmente y respetan disponibilidad real al momento de la
asignación. Sin un constraint duro de capacidad, el modelo siempre va
a empeorar este indicador.

**Acción única correcta:** implementar el optimizador LP global con
restricción `sum(horas_asignadas_por_prestador) ≤ capacidad` (Día 4.5).
Este es el caso de uso canónico del problema de asignación lineal.

## Cómo Replicar

```bash
PYTHONPATH=. uv run python -m src.monitoring.kpis
```

Lee:
- `gs://sura-clustering-raw/data/processed/assignments.parquet`
- `gs://sura-clustering-raw/Ordenado.parquet`
- `gs://sura-clustering-raw/gold/feat_prestador.parquet`

Escribe:
- `gs://sura-clustering-raw/data/processed/kpis_summary.parquet`
- `proyecto-sura-clustering-2026.sura_clustering_processed.kpis_summary`

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
