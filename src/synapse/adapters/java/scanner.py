"""Java scanner for Phase 1 symbol table construction.

This module scans Java source files to build a symbol table
containing all type and callable definitions.
"""

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Node, Parser

from synapse.adapters.base import SymbolTable
from synapse.adapters.java.ast_utils import JavaAstUtils

logger = logging.getLogger(__name__)


class JavaScanner:
    """Phase 1: Scan Java files to build symbol table.

    Collects all type and method definitions without resolving references.
    """

    def __init__(self, parser: Parser) -> None:
        """Initialize the scanner.

        Args:
            parser: Configured tree-sitter parser for Java
        """
        self._parser = parser
        self._ast = JavaAstUtils()

    def scan_directory(self, source_path: Path) -> SymbolTable:
        """Scan all Java files and build symbol table.

        Args:
            source_path: Root directory of Java source code

        Returns:
            SymbolTable containing all definitions
        """
        symbol_table = SymbolTable()

        for java_file in source_path.rglob("*.java"):
            try:
                self._scan_file_definitions(java_file, source_path, symbol_table)
            except Exception as e:
                logger.warning(f"Failed to scan {java_file}: {e}")

        return symbol_table

    def _scan_file_definitions(
        self, file_path: Path, source_root: Path, symbol_table: SymbolTable
    ) -> None:
        """Scan a single Java file for type and method definitions.

        Args:
            file_path: Path to the Java file
            source_root: Root directory for relative path calculation
            symbol_table: Symbol table to populate
        """
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        # Extract package declaration
        package_name = JavaAstUtils.extract_package(root, content)

        # Scan for class/interface/enum declarations
        self._scan_type_declarations(root, content, package_name, symbol_table)

    def _scan_type_declarations(
        self,
        node: Node,
        content: bytes,
        package_name: str,
        symbol_table: SymbolTable,
        parent_type: str | None = None,
    ) -> None:
        """Recursively scan for type declarations.

        Args:
            node: Current AST node
            content: Source file content
            package_name: Current package name
            symbol_table: Symbol table to populate
            parent_type: Parent type's qualified name (for nested types)
        """
        type_declarations = (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        )

        for child in node.children:
            if child.type in type_declarations:
                # Skip anonymous classes
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue

                type_name = JavaAstUtils.get_node_text(name_node, content)

                # Build qualified name
                if parent_type:
                    qualified_name = f"{parent_type}.{type_name}"
                elif package_name:
                    qualified_name = f"{package_name}.{type_name}"
                else:
                    qualified_name = type_name

                # Register type in symbol table
                symbol_table.add_type(type_name, qualified_name)

                # Scan for methods in this type
                body_node = child.child_by_field_name("body")
                if body_node:
                    self._scan_callable_declarations(
                        body_node, content, qualified_name, symbol_table
                    )
                    # Recursively scan for nested types
                    self._scan_type_declarations(
                        body_node, content, package_name, symbol_table, qualified_name
                    )

            elif child.type in ("class_body", "interface_body", "enum_body"):
                # Continue scanning inside bodies
                self._scan_type_declarations(
                    child, content, package_name, symbol_table, parent_type
                )

    def _scan_callable_declarations(
        self,
        body_node: Node,
        content: bytes,
        owner_qualified_name: str,
        symbol_table: SymbolTable,
    ) -> None:
        """Scan for method and constructor declarations in a type body.

        Args:
            body_node: The class/interface body node
            content: Source file content
            owner_qualified_name: The owning type's qualified name
            symbol_table: Symbol table to populate
        """
        callable_declarations = (
            "method_declaration",
            "constructor_declaration",
        )

        for child in body_node.children:
            if child.type in callable_declarations:
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    # Constructor uses type name
                    if child.type == "constructor_declaration":
                        # Get the simple name from qualified name
                        name = owner_qualified_name.split(".")[-1]
                    else:
                        continue
                else:
                    name = JavaAstUtils.get_node_text(name_node, content)

                # Build signature
                signature = JavaAstUtils.build_signature(child, content)
                qualified_name = f"{owner_qualified_name}.{name}"

                # Get return type for methods
                return_type = None
                if child.type == "method_declaration":
                    return_type_node = child.child_by_field_name("type")
                    if return_type_node and return_type_node.type != "void_type":
                        return_type = JavaAstUtils.get_type_name(return_type_node, content)

                # Register callable in symbol table with signature
                symbol_table.add_callable(
                    name, qualified_name, return_type=return_type, signature=signature
                )
