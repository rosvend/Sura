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
    """Materializa el LazyFrame y devuelve (df_completo, X numpy)."""
    df = build_clustering_input().collect()
    df = df.with_columns(pl.col(FEATURE_COLS).fill_null(0).fill_nan())
    X = df.select(FEATURE_COLS).to_numpy() 
    return df, X


def _fit_preprocessing(X: np.ndarray) -> tuple[RobustScaler, PCA, np.ndarray]:
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    # PCA con suficientes componentes para alcanzar PCA_VARIANCE_TARGET.
    # Empieza con todos y luego corta — más simple que iterar.
    pca_full = PCA(random_state=RANDOM_STATE).fit(X_scaled)
    cumvar = np.cumsum(pca_full.explained_variance_ratio_)
    n_components = int(np.searchsorted(cumvar, PCA_VARIANCE_TARGET) + 1)
    n_components = max(n_components, 2)

    pca = PCA(n_components=n_components, random_state=RANDOM_STATE).fit(X_scaled)
    X_pca = pca.transform(X_scaled)
    return scaler, pca, X_pca


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


def _select_kmeans(results: list[KMeansResult], min_cluster_size: int = 50) -> KMeansResult:
    """Selecciona k combinando silhouette con interpretabilidad de negocio.

    Reglas:
      1. Filtrar k cuyo cluster más pequeño tenga >= min_cluster_size prestadores.
      2. De esos, elegir el de mayor silhouette.
    Si ninguno cumple (1), se acepta el de mayor silhouette aunque tenga clusters
    pequeños (caso borde; se reporta en la metadata).
    """
    elegibles = [r for r in results if min(r.cluster_sizes) >= min_cluster_size]
    pool = elegibles if elegibles else results
    return max(pool, key=lambda r: r.silhouette)


def fit_and_persist(
    k_range: Iterable[int] = DEFAULT_K_RANGE,
    models_dir: str = MODELS_DIR_GCS,
    clusters_parquet: str = CLUSTERS_PARQUET,
) -> dict:
    df, X = _load_matrix()
    n_rows, n_features = X.shape

    scaler, pca, X_pca = _fit_preprocessing(X)

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
    labels = final_model.labels_
    distance_to_centroid = distances_all[np.arange(len(labels)), labels]

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
        pl.Series("cluster_id", labels.astype(np.int32)),
        pl.Series("distance_to_centroid", distance_to_centroid),
    ])

    df_out.write_parquet(clusters_parquet)

    _joblib_dump_gcs(scaler,      f"{models_dir}/scaler.joblib")
    _joblib_dump_gcs(pca,         f"{models_dir}/pca.joblib")
    _joblib_dump_gcs(final_model, f"{models_dir}/model.joblib")

    metadata = {
        "n_rows": int(n_rows),
        "n_features_in": int(n_features),
        "feature_cols": FEATURE_COLS,
        "pca_components": int(pca.n_components_),
        "pca_variance_explained": float(pca.explained_variance_ratio_.sum()),
        "selected": asdict(selected),
        "kmeans_grid": [asdict(r) for r in kmeans_results],
        "hdbscan_grid": [asdict(r) for r in hdbscan_results],
        "random_state": RANDOM_STATE,
        "parquet_path": clusters_parquet,
        "models_dir": models_dir,
    }
    _write_text_gcs(json.dumps(metadata, indent=2), f"{models_dir}/metadata.json")
    return metadata


def load_pipeline(models_dir: str = MODELS_DIR_GCS) -> tuple[RobustScaler, PCA, KMeans]:
    scaler = _joblib_load_gcs(f"{models_dir}/scaler.joblib")
    pca    = _joblib_load_gcs(f"{models_dir}/pca.joblib")
    model  = _joblib_load_gcs(f"{models_dir}/model.joblib")
    return scaler, pca, model


def assign(df_features: pl.DataFrame, models_dir: str = MODELS_DIR_GCS) -> np.ndarray:
    """Asigna cluster_id a un DataFrame con las columnas FEATURE_COLS."""
    scaler, pca, model = load_pipeline(models_dir)
    X = df_features.select(FEATURE_COLS).to_numpy()
    return model.predict(pca.transform(scaler.transform(X)))


if __name__ == "__main__":
    meta = fit_and_persist()
    sel = meta["selected"]
    print(f"PCA components: {meta['pca_components']} (var={meta['pca_variance_explained']:.3f})")
    print(f"Selected k={sel['k']}  silhouette={sel['silhouette']:.3f}  "
          f"CH={sel['calinski_harabasz']:.0f}  DB={sel['davies_bouldin']:.3f}")
    print(f"Cluster sizes: {sel['cluster_sizes']}")
    print(f"Wrote: {meta['parquet_path']}")
