# Insights Relevantes Pre-Clustering - Reto SURA 2026

El objetivo de este documento es documentar insights, datos y observaciones importantes que se han identificado durante la fase de pre-clustering del reto. Estos insights pueden ser útiles para orientar el proceso de clustering y para entender mejor los datos con los que estamos trabajando.

## Metodología

El proceso que se va a describir se hizo por medio de un proyecto en GCP asociado al reto, se contó con la herramienta de Colab Enterprise dentro de Vertex AI, donde se programó la ejecución del notebook `prog_test_pre_clustering_v8.ipynb` usando un entorno de ejecución con una instancia E2-Standard-4 (4 vCPU, 16 GB de RAM) y se usó un bucket de Cloud Storage para guardar los datasets procesados y los resultados de los análisis.

Por razones de procesamiento y análisis, se seleccionó una muestra aleatoria de 15.000 registros del daatset de `Tareas_Programadas_canceladas_2025.txt`. El número optimo para una muestra finita representativa se calculó utilizando la fórmula de proporción demuestra finita, considerando un nivel de confianza del 95% y un margen de error del 5% (detallado en el notebook `prog_test_pre_clustering_v8.ipynb`). Y se hicieron diferentes combinaciones, análisis y grid de parámetros para medirnos y tener una noción inicial de los datos.

Antes de comenzar a detallar el análisis, lo que hizo fué realizar una breve limpieza y pre-procesamiento de los datos. Se hizo lo siguiente y en dicho orden:

1. Eliminación de columnas que sobrepasen cierto umbral de valores nulos (threshold >= 0.1).
2. Eliminación de columnas irrelevantes para el análisis (se eliminaron las columnas que contienen `DNI` aunque pueden servir para joins).
3. Imputación de valores faltantes usando la clase KNNImputer con k = 5, esto solo para una sola columna que quedó con nulos.
4. Normalización de valores numéricos usando StandardScaler.
5. Para la columna `TIPO_DE_ASESOR` basicamente se agruparon todas las categorías (que eran muchas) en solo 5 categorías principales: 'Mixto (Core)', 'Prevención', 'Riesgos', 'Proyectos' y 'Otros/Especiales'.
6. Codificación de variables categóricas usando el método pandas.get_dummies().

A lo largo del proceso, se hicieron varios tipos de procesamiento y análisis. Acá se detallan las nomenclaturas usadas para referenciar cada tipo de análisis/dataset:

- **dataset procesado**: Se refiere al dataset que ha pasado por el proceso previamente descrito.
- **dataset de embeddings**: Se rerifere al dataset preprocesado (sin la codificación de variables categóricas) al que se le aplicó la reducción de dimensionalidad usando el modelo de embeddings all-MiniLM-L6-v2 de Sentence Transformers (de 385 dimensiones + 4 numéricas).
- **dataset procesado + PCA**: Se refiere al dataset procesado al que se le aplicó la reducción de dimensionalidad usando PCA, con la prueba de cantidad de componentes que expliquen la varianza.
- **dataset de embeddings + PCA**: Se refiere al dataset de embeddings al que se le aplicó la reducción de dimensionalidad usando PCA, con la prueba de cantidad de componentes que expliquen la varianza.
- **dataset procesado + UMAP**: Se refiere al dataset procesado al que se le aplicó la reducción de dimensionalidad usando UMAP. Como UMAP no tiene una métrica para optimizar, a este proceso se le hizo un ajuste de hiperparámetros en los 3 métodos de clustering para medir su rendimiento.
- **dataset de embeddings + UMAP**: Se refiere al dataset de embeddings al que se le aplicó la reducción de dimensionalidad usando UMAP. Como UMAP no tiene una métrica para optimizar, a este proceso se le hizo un ajuste de hiperparámetros en los 3 métodos de clustering para medir su rendimiento.

## Método de Clustering Probados

Durante la fase de pre-clustering se probaron los siguientes métodos de clustering de SKLearn:

1. K-Means
2. Agglomerative Clustering
3. DBSCAN

Cada método se probó con diferentes combinaciones de los datasets mencionados anteriormente, y se evaluó su rendimiento usando las métricas de Silhouette Score.

## Nomenclatura y Convenciones de Datasets

| Dataset | Descripción |
|--------|------------|
| df  | Dataset limpio y normalizado con 13 columnas. |
| df1 | Dataset limpio, normalizado y procesado con OneHotEncoding (dummies). |
| df2 | Dataset con embeddings con 389 columnas (4 numéricas, 1 de texto sin importancia, 384 dimensiones del modelo all-MiniLM L6 v2). |
| df3 | Dataset normalizado con dummies + PCA (df1 + PCA). |
| df4 | Dataset con embeddings + PCA (df2 + PCA). |
| df5 | Dataset con embeddings + UMAP (df2 + UMAP). |
| df6 | Dataset normalizado con dummies + UMAP (df1 + UMAP). |

