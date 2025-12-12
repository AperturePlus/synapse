"""Go language adapter using tree-sitter-go.

This module implements the LanguageAdapter interface for Go source code,
using tree-sitter for parsing and a two-phase approach for symbol resolution.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_go as tsgo
from tree_sitter import Language, Parser

from synapse.adapters.base import LanguageAdapter, SymbolTable
from synapse.adapters.go.resolver import GoResolver
from synapse.adapters.go.scanner import GoScanner
from synapse.core.models import IR, LanguageType


class GoAdapter(LanguageAdapter):
    """Go language adapter using tree-sitter.

    Implements two-phase parsing:
    - Phase 1: Scan all files to build symbol table (types and functions)
    - Phase 2: Resolve references using the symbol table

    MVP Limitations:
    - Does not detect implicit interface implementations (IMPLEMENTS)
    - Only handles struct definitions and EMBEDS relationships
    """

    def __init__(self, project_id: str) -> None:
        """Initialize the Go adapter.

        Args:
            project_id: The project identifier for ID generation
        """
        super().__init__(project_id)
        self._language = Language(tsgo.language())
        self._parser = Parser(self._language)
        self._scanner = GoScanner(self._parser, self.generate_id)
        self._resolver = GoResolver(
            self._parser,
            project_id,
            self.language_type,
            self.generate_id,
        )
        self._module_name: str = ""

    @property
    def language_type(self) -> LanguageType:
        """Return Go as the supported language type."""
        return LanguageType.GO

    def analyze(self, source_path: Path) -> IR:
        """Analyze Go source code and return IR.

        Args:
            source_path: Root directory of Go source code

        Returns:
            IR containing all modules, types, and callables
        """
        # Try to read module name from go.mod
        self._module_name = self._scanner.read_module_name(source_path)

        # Phase 1: Build symbol table
        symbol_table = self.build_symbol_table(source_path)

        # Phase 2: Resolve references
        return self.resolve_references(source_path, symbol_table)

    def build_symbol_table(self, source_path: Path) -> SymbolTable:
        """Phase 1: Scan all Go files and build symbol table.

        Args:
            source_path: Root directory of Go source code

        Returns:
            SymbolTable containing all definitions
        """
        # Read module name if not already set
        if not self._module_name:
            self._module_name = self._scanner.read_module_name(source_path)
        return self._scanner.scan_directory(source_path, self._module_name)

    def resolve_references(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        """Phase 2: Resolve references using the symbol table.

        Args:
            source_path: Root directory of Go source code
            symbol_table: Symbol table from Phase 1

        Returns:
            IR with resolved references
        """
        return self._resolver.resolve_directory(
            source_path, symbol_table, self._module_name
        )
