# Perfil de los Clusters de Prestadores

**Modelo en producción:** commit `98e1d98` · `random_state=42` · `k=5`,
`silhouette_kept=0.580`, **4 arquetipos válidos** + 1 bucket de excepciones.

Total prestadores activos: **5,449** (filtrados de 6,514 con
`FLAG_SIN_ACTIVIDAD_2025=False`). El 96.7 % cae en uno de los 4 arquetipos;
3.3 % (180 prestadores) van a `cluster_id = -1` para *routing manual*.

| Cluster | Nombre | n | % | Rasgo definitorio |
| ---: | --- | ---: | ---: | --- |
| **0** | Generalistas Estratégicos de Alto Volumen | 3,725 | 68.4 % | El núcleo operativo: catálogo amplio, volumen estable, 98 % red estratégica |
| **1** | Especialistas Regionales Multi-Municipio | 666 | 12.2 % | Mayor amplitud (217 tareas, 11 municipios) y mayor volumen (339 citas, 96 empresas), levemente sobre-utilizados |
| **2** | Locales Sub-Utilizados Solo-Campo | 597 | 11.0 % | 100 % visitas presenciales pero solo 16 citas/año y 21 % de capacidad usada |
| **3** | Virtuales Especializados (LIVIANA) | 281 | 5.2 % | Canal virtual puro, 3 tareas, 64 % marcados como solo virtual, 0 % campo |
| **-1** | Excepciones / Routing Manual | 180 | 3.3 % | Mezcla heterogénea: outliers de IsolationForest + clusters de < 100 reasignados |

Las cifras siguientes son **medianas por cluster** sobre el set de 5,449
prestadores. Las medias y conteos completos viven en
`gs://sura-clustering-raw/models/metadata.json`.

---

## Cluster 0 — Generalistas Estratégicos de Alto Volumen

> 3,725 prestadores · 68.4 % de la red

El cuerpo principal de la red. Profesionales **AVANZADO/INTERMEDIO**
(percentil de seniority alto), con un catálogo amplio (12 bloques, 129
tareas) y volumen estable (193 citas/año, 18 empresas atendidas, 6
municipios). **98.1 % son red ESTRATEGICA**, 91 % de utilización de
capacidad — bien aprovechados sin sobrecarga.

Concentran el **costo logístico más alto** (mediana \$13,394 vs. \$9,223
global) — son los que cubren las visitas presenciales que requieren más
desplazamiento.

| Discriminador (vs. global) | Cluster | Global | z |
| --- | ---: | ---: | ---: |
| n_citas_total | 193 | 160 | +0.17 |
| duracion_promedio_ejecutada | 3.16 | 2.67 | +0.17 |
| n_bloques_distintos | 12 | 11 | +0.14 |

**Implicación operativa:** *default* del motor de asignación. Cuando
ninguna característica especial del pedido lo descarta, este cluster es la
elección segura.

---

## Cluster 1 — Especialistas Regionales Multi-Municipio

> 666 prestadores · 12.2 % de la red

Los **caballos de batalla de cobertura amplia**. Catálogo más extenso de
toda la red (217 tareas, 14 bloques) y mayor volumen operativo: **339
citas/año** y **96 empresas atendidas** (5–10 × el promedio). Operan
sobre **11 municipios** (≈ 2 × el global).

Su seniority es ligeramente menor (INTERMEDIO/AVANZADO, percentil 3 vs.
5 global) — son ejecutores especializados pero no necesariamente seniors.
Utilización al 132 % indica que están **levemente sobre-asignados**: el
motor de asignación debería preferir Cluster 0 cuando ambos cumplen.

| Discriminador (vs. global) | Cluster | Global | z |
| --- | ---: | ---: | ---: |
| n_tareas_distintas | 217 | 131 | +1.22 |
| n_citas_total | 339 | 160 | +0.92 |
| n_empresas_atendidas | 96 | 17 | +0.88 |
| pct_tareas_nuevo_modelo | 0.83 | 1.00 | −2.01 |

**Bandera:** son los únicos con `pct_tareas_nuevo_modelo` mediano por
debajo de 1.0 — un subconjunto significativo de su catálogo está en el
modelo de atención previo. No bloquea asignación pero conviene auditar.

**Implicación operativa:** ideal para órdenes que requieren cobertura
geográfica amplia o tareas poco frecuentes. Penalizar por capacidad si
`utilizacion_capacidad > 0.9` para evitar burnout.

---

## Cluster 2 — Locales Sub-Utilizados Solo-Campo

> 597 prestadores · 11.0 % de la red

**Capacidad ociosa**: utilización mediana 21 %, solo 16 citas/año, 3
empresas atendidas, 2 municipios destino. **100 % visitas presenciales**
(`pct_programaciones_campo = 1.0`) y costo logístico mediano \$0 — operan
en el municipio base sin desplazamientos.

