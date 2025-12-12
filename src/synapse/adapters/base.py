"""Base classes and utilities for language adapters.

This module defines the LanguageAdapter abstract interface for implementing
language-specific parsers, along with supporting classes for symbol tables
and deterministic ID generation.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from synapse.core.models import IR, LanguageType

if TYPE_CHECKING:
    pass


class FileContext(BaseModel):
    """File-level context for symbol resolution.

    Contains information about the current file being parsed,
    used to resolve short names to qualified names.
    """

    package: str = Field(..., description="Current package/module name")
    imports: list[str] = Field(default_factory=list, description="Import statements")
    local_types: dict[str, str] = Field(
        default_factory=dict, description="Local type aliases (short -> qualified)"
    )


class SymbolTable(BaseModel):
    """Symbol table for two-phase parsing.

    Stores definition information collected during Phase 1 (definition scanning)
    for use in Phase 2 (reference resolution).
    """

    type_map: dict[str, list[str]] = Field(
        default_factory=dict, description="short_name -> [qualified_names]"
    )
    callable_map: dict[str, list[str]] = Field(
        default_factory=dict, description="short_name -> [qualified_names]"
    )
    module_map: dict[str, str] = Field(
        default_factory=dict, description="qualified_name -> module_id"
    )

    def add_type(self, short_name: str, qualified_name: str) -> None:
        """Register a type in the symbol table."""
        if short_name not in self.type_map:
            self.type_map[short_name] = []
        if qualified_name not in self.type_map[short_name]:
            self.type_map[short_name].append(qualified_name)

    def add_callable(self, short_name: str, qualified_name: str) -> None:
        """Register a callable in the symbol table."""
        if short_name not in self.callable_map:
            self.callable_map[short_name] = []
        if qualified_name not in self.callable_map[short_name]:
            self.callable_map[short_name].append(qualified_name)

    def resolve_type(self, short_name: str, context: FileContext) -> str | None:
        """Resolve a type's short name to its qualified name using file context.

        Resolution order:
        1. Check local type aliases
        2. Check same-package types
        3. Check imported types (explicit imports)
        4. Check wildcard imports

        Args:
            short_name: The simple type name to resolve
            context: The file context containing package and imports

        Returns:
            The qualified name if resolved, None otherwise
        """
        # 1. Check local type aliases
        if short_name in context.local_types:
            return context.local_types[short_name]

        candidates = self.type_map.get(short_name, [])
        if not candidates:
            return None

        # 2. Check same-package types
        same_package = f"{context.package}.{short_name}"
        if same_package in candidates:
            return same_package

        # 3. Check explicit imports
        for imp in context.imports:
            if imp.endswith(f".{short_name}"):
                if imp in candidates:
                    return imp

        # 4. Check wildcard imports
        for imp in context.imports:
            if imp.endswith(".*"):
                prefix = imp[:-2]  # Remove ".*"
                for candidate in candidates:
                    if candidate.startswith(prefix + ".") and candidate.endswith(
                        f".{short_name}"
                    ):
                        return candidate

        # 5. Return first candidate as fallback (may be ambiguous)
        return candidates[0] if len(candidates) == 1 else None

    def resolve_callable(
        self, short_name: str, owner_qualified_name: str | None = None
    ) -> str | None:
        """Resolve a callable's short name to its qualified name.

        Args:
            short_name: The simple callable name to resolve
            owner_qualified_name: Optional owner type's qualified name for methods

        Returns:
            The qualified name if resolved, None otherwise
        """
        candidates = self.callable_map.get(short_name, [])
        if not candidates:
            return None

        if owner_qualified_name:
            # Look for method on specific type
            prefix = f"{owner_qualified_name}."
            for candidate in candidates:
                if candidate.startswith(prefix):
                    return candidate

        return candidates[0] if len(candidates) == 1 else None


def generate_entity_id(
    project_id: str,
    language_type: LanguageType,
    qualified_name: str,
    signature: str | None = None,
) -> str:
    """Generate a deterministic entity ID.

    Uses SHA256 hash of the entity's identifying properties to ensure
    the same entity always gets the same ID across multiple scans.

    Args:
        project_id: The project identifier
        language_type: The programming language
        qualified_name: The fully qualified name of the entity
        signature: Optional method signature (for Callables)

    Returns:
        A hex string ID (length from config, default 16)
    """
    from synapse.core.config import get_config

    config = get_config()
    parts = [project_id, language_type.value, qualified_name]
    if signature:
        parts.append(signature)
    content = "|".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[: config.id_length]


class LanguageAdapter(ABC):
    """Abstract base class for language-specific parsers.

    Implements a two-phase parsing strategy:
    - Phase 1 (Definition Scanning): Scan all files to build a symbol table
    - Phase 2 (Reference Resolution): Use the symbol table to resolve references

    Subclasses must implement the abstract methods for their specific language.
    """

    def __init__(self, project_id: str) -> None:
        """Initialize the adapter.

        Args:
            project_id: The project identifier for ID generation
        """
        self.project_id = project_id

    @property
    @abstractmethod
    def language_type(self) -> LanguageType:
        """Return the supported language type."""
        ...

    @abstractmethod
    def analyze(self, source_path: Path) -> IR:
        """Analyze source code directory and return IR data.

        This method orchestrates the two-phase parsing:
        1. Call build_symbol_table() to scan definitions
        2. Call resolve_references() to resolve references

        Args:
            source_path: Root directory of source code

        Returns:
            IR containing all modules, types, and callables

        Raises:
            ParseError: If parsing fails critically
        """
        ...

    @abstractmethod
    def build_symbol_table(self, source_path: Path) -> SymbolTable:
        """Phase 1: Scan all files and build the symbol table.

        Collects all type and callable definitions without resolving
        references between them.

        Args:
            source_path: Root directory of source code

        Returns:
            SymbolTable containing all definitions
        """
        ...

    @abstractmethod
    def resolve_references(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        """Phase 2: Use symbol table to resolve references.

        Parses files again, this time resolving references using the
        symbol table built in Phase 1. Unresolvable references are
        marked as Unresolved rather than causing failures.

        Args:
            source_path: Root directory of source code
            symbol_table: Symbol table from Phase 1

        Returns:
            IR with resolved references
        """
        ...

    def generate_id(
        self, qualified_name: str, signature: str | None = None
    ) -> str:
        """Generate a deterministic ID for an entity.

        Convenience method that uses the adapter's project_id and language_type.

        Args:
            qualified_name: The fully qualified name of the entity
            signature: Optional method signature (for Callables)

        Returns:
            A 16-character hex string ID
        """
        return generate_entity_id(
            self.project_id, self.language_type, qualified_name, signature
        )
