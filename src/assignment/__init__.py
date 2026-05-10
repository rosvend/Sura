"""Motor de asignación (Día 3).

Expone:
    score_providers(empresa_id, cdtarea, cd_municipio_destino=None, top_n=10)
        → top-N prestadores compatibles con score breakdown.
"""

from src.assignment.score import score_providers

__all__ = ["score_providers"]