Anomalía clara: **`tasa_aprobacion_informe = 0`** (z = −2.66). Estos
prestadores ejecutan citas pero no generan informes aprobados. Posibles
causas: las tareas que ejecutan no requieren informe formal, o hay un
gap en el flujo de aprobación. Vale la pena triagear con el equipo
operativo antes de Día 3.

| Discriminador (vs. global) | Cluster | Global | z |
| --- | ---: | ---: | ---: |
| tasa_aprobacion_informe | 0.000 | 0.972 | −2.66 |
| pct_programaciones_campo | 1.00 | 0.81 | +0.82 |
| n_citas_total | 16 | 160 | −0.74 |
| antiguedad_dias | 595 | 1,155 | −0.34 |

**Implicación operativa:** **oportunidad de capacidad**. El motor de
asignación debería favorecerlos para órdenes locales presenciales que no
requieran cobertura amplia ni informes complejos, hasta llevar su
utilización a un rango operativo (50–80 %).

---

## Cluster 3 — Virtuales Especializados (Canal LIVIANA)

> 281 prestadores · 5.2 % de la red

El **canal virtual puro**, confirmado por la Q&A 2026-04-11 (la ruta
LIVIANA usa prestadores que orientan clientes por mensajes/llamadas sin
visita presencial). 63.7 % marcados con `FLAG_SOLO_VIRTUAL_2025` (vs. <
1 % en los otros arquetipos), 0 % campo, 0 citas presenciales, 0 costo
logístico.

Catálogo extremadamente acotado (3 tareas, 2 bloques) con **especialización
máxima** (`indice_especializacion = 1.00`) y **100 % en etapa
TRA** (tratamiento). Son los responsables de intervenciones específicas
del nuevo modelo de atención que se entregan por canal digital.

| Discriminador (vs. global) | Cluster | Global | z |
| --- | ---: | ---: | ---: |
| indice_especializacion | 1.00 | 0.48 | +3.35 |
| pct_tareas_tratamiento | 1.00 | 0.60 | +2.99 |
| pct_programaciones_campo | 0.00 | 0.81 | −3.39 |
| tasa_aprobacion_informe | 0.000 | 0.972 | −2.66 |
| n_tareas_distintas | 3 | 131 | −1.81 |

**Implicación operativa:** segmento dedicado para empresas con
`Ruta_Atencion = LIVIANA` (independientes, microempresas con riesgo
bajo). El motor de asignación debe rutear a este cluster por
construcción cuando la empresa tenga ruta liviana, sin pasar por el
scoring presencial estándar.

---

## Cluster -1 — Excepciones / Routing Manual

> 180 prestadores · 3.3 % de la red

Bucket de seguridad operativa. Combina dos fuentes:

1. **Outliers de IsolationForest** (`contamination = 0.03`, ~164
   prestadores): valores extremos en ejes que distorsionarían los
   centroides. Ejemplos típicos: `utilizacion_capacidad > 10`
   (probable error de unidades en `capacidad`), `costo_logistico_prom >
   p99`.
2. **Clusters de KMeans con < 100 miembros, suprimidos en post-fit**
   (~16 prestadores): subgrupos persistentes que aparecen en todos los
   k pero son demasiado pequeños para constituir un arquetipo
   accionable.

Características distintivas: solo cluster donde la red estratégica **no
domina** (32 % vs. > 97 % en los demás). Mayor antigüedad mediana
(2,522 días = 6.9 años) y especialización máxima (0.98). Mezcla de
canales (50 % virtual, 50 % presencial).

| Discriminador (vs. global) | Cluster | Global | z |
| --- | ---: | ---: | ---: |
| es_red_estrategica | 0.00 | 1.00 | −4.88 |
| pct_programaciones_campo | 0.00 | 0.81 | −3.39 |
| indice_especializacion | 0.98 | 0.48 | +3.24 |
| tipo_perfil_ord | 1 | 5 | −2.88 |

**Implicación operativa:** **no asignar automáticamente**. El motor
debe excluir este cluster del scoring y devolver una bandera de "revisar
manualmente" para que operaciones decida caso por caso. Día 3
implementará esta lógica como filtro previo al scoring.

---

## Notas para el lector técnico

- Los IDs de KMeans **no son estables** entre refits. Si se re-entrena
  el modelo, validar con `python -m src.gold.cluster_profiles` que los
  nombres de `ARCHETYPE_NAMES` siguen correspondiendo a los rasgos
  descritos arriba.
- `sector_principal_atendido` y `segmento_principal_atendido` aparecen
  como `None` para todos los prestadores en `clustering_input` —
  comportamiento esperado dado que esas columnas todavía no se calculan
  desde `feat_prestador_perfil.py` (deuda técnica de Día 2).
- Los bugs en `n_municipios_cobertura` (constante 1.0) y
  `pct_empresa_compleja` (constante 0.0) en `feat_prestador_perfil.py`
  llevaron a sacarlas de `FEATURE_COLS` el 2026-05-09. Repararlas y
  re-introducirlas podría generar un quinto arquetipo (probable: red
  no-estratégica vs. estratégica), pero no es crítico para Día 3.
