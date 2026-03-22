# Diagnóstico y análisis inicial — Reto SURA 2026

**Estrategia de clústeres inteligentes para la asignación de prestadores**

---

## 1. Resumen ejecutivo

La ARL SURA opera con una red de más de **800 firmas prestadoras** y **5.000 asesores individuales** que ejecutan servicios de prevención, capacitación y asesoría en seguridad y salud en el trabajo (SST) a un universo de clientes que supera los **2,1 millones de empresas afiliadas**. Tras la centralización del proceso de asignación de órdenes de compra, se han generado cuellos de botella operativos que afectan los tiempos de respuesta y la calidad del servicio.

Este documento diagnostica el estado actual del modelo, identifica los problemas estructurales y propone un conjunto de soluciones basadas en analítica de datos, con énfasis en el agrupamiento inteligente (clústeres) de prestadores para optimizar la asignación de servicios.

---

## 2. Descripción del modelo operativo actual

### 2.1 Actores del sistema

| Actor                                   | Rol                                                                                                                                                                                                                    |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ARL SURA**                            | Aseguradora de riesgos laborales. Define los productos, las tareas y los planes de prevención para cada empresa afiliada.                                                                                              |
| **Firmas prestadoras (distribuidores)** | Empresas externas contratadas por la ARL para entregar los servicios. Actúan como intermediarios. Existen +800 firmas.                                                                                                 |
| **Asesores (prestadores individuales)** | Profesionales que ejecutan las tareas directamente en las empresas clientes. Existen +5.000 asesores. Cada asesor pertenece a una firma prestadora y puede estar habilitado para múltiples tareas y bloques temáticos. |
| **Empresas clientes**                   | Empresas afiliadas a la ARL que reciben los servicios de SST. Representan la demanda. Superan los 2,1 millones de registros.                                                                                           |

### 2.2 Flujo del proceso actual

```
Empresa afiliada
  → Plan de prevención definido por la ARL
    → Orden de compra (OC) generada centralizadamente
      → Asignación de la OC a un prestador (firma + asesor)
        → Programación de la cita/visita
          → Ejecución del servicio
            → Registro de cumplimiento e informe
              → Facturación y legalización
```

### 2.3 Escala de los datos

| Dimensión                      | Cifra      |
| ------------------------------ | ---------- |
| Empresas clientes              | ~2.175.102 |
| Órdenes de compra históricas   | ~607.331   |
| Citas programadas en 2025      | ~1.542.709 |
| Tareas habilitadas en catálogo | 1.066      |
| Bloques temáticos              | 89         |
| Productos/programas            | 39–53      |
| Regionales ARL                 | 5          |
| Oficinas operativas            | 8          |
| Municipios con cobertura       | +900       |

---

## 3. Diagnóstico — Problemas identificados

### 3.1 Problema central: cuello de botella por centralización

La asignación de órdenes de compra se gestiona de forma centralizada. Esto significa que una sola instancia toma decisiones de asignación para un volumen de +1,5 millones de citas anuales, sin un mecanismo sistemático que considere simultáneamente la especialización del asesor, su carga actual, su ubicación geográfica y la complejidad de la empresa cliente. El resultado es un proceso lento, reactivo y con alta probabilidad de desajuste entre la oferta (prestador) y la demanda (empresa).

### 3.2 Fragmentación de la información de oferta

El catálogo de prestadores (`Tareas_prestador_bloque.xlsx`) está dividido en cuatro redes (`CGR`, `Red_otras_ofic`, `Red_med&Cali`, `Red_Bogota`), lo que implica que la visión de la capacidad disponible no está unificada. Cada red opera con sus propias habilitaciones de tareas, tarifas y municipios de cobertura, lo que dificulta la comparación y la asignación transversal de recursos cuando una red está saturada y otra tiene capacidad libre.

### 3.3 Ausencia de una segmentación operativa de prestadores

