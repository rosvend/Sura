"""Gold layer — features de perfil técnico por prestador.

Computa el vector de especialización de cada asesor a partir del catálogo
de capacidades (Tareas_prestador_bloque). Captura el perfil *declarado*:
qué tareas está habilitado a ejecutar, en qué áreas se especializa y cuál
es su capacidad disponible.

Estas features complementan las de desempeño operativo (feat_prestador_performance.py),
que capturan el perfil *real* observado en la ejecución de 2025.

Uso:
    from src.gold.feat_prestador_perfil import build_perfil_features
    df = build_perfil_features().collect()
"""

import datetime

import polars as pl

from src.silver.extract import load_tareas_prestador

# Fecha de corte para calcular antigüedad (hoy según contexto del proyecto)
_FECHA_CORTE = datetime.date(2026, 4, 8)


# ── Bloques internos ─────────────────────────────────────────────────────────

def _perfil_base() -> pl.LazyFrame:
    """Agregaciones directas por DNI_PRESTADOR desde el catálogo.

    CAPACIDAD, DSTIPO_PERFIL, FUNCION_PRESTADOR, PERFIL_TARIFA, TIPO_DE_RED
    y CDOFICINA son atributos del asesor repetidos en cada fila; se extrae
    el primer valor no nulo. FEALTA_PRESTADOR toma el mínimo (fecha de
    registro más antigua del asesor en el sistema).
    """
    return (
        load_tareas_prestador()
        .group_by("DNI_PRESTADOR")
        .agg([
            # ── Identificación ───────────────────────────────────────────────
            pl.col("NOMBRE_PRESTADOR").first().alias("nombre_prestador"),
            pl.col("DNI_DISTRIBUIDOR").first().alias("dni_distribuidor"),
            pl.col("NOMBRE_DISTRIBUIDOR").first().alias("nombre_distribuidor"),

            # ── Dimensión técnica: amplitud del catálogo ─────────────────────
            # n_habilitaciones: total de filas = combinaciones (tarea × bloque)
            # n_tareas_distintas: tareas únicas, independientemente del bloque
            pl.len().alias("n_habilitaciones"),
            pl.col("CDTAREA").n_unique().alias("n_tareas_distintas"),
            pl.col("CDBLOQUE").n_unique().alias("n_bloques_distintos"),
            pl.col("CDPRODUCTO").n_unique().alias("n_productos_distintos"),

            # ── Perfil del asesor (atributos a nivel asesor) ─────────────────
            pl.col("DSTIPO_PERFIL").first().alias("tipo_perfil"),
            pl.col("PERFIL_TARIFA").first().alias("perfil_tarifa"),
            pl.col("FUNCION_PRESTADOR").first().alias("funcion_prestador"),

            # ── Red y oficina ────────────────────────────────────────────────
            pl.col("TIPO_DE_RED").first().alias("tipo_red"),
            pl.col("CDOFICINA").first().alias("cdoficina"),
            pl.col("DSOFICINA").first().alias("dsoficina"),
            # Cuántas redes regionales (hojas del Excel) incluyen al prestador.
            # 1 = exclusivo de una red; 4 = presente en todas las redes.
            pl.col("_RED_ORIGEN").n_unique().alias("n_redes"),
            # Flag directo: True si el prestador aparece en la red ESTRATEGICA
            # en al menos una de las hojas del catálogo. Se usa .any() en lugar
            # de .first() porque un prestador puede estar en múltiples redes con
            # distintos TIPO_DE_RED; .first() elige arbitrariamente una hoja.
            (pl.col("TIPO_DE_RED") == "ESTRATEGICA").any().alias("es_red_estrategica"),

            # ── Capacidad ────────────────────────────────────────────────────
            # CAPACIDAD es el mismo valor en todas las filas del asesor.
            # Se toma el primer valor; FLAG_CAPACIDAD_CERO indica si es 0.
            pl.col("CAPACIDAD").first().alias("capacidad"),
            pl.col("FLAG_CAPACIDAD_CERO").first().alias("sin_capacidad"),

            # ── Cobertura geográfica ─────────────────────────────────────────
            pl.col("CDMUNICIPIO").n_unique().alias("n_municipios_cobertura"),
            pl.col("CDMUNICIPIO").first().alias("cdmunicipio_base"),
            pl.col("DSMUNICIPIO").first().alias("municipio_base"),

            # ── Antigüedad ───────────────────────────────────────────────────
            # Fecha de registro más antigua del asesor en el sistema.
            pl.col("FEALTA_PRESTADOR").min().alias("fealta_prestador"),
        ])
    )


