"""Gold layer — features de desempeño operativo por prestador.

Computa KPIs por DNI_PRESTADOR a partir de dos fuentes Silver:
  - Tareas_Programadas_canceladas_2025: ejecución real de citas en 2025
  - Ordenado: historial completo de órdenes de compra

Estas métricas capturan el *perfil operativo real* del asesor —
lo que realmente hace y con qué calidad — en contraste con el perfil
declarado en el catálogo (feat_prestador_perfil.py).

Uso:
    from src.gold.feat_prestador_performance import build_performance_features
    df = build_performance_features().collect()
"""

import polars as pl

from src.silver.extract import load_empresas, load_ordenado, load_tareas_programadas

# ── Constantes de dominio ────────────────────────────────────────────────────
# Estados de DSESTADO_PROGRAMACION verificados contra el dataset (7 valores)

# Citas que representan entrega efectiva del servicio (total o parcial)
_ESTADOS_EJECUTADA = frozenset([
    "CITA EJECUTADA",
    "PARCIALMENTE EJECUTADO",
    "PARCIALMENTE COMPLETADO",
])

_ESTADO_CANCELADA = "CITA CANCELADA"

# Estado del informe tras normalización Silver ("AP" → "APROBADO", etc.)
_ESTADO_INFORME_APROBADO = "APROBADO"

# Segmentaciones ARL que corresponden a empresas de alta complejidad.
# Confirmado en DESCRIPCION_DATOS.md. Determina pct_empresa_compleja.
_SEGMENTOS_COMPLEJOS = frozenset(["Gran Empresa", "Mediana Empresa"])


# ── Bloques internos ─────────────────────────────────────────────────────────