--------------------------

## Insights Relevantes

--------------------------

### Respecto a df3

* El PCA arrojó que con 71 componentes se explica el 90% de la varianza y con 171 componentes se explica el 95% de la varianza. Agregar 100 componentes solo para explicar un 5% adicional no es eficientes, así que el número de componentes se dejó en 71 para el dataset df3.

#### Grid de Hiperparámetros para df3 para K-Means, Agglomeartive Cluster y DBSCAN:

- K-Means: numero de clusters (5, 41, 2) → entre 5 y 40 clusters de a 2 en 2.
- Agglomerative Clustering: numero de clusters (5, 41, 2) → entre 5 y 40 clusters de a 2 en 2.
- DBSCAN: eps_range = [0.1, 0.3, 0.5, 0.7, 1.0] y min_samples_range = [5, 10, 20, 50], con limitación de que mínimo deben haber 2 clusters formados.

* Resultados delAjuste de Hiperparámetros para df3 para K-Means, Agglomeartive Cluster y DBSCAN:

  - K-Means no da buenos resultados, la inercia mínima es de 40.000 (muy alta) y el silhouette score nunca superó el 0.15.
  - Agglomerative Clustering no da buenos resultados, el silhouette score nunca superó el 0.15. Lo curioso es que a medida que se incrementa el número de clusters, el silhouette score va disminuyendo.
  - DBSCAN no tiene buen rendiemiento, a pesar de tener más variedad de hiperparámetros, las mejores combinaciones tiene un silhouette score negativo → pésima asignación, muchas veces lo puntos están más cerca a otros clusters que al suyo propio.


### Respecto a df4

* El PCA arrojó que el dataset de embeddings puede ser reducido a 4 componentes para explicar el 90% de la varianza, y a 14 componentes para explicar el 95% de la varianza. Se decidió usar 4 componentes para el dataset df4 → Navaja de Ockham, no es eficiente agregar 10 componentes para explicar un 5% adicional de la varianza.

#### Grid de Hiperparámetros para df4 para K-Means, Agglomeartive Cluster y DBSCAN:

- K-Means: numero de clusters (2, 11) → entre 2 y 10 clusters de a 1 en 1.
- Agglomerative Clustering: numero de clusters (2, 11) → entre 2 y 10 clusters de a 1 en 1.
- DBSCAN: eps_range = [0.1, 0.3, 0.5, 0.7, 1.0] y min_samples_range = [5, 10, 20], con limitación de que mínimo deben haber 2 clusters formados.

* Resultados delAjuste de Hiperparámetros para df4 para K-Means, Agglomeartive Cluster y DBSCAN:

  - K-Means nos da que 6 clusters se tiene una inercia de 7000 aproximadamente y un silhouette score de 0.942, lo cual es un resultado excelente. Sin embargo, habría que revisar la estabilidad de este resultado, ya que el dataset es pequeño y con pocas dimensiones, lo cual puede llevar a resultados inestables.
  - Agglomerative Clustering también da un resultado excelente con pocos cluster, siendo el mejor resultado con 2 clusters, con un silhouette score de 0.99, lo cual es casi perfecto.
  - DBSCAN tiene valores más variados entre 0.2 y 0.9. La mejor combinación fué con eps = 1.0, min_samples = 5 y con clsuters formados = 5 y tuvo un silhouette score de 0.90.


### Respecto a df5

* UMAP no tiene una métrixa como tal para optimizar sus hiperparámetros, así que se hizo un ajuste de hiperparámetros para los métodos de clustering con diferentes combinaciones de los hiperparámetros de UMAP. El dataset de embeddings + UMAP se probó con las siguientes combinaciones de hiperparámetros, por medio de itertools para generar todas esas combinaciones:

- K-Means y Agglomerative Clustering probaron el siguiente grid de hiperparámetros para UMAP:

    - n_components_range = [10, 20, 40, 80]
    - n_neighbors_range = [10, 30, 60, 100]
    - min_dist_range = [0.1, 0.3, 0.5]
    - clusters_range = [15, 35, 55]

- DBSCAN probó el siguiente grid de hiperparámetros para UMAP:

    - n_components_range = [20, 65, 100]
    - n_neighbors_range = [30, 60, 100]
    - min_dist_range = [0.25, 0.6]
    - eps_range = [0.5, 0.9]
    - min_samples_range = [15, 45]

* Resultados del Ajuste de Hiperparámetros para df5 para K-Means, Agglomeartive Cluster y DBSCAN:

  - K-Means, obtiene resultados entre las cotas de 0.58 y 0.60, siendo la mejor combinación global con n_components = 40, n_neighbors = 30, min_dist = 0.1, n_clusters = 35.
  - Agglomerative Clustering, muy parecido a los resultados de K-Means, obtiene resultados entre las cotas de 0.59 y 0.60, siendo la mejor combinación global con n_components = 80, n_neighbors = 60, min_dist = 0.1, n_clusters = 35.
  - DBSCAN, no ofece buen rendimiento, donde el mejor resultado evaluado tuve un silhouette score cercano a 0.4, indicando una mala asignación de clusters.


