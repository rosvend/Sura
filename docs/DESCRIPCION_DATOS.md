# Descripción archivos de datos — Reto SURA 2026

Este documento describe el contenido, estructura y relevancia de cada uno de los archivos proporcionados para el reto.

El objetivo central es agrupar prestadores en clústeres estratégicos para optimizar la asignación de servicios y mejorar los tiempos de respuesta de la ARL SURA.

---

## Contexto general

La ARL cuenta con más de **800 firmas prestadoras** y **5.000 prestadores individuales** (asesores). El proceso de asignación de órdenes de compra está centralizado, lo que genera cuellos de botella. Los datos proporcionados permiten caracterizar a los prestadores, entender qué tareas ejecutan, con qué empresas trabajan y cuál es el desempeño de cada servicio.

---

## 1. `Diccionario_Datos.xlsx`

**Tipo:** Metadato / Diccionario

**Formato:** Excel (.xlsx), 4 hojas

Este archivo es el diccionario de datos del proyecto. Describe cada variable de los otros tres archivos: su nombre, definición, número de categorías únicas y tipo de dato. Es el punto de partida para entender qué representa cada campo antes de explorar los datos.

| Hoja                           | Archivo que documenta                    |
| ------------------------------ | ---------------------------------------- |
| `Tareas_Por_prestador_Bloque`  | `Tareas_prestador_bloque.xlsx`           |
| `Ordenado`                     | `Ordenado.txt`                           |
| `Tareas_Programads_Canceladas` | `Tareas_Programadas_canceladas_2025.txt` |
| `Detalle_Empresa`              | `Detalle_Empresa.txt`                    |

---

## 2. `Tareas_prestador_bloque.xlsx`

**Tipo:** Catálogo de prestadores y sus capacidades habilitadas

**Formato:** Excel (.xlsx), 4 hojas

**Columnas:** 38 (37 originales + `_RED_ORIGEN` agregada en ingesta para identificar la hoja de origen)

> ⚠️ **Nota de ingesta:** `pl.read_excel()` sin parámetros lee solo la primera hoja. Se corrigió en `src/ingestion/extract.py` con `_read_all_sheets()` que concatena las 4 hojas. La capa Silver trabaja con las **2.812.076 filas combinadas**. Las cardinalidades de este documento reflejan el dataset completo — los valores parciales del análisis exploratorio inicial (basado en CGR únicamente) están desactualizados.

**Hojas:**

- `CGR` — Red principal / Coordinación General de Red (~663.503 filas)
- `Red_otras_ofic` — Red de otras oficinas regionales (~736.923 filas)
- `Red_med&Cali` — Red de Medellín y Cali (~486.099 filas)
- `Red_Bogota` — Red de Bogotá (~925.551 filas)

### Descripción

Este archivo es el **catálogo maestro de prestadores**. Contiene la lista de asesores habilitados por cada firma prestadora, las tareas que están autorizados a ejecutar (por bloque y producto), su perfil tarifario, capacidad disponible y municipio de cobertura. Cada fila representa la habilitación de un prestador para una tarea específica dentro de un bloque.

### Variables clave

