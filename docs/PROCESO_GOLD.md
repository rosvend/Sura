# Proceso de construcción de la capa Gold

> Documento de constancia técnica y de decisiones del proceso de ingeniería de features para el reto SURA 2026.
>
> Para cada decisión se indica: **qué se decidió**, **por qué se tomó esa decisión**, y si aplica, **qué pregunta del encuentro estratégico puede confirmar o corregir el supuesto** (ver `PREGUNTAS_QA_SURA.md`).

---

## 1. Contexto: arquitectura Medallion

El proyecto sigue una arquitectura de datos en tres capas (Medallion), donde cada capa tiene una responsabilidad distinta y un destino de almacenamiento propio.

```
GCS: archivos crudos (.txt, .xlsx)
        │
        │  scripts/load_to_parquet.py
        │  src/ingestion/extract.py
        ▼
┌─────────────────────────────────────────────────────┐
│  BRONZE — src/ingestion/                            │
│  Lectura cruda de archivos tal como llegan.         │
│  Auto-detección de encoding y delimitador.          │
│  Todos los campos se cargan como string (sin tipos).│
│  Sin transformaciones. Sin limpieza.                │
│                                                     │
│  Destino 1: GCS — archivos fuente originales        │
│             (.txt, .xlsx)                           │
│  Destino 2: GCS — mismos datos en formato Parquet   │
│             (.parquet) — caché de lectura rápida    │
└──────────────────────────┬──────────────────────────┘
                           │
                           │  src/silver/extract.py
                           ▼
┌─────────────────────────────────────────────────────┐
│  SILVER — src/silver/                               │
│  Parseo de tipos, normalización de columnas,        │
│  limpieza de nulos y deduplicación.                 │
│  Lee desde los parquets Bronze de GCS.              │
│  Expone LazyFrames nombrados por dataset.           │
│                                                     │
│  Destino: BigQuery sura_clustering_cleaned          │
└──────────────────────────┬──────────────────────────┘
                           │
                           │  src/gold/
                           ▼
┌─────────────────────────────────────────────────────┐
│  GOLD — src/gold/                                   │
│  Ingeniería de features: agregación, cómputo de     │
│  KPIs, encoding, imputación.                        │
│  Grano analítico: 1 fila por prestador / empresa.   │
│                                                     │
│  Destino: BigQuery sura_clustering_processed        │
└─────────────────────────────────────────────────────┘
```

---

## 2. Tablas Gold

### Mapa de dependencias

```
load_tareas_prestador()  ──► feat_prestador_perfil ──┐
                                                      ├──► feat_prestador ──► clustering_input
load_tareas_programadas()  ┐                          │
load_ordenado()            ├──► feat_prestador_perf ──┘
load_empresas()  ──────────┘   (demanda atendida)

load_empresas()          ──┐
load_ordenado()            ├──► feat_empresa
load_tareas_programadas()  ┘
```

Las tablas `feat_prestador` y `feat_empresa` representan los dos lados del problema de asignación: **oferta** (quién puede hacer qué) y **demanda** (quién necesita qué). `clustering_input` es la matriz final que entra al notebook de modelado.

---

## 3. `feat_prestador_perfil` — Perfil técnico del catálogo

**Archivo:** `src/gold/feat_prestador_perfil.py`

**Fuente:** `load_tareas_prestador()` — catálogo completo 4 hojas

**Grano de salida:** 1 fila por `DNI_PRESTADOR` → **6.514 prestadores**

### Qué contiene

| Grupo               | Columnas clave                                                                                         |
| ------------------- | ------------------------------------------------------------------------------------------------------ |
| Conteos técnicos    | `n_habilitaciones`, `n_tareas_distintas`, `n_bloques_distintos`, `n_productos_distintos`               |
| Geografía           | `n_municipios_cobertura`, `municipio_base`                                                             |
| Capacidad           | `capacidad_total_declarada` (suma de CAPACIDAD del catálogo)                                           |
| Antigüedad          | `antiguedad_dias` (desde FECHA_INGRESO)                                                                |
| Perfil predominante | `tipo_perfil_predominante`, `funcion_predominante`, `clasificacion_predominante`, `tipo_red_principal` |
| Especialización     | `bloque_principal`, `n_tareas_bloque_principal`, `indice_especializacion`                              |

### Decisiones tomadas

---

**Decisión 3.1 — Cómputo de perfil predominante por moda (sort-and-take)**

Se calcula el valor más frecuente de `DSTIPO_PERFIL` y `FUNCION_PRESTADOR` por prestador usando el patrón: ordenar descendente por conteo y tomar el primer valor de cada grupo. No se usa `pl.mode()` directamente porque en Polars lazy no está disponible de forma eficiente.

Para `TIPO_DE_RED`, el tratamiento es distinto (ver abajo): se usa `.any()` para derivar `es_red_estrategica` en lugar de calcular la moda.

**Justificación:** Un prestador tiene miles de filas en el catálogo (una por cada combinación tarea-bloque-municipio). Agregar a nivel de prestador requiere elegir un valor representativo. La moda es la decisión estadísticamente correcta para variables categóricas.

**Pendiente de validación:** No hay pregunta específica que la afecte, pero la interpretación del perfil predominante depende de que los valores del catálogo sean correctos y actualizados. Si SURA actualiza el catálogo periódicamente, este cómputo es automáticamente correcto en cada recalibración.

---

**Decisión 3.4 — `es_red_estrategica` con `.any()` en lugar de moda**