### Respecto a df6

* UMAP no tiene una métrixa como tal para optimizar sus hiperparámetros, así que se hizo un ajuste de hiperparámetros para los métodos de clustering con diferentes combinaciones de los hiperparámetros de UMAP. El dataset normalizado con dummies + UMAP se probó con las siguientes combinaciones de hiperparámetros, por medio de itertools para generar todas esas combinaciones:

- K-Means y Agglomerative Clustering probaron el siguiente grid de hiperparámetros para UMAP, se intentaron rangos mayores:

    - n_components_range = [20, 50, 100, 150]
    - n_neighbors_range = [30, 50, 100, 200]
    - min_dist_range = [0.1, 0.3, 0.5]
    - clusters_range = [15, 35, 55]

- DBSCAN probó el siguiente grid de hiperparámetros para UMAP, se intentaron rangos mayores:

    - n_components_range = [20, 100, 150]
    - n_neighbors_range = [30, 100, 200]
    - min_dist_range = [0.1, 0.3, 0.5]
    - eps_range = [0.7, 2.5]
    - min_samples_range = [20, 80]

* Resultados del Ajuste de Hiperparámetros para df6 para K-Means, Agglomeartive Cluster y DBSCAN:

  - K-Means, no obiene buenos resultados, donde el mejor resultado evaluado tuve un silhouette score cercano a 0.4, indicando una mala asignación de clusters.
  - Agglomerative Clustering, presenta resultados similares a K-Means, donde el mejor resultado evaluado tuve un silhouette score cercano a 0.4 o 0.48, indicando una mala asignación de clusters.
  - DBSCAN, todas las combinaciones evaluadas tiene buen rendiemiento, todos scores de silhouette cercanos a 0.8 o 0.9, indicando una excelente asignación de clusters, siendo la mejor combinación con n_components = 200, n_neighbors = 20, min_dist = 0.5, eps = 2.5, min_samples = 20, n_clusters = 5, silhouette score = 0.82. 


-------------------

## Conclusiones

* Normalmente, los resultados de silhouette score son similares entre K-Means y Agglomerative Clustering, esto porque ambos métodos de clustering buscan formar clusters compactos y separados, aunque con diferentes enfoques (K-Means es un método de partición, mientras que Agglomerative Clustering es un método jerárquico). Sin embargo, DBSCAN tiene resultados muy variados, lo cual puede ser debido a su naturaleza basada en densidad, que puede ser más sensible a la forma y distribución de los datos.

* Es fundamental reducir las dimensiones para los df1 (dataset procesado con dummies), paraa este caso del orden del 90%, es decir, tratar de reducir al 10%-15% de las dimensiones originales para tener mejores resultados en el clustering. Para el caso de los embeddings, la reducción de dimensionalidad no es tan crítica, ya que el modelo de embeddings ya ha hecho una reducción de dimensionalidad implícita al convertir el texto en vectores numéricos, aunque también se puede aplicar PCA o UMAP para mejorar los resultados.

* La combinación de embeddings + PCA (df4) + DBSCAN da resultados excelentes, con silhouette scores cercanos a 0.9, lo cual indica una excelente asignación de clusters. Estos sugiere que el modelo de embeddings all-MiniLM L6 v2 es capaz de capturar la semántica del texto de manera efectiva, y que la reducción de dimensionalidad con PCA ayuda a mejorar la calidad del clustering.

* Los dataset con procesamiento tradicional no dieron buenos resultados, en cambio, los datasets con embeddings demostraron mejores resultados, puede ser que lasegmentación clásica no es eficiente, siendo más cercano a NLP + clustering semántico este tipo de ejercicio.

* La estructura de los datos parece ser mayormente lineal, ya que las combinaciones con PCA dieron mejores resultados que las combinaciones con UMAP, lo cual sugiere que los datos pueden ser mejor representados en un espacio lineal reducido. Además, el PCA tuvo buen desempeño con los embeddings, sugiriendo que nos es influenciable por el ruido semántico al hacer la reducción de dimensionalida.

* DISCLAIMER: Estos insights son preliminares y se basan en una muestra de 15.000 registros, por lo que pueden no ser representativos de todo el dataset. Además, los resultados pueden variar dependiendo de la configuración de los hiperparámetros y del método de clustering utilizado, por lo que es importante seguir explorando y ajustando estos parámetros para obtener mejores resultados, sobre todo a la hora de incluir y unir los demás datasets y aumentar muy significativamente la cantidad de registros.