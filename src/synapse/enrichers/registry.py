"""Enricher registry and orchestration."""

from __future__ import annotations

from pathlib import Path

from synapse.core.models import IR, LanguageType
from synapse.enrichers.base import IREnricher
from synapse.enrichers.fiber import FiberEnricher
from synapse.enrichers.gin import GinEnricher
from synapse.enrichers.laravel import LaravelEnricher
from synapse.enrichers.spring import SpringEnricher


def get_default_enrichers() -> list[IREnricher]:
    """Return built-in enrichers shipped with Synapse."""
    return [
        SpringEnricher(),
        LaravelEnricher(),
        GinEnricher(),
        FiberEnricher(),
    ]


def enrich_ir(ir: IR, source_path: Path, languages: set[LanguageType]) -> list[str]:
    """Apply built-in enrichers and return any error messages."""
    errors: list[str] = []
    for enricher in get_default_enrichers():
        if not enricher.supported_languages.intersection(languages):
            continue
        try:
            enricher.enrich(ir, source_path)
        except Exception as exc:
            errors.append(f"{enricher.name}: {exc}")
    return errors
