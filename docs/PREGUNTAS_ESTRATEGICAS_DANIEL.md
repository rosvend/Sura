# Preguntas Estratégicas para el Encuentro con SURA (Daniel)

> Preguntas de negocio orientadas a obtener información clave para el diseño del modelo de clústeres de prestadores y la solución de asignación.
>
> Cada pregunta incluye: **qué información se busca extraer** y **cómo aporta al reto**.
>
> La **Sección 8** contiene preguntas puntuales para validar supuestos asumidos al construir la capa Gold del modelo. Si alguno de esos supuestos es incorrecto, las features derivadas deben recalcularse antes de entrenar.

---

## 1. Criterios de éxito — ¿Qué define una "buena asignación"?

---

**P1.** ¿Cuál es el indicador de negocio que más dolor genera hoy en el modelo de asignación? ¿Es la velocidad de asignación, la tasa de cancelación, la distancia recorrida, o la satisfacción de la empresa cliente?

> **Busca:** Identificar cuál es la variable que el negocio quiere optimizar por encima de las demás.
>
> **Utilidad para el reto:** Define la función objetivo del modelo. Si el dolor es velocidad → el clúster debe priorizar disponibilidad y carga. Si es cancelación → `tasa_cancela_prestador` debe tener mayor peso en las features. Si es distancia → la dimensión geográfica (`n_municipios_cobertura`, `municipio_base`) pasa a ser crítica. Sin esta respuesta, el modelo optimiza variables que pueden no importarle al negocio.

---

**P2.** ¿Cómo sabe SURA si una asignación fue exitosa? ¿Existe un indicador formal de calidad post-servicio (CSAT, NPS, evaluación del prestador)? ¿Ese dato está disponible para el análisis?

> **Busca:** Determinar si existe una variable de calidad percibida asociada al prestador que no esté en los datasets actuales.
>
> **Utilidad para el reto:** Si existe un score de satisfacción por prestador, se convierte en la variable de validación más poderosa del modelo: un buen clúster de "alto rendimiento" debería correlacionar con alta satisfacción. También podría usarse como etiqueta para un enfoque supervisado. Si no existe, confirma que el modelo debe ser puramente no supervisado y que la validación será interna (silhouette, interpretabilidad de centroides).

---

**P3.** ¿Qué trade-off es prioritario para el negocio: asignar al prestador más cercano (eficiencia logística), al más especializado (calidad técnica), o al con menor carga actual (balance operativo)?

> **Busca:** Establecer la jerarquía de dimensiones del modelo antes de entrenar.
>
> **Utilidad para el reto:** Informa directamente qué bloques de features deben tener mayor peso relativo en el clustering. Las features están organizadas en cuatro dimensiones (técnica, geográfica, desempeño, carga). Si el negocio prioriza especialización, las features técnicas (`indice_especializacion`, `tipo_perfil_ord`) deben liderar. Si prioriza balance, `utilizacion_capacidad` y `n_citas_total` son las protagonistas. Esto puede implementarse ajustando el escalado o aplicando pesos antes del StandardScaler.

---

## 2. El proceso actual — ¿Cómo funciona la asignación hoy?

---

**P4.** ¿Quién toma la decisión de asignación hoy y con qué información? ¿Hay un equipo centralizado, una herramienta, reglas fijas, o depende del criterio personal del coordinador?

> **Busca:** Entender si hay reglas implícitas de asignación que el modelo debe capturar o reemplazar.
>
> **Utilidad para el reto:** Si los coordinadores usan criterios tácitos ("siempre asigno al prestador X para empresas de construcción"), esos criterios pueden convertirse en features o restricciones de negocio del modelo. Además, conocer el proceso actual define qué tan disruptiva es la solución propuesta y qué nivel de adopción se puede esperar.

---

**P5.** ¿Cuánto tiempo demora una asignación desde que la empresa la solicita hasta que el prestador recibe la orden? ¿Cuál sería el tiempo objetivo con el nuevo modelo?

> **Busca:** Determinar si el modelo debe operar en tiempo real, en batch diario, o en ciclos semanales.
>
> **Utilidad para el reto:** Define la arquitectura de despliegue del prototipo. Si la asignación debe ser en minutos → se necesita una API de scoring. Si puede ser batch → un proceso nocturno es suficiente. También pone un benchmark concreto contra el cual medir el impacto de la solución más allá de las métricas técnicas del modelo.

---

**P6.** ¿Qué pasa cuando un prestador cancela una cita? ¿Existe un proceso de reasignación formal? ¿Hay un prestador de respaldo predefinido? ¿Quién absorbe el costo del retraso?

