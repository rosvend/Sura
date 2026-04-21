# Top 10 — Preguntas para Q&A con ARL SURA

Preguntas consolidadas del equipo (Roy, Daniel, Pablo) para la sesión de Q&A del **2026-04-11**. Seleccionadas por impacto en el entendimiento del negocio y relevancia directa para el diseño del modelo de clustering. Ordenadas de mayor a menor prioridad.

---

**1. ¿Podrían caminarnos por el ciclo completo de un servicio, desde que una empresa cliente tiene una necesidad hasta que la tarea se factura/legaliza? ¿En qué punto del flujo aparece por primera vez la orden de compra y en qué punto aparece la programación de la cita?**

_Sin entender el flujo end-to-end, todo lo demás es suposición._ — Roy Q1

R. Se manejan servicios de prevención. Servicios orientados a la prevención de riesgos que puedan generar enfermedades o accidentes de trabajo.

Hay dos formas de atender:

1. Cartera directa. Atención al ciente 1:1
2. Cartera masiva. Volumen de empresas las cuales se tipifican y se trata de hacer planes para ellas.

Todos los servicios arrancan con una orden de compra/servicio. Una orden de compra son las indicaciones dadas al prestador acerca de lo que tiene que entregar.

Los prestadores no hacen parte de Sura, son firmas prestadoras con las cuales se hacen contratos.

La orden de compra/servicio tiene: a que cliente se debe atender, que producto y que tarea se necesita realizar. Incluye también la clasificación del servicio, la cantidad de horas por la prestación de la tarea y el centro de trabajo de ese cliente, ej: Éxito de Laureles, o centro de distrubución del Éxito.

Plataforma interconectados. Programación de la cita; es acordada entre proveedor y cliente.

Con el cliente se maneja un cronograma en una plataforma propia de Sura, donde se ingresa la tarea y se genera la orden de compra.

Luego de la realización de la tarea, el prestador la documenta y la carga al sistema. En ese momento el servicio se da por cerrado. Cuando el servicio cumple con los requisitos, el prestador procede a facturar.

---

**2. ¿Qué dispara la creación de una orden de compra — es automático a partir del plan de prevención, lo solicita la empresa, o lo genera un empleado de Sura? Y si la primera cita se cancela, ¿se reprograma dentro de la misma orden o se genera una orden nueva?**

_Define cómo se genera la demanda y si la relación orden-cita es 1:1 o 1:N. Sin esto no podemos interpretar correctamente los reintentos ni modelar la demanda._ — Roy Q2+Q3

La creación de una orden de compra no es automática. Sura maneja un software desde el cpmienzo de la ARL, el cual cuenta con muchas limitaciones tecnológicas.

Figura profesional en prevención de riesgos. Crea de manera manual la orden de compra y define un cronograma con el cliente.

Generar una orden de compra compromente el presupuesto y el recurso público. Por esta razón el acceso es restringido, ni siquiera ellos tienen acceso.

Plataforma Interconectados. Es el micrositio del prestador. A través de esta plataforma el mismo prestador gestiona todo.

Una orden puede tener tantas citas como sean necesarias. Si una cita es cancelada, otra puede ser programada.

---

**3. ¿Qué significa exactamente que una empresa esté "afiliada" a ARL SURA? Vemos ~2.1 millones de registros pero cerca del 70% tienen cero afiliados activos. ¿Son clientes actuales, históricos, prospectos, o una mezcla? ¿Cuáles deberían estar dentro del alcance del modelo?**

_Delimita el universo del modelo — podríamos estar incluyendo empresas que ya no existen operativamente._ — Roy Q4

Muchos contratos son de independientes. O empresas desafiliadas en este momento.

Que una empresa esté afiliada significa que tenga cobertura en ese momento

En Detalle_Empresa:

- ESTADO_EMPRESA Estado actual de la empresa según registro operativo.
- Fecha_Inicio_Cobertura Fecha a partir de la cual inicia la cobertura de la empresa en la ARL.
- Fecha_Fin_Cobertura Fecha en la que finaliza la cobertura de la empresa en la ARL.

Retirado significa desafiliado. Todo lo demás es afiliado. En mora significa en cobertura pero debe plata.

### LENGUAJE

#### RUTAS DE ATENCIÓN

Van por la capadicad que tiene el cliente de hacer cosas diferentes. Categorías:

- LIVIANA: empresas pequeñas, independientes, voluntarios. Se tiene un modelo de atención que no es presencial, sino virtual. Se disponen herramientas, documentos, mensajes, etc. para orientarlos.
- ESTÁNDAR: herramientas y órdenes de compra. Si se hace acompañamiento.
- INTERVENCIÓN, AVANZADA, ESPECIALIZADA: todas estas son presenciales.

#### CLIENTE

