"""Fiber semantic enrichment for Go IR.

Best-effort extraction of HTTP routes registered via `github.com/gofiber/fiber`
and attachment to handler callables as `Callable.routes` entries.
"""

from __future__ import annotations

from pathlib import Path

from synapse.core.models import IR, LanguageType
from synapse.enrichers.base import IREnricher
from synapse.enrichers.go_router import GoRouterConfig, GoRouterRouteExtractor


_FIBER_CONFIG = GoRouterConfig(
    framework="fiber",
    import_prefixes=("github.com/gofiber/fiber",),
    path_first_methods={
        "Get": "GET",
        "Post": "POST",
        "Put": "PUT",
        "Patch": "PATCH",
        "Delete": "DELETE",
        "Options": "OPTIONS",
        "Head": "HEAD",
        "All": "ANY",
    },
    verb_path_methods=frozenset({"Add"}),
    group_method="Group",
)


class FiberEnricher(IREnricher):
    """Enrich Go IR with Fiber routing semantics."""

    def __init__(self) -> None:
        self._extractor = GoRouterRouteExtractor(_FIBER_CONFIG)

    @property
    def name(self) -> str:
        return "fiber"

    @property
    def supported_languages(self) -> set[LanguageType]:
        return {LanguageType.GO}

    def enrich(self, ir: IR, source_path: Path) -> None:
        self._extractor.enrich(ir, source_path)