La feature binaria `es_red_estrategica` se calcula como: *¿aparece `ESTRATEGICA` en al menos una hoja del catálogo para este prestador?* Se usa `.any()` sobre `TIPO_DE_RED == "ESTRATEGICA"`.

**Justificación:** 35 prestadores aparecen en múltiples redes regionales, y 3 de ellos tienen `TIPO_DE_RED` distinto entre hojas. Usar `.first()` o moda produciría un resultado arbitrario o incorrecto para estos casos. Con `.any()`, un prestador que pertenece a la red ESTRATEGICA en cualquier región queda correctamente marcado, independientemente del orden de lectura del catálogo. Verificado: 1 prestador era mal clasificado con `.first()` en los datos actuales.

La columna `tipo_red` sigue existiendo en la tabla con `.first()` como columna de **contexto interpretativo** (no entra al modelo).

---

**Decisión 3.2 — Índice de especialización**

`indice_especializacion = n_tareas_bloque_principal / n_tareas_distintas`

Valor de 1.0 = prestador que concentra todas sus habilitaciones en un solo bloque (especialista puro). Valor cercano a 0 = prestador generalista distribuido en muchos bloques.

**Justificación:** Esta feature captura la dimensión de foco técnico que no es evidente con los conteos individuales. Dos prestadores con 100 tareas pueden ser muy distintos si uno las tiene todas en rehabilitación y el otro las tiene repartidas en 20 bloques.

**Pendiente de validación:** Ninguna pregunta específica la invalida, pero la respuesta del negocio a "*¿cuál es la jerarquía de prioridades entre especialización técnica, eficiencia logística y balance de carga?*" (Q24) determinará si esta feature debe tener mayor o menor peso relativo en el clustering.

---

**Decisión 3.3 — `FECHA_INGRESO` como proxy de antigüedad**

Se usa `FECHA_INGRESO` del catálogo para calcular los días desde que el prestador ingresó a la red hasta hoy.

**Justificación:** Es el único campo temporal disponible en el catálogo que puede aproximar experiencia en la red. La antigüedad es un proxy razonable de madurez operativa.

**⚠️ Supuesto no confirmado (Q21):** si `FECHA_INGRESO` es una fecha de última actualización del registro en el sistema en lugar de la fecha real de incorporación a la red, `antiguedad_dias` es ruido y debe eliminarse de `FEATURE_COLS`.

**Esta pregunta debe hacerse en el encuentro.**

---

## 4. `feat_prestador_performance` — KPIs operativos 2025

**Archivo:** `src/gold/feat_prestador_performance.py`

**Fuentes:** `load_tareas_programadas()` + `load_ordenado()` + `load_empresas()` *(agregado — perfil de demanda)*

**Grano de salida:** 1 fila por `DNI_PRESTADOR` con actividad en 2025 → **6.576 prestadores**

> ⚠️ **6.576 > 6.514 (catálogo):** existen 62 prestadores con citas en Tareas_Programadas que no tienen fila en el catálogo. El left join en `feat_prestador` los descarta. Ver Observación O1 en Sección 9.

### Qué contiene

| Grupo              | Columnas clave                                                                                                  |
| ------------------ | --------------------------------------------------------------------------------------------------------------- |
| Ejecución de citas | `tasa_ejecucion`, `n_citas_total`, `duracion_promedio_ejecutada`, `duracion_total_ejecutada`                    |
| Cancelaciones      | `tasa_cancelacion`, `tasa_cancela_empresa`, `tasa_cancela_prestador`, `tasa_cancela_real_prestador`             |
| Diagnóstico cancel.| `n_cancela_sin_motivo`, `n_cancela_real_prestador` *(desglose del proxy de timeout del sistema)*                |
| Informes           | `tasa_aprobacion_informe`, `tasa_aprobacion_auto`, `dias_ciclo_informe_prom`                                    |
| Órdenes históricas | `n_oc_historicas`, `n_empresas_atendidas`, `costo_logistico_prom`, `n_municipios_destino`                       |
| Demanda atendida   | `sector_principal_atendido`, `segmento_principal_atendido`, `pct_empresa_compleja` *(perfil de clientes reales)*|

### Decisiones tomadas

---

**Decisión 4.1 — Definición de estados de éxito y cancelación**

Se clasificaron los estados de `DSESTADO_PROGRAMACION` en dos grupos:

- **Ejecutada (éxito):** `CITA EJECUTADA`, `PARCIALMENTE EJECUTADO`, `PARCIALMENTE COMPLETADO`
- **Cancelada:** `CITA CANCELADA`
- **Excluidos de ambos cálculos:** `PENDIENTE`, `EN PROCESO`, `AGENDADA` y otros estados intermedios

**Justificación:** Solo los estados con resultado definitivo aportan información confiable para los KPIs. Los estados intermedios no tienen resultado conocido y contaminarían las tasas si se incluyeran en el denominador.

**⚠️ Supuesto no confirmado (Q20):** se asumió que `PARCIALMENTE EJECUTADO` y `PARCIALMENTE COMPLETADO` son servicios entregados (facturables, que cumplen el SLA). Si desde el negocio una ejecución parcial equivale a una cancelación, estos estados deben moverse al grupo de canceladas, y `tasa_ejecucion` estaría sobreestimada para algunos prestadores.

**Esta pregunta debe hacerse en el encuentro.**

---

**Decisión 4.2 — Separación de registros CAMPO e INFORME**

