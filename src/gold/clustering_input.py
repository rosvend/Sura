"""Gold layer — matriz de features para el modelo de clustering.

Toma feat_prestador (tabla maestra Gold) y produce una matriz lista para
sklearn.cluster.KMeans: un registro por prestador activo, todas las columnas
en Float64, sin nulos.

Esta capa NO normaliza (StandardScaler va en el notebook/modelo) para que
los valores originales sigan siendo legibles en BigQuery y útiles para
diagnósticos. El notebook aplica:
    from sklearn.preprocessing import StandardScaler
    X_scaled = StandardScaler().fit_transform(df[FEATURE_COLS])

Uso:
    from src.gold.clustering_input import build_clustering_input, FEATURE_COLS
    df = build_clustering_input().collect()
    # df[FEATURE_COLS] es la matriz de entrada para KMeans
"""

import polars as pl

from src.gold.feat_prestador import build_prestador_features

# ── Encoding ordinal de tipo_perfil ──────────────────────────────────────────
# Escala de seniority confirmada contra los valores reales del dataset.
# OTROS queda en null (nivel ambiguo); se imputa con la mediana en _imputar().
_TIPO_PERFIL_ORD: dict[str, int] = {
    "BASICO":       1,
    "TECNOLOGO":    2,
    "INTERMEDIO":   3,
    "PROFESIONAL":  4,
    "AVANZADO":     5,
    "EXPERTO":      6,
    "ESPECIALISTA": 7,
}

# ── Features que entran al modelo de clustering ──────────────────────────────
# Organizadas por dimensión (diagnóstico §5.1). Este listado es la referencia
# canónica para el notebook: sklearn recibe df[FEATURE_COLS].
FEATURE_COLS: list[str] = [
    # Dimensión técnica
    # n_productos_distintos eliminado: alta correlación con n_tareas_distintas y
    # n_bloques_distintos (las tres miden amplitud de catálogo). Conservar las tres
    # sobrepondera esta dimensión en K-Means (distancia euclidiana).
    "n_tareas_distintas",
    "n_bloques_distintos",
    "indice_especializacion",
    "tipo_perfil_ord",        # ordinal derivado de DSTIPO_PERFIL

    # Dimensión geográfica
    "n_municipios_cobertura",
    "n_municipios_destino",
    "ratio_cobertura_real",    # n_municipios_destino / n_municipios_cobertura

    # Dimensión de desempeño (perfil real 2025)
    "tasa_ejecucion",
    # tasa_cancela_real_prestador reemplaza tasa_cancela_prestador:
    # excluye cancelaciones por timeout del sistema (política de 2 meses confirmada en Q&A).
    # tasa_cancela_prestador incluía ~79,3% de ruido de política interna.
    "tasa_cancela_real_prestador",
    "tasa_aprobacion_informe",
    "tasa_aprobacion_auto",
    "dias_ciclo_informe_prom",
    "duracion_promedio_ejecutada",

    # Dimensión de carga
    "n_citas_total",
    "n_empresas_atendidas",
    "utilizacion_capacidad",
    "pct_programaciones_campo",  # fracción de programaciones que son visitas presenciales

    # Dimensión de match demanda (perfil de clientes realmente atendidos)
    # Captura si el prestador sirve clientes de alta complejidad (Gran/Mediana Empresa)
    # vs. clientes simples (Micro, Independiente). Prioridad #1 en Q&A: especialización.
    "pct_empresa_compleja",

    # Dimensión de costo logístico
    "costo_logistico_prom",

    # Dimensión de red y antigüedad
    "es_red_estrategica",     # binaria derivada de TIPO_DE_RED
    "n_redes",
    "antiguedad_dias",
]


# ── Bloques internos ─────────────────────────────────────────────────────────

def _codificar_categoricas(df: pl.LazyFrame) -> pl.LazyFrame:
    """Convierte las variables categóricas a representación numérica.

    tipo_perfil_ord: ordinal según escala de seniority (_TIPO_PERFIL_ORD).
                     OTROS → null (se imputa en _imputar_nulos con la mediana).
    es_red_estrategica: 1 si el prestador pertenece a la red ESTRATEGICA en al
                        menos una hoja del catálogo, 0 en caso contrario. Se
                        usa el booleano pre-computado en feat_prestador_perfil
                        (via .any()) para que prestadores multi-red sean
                        evaluados correctamente en lugar de depender del orden
                        arbitrario de .first().
    """
    return df.with_columns([
        pl.col("tipo_perfil")
        .replace(_TIPO_PERFIL_ORD, default=None)
        .cast(pl.Float64)
        .alias("tipo_perfil_ord"),

        pl.col("es_red_estrategica")
        .cast(pl.Float64),
    ])


