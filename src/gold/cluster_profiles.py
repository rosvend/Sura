"""Gold layer — perfilado y nombramiento de clusters de prestadores.

Lee los artefactos de Día 1 (prestador_clusters.parquet + feat_prestador.parquet
+ clustering_input.parquet) y produce:

  - `build_cluster_profile()` — DataFrame de una fila por cluster con tamaños,
    medianas de features, modas de columnas categóricas, y banderas
    operativas (% virtual, % red estratégica). Usado por el dashboard de Día 5.
  - `discriminating_features()` — top-N features que más diferencian a un
    cluster del global, medidas por |z-score| de mediana del cluster vs
    mediana global.
  - `ARCHETYPE_NAMES` — mapping cluster_id → nombre de negocio. Hardcoded
    contra los resultados del fit con random_state=42 + el FEATURE_COLS y
    LOG_FEATURES de la rama main al 2026-05-09. Si se re-entrena con datos
    distintos, validar contra `build_cluster_profile()` antes de confiar en
    los nombres (los IDs de KMeans no son estables a través de refits).

Uso:
    from src.gold.cluster_profiles import build_cluster_profile, ARCHETYPE_NAMES
    profile = build_cluster_profile().to_pandas()
"""

from __future__ import annotations

import numpy as np
import polars as pl

from src.config import CLUSTERS_PARQUET, GOLD_PARQUETS
from src.gold.clustering_input import FEATURE_COLS