`Tareas_Programadas` contiene dos tipos de registros con semántica distinta:
- `CAMPO` (1.18M filas, 76%): visitas de servicio presencial — la unidad de trabajo que el modelo quiere medir.
- `INFORME` (362K filas, 24%): envíos de documentos administrativos — no representan entrega de servicio.

Todos los KPIs de ejecución, cancelación y duración se calculan sobre registros `CAMPO` únicamente. Los KPIs de informes (`n_informes_enviados`, `tasa_aprobacion_informe`, etc.) se mantienen sobre todos los registros porque `FEENVIO_INFORME` puede estar poblado en cualquier tipo.

`n_programaciones_total` conserva el conteo de todos los registros; `pct_programaciones_campo` expresa el mix como feature del modelo.

**Justificación:** El ratio CAMPO/INFORME varía significativamente entre prestadores (std = 0.23, rango 0%–100%). Sin el filtro, un prestador con alta carga administrativa vería su `tasa_ejecucion` inflada porque las submissions de INFORME casi siempre tienen estado `CITA EJECUTADA`. Verificado en los datos: 457 prestadores tienen menos del 50% de sus programaciones como visitas de campo; 318 tienen exactamente 0% (solo INFORME).

---

**Decisión 4.3b — Denominador de `tasa_cancela_empresa`**

`tasa_cancela_empresa` usa `n_citas_total` (citas CAMPO) como denominador, igual que `tasa_cancelacion` y `tasa_cancela_prestador`.

**Justificación:** Con el mismo denominador se garantiza la propiedad aditiva: `tasa_cancela_empresa + tasa_cancela_prestador = tasa_cancelacion`. Las tres tasas son directamente comparables entre sí. El denominador anterior (`n_citas_canceladas`) respondía una pregunta distinta —composición de cancelaciones— que queda cubierta implícitamente por las otras métricas.

---

**Decisión 4.4 — Columna diagnóstica `n_duracion_nula_ejecutadas`**

Se agrega el conteo de citas CAMPO ejecutadas donde `DURACION` es nulo. `DURACION` tiene ~41% de nulos en el dataset completo; los nulos se excluyen silenciosamente del `sum()` y `mean()`, lo que subestima `duracion_total_ejecutada` y por ende `utilizacion_capacidad`.

**Justificación:** No es posible corregir el sesgo sin conocer la duración real de esas citas. La columna expone la severidad del problema por prestador: si un prestador tiene `n_duracion_nula_ejecutadas` alto, su `utilizacion_capacidad` debe interpretarse como límite inferior, no como valor exacto.

---

**Decisión 4.5 — Interpretación de `SNCANCELA_EMPRESA`**

Se interpretó el campo como: `True = la empresa cliente fue responsable de la cancelación`, lo que permite separar `tasa_cancela_empresa` (cancelaciones atribuibles al cliente) de `tasa_cancela_prestador` (todo lo demás).

**Justificación:** Esta separación es crítica para no penalizar a un prestador por cancelaciones que no son su responsabilidad. Un prestador puede tener alta tasa de cancelación no porque sea unreliable, sino porque le asignan empresas que cancelan sistemáticamente.

**⚠️ Supuesto de alto riesgo (Q19):** si el campo significa lo contrario (True = el prestador o el sistema canceló), los dos features `tasa_cancela_empresa` y `tasa_cancela_prestador` estarían **completamente invertidos**. Es el supuesto de mayor riesgo del modelo: los prestadores confiables aparecerían como problemáticos y viceversa.

**Esta pregunta es prioritaria en el encuentro.**

---

**Decisión 4.6 — Proxy de cancelaciones por timeout del sistema (`n_cancela_sin_motivo`)**

Se agrega el conteo `n_cancela_sin_motivo`: citas CAMPO canceladas donde `SNCANCELA_EMPRESA = False/null` **y** `MOTIVO_CANCELACION IS NULL`. A partir de este conteo se derivan `n_cancela_real_prestador` y `tasa_cancela_real_prestador`.

**Justificación:** Q&A 2026-04-11 confirmó que el 79,3% de las cancelaciones catalogadas como "causas del sistema" se deben a la **política de timeout automático**: OC sin gestión durante 2 meses se cancela automáticamente. Estas cancelaciones no son responsabilidad real del prestador pero quedaban absorbidas en `tasa_cancela_prestador`, penalizando injustamente a prestadores que atienden clientes difíciles de coordinar. El MOTIVO_CANCELACION tiende a quedar nulo en estas cancelaciones automáticas ("la mayoría está vacío o de cancelación por proceso de bajar colas desde SGS", Q&A transcripción). `tasa_cancela_real_prestador` reemplaza a `tasa_cancela_prestador` en `FEATURE_COLS` por ser una señal más limpia de fallo real del prestador.

**Limitación documentada:** `n_cancela_sin_motivo` es una heurística. Un prestador que cancela sin documentar el motivo también quedaría en este conteo, aunque su cancelación sea real y no un timeout. Se necesita exploración de los valores de `MOTIVO_CANCELACION` para refinar el proxy. `tasa_cancela_prestador` se conserva en `feat_prestador` para diagnóstico comparativo.

**Invariante:** `n_cancela_sin_motivo ≤ n_cancela_prestador` siempre (es un subconjunto).

---

**Decisión 4.7 — Perfil de demanda atendida (`_demanda_atendida()`)**