Actualmente, los asesores tienen un perfil tarifario (A, B, C o D) y un tipo de función (Asesor en Prevención, Asesor en Riesgos, etc.), pero **no existe una segmentación estratégica** que agrupe a los prestadores por patrones de comportamiento real: qué tipos de empresa atienden con mayor frecuencia, en qué sectores se especializan en la práctica, qué tan eficientes son en la ejecución, qué tasa de cancelación tienen. El perfil declarado no siempre coincide con el perfil operativo real.

### 3.4 Alta tasa de cancelaciones sin análisis de causa

El archivo `Tareas_Programadas_canceladas_2025.txt` contiene ~1,5 millones de registros, incluyendo citas canceladas con su motivo (`MOTIVO_CANCELACION`) y si la cancelación fue iniciada por la empresa (`SNCANCELA_EMPRESA`). Con más de 200.000 fechas de cancelación únicas registradas, existe evidencia de un volumen significativo de citas que no llegan a ejecutarse. Este desperdicio operativo no está siendo analizado ni retroalimentado al proceso de asignación.

### 3.5 Desconexión entre capacidad declarada y demanda real

El campo `CAPACIDAD` en el catálogo de prestadores indica las horas disponibles del asesor, y `SNCONTROLAR_HORAS_MES` indica si esa capacidad se controla. Sin embargo, la asignación de órdenes de compra no evidencia un mecanismo formal que cruce la demanda esperada de una empresa (derivada de su sector, tamaño y número de afiliados) con la capacidad real disponible del asesor asignado. Esto conduce a saturación en algunos asesores y subutilización en otros.

### 3.6 Complejidad geográfica no explotada

Las órdenes de compra registran tanto el municipio de origen del servicio como el municipio de entrega, y el catálogo de prestadores distingue entre el municipio de base del asesor y el municipio de origen de la OC. Con más de **900 municipios de entrega únicos** y costos de transporte y viáticos que varían según la distancia, la dimensión geográfica representa un factor crítico de eficiencia que actualmente no está siendo optimizado de forma sistemática.

### 3.7 Pérdida de contexto de la empresa cliente en la asignación

El archivo `Detalle_Empresa.txt` contiene atributos ricos de cada empresa: sector económico (29 categorías), segmentación ARL (micro, pequeña, mediana, gran empresa, independiente), número de afiliados, actividad económica (1.475 categorías) y ruta de atención (liviana, estándar, sin ruta). Sin embargo, esta información no parece estar integrada al proceso de asignación. Un asesor especializado en riesgos ergonómicos en industria manufacturera podría estar siendo asignado a una empresa de servicios financieros, perdiendo valor de especialización.

### 3.8 Ciclo de retroalimentación inexistente

No existe un mecanismo documentado que tome los resultados de la ejecución (tiempos reales, tasas de cancelación, aprobación de informes) y los retroalimente al proceso de asignación para mejorar futuras decisiones. El sistema opera en abierto: asigna, ejecuta, pero no aprende.

---

## 4. Análisis de las variables clave

### 4.1 Variables de oferta (prestadores)

Las siguientes variables del catálogo de prestadores son las más relevantes para construir un perfil operativo de cada asesor:

| Variable               | Por qué es clave                                                                                                                                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `CDBLOQUE` / `DSTAREA` | Define la especialización técnica real del asesor. Un asesor habilitado para 50 tareas en el bloque de riesgos ergonómicos tiene un perfil diferente a uno habilitado para 10 tareas en gestión psicosocial. |
| `DSTIPO_PERFIL`        | Indica el nivel de expertise (Básico, Medio, Avanzado, Especializado). Debe coincidir con la complejidad del cliente asignado.                                                                               |
| `CAPACIDAD`            | Horas disponibles. Variable directa para detectar saturación.                                                                                                                                                |
| `CDMUNICIPIO`          | Municipio de base. Determina viabilidad geográfica y costo logístico.                                                                                                                                        |
| `TIPO_DE_RED`          | Estratégica vs. Apoyo. Define el tipo de relación contractual y la prioridad de asignación.                                                                                                                  |
| `FUNCION_PRESTADOR`    | Rol específico dentro del servicio. No todos los asesores pueden ejecutar todos los tipos de tarea.                                                                                                          |
| `PERFIL_TARIFA`        | Proxy del costo. Asesores de perfil A son más costosos; deben asignarse a servicios que lo justifiquen.                                                                                                      |