> **Busca:** Saber si el modelo debe producir un ranking de prestadores (primario + alternativas) o solo una asignación única.
>
> **Utilidad para el reto:** Si no hay respaldo formal, el output del modelo debería ser un top-N de prestadores por clúster compatible, no solo el primero. Esto mejora la resiliencia del sistema sin complejidad adicional y puede presentarse como una ventaja directa de la solución sobre el proceso actual.

---

**P7.** ¿Las empresas pueden rechazar o solicitar un cambio de prestador asignado? Si sí, ¿con qué frecuencia ocurre y cuál es el motivo más común?

> **Busca:** Identificar si existe una señal de calidad de asignación implícita en los datos transaccionales.
>
> **Utilidad para el reto:** Los rechazos de empresa son un proxy de asignación fallida. Si ese dato existe (aunque no esté en los datasets actuales), puede usarse como variable de validación del modelo. Si es frecuente en ciertos segmentos, indica que la compatibilidad empresa-prestador tiene dimensiones que los datos actuales no capturan bien (ej. idioma, cultura sectorial, histórico de conflictos).

---

## 3. Restricciones de negocio — ¿Qué el modelo NO puede violar?

---

**P8.** ¿Existen empresas o grupos económicos que tienen prestadores dedicados y exclusivos? Si es así, ¿son negociables o son restricciones duras que el modelo debe respetar siempre?

> **Busca:** Delimitar el universo real sobre el que opera el modelo.
>
> **Utilidad para el reto:** Si el 20% de las empresas ya tienen prestador fijo, el modelo solo debe resolver el 80% restante. No saberlo llevaría a proponer reasignaciones que operativamente son imposibles, haciendo la solución inviable. Estos casos podrían modelarse como un clúster separado ("dedicados") o simplemente excluirse del scope.

---

**P9.** ¿Hay regulaciones o compromisos contractuales que determinen qué tipo de prestador debe atender a ciertos sectores económicos?

> **Busca:** Identificar restricciones de compatibilidad sector-prestador que no son inferibles de los datos.
>
> **Utilidad para el reto:** Si minería solo puede ser atendida por prestadores con certificación ESPECIALISTA, eso no está en los datasets actuales y debe modelarse como una capa de filtrado pre-asignación. Sin esta información, el modelo podría generar asignaciones técnicamente óptimas pero contractualmente inválidas.

---

**P10.** ¿La ruta de atención (LIVIANA, ESTÁNDAR, AVANZADA, ESPECIALIZADA) es asignada por SURA o la empresa puede cambiarla? ¿Podría el modelo proponer que una empresa suba de ruta si los datos muestran alta complejidad de servicio?

> **Busca:** Determinar si `Ruta_Atencion` es una variable de entrada (restricción fija) o una variable de salida (recomendación) del modelo.
>
> **Utilidad para el reto:** Si la ruta es dinámica, el modelo puede añadir una dimensión de valor adicional: no solo "qué clúster de prestadores asignar", sino "si esta empresa debería estar en una ruta más alta". Esto enriquece la propuesta de solución. Si es fija, se usa únicamente como variable de segmentación de la demanda en `feat_empresa`.

---

**P11.** ¿Qué significa en la práctica pertenecer a la Red Estratégica versus las Redes de Apoyo, Comercial u Operaciones?

> **Busca:** Entender el significado operativo de `TIPO_DE_RED`, que actualmente es un campo categórico con 7 valores en el catálogo.
>
> **Utilidad para el reto:** Si la Red Estratégica implica prestadores con mayor nivel de compromiso, disponibilidad o tarifa diferencial, entonces `es_red_estrategica` (feature binaria ya incluida en el modelo) tiene un peso de negocio concreto. Si los distintos tipos de red tienen reglas de asignación distintas, el modelo podría necesitar clústeres separados por red en lugar de mezclarlos.

---

## 4. Dinámica prestador-empresa — La relación de largo plazo

---

**P12.** ¿Es estratégico para el negocio que una empresa siempre sea atendida por el mismo prestador? ¿Qué tan relevante es la "memoria relacional" entre prestador y empresa?

> **Busca:** Determinar si la continuidad de la relación es un criterio de asignación que el modelo debe preservar.
>
> **Utilidad para el reto:** Si la continuidad es valorada, el modelo de asignación debe incluir un componente de afinidad histórica: ¿cuántas veces ha atendido este prestador a esta empresa antes? Ese dato existe implícitamente en `Tareas_Programadas` y `Ordenado`. Si no importa, se simplifica el motor de asignación y el clustering puro es suficiente.