Se agrega la función `_demanda_atendida()` que une citas CAMPO ejecutadas (Tareas_Programadas) con el catálogo de empresas (Detalle_Empresa) para computar, por `DNI_PRESTADOR`: el sector económico predominante de los clientes atendidos (`sector_principal_atendido`), la segmentación ARL predominante (`segmento_principal_atendido`) y la fracción de citas en empresas de alta complejidad — Gran Empresa o Mediana Empresa — (`pct_empresa_compleja`).

**Justificación:** El Q&A 2026-04-11 confirmó que la **prioridad #1 de asignación es la especialización técnica** del prestador para el tipo de cliente. Sin embargo, el catálogo solo captura el perfil *declarado* (qué tareas está habilitado a ejecutar); no dice nada sobre qué tipos de empresas atiende realmente. `pct_empresa_compleja` cierra esta brecha: un prestador que consistentemente atiende Gran Empresa trabaja en un registro de complejidad diferente al que atiende Micro empresas o independientes, aunque ambos tengan el mismo `tipo_perfil` declarado. Esta feature entra directamente a `FEATURE_COLS` como feature numérica; las categóricas (`sector_principal_atendido`, `segmento_principal_atendido`) viajan como columnas de contexto en `clustering_input` para nombrar y validar los clústeres.

**Nota de implementación:** Solo se consideran citas CAMPO *ejecutadas* (no programadas, no canceladas). Captura el perfil de clientes *realmente servidos*, que es más informativo que el perfil de clientes asignados. La llave de join es `DNI_EMPRESA` (Tareas_Programadas) → `Empresa_Id` (Detalle_Empresa), confirmada como la misma entidad en ER_DIAGRAMA.md.

---

**Decisión 4.3 — Fuente de n_empresas_atendidas y n_oc_historicas**

`n_empresas_atendidas` se computa desde `Tareas_Programadas_canceladas_2025` (alcance operativo 2025). `n_oc_historicas` y `n_lineas_oc` se computan desde `Ordenado` (historial completo de órdenes de compra).

**Justificación:** Para el modelo de asignación, la cobertura de empresas _reciente_ es más informativa que la histórica: refleja la capacidad operativa actual del prestador, no contratos de años anteriores que pueden no ser representativos del estado actual. `n_oc_historicas` sí usa el historial completo porque el volumen acumulado de órdenes es un indicador de trayectoria y madurez en la red que sí se beneficia de la ventana larga.

**Nota de implementación:** El campo se calcula como `DNI_EMPRESA.n_unique()` sobre las programaciones 2025. No se usa `Ordenado` para este cómputo.

---

## 5. `feat_prestador` — Tabla maestra de la oferta

**Archivo:** `src/gold/feat_prestador.py`

**Fuente:** `feat_prestador_perfil` LEFT JOIN `feat_prestador_performance`

**Grano de salida:** 1 fila por `DNI_PRESTADOR` → **6.514 prestadores**

**Columnas:** 56

Esta es la tabla central del modelo de oferta. Integra en un único vector todo lo que se sabe de cada prestador: quién es técnicamente, cómo opera, qué tan cargado está y dónde trabaja.

### Decisiones tomadas

---

**Decisión 5.1 — LEFT JOIN desde perfil hacia performance (no al revés)**

La tabla `feat_prestador_perfil` es la tabla izquierda. Todos los prestadores del catálogo aparecen en el resultado, aunque no tengan actividad en 2025.

**Justificación:** El catálogo es la fuente de verdad de quién pertenece a la red. Un prestador habilitado que no tuvo actividad en 2025 sigue siendo parte de la red y su ausencia de actividad es en sí misma información relevante: puede ser capacidad ociosa o un prestador en proceso de retiro. Excluirlos en esta tabla eliminaría esa señal prematuramente.

**Relación con el reto (Q22):** si los 1.352 prestadores sin actividad de campo son capacidad ociosa disponible (y no inactivos definitivamente), su tratamiento en el modelo cambia radicalmente (ver Decisión 6.1).

---

**Decisión 5.2 — Feature `utilizacion_capacidad`**

`utilizacion_capacidad = duracion_total_ejecutada / capacidad_total_declarada`

Mide qué fracción de la capacidad declarada fue efectivamente usada en el período analizado.

**Justificación:** Es la feature que conecta la oferta técnica (lo que el prestador dice que puede hacer) con la realidad operativa (lo que realmente hizo). Es el indicador más directo de desbalance de carga: un prestador con `utilizacion_capacidad = 0.95` está sobrecargado; uno con `0.05` está subutilizado.

**⚠️ Supuesto no confirmado (Q18):** `duracion_total_ejecutada` está en horas acumuladas de 2025. Para que el ratio sea válido, `capacidad_total_declarada` debe estar en la misma unidad temporal. Si la capacidad del catálogo está declarada en horas mensuales, el denominador debería multiplicarse por 12 para compararse con un año completo de ejecución.

**Esta pregunta debe aclararse antes de entrenar el modelo.**

---

**Decisión 5.3 — Flag `FLAG_SIN_ACTIVIDAD_2025`**

Se marca como `True` en dos casos:
- `n_citas_total IS NULL`: prestador sin ningún registro en `Tareas_Programadas` (~225 prestadores).
- `n_citas_total == 0`: prestador que aparece en `Tareas_Programadas` pero únicamente con registros de tipo `INFORME`, sin ninguna visita de campo (318 prestadores verificados en los datos).

Condición: `n_citas_total IS NULL OR n_citas_total == 0`

