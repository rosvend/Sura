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