El cliente es la empresa (1), quien paga la ARL para todos sus trabajadores independientes. Aunque la empresa tenga muchos empleados, el cliente es como tal la empresa.

También existen otros tipos de cliente:

2. Independiente prestador de servicio: persona natural. Ej: profesor. Puede tener n contratos.

3. Independiente voluntario. Ej: taxista afiliado

4. Estudiantes en prácticas profesionales. Por ley deben estar afiliados a la ARL

Grupos -> riesgos
Tareas -> enfoque

---

**4. ¿Cuál es el indicador de negocio que más dolor genera hoy en el modelo de asignación? ¿Es la velocidad de asignación, la tasa de cancelación, la distancia recorrida, o la satisfacción de la empresa cliente?**

_Define la función objetivo del modelo. Si el dolor es velocidad, el clúster prioriza disponibilidad. Si es cancelación, el desempeño histórico del prestador pesa más. Si es distancia, la dimensión geográfica es crítica. Sin esta respuesta optimizamos variables que pueden no importarle al negocio._ — Daniel P1

Métricas: cuantas órdenes debe un prestador? Se compartirá un tablero.

---

**5. ¿Quién toma la decisión de asignación hoy y con qué información? ¿Hay un equipo centralizado, una herramienta, reglas fijas, o depende del criterio personal del coordinador?**

_Si los coordinadores usan criterios tácitos ("siempre asigno al prestador X para empresas de construcción"), esos criterios deben convertirse en features o restricciones del modelo. Además, define qué tan disruptiva es la solución propuesta._ — Daniel P4

---

**6. ¿Qué trade-off es prioritario para el negocio: asignar al prestador más cercano (eficiencia logística), al más especializado (calidad técnica), o al con menor carga actual (balance operativo)?**

_Determina directamente qué bloques de features deben tener mayor peso en el clustering: geográficas, técnicas o de carga. Sin esta jerarquía, todas las dimensiones pesan igual y el modelo no refleja las prioridades reales del negocio._ — Daniel P3

No hay restricciones geográficas. El ideal es que lo atienda alguien cercano.

La prioridad #1 es asignar a alguien que tenga la especialidad, que sepa lo que hace, que tenga la capacidad de asesorar, que tenga la experticia.

Luego viene que tenga capcidad de tiempo.

Y luego que esté en la zona.

---

**7. Cuando una cita se cancela, ¿qué pasa después desde el punto de vista del negocio? ¿Se reprograma con el mismo asesor, se reasigna a otro, o se debe crear una orden nueva? ¿Existe un prestador de respaldo predefinido? ¿Y quién absorbe el costo del retraso — Sura, el prestador o la empresa?**

_Si no hay respaldo formal, el output del modelo debería ser un top-N de prestadores compatibles, no solo el primero. Saber quién paga la cancelación permite cuantificar el ROI de reducirlas._ — Daniel P6 + Roy Q11, Q12 + Pablo P1

---

**8. Las cancelaciones clasificadas como "causas del sistema" representan el 79.3% del total. ¿A qué se deben principalmente desde la perspectiva operativa? ¿Cuántas de ellas son evitables con una mejor asignación?**

_Si la mayoría son por sobrecarga del prestador, el modelo puede reducirlas directamente. Si son por incapacidades u otras causas externas, el impacto del clustering tiene un techo y debemos ajustar las expectativas._ — Daniel P16 + Pablo P3

Se deben a la política de cancelación; se cancelan porque no se han gestionado (por ejemplo, no se llegó a un acuerdo entre el cliente y el proveedor). Antes era de 3 meses, ahora de 2.

---

**9. ¿Existen restricciones de negocio, contractuales o regulatorias que el modelo TIENE que respetar obligatoriamente? Por ejemplo: empresas o grupos económicos con prestadores dedicados y exclusivos, requisitos legales de qué tipo de prestador atiende ciertos sectores, SLAs mínimos de tiempo de respuesta, o reglas geográficas sobre qué firma atiende qué región.**

_Estas son restricciones duras — violarlas invalida el modelo sin importar qué tan buenos sean los clusters. Si el 20% de las empresas ya tienen prestador fijo, el modelo solo resuelve el 80% restante._ — Daniel P8, P9 + Roy Q16

Existen en negociaciones comerciales, pero no es representativo.

---

**10. ¿Quién va a usar el modelo de clustering en la práctica — un analista que revisa recomendaciones, un sistema automatizado, o un gerente que toma decisiones estratégicas? ¿Las recomendaciones serán vinculantes o solo orientativas? ¿Y el objetivo es asignar empresas a clústeres de prestadores (regla general) o recomendar un prestador individual específico para cada empresa?**

_Define el formato del entregable, el nivel de explicabilidad requerido y si la solución es un modelo de clustering puro o un sistema de dos capas (clustering + ranking individual)._ — Daniel P18, P20 + Roy Q15
