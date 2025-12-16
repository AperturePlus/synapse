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
    callable_return_types: dict[str, str] = Field(
        default_factory=dict, description="qualified_callable_name -> return_type"
    )
    field_types: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="owner_type -> {field_name -> field_type}"
    )
    callable_signatures: dict[str, str] = Field(
        default_factory=dict, description="qualified_callable_name -> signature"
    )
    type_hierarchy: dict[str, list[str]] = Field(
        default_factory=dict, description="type_qualified_name -> [supertype_qualified_names]"
    )

    def add_type(self, short_name: str, qualified_name: str) -> None:
        """Register a type in the symbol table."""
        if short_name not in self.type_map:
            self.type_map[short_name] = []
        if qualified_name not in self.type_map[short_name]:
            self.type_map[short_name].append(qualified_name)

    def add_callable(
        self,
        short_name: str,
        qualified_name: str,
        return_type: str | None = None,
        signature: str | None = None,
    ) -> None:
        """Register a callable in the symbol table.

        For overloaded methods (same qualified name, different signatures),
        each overload is stored as a separate entry in callable_map.
        The signature is used as part of the key for callable_signatures
        and callable_return_types to support overload resolution.

        Args:
            short_name: The simple name of the callable.
            qualified_name: The fully qualified name.
            return_type: Optional return type name.
            signature: Optional method signature (e.g., "(String, int)").
        """
        if short_name not in self.callable_map:
            self.callable_map[short_name] = []

        # For overloaded methods, we need to track each overload separately
        # Use qualified_name + signature as the unique key for signatures/return types
        sig_key = f"{qualified_name}#{signature}" if signature else qualified_name

        # Add to callable_map if this exact overload isn't already present
        # Check if this specific overload (qualified_name + signature) exists
        existing_sigs = [
            self.callable_signatures.get(f"{qualified_name}#{s}")
            for s in self._get_signatures_for_qualified_name(qualified_name)
        ]

        if signature not in existing_sigs:
            # This is a new overload or the first entry
            if qualified_name not in self.callable_map[short_name]:
                self.callable_map[short_name].append(qualified_name)

        if return_type:
            self.callable_return_types[sig_key] = return_type
        if signature:
            self.callable_signatures[sig_key] = signature

    def _get_signatures_for_qualified_name(self, qualified_name: str) -> list[str]:
        """Get all signatures registered for a qualified name.

        Args:
            qualified_name: The fully qualified callable name.

        Returns:
            List of signatures for this callable (for overload tracking).
        """
        signatures = []
        prefix = f"{qualified_name}#"
        for key in self.callable_signatures:
            if key.startswith(prefix):
                signatures.append(key[len(prefix):])
            elif key == qualified_name:
                # Legacy key without signature
                signatures.append("")
        return signatures

    def get_callable_return_type(
        self, qualified_name: str, signature: str | None = None
    ) -> str | None:
        """Get the return type for a callable.

        Args:
            qualified_name: The fully qualified callable name.
            signature: Optional signature for overloaded methods.

        Returns:
            The return type name, or None if not known.
        """
        if signature:
            sig_key = f"{qualified_name}#{signature}"
            if sig_key in self.callable_return_types:
                return self.callable_return_types[sig_key]
        # Fall back to legacy key or first match
        if qualified_name in self.callable_return_types:
            return self.callable_return_types[qualified_name]
        # Try to find any return type for this qualified name
        prefix = f"{qualified_name}#"
        for key, value in self.callable_return_types.items():
            if key.startswith(prefix):
                return value
        return None

    def get_callable_signature(self, qualified_name: str) -> str | None:
        """Get the signature for a callable.

        For overloaded methods, returns the first signature found.
        Use get_all_signatures_for_callable for all overloads.

        Args:
            qualified_name: The fully qualified callable name.

        Returns:
            The signature string (e.g., "(String, int)"), or None if not known.
        """
        # Check legacy key first
        if qualified_name in self.callable_signatures:
            return self.callable_signatures[qualified_name]
        # Try to find any signature for this qualified name
        prefix = f"{qualified_name}#"
        for key, value in self.callable_signatures.items():
            if key.startswith(prefix):
                return value
        return None

    def get_all_signatures_for_callable(self, qualified_name: str) -> list[str]:
        """Get all signatures for a callable (for overloaded methods).

        Args:
            qualified_name: The fully qualified callable name.

        Returns:
            List of all signatures for this callable.
        """
        signatures = []
        # Check legacy key
        if qualified_name in self.callable_signatures:
            signatures.append(self.callable_signatures[qualified_name])
        # Check new format keys
        prefix = f"{qualified_name}#"
        for key, value in self.callable_signatures.items():
            if key.startswith(prefix) and value not in signatures:
                signatures.append(value)
        return signatures

    def add_field(self, owner_type: str, field_name: str, field_type: str) -> None:
        """Register a field in the symbol table.

        Args:
            owner_type: The type that owns the field.
            field_name: The name of the field.
            field_type: The type of the field.
        """
        if owner_type not in self.field_types:
            self.field_types[owner_type] = {}
        self.field_types[owner_type][field_name] = field_type

    def add_type_hierarchy(self, type_name: str, supertypes: list[str]) -> None:
        """Register a type's supertypes in the symbol table.

        Args:
            type_name: The qualified name of the type.
            supertypes: List of qualified names of supertypes (extends/implements/embeds).
        """
        if type_name not in self.type_hierarchy:
            self.type_hierarchy[type_name] = []
        for supertype in supertypes:
            if supertype not in self.type_hierarchy[type_name]:
                self.type_hierarchy[type_name].append(supertype)

    def get_supertypes(self, type_name: str) -> list[str]:
        """Get the supertypes for a type.

        Args:
            type_name: The qualified name of the type.

        Returns:
            List of qualified supertype names, or empty list if none.
        """
        return self.type_hierarchy.get(type_name, [])

    def get_field_type(self, owner_type: str, field_name: str) -> str | None:
        """Get the type of a field.

        Args:
            owner_type: The type that owns the field.
            field_name: The name of the field.

        Returns:
            The field type name, or None if not known.
        """
        if owner_type in self.field_types:
            return self.field_types[owner_type].get(field_name)
        return None

    def resolve_type(self, short_name: str, context: FileContext) -> str | None:
        """Resolve a type's short name to its qualified name using file context.

        Resolution order:
        1. Check local type aliases
        2. Check same-package types
        3. Check imported types (explicit imports)
        4. Check wildcard imports

        Note: Candidates are sorted to ensure deterministic resolution order
        regardless of symbol table insertion order (Requirement 5.3).

        Args:
            short_name: The simple type name to resolve
            context: The file context containing package and imports

        Returns:
            The qualified name if resolved, None otherwise
        """
        # 1. Check local type aliases
        if short_name in context.local_types:
            return context.local_types[short_name]

        # Sort candidates for deterministic iteration order (Requirement 5.3)
        candidates = sorted(self.type_map.get(short_name, []))
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

        # 4. Check wildcard imports (iterate sorted candidates for determinism)
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

        Note: Candidates are sorted to ensure deterministic resolution order
        regardless of symbol table insertion order (Requirement 5.3).

        Args:
            short_name: The simple callable name to resolve
            owner_qualified_name: Optional owner type's qualified name for methods

        Returns:
            The qualified name if resolved, None otherwise
        """
        # Sort candidates for deterministic iteration order (Requirement 5.3)
        candidates = sorted(self.callable_map.get(short_name, []))
        if not candidates:
            return None

        if owner_qualified_name:
            # Look for method on specific type - return first match in sorted order
            prefix = f"{owner_qualified_name}."
            for candidate in candidates:
                if candidate.startswith(prefix):
                    return candidate

        return candidates[0] if len(candidates) == 1 else None

    def resolve_callable_with_receiver(
        self,
        method_name: str,
        receiver_type: str | None,
        signature: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Resolve callable using receiver type and signature.

        Resolution order:
        1. If receiver_type is None, return error "Unknown receiver type"
        2. Check methods on the receiver type itself
        3. Check methods on supertypes (in order)
        4. If multiple matches and signature provided, use signature to disambiguate
        5. If still ambiguous, return error "Ambiguous: N candidates"

        Note: Candidates are sorted to ensure deterministic resolution order
        regardless of symbol table insertion order (Requirement 5.3).

        Args:
            method_name: The simple method name to resolve
            receiver_type: The qualified name of the receiver type, or None if unknown
            signature: Optional method signature for disambiguation

        Returns:
            Tuple of (qualified_name, error_reason) - one will be None
        """
        if receiver_type is None:
            return (None, "Unknown receiver type")

        # Sort candidates for deterministic iteration order (Requirement 5.3)
        candidates = sorted(self.callable_map.get(method_name, []))
        if not candidates:
            return (None, f"Method not found: {method_name}")

        # Collect types to check: receiver type + supertypes
        types_to_check = [receiver_type] + self.get_supertypes(receiver_type)

        # Find matching candidates on receiver type or supertypes
        # Use a set for deduplication, then sort for deterministic order
        matching_set: set[str] = set()
        for type_name in types_to_check:
            prefix = f"{type_name}."
            for candidate in candidates:
                if candidate.startswith(prefix):
                    matching_set.add(candidate)
        matching_candidates = sorted(matching_set)

        if not matching_candidates:
            return (None, f"Method not found on type {receiver_type}")

        # Try signature disambiguation if provided
        if signature:
            # Check each candidate for matching signature
            # Use set for deduplication, then sort for deterministic order
            signature_match_set: set[str] = set()
            for candidate in matching_candidates:
                # Check if this candidate has the matching signature
                sig_key = f"{candidate}#{signature}"
                if sig_key in self.callable_signatures:
                    signature_match_set.add(candidate)
                # Also check legacy format
                elif (candidate in self.callable_signatures and
                      self.callable_signatures[candidate] == signature):
                    signature_match_set.add(candidate)

            signature_matches = sorted(signature_match_set)
            if len(signature_matches) == 1:
                return (signature_matches[0], None)
            if len(signature_matches) > 1:
                return (None, f"Ambiguous: {len(signature_matches)} candidates")

            # No exact signature match - check if any candidate has this signature
            # among its overloads (iterate in sorted order for determinism)
            for candidate in matching_candidates:
                all_sigs = self.get_all_signatures_for_callable(candidate)
                if signature in all_sigs:
                    return (candidate, None)

        # If only one match and no signature provided, return it
        if len(matching_candidates) == 1:
            return (matching_candidates[0], None)

        # Multiple matches without signature disambiguation
        return (None, f"Ambiguous: {len(matching_candidates)} candidates")


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