**Justificación:** Con el filtro CAMPO introducido en Decisión 4.2, `n_citas_total` ya no es un conteo total sino un conteo de visitas presenciales. Un prestador con solo registros INFORME tendría `n_citas_total = 0` (no null), y sin esta condición adicional entraría al clustering como un punto anómalo con todas las métricas de desempeño de campo en cero.

**Relación con el reto (Q22):** si los prestadores marcados son capacidad disponible no asignada (y no inactivos definitivamente), excluirlos perpetúa el desbalance. En ese caso deben incorporarse como un clúster separado de "capacidad sin explotar".

---

## 6. `clustering_input` — Matriz lista para ML

**Archivo:** `src/gold/clustering_input.py`

**Fuente:** `feat_prestador` filtrado + codificado + imputado

**Grano de salida:** 1 fila por `DNI_PRESTADOR` activo en 2025

**Columnas:** 32 (1 ID + 22 features numéricas + 9 columnas de contexto)

Esta es la única tabla que recibe el notebook de modelado. Su responsabilidad es entregar un DataFrame numérico, sin nulos, listo para aplicar `StandardScaler` o `MinMaxScaler` y luego el algoritmo de clustering seleccionado.

### Las 22 features del modelo

| Dimensión             | Features                                                                                                                                                                                                  | Justificación de la dimensión                                        |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| **Técnica**           | `n_tareas_distintas`, `n_bloques_distintos`, `indice_especializacion`, `tipo_perfil_ord`                                                                                                                  | Amplitud y foco técnico declarado. `n_productos_distintos` eliminado: correlación > 0.85 con las otras dos — sobrepondera la dimensión en K-Means |
| **Geográfica**        | `n_municipios_cobertura`, `n_municipios_destino`, `ratio_cobertura_real`                                                                                                                                  | Alcance territorial declarado vs. real vs. su ratio                  |
| **Desempeño**         | `tasa_ejecucion`, `tasa_cancela_real_prestador`, `tasa_aprobacion_informe`, `tasa_aprobacion_auto`, `dias_ciclo_informe_prom`, `duracion_promedio_ejecutada`                                               | Calidad real de campo 2025. `tasa_cancela_real_prestador` excluye timeouts del sistema (Decisión 4.6)   |
| **Carga**             | `n_citas_total`, `n_empresas_atendidas`, `utilizacion_capacidad`, `pct_programaciones_campo`                                                                                                              | Volumen, cobertura y mix de trabajo del prestador                    |
| **Match demanda**     | `pct_empresa_compleja`                                                                                                                                                                                    | Fracción de citas en Gran/Mediana Empresa. Conecta perfil técnico con complejidad real de clientes atendidos (Decisión 4.7) |
| **Red y costo**       | `costo_logistico_prom`, `es_red_estrategica`, `n_redes`, `antiguedad_dias`                                                                                                                                | Posicionamiento en la red, costo y experiencia                       |

**Columnas de contexto (no entran al modelo):** `bloque_principal`, `clasificacion_predominante`, `tipo_perfil`, `tipo_red`, `municipio_base`, `dsoficina`, `nombre_distribuidor`, `sector_principal_atendido`, `segmento_principal_atendido`

### Decisiones tomadas

---

**Decisión 6.1 — Filtrar prestadores sin actividad en 2025**

Se excluyen del input de clustering los prestadores con `FLAG_SIN_ACTIVIDAD_2025 = True`.

**Justificación:** Las 16 features de desempeño no tienen valores reales para estos prestadores (serían imputaciones puras), lo que hace que el clustering los agrupe por los valores imputados y no por su comportamiento real. Incluirlos degradaría la calidad de los clústeres.

**⚠️ Supuesto con implicación estratégica (Q22):** si estos prestadores son capacidad disponible no asignada (y no inactivos definitivamente), excluirlos del modelo significa que el sistema nunca los considerará para nuevas asignaciones, perpetuando el desbalance actual. En ese caso deben incorporarse como un clúster separado de "capacidad sin explotar", posiblemente con un modelo de perfil técnico sin features de desempeño.

---

**Decisión 6.2 — Codificación ordinal de `DSTIPO_PERFIL`**

Se convirtió la variable categórica a numérica con la siguiente escala:

```
BASICO=1, TECNOLOGO=2, INTERMEDIO=3, PROFESIONAL=4, AVANZADO=5, EXPERTO=6, ESPECIALISTA=7
OTROS → imputación por mediana
```

**Justificación:** K-Means requiere variables numéricas. Se usó codificación ordinal (y no one-hot) porque se asume que estos perfiles forman una progresión de seniority o competencia técnica. La codificación ordinal preserva esa relación de orden y evita aumentar la dimensionalidad con 8 columnas binarias.

**⚠️ Supuesto crítico (Q17):** el orden de la escala fue inferido del nombre de los perfiles; no fue confirmado con SURA. Si la jerarquía real es diferente (por ejemplo, AVANZADO no es superior a PROFESIONAL, o el orden correcto es distinto), esta feature introduce un sesgo sistemático en el clustering.

**Esta pregunta de validación técnica es la más importante del encuentro.**

---

**Decisión 6.3 — Imputación diferenciada de nulos**

Se aplicaron dos estrategias distintas según el tipo de nulo:

