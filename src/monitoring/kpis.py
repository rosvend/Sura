"""Simulación de impacto: KPIs del motor de asignación vs. status quo (Día 4).

Hace replay de las 2025-orders en Ordenado. Para cada orden histórica
(dni_empresa, codigo_tarea, cd_municipio_destino) compara:
    - el prestador asignado realmente (Ordenado.Dni_Prestador)
    - el prestador top-1 recomendado por nuestro modelo (assignments parquet)

KPIs:
    K1. Tasa esperada de cancelación (real, sin ruido de timeout)
        Mide la tasa_cancela_real_prestador del prestador asignado, ponderada
        por número de órdenes. Target: -15 % relativo (modelo < baseline).
    K2. Gini de carga
        Inequalidad de horas asignadas a través de la red. Target: -10 % rel.
    K3. Costo logístico esperado
        Costo logístico promedio del prestador asignado (transporte + viáticos
        observados en su historial). Target: -5 % relativo.
    K4. Tasa de match geográfico
        % de órdenes donde el municipio base del prestador asignado coincide
        con el municipio de entrega. Target: +10 puntos porcentuales.

Persistencia:
    gs://sura-clustering-raw/data/processed/kpis_summary.parquet
    sura_clustering_processed.kpis_summary

Uso:
    PYTHONPATH=. uv run python -m src.monitoring.kpis
"""

from __future__ import annotations

import shutil
import subprocess
import time

import numpy as np
import polars as pl

from src.config import (
    ASSIGNMENTS_PARQUET,
    BQ_PROJECT,
    BQ_TABLE_KPIS_SUMMARY,
    GOLD_PARQUETS,
    KPIS_SUMMARY_PARQUET,
)
from src.silver.extract import load_ordenado

# ── Targets (DIAGNOSTICO §5.4) ────────────────────────────────────────────────
KPI_TARGETS: dict[str, dict] = {
    "K1_tasa_cancelacion_esperada": {"direction": "lower", "target_rel": -0.15},
    "K2_gini_carga":                {"direction": "lower", "target_rel": -0.10},
    "K3_costo_logistico_esperado":  {"direction": "lower", "target_rel": -0.05},
    "K4_match_geografico":          {"direction": "higher", "target_abs": 0.10},
}


def _gini(values: np.ndarray) -> float:
    """Coeficiente de Gini sobre un vector no-negativo (0 = igualdad, 1 = max desigualdad)."""
    if values.size == 0:
        return float("nan")
    v = np.sort(values.astype(float))
    v = np.maximum(v, 0.0)
    n = v.size
    cum = v.sum()
    if cum == 0:
        return 0.0
    return float((2 * np.arange(1, n + 1) * v).sum() / (n * cum) - (n + 1) / n)


def _load_replay_table() -> pl.DataFrame:
    """Une cada orden histórica con la recomendación del modelo + features
    del prestador histórico y del recomendado.
    """
    # Historical: una fila por orden cruda en Ordenado.
    hist = (
        load_ordenado()
        .select([
            "Dni_Empresa", "Codigo_Tarea", "Municipio_Entrega_Id",
            "Dni_Prestador",
            "Valor_Costo_Transporte", "Valor_Costo_Viaticos",
            "Numero_Cantidad_Pedida",
        ])
        .drop_nulls(["Dni_Empresa", "Codigo_Tarea", "Municipio_Entrega_Id", "Dni_Prestador"])
        .collect()
    )
    # Normalizar muni
    hist = hist.with_columns(
        pl.when(pl.col("Municipio_Entrega_Id").str.ends_with(".0"))
        .then(pl.col("Municipio_Entrega_Id").str.slice(0, pl.col("Municipio_Entrega_Id").str.len_chars() - 2))
        .otherwise(pl.col("Municipio_Entrega_Id"))
        .alias("cd_municipio_destino")
    ).rename({
        "Dni_Empresa":   "dni_empresa",
        "Codigo_Tarea":  "codigo_tarea",
        "Dni_Prestador": "dni_prestador_hist",
    }).drop("Municipio_Entrega_Id")

    asg = (
        pl.read_parquet(ASSIGNMENTS_PARQUET)
        .select([
            "dni_empresa", "codigo_tarea", "cd_municipio_destino",
            pl.col("dni_prestador").alias("dni_prestador_model"),
            pl.col("cluster_id").alias("cluster_id_model"),
            pl.col("archetype_name").alias("archetype_model"),
            pl.col("utilizacion_capacidad").alias("util_model"),
        ])
    )
    replay = hist.join(asg, on=["dni_empresa", "codigo_tarea", "cd_municipio_destino"], how="inner")

    # Anotar atributos por prestador (histórico y recomendado).
    fp = pl.read_parquet(GOLD_PARQUETS["feat_prestador"]).select([
        "DNI_PRESTADOR", "cdmunicipio_base",
        "tasa_cancela_real_prestador", "costo_logistico_prom",
        "duracion_promedio_ejecutada",
    ])

    replay = (
        replay
        .join(fp.rename({
            "DNI_PRESTADOR":              "dni_prestador_hist",
            "cdmunicipio_base":           "muni_base_hist",
            "tasa_cancela_real_prestador":"tasa_cancela_hist",
            "costo_logistico_prom":       "costo_log_hist",
            "duracion_promedio_ejecutada":"duracion_hist",
        }), on="dni_prestador_hist", how="left")
        .join(fp.rename({
            "DNI_PRESTADOR":              "dni_prestador_model",
            "cdmunicipio_base":           "muni_base_model",
            "tasa_cancela_real_prestador":"tasa_cancela_model",
            "costo_logistico_prom":       "costo_log_model",
            "duracion_promedio_ejecutada":"duracion_model",
        }), on="dni_prestador_model", how="left")
    )
    return replay