| Variable                              | Descripción                                                                                                     |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `DNI_PRESTADOR`                       | Identificador único del asesor                                                                                  |
| `NOMBRE_PRESTADOR`                    | Nombre del asesor                                                                                               |
| `DNI_DISTRIBUIDOR`                    | Identificador de la firma prestadora (NIT)                                                                      |
| `CDOFICINA` / `DSOFICINA`             | Oficina regional (8 oficinas: Medellín, Bogotá, Cali, Barranquilla, Bucaramanga, Cartagena, Manizales, Pereira) |
| `CDPRODUCTO` / `DSPRODUCTO`           | Producto o programa de servicio (**79 categorías** — las 4 redes combinadas)                                    |
| `CDBLOQUE` / `DSBLOQUE`               | Bloque temático al que pertenece la tarea (**104 bloques** — las 4 redes combinadas)                            |
| `CDTAREA` / `DSTAREA`                 | Tarea específica habilitada para el prestador (**1.658 tareas** — las 4 redes combinadas)                       |
| `DSCLASIFICACION`                     | Tipo de servicio (16 valores): ASESORÍA, CAPACITACIÓN, ADMINISTRATIVA, EXAMEN, LÚDICO, MATERIALES, MEDICAMENTOS, MEDICIONES AMBIENTALES, OPER. ADMINISTRATIVA, OPER. ASESORIA, OPER. CAPACITACION, OPER.REDES, PROMOCION, PROYECTOS, SERVICIO NO ENTREGADO, SERVICIOS |
| `DSTIPO_PERFIL`                       | Nivel del prestador (8 valores): BASICO, TECNOLOGO, INTERMEDIO, PROFESIONAL, AVANZADO, EXPERTO, ESPECIALISTA, OTROS |
| `PERFIL_TARIFA`                       | Perfil tarifario (8 valores): A, B, E, I, O, P, T, X                                                           |
| `FUNCION_PRESTADOR`                   | Rol del prestador: Asesor en Prevención, Asesor en Riesgos, Proyectos, etc.                                     |
| `CAPACIDAD`                           | Horas disponibles del prestador para el periodo                                                                 |
| `CDMUNICIPIO` / `DSMUNICIPIO`         | Municipio de base del prestador (**241 municipios** con cobertura — las 4 redes combinadas)                     |
| `CDMUNICIPIO_ORIGEN_OC`               | Municipio desde el cual se origina la orden de compra                                                           |
| `TIPO_DE_RED`                         | Tipo de red (7 valores): ESTRATEGICA, APOYO, COMERCIAL, ESPECIALIZADA, MERCADEO, OPERACIONES, PROMOTORA         |
| `SNCONTROLAR_HORAS_MES`               | Si se controla la capacidad mensual del asesor (S/N)                                                            |
| `FEALTA_PRESTADOR`                    | Fecha de registro del prestador                                                                                 |
| `FEC_INI_COS_TAR` / `FEC_FIN_COS_TAR` | Vigencia de la tarifa asignada                                                                                  |

### Relevancia

Es la base para construir el clúster de prestadores. Permite identificar la **especialización**, **cobertura geográfica**, **capacidad** y **perfil** de cada asesor. Esencial para la asignación inteligente.

---

## 3. `Ordenado.txt`

**Tipo:** Transaccional — Órdenes de compra

**Formato:** Texto plano delimitado por tabulación (`\t`)

**Registros:** ~607.331 filas (excluye encabezado)

**Columnas:** 100

### Descripción

Este archivo contiene el **historial completo de órdenes de compra** emitidas a los prestadores. Cada fila es una línea de orden (tarea contratada) con su estado, costos, fechas, municipios de entrega, empresa cliente beneficiada y el prestador asignado. La llave única del registro es `Ord_Plan_Vers_Act_Id`, que combina orden + plan + versión + actividad.

### Variables clave

| Variable                                                | Descripción                                                           |
| ------------------------------------------------------- | --------------------------------------------------------------------- |
| `Ord_Plan_Vers_Act_Id`                                  | Llave primaria del registro                                           |
| `Numero_Consecutivo_Orden`                              | Número de la orden                                                    |
| `Dni_Prestador` / `Nombre_Prestador`                    | Prestador asignado a la orden                                         |
| `Nombre_Regional`                                       | Regional de la ARL (5 regionales)                                     |
| `Codigo_Tarea` / `Tarea_Desc`                           | Tarea contratada                                                      |
| `Codigo_Estado_Orden` / `Estado_Orden_Desc`             | Estado (6 valores): APROBADO, BLOQUEADO, FACTURA, FACTURADO, LEGALIZADO, PENDIENTE |
| `Fecha_Creacion_Orden`                                  | Fecha de creación                                                     |
| `Fecha_Entrega_Servicio` / `Fecha_Entrega_Servicio_Fin` | Ventana de entrega del servicio                                       |
| `Valor_Costo_Unitario`                                  | Costo por unidad del servicio                                         |
| `Valor_Costo_Total_Tarea`                               | Costo total de la orden                                               |
| `Valor_Costo_Transporte` / `Valor_Costo_Viaticos`       | Costos logísticos asociados                                           |
| `Municipio_Origen_Desc` / `Municipio_Entrega_Desc`      | Origen y destino del servicio                                         |
| `Clasificacion_Desc`                                    | Tipo: Asesoría, Capacitación, Promoción, etc.                         |
| `Tipo_Red_Desc`                                         | Tipo de red del prestador                                             |
| `Nombre_Empresa` / `Dni_Empresa`                        | Empresa cliente beneficiada                                           |
| `Centro_Trabajo_Desc`                                   | Centro de trabajo de la empresa cliente                               |
| `Macrosegmentacion_Desc`                                | Segmento de la empresa: Gran Empresa, Mediana, Micro, etc.            |
| `Actividad_Economica_Desc`                              | Actividad económica de la empresa cliente                             |
| `Estado_Girop_Desc` / `Estado_Micrositio_Desc`          | Estados en sistemas de gestión internos                               |
| `Numero_Cantidad_Cancelada`                             | Unidades canceladas de la orden                                       |
| `Numero_Version`                                        | Versión del plan                                                      |