- **Imputación por cero** para tasas y duraciones donde `NULL` significa "nunca ocurrió": `tasa_cancela_real_prestador`, `tasa_aprobacion_informe`, `tasa_aprobacion_auto`, `duracion_promedio_ejecutada`, `pct_empresa_compleja`, `costo_logistico_prom`, etc.
- **Imputación por mediana** para variables donde `NULL` significa "no se pudo calcular" y el cero no es el valor correcto: `dias_ciclo_informe_prom` (si no hay informes, no es que el ciclo sea 0 días), `tipo_perfil_ord` (si el perfil no está en el catálogo, se asigna el valor típico de la red).

**Justificación:** Imputar cero en una tasa que nunca se activó es correcto por conocimiento de dominio: si un prestador no tuvo cancelaciones, su tasa es efectivamente 0, no un valor desconocido. `pct_empresa_compleja = 0` para prestadores virtuales (FLAG_SOLO_VIRTUAL_2025) es correcto: sin visitas de campo ejecutadas no hay perfil de cliente complejo atendido. Imputar cero en el ciclo de informe sería incorrecto porque distorsionaría la distribución de una variable que sí tiene valores reales positivos.

---

**Decisión 6.4 — Normalización de features fuera de Gold, en el notebook**

La normalización de features NO se aplica en esta tabla. `clustering_input` entrega los valores en sus unidades originales.

**Justificación:** El escalado es parte del proceso de modelado, no de la preparación de datos. Aplicarlo en Gold impediría experimentar con distintas estrategias de normalización (StandardScaler, MinMaxScaler, RobustScaler, sin escalar) sin regenerar la tabla completa. El notebook puede aplicar el escalado que considere apropiado directamente sobre `clustering_input`.

**Relación con el reto:** Si el negocio confirma (vía Q24) que ciertas dimensiones deben tener mayor peso, el notebook puede aplicar escalado diferenciado por dimensión antes de K-Means, sin modificar Gold.

---

**Decisión 6.5 — Columnas de contexto separadas de features**

Las columnas `tipo_perfil`, `funcion_prestador`, `clasificacion_predominante`, `tipo_red`, `bloque_principal`, `municipio_base`, `dsoficina`, `nombre_distribuidor`, `sector_principal_atendido` y `segmento_principal_atendido` viajan en la tabla pero **no están en `FEATURE_COLS`**.

**Justificación:** Estas columnas son categóricas con cardinalidad alta o son texto descriptivo. No son apropiadas para K-Means directamente, pero son esenciales para interpretar y nombrar los clústeres una vez que el modelo entrega sus resultados. Tenerlas en la misma tabla evita hacer un join posterior en el notebook solo para labeling. `sector_principal_atendido` y `segmento_principal_atendido` se agregaron en la revisión de la capa Gold (ver §8b) como contexto de demanda atendida.

---

**Decisión 6.6 — Eliminación de `n_productos_distintos` de `FEATURE_COLS`**

Se eliminó `n_productos_distintos` del vector de features. Sigue existiendo en `feat_prestador` como columna informativa.

**Justificación:** Las tres features de amplitud técnica (`n_tareas_distintas`, `n_bloques_distintos`, `n_productos_distintos`) tienen correlación estimada > 0.85 entre sí, ya que las tareas son subconjunto de los bloques, y los bloques subconjunto de los productos. Conservarlas tres en la misma distancia euclidiana de K-Means triplica el peso implícito de la dimensión de amplitud respecto a desempeño y geografía. Se conserva `n_tareas_distintas` (mayor granularidad) y `n_bloques_distintos` (captura diversidad temática, relevante para el matching especialización-cliente).

---

**Decisión 6.7 — `tasa_cancela_real_prestador` reemplaza `tasa_cancela_prestador` en `FEATURE_COLS`**

`tasa_cancela_prestador` sigue existiendo en `feat_prestador` para diagnóstico, pero ya no entra al modelo de clustering. Su sucesor en `FEATURE_COLS` es `tasa_cancela_real_prestador`.

**Justificación:** Ver Decisión 4.6. `tasa_cancela_prestador` incluía el ruido de cancelaciones automáticas por timeout del sistema (~79,3% de las "causas del sistema" según Q&A). `tasa_cancela_real_prestador` filtra ese ruido restando `n_cancela_sin_motivo` del numerador. El resultado es una señal más informativa para separar prestadores confiables de los que genuinamente tienen problemas de gestión de citas.

---

## 7. Script de carga a BigQuery

**Archivo:** `scripts/load_to_bigquery_gold.py`

Orquesta la materialización de las 5 tablas Gold en el dataset `sura_clustering_processed` de BigQuery.

### Flujo de ejecución

```
build_perfil_features()       → BQ: feat_prestador_perfil
build_performance_features()  → BQ: feat_prestador_performance
build_prestador_features()    → BQ: feat_prestador
build_empresa_features()      → BQ: feat_empresa
build_clustering_input()      → BQ: clustering_input
```

El orden respeta las dependencias: `feat_prestador` depende de las dos primeras, y `clustering_input` depende de `feat_prestador`. `feat_empresa` es independiente.

Cada tabla se carga con `WRITE_TRUNCATE`: en cada ejecución se borra y reescribe completamente. No hay lógica de merge incremental porque los datasets fuente se consideran snapshots completos (no streams).

---

## 8. Resumen de supuestos que requieren validación

Los siguientes supuestos fueron necesarios para construir Gold. La columna **Estado** refleja el resultado del encuentro Q&A del 2026-04-11 con el equipo de SURA.