---

**P13.** ¿Existen prestadores "ancla" que la estrategia de clústeres debe proteger? Los datos muestran que 2 prestadores concentran el 34,4% de todas las órdenes históricas.

> **Busca:** Saber si esa concentración extrema es una decisión estratégica deliberada o un síntoma del problema que se quiere resolver.
>
> **Utilidad para el reto:** Si es deliberada, el modelo debe respetar esa concentración o al menos no fragmentarla sin autorización. Si es un accidente del modelo actual, el rebalanceo de carga se convierte en un objetivo explícito del clustering, y el índice de Gini (0,757 → objetivo de reducirlo) es la métrica de impacto de negocio más directa del reto.

---

**P14.** ¿Qué le pasa al negocio si un prestador estratégico abandona la red? ¿Existe un plan de contingencia?

> **Busca:** Evaluar la resiliencia actual del sistema y si el modelo debe garantizar redundancia dentro de cada clúster.
>
> **Utilidad para el reto:** Si no hay plan de contingencia, el modelo puede añadir una restricción de diseño: ningún clúster debe depender de un único prestador para más del X% de su capacidad. Esto convierte al clustering en una herramienta de gestión de riesgo operacional, un argumento de negocio mucho más potente que la eficiencia.

---

## 5. Cancelaciones — El problema más costoso

---

**P15.** ¿Cuál es el costo real para SURA de una cita cancelada? ¿Hay penalidades contractuales, impacto medible en la relación con la empresa, o costo logístico de reasignación?

> **Busca:** Cuantificar el impacto económico de las cancelaciones para dimensionar el ROI de la solución.
>
> **Utilidad para el reto:** Si se conoce el costo unitario por cancelación, y el modelo reduce la tasa de cancelación en X puntos porcentuales, se puede estimar el ahorro anual concreto. Los datos muestran 229.824 cancelaciones en 2025. Incluso una reducción del 10% representaría ~23.000 citas recuperadas. Ese número convierte el modelo de un ejercicio técnico a un caso de negocio con cifras.

---

**P16.** Las cancelaciones que los datos clasifican como "causas del sistema" representan el 79,3% del total. ¿A qué se deben principalmente desde la perspectiva operativa?

> **Busca:** Determinar qué fracción de las cancelaciones es evitable con mejor asignación.
>
> **Utilidad para el reto:** Si las cancelaciones del sistema son principalmente por sobrecarga del prestador, el feature `utilizacion_capacidad` es el más importante del modelo y reducirlo es el objetivo central. Si son por incapacidades o causas externas, el modelo de clustering no puede reducirlas y el argumento de impacto debe ajustarse. Esta respuesta define qué tan ambicioso puede ser el modelo en sus promesas de reducción.

---

**P17.** ¿Hay empresas que cancelan de forma sistemática y SURA lo tolera por su importancia comercial? ¿Debe el modelo penalizar o premiar prestadores según el comportamiento histórico de la empresa que atienden?

> **Busca:** Identificar si la tasa de cancelación de un prestador está contaminada por el perfil de sus empresas asignadas.
>
> **Utilidad para el reto:** Este es un sesgo crítico de los datos: un prestador puede aparecer con alta tasa de cancelación no porque sea malo, sino porque le asignan empresas que sistemáticamente cancelan. La variable `tasa_cancela_como_cliente` en `feat_empresa` ya existe en el modelo Gold. Confirmar que este fenómeno ocurre justifica incluirla en el motor de asignación y mejora la equidad del modelo hacia los prestadores.

---

## 6. Visión del clúster — ¿Cómo se usará la solución?

---

**P18.** Una vez que el modelo identifique perfiles de prestadores, ¿cómo se incorporará al proceso operativo? ¿El sistema propone y un humano aprueba, o se busca asignación automática?

> **Busca:** Definir el nivel de automatización requerido y el modelo de interacción persona-sistema.
>
> **Utilidad para el reto:** Define la arquitectura del prototipo. Si es "propone y humano aprueba" → el output es un dashboard o reporte con recomendaciones explicables. Si es automático → se necesita una API de scoring con latencia baja. El nivel de explicabilidad requerido también cambia: en modo manual, los centroides de los clústeres deben ser interpretables por un coordinador no técnico.

---

**P19.** ¿Cuántos clústeres de prestadores serían manejables operativamente para el equipo?

