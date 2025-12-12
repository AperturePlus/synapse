"""Go scanner for Phase 1 symbol table construction.

This module scans Go source files to build a symbol table
containing all type and callable definitions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable as CallableFunc

from tree_sitter import Node, Parser

from synapse.adapters.base import SymbolTable
from synapse.adapters.go.ast_utils import GoAstUtils

logger = logging.getLogger(__name__)


class GoScanner:
    """Phase 1: Scan Go files to build symbol table.

    Collects all type and function definitions without resolving references.
    """

    def __init__(
        self,
        parser: Parser,
        id_generator: CallableFunc[[str, str | None], str],
    ) -> None:
        """Initialize the scanner.

        Args:
            parser: Configured tree-sitter parser for Go
            id_generator: Function to generate entity IDs
        """
        self._parser = parser
        self._generate_id = id_generator
        self._ast = GoAstUtils()
        self._module_name: str = ""

    def read_module_name(self, source_path: Path) -> str:
        """Read module name from go.mod file.

        Args:
            source_path: Root directory of Go source code

        Returns:
            Module name or empty string if go.mod not found
        """
        go_mod = source_path / "go.mod"
        if go_mod.exists():
            content = go_mod.read_text()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("module "):
                    return line[7:].strip()
        return ""

    def scan_directory(self, source_path: Path, module_name: str = "") -> SymbolTable:
        """Scan all Go files and build symbol table.

        Args:
            source_path: Root directory of Go source code
            module_name: Module name from go.mod (optional)

        Returns:
            SymbolTable containing all definitions
        """
        self._module_name = module_name or self.read_module_name(source_path)
        symbol_table = SymbolTable()

        for go_file in source_path.rglob("*.go"):
            # Skip test files and vendor
            if go_file.name.endswith("_test.go"):
                continue
            if "vendor" in go_file.parts:
                continue

            try:
                self._scan_file_definitions(go_file, source_path, symbol_table)
            except Exception as e:
                logger.warning(f"Failed to scan {go_file}: {e}")

        return symbol_table

    def _scan_file_definitions(
        self, file_path: Path, source_root: Path, symbol_table: SymbolTable
    ) -> None:
        """Scan a single Go file for type and function definitions.

        Args:
            file_path: Path to the Go file
            source_root: Root directory for relative path calculation
            symbol_table: Symbol table to populate
        """
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        # Extract package name
        package_name = GoAstUtils.extract_package(root, content)
        if not package_name:
            return

        # Build qualified package name
        rel_path = file_path.relative_to(source_root).parent
        rel_path_str = str(rel_path).replace("\\", "/")
        if self._module_name:
            if rel_path_str == "." or rel_path_str == "":
                qualified_pkg = self._module_name
            else:
                qualified_pkg = f"{self._module_name}/{rel_path_str}"
        else:
            qualified_pkg = str(rel_path).replace("\\", "/") or package_name

        # Register module
        symbol_table.module_map[qualified_pkg] = self._generate_id(qualified_pkg, None)

        # Scan for type and function declarations
        self._scan_declarations(root, content, qualified_pkg, symbol_table)

    def _scan_declarations(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> None:
        """Scan for type and function declarations.

        Args:
            node: Current AST node
            content: Source file content
            qualified_pkg: Qualified package name
            symbol_table: Symbol table to populate
        """
        for child in node.children:
            if child.type == "type_declaration":
                self._scan_type_declaration(child, content, qualified_pkg, symbol_table)
            elif child.type == "function_declaration":
                self._scan_function_declaration(
                    child, content, qualified_pkg, symbol_table
                )
            elif child.type == "method_declaration":
                self._scan_method_declaration(
                    child, content, qualified_pkg, symbol_table
                )

    def _scan_type_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> None:
        """Scan a type declaration for struct/interface definitions."""
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                if name_node:
                    type_name = GoAstUtils.get_node_text(name_node, content)
                    qualified_name = f"{qualified_pkg}.{type_name}"
                    symbol_table.add_type(type_name, qualified_name)

    def _scan_function_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> None:
        """Scan a function declaration."""
        name_node = node.child_by_field_name("name")
        if name_node:
            func_name = GoAstUtils.get_node_text(name_node, content)
            qualified_name = f"{qualified_pkg}.{func_name}"
            symbol_table.add_callable(func_name, qualified_name)

    def _scan_method_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> None:
        """Scan a method declaration (with receiver)."""
        name_node = node.child_by_field_name("name")
        receiver_node = node.child_by_field_name("receiver")

        if name_node and receiver_node:
            method_name = GoAstUtils.get_node_text(name_node, content)
            receiver_type = GoAstUtils.extract_receiver_type(receiver_node, content)

            if receiver_type:
                qualified_name = f"{qualified_pkg}.{receiver_type}.{method_name}"
                symbol_table.add_callable(method_name, qualified_name)