| #   | Supuesto                                                                          | Feature afectada                                 | Pregunta | Estado |
| --- | --------------------------------------------------------------------------------- | ------------------------------------------------ | -------- | ------ |
| 1   | `DSTIPO_PERFIL` tiene jerarquía BASICO → ESPECIALISTA                             | `tipo_perfil_ord`                                | Q17      | ⚠️ No preguntado — pendiente |
| 2   | `CAPACIDAD` está en horas del mismo período que `duracion_total_ejecutada`        | `utilizacion_capacidad`                          | Q18      | ⚠️ No preguntado — pendiente |
| 3   | `SNCANCELA_EMPRESA = True` significa que la empresa cliente canceló               | `tasa_cancela_empresa`, `tasa_cancela_prestador` | Q19      | ⚠️ No preguntado — alto riesgo |
| 4   | `PARCIALMENTE EJECUTADO` es un servicio entregado exitosamente                    | `tasa_ejecucion`, `tasa_cancelacion`             | Q20      | ⚠️ No preguntado — pendiente |
| 5   | `FECHA_INGRESO` registra la fecha de incorporación real a la red                  | `antiguedad_dias`                                | Q21      | ⚠️ No preguntado — pendiente |
| 6   | Los prestadores con `FLAG_SIN_ACTIVIDAD_2025` son inactivos (no capacidad ociosa) | Decisión de exclusión del clustering             | Q22      | ⚠️ No preguntado — pendiente |
| 7   | `PERFIL_TARIFA` (A,B,E,I,O,P,T,X) es nominal sin jerarquía                        | No incluida en features actualmente              | Q23      | ⚠️ No preguntado — bajo riesgo |
| 8   | `snnuevo_modelo = S` en Maestro indica tareas con distinción operativa real        | `pct_tareas_nuevo_modelo`                        | —        | ⚠️ Semántica desconocida — preguntar en próximo encuentro. Si es solo un flag de migración de sistema sin impacto operativo, eliminar de `FEATURE_COLS`. |

---

## 8b. Confirmaciones y ajustes del encuentro Q&A (2026-04-11)

### Confirmaciones que no requieren cambio de código

**ESTADO_EMPRESA — "Retirado = desafiliado" (Q3)**

Confirmado por SURA: `ESTADO_EMPRESA = "RETIRADO"` significa empresa desafiliada, sin cobertura activa. "En mora" significa cobertura vigente con deuda pendiente. Se agregó el flag `FLAG_EMPRESA_ACTIVA = (ESTADO_EMPRESA != "RETIRADO")` a `feat_empresa`. Las empresas retiradas no deben ser objetivo del modelo de asignación.

**Rutas de atención — LIVIANA = atención virtual (Q3)**

Confirmado: LIVIANA comprende empresas pequeñas, independientes y voluntarios. El modelo de atención es 100% virtual (documentos, herramientas digitales, mensajería). No generan visitas de campo. Esto valida el diseño actual de `nivel_complejidad_calculado` y explica por qué muchas empresas LIVIANA tienen `FLAG_SIN_DEMANDA_HISTORICA = True` en programaciones de campo.

**Implicación para el notebook:** el modelo de clustering de prestadores está orientado a visitas ESTÁNDAR, INTERVENCIÓN, AVANZADA y ESPECIALIZADA. Las empresas LIVIANA y SIN RUTA pueden excluirse del matching con prestadores de campo.

**Prioridad de asignación — Especialización > Capacidad > Geografía (Q6)**

Confirmado por SURA: la prioridad es (1) que el prestador tenga la especialidad técnica, (2) que tenga disponibilidad de tiempo, (3) que esté en la zona. No hay restricción geográfica estricta; la cercanía es un deseable, no un requisito.

**Implicación para el notebook:** la dimensión Técnica (`n_tareas_distintas`, `tipo_perfil_ord`, `indice_especializacion`) debe tener mayor peso relativo que la dimensión Geográfica en el escalado de features. En StandardScaler esto se puede lograr con escalado diferenciado por dimensión.

**Cancelaciones "causas del sistema" = política de timeout (Q8)**

Confirmado: el 79,3% de cancelaciones catalogadas como "causas del sistema" se deben a la **política de cancelación automática**: si una cita no es gestionada (no se llega a acuerdo entre cliente y proveedor) en el plazo establecido (antes 3 meses, ahora 2 meses), el sistema la cancela automáticamente.

**Implicación para `tasa_cancela_prestador`:** esta tasa incluye cancelaciones por timeout que no son responsabilidad directa del prestador. El valor absoluto de `tasa_cancela_prestador` sobreestima la "falla" del prestador. Para el modelo, es más informativa en términos comparativos (prestadores con tasa alta vs. baja entre sí) que en términos absolutos. La separación vía `SNCANCELA_EMPRESA` ya captura parte de la distinción, pero el timeout del sistema queda en el bucket del prestador.

**Relación OC → citas (Q2 confirmado)**

Una orden de compra puede tener tantas citas como sean necesarias. Si una cita se cancela, otra puede ser programada dentro de la misma OC. Esto valida el diseño de `feat_prestador_performance` que cuenta citas individuales como unidad de análisis, no órdenes.

### Cambios de código aplicados

