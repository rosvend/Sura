# Preguntas para Q&A con ARL SURA

Este documento reúne preguntas de entendimiento de negocio para la sesión de Q&A con ARL SURA del **2026-04-10**, dentro del reto de clustering de prestadores de servicios de salud. El enfoque es exclusivamente de negocio y necesidades del cliente — no hay preguntas técnicas sobre datos, esquema o herramientas. El objetivo es cerrar los vacíos que no pudieron resolverse leyendo `RETO.md`, `DESCRIPCION_DATOS.md` ni `DIAGNOSTICO_ANALISIS.md`. Cada pregunta incluye una justificación corta para facilitar la priorización en la reunión interna de hoy donde el equipo seleccionará el set final.

---

## 1. Flujo operativo end-to-end

**Q1. ¿Podrían caminarnos por el ciclo completo de un servicio, desde que una empresa cliente tiene una necesidad hasta que la tarea se factura/legaliza? ¿En qué punto del flujo aparece por primera vez un registro de la orden, y en qué punto aparece la programación de la cita?**
*Resuelve la duda central: cómo se relacionan las tablas en términos de eventos de negocio, no de llaves foráneas.*

**Q2. ¿Qué dispara la creación de una orden de compra? ¿Es automático a partir del plan de prevención de la empresa, lo solicita la empresa cliente directamente, o lo genera un asesor o empleado de Sura?**
*Sin conocer el trigger, no podemos modelar ni predecir la demanda.*

**Q3. ¿Una misma orden de compra puede generar múltiples citas programadas? Por ejemplo, si la primera cita se cancela, ¿se crea una nueva programación dentro de la misma orden o se genera una orden nueva?**
*Define si la relación orden-cita es 1:1 o 1:N y cómo interpretar los reintentos.*

---

## 2. Empresas afiliadas — ¿qué significan realmente?

**Q4. ¿Qué significa exactamente que una empresa esté "afiliada" a ARL SURA? Vemos alrededor de 2.1 millones de registros de empresas, pero cerca del 70% tienen cero afiliados activos. ¿Son clientes actuales, históricos, prospectos, o una mezcla? ¿Cuáles deberían estar dentro del alcance del modelo de clustering?**
*Sin esto, el universo de clientes del modelo es ambiguo — podríamos estar clusterizando empresas que ya no existen operativamente.*

**Q5. La ruta de atención tiene tres valores: LIVIANA, ESTÁNDAR y SIN RUTA. ¿Quién decide qué ruta recibe una empresa, bajo qué criterios, y qué diferencia concreta experimenta la empresa entre una ruta y otra? ¿Puede una empresa cambiar de ruta con el tiempo?**
*Es probablemente una feature clave del modelo, pero no sabemos qué representa en el mundo real ni qué la determina.*

**Q6. Cada empresa tiene asignado un profesional principal. ¿Qué rol cumple este profesional en la práctica — es una asignación permanente, un fallback por defecto, o un simple registro histórico? ¿Por qué alrededor del 16% de las empresas no tiene uno asignado?**
*Si existe una pareja fija empresa-asesor, el clustering tiene que respetarla o justificar muy bien cuándo romperla.*

**Q7. ¿Qué diferencias operativas reales hay entre los segmentos "Gran Empresa", "Mediana", "Micro", "Independiente" y "Empresa Nueva"? ¿El modelo de asignación actual los trata de forma distinta, y deberíamos nosotros hacer lo mismo?**
*Permite entender si el clustering debe respetar la segmentación existente o proponer una alternativa.*

---

## 3. Prestadores y capacidad

**Q8. Cuando hablamos de un "prestador", ¿a qué nos referimos en el día a día — una firma, un contratista individual, un empleado directo de Sura, o una mezcla? ¿Qué tipo de relación contractual tienen las firmas prestadoras con Sura (comisión, tarifa fija, exclusividad, tercerización pura)?**
*La naturaleza del prestador cambia completamente cómo se debe modelar el lado de la oferta.*

**Q9. ¿Cómo se determina y actualiza el perfil de un asesor (Básico, Medio, Avanzado, Especializado)? ¿Existen tareas o tipos de empresa que por ley, contrato o política interna solo pueden ser atendidas por un perfil específico?**
*Busca identificar restricciones duras que el modelo no puede violar sin importar qué tan óptima sea su recomendación.*

**Q10. El tipo de red (Estratégica vs. Apoyo) ¿refleja prioridad de asignación, exclusividad geográfica, tipo de contrato, o algo más? ¿Una red de "Apoyo" solo se usa cuando la "Estratégica" no da abasto, o se usan en paralelo?**
*Impacta directamente la lógica de prioridad del modelo de asignación.*

