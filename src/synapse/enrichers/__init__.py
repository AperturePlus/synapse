"""IR enrichers for framework-level semantics.

Enrichers run after language adapters produce IR, adding best-effort semantic
relationships and metadata for common frameworks (e.g., Spring, Laravel).
"""

from synapse.enrichers.base import IREnricher
from synapse.enrichers.registry import enrich_ir, get_default_enrichers

__all__ = [
    "IREnricher",
    "enrich_ir",
    "get_default_enrichers",
]

