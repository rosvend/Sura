# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

This project is a healthcare provider clustering system for ARL SURA (a Colombian workers' compensation insurer). It groups ~800 healthcare service provider firms into strategic clusters to optimize task assignment for ~2.1M client companies. Documentation and comments are in Spanish.

## Build & Run

Package manager is **uv** (Python 3.12). No test framework is configured yet.

```bash
uv sync                  # install dependencies

# Silver layer data loading (primary workflow for teammates)
uv run python -c "from src.silver.extract import load_ordenado; print(load_ordenado().collect().head())"

# Raw file ingestion (if converting new source files)
uv run python src/ingestion/extract.py <file>   # local path or gs://...

# One-off scripts (already ran, kept for reproducibility)
uv run python scripts/load_to_parquet.py        # batch convert raw files to parquet on GCS
uv run python scripts/benchmark.py              # benchmark loading approaches
```

## Architecture

Medallion (Bronze → Silver → Gold) data pipeline using **Polars** as the primary DataFrame library.

- **`src/config.py`** — centralized GCS bucket paths and dataset constants
- **`src/ingestion/`** — Bronze layer: raw file loading with auto-detection (encoding, delimiter). `load_data(path)` is the unified entry point.
- **`src/silver/`** — Silver layer: named loader functions returning `pl.LazyFrame`. This is where teammates start: `from src.silver.extract import load_ordenado`
- **`scripts/`** — one-off utilities (parquet conversion, benchmarks), not part of the pipeline
- **`docs/`** — project documentation (data dictionary, diagnosis, challenge spec, brand colors)
- **`notebooks/`** — EDA Jupyter notebooks

### Data Access Pattern

All data is pre-converted to Parquet on GCS. Use Polars lazy scan:

```python
from src.silver.extract import load_ordenado
df = load_ordenado().select(["col1", "col2"]).filter(pl.col("col1") == "x").collect()
```

## Key Conventions

- GCS bucket: `gs://sura-clustering-raw/`
- Integration keys across datasets: `DNI_PRESTADOR` (provider), `NMCONSECUTIVO_ORDEN` (order), `Empresa_Id` (company), `CDTAREA` (task)
- Encoding fallback order in raw loader: utf-8-sig → utf-8 → latin-1 → cp1252
- All raw columns are ingested as strings (`infer_schema_length=0`); type casting happens in silver layer

## Documentation & Analysis

### Doc Files (`/docs/`)

1. **RETO.md** - Challenge specification
   - Context: 800+ provider firms, 5,000 individual advisors
   - Problem: Centralized assignment creates bottlenecks
   - Deliverables: diagnostic doc, model proposal, functional prototype, monitoring dashboard
   - Evaluation criteria: model quality, innovation, clarity, real-world applicability

2. **DESCRIPCION_DATOS.md** - Comprehensive data dictionary
   - Describes all 5 datasets with field-by-field documentation
   - Explains data relationships and integration keys
   - Notes data quality issues and special considerations
   - Contains variable cardinality statistics (89 blocks, 39 products, 1,066 tasks, 900+ municipalities)

3. **DIAGNOSTICO_ANALISIS.md** - Problem diagnosis and initial analysis
   - Identifies 8 structural problems in current model (centralization bottleneck, fragmented provider info, lack of operational segmentation, high cancellation rates, capacity misalignment, geographic complexity, loss of client context, no feedback loop)
   - Proposes clustering strategy with detailed feature engineering plan
   - Includes 7-phase implementation roadmap
   - Outlines KPI framework for model monitoring

4. **GUIA_COLORES.md** - SURA brand color palette
   - Primary: Azure Blue (#2D6DF6), Pure White (#FFFFFF)
   - Complementary: SURA Blue (#0033A0), Cheerful Yellow (#E3E829), Aqua (#00AEC7), Neutral Gray (#888B8D)
   - Digital background colors and proportion rules (60/30/10)

5. **NOTAS.md** - Working notes and quick reference
   - Problem summary: need to determine optimal provider-to-client assignment
   - Actor definitions: Clients (demand), Providers (supply)
   - File-by-file reference guide

### Data Dictionary & Structure

**4 Core Datasets:**

1. **Provider Capabilities Catalog** (`Tareas_prestador_bloque.xlsx`)
   - Type: Master data (offer-side)
   - 4 sheets (regional networks): CGR, Red_otras_ofic, Red_med&Cali, Red_Bogota
   - 37 columns per provider-task combination
   - Key fields: DNI_PRESTADOR, CDBLOQUE, CDTAREA, CAPACIDAD, DSTIPO_PERFIL, PERFIL_TARIFA, CDMUNICIPIO
   - Describes what tasks each provider is authorized to perform, their expertise level, geographic coverage, and available capacity

2. **Purchase Orders** (`Ordenado.txt`, Tab-delimited)
   - Type: Transactional (historical orders)
   - 607,331 rows, 100 columns
   - Key fields: Ord_Plan_Vers_Act_Id (unique key), Dni_Prestador, Nombre_Empresa, Codigo_Tarea, Estado_Orden_Desc, Fecha_Entrega_Servicio, Valor_Costo_Total_Tarea, Municipio_Entrega_Desc
   - Captures complete order lifecycle: creation, assignment, delivery, costs, and final status (Facturado, Legalizado, Aprobado, Cancelado, etc. - 13 states)
   - Contains geographic data (origin/delivery municipalities) and financial data (unit costs, transport, per diem)

3. **Scheduled Tasks & Cancellations** (`Tareas_Programadas_canceladas_2025.txt`, Tab-delimited)
   - Type: Transactional (operational execution)
   - 1,542,709 rows, 62 columns
   - Key fields: NMCONSECUTIVO_ORDEN, DNI_PRESTADOR, DSESTADO_PROGRAMACION (7 states), DURACION, MOTIVO_CANCELACION, DSESTADO_INFORME
   - Records scheduled appointments for task execution in 2025 with outcomes (executed, cancelled, pending)
   - Captures cancellation reasons and report approval workflow
   - High-cardinality text field: MOTIVO_CANCELACION has 70,000+ unique values (needs NLP cleaning)

4. **Client Company Master** (`Detalle_Empresa.txt`, Virgulilla-delimited `~`)
   - Type: Master data (demand-side)
   - 2,175,102 rows, 16 columns
   - Key fields: Empresa_Id, ESTADO_EMPRESA, Numero_Afiliados, Segmentacion_Arl_Desc, Sector_Economico_Desc, Ruta_Atencion
   - Describes 1,475 economic activities across 29 economic sectors
   - Company segmentation: Gran Empresa, Mediana, Micro, Independiente, Empresa Nueva
   - Service routing levels: LIVIANA (light), ESTÁNDAR (standard), SIN RUTA (inactive)
