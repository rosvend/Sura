# Top 10 — Preguntas para Q&A con ARL SURA

Preguntas consolidadas del equipo (Roy, Daniel, Pablo) para la sesión de Q&A del **2026-04-11**. Seleccionadas por impacto en el entendimiento del negocio y relevancia directa para el diseño del modelo de clustering. Ordenadas de mayor a menor prioridad.

---

**1. ¿Podrían caminarnos por el ciclo completo de un servicio, desde que una empresa cliente tiene una necesidad hasta que la tarea se factura/legaliza? ¿En qué punto del flujo aparece por primera vez la orden de compra y en qué punto aparece la programación de la cita?**

*Sin entender el flujo end-to-end, todo lo demás es suposición.* — Roy Q1

---

**2. ¿Qué dispara la creación de una orden de compra — es automático a partir del plan de prevención, lo solicita la empresa, o lo genera un empleado de Sura? Y si la primera cita se cancela, ¿se reprograma dentro de la misma orden o se genera una orden nueva?**

*Define cómo se genera la demanda y si la relación orden-cita es 1:1 o 1:N. Sin esto no podemos interpretar correctamente los reintentos ni modelar la demanda.* — Roy Q2+Q3

---

**3. ¿Qué significa exactamente que una empresa esté "afiliada" a ARL SURA? Vemos ~2.1 millones de registros pero cerca del 70% tienen cero afiliados activos. ¿Son clientes actuales, históricos, prospectos, o una mezcla? ¿Cuáles deberían estar dentro del alcance del modelo?**

*Delimita el universo del modelo — podríamos estar incluyendo empresas que ya no existen operativamente.* — Roy Q4

---

**4. ¿Cuál es el indicador de negocio que más dolor genera hoy en el modelo de asignación? ¿Es la velocidad de asignación, la tasa de cancelación, la distancia recorrida, o la satisfacción de la empresa cliente?**

*Define la función objetivo del modelo. Si el dolor es velocidad, el clúster prioriza disponibilidad. Si es cancelación, el desempeño histórico del prestador pesa más. Si es distancia, la dimensión geográfica es crítica. Sin esta respuesta optimizamos variables que pueden no importarle al negocio.* — Daniel P1

---

**5. ¿Quién toma la decisión de asignación hoy y con qué información? ¿Hay un equipo centralizado, una herramienta, reglas fijas, o depende del criterio personal del coordinador?**

*Si los coordinadores usan criterios tácitos ("siempre asigno al prestador X para empresas de construcción"), esos criterios deben convertirse en features o restricciones del modelo. Además, define qué tan disruptiva es la solución propuesta.* — Daniel P4

---

**6. ¿Qué trade-off es prioritario para el negocio: asignar al prestador más cercano (eficiencia logística), al más especializado (calidad técnica), o al con menor carga actual (balance operativo)?**

*Determina directamente qué bloques de features deben tener mayor peso en el clustering: geográficas, técnicas o de carga. Sin esta jerarquía, todas las dimensiones pesan igual y el modelo no refleja las prioridades reales del negocio.* — Daniel P3

---

**7. Cuando una cita se cancela, ¿qué pasa después desde el punto de vista del negocio? ¿Se reprograma con el mismo asesor, se reasigna a otro, o se debe crear una orden nueva? ¿Existe un prestador de respaldo predefinido? ¿Y quién absorbe el costo del retraso — Sura, el prestador o la empresa?**

*Si no hay respaldo formal, el output del modelo debería ser un top-N de prestadores compatibles, no solo el primero. Saber quién paga la cancelación permite cuantificar el ROI de reducirlas.* — Daniel P6 + Roy Q11, Q12 + Pablo P1

---

**8. Las cancelaciones clasificadas como "causas del sistema" representan el 79.3% del total. ¿A qué se deben principalmente desde la perspectiva operativa? ¿Cuántas de ellas son evitables con una mejor asignación?**

*Si la mayoría son por sobrecarga del prestador, el modelo puede reducirlas directamente. Si son por incapacidades u otras causas externas, el impacto del clustering tiene un techo y debemos ajustar las expectativas.* — Daniel P16 + Pablo P3

---

**9. ¿Existen restricciones de negocio, contractuales o regulatorias que el modelo TIENE que respetar obligatoriamente? Por ejemplo: empresas o grupos económicos con prestadores dedicados y exclusivos, requisitos legales de qué tipo de prestador atiende ciertos sectores, SLAs mínimos de tiempo de respuesta, o reglas geográficas sobre qué firma atiende qué región.**

*Estas son restricciones duras — violarlas invalida el modelo sin importar qué tan buenos sean los clusters. Si el 20% de las empresas ya tienen prestador fijo, el modelo solo resuelve el 80% restante.* — Daniel P8, P9 + Roy Q16

---

**10. ¿Quién va a usar el modelo de clustering en la práctica — un analista que revisa recomendaciones, un sistema automatizado, o un gerente que toma decisiones estratégicas? ¿Las recomendaciones serán vinculantes o solo orientativas? ¿Y el objetivo es asignar empresas a clústeres de prestadores (regla general) o recomendar un prestador individual específico para cada empresa?**

*Define el formato del entregable, el nivel de explicabilidad requerido y si la solución es un modelo de clustering puro o un sistema de dos capas (clustering + ranking individual).* — Daniel P18, P20 + Roy Q15
