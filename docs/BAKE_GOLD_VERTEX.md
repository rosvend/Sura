# Materialización de la capa Gold en Vertex AI

## Por qué

`build_prestador_features()`, `build_empresa_features()` y
`build_clustering_input()` ejecutan joins entre Bronze→Silver→Gold sobre
~1.5M filas (Tareas_Programadas) × ~2.1M filas (Detalle_Empresa). El plan
lazy de Polars puede consumir 8–12 GB pico de RAM al colectar, lo que
bloquea máquinas locales con < 32 GB.

La solución es **bakear una sola vez** las tres tablas Gold a parquet en
GCS. Después, todo el pipeline (clustering, perfilado, motor de
asignación, dashboard) lee ~10 MB en milisegundos en lugar de recomputar.

Salida del bake (en `gs://sura-clustering-raw/gold/`):

| Archivo                  | Filas aprox. | Tamaño |
|--------------------------|--------------|--------|
| `feat_prestador.parquet` | ~6,500       | ~5 MB  |
| `clustering_input.parquet` | ~6,300     | ~2 MB  |
| `feat_empresa.parquet`   | ~2,175,000   | ~50 MB |

## Pasos en Vertex AI Colab Enterprise

Mismo entorno que usó Pablo para el pre-clustering: E2-Standard-4 (4 vCPU, 16 GB RAM).

1. **Crear runtime / notebook**
   - Vertex AI → Colab Enterprise → New Notebook
   - Runtime template: E2-Standard-4 (16 GB)
   - Region: la misma del bucket `sura-clustering-raw`

2. **Subir el código del repo** (una de las dos opciones)
   - **Opción A (recomendada): clonar desde Git.** En la primera celda:
     ```bash
     !git clone https://<token>@github.com/<owner>/sura.git
     %cd sura
     !pip install uv
     !uv sync
     ```
   - **Opción B: subir como zip.** Comprimir la carpeta del proyecto local
     (excluyendo `.venv`, `notebooks/*.ipynb` con outputs pesados) y
     subirla mediante el panel de archivos.

3. **Autenticación GCS** (Vertex AI normalmente la inyecta automáticamente
   con la cuenta de servicio del runtime; si no):
   ```bash
   !gcloud auth application-default login
   ```
   Verificar que la SA tiene permiso `roles/storage.objectAdmin` sobre
   `gs://sura-clustering-raw`.

4. **Ejecutar el bake**
   ```bash
   !uv run python scripts/bake_gold.py
   ```
   Salida esperada:
   ```
   [bake] feat_prestador → gs://sura-clustering-raw/gold/feat_prestador.parquet
   [bake] computed in ~120s — 6,514 rows × 73 cols
   [bake] wrote parquet in ~2s
   [bake] clustering_input → gs://sura-clustering-raw/gold/clustering_input.parquet
   [bake] computed in <1s (lee de feat_prestador.parquet)
   [bake] feat_empresa → gs://sura-clustering-raw/gold/feat_empresa.parquet
   [bake] computed in ~180s — 2,175,102 rows × 38 cols
   ```
   Tiempo total esperado: 5–10 min.

5. **Verificación**
   ```bash
   !gsutil ls -l gs://sura-clustering-raw/gold/
   ```
   Deben aparecer los tres parquets con tamaño > 0.

6. **Apagar el runtime** para no acumular cargos.

## Recomputar después de cambios

Si modificas la lógica de feature engineering (ej. una nueva métrica en
`feat_prestador_perfil.py`), necesitas re-bakear la tabla afectada:

```bash
!uv run python scripts/bake_gold.py feat_prestador clustering_input
```

`clustering_input` depende de `feat_prestador`, así que bakea ambos
juntos cuando cambies el perfil del prestador.

## Después del bake: trabajo local

Con las tres tablas en `gs://.../gold/`, todo lo siguiente corre en
segundos en una máquina local:

```python
from src.gold.clustering_input import build_clustering_input
df = build_clustering_input().collect()  # ~6,300 filas, instantáneo

from src.gold.feat_prestador import build_prestador_features
prestadores = build_prestador_features().collect()

from src.gold.feat_empresa import build_empresa_features
empresas = build_empresa_features().collect()
```

Y ya podemos correr `uv run python -m src.gold.clustering_model` localmente
sin que el sistema se congele.
