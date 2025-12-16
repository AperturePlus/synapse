"""PHP language adapter using tree-sitter-php.

Implements the standard two-phase approach:
- Phase 1: Scan definitions to build a symbol table (types/functions/methods)
- Phase 2: Build IR and resolve basic references (namespace/use/extends/implements)

Call graph resolution for PHP is intentionally best-effort due to the language's
dynamic nature; unresolved references should be expected for real-world projects.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_php as tsphp
from tree_sitter import Language, Parser

from synapse.adapters.base import LanguageAdapter, SymbolTable
from synapse.adapters.php.resolver import PhpResolver
from synapse.adapters.php.scanner import PhpScanner
from synapse.core.models import IR, LanguageType


class PhpAdapter(LanguageAdapter):
    """PHP language adapter using tree-sitter."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self._language = Language(tsphp.language_php())
        self._parser = Parser(self._language)
        self._scanner = PhpScanner(self._parser)
        self._resolver = PhpResolver(
            self._parser,
            project_id,
            self.language_type,
            self.generate_id,
        )

    @property
    def language_type(self) -> LanguageType:
        return LanguageType.PHP

    def analyze(self, source_path: Path) -> IR:
        symbol_table = self.build_symbol_table(source_path)
        return self.resolve_references(source_path, symbol_table)

    def build_symbol_table(self, source_path: Path) -> SymbolTable:
        return self._scanner.scan_directory(source_path)

    def resolve_references(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        return self._resolver.resolve_directory(source_path, symbol_table)