> **Busca:** Alinear el parámetro K del modelo con la capacidad real de adopción del equipo operativo.
>
> **Utilidad para el reto:** Si el equipo puede manejar máximo 5 segmentos, K=5 es el techo del modelo aunque el método del codo sugiera K=8. Un modelo técnicamente óptimo pero operativamente inmanejable no se adopta. Esta respuesta convierte una decisión matemática (elección de K) en una decisión de negocio, y permite presentar el trade-off de forma honesta y colaborativa.

---

**P20.** ¿El objetivo es asignar empresas a clústeres de prestadores (regla general), o recomendar un prestador individual específico para cada empresa (recomendación puntual)?

> **Busca:** Definir el alcance y la granularidad del output del modelo.
>
> **Utilidad para el reto:** Si el output es "clúster compatible", el modelo de clustering es suficiente y el prototipo es alcanzable en el tiempo del reto. Si el output debe ser un prestador específico, se necesita un segundo nivel (ranking o matching dentro del clúster), lo que aumenta la complejidad. Esta respuesta define si la solución final es un modelo o un sistema de dos capas.

---

## 7. Evolución y sostenibilidad del modelo

---

**P21.** ¿Con qué frecuencia se prevé recalibrar el modelo? ¿Los clústeres deben ser estables por meses o años, o actualizarse con cada nuevo ciclo de datos?

> **Busca:** Definir si se necesita un pipeline de reentrenamiento automático o un modelo estático con revisión periódica.
>
> **Utilidad para el reto:** Si los clústeres deben actualizarse mensualmente, el prototipo debe incluir un pipeline automatizado (ya existe `load_to_bigquery_gold.py` como base). Si son anuales, un modelo estático es suficiente y el foco del prototipo puede estar en la interpretabilidad y el dashboard de monitoreo en lugar de en la automatización del reentrenamiento.

---

**P22.** ¿La brecha de municipios sin prestador local es un problema activo que SURA quiere resolver? Los datos muestran 665 municipios con demanda pero sin prestador local.

> **Busca:** Saber si el modelo debe informar decisiones de expansión de red o solo optimizar la red existente.
>
> **Utilidad para el reto:** Si es un problema activo, el modelo puede ir más allá del clustering de asignación y ofrecer un mapa de brechas: "en estos 665 municipios se necesita un prestador del clúster X para cubrir la demanda existente". Esto amplía significativamente el valor de negocio de la solución y la diferencia de propuestas que solo optimizan la asignación dentro de la red actual.

---

**P23.** ¿Existe alguna iniciativa para crear perfiles de prestadores especializados en segmentos específicos como empresa nueva o microempresa? El 11,4% del portafolio son empresas desafiliadas.

> **Busca:** Determinar si los clústeres deben ser cross-sector (prestador sirve todo tipo de empresa) o sector-específicos.
>
> **Utilidad para el reto:** Si SURA quiere prestadores especializados por segmento, los clústeres deben construirse cruzando el perfil del prestador con el perfil de las empresas que históricamente ha atendido bien (join entre `clustering_input` y `feat_empresa`). Esto añade una dimensión de compatibilidad al modelo que los datos ya permiten calcular. El 11,4% de empresas desafiliadas es además una oportunidad de negocio cuantificable: si se identifica el clúster de prestadores con mejor tasa de retención de ese segmento, se puede proponer una estrategia de reactivación basada en datos.

---

## 8. Validación de supuestos técnicos — Decisiones tomadas en la capa Gold

> Esta sección contiene preguntas específicas para confirmar o corregir supuestos asumidos durante la construcción del modelo de datos. A diferencia de las secciones anteriores, **cada respuesta incorrecta implica recalcular una o más features antes de entrenar el modelo**.

---

**P24.** En el catálogo de prestadores, los perfiles `DSTIPO_PERFIL` se codificaron con la jerarquía BÁSICO → TECNÓLOGO → INTERMEDIO → PROFESIONAL → AVANZADO → EXPERTO → ESPECIALISTA (de menor a mayor). ¿Esa progresión refleja fielmente los niveles de competencia o seniority que maneja SURA internamente?

> **Busca:** Confirmar o corregir el orden ordinal del campo más influyente del perfil técnico del prestador.
>
> **Impacto si el supuesto es incorrecto:** La feature `tipo_perfil_ord` introduce un sesgo sistemático en el clustering. Un prestador AVANZADO podría estar siendo posicionado por encima de uno PROFESIONAL cuando en realidad son equivalentes o el orden es inverso. Requiere recodificar `_TIPO_PERFIL_ORD` en `src/gold/clustering_input.py` y regenerar la tabla Gold antes de entrenar.