def compute_kpis(replay: pl.DataFrame) -> pl.DataFrame:
    n = replay.height
    print(f"[kpis] replay rows: {n:,}")

    # ── K1: Tasa esperada de cancelación ─────────────────────────────────────
    k1_base = float(replay["tasa_cancela_hist"].drop_nulls().mean() or 0.0)
    k1_mod  = float(replay["tasa_cancela_model"].drop_nulls().mean() or 0.0)

    # ── K2: Gini de carga ─────────────────────────────────────────────────────
    # Baseline: carga histórica = #órdenes asignadas a cada DNI_PRESTADOR.
    hist_load = (
        replay.group_by("dni_prestador_hist").len().rename({"len": "n"})
        .filter(pl.col("dni_prestador_hist").is_not_null())
    )
    model_load = (
        replay.group_by("dni_prestador_model").len().rename({"len": "n"})
        .filter(pl.col("dni_prestador_model").is_not_null())
    )
    k2_base = _gini(hist_load["n"].to_numpy())
    k2_mod  = _gini(model_load["n"].to_numpy())

    # ── K3: Costo logístico esperado ─────────────────────────────────────────
    # Para cada orden, el costo logístico esperado es el costo_logistico_prom
    # del prestador asignado (histórico vs. recomendado). Si null, 0.
    k3_base = float(replay["costo_log_hist"].fill_null(0.0).mean())
    k3_mod  = float(replay["costo_log_model"].fill_null(0.0).mean())

    # ── K4: Match geográfico ──────────────────────────────────────────────────
    # % de órdenes donde muni_base del prestador == municipio de entrega.
    k4_base = float(
        (replay["muni_base_hist"]  == replay["cd_municipio_destino"]).fill_null(False).cast(pl.Float64).mean()
    )
    k4_mod  = float(
        (replay["muni_base_model"] == replay["cd_municipio_destino"]).fill_null(False).cast(pl.Float64).mean()
    )

    rows = [
        {"name": "K1_tasa_cancelacion_esperada", "baseline": k1_base, "model": k1_mod},
        {"name": "K2_gini_carga",                "baseline": k2_base, "model": k2_mod},
        {"name": "K3_costo_logistico_esperado",  "baseline": k3_base, "model": k3_mod},
        {"name": "K4_match_geografico",          "baseline": k4_base, "model": k4_mod},
    ]
    df = pl.DataFrame(rows).with_columns([
        (pl.col("model") - pl.col("baseline")).alias("delta_abs"),
        pl.when(pl.col("baseline").abs() > 1e-9)
        .then((pl.col("model") - pl.col("baseline")) / pl.col("baseline"))
        .otherwise(None)
        .alias("delta_rel"),
    ])

    # Status (PASS si la dirección y magnitud cumplen el target).
    def _status(row) -> str:
        spec = KPI_TARGETS[row["name"]]
        if spec["direction"] == "lower":
            return "PASS" if (row["delta_rel"] is not None and row["delta_rel"] <= spec["target_rel"]) else "FAIL"
        else:  # higher
            return "PASS" if row["delta_abs"] >= spec["target_abs"] else "FAIL"

    target_rows = []
    for r in df.iter_rows(named=True):
        spec = KPI_TARGETS[r["name"]]
        target_rows.append({
            "name": r["name"],
            "target": spec.get("target_rel", spec.get("target_abs")),
            "target_kind": "relative" if "target_rel" in spec else "absolute",
            "status": _status(r),
        })
    target_df = pl.DataFrame(target_rows)
    return df.join(target_df, on="name", how="left").with_columns(
        pl.lit("rule_based").alias("scenario"),
        pl.lit(n).alias("n_orders"),
    )


def _refresh_bq(table: str, gs_uri: str) -> None:
    if not shutil.which("bq"):
        print(f"[kpis] bq CLI no encontrado, omitiendo refresh de {table}")
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
        print(f"[kpis] BQ load FAILED for {table}:\n{res.stderr}")
        raise SystemExit(res.returncode)
    print(f"[kpis] BQ {table} refreshed in {time.perf_counter() - t0:.1f}s")


def run() -> pl.DataFrame:
    t0 = time.perf_counter()
    replay = _load_replay_table()
    kpis = compute_kpis(replay)
    print("\n[kpis] summary:")
    print(kpis)
    kpis.write_parquet(KPIS_SUMMARY_PARQUET)
    _refresh_bq(BQ_TABLE_KPIS_SUMMARY, KPIS_SUMMARY_PARQUET)
    print(f"\n[kpis] done in {time.perf_counter() - t0:.1f}s")
    return kpis


if __name__ == "__main__":
    run()