### 4.2 Variables de demanda (empresas clientes)

| Variable                   | Por qué es clave                                                                                                                                  |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Segmentacion_Arl_Desc`    | Define la intensidad del servicio requerido. Gran Empresa requiere mayor frecuencia y complejidad que una Micro Empresa.                          |
| `Sector_Economico_Desc`    | Los riesgos laborales varían por sector. Construcción e infraestructura tienen perfil de riesgo muy diferente al sector financiero.               |
| `Numero_Afiliados`         | A mayor número de afiliados, mayor volumen de actividades de SST requeridas.                                                                      |
| `Ruta_Atencion`            | Clasifica la intensidad del modelo de atención: LIVIANA (menor contacto), ESTÁNDAR (contacto regular), SIN RUTA (empresa inactiva o desafiliada). |
| `ESTADO_EMPRESA`           | Solo las empresas EN COBERTURA deben recibir servicios activos. Las EN MORA y RETIRADO tienen restricciones.                                      |
| `Actividad_Economica_Desc` | Permite identificar el tipo de riesgos específicos que enfrenta la empresa y el perfil del asesor que la debe atender.                            |

### 4.3 Variables de desempeño histórico (transaccionales)

| Variable                                          | Por qué es clave                                                                                                |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `Estado_Orden_Desc` / `DSESTADO_PROGRAMACION`     | Permite calcular tasas de completitud y cancelación por prestador.                                              |
| `DURACION`                                        | Tiempo real de ejecución. Permite identificar asesores eficientes vs. los que consumen más tiempo del estimado. |
| `MOTIVO_CANCELACION` / `SNCANCELA_EMPRESA`        | Diferencia entre cancelaciones atribuibles al prestador y las atribuibles a la empresa.                         |
| `Valor_Costo_Transporte` + `Valor_Costo_Viaticos` | Costo logístico real por orden. Permite evaluar eficiencia de la asignación geográfica.                         |
| `FEENVIO_INFORME` → `FEAPROBACION_INFORME`        | Tiempo entre envío y aprobación del informe. Indicador de calidad de la documentación del asesor.               |
| `SNAPROBADO_AUTOMATICO`                           | Si el informe fue aprobado sin revisión manual, indica un historial de calidad confiable.                       |

---

## 5. Propuestas de solución

### 5.1 Propuesta central: modelo de clústeres de prestadores

**Objetivo:** Agrupar a los asesores en segmentos homogéneos según su perfil técnico, geográfico y de desempeño, para que la asignación de OC se haga al clúster más adecuado para cada tipo de empresa cliente.

#### Variables propuestas para la construcción del clúster

```
Dimensión técnica:
  - Número de tareas habilitadas por bloque temático
  - Perfil (Básico / Avanzado / Especializado)
  - Función del prestador
  - Tipo de clasificación predominante (Asesoría / Capacitación / Promoción)

Dimensión geográfica:
  - Municipio de base
  - Número de municipios de entrega históricos
  - Distancia promedio recorrida (estimada desde municipio origen → destino)

Dimensión de desempeño (derivada de historial):
  - Tasa de ejecución = citas ejecutadas / citas programadas
  - Tasa de cancelación = citas canceladas / total asignadas
  - Tasa de aprobación de informes
  - Tiempo promedio de ejecución por tipo de tarea
  - Porcentaje de informes aprobados automáticamente

Dimensión de carga:
  - Número de OC activas simultáneas (en el periodo evaluado)
  - Proporción de capacidad utilizada vs. capacidad declarada
