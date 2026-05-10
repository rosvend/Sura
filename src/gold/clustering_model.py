"""Gold layer — modelo de clustering productivo sobre la matriz de prestadores.

Pipeline:
    build_clustering_input()          → ~6.289 prestadores activos × 23 features
    RobustScaler                      → robusto a colas pesadas (n_citas_total, costos)
    PCA(varianza acumulada >= 0.90)   → reduce a ~10–14 componentes
    KMeans + HDBSCAN (grid)           → seleccion por silhouette + interpretabilidad
    persistencia joblib + parquet     → modelo, escalador, PCA, etiquetas

Uso programático:
    from src.gold.clustering_model import fit_and_persist
    result = fit_and_persist()
    print(result["selected"])

CLI:
    uv run python -m src.gold.clustering_model
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Iterable

import gcsfs
import joblib
import numpy as np
import polars as pl
from sklearn.cluster import HDBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.preprocessing import RobustScaler

from src.config import CLUSTERS_PARQUET, MODELS_DIR_GCS
from src.gold.clustering_input import FEATURE_COLS, build_clustering_input

PCA_VARIANCE_TARGET = 0.90
DEFAULT_K_RANGE = range(3, 11)
DEFAULT_HDBSCAN_MCS = (50, 100, 150)
RANDOM_STATE = 42

# Tamaño mínimo para que un cluster se considere "real" (operativamente útil).
# Clusters por debajo de este umbral se reasignan a -1 (ruido) en post-fit,
# uniéndose a los outliers ya marcados por IsolationForest. Esto absorbe los
# micro-grupos residuales (~11–24 prestadores) que persistían en todos los k
# tras el quarantine — son extremos en ejes que IF no pondera lo suficiente.
MIN_KEPT_CLUSTER_SIZE = 100

# Mínimo de clusters "reales" para aceptar un k. Garantiza que el modelo
# entregue al menos esta cantidad de arquetipos diferenciados a Día 2.
MIN_N_KEPT_CLUSTERS = 3

# Features con colas pesadas (costos, conteos altos, duraciones) que distorsionan
# PCA si entran sin transformar. Se aplica log1p antes del scaler para que la
# varianza del cuerpo de la distribución no quede aplastada por la cola.
LOG_FEATURES = frozenset({
    "n_citas_total",
    "n_empresas_atendidas",
    "costo_logistico_prom",
    "antiguedad_dias",
    "dias_ciclo_informe_prom",
    "duracion_promedio_ejecutada",
    "n_municipios_cobertura",
    "n_municipios_destino",
})

# Fracción de prestadores marcados como outliers por IsolationForest. Estos
# reciben cluster_id = -1 (convención HDBSCAN de ruido) y se enrutan a manejo
# manual en Día 3. Empíricamente, la primera corrida sin quarantine produjo
# 27 outliers degenerados en clusters de tamaño 24+3 sobre 5,449 prestadores;
# 0.01 (≈55) cubre eso con margen sin esconder subclusters reales.
IFOREST_CONTAMINATION = 0.03

# ── Helpers GCS ──────────────────────────────────────────────────────────────
# joblib no soporta gs:// directamente; abrimos el handle con gcsfs y le pasamos
# el file-object. Para metadata.json usamos el mismo fs.

def _gcs() -> gcsfs.GCSFileSystem:
    return gcsfs.GCSFileSystem()


def _joblib_dump_gcs(obj, uri: str) -> None:
    with _gcs().open(uri, "wb") as f:
        joblib.dump(obj, f)


def _joblib_load_gcs(uri: str):
    with _gcs().open(uri, "rb") as f:
        return joblib.load(f)


def _write_text_gcs(text: str, uri: str) -> None:
    with _gcs().open(uri, "w") as f:
        f.write(text)


@dataclass
class KMeansResult:
    k: int
    silhouette: float
    calinski_harabasz: float
    davies_bouldin: float
    inertia: float
    cluster_sizes: list[int]


@dataclass
class HDBSCANResult:
    min_cluster_size: int
    n_clusters: int
    n_noise: int
    silhouette: float | None  # None si todo es ruido o un solo cluster
    cluster_sizes: list[int]


def _load_matrix() -> tuple[pl.DataFrame, np.ndarray]:
    """Materializa el LazyFrame, aplica log1p a LOG_FEATURES y devuelve (df, X).

    El log1p se aplica sobre el DataFrame de Polars antes de extraer el numpy,
    para que el orden de FEATURE_COLS quede inalterado y los valores transformados
    queden trazables en `df`.
    """
    df = build_clustering_input().collect()
    df = df.with_columns(pl.col(FEATURE_COLS).fill_null(0).fill_nan(0))
    df = df.with_columns([
        pl.col(c).log1p() for c in LOG_FEATURES if c in FEATURE_COLS
    ])
    X = df.select(FEATURE_COLS).to_numpy()
    return df, X


def _fit_preprocessing(
    X: np.ndarray,
) -> tuple[RobustScaler, PCA, np.ndarray, IsolationForest, np.ndarray]:
    """Quarantine + scaler + PCA, en ese orden.

    1. Fit IsolationForest sobre la matriz log-transformada completa para
       producir una máscara de inliers.
    2. RobustScaler y PCA se entrenan **solo** con inliers — así los ejes
       principales reflejan la población típica y no quedan distorsionados
       por unos pocos prestadores con costos/conteos extremos.

    Devuelve (scaler, pca, X_pca_inliers, iforest, inlier_mask). El caller
    es responsable de aplicar la máscara a otras estructuras (e.g., el
    DataFrame original) si las necesita alineadas.
    """
    iforest = IsolationForest(
        contamination=IFOREST_CONTAMINATION,
        random_state=RANDOM_STATE,
    ).fit(X)
    inlier_mask = iforest.predict(X) == 1
    X_in = X[inlier_mask]

    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X_in)

    # PCA con suficientes componentes para alcanzar PCA_VARIANCE_TARGET.
    # Empieza con todos y luego corta — más simple que iterar.
    pca_full = PCA(random_state=RANDOM_STATE).fit(X_scaled)
    cumvar = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.searchsorted(cumvar, PCA_VARIANCE_TARGET) + 1)
    n_components = max(n_components, 2)

    pca = PCA(n_components=n_components, random_state=RANDOM_STATE).fit(X_scaled)
    X_pca = pca.transform(X_scaled)
    return scaler, pca, X_pca, iforest, inlier_mask


def evaluate_kmeans(X_pca: np.ndarray, k_range: Iterable[int] = DEFAULT_K_RANGE) -> list[KMeansResult]:
    results: list[KMeansResult] = []
    for k in k_range:
        model = KMeans(n_clusters=k, n_init=20, random_state=RANDOM_STATE).fit(X_pca)
        labels = model.labels_
        sizes = np.bincount(labels).tolist()
        results.append(
            KMeansResult(
                k=k,
                silhouette=float(silhouette_score(X_pca, labels)),
                calinski_harabasz=float(calinski_harabasz_score(X_pca, labels)),
                davies_bouldin=float(davies_bouldin_score(X_pca, labels)),
                inertia=float(model.inertia_),
                cluster_sizes=sizes,
            )
        )
    return results


def evaluate_hdbscan(X_pca: np.ndarray, mcs_values: Iterable[int] = DEFAULT_HDBSCAN_MCS) -> list[HDBSCANResult]:
    results: list[HDBSCANResult] = []
    for mcs in mcs_values:
        model = HDBSCAN(min_cluster_size=mcs).fit(X_pca)
        labels = model.labels_
        n_noise = int((labels == -1).sum())
        clusters = labels[labels != -1]
        unique = np.unique(clusters)
        n_clusters = int(len(unique))
        sizes = np.bincount(clusters).tolist() if n_clusters else []

        sil: float | None = None
        if n_clusters >= 2:
            mask = labels != -1
            sil = float(silhouette_score(X_pca[mask], labels[mask]))

        results.append(
            HDBSCANResult(
                min_cluster_size=mcs,
                n_clusters=n_clusters,
                n_noise=n_noise,
                silhouette=sil,
                cluster_sizes=sizes,
            )
        )
    return results


def _select_kmeans(
    results: list[KMeansResult],
    min_kept_size: int = MIN_KEPT_CLUSTER_SIZE,
    min_n_kept: int = MIN_N_KEPT_CLUSTERS,
) -> KMeansResult:
    """Selecciona k por silhouette entre k con suficientes clusters "reales".

    Un cluster es "real" si tiene >= min_kept_size prestadores. Los clusters
    pequeños se absorben en post-fit como ruido (-1), por lo que aquí solo
    necesitamos garantizar que sobren al menos min_n_kept arquetipos
    interpretables.

    Si ningún k satisface la regla, se levanta `RuntimeError` con la grilla.
    """
    elegibles = [
        r for r in results
        if sum(s >= min_kept_size for s in r.cluster_sizes) >= min_n_kept
    ]
    if not elegibles:
        grid = "\n".join(
            f"  k={r.k:2d}  silhouette={r.silhouette:.3f}  sizes={r.cluster_sizes}"
            for r in results
        )
        raise RuntimeError(
            f"Ningún k produjo >= {min_n_kept} clusters de tamaño >= {min_kept_size}.\n"
            f"Grilla KMeans:\n{grid}\n"
            f"Triage: ajustar MIN_KEPT_CLUSTER_SIZE / MIN_N_KEPT_CLUSTERS, subir "
            f"IFOREST_CONTAMINATION, o revisar features con varianza extrema."
        )
    return max(elegibles, key=lambda r: r.silhouette)


def fit_and_persist(
    k_range: Iterable[int] = DEFAULT_K_RANGE,
    models_dir: str = MODELS_DIR_GCS,
    clusters_parquet: str = CLUSTERS_PARQUET,
) -> dict:
    df, X = _load_matrix()
    n_rows, n_features = X.shape

    scaler, pca, X_pca, iforest, inlier_mask = _fit_preprocessing(X)
    n_inliers = int(inlier_mask.sum())
    n_outliers = int((~inlier_mask).sum())

    # KMeans + HDBSCAN se entrenan/evalúan solo sobre inliers para que el
    # silhouette refleje la separación real de la población típica y no la
    # distancia trivial a outliers extremos.
    kmeans_results = evaluate_kmeans(X_pca, k_range)
    hdbscan_results = evaluate_hdbscan(X_pca)
    selected = _select_kmeans(kmeans_results)

    final_model = KMeans(
        n_clusters=selected.k,
        n_init=20,
        random_state=RANDOM_STATE,
    ).fit(X_pca)

    centroids = final_model.cluster_centers_
    distances_all = np.linalg.norm(X_pca[:, None, :] - centroids[None, :, :], axis=2)
    inlier_labels = final_model.labels_
    inlier_dists = distances_all[np.arange(len(inlier_labels)), inlier_labels]

    # ── Post-hoc: clusters pequeños → ruido (-1) ────────────────────────────
    # KMeans peló micro-clusters de ~10–25 prestadores que IsolationForest no
    # alcanzó (extremos en ejes que IF no pondera lo suficiente). Los absorbemos
    # como ruido aquí en vez de fallar la corrida — preservamos los 3–4
    # arquetipos reales y unificamos ruido en el bucket -1 ya existente.
    sizes_per_cluster = np.bincount(inlier_labels, minlength=selected.k)
    kept_old_ids = np.where(sizes_per_cluster >= MIN_KEPT_CLUSTER_SIZE)[0]
    n_kept_clusters = int(len(kept_old_ids))

    cluster_id_remap = np.full(selected.k, -1, dtype=np.int32)
    for new_id, old_id in enumerate(kept_old_ids):
        cluster_id_remap[old_id] = new_id

    inlier_labels_kept = cluster_id_remap[inlier_labels]
    n_relabeled_as_noise = int((inlier_labels_kept == -1).sum())
    kept_cluster_sizes = [int(sizes_per_cluster[old_id]) for old_id in kept_old_ids]
    inlier_dists_kept = np.where(inlier_labels_kept == -1, 0.0, inlier_dists)

    # Silhouette recomputado solo sobre los clusters preservados, para que la
    # métrica reportada refleje la calidad real de los arquetipos finales y no
    # quede inflada por la separación trivial de los micro-clusters de ruido.
    kept_mask_inliers = inlier_labels_kept != -1
    if (
        kept_mask_inliers.sum() >= 2
        and len(np.unique(inlier_labels_kept[kept_mask_inliers])) >= 2
    ):
        silhouette_kept = float(silhouette_score(
            X_pca[kept_mask_inliers], inlier_labels_kept[kept_mask_inliers]
        ))
    else:
        silhouette_kept = None

    # Reconstruir labels y distancias en el orden original del df: outliers
    # IF + clusters pequeños comparten cluster_id = -1; preservamos las 5,449
    # filas para que Día 3 filtre por cluster != -1.
    full_labels = np.full(n_rows, -1, dtype=np.int32)
    full_labels[inlier_mask] = inlier_labels_kept.astype(np.int32)
    full_dists = np.zeros(n_rows, dtype=np.float64)
    full_dists[inlier_mask] = inlier_dists_kept

    df_out = df.select([
        "DNI_PRESTADOR",
        "bloque_principal",
        "tipo_perfil",
        "tipo_red",
        "municipio_base",
        "sector_principal_atendido",
        "segmento_principal_atendido",
        "etapa_predominante",
    ]).with_columns([
        pl.Series("cluster_id", full_labels),
        pl.Series("distance_to_centroid", full_dists),
    ])

    df_out.write_parquet(clusters_parquet)

    _joblib_dump_gcs(scaler,           f"{models_dir}/scaler.joblib")
    _joblib_dump_gcs(pca,              f"{models_dir}/pca.joblib")
    _joblib_dump_gcs(final_model,      f"{models_dir}/model.joblib")
    _joblib_dump_gcs(iforest,          f"{models_dir}/isolation_forest.joblib")
    _joblib_dump_gcs(cluster_id_remap, f"{models_dir}/cluster_id_remap.joblib")

    # pct_empresa_compleja salió mediana=0 en los 3 clusters de la primera
    # corrida. Persistimos el describe para triagearlo desde Día 2 (binarizar
    # vs. dropear) sin tener que volver a Colab.
    pct_complex_describe = (
        df.select("pct_empresa_compleja").describe().to_dicts()
        if "pct_empresa_compleja" in df.columns
        else None
    )

    metadata = {
        "n_rows": int(n_rows),
        "n_inliers": n_inliers,
        "n_outliers_iforest": n_outliers,
        "n_relabeled_as_noise": n_relabeled_as_noise,
        "n_total_noise": int(n_outliers + n_relabeled_as_noise),
        "iforest_contamination": IFOREST_CONTAMINATION,
        "log_features": sorted(LOG_FEATURES),
        "n_features_in": int(n_features),
        "feature_cols": FEATURE_COLS,
        "pca_components": int(pca.n_components_),
        "pca_variance_explained": float(pca.explained_variance_ratio_.sum()),
        "selected": asdict(selected),
        "kmeans_grid": [asdict(r) for r in kmeans_results],
        "hdbscan_grid": [asdict(r) for r in hdbscan_results],
        "n_kept_clusters": n_kept_clusters,
        "kept_cluster_sizes": kept_cluster_sizes,
        "silhouette_kept": silhouette_kept,
        "cluster_id_remap": cluster_id_remap.tolist(),
        "random_state": RANDOM_STATE,
        "min_kept_cluster_size": MIN_KEPT_CLUSTER_SIZE,
        "min_n_kept_clusters": MIN_N_KEPT_CLUSTERS,
        "parquet_path": clusters_parquet,
        "models_dir": models_dir,
        "pct_empresa_compleja_describe": pct_complex_describe,
    }
    _write_text_gcs(json.dumps(metadata, indent=2), f"{models_dir}/metadata.json")
    return metadata


def load_pipeline(
    models_dir: str = MODELS_DIR_GCS,
) -> tuple[RobustScaler, PCA, KMeans, IsolationForest, np.ndarray]:
    scaler  = _joblib_load_gcs(f"{models_dir}/scaler.joblib")
    pca     = _joblib_load_gcs(f"{models_dir}/pca.joblib")
    model   = _joblib_load_gcs(f"{models_dir}/model.joblib")
    iforest = _joblib_load_gcs(f"{models_dir}/isolation_forest.joblib")
    remap   = _joblib_load_gcs(f"{models_dir}/cluster_id_remap.joblib")
    return scaler, pca, model, iforest, remap


def assign(df_features: pl.DataFrame, models_dir: str = MODELS_DIR_GCS) -> np.ndarray:
    """Asigna cluster_id a un DataFrame con las columnas FEATURE_COLS.

    Aplica el mismo pipeline que `fit_and_persist`:
      1. log1p sobre LOG_FEATURES
      2. IsolationForest gate (outliers → -1)
      3. KMeans sobre los inliers, devolviendo IDs originales del modelo
      4. Remap: IDs originales → IDs compactos del parquet (clusters
         pequeños suprimidos durante el fit también caen a -1)

    Devuelve np.ndarray de int en el orden de las filas de df_features.
    """
    scaler, pca, model, iforest, remap = load_pipeline(models_dir)

    df_log = df_features.with_columns([
        pl.col(c).log1p() for c in LOG_FEATURES if c in FEATURE_COLS
    ])
    X = df_log.select(FEATURE_COLS).to_numpy()

    inlier_mask = iforest.predict(X) == 1
    out = np.full(X.shape[0], -1, dtype=np.int32)
    if inlier_mask.any():
        X_in = X[inlier_mask]
        raw_labels = model.predict(pca.transform(scaler.transform(X_in)))
        out[inlier_mask] = remap[raw_labels].astype(np.int32)
    return out


if __name__ == "__main__":
    meta = fit_and_persist()
    sel = meta["selected"]
    sil_kept = meta["silhouette_kept"]
    sil_kept_str = f"{sil_kept:.3f}" if sil_kept is not None else "n/a"
    print(
        f"Inliers: {meta['n_inliers']:,}  "
        f"IF outliers: {meta['n_outliers_iforest']:,}  "
        f"Small-cluster relabel: {meta['n_relabeled_as_noise']:,}  "
        f"→ Total noise: {meta['n_total_noise']:,}"
    )
    print(f"PCA components: {meta['pca_components']} (var={meta['pca_variance_explained']:.3f})")
    print(
        f"Selected k={sel['k']}  raw silhouette={sel['silhouette']:.3f}  "
        f"CH={sel['calinski_harabasz']:.0f}  DB={sel['davies_bouldin']:.3f}"
    )
    print(f"KMeans raw sizes: {sel['cluster_sizes']}")
    print(
        f"Kept {meta['n_kept_clusters']} arquetipos: {meta['kept_cluster_sizes']}  "
        f"silhouette_kept={sil_kept_str}"
    )
    print(f"Wrote: {meta['parquet_path']}")
