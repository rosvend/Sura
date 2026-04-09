"""Gold layer — tabla maestra de features por prestador.

Une el perfil técnico declarado (feat_prestador_perfil) con el desempeño
operativo real (feat_prestador_performance) en una sola tabla por DNI_PRESTADOR.

Esta tabla es el insumo directo de clustering_input.py, que normaliza y
codifica las features para el modelo de clústeres.

Uso:
    from src.gold.feat_prestador import build_prestador_features
    df = build_prestador_features().collect()
"""

import polars as pl

from src.gold.feat_prestador_performance import build_performance_features
from src.gold.feat_prestador_perfil import build_perfil_features


def build_prestador_features() -> pl.LazyFrame:
    """Tabla Gold maestra por DNI_PRESTADOR.

    Estrategia de join: left join desde el perfil (catálogo) hacia el
    desempeño (citas 2025). El catálogo es la fuente de verdad de qué
    prestadores existen. Los que no tuvieron citas en 2025 aparecen con
    métricas de performance en null y quedan marcados con FLAG_SIN_ACTIVIDAD_2025.

    Columna clave derivada
    ──────────────────────
    utilizacion_capacidad   duracion_total_ejecutada / capacidad
                            Proporción de la capacidad declarada que se usó
                            efectivamente en 2025. null si capacidad == 0 o
                            sin actividad. Objetivo: entre 0.70 y 0.90
                            (ver DIAGNOSTICO_ANALISIS.md §5.4).
    FLAG_SIN_ACTIVIDAD_2025 True si el prestador no tiene citas de campo en 2025.
                            Cubre dos casos: (a) nunca apareció en Tareas_Programadas
                            (n_citas_total null) y (b) apareció solo con registros
                            INFORME, sin ninguna visita presencial (n_citas_total == 0).
                            Permite excluirlos del clustering o tratarlos como grupo separado.
    """
    perfil = build_perfil_features()
    performance = build_performance_features()

    return (
        perfil
        .join(performance, on="DNI_PRESTADOR", how="left")
        # ── Ratio de cobertura real ──────────────────────────────────────────
        # Municipios realmente atendidos en 2025 / municipios habilitados en
        # catálogo. Captura qué fracción del alcance geográfico declarado se
        # utilizó. null cuando n_municipios_cobertura == 0 (sin catálogo) o
        # cuando n_municipios_destino es null (sin actividad).
        .with_columns(
            pl.when(pl.col("n_municipios_cobertura") > 0)
            .then(pl.col("n_municipios_destino") / pl.col("n_municipios_cobertura"))
            .otherwise(None)
            .alias("ratio_cobertura_real")
        )
        # ── Utilización de capacidad ─────────────────────────────────────────
        # Horas ejecutadas reales (2025) sobre horas declaradas disponibles.
        # Se excluye el caso capacidad==0 (sin_capacidad=True) porque
        # la división generaría inf o NaN sin significado operativo.
        .with_columns(
            pl.when(
                (pl.col("capacidad") > 0)
                & pl.col("duracion_total_ejecutada").is_not_null()
            )
            .then(pl.col("duracion_total_ejecutada") / pl.col("capacidad"))
            .otherwise(None)
            .alias("utilizacion_capacidad")
        )
        # ── Flag de actividad ────────────────────────────────────────────────
        # null → prestador sin fila en Tareas_Programadas (nunca apareció).
        # 0   → prestador con programaciones pero todas de tipo INFORME (cero
        #       visitas de campo). Ambos casos quedan excluidos del clustering.
        # Verificado: 318 prestadores tienen n_citas_total == 0 en los datos.
        .with_columns(
            (pl.col("n_citas_total").is_null() | (pl.col("n_citas_total") == 0))
            .alias("FLAG_SIN_ACTIVIDAD_2025")
        )
        # ── Orden de columnas: identificación → perfil → desempeño → flags ──
        .select([
            # Identificación
            "DNI_PRESTADOR",
            "nombre_prestador",
            "dni_distribuidor",
            "nombre_distribuidor",

            # Perfil técnico (catálogo)
            "tipo_perfil",
            "perfil_tarifa",
            "funcion_prestador",
            "clasificacion_predominante",
            "n_habilitaciones",
            "n_tareas_distintas",
            "n_bloques_distintos",
            "n_productos_distintos",
            "bloque_principal",
            "cdbloque_principal",
            "n_tareas_bloque_principal",
            "indice_especializacion",

            # Red y geografía (catálogo)
            "tipo_red",
            "es_red_estrategica",
            "cdoficina",
            "dsoficina",
            "n_redes",
            "cdmunicipio_base",
            "municipio_base",
            "n_municipios_cobertura",

            # Capacidad (catálogo)
            "capacidad",
            "sin_capacidad",
            "antiguedad_dias",
            "fealta_prestador",

            # Desempeño operativo (citas CAMPO 2025)
            "n_programaciones_total",
            "n_citas_total",
            "pct_programaciones_campo",
            "n_citas_ejecutadas",
            "n_citas_canceladas",
            "n_cancela_empresa",
            "n_cancela_prestador",
            "tasa_ejecucion",
            "tasa_cancelacion",
            "tasa_cancela_empresa",
            "tasa_cancela_prestador",
            "duracion_promedio_ejecutada",
            "duracion_total_ejecutada",
            "n_duracion_nula_ejecutadas",
            "n_empresas_atendidas",
            "n_tareas_distintas_ejecutadas",
            "n_municipios_destino",

            # Informes (citas 2025)
            "n_informes_enviados",
            "n_informes_aprobados",
            "n_aprobados_auto",
            "tasa_aprobacion_informe",
            "tasa_aprobacion_auto",
            "dias_ciclo_informe_prom",

            # Órdenes históricas
            "n_lineas_oc",
            "n_oc_historicas",
            "n_ordenes_distintas_prog",
            "costo_logistico_prom",
            "costo_total_tarea_prom",
            "fecha_primera_oc",
            "fecha_ultima_oc",

            # Derivadas
            "utilizacion_capacidad",
            "ratio_cobertura_real",

            # Flags
            "FLAG_SIN_ACTIVIDAD_2025",
        ])
    )