```

#### Algoritmos sugeridos

| Método                    | Cuándo usar                                                                                                                              |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **K-Means**               | Primera exploración. Rápido, escalable. Requiere definir K (número de clústeres) con método del codo o silhouette score.                 |
| **K-Medoids (PAM)**       | Más robusto a valores atípicos que K-Means. Útil si hay asesores con comportamientos extremos.                                           |
| **Clustering jerárquico** | Permite explorar la estructura natural de los datos sin fijar K a priori. Útil para análisis exploratorio.                               |
| **DBSCAN**                | Identifica asesores "atípicos" que no encajan en ningún clúster estándar (por ejemplo, asesores muy especializados o de baja actividad). |

Se recomienda iniciar con **K-Means sobre variables normalizadas**, complementado con **análisis de componentes principales (PCA)** para reducir la dimensionalidad y facilitar la visualización.

---

### 5.2 Propuesta de modelo de asignación automática o asistida

Una vez definidos los clústeres de prestadores, se propone un **motor de asignación por reglas de compatibilidad** que opere así:

```
Entrada: nueva OC con atributos de la empresa cliente
  ↓
Paso 1: Filtrar prestadores disponibles
  - Estado activo, capacidad residual > 0
  - Habilitado para la tarea específica (CDTAREA)
  - Municipio de cobertura compatible con municipio de entrega

  ↓
Paso 2: Calcular score de compatibilidad para cada prestador candidato
  Score = f(
    match de perfil (perfil del prestador vs. complejidad de la empresa),
    match geográfico (distancia origen-destino),
    carga actual (horas asignadas / capacidad),
    desempeño histórico (tasa de ejecución, calidad de informes),
    costo estimado (tarifa + transporte + viáticos)
  )

  ↓
Paso 3: Asignar al prestador del clúster con mayor score
  - Si hay empate: priorizar menor carga actual
  - Si ningún prestador disponible en la red principal: escalar a red de apoyo

  ↓
