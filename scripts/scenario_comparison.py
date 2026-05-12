"""Comparación rule_based ↔ lp_optimized — el "Valor de la Optimización".

Cuantifica QUÉ cambia LP frente al greedy puro de scoring:
  - % de órdenes reasignadas a otro prestador.
  - Cambio en Gini de carga (equidad).
  - Distribución del delta de score (calidad vs equidad).
  - Cambio en costo logístico esperado por orden.

Estrictamente post-hoc: lee assignments.parquet + assignments_lp.parquet
+ feat_prestador.parquet. No toca exporter / optimizer / score / kpis.

Persiste dos tablas:
  - kpi_scenario_diff              — 1 fila con métricas globales
  - kpi_scenario_diff_by_cluster   — 1 fila por cluster (pivot por cluster RB)

Uso:
    PYTHONPATH=. uv run python scripts/scenario_comparison.py
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from src.config import (
    ASSIGNMENTS_PARQUET,
    BQ_PROJECT,
    BQ_TABLE_KPI_SCENARIO_DIFF,
    BQ_TABLE_KPI_SCENARIO_DIFF_BY_CLUSTER,
    GCS_BUCKET,
    GOLD_PARQUETS,
    KPI_SCENARIO_DIFF_BY_CLUSTER_PARQUET,
    KPI_SCENARIO_DIFF_PARQUET,
)
from src.gold.cluster_profiles import ARCHETYPE_NAMES
from src.monitoring.kpis import _gini  # reuse — fuente única de verdad de Gini

ASSIGNMENTS_LP_PARQUET = f"{GCS_BUCKET}/data/processed/assignments_lp.parquet"

ORDER_KEY = ["dni_empresa", "codigo_tarea", "cd_municipio_destino"]


def _load_scenario(path: str) -> pl.DataFrame:
    """Carga columnas mínimas necesarias para la comparación."""
    df = pl.read_parquet(path).select([
        *ORDER_KEY,
        "dni_prestador",
        "cluster_id",
        "score_total",
    ])
    print(f"[diff] cargado {path.rsplit('/', 1)[-1]}: {df.height:,} filas")
    return df


def _load_cost_lookup() -> pl.DataFrame:
    """Lookup DNI_PRESTADOR → costo_logistico_prom (mismo patrón que kpis.py)."""
    return (
        pl.read_parquet(GOLD_PARQUETS["feat_prestador"])
        .select(["DNI_PRESTADOR", "costo_logistico_prom"])
        .rename({"DNI_PRESTADOR": "dni_prestador"})
    )


def _refresh_bq(table: str, gs_uri: str) -> None:
    if not shutil.which("bq"):
        print(f"[diff] bq CLI no encontrado, omitiendo refresh de {table}")
        return
    cmd = ["bq", "load", "--replace", "--source_format=PARQUET",
           f"--project_id={BQ_PROJECT}", f"{BQ_PROJECT}:{table}", gs_uri]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[diff] BQ load FAILED for {table}:\n{res.stderr}")
        raise SystemExit(res.returncode)
    print(f"[diff] BQ {table} refreshed in {time.perf_counter() - t0:.1f}s")


def run() -> tuple[pl.DataFrame, pl.DataFrame]:
    t0 = time.perf_counter()

    rb = _load_scenario(ASSIGNMENTS_PARQUET).rename({
        "dni_prestador": "dni_prestador_rb",
        "cluster_id":    "cluster_id_rb",
        "score_total":   "score_total_rb",
    })
    lp = _load_scenario(ASSIGNMENTS_LP_PARQUET).rename({
        "dni_prestador": "dni_prestador_lp",
        "cluster_id":    "cluster_id_lp",
        "score_total":   "score_total_lp",
    })

    rb_total = rb.height
    lp_total = lp.height

    # Inner join sobre (empresa, tarea, muni). El gap rb − inner son órdenes
    # que LP no logró encajar bajo el cap (graceful overflow del optimizer).
    joined = rb.join(lp, on=ORDER_KEY, how="inner")
    n_compared = joined.height
    n_only_rb = rb_total - n_compared
    if n_compared == 0:
        raise SystemExit("[diff] ABORT: inner-join vacío. ¿Las parquets están alineadas?")

    print(f"[diff] inner-join: {n_compared:,} órdenes comparables "
          f"(rule_based={rb_total:,}, lp_optimized={lp_total:,}, "
          f"solo_rb={n_only_rb:,})")

    # Join de costo logístico por prestador (mismo patrón que kpis.py:130-158).
    cost = _load_cost_lookup()
    joined = (
        joined
        .join(cost.rename({
            "dni_prestador":        "dni_prestador_rb",
            "costo_logistico_prom": "costo_log_rb",
        }), on="dni_prestador_rb", how="left")
        .join(cost.rename({
            "dni_prestador":        "dni_prestador_lp",
            "costo_logistico_prom": "costo_log_lp",
        }), on="dni_prestador_lp", how="left")
    )
    n_cost_null_rb = int(joined["costo_log_rb"].is_null().sum())
    n_cost_null_lp = int(joined["costo_log_lp"].is_null().sum())
    if max(n_cost_null_rb, n_cost_null_lp) / max(n_compared, 1) > 0.05:
        print(f"[diff] WARNING: nulls en costo_log_* rb={n_cost_null_rb:,} "
              f"lp={n_cost_null_lp:,} (>5%) — métricas de costo son parciales")

    # ── Reasignación ──────────────────────────────────────────────────────────
    joined = joined.with_columns(
        (pl.col("dni_prestador_rb") != pl.col("dni_prestador_lp")).alias("reassigned"),
        (pl.col("cluster_id_rb") != pl.col("cluster_id_lp")).alias("cluster_changed"),
        (pl.col("score_total_lp") - pl.col("score_total_rb")).alias("score_delta"),
        (pl.col("costo_log_lp") - pl.col("costo_log_rb")).alias("cost_delta"),
    )

    n_reassigned = int(joined["reassigned"].sum())
    pct_reassigned = n_reassigned / n_compared

    # ── Gini de carga por escenario ──────────────────────────────────────────
    # Calculado sobre el universo inner-joined para que sean comparables 1:1.
    load_rb = joined.group_by("dni_prestador_rb").len().rename({"len": "n"})
    load_lp = joined.group_by("dni_prestador_lp").len().rename({"len": "n"})
    gini_rb = _gini(load_rb["n"].to_numpy())
    gini_lp = _gini(load_lp["n"].to_numpy())
    if not (0.0 <= gini_rb <= 1.0) or not (0.0 <= gini_lp <= 1.0):
        raise SystemExit(f"[diff] ABORT: Gini fuera de [0,1] · rb={gini_rb} lp={gini_lp}")
    gini_delta_abs = gini_lp - gini_rb
    gini_delta_rel = gini_delta_abs / gini_rb if gini_rb > 1e-9 else None

    # ── Score delta (LP-RB): negativo esperado (LP sacrifica calidad) ───────
    score_arr = joined["score_delta"].to_numpy()
    score_delta_mean = float(np.mean(score_arr))
    score_delta_p25  = float(np.percentile(score_arr, 25))
    score_delta_p50  = float(np.percentile(score_arr, 50))
    score_delta_p75  = float(np.percentile(score_arr, 75))

    # ── Costo logístico: signo se preserva, sin spin ─────────────────────────
    cost_log_mean_rb = float(joined["costo_log_rb"].drop_nulls().mean() or 0.0)
    cost_log_mean_lp = float(joined["costo_log_lp"].drop_nulls().mean() or 0.0)
    cost_delta_abs = cost_log_mean_lp - cost_log_mean_rb
    cost_savings_annual = cost_delta_abs * n_compared  # signo preservado

    score_mean_rb = float(joined["score_total_rb"].mean())
    score_mean_lp = float(joined["score_total_lp"].mean())

    now = datetime.now(timezone.utc).replace(microsecond=0)

    global_df = pl.DataFrame([{
        "n_orders_compared":           n_compared,
        "n_orders_only_in_rule_based": n_only_rb,
        "n_reassigned":                n_reassigned,
        "pct_reassigned":              pct_reassigned,
        "gini_load_rule_based":        gini_rb,
        "gini_load_lp_optimized":      gini_lp,
        "gini_delta_abs":              gini_delta_abs,
        "gini_delta_rel":              gini_delta_rel,
        "score_total_mean_rule_based": score_mean_rb,
        "score_total_mean_lp_optimized": score_mean_lp,
        "score_delta_mean":            score_delta_mean,
        "score_delta_p25":             score_delta_p25,
        "score_delta_p50":             score_delta_p50,
        "score_delta_p75":             score_delta_p75,
        "costo_log_mean_rule_based":   cost_log_mean_rb,
        "costo_log_mean_lp_optimized": cost_log_mean_lp,
        "costo_log_delta_abs":         cost_delta_abs,
        "cost_savings_annual_cop":     cost_savings_annual,
        "n_costo_log_null_rb":         n_cost_null_rb,
        "n_costo_log_null_lp":         n_cost_null_lp,
        "computed_at":                 now,
    }])

    print("\n[diff] === GLOBAL ===")
    print(global_df.transpose(include_header=True, header_name="metric", column_names=["value"]))

    # ── Per-cluster: pivot por cluster_id_rb ──────────────────────────────────
    arche = pl.DataFrame({
        "cluster_id_rb":  list(ARCHETYPE_NAMES.keys()),
        "archetype_name": list(ARCHETYPE_NAMES.values()),
    }).with_columns(pl.col("cluster_id_rb").cast(joined.schema["cluster_id_rb"]))

    by_cluster = (
        joined
        .group_by("cluster_id_rb")
        .agg([
            pl.len().alias("n_orders"),
            pl.col("cluster_changed").sum().alias("n_reassigned_to_other_cluster"),
            (
                (pl.col("reassigned") & ~pl.col("cluster_changed"))
                .sum()
            ).alias("n_reassigned_to_same_cluster_diff_provider"),
            pl.col("score_delta").mean().alias("mean_score_delta"),
            pl.col("cost_delta").mean().alias("mean_cost_delta"),
        ])
        .with_columns(
            (pl.col("n_reassigned_to_other_cluster") / pl.col("n_orders"))
            .alias("pct_reassigned_to_other_cluster"),
            pl.lit(now).alias("computed_at"),
        )
        .join(arche, on="cluster_id_rb", how="left")
        .rename({"cluster_id_rb": "cluster_id"})
        .select([
            "cluster_id", "archetype_name", "n_orders",
            "n_reassigned_to_other_cluster", "pct_reassigned_to_other_cluster",
            "n_reassigned_to_same_cluster_diff_provider",
            "mean_score_delta", "mean_cost_delta",
            "computed_at",
        ])
        .sort("cluster_id")
    )

    print("\n[diff] === BY CLUSTER ===")
    print(by_cluster)

    # ── Smoking gun: cluster 3 debe tener cross-cluster = 0 ──────────────────
    c3 = by_cluster.filter(pl.col("cluster_id") == 3)
    if c3.height > 0:
        cross = int(c3["n_reassigned_to_other_cluster"][0])
        if cross != 0:
            print(f"[diff] NOTA: cluster 3 (LIVIANA) tiene cross-cluster={cross}. "
                  f"Esperábamos 0 — verificar si la regla LIVIANA→cluster_id=3 cambió.")
        else:
            print(f"[diff] ✓ cluster 3 (LIVIANA) cross-cluster=0 — gate LIVIANA confirmado")

    # ── Persistir ────────────────────────────────────────────────────────────
    global_df.write_parquet(KPI_SCENARIO_DIFF_PARQUET)
    print(f"[diff] escrito → {KPI_SCENARIO_DIFF_PARQUET}")
    by_cluster.write_parquet(KPI_SCENARIO_DIFF_BY_CLUSTER_PARQUET)
    print(f"[diff] escrito → {KPI_SCENARIO_DIFF_BY_CLUSTER_PARQUET}")

    _refresh_bq(BQ_TABLE_KPI_SCENARIO_DIFF,            KPI_SCENARIO_DIFF_PARQUET)
    _refresh_bq(BQ_TABLE_KPI_SCENARIO_DIFF_BY_CLUSTER, KPI_SCENARIO_DIFF_BY_CLUSTER_PARQUET)

    print(f"\n[diff] done in {time.perf_counter() - t0:.1f}s")
    return global_df, by_cluster


if __name__ == "__main__":
    run()