# ── Nombres de arquetipos ────────────────────────────────────────────────────
# Asignados a partir del perfil del fit con commit 98e1d98:
#   silhouette_kept=0.580  k=5  kept=4 arquetipos
# Los nombres reflejan la dimensión más diferenciadora (vs. global) de cada
# cluster — ver discriminating_features() para la evidencia.
ARCHETYPE_NAMES: dict[int, str] = {
    -1: "Excepciones / Routing Manual",
    0:  "Generalistas Estratégicos de Alto Volumen",
    1:  "Especialistas Regionales Multi-Municipio",
    2:  "Locales Sub-Utilizados Solo-Campo",
    3:  "Virtuales Especializados (Canal LIVIANA)",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_joined(
    clusters_parquet: str,
    feat_prestador_parquet: str,
    clustering_input_parquet: str,
) -> pl.DataFrame:
    """Une etiquetas + features + flags operativos en un solo DataFrame."""
    clusters = pl.read_parquet(clusters_parquet)
    ci = pl.read_parquet(clustering_input_parquet)
    prestador = pl.read_parquet(feat_prestador_parquet).select([
        "DNI_PRESTADOR",
        "es_red_estrategica",
        "FLAG_SOLO_VIRTUAL_2025",
        "FLAG_SIN_ACTIVIDAD_2025",
        "capacidad",
        "sin_capacidad",
    ])
    return (
        clusters
        .join(ci.select(["DNI_PRESTADOR", *FEATURE_COLS]), on="DNI_PRESTADOR", how="left")
        .join(prestador, on="DNI_PRESTADOR", how="left", suffix="_p")
    )


def _mode_or_none(s: pl.Series) -> str | None:
    """Devuelve el valor más frecuente de una serie, o None si está vacía."""
    if s.len() == 0:
        return None
    counts = s.value_counts(sort=True)
    return counts.row(0)[0] if counts.height else None


# ── API pública ──────────────────────────────────────────────────────────────

def build_cluster_profile(
    clusters_parquet: str = CLUSTERS_PARQUET,
    feat_prestador_parquet: str = GOLD_PARQUETS["feat_prestador"],
    clustering_input_parquet: str = GOLD_PARQUETS["clustering_input"],
) -> pl.DataFrame:
    """Tabla de una fila por cluster con resumen ejecutivo.

    Columnas de salida:
      cluster_id              int
      archetype_name          str (de ARCHETYPE_NAMES, "Sin nombre" si no mapea)
      n_providers             int
      share_of_total          float (0-1)
      pct_red_estrategica     float (0-1)
      pct_solo_virtual        float (0-1)
      pct_sin_capacidad       float (0-1)
      top_bloque              str
      top_tipo_perfil         str
      top_etapa               str
      top_tipo_red            str
      median_<feature>        float (una columna por FEATURE_COL)
    """
    df = _load_joined(clusters_parquet, feat_prestador_parquet, clustering_input_parquet)
    n_total = df.height

    rows: list[dict] = []
    for cid in sorted(df["cluster_id"].unique().to_list()):
        sub = df.filter(pl.col("cluster_id") == cid)
        row = {
            "cluster_id": int(cid),
            "archetype_name": ARCHETYPE_NAMES.get(int(cid), "Sin nombre"),
            "n_providers": sub.height,
            "share_of_total": sub.height / n_total,
            "pct_red_estrategica": float(
                # feat_prestador la persiste como bool; clustering_input la castea a float.
                # El join con suffix='_p' deja la versión bool en es_red_estrategica_p.
                sub["es_red_estrategica_p"].cast(pl.Float64).mean()
                if "es_red_estrategica_p" in sub.columns
                else sub["es_red_estrategica"].cast(pl.Float64).mean()
            ),
            "pct_solo_virtual": float(sub["FLAG_SOLO_VIRTUAL_2025"].mean()),
            "pct_sin_capacidad": float(sub["sin_capacidad"].mean()),
            "top_bloque": _mode_or_none(sub["bloque_principal"]),
            "top_tipo_perfil": _mode_or_none(sub["tipo_perfil"]),
            "top_etapa": _mode_or_none(sub["etapa_predominante"]),
            "top_tipo_red": _mode_or_none(sub["tipo_red"]),
        }
        for c in FEATURE_COLS:
            row[f"median_{c}"] = float(sub[c].median()) if sub.height else None
        rows.append(row)

    return pl.from_dicts(rows)


def discriminating_features(
    cluster_id: int,
    top_n: int = 5,
    clusters_parquet: str = CLUSTERS_PARQUET,
    clustering_input_parquet: str = GOLD_PARQUETS["clustering_input"],
) -> list[dict]:
    """Top-N features cuya mediana en el cluster más se aleja de la global.

    Métrica: |cluster_median - global_median| / global_std (z-score signed).
    Devuelve lista de dicts con keys: feature, cluster_median, global_median,
    z_score, direction ("HIGH"/"LOW"). Útil para construir las "score
    breakdown bars" en el dashboard.
    """
    clusters = pl.read_parquet(clusters_parquet)
    ci = pl.read_parquet(clustering_input_parquet)
    df = clusters.join(ci.select(["DNI_PRESTADOR", *FEATURE_COLS]), on="DNI_PRESTADOR")

    arr = df.select(FEATURE_COLS).to_numpy()
    global_med = np.median(arr, axis=0)
    global_std = arr.std(axis=0) + 1e-9
    labels = df["cluster_id"].to_numpy()

    mask = labels == cluster_id
    if mask.sum() == 0:
        return []
    cluster_med = np.median(arr[mask], axis=0)
    z = (cluster_med - global_med) / global_std
    order = np.argsort(-np.abs(z))[:top_n]

    return [
        {
            "feature": FEATURE_COLS[i],
            "cluster_median": float(cluster_med[i]),
            "global_median": float(global_med[i]),
            "z_score": float(z[i]),
            "direction": "HIGH" if z[i] > 0 else "LOW",
        }
        for i in order
    ]


if __name__ == "__main__":
    profile = build_cluster_profile()
    print(profile.select([
        "cluster_id", "archetype_name", "n_providers", "share_of_total",
        "pct_red_estrategica", "pct_solo_virtual", "top_bloque", "top_tipo_perfil",
    ]))
    print()
    for cid in sorted(ARCHETYPE_NAMES.keys()):
        print(f"\n=== {ARCHETYPE_NAMES[cid]} (cluster {cid}) — top discriminadores ===")
        for r in discriminating_features(cid):
            print(
                f"  {r['direction']}  z={r['z_score']:+.2f}  {r['feature']}: "
                f"cluster={r['cluster_median']:.3f}  global={r['global_median']:.3f}"
            )
