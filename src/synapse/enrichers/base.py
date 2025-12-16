"""Base interface for IR enrichers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from synapse.core.models import IR, LanguageType


class IREnricher(ABC):
    """Post-process an IR to add framework-level semantics."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique enricher name."""

    @property
    @abstractmethod
    def supported_languages(self) -> set[LanguageType]:
        """Languages this enricher can operate on."""

    @abstractmethod
    def enrich(self, ir: IR, source_path: Path) -> None:
        """Mutate IR in-place to add metadata and relationships."""