### Relevancia

Permite analizar la **carga histórica por prestador**, los **patrones de asignación**, los **costos por tipo de servicio y región**, y los puntos de saturación. Es clave para medir desempeño y detectar cuellos de botella operativos.

---

## 4. `Tareas_Programadas_canceladas_2025.txt`

**Tipo:** Transaccional — Programaciones de servicios (ejecución y cancelación)

**Formato:** Texto plano delimitado por tabulación (`\t`)

**Registros:** ~1.542.709 filas (excluye encabezado)

**Columnas:** 62

### Descripción

Este archivo registra las **citas o visitas programadas** para la ejecución de tareas en las empresas clientes durante 2025. Incluye tanto las citas ejecutadas como las canceladas, con sus motivos, fechas, duración, responsables, y el estado del informe resultante. Permite medir tiempos reales de atención y patrones de cancelación.

### Variables clave

| Variable                                            | Descripción                                                     |
| --------------------------------------------------- | --------------------------------------------------------------- |
| `NMCONSECUTIVO_ORDEN`                               | Orden a la que pertenece la cita                                |
| `DNI_PRESTADOR` / `NOMBRE_PRESTADOR`                | Asesor que ejecutó el servicio                                  |
| `DNI_DISTRIBUIDOR` / `NOMBRE_DISTRIBUIDOR`          | Firma prestadora                                                |
| `TIPO_DE_ASESOR`                                    | Rol del asesor (45 variantes)                                   |
| `DNI_EMPRESA` / `DSNOMBRE_EMPRESA`                  | Empresa cliente atendida                                        |
| `NPOLIZA`                                           | Identificador de la empresa en la ARL                           |
| `CDTAREA` / `DSTAREA`                               | Tarea ejecutada                                                 |
| `CLASIFICACION`                                     | Tipo de servicio                                                |
| `CDPRODUCTO` / `DSPRODUCTO`                         | Producto del servicio                                           |
| `DS_MUNICIPIO_ORIGEN` / `DS_MUNICIPIO_DESTINO`      | Municipios de origen y destino                                  |
| `TIPO_PROGRAMACION`                                 | Campo (presencial) o Informe (virtual)                          |
| `FEENTREGA_SERVICIO_INI` / `FEENTREGA_SERVICIO_FIN` | Ventana del servicio                                            |
| `FEPROGRAMACION`                                    | Fecha real de programación de la cita                           |
| `FEINGRESO_CUMPLIMIENTO`                            | Fecha de registro de cumplimiento                               |
| `DURACION`                                          | Duración de la actividad (horas)                                |
| `NMCANTIDAD_EJECUTADA`                              | Unidades efectivamente entregadas                               |
| `NMASISTENTES`                                      | Número de asistentes                                            |
| `DSESTADO_PROGRAMACION`                             | Estado (7 valores): CITA EJECUTADA (84.1%), CITA CANCELADA (14.9%), CITA PROGRAMADA (0.9%), PARCIALMENTE EJECUTADO, PARCIALMENTE COMPLETADO, CITA REPROGRAMADA, RECHAZADA |
| `FECANCELACION` / `MOTIVO_CANCELACION`              | Fecha y razón de cancelación                                    |
| `SNCANCELA_EMPRESA`                                 | Si la cancelación fue por parte de la empresa                   |
| `DSESTADO_INFORME`                                  | Estado del informe: Aprobado, Rechazado, Enviado, etc.          |
| `FEAPROBACION_INFORME` / `FERECHAZO_INFORME`        | Fechas de gestión del informe                                   |
| `SNAPROBADO_AUTOMATICO`                             | Si el informe fue aprobado automáticamente                      |
| `SNPARCIAL`                                         | Si el cumplimiento fue parcial                                  |

### Relevancia

Es el archivo más operativo del conjunto. Permite medir los **tiempos reales de atención**, la **tasa de cancelación por prestador o empresa**, la **carga operativa** por asesor y periodo, y los **motivos de fallo en la prestación**. Fundamental para detectar saturación y construir indicadores de seguimiento del modelo.

---

## 5. `Detalle_Empresa.txt`

**Tipo:** Maestro de clientes (empresas afiliadas)

