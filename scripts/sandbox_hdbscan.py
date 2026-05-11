"""SANDBOX — V1 (PCA + KMeans, producción) vs V2 (UMAP 5D + HDBSCAN).

READ-ONLY. No toca el pipeline de producción:
  · sólo lee parquets desde GCS (clustering_input, prestador_clusters)
  · no llama a `src.gold.clustering_model` ni reescribe ARCHETYPE_NAMES
  · no escribe a GCS ni a BigQuery
  · output: viz/sandbox_comparison.png + métricas a stdout

Uso:
    PYTHONPATH=. uv run python scripts/sandbox_hdbscan.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
import umap
from sklearn.cluster import HDBSCAN
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.preprocessing import RobustScaler

from src.config import CLUSTERS_PARQUET, GOLD_PARQUETS
from src.gold.clustering_input import FEATURE_COLS

# Heavy-tailed features (compresión log1p antes del scaling).
LOG_FEATURES: list[str] = [
    "n_citas_total",
    "n_empresas_atendidas",
    "costo_logistico_prom",
    "antiguedad_dias",
    "dias_ciclo_informe_prom",
    "duracion_promedio_ejecutada",
]

RANDOM_STATE = 42
OUTPUT_PATH = Path("viz/sandbox_comparison.png")


def _load_features_and_v1() -> tuple[pl.DataFrame, np.ndarray]:
    """Lee clustering_input + V1 labels desde GCS. Read-only."""
    print("[sandbox] cargando clustering_input + prestador_clusters (read-only)…")
    feats = pl.read_parquet(GOLD_PARQUETS["clustering_input"]).select(
        ["DNI_PRESTADOR", *FEATURE_COLS]
    )
    v1 = pl.read_parquet(CLUSTERS_PARQUET).select(["DNI_PRESTADOR", "cluster_id"])
    joined = feats.join(v1, on="DNI_PRESTADOR", how="inner")
    print(f"[sandbox]   {joined.height:,} prestadores · {len(FEATURE_COLS)} features")
    return joined, joined["cluster_id"].to_numpy()


def _transform_features(df: pl.DataFrame) -> np.ndarray:
    """log1p en heavy-tails + RobustScaler en memoria. No persiste nada."""
    print(f"[sandbox] log1p en {len(LOG_FEATURES)} features pesadas + RobustScaler…")
    expr = []
    for c in FEATURE_COLS:
        if c in LOG_FEATURES:
            # log1p(x) requiere x ≥ -1; las heavy-tails son ≥ 0 por construcción,
            # clip(0) es defensa contra cualquier residual numérico.
            expr.append(pl.col(c).fill_null(0.0).clip(lower_bound=0.0).log1p().alias(c))
        else:
            expr.append(pl.col(c).fill_null(0.0))
    X = df.with_columns(expr).select(FEATURE_COLS).to_numpy()
    return RobustScaler().fit_transform(X)


def _fit_v2_labels(X_scaled: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """UMAP 5D → HDBSCAN, y un UMAP 2D separado solo para visualizar."""
    print("[sandbox] UMAP 5D (n_neighbors=30, min_dist=0.0) para clustering…")
    reducer_5d = umap.UMAP(
        n_components=5,
        n_neighbors=30,
        min_dist=0.0,
        random_state=RANDOM_STATE,
        metric="euclidean",
    )
    X_5d = reducer_5d.fit_transform(X_scaled)

    print("[sandbox] HDBSCAN(min_cluster_size=50, cluster_selection_epsilon=0.5)…")
    hdb = HDBSCAN(
        min_cluster_size=50,
        cluster_selection_epsilon=0.5,
    )
    v2_labels = hdb.fit_predict(X_5d)

    print("[sandbox] UMAP 2D (min_dist=0.3) para visualización…")
    reducer_2d = umap.UMAP(
        n_components=2,
        n_neighbors=30,
        min_dist=0.3,
        random_state=RANDOM_STATE,
        metric="euclidean",
    )
    emb_2d = reducer_2d.fit_transform(X_scaled)
    return v2_labels, emb_2d


def _print_distribution(name: str, labels: np.ndarray) -> None:
    counts = Counter(labels.tolist())
    total = len(labels)
    print(f"\n[sandbox] {name} — distribución de tamaños (n={total:,}):")
    for cid in sorted(counts.keys()):
        pct = counts[cid] / total * 100
        marker = "  (noise)" if cid == -1 else ""
        print(f"   cluster {cid:>3}: {counts[cid]:>6,}  ({pct:5.1f} %){marker}")


def _plot_comparison(
    emb_2d: np.ndarray, v1: np.ndarray, v2: np.ndarray, output: Path
) -> None:
    print(f"\n[sandbox] renderizando comparación lado-a-lado → {output}…")
    fig, axes = plt.subplots(1, 2, figsize=(16, 7), dpi=140)

    # V1 — paleta SURA fija para los 4 arquetipos + gris para -1
    v1_palette = {
        -1: "#888B8D", 0: "#2D6DF6", 1: "#00AEC7", 2: "#E3E829", 3: "#0033A0",
    }
    for cid in sorted(np.unique(v1).tolist()):
        m = v1 == cid
        axes[0].scatter(
            emb_2d[m, 0], emb_2d[m, 1],
            s=8, alpha=0.6, c=v1_palette.get(cid, "#444444"),
            label=f"{cid} (n={int(m.sum()):,})", edgecolors="none",
        )
    axes[0].set_title("V1 — PCA + KMeans (producción)", fontsize=11)
    axes[0].legend(loc="best", fontsize=8, framealpha=0.9)

    # V2 — tab20 para HDBSCAN, gris para noise (-1)
    cmap = plt.get_cmap("tab20")
    for i, cid in enumerate(sorted(np.unique(v2).tolist())):
        m = v2 == cid
        color = "#888B8D" if cid == -1 else cmap(i % 20)
        axes[1].scatter(
            emb_2d[m, 0], emb_2d[m, 1],
            s=8, alpha=0.6, c=[color],
            label=f"{cid} (n={int(m.sum()):,})", edgecolors="none",
        )
    axes[1].set_title("V2 — UMAP(5D) + HDBSCAN (sandbox, no producción)", fontsize=11)
    axes[1].legend(loc="best", fontsize=7, framealpha=0.9, ncol=2)

    for ax in axes:
        ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
        ax.set_xticks([]); ax.set_yticks([])
        ax.grid(alpha=0.15)

    fig.suptitle(
        "Sandbox V1 vs V2 — mismos 5,449 prestadores, dos métodos de clustering",
        fontsize=13, y=1.02,
    )
    plt.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, bbox_inches="tight")
    plt.close()


def main() -> None:
    joined, v1 = _load_features_and_v1()
    X_scaled = _transform_features(joined)
    v2, emb_2d = _fit_v2_labels(X_scaled)

    _print_distribution("V1 (PCA + KMeans)",   v1)
    _print_distribution("V2 (UMAP + HDBSCAN)", v2)

    # Similitud entre etiquetados — el número que va al slide de "lo evaluamos".
    nmi = normalized_mutual_info_score(v1, v2)
    ari = adjusted_rand_score(v1, v2)
    print(f"\n[sandbox] similitud V1 vs V2:")
    print(f"   NMI = {nmi:.3f}   (1.0 = idénticos · 0.0 = independientes)")
    print(f"   ARI = {ari:.3f}   (1.0 = idénticos · 0.0 = al azar)")

    _plot_comparison(emb_2d, v1, v2, OUTPUT_PATH)
    print(f"\n[sandbox] done — PNG en {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