def _kpis_programaciones() -> pl.LazyFrame:
    """KPIs por prestador a partir de Tareas_Programadas_canceladas_2025.

    TIPO_PROGRAMACION tiene dos valores: 'CAMPO' (visitas de servicio presencial,
    1.18M filas) e 'INFORME' (envíos de documentos administrativos, 362K filas).
    Las métricas de ejecución, cancelación y duración se calculan sobre CAMPO
    únicamente para medir calidad de servicio real. Incluir INFORME inflaría
    n_citas_total ~24% y distorsionaría todas las tasas derivadas.

    Las métricas de informes (n_informes_enviados, etc.) se mantienen sobre
    todos los registros porque FEENVIO_INFORME puede estar poblado en cualquier
    tipo de programación.

    Métricas calculadas:
    - Mix: n_programaciones_total (todos), n_citas_total y tasas (solo CAMPO)
    - Volumen CAMPO: órdenes, empresas y municipios distintos
    - Ejecución CAMPO: ejecutadas, canceladas, canceladas por empresa
    - Duración CAMPO: promedio y total de horas ejecutadas; diagnóstico de nulos
    - Informes (todos): enviados, aprobados, auto-aprobados, ciclo en días
    """
    tp = (
        load_tareas_programadas()
        .with_columns(
            (pl.col("FEAPROBACION_INFORME") - pl.col("FEENVIO_INFORME"))
            .dt.total_days()
            .alias("_dias_ciclo")
        )
    )

    return (
        tp.group_by("DNI_PRESTADOR")
        .agg([
            # ── Mix de programaciones ─────────────────────────────────────────
            # n_programaciones_total: todos los registros (CAMPO + INFORME).
            # n_citas_total: solo CAMPO; es el denominador de todas las tasas.
            pl.len().alias("n_programaciones_total"),
            (pl.col("TIPO_PROGRAMACION") == "CAMPO").sum().alias("n_citas_total"),

            # ── Volumen de servicio (CAMPO) ───────────────────────────────────
            pl.col("NMCONSECUTIVO_ORDEN")
            .filter(pl.col("TIPO_PROGRAMACION") == "CAMPO")
            .n_unique().alias("n_ordenes_distintas_prog"),

            pl.col("DNI_EMPRESA")
            .filter(pl.col("TIPO_PROGRAMACION") == "CAMPO")
            .n_unique().alias("n_empresas_atendidas"),

            pl.col("CDTAREA")
            .filter(pl.col("TIPO_PROGRAMACION") == "CAMPO")
            .n_unique().alias("n_tareas_distintas_ejecutadas"),

            pl.col("DS_MUNICIPIO_DESTINO")
            .filter(pl.col("TIPO_PROGRAMACION") == "CAMPO")
            .n_unique().alias("n_municipios_destino"),

            # ── Ejecución (CAMPO) ─────────────────────────────────────────────
            (
                pl.col("DSESTADO_PROGRAMACION").is_in(list(_ESTADOS_EJECUTADA))
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            ).sum().alias("n_citas_ejecutadas"),

            (
                (pl.col("DSESTADO_PROGRAMACION") == _ESTADO_CANCELADA)
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            ).sum().alias("n_citas_canceladas"),

            # ── Cancelación por empresa (CAMPO) ───────────────────────────────
            # SNCANCELA_EMPRESA es Boolean tras Silver; True = la empresa canceló.
            (
                pl.col("SNCANCELA_EMPRESA")
                & (pl.col("DSESTADO_PROGRAMACION") == _ESTADO_CANCELADA)
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            ).sum().alias("n_cancela_empresa"),

            # ── Cancelaciones sin motivo documentado — proxy de timeout (CAMPO) ──
            # SURA confirmó (Q&A 2026-04-11) que el 79,3% de las cancelaciones
            # por "causas del sistema" se deben a la política de timeout automático:
            # OC sin gestión durante 2 meses → el sistema las cancela sin registrar
            # motivo explícito. Este conteo aísla ese ruido de la métrica de fallo
            # real del prestador. Invariante: n_cancela_sin_motivo ≤ n_cancela_prestador.
            (
                (~pl.col("SNCANCELA_EMPRESA").fill_null(False))
                & (pl.col("DSESTADO_PROGRAMACION") == _ESTADO_CANCELADA)
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
                & pl.col("MOTIVO_CANCELACION").is_null()
            ).sum().alias("n_cancela_sin_motivo"),

            # ── Duración (CAMPO ejecutadas) ───────────────────────────────────
            # DURACION tiene ~41% de nulos en el dataset completo. Los nulos se
            # excluyen silenciosamente del mean/sum, lo que subestima las horas
            # reales y por ende utilizacion_capacidad. n_duracion_nula_ejecutadas
            # permite medir la severidad del sesgo por prestador.
            pl.col("DURACION")
            .filter(
                pl.col("DSESTADO_PROGRAMACION").is_in(list(_ESTADOS_EJECUTADA))
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            ).mean().alias("duracion_promedio_ejecutada"),

            pl.col("DURACION")
            .filter(
                pl.col("DSESTADO_PROGRAMACION").is_in(list(_ESTADOS_EJECUTADA))
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            ).sum().alias("duracion_total_ejecutada"),

            pl.col("DURACION")
            .filter(
                pl.col("DSESTADO_PROGRAMACION").is_in(list(_ESTADOS_EJECUTADA))
                & (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            ).is_null().sum().alias("n_duracion_nula_ejecutadas"),

            # ── Informes (todos los tipos de programación) ────────────────────
            pl.col("FEENVIO_INFORME").is_not_null().sum().alias("n_informes_enviados"),

            (pl.col("DSESTADO_INFORME") == _ESTADO_INFORME_APROBADO)
            .sum().alias("n_informes_aprobados"),

            # SNAPROBADO_AUTOMATICO es Boolean; True = aprobado sin revisión manual
            pl.col("SNAPROBADO_AUTOMATICO").sum().alias("n_aprobados_auto"),

            # Ciclo negativo indica inconsistencia de fechas en la fuente
            pl.col("_dias_ciclo")
            .filter(pl.col("_dias_ciclo") >= 0)
            .mean().alias("dias_ciclo_informe_prom"),
        ])
        # pct_programaciones_campo: fracción de programaciones que son visitas
        # de servicio presencial. Captura el mix de trabajo de campo vs.
        # administrativo de cada prestador.
        .with_columns(
            pl.when(pl.col("n_programaciones_total") > 0)
            .then(pl.col("n_citas_total") / pl.col("n_programaciones_total"))
            .otherwise(None)
            .alias("pct_programaciones_campo")
        )
    )


def _kpis_ordenado() -> pl.LazyFrame:
    """KPIs por prestador a partir del historial de Órdenes de compra.

    Métricas calculadas:
    - Volumen de OC: líneas totales y órdenes únicas
    - Costos: costo logístico promedio (transporte + viáticos) y costo total
    - Antigüedad: fecha de primera y última OC
    """
    return (
        load_ordenado()
        .group_by("Dni_Prestador")
        .agg([
            pl.col("Ord_Plan_Vers_Act_Id").count().alias("n_lineas_oc"),
            pl.col("Numero_Consecutivo_Orden").n_unique().alias("n_oc_historicas"),

            # Costo logístico = transporte + viáticos. fill_null(0) porque
            # algunos registros no tienen transporte o viáticos (servicio local).
            (
                pl.col("Valor_Costo_Transporte").fill_null(0.0)
                + pl.col("Valor_Costo_Viaticos").fill_null(0.0)
            )
            .mean()
            .alias("costo_logistico_prom"),

            pl.col("Valor_Costo_Total_Tarea").mean().alias("costo_total_tarea_prom"),

            pl.col("Fecha_Creacion_Orden").min().alias("fecha_primera_oc"),
            pl.col("Fecha_Creacion_Orden").max().alias("fecha_ultima_oc"),
        ])
        .rename({"Dni_Prestador": "DNI_PRESTADOR"})
    )


def _demanda_atendida() -> pl.LazyFrame:
    """Perfil de la demanda empresarial realmente atendida por cada prestador en 2025.

    Fuente: Tareas_Programadas (citas CAMPO ejecutadas) ← Detalle_Empresa (perfil empresa).
    Llave de join: DNI_EMPRESA → Empresa_Id (misma entidad, confirmado en ER_DIAGRAMA.md).

    Solo se consideran citas CAMPO ejecutadas: captura el perfil de a quién sirve
    realmente el prestador, no a quién tiene programado. Esto es el puente entre la
    oferta técnica declarada (catálogo) y la demanda real atendida, factor clave para
    el matching empresa ↔ prestador (prioridad #1 confirmada en Q&A 2026-04-11).

    Columnas de salida
    ──────────────────
    sector_principal_atendido    Sector económico predominante de los clientes atendidos.
                                 Contexto para clustering; no entra a FEATURE_COLS directamente.
    segmento_principal_atendido  Segmentación ARL predominante (Gran Empresa, Mediana, Micro...).
                                 Contexto para clustering; no entra a FEATURE_COLS directamente.
    pct_empresa_compleja         Fracción de citas ejecutadas para Gran Empresa o Mediana Empresa.
                                 Feature directamente usable: captura si el prestador atiende
                                 clientes de alta complejidad (Avanzado/Especializado) o clientes
                                 simples (Micro, Independiente, Liviana).
    """
    tp_campo_exec = (
        load_tareas_programadas()
        .filter(
            (pl.col("TIPO_PROGRAMACION") == "CAMPO")
            & pl.col("DSESTADO_PROGRAMACION").is_in(list(_ESTADOS_EJECUTADA))
        )
        .select(["DNI_PRESTADOR", "DNI_EMPRESA"])
    )

    empresas = (
        load_empresas()
        .select(["Empresa_Id", "Sector_Economico_Desc", "Segmentacion_Arl_Desc"])
    )

    joined = tp_campo_exec.join(
        empresas, left_on="DNI_EMPRESA", right_on="Empresa_Id", how="left"
    )

    # Sector predominante: patrón sort-and-take (equivalente a moda)
    sector_top = (
        joined
        .group_by(["DNI_PRESTADOR", "Sector_Economico_Desc"])
        .agg(pl.len().alias("_cnt"))
        .sort("_cnt", descending=True)
        .group_by("DNI_PRESTADOR")
        .agg(pl.col("Sector_Economico_Desc").first().alias("sector_principal_atendido"))
    )

    # Segmentación ARL predominante: mismo patrón
    segmento_top = (
        joined
        .group_by(["DNI_PRESTADOR", "Segmentacion_Arl_Desc"])
        .agg(pl.len().alias("_cnt"))
        .sort("_cnt", descending=True)
        .group_by("DNI_PRESTADOR")
        .agg(pl.col("Segmentacion_Arl_Desc").first().alias("segmento_principal_atendido"))
    )

    # KPI numérico: fracción de citas en empresas de alta complejidad
    kpis = (
        joined
        .group_by("DNI_PRESTADOR")
        .agg(
            pl.col("Segmentacion_Arl_Desc")
            .is_in(list(_SEGMENTOS_COMPLEJOS))
            .mean()
            .alias("pct_empresa_compleja"),
        )
    )

    return (
        sector_top
        .join(segmento_top, on="DNI_PRESTADOR", how="left")
        .join(kpis, on="DNI_PRESTADOR", how="left")
    )


# ── API pública ──────────────────────────────────────────────────────────────

def build_performance_features() -> pl.LazyFrame:
    """Tabla Gold de desempeño operativo por DNI_PRESTADOR.

    Combina KPIs de citas programadas 2025 con historial de órdenes y
    calcula tasas derivadas. Los cálculos de tasas usan pl.when para
    evitar divisiones por cero; el resultado es null cuando el denominador
    es 0 (prestador sin cancelaciones, sin informes, etc.).

    Nota sobre cobertura: esta tabla contiene solo prestadores con actividad
    en 2025 (presentes en Tareas_Programadas). Prestadores en el catálogo
    sin citas 2025 aparecerán con performance null cuando esta tabla se
    incorpore vía left join en feat_prestador.py.

    Columnas clave de salida
    ─────────────────────────
    tasa_ejecucion           citas ejecutadas (incl. parciales) / total citas
    tasa_cancelacion         citas canceladas / total citas
    tasa_cancela_empresa     cancelaciones por empresa / total canceladas
    tasa_aprobacion_informe  informes aprobados / informes enviados
    tasa_aprobacion_auto     aprobados automáticamente / total aprobados
    dias_ciclo_informe_prom  días promedio entre envío y aprobación
    duracion_promedio_ejecutada  horas promedio por cita ejecutada

    Metas de referencia (de DIAGNOSTICO_ANALISIS.md):
        tasa_ejecucion           > 0.90
        tasa_cancelacion_empresa < 0.10
        tasa_aprobacion_informe  > 0.92
        tasa_aprobacion_auto     > 0.60
        dias_ciclo_informe_prom  < 5 días hábiles
    """
    prog = _kpis_programaciones()
    oc = _kpis_ordenado()
    demanda = _demanda_atendida()

    return (
        prog
        .join(oc, on="DNI_PRESTADOR", how="left")
        .join(demanda, on="DNI_PRESTADOR", how="left")
        .with_columns([
            # Tasa de ejecución: citas con resultado / total asignadas
            pl.when(pl.col("n_citas_total") > 0)
            .then(pl.col("n_citas_ejecutadas") / pl.col("n_citas_total"))
            .otherwise(None)
            .alias("tasa_ejecucion"),

            # Tasa de cancelación total
            pl.when(pl.col("n_citas_total") > 0)
            .then(pl.col("n_citas_canceladas") / pl.col("n_citas_total"))
            .otherwise(None)
            .alias("tasa_cancelacion"),

            # Fracción de citas donde la empresa canceló, sobre el total CAMPO.
            # Mismo denominador que tasa_cancelacion y tasa_cancela_prestador,
            # garantizando la propiedad aditiva:
            #   tasa_cancela_empresa + tasa_cancela_prestador = tasa_cancelacion
            pl.when(pl.col("n_citas_total") > 0)
            .then(pl.col("n_cancela_empresa") / pl.col("n_citas_total"))
            .otherwise(None)
            .alias("tasa_cancela_empresa"),

            # Tasa de aprobación de informes (calidad documental)
            pl.when(pl.col("n_informes_enviados") > 0)
            .then(pl.col("n_informes_aprobados") / pl.col("n_informes_enviados"))
            .otherwise(None)
            .alias("tasa_aprobacion_informe"),

            # Qué proporción de aprobaciones no requirió revisión manual
            pl.when(pl.col("n_informes_aprobados") > 0)
            .then(pl.col("n_aprobados_auto") / pl.col("n_informes_aprobados"))
            .otherwise(None)
            .alias("tasa_aprobacion_auto"),

            # Cancelaciones atribuibles al prestador (no a la empresa)
            (pl.col("n_citas_canceladas") - pl.col("n_cancela_empresa"))
            .alias("n_cancela_prestador"),
        ])
        # n_cancela_real_prestador: cancellaciones con motivo documentado.
        # Excluye n_cancela_sin_motivo (proxy de timeouts del sistema, Q8).
        # Se calcula en paso separado para poder reusar n_cancela_prestador.
        .with_columns([
            pl.when(pl.col("n_citas_total") > 0)
            .then(pl.col("n_cancela_prestador") / pl.col("n_citas_total"))
            .otherwise(None)
            .alias("tasa_cancela_prestador"),

            (pl.col("n_cancela_prestador") - pl.col("n_cancela_sin_motivo"))
            .clip(lower_bound=0)
            .alias("n_cancela_real_prestador"),
        ])
        # tasa_cancela_real_prestador: requiere n_cancela_real_prestador del paso anterior.
        # Señal más limpia que tasa_cancela_prestador para el modelo de clustering:
        # excluye el ruido de las cancelaciones automáticas por política de timeout.
        .with_columns(
            pl.when(pl.col("n_citas_total") > 0)
            .then(pl.col("n_cancela_real_prestador") / pl.col("n_citas_total"))
            .otherwise(None)
            .alias("tasa_cancela_real_prestador")
        )
    )