---

## 4. Cancelaciones y ciclo de vida

**Q11. Cuando una cita se cancela, ¿qué pasa después desde el punto de vista del negocio? ¿Se reprograma con el mismo asesor, se reasigna a otro, o se debe crear una orden completamente nueva? ¿Y qué pasa a nivel de la orden padre — queda abierta, se cierra parcialmente, cambia de estado?**
*Necesario para medir el verdadero "costo" de una cancelación y entender la cascada de efectos.*

**Q12. ¿Quién asume el costo cuando el prestador cancela versus cuando la empresa cancela? ¿Hay penalidades económicas, impactos en la calificación del asesor, o consecuencias para la empresa cliente?**
*Si hay penalidad económica, reducir cancelaciones se traduce directamente en dinero ahorrado — un caso de negocio concreto para el proyecto.*

**Q13. De los múltiples estados que tiene una orden (Facturado, Legalizado, Aprobado, Cancelado, Bloqueado, etc.), ¿cuáles son secuenciales y cuáles son terminales? ¿Qué estado representa "éxito total" desde el punto de vista del negocio, y cuáles representan éxito parcial o fracaso?**
*Sin saber qué es "éxito" a nivel de orden, no podemos construir una métrica de evaluación para el modelo.*

---

## 5. Definición de éxito y uso del modelo

**Q14. Si tuvieran que escoger UNA sola métrica que, al mejorar significativamente, haría que este proyecto fuera considerado un éxito claro e indiscutible — ¿cuál sería? ¿Reducción de cancelaciones, tiempo de asignación, costo logístico, satisfacción del cliente, aprovechamiento de capacidad, o alguna otra?**
*Los documentos listan muchas KPIs propuestas — necesitamos saber cuál le importa más al negocio para priorizar el diseño del modelo.*

**Q15. ¿Quién va a usar el modelo de clustering en la práctica — un analista humano que revisa recomendaciones, un sistema automatizado que asigna sin intervención, o un gerente que toma decisiones estratégicas de mediano plazo? ¿Las recomendaciones serán vinculantes o solo orientativas?**
*Determina el formato del entregable, el nivel de explicabilidad requerido y cuánta fricción puede tolerar el usuario final.*

**Q16. ¿Existen restricciones de negocio, contractuales o regulatorias que el modelo TIENE que respetar obligatoriamente? Por ejemplo: contratos exclusivos entre ciertos prestadores y ciertas empresas, SLAs mínimos de tiempo de respuesta, o reglas políticas/geográficas sobre qué firma atiende qué región.**
*Estas son las restricciones duras — violarlas invalida el modelo por completo sin importar qué tan buenos sean los clusters.*

---

## 6. Validación de supuestos técnicos — Capa Gold (Fase 1: limpieza de datos)

> Estas preguntas validan supuestos asumidos al construir las features del modelo. Una respuesta incorrecta en cualquiera de ellas implica recalcular una o más features antes de entrenar.

**Q17. La jerarquía de perfiles `DSTIPO_PERFIL` en el catálogo se codificó con el orden: BÁSICO → TECNÓLOGO → INTERMEDIO → PROFESIONAL → AVANZADO → EXPERTO → ESPECIALISTA (de menor a mayor seniority). ¿Esa progresión refleja fielmente los niveles de competencia que maneja SURA internamente?**
*Si el orden es incorrecto, la feature `tipo_perfil_ord` introduce un sesgo sistemático en el clustering. Es la pregunta de validación técnica más importante del encuentro.*

**Q18. El campo `CAPACIDAD` del catálogo tiene valores entre 0 y 240, interpretados como horas de disponibilidad. ¿Corresponden a un período mensual, trimestral o anual?**
*La feature `utilizacion_capacidad = duracion_ejecutada / capacidad_declarada` solo es válida si ambas magnitudes están en la misma unidad temporal. Si la capacidad es mensual pero la duración ejecutada es anual (2025 completo), el ratio está inflado en un factor de 12.*

**Q19. En el dataset de tareas programadas, ¿`SNCANCELA_EMPRESA = True` significa que la empresa cliente fue responsable de la cancelación?**
*Si el campo significa lo contrario (True = el prestador o el sistema canceló), las features `tasa_cancela_empresa` y `tasa_cancela_prestador` estarían completamente invertidas. Es el supuesto de mayor riesgo del modelo: los prestadores confiables aparecerían como problemáticos.*

