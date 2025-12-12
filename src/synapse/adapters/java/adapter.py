"""Java language adapter using tree-sitter-java.

This module implements the LanguageAdapter interface for Java source code,
using tree-sitter for parsing and a two-phase approach for symbol resolution.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from synapse.adapters.base import LanguageAdapter, SymbolTable
from synapse.adapters.java.resolver import JavaResolver
from synapse.adapters.java.scanner import JavaScanner
from synapse.core.models import IR, LanguageType


class JavaAdapter(LanguageAdapter):
    """Java language adapter using tree-sitter.

    Implements two-phase parsing:
    - Phase 1: Scan all files to build symbol table (types and methods)
    - Phase 2: Resolve references using the symbol table
    """

    def __init__(self, project_id: str) -> None:
        """Initialize the Java adapter.

        Args:
            project_id: The project identifier for ID generation
        """
        super().__init__(project_id)
        self._language = Language(tsjava.language())
        self._parser = Parser(self._language)
        self._scanner = JavaScanner(self._parser)
        self._resolver = JavaResolver(
            self._parser,
            project_id,
            self.language_type,
            self.generate_id,
        )

    @property
    def language_type(self) -> LanguageType:
        """Return Java as the supported language type."""
        return LanguageType.JAVA

    def analyze(self, source_path: Path) -> IR:
        """Analyze Java source code and return IR.

        Args:
            source_path: Root directory of Java source code

        Returns:
            IR containing all modules, types, and callables
        """
        # Phase 1: Build symbol table
        symbol_table = self.build_symbol_table(source_path)

        # Phase 2: Resolve references
        return self.resolve_references(source_path, symbol_table)

    def build_symbol_table(self, source_path: Path) -> SymbolTable:
        """Phase 1: Scan all Java files and build symbol table.

        Collects all type and method definitions without resolving references.

        Args:
            source_path: Root directory of Java source code

        Returns:
            SymbolTable containing all definitions
        """
        return self._scanner.scan_directory(source_path)

    def resolve_references(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        """Phase 2: Resolve references using the symbol table.

        Args:
            source_path: Root directory of Java source code
            symbol_table: Symbol table from Phase 1

        Returns:
            IR with resolved references
        """
        return self._resolver.resolve_directory(source_path, symbol_table)