def _imputar_nulos(df: pl.LazyFrame) -> pl.LazyFrame:
    """Imputa nulos en las features de clustering.

    Estrategia por tipo de métrica:

    → Cero: tasas y duraciones donde null significa "nunca ocurrió".
      Un prestador sin cancelaciones tiene tasa_cancelacion = 0, no nulo.
      Un prestador sin informes tiene tasa_aprobacion_informe = 0.

    → Mediana: métricas continuas donde null indica ausencia de datos
      (no ausencia del fenómeno). dias_ciclo_informe_prom y
      tipo_perfil_ord (OTROS) caen aquí.

    → Cero para n_municipios_destino: prestador con actividad en 2025
      pero sin registro de municipio destino en las citas → 0.

    Nota: esta función opera sobre prestadores con FLAG_SIN_ACTIVIDAD_2025=False,
    por lo que los nulos en features de performance son minoritarios.
    """
    # Features que se imputan con 0
    _imputar_cero = [
        "tasa_cancela_real_prestador",   # null = nunca tuvo cancelaciones con motivo → 0
        "tasa_aprobacion_informe",
        "tasa_aprobacion_auto",
        "duracion_promedio_ejecutada",
        "utilizacion_capacidad",
        "pct_programaciones_campo",  # null solo si n_programaciones_total == 0 (imposible para activos)
        "pct_empresa_compleja",      # null = sin citas CAMPO ejecutadas (prestador virtual) → 0
        "costo_logistico_prom",
        "n_municipios_destino",
        "ratio_cobertura_real",      # null si sin destinos registrados o sin catálogo geográfico
        "es_red_estrategica",
    ]

    # Features que se imputan con la mediana (valor típico del grupo)
    _imputar_mediana = [
        "dias_ciclo_informe_prom",
        "tipo_perfil_ord",
        "antiguedad_dias",   # null cuando FEALTA_PRESTADOR ausente en catálogo (29 casos)
    ]

    df = df.with_columns([
        pl.col(c).fill_null(0.0) for c in _imputar_cero
    ])

    # Mediana: se calcula una sola vez en un with_columns vectorizado
    df = df.with_columns([
        pl.col(c).fill_null(pl.col(c).median()) for c in _imputar_mediana
    ])

    return df


# ── API pública ──────────────────────────────────────────────────────────────

def build_clustering_input() -> pl.LazyFrame:
    """Matriz de features lista para sklearn.cluster.KMeans.

    Proceso:
      1. Carga feat_prestador (perfil + desempeño, 56 cols)
      2. Excluye prestadores sin ningún registro en TP (FLAG_SIN_ACTIVIDAD_2025=True).
         Los prestadores virtuales (FLAG_SOLO_VIRTUAL_2025=True) sí se incluyen.
      3. Codifica tipo_perfil → ordinal; es_red_estrategica (booleano pre-computado) → Float64
      4. Imputa nulos residuales
      5. Selecciona DNI_PRESTADOR + FEATURE_COLS + columnas de contexto

    Columnas de contexto (no entran al modelo, útiles para labeling):
        bloque_principal, clasificacion_predominante, tipo_perfil,
        tipo_red, municipio_base, dsoficina

    La normalización (StandardScaler) ocurre en el notebook:
        X = df[FEATURE_COLS].to_numpy()
        X_scaled = StandardScaler().fit_transform(X)
    """
    return (
        build_prestador_features()
        # Excluye solo los prestadores sin ningún registro en Tareas_Programadas
        # (FLAG_SIN_ACTIVIDAD_2025). Sin datos de desempeño, la imputación masiva
        # distorsionaría los centroides.
        # Los prestadores FLAG_SOLO_VIRTUAL_2025 (canal virtual, ruta LIVIANA) sí se
        # incluyen: tienen métricas de informe reales y formarán su propio segmento.
        .filter(~pl.col("FLAG_SIN_ACTIVIDAD_2025"))
        .pipe(_codificar_categoricas)
        .pipe(_imputar_nulos)
        # Castear todas las features a Float64 para homogeneidad
        .with_columns([
            pl.col(c).cast(pl.Float64) for c in FEATURE_COLS
        ])
        .select([
            # Identificador (no entra al modelo)
            "DNI_PRESTADOR",

            # Features del modelo
            *FEATURE_COLS,

            # Contexto técnico para interpretar clusters
            "bloque_principal",
            "clasificacion_predominante",
            "tipo_perfil",
            "tipo_red",
            "municipio_base",
            "dsoficina",
            "nombre_distribuidor",

            # Contexto de demanda atendida (M3: match oferta-demanda)
            # No entran a FEATURE_COLS (categóricas de alta cardinalidad),
            # pero son esenciales para nombrar y validar los clusters.
            "sector_principal_atendido",
            "segmento_principal_atendido",
        ])
    )