**Q20. Los estados `PARCIALMENTE EJECUTADO` y `PARCIALMENTE COMPLETADO` se contabilizaron como citas exitosas al calcular `tasa_ejecucion`. Desde el punto de vista operativo y de facturación, ¿una ejecución parcial cuenta como servicio entregado o se trata como una cancelación?**
*Si las ejecuciones parciales son fallos, `tasa_ejecucion` está sobreestimada para prestadores con alto porcentaje de parciales y `tasa_cancelacion` está subestimada. Requiere reclasificar esos estados y regenerar Gold.*

**Q21. El campo `FECHA_INGRESO` del catálogo se usó para calcular la antigüedad de cada prestador en la red (`antiguedad_dias`). ¿Esa fecha registra cuándo el prestador ingresó realmente a la red de SURA, o puede ser una fecha de última actualización del registro en el sistema?**
*Si es fecha de actualización del sistema, `antiguedad_dias` es ruido en lugar de señal y debe eliminarse de las features del modelo.*

**Q22. 1.352 prestadores del catálogo (20.7%) no ejecutaron ninguna visita de campo en 2025 y fueron excluidos del input de clustering. ¿Son prestadores definitivamente inactivos (dados de baja, suspendidos), o son prestadores habilitados que simplemente no recibieron asignaciones durante ese período?**
*Si son inactivos definitivos: la exclusión es correcta. Si son capacidad ociosa disponible: excluirlos perpetúa el desbalance actual — el modelo nunca los considerará para nuevas asignaciones, que es exactamente el problema que el reto quiere resolver.*

**Q23. Los valores de `PERFIL_TARIFA` en el catálogo (A, B, E, I, O, P, T, X) se trataron como categorías nominales sin jerarquía. ¿Existe una progresión o ranking entre estos perfiles que refleje nivel de servicio o costo?**
*Si existe jerarquía, el campo debería codificarse ordinalmente, añadiendo una dimensión económica al vector de features que actualmente no está capturada.*

---

## 7. Diseño del modelo de clustering (Fase 2)

**Q24. Ante el trade-off entre especialización técnica (asignar al más calificado), eficiencia logística (asignar al más cercano) y balance de carga (asignar al menos ocupado) — ¿cuál es la jerarquía de prioridades desde el negocio?**
*Determina qué dimensión de features debe tener mayor peso relativo en el clustering. Puede implementarse con escalado diferenciado por dimensión antes de K-Means sin modificar la capa Gold.*

**Q25. Los datos muestran que 2 prestadores concentran el 34.4% de todas las órdenes históricas (índice de Gini = 0.757). ¿Esa concentración es una decisión estratégica deliberada o un síntoma del problema que se quiere resolver?**
*Si es deliberada: el modelo debe respetar esa concentración o justificar cuándo romperla. Si es un accidente del modelo actual: reducir el índice de Gini es el objetivo explícito del clustering y el indicador de impacto más directo del reto.*

**Q26. ¿Cuántos clústeres de prestadores serían manejables operativamente para el equipo que va a usar el modelo?**
*Si el equipo puede gestionar máximo 5 segmentos, K=5 es el techo del modelo aunque el método del codo sugiera K=8. Un modelo técnicamente óptimo pero operativamente inmanejable no se adopta.*

---

## 8. Optimización de asignación (Fase 3)

**Q27. Las cancelaciones clasificadas como "causas del sistema" representan el 79.3% de las 229.824 cancelaciones registradas en 2025. ¿A qué se deben principalmente desde la perspectiva operativa — sobrecarga del prestador, incapacidades, problemas de agenda, u otros?**
*Si son por sobrecarga, `utilizacion_capacidad` es el feature más crítico del modelo y reducirlo es el objetivo central. Si son por causas externas no controlables, el modelo de clustering no puede reducirlas y el argumento de impacto debe ajustarse.*

**Q28. ¿Hay empresas que cancelan de forma sistemática y SURA lo tolera por su importancia comercial? ¿Debe el modelo tener en cuenta el historial de cancelaciones de la empresa al evaluar el desempeño del prestador?**
*Un prestador puede tener alta tasa de cancelación no porque sea poco confiable, sino porque le asignan empresas que sistemáticamente cancelan. Confirmar este fenómeno justifica incluir el comportamiento histórico de la empresa como variable en el motor de asignación.*

**Q29. Los datos muestran 665 municipios con demanda de empresas activas pero sin ningún prestador local registrado en el catálogo. ¿Es cubrir esas brechas geográficas un objetivo activo de este proyecto?**
*Si es un objetivo activo, el modelo puede ir más allá del clustering de asignación y entregar un mapa de brechas: "en estos municipios se necesita un prestador del clúster X". Esto amplía el valor de negocio de la solución más allá de la optimización de la red existente.*
