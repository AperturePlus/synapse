"""Gin semantic enrichment for Go IR.

Best-effort extraction of HTTP routes registered via `github.com/gin-gonic/gin`
and attachment to handler callables as `Callable.routes` entries.
"""

from __future__ import annotations

from pathlib import Path

from synapse.core.models import IR, LanguageType
from synapse.enrichers.base import IREnricher
from synapse.enrichers.go_router import GoRouterConfig, GoRouterRouteExtractor


_GIN_CONFIG = GoRouterConfig(
    framework="gin",
    import_prefixes=("github.com/gin-gonic/gin",),
    path_first_methods={
        "GET": "GET",
        "POST": "POST",
        "PUT": "PUT",
        "PATCH": "PATCH",
        "DELETE": "DELETE",
        "OPTIONS": "OPTIONS",
        "HEAD": "HEAD",
        "Any": "ANY",
    },
    verb_path_methods=frozenset({"Handle"}),
    group_method="Group",
)


class GinEnricher(IREnricher):
    """Enrich Go IR with Gin routing semantics."""

    def __init__(self) -> None:
        self._extractor = GoRouterRouteExtractor(_GIN_CONFIG)

    @property
    def name(self) -> str:
        return "gin"

    @property
    def supported_languages(self) -> set[LanguageType]:
        return {LanguageType.GO}

    def enrich(self, ir: IR, source_path: Path) -> None:
        self._extractor.enrich(ir, source_path)