| Cambio | Archivo | Detalle |
| ------ | ------- | ------- |
| Agregado `FLAG_EMPRESA_ACTIVA` | `src/gold/feat_empresa.py` | `True` si `ESTADO_EMPRESA != "RETIRADO"`. Basado en confirmación Q3. |
| Split de `FLAG_SIN_ACTIVIDAD_2025` | `src/gold/feat_prestador.py` | Se separó en dos flags: `FLAG_SIN_ACTIVIDAD_2025` (sin registro alguno en TP, ~225 prestadores) y `FLAG_SOLO_VIRTUAL_2025` (solo INFORME, sin campo, 318 prestadores). Los virtuales ahora se incluyen en el clustering. |
| Actualizado filtro clustering | `src/gold/clustering_input.py` | El filtro ahora excluye solo `FLAG_SIN_ACTIVIDAD_2025`. Los 318 prestadores virtuales entran al modelo y formarán su propio segmento. El universo sube de ~5.162 a ~5.480 prestadores. |
| Proxy timeout del sistema (M1) | `src/gold/feat_prestador_performance.py` | Agregados `n_cancela_sin_motivo`, `n_cancela_real_prestador`, `tasa_cancela_real_prestador`. Decisión 4.6. |
| Perfil de demanda atendida (M3) | `src/gold/feat_prestador_performance.py` | Nueva función `_demanda_atendida()` con join TP ← Detalle_Empresa. Agrega `sector_principal_atendido`, `segmento_principal_atendido`, `pct_empresa_compleja`. Decisión 4.7. |
| Propagación columnas nuevas | `src/gold/feat_prestador.py` | Select actualizado: +6 columnas de M1 y M3. |
| Depuración `FEATURE_COLS` (M2) | `src/gold/clustering_input.py` | Eliminado `n_productos_distintos` (correlación redundante). Decisión 6.6. |
| Reemplazo en `FEATURE_COLS` (M1) | `src/gold/clustering_input.py` | `tasa_cancela_prestador` → `tasa_cancela_real_prestador`. Imputación: añadida a `_imputar_cero`. Decisión 6.7. |
| Nueva feature en `FEATURE_COLS` (M3) | `src/gold/clustering_input.py` | `pct_empresa_compleja` añadida a `FEATURE_COLS` e `_imputar_cero`. Contexto: `sector_principal_atendido` y `segmento_principal_atendido` añadidos al select. Decisión 6.5. |

---

## 9. Estado final del modelo de datos Gold

```
BigQuery: sura_clustering_processed
│
├── feat_prestador_perfil      (6.514 filas × 28 cols)  — perfil técnico catálogo
├── feat_prestador_performance (6.576 filas × 37 cols)  — KPIs operativos 2025 (+6 cols: M1/M3)
├── feat_prestador             (6.514 filas × 67 cols)  — tabla maestra oferta (+6 cols: M1/M3)
├── feat_empresa               (2.175.102 filas × 38 cols) — tabla maestra demanda
└── clustering_input           (~5.480 filas × 32 cols) — input directo para ML (+2 context cols)
```

> **FEATURE_COLS activas (22 features):** `n_tareas_distintas`, `n_bloques_distintos`, `indice_especializacion`, `tipo_perfil_ord`, `n_municipios_cobertura`, `n_municipios_destino`, `ratio_cobertura_real`, `tasa_ejecucion`, `tasa_cancela_real_prestador`, `tasa_aprobacion_informe`, `tasa_aprobacion_auto`, `dias_ciclo_informe_prom`, `duracion_promedio_ejecutada`, `n_citas_total`, `n_empresas_atendidas`, `utilizacion_capacidad`, `pct_programaciones_campo`, `pct_empresa_compleja`, `costo_logistico_prom`, `es_red_estrategica`, `n_redes`, `antiguedad_dias`

### Observaciones de la primera carga a BigQuery

**O1 — 62 prestadores con actividad pero sin catálogo**

`feat_prestador_performance` tiene 6.576 filas pero el catálogo tiene 6.514. Existen 62 `DNI_PRESTADOR` que ejecutaron citas en 2025 y aparecen en Tareas_Programadas, pero no tienen fila en Tareas_prestador_bloque (catálogo). El left join desde el catálogo en `feat_prestador` los descarta silenciosamente — no entran al modelo.

Posibles causas: prestadores dados de baja del catálogo pero con citas pre-agendadas que se ejecutaron igual, errores de clave entre datasets, o registros temporales no consolidados. **Requiere verificación con SURA antes de entrenar:** si son prestadores válidos, su exclusión del modelo es un gap de cobertura. Si son basura, confirmar y documentar.

**O2 — Solo 5.162 de 6.514 prestadores entran al clustering (79%)**

1.352 prestadores del catálogo quedan excluidos por `FLAG_SIN_ACTIVIDAD_2025 = True`: no tuvieron ninguna visita de campo en 2025 (ya sea porque no aparecen en Tareas_Programadas, o porque sus programaciones fueron todas de tipo INFORME). Esto representa el 20.7% del catálogo declarado como inactivo en campo durante el año.

Implicación directa para el reto: el modelo de clustering se construye sobre el 79% activo. El 21% restante es capacidad que existe en el sistema pero no se usó — exactamente el desbalance que el reto quiere diagnosticar y corregir (ver Q22).

---

El siguiente paso es construir el notebook de modelado, que tome `clustering_input`, aplique normalización de features y explore técnicas de clustering (K-Means como línea base, más otras alternativas).

En cada técnica evaluar métricas internas para seleccionar el mejor modelo y número de clústeres. Unir los labels resultantes con las columnas de contexto de `clustering_input` y con `feat_empresa` para caracterizar cada clúster en términos de negocio.