---

**P25.** El campo `CAPACIDAD` del catálogo de prestadores tiene valores entre 0 y 240, interpretados como horas de disponibilidad. ¿Esas horas corresponden a un período mensual, trimestral, o anual?

> **Busca:** Confirmar la unidad temporal de la capacidad declarada para que sea comparable con la duración ejecutada (también en horas).
>
> **Impacto si el supuesto es incorrecto:** El feature `utilizacion_capacidad = duracion_total_ejecutada / capacidad` solo es válido si ambas magnitudes están en la misma unidad de tiempo. Si la capacidad es mensual pero la duración ejecutada es anual (2025 completo), la utilización calculada está inflada en un factor de 12. Requiere ajustar el denominador antes de entrenar.

---

**P26.** En el dataset de tareas programadas, el campo `SNCANCELA_EMPRESA` fue interpretado como: `True = la empresa cliente fue responsable de la cancelación`, `False/nulo = causa interna del sistema o del prestador`. ¿Es correcta esa lectura?

> **Busca:** Confirmar el significado del campo para asegurar que los features `tasa_cancela_empresa` y `tasa_cancela_prestador` estén calculados en la dirección correcta.
>
> **Impacto si el supuesto es incorrecto:** Si el campo significa lo contrario (True = el prestador canceló), los dos features estarían completamente invertidos: los prestadores "confiables" aparecerían como problemáticos y viceversa. Es uno de los supuestos de mayor riesgo del modelo.

---

**P27.** Los estados `PARCIALMENTE EJECUTADO` y `PARCIALMENTE COMPLETADO` se incluyeron como ejecuciones exitosas al calcular `tasa_ejecucion`. Desde la perspectiva operativa y de facturación, ¿una ejecución parcial cuenta como servicio entregado o se trata como una cancelación?

> **Busca:** Definir si los servicios parciales son "éxito degradado" o "fallo".
>
> **Impacto si el supuesto es incorrecto:** Si las ejecuciones parciales son equivalentes a cancelaciones, `tasa_ejecucion` está sobreestimada para los prestadores con alto porcentaje de parciales, y `tasa_cancelacion` está subestimada. Requiere reclasificar esos estados en `src/gold/feat_prestador_performance.py` y regenerar Gold.

---

**P28.** La antigüedad de cada prestador (`antiguedad_dias`) se calculó desde el campo `FECHA_INGRESO` del catálogo. ¿Esa fecha registra cuándo el prestador ingresó a la red de SURA, o puede ser una fecha de última actualización del registro?

> **Busca:** Confirmar que la antigüedad calculada mide experiencia real en la red, no un artefacto administrativo del sistema.
>
> **Impacto si el supuesto es incorrecto:** Si `FECHA_INGRESO` es una fecha de actualización del sistema, `antiguedad_dias` es ruido en lugar de señal y debe eliminarse de `FEATURE_COLS` en `clustering_input.py` para no degradar el modelo.

---

**P29.** Los ~225 prestadores sin actividad registrada en 2025 fueron excluidos del input de clustering (`FLAG_SIN_ACTIVIDAD_2025 = True`). ¿Son prestadores definitivamente inactivos (dados de baja), o simplemente prestadores habilitados que no recibieron asignaciones durante ese período?

> **Busca:** Determinar si esos prestadores deben estar fuera del modelo o si precisamente son el problema que el modelo debería resolver.
>
> **Impacto si el supuesto es incorrecto:** Si son prestadores disponibles con capacidad ociosa, excluirlos del clustering es contraproducente: el modelo no los considerará nunca para nuevas asignaciones, perpetuando el desbalance actual. En ese caso deben incluirse con imputation de variables de desempeño y tratarse como un clúster separado de "capacidad sin explotar".

---

**P30.** Los valores de `PERFIL_TARIFA` (A, B, E, I, O, P, T, X) se trataron como categorías nominales sin jerarquía. ¿Existe una progresión o ranking entre estos perfiles tarifarios que refleje nivel de servicio o costo?

> **Busca:** Determinar si `PERFIL_TARIFA` tiene una dimensión ordinal útil para el clustering.
>
> **Impacto si el supuesto es incorrecto:** Si existe una jerarquía (ej. T > A en nivel de servicio), el campo debería codificarse ordinalmente al igual que `DSTIPO_PERFIL`, añadiendo una dimensión económica al vector de features que actualmente no está capturada. Podría ser un discriminador importante entre clústeres de alto y bajo valor.