Salida: prestador asignado con justificación del score
```

Este modelo puede implementarse inicialmente como un sistema **asistido** (recomendación al gestor humano) y evolucionar hacia **automatización plena** a medida que se validen sus resultados.

---

### 5.3 Sistema de atención escalonado

Se propone definir **tres niveles de atención** según la complejidad de la empresa cliente:

| Nivel             | Perfil de empresa                                                                                        | Perfil de asesor recomendado | Tipo de servicio                                                |
| ----------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------- | --------------------------------------------------------------- |
| **Liviano**       | Independientes voluntarios, Micro empresas, Sin afiliados                                                | Básico / Medio               | Capacitaciones grupales, asesorías virtuales, informes estándar |
| **Estándar**      | Pequeñas y medianas empresas, sectores de riesgo moderado                                                | Avanzado                     | Asesorías presenciales, seguimiento de PVE, inspecciones        |
| **Especializado** | Gran empresa, sectores de alto riesgo (construcción, minería, transporte), empresas con muchos afiliados | Especializado                | Gestión integral de SST, auditorías, programas personalizados   |

La `Ruta_Atencion` existente en `Detalle_Empresa.txt` (LIVIANA / ESTÁNDAR / SIN RUTA) es una aproximación a este esquema y puede usarse como variable de validación.

---

### 5.4 Indicadores de monitoreo del modelo

Se propone un conjunto de indicadores para medir el desempeño del modelo una vez implementado:

#### Indicadores de asignación

| Indicador              | Descripción                                                                      | Meta sugerida                    |
| ---------------------- | -------------------------------------------------------------------------------- | -------------------------------- |
| Tasa de compatibilidad | % de OC asignadas donde el perfil del asesor coincide con el nivel de la empresa | > 85%                            |
| Tiempo de asignación   | Tiempo promedio entre creación de OC y asignación al prestador                   | Reducción del 40% vs. línea base |
| Concentración de carga | Índice de Gini sobre la distribución de OC entre asesores activos                | < 0.40 (distribución equitativa) |

#### Indicadores de ejecución

| Indicador                     | Descripción                                                | Meta sugerida    |
| ----------------------------- | ---------------------------------------------------------- | ---------------- |
| Tasa de ejecución             | Citas ejecutadas / citas programadas                       | > 90%            |
| Tasa de cancelación empresa   | Cancelaciones iniciadas por la empresa / total programadas | < 10%            |
| Tasa de cancelación prestador | Cancelaciones atribuibles al prestador / total programadas | < 5%             |
| Tiempo promedio de ejecución  | Duración real vs. duración estimada por tipo de tarea      | Desviación < 15% |

#### Indicadores de calidad

| Indicador                      | Descripción                                          | Meta sugerida    |
| ------------------------------ | ---------------------------------------------------- | ---------------- |
| Tasa de aprobación de informes | Informes aprobados / informes enviados               | > 92%            |
| Tasa de aprobación automática  | Informes aprobados automáticamente / total aprobados | > 60%            |
| Tiempo de ciclo del informe    | Días entre envío y aprobación/rechazo del informe    | < 5 días hábiles |

#### Indicadores de eficiencia de costos

| Indicador                | Descripción                                    | Meta sugerida                    |
| ------------------------ | ---------------------------------------------- | -------------------------------- |
| Costo logístico por OC   | (Transporte + viáticos) / Costo total de la OC | Reducción del 20% vs. línea base |
| Utilización de capacidad | Horas asignadas / horas disponibles del asesor | Entre 70% y 90%                  |

---

## 6. Limitaciones y consideraciones

- **Anonimización de los datos:** Los identificadores de prestadores, distribuidores, empresas y usuarios están encriptados (hashes). Esto impide la validación nominal pero no afecta el análisis de patrones y la construcción de clústeres.
- **Calidad de datos en campos de texto libre:** El campo `MOTIVO_CANCELACION` tiene más de 70.000 valores únicos, lo que sugiere baja estandarización. Requiere limpieza y categorización mediante técnicas de NLP antes de ser usado analíticamente.
- **Observaciones con codificación especial:** Algunos campos de texto en los archivos presentan caracteres especiales mal codificados (ej. `ASESOR�A`, `GESTI�N`), lo que indica una inconsistencia en el encoding (posiblemente Latin-1 vs. UTF-8). Debe corregirse en la etapa de preprocesamiento.
- **Volumen de datos:** El conjunto total supera los 4 millones de registros. Se recomienda trabajar con muestras estratificadas en la fase exploratoria y escalar el modelo al total una vez validado.
- **Dimensión temporal:** Los datos transaccionales cubren principalmente 2025. Para construir indicadores de desempeño histórico robustos, sería valioso contar con datos de periodos anteriores.

---

## 7. Hoja de ruta propuesta

| Fase                             | Actividades                                                                                                               | Artefacto                                       |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| **1. Exploración y limpieza**    | Corrección de encoding, tratamiento de nulos, normalización de campos categóricos, análisis de distribuciones             | Dataset limpio y documentado                    |
| **2. Feature engineering**       | Construcción de variables derivadas (tasa de ejecución, carga histórica, distancia geográfica, índice de especialización) | Tabla de features por asesor                    |
| **3. Clusterización**            | Aplicación de K-Means + PCA sobre la tabla de features. Evaluación con silhouette score y validación de interpretabilidad | Mapa de clústeres con descripción de cada grupo |
| **4. Modelo de asignación**      | Reglas de compatibilidad empresa-prestador basadas en clústeres. Simulación sobre OC históricas                           | Motor de asignación con scoring                 |
| **5. Visualización y dashboard** | Mapa geográfico de cobertura, distribución de carga por asesor, evolución de indicadores de ejecución                     | Dashboard interactivo                           |
| **6. Validación**                | Comparación del modelo vs. asignación actual. Cálculo del impacto en tiempos, tasas de cancelación y costos logísticos    | Informe de resultados y recomendaciones         |

---

## 8. Conclusión

El modelo operativo actual de la ARL SURA tiene las condiciones para ser transformado mediante analítica de datos. La información disponible es suficiente en volumen y riqueza para construir perfiles operativos de prestadores, segmentar la demanda de empresas clientes y diseñar un sistema de asignación inteligente que reduzca el cuello de botella actual.

El primer paso es construir los **clústeres de prestadores** a partir de su especialización técnica, comportamiento histórico y cobertura geográfica. Estos clústeres se convierten en la unidad fundamental del nuevo modelo, asignando el clúster correcto para cada tipo de empresa y seleccionando el asesor disponible con mayor compatibilidad y menor carga.

Este enfoque no solo reduce los tiempos de asignación sino que también mejora la calidad del servicio al garantizar que cada empresa recibe al asesor con el perfil más adecuado para sus necesidades específicas.