def _clasificacion_predominante() -> pl.LazyFrame:
    """Clasificación de servicio más frecuente por prestador.

    Patrón: contar por (prestador, clasificación) → ordenar descendente →
    tomar el primero por prestador. Equivalente a un MODE en SQL.

    DSCLASIFICACION: Asesoría, Capacitación, Promoción, Inspección, etc.
    """
    return (
        load_tareas_prestador()
        .group_by(["DNI_PRESTADOR", "DSCLASIFICACION"])
        .agg(pl.len().alias("_cnt"))
        .sort("_cnt", descending=True)
        .group_by("DNI_PRESTADOR")
        .agg(pl.col("DSCLASIFICACION").first().alias("clasificacion_predominante"))
    )


def _bloque_principal() -> pl.LazyFrame:
    """Bloque temático con más tareas habilitadas y índice de especialización.

    indice_especializacion = n_tareas_en_bloque_principal / n_tareas_distintas_total

    Un valor cercano a 1 indica un asesor muy concentrado en un solo bloque
    (especialista); cercano a 0 indica un asesor generalista distribuido en
    muchos bloques.
    """
    tp = load_tareas_prestador()

    # Paso 1: contar tareas distintas por (prestador, bloque)
    por_bloque = (
        tp
        .group_by(["DNI_PRESTADOR", "CDBLOQUE", "DSBLOQUE"])
        .agg(pl.col("CDTAREA").n_unique().alias("n_tareas_bloque"))
    )

    # Paso 2: para cada prestador, tomar el bloque con más tareas
    bloque_top = (
        por_bloque
        .sort("n_tareas_bloque", descending=True)
        .group_by("DNI_PRESTADOR")
        .agg([
            pl.col("CDBLOQUE").first().alias("cdbloque_principal"),
            pl.col("DSBLOQUE").first().alias("bloque_principal"),
            pl.col("n_tareas_bloque").first().alias("n_tareas_bloque_principal"),
        ])
    )

    # Paso 3: índice de especialización — requiere n_tareas_distintas del total,
    # que se calcula en _perfil_base. Se devuelve bloque_top y el join lo cierra.
    return bloque_top


# ── API pública ──────────────────────────────────────────────────────────────

def build_perfil_features() -> pl.LazyFrame:
    """Tabla Gold de perfil técnico declarado por DNI_PRESTADOR.

    Combina las tres sub-agregaciones y calcula el índice de especialización
    final. Cubre todos los prestadores del catálogo, incluidos los que no
    tienen actividad en 2025 (a diferencia de feat_prestador_performance, que
    solo incluye prestadores con citas programadas ese año).

    Columnas clave de salida
    ─────────────────────────
    n_habilitaciones         filas en catálogo = combinaciones (tarea × bloque)
    n_tareas_distintas       tareas únicas habilitadas
    n_bloques_distintos      bloques temáticos con al menos una tarea
    n_productos_distintos    productos/programas cubiertos
    clasificacion_predominante  tipo de servicio más frecuente en el catálogo
    bloque_principal         bloque con más tareas habilitadas
    indice_especializacion   n_tareas_bloque_principal / n_tareas_distintas
                             → 1.0 = especialista puro; ~0 = generalista
    capacidad                horas disponibles declaradas para el periodo
    sin_capacidad            True si CAPACIDAD == 0
    n_municipios_cobertura   municipios de base distintos en el catálogo
    n_redes                  cuántas redes regionales incluyen al prestador
    antiguedad_dias          días desde FEALTA_PRESTADOR hasta fecha de corte
    """
    base = _perfil_base()
    clasificacion = _clasificacion_predominante()
    bloque = _bloque_principal()

    return (
        base
        .join(clasificacion, on="DNI_PRESTADOR", how="left")
        .join(bloque, on="DNI_PRESTADOR", how="left")
        # Índice de especialización: requiere n_tareas_distintas (de base)
        # y n_tareas_bloque_principal (de bloque_top)
        .with_columns(
            pl.when(pl.col("n_tareas_distintas") > 0)
            .then(
                pl.col("n_tareas_bloque_principal") / pl.col("n_tareas_distintas")
            )
            .otherwise(None)
            .alias("indice_especializacion")
        )
        # Antigüedad en días desde el registro en el sistema
        .with_columns(
            (pl.lit(_FECHA_CORTE) - pl.col("fealta_prestador"))
            .dt.total_days()
            .alias("antiguedad_dias")
        )
    )