**Formato:** Texto plano delimitado por virgulilla (`~`)

**Registros:** ~2.175.102 filas (excluye encabezado)

**Columnas:** 16

### Descripción

Este archivo es el **catálogo maestro de empresas clientes** de la ARL. Contiene información de caracterización de cada empresa: estado de afiliación, actividad económica, sector, segmentación, número de afiliados y la ruta de atención asignada. Los datos están anonimizados (no se expone razón social directa en todos los casos).

### Variables clave

| Variable                                         | Descripción                                                                                    |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `Empresa_Id`                                     | Identificador único de la empresa                                                              |
| `ESTADO_EMPRESA_CALCULADO`                       | Estado derivado por reglas de negocio: Activa / Inactiva                                       |
| `ESTADO_EMPRESA`                                 | Estado operativo (4 valores): EN COBERTURA, EN MORA, RETIRADO, POR INICIAR COBERTURA           |
| `ID_PROFESIONAL_PPAL`                            | Asesor principal asignado a la empresa                                                         |
| `Fecha_Inicio_Cobertura` / `Fecha_Fin_Cobertura` | Vigencia de la afiliación                                                                      |
| `Actividad_Economica_Desc`                       | Actividad económica (1.475 categorías)                                                         |
| `Ind_Multiregional`                              | Si la empresa opera en múltiples regiones (S/N)                                                |
| `Ind_Afiliada`                                   | Tipo de afiliación: Empresa (E), Voluntario (V), Cotizante (C)                                 |
| `Afiliados`                                      | Indicador cualitativo: Con Afiliados / Sin Afiliados                                           |
| `Numero_Afiliados`                               | Cantidad de afiliados                                                                          |
| `Sector_Economico_Desc`                          | Sector: Construcción, Financiero, Independientes, etc. (29 sectores)                           |
| `Segmentacion_Arl_Desc`                          | Segmento ARL: Gran Empresa, Mediana Empresa, Micro Empresa, Independiente, Empresa Nueva, etc. |
| `GRUPO_ECONOMICO_ARL_ID`                         | Grupo económico al que pertenece la empresa                                                    |
| `UEN_PPAL_ARL_ID`                                | Unidad Estratégica de Negocio principal asignada                                               |
| `Ruta_Atencion`                                  | Ruta de atención (6 valores, orden ascendente de intensidad): LIVIANA (80%), SIN RUTA (13.2%), ESTÁNDAR, INTERVENCIÓN, AVANZADA, ESPECIALIZADA |

### Relevancia

Permite **caracterizar la demanda**: qué tipo de empresas requieren qué tipo de servicios, en qué regiones y con qué complejidad. La segmentación y el sector económico son variables clave para definir las necesidades de atención y hacer un match inteligente con el perfil del prestador.

---

## Resumen de archivos

| Archivo                                  | Tipo               | Registros         | Separador        | Rol en el reto                       |
| ---------------------------------------- | ------------------ | ----------------- | ---------------- | ------------------------------------ |
| `Diccionario_Datos.xlsx`                 | Metadato           | —                 | Excel            | Diccionario de variables             |
| `Tareas_prestador_bloque.xlsx`           | Catálogo de oferta | 2.812.076 (4 hojas combinadas) | Excel  | Perfil y capacidad del prestador     |
| `Ordenado.txt`                           | Transaccional      | ~607.331          | Tab              | Historial de órdenes de compra       |
| `Tareas_Programadas_canceladas_2025.txt` | Transaccional      | ~1.542.709        | Tab              | Ejecución y cancelación de citas     |
| `Detalle_Empresa.txt`                    | Maestro de demanda | ~2.175.102        | Virgulilla (`~`) | Caracterización de empresas clientes |

---

## Relaciones entre archivos

```
Detalle_Empresa.txt
    └── Empresa_Id / DNI_EMPRESA
         └── Ordenado.txt  (Dni_Empresa)
              └── Numero_Consecutivo_Orden
                   └── Tareas_Programadas_canceladas_2025.txt (NMCONSECUTIVO_ORDEN)

Tareas_prestador_bloque.xlsx
    └── DNI_PRESTADOR
         ├── Ordenado.txt  (Dni_Prestador)
         └── Tareas_Programadas_canceladas_2025.txt (DNI_PRESTADOR)
```

El `DNI_PRESTADOR` y el `NMCONSECUTIVO_ORDEN` / `Numero_Consecutivo_Orden` son las llaves de integración entre los archivos transaccionales y los catálogos maestros.
