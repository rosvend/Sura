"""Visualización UMAP 2D de prestadores, coloreada por arquetipo.

NO entra en el pipeline de producción. Es un add-on visual para la deck
de presentación / el dashboard: un scatter 2D donde se ven las 4 nubes
de arquetipos + la nube gris de excepciones. UMAP se usa SOLO para la
proyección visual; el clustering en producción sigue siendo PCA + KMeans
(determinístico, interpretable, ARCHETYPE_NAMES estables).

Lee:
  - sura_clustering_processed.prestador_clusters (cluster_id por DNI)
  - sura_clustering_processed.clustering_input   (matriz de FEATURE_COLS)

Escribe:
  - data/viz/cluster_umap.png

Uso:
    PYTHONPATH=. uv run python scripts/viz_clusters.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import polars as pl
import umap

from src.config import CLUSTERS_PARQUET, GOLD_PARQUETS
from src.gold.cluster_profiles import ARCHETYPE_NAMES
from src.gold.clustering_input import FEATURE_COLS

# Paleta SURA (GUIA_COLORES.md). Gris para el bucket de excepciones (-1).
PALETTE: dict[int, str] = {
    -1: "#888B8D",  # Neutral Gray
     0: "#2D6DF6",  # Azure Blue (Generalistas — el grupo más grande)
     1: "#00AEC7",  # Aqua (Especialistas Regionales)
     2: "#E3E829",  # Cheerful Yellow (Locales Sub-Utilizados)
     3: "#0033A0",  # SURA Blue (Virtuales Especializados)
}

OUTPUT_PATH = Path("data/viz/cluster_umap.png")


def main() -> None:
    print("[viz] cargando prestador_clusters + clustering_input desde GCS…")
    clusters = pl.read_parquet(CLUSTERS_PARQUET).select(["DNI_PRESTADOR", "cluster_id"])
    feats = pl.read_parquet(GOLD_PARQUETS["clustering_input"]).select(
        ["DNI_PRESTADOR", *FEATURE_COLS]
    )
    df = clusters.join(feats, on="DNI_PRESTADOR", how="inner")
    print(f"[viz]   {df.height:,} prestadores · {len(FEATURE_COLS)} features")

    # Matriz numérica para UMAP. Sin imputación adicional — clustering_input
    # ya está sin nulls; un fillna(0) defensivo por si acaso.
    X = df.select(FEATURE_COLS).fill_null(0.0).to_numpy()

    print("[viz] proyectando con UMAP(n_components=2, random_state=42)…")
    reducer = umap.UMAP(
        n_components=2,
        random_state=42,
        min_dist=0.3,
        n_neighbors=30,
        metric="euclidean",
    )
    emb = reducer.fit_transform(X)
    labels = df["cluster_id"].to_numpy()

    print("[viz] renderizando scatter…")
    fig, ax = plt.subplots(figsize=(10, 7), dpi=140)
    for cid in sorted(ARCHETYPE_NAMES.keys()):
        mask = labels == cid
        if mask.sum() == 0:
            continue
        ax.scatter(
            emb[mask, 0], emb[mask, 1],
            s=10, alpha=0.55,
            c=PALETTE[cid],
            label=f"{cid}: {ARCHETYPE_NAMES[cid]} (n={int(mask.sum()):,})",
            edgecolors="none",
        )
    ax.set_title(
        "Prestadores SURA — proyección UMAP 2D\n"
        "color = arquetipo (KMeans k=5 sobre 19 features, PCA(0.90) en producción)",
        fontsize=11,
    )
    ax.set_xlabel("UMAP-1"); ax.set_ylabel("UMAP-2")
    ax.set_xticks([]); ax.set_yticks([])
    ax.legend(loc="best", fontsize=8, framealpha=0.9)
    ax.grid(alpha=0.15)
    plt.tight_layout()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUTPUT_PATH, bbox_inches="tight")
    plt.close()
    print(f"[viz] PNG → {OUTPUT_PATH.resolve()}")


if __name__ == "__main__":
    main()
