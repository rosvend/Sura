"""Índice de Saturación del Clúster (ISC) — KPI post-hoc por cluster.

Calcula, sobre los outputs YA materializados del motor de asignación, el
nivel de presión operativa de cada cluster:

    ISC = tareas_asignadas / capacidad_estimada
    capacidad_estimada = n_providers(cluster) * median(capacidad)(cluster)

Estado semáforo:
    ISC ≤ 0.85       → "Normal (Verde)"
    0.85 < ISC ≤ 1.0 → "Alerta (Amarillo)"
    ISC > 1.0        → "Crítico (Rojo)"

Diseño:
  * Lee `assignments.parquet` (rule_based) y, si existe, `assignments_lp.parquet`
    (lp_optimized). Mismo gating que src/monitoring/kpis.py.
  * NO toca exporter.py / optimizer.py / score.py / kpis.py. Es estrictamente
    post-hoc: una nueva tabla independiente del esquema existente de
    `kpis_summary`. Power BI puede leerla sin tocar bindings ya conectados.
  * `capacidad` por prestador viene de feat_prestador (sin_capacidad excluido).
    Mediana intra-cluster — se autocalibra al arquetipo. Sin constantes mágicas.

Persistencia:
    gs://sura-clustering-raw/data/processed/kpi_saturacion_cluster.parquet
    sura_clustering_processed.kpi_saturacion_cluster

Uso:
    PYTHONPATH=. uv run python scripts/compute_isc.py
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone

import polars as pl

from src.config import (
    ASSIGNMENTS_PARQUET,
    BQ_PROJECT,
    BQ_TABLE_KPI_SATURACION_CLUSTER,
    CLUSTERS_PARQUET,
    GCS_BUCKET,
    GOLD_PARQUETS,
    KPI_SATURACION_CLUSTER_PARQUET,
)
from src.gold.cluster_profiles import ARCHETYPE_NAMES

ASSIGNMENTS_LP_PARQUET = f"{GCS_BUCKET}/data/processed/assignments_lp.parquet"

# Umbrales semáforo. Explícitos a nivel de módulo para que Power BI / el reporte
# puedan referenciarlos por nombre en lugar de re-derivarlos.
THRESHOLDS = {"verde": 0.85, "amarillo": 1.0}


def _has_lp_parquet() -> bool:
    try:
        import gcsfs
        return gcsfs.GCSFileSystem().exists(ASSIGNMENTS_LP_PARQUET)
    except Exception:
        return False


def _load_capacity_per_cluster() -> pl.DataFrame:
    """Capacidad estimada por cluster.

    Une feat_prestador (capacidad por DNI) con prestador_clusters (cluster_id
    por DNI), filtra prestadores con sin_capacidad=True, y agrega:
        n_providers        — # prestadores activos en el cluster
        median_capacidad   — mediana de capacidad intra-cluster
        capacidad_estimada — n_providers * median_capacidad
    """
    fp = pl.read_parquet(GOLD_PARQUETS["feat_prestador"]).select([
        "DNI_PRESTADOR", "capacidad", "sin_capacidad",
    ])
    clusters = pl.read_parquet(CLUSTERS_PARQUET).select(["DNI_PRESTADOR", "cluster_id"])

    joined = (
        clusters
        .join(fp, on="DNI_PRESTADOR", how="inner")
        .filter(~pl.col("sin_capacidad").fill_null(True))
        .filter(pl.col("cluster_id") != -1)
    )

    cap = (
        joined
        .group_by("cluster_id")
        .agg([
            pl.len().alias("n_providers"),
            pl.col("capacidad").median().alias("median_capacidad"),
        ])
        .with_columns(
            (pl.col("n_providers") * pl.col("median_capacidad")).alias("capacidad_estimada"),
            pl.col("cluster_id").cast(pl.Int32),
        )
    )

    bad = cap.filter(
        pl.col("capacidad_estimada").is_null()
        | (pl.col("capacidad_estimada") <= 0)
    )
    if bad.height > 0:
        raise SystemExit(
            f"[isc] ABORT: capacidad_estimada inválida en clusters {bad['cluster_id'].to_list()}. "
            f"Revisa feat_prestador.capacidad / sin_capacidad antes de publicar."
        )
    return cap


def _load_load_per_cluster(assignments_parquet: str, scenario: str) -> pl.DataFrame:
    """Carga asignada por cluster en un escenario.

    Lee el parquet de asignaciones (top-1) y cuenta filas por cluster.
    No depende de columnas como `scenario` en el parquet — la etiqueta del
    escenario la inyectamos aquí, así que la función es robusta tanto al
    output crudo de exporter.py como al de optimizer.py.
    """
    df = pl.read_parquet(assignments_parquet).select(["cluster_id"])
    total = df.height

    load = (
        df
        .filter(pl.col("cluster_id").is_not_null() & (pl.col("cluster_id") != -1))
        .group_by("cluster_id")
        .agg(pl.len().alias("tareas_asignadas"))
        .with_columns(
            pl.col("cluster_id").cast(pl.Int32),
            pl.lit(scenario).alias("scenario"),
        )
    )

    # Conservación: lo agregado debe igualar la cantidad de filas no-nulas
    # (excluyendo cluster -1, que el exporter ya filtra fuera). Falla ruidosa
    # si algún día el exporter empieza a emitir cluster=-1 sin avisar.
    summed = int(load["tareas_asignadas"].sum())
    n_minus1 = int(df.filter(pl.col("cluster_id") == -1).height)
    n_null = int(df.filter(pl.col("cluster_id").is_null()).height)
    if summed + n_minus1 + n_null != total:
        raise SystemExit(
            f"[isc] ABORT: conservación rota en {scenario}: "
            f"sum(tareas)={summed} + cluster=-1({n_minus1}) + nulls({n_null}) "
            f"!= total({total})"
        )
    print(f"[isc] {scenario}: {summed:,} tareas asignadas en {load.height} clusters "
          f"(excluidos -1={n_minus1}, null={n_null})")
    return load


def _label_estado(isc_col: pl.Expr) -> pl.Expr:
    """Expresión vectorizada para estado_saturacion."""
    return (
        pl.when(isc_col <= THRESHOLDS["verde"]).then(pl.lit("Normal (Verde)"))
        .when(isc_col <= THRESHOLDS["amarillo"]).then(pl.lit("Alerta (Amarillo)"))
        .otherwise(pl.lit("Crítico (Rojo)"))
    )


def _archetype_df() -> pl.DataFrame:
    return pl.DataFrame({
        "cluster_id":     list(ARCHETYPE_NAMES.keys()),
        "archetype_name": list(ARCHETYPE_NAMES.values()),
    }).with_columns(pl.col("cluster_id").cast(pl.Int32))


def _refresh_bq(table: str, gs_uri: str) -> None:
    if not shutil.which("bq"):
        print(f"[isc] bq CLI no encontrado, omitiendo refresh de {table}")
        return
    cmd = [
        "bq", "load",
        "--replace",
        "--source_format=PARQUET",
        f"--project_id={BQ_PROJECT}",
        f"{BQ_PROJECT}:{table}",
        gs_uri,
    ]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[isc] BQ load FAILED for {table}:\n{res.stderr}")
        raise SystemExit(res.returncode)
    print(f"[isc] BQ {table} refreshed in {time.perf_counter() - t0:.1f}s")


def run() -> pl.DataFrame:
    t0 = time.perf_counter()

    cap = _load_capacity_per_cluster()
    print(f"[isc] capacity per cluster:\n{cap.sort('cluster_id')}")

    loads: list[pl.DataFrame] = [_load_load_per_cluster(ASSIGNMENTS_PARQUET, "rule_based")]
    if _has_lp_parquet():
        loads.append(_load_load_per_cluster(ASSIGNMENTS_LP_PARQUET, "lp_optimized"))
    else:
        print("[isc] (assignments_lp.parquet ausente — solo rule_based)")

    load_all = pl.concat(loads)

    arche = _archetype_df()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    out = (
        load_all
        .join(cap, on="cluster_id", how="left")
        .join(arche, on="cluster_id", how="left")
        .with_columns(
            (pl.col("tareas_asignadas") / pl.col("capacidad_estimada")).alias("isc"),
            pl.col("archetype_name").fill_null("Sin nombre"),
            pl.lit(now).alias("computed_at"),
        )
        .with_columns(_label_estado(pl.col("isc")).alias("estado_saturacion"))
        .select([
            "cluster_id", "archetype_name", "scenario",
            "n_providers", "median_capacidad", "capacidad_estimada",
            "tareas_asignadas", "isc", "estado_saturacion",
            "computed_at",
        ])
        .sort(["scenario", "cluster_id"])
    )

    # Validación final pre-publicación.
    if out["capacidad_estimada"].is_null().any() or (out["capacidad_estimada"] <= 0).any():
        raise SystemExit("[isc] ABORT: capacidad_estimada con NaN o <=0 en el output final.")
    if out["isc"].is_null().any():
        raise SystemExit("[isc] ABORT: ISC con NaN en el output final.")

    print("\n[isc] salida:")
    print(out)
    print("\n[isc] distribución de estado_saturacion:")
    print(out.group_by(["scenario", "estado_saturacion"]).agg(pl.len()).sort(["scenario", "estado_saturacion"]))

    out.write_parquet(KPI_SATURACION_CLUSTER_PARQUET)
    print(f"[isc] escrito → {KPI_SATURACION_CLUSTER_PARQUET}")
    _refresh_bq(BQ_TABLE_KPI_SATURACION_CLUSTER, KPI_SATURACION_CLUSTER_PARQUET)
    print(f"\n[isc] done in {time.perf_counter() - t0:.1f}s")
    return out


if __name__ == "__main__":
    run()
