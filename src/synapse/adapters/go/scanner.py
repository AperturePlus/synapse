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

        Files are processed in sorted order to ensure deterministic results
        regardless of filesystem traversal order (Requirement 5.3).

        Args:
            source_path: Root directory of Go source code
            module_name: Module name from go.mod (optional)

        Returns:
            SymbolTable containing all definitions
        """
        self._module_name = module_name or self.read_module_name(source_path)
        symbol_table = SymbolTable()

        # Sort files for deterministic processing order (Requirement 5.3)
        go_files = sorted(source_path.rglob("*.go"))
        for go_file in go_files:
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
                type_node = child.child_by_field_name("type")
                if name_node:
                    type_name = GoAstUtils.get_node_text(name_node, content)
                    qualified_name = f"{qualified_pkg}.{type_name}"
                    symbol_table.add_type(type_name, qualified_name)

                    # Extract embedded types for type hierarchy
                    if type_node:
                        embedded_types = self._extract_embedded_types(
                            type_node, content, qualified_pkg, symbol_table
                        )
                        if embedded_types:
                            symbol_table.add_type_hierarchy(qualified_name, embedded_types)

    def _extract_embedded_types(
        self,
        type_node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> list[str]:
        """Extract embedded types from a struct or interface definition.

        For structs, embedded types are field declarations with only a type
        (no field name). For interfaces, embedded types are type_elem nodes.

        Args:
            type_node: The struct_type or interface_type AST node
            content: Source file content
            qualified_pkg: Qualified package name for resolving local types
            symbol_table: Symbol table for type resolution

        Returns:
            List of qualified names of embedded types
        """
        embedded: list[str] = []

        if type_node.type == "struct_type":
            embedded = self._extract_struct_embeds(type_node, content, qualified_pkg, symbol_table)
        elif type_node.type == "interface_type":
            embedded = self._extract_interface_embeds(
                type_node, content, qualified_pkg, symbol_table
            )

        return embedded

    def _extract_struct_embeds(
        self,
        struct_node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> list[str]:
        """Extract embedded types from a struct definition.

        An embedded type in a struct is a field_declaration with only a type_identifier
        (no field_identifier).

        Args:
            struct_node: The struct_type AST node
            content: Source file content
            qualified_pkg: Qualified package name
            symbol_table: Symbol table for type resolution

        Returns:
            List of qualified names of embedded types
        """
        embedded: list[str] = []

        for child in struct_node.children:
            if child.type == "field_declaration_list":
                for field in child.children:
                    if field.type == "field_declaration":
                        # Check if this is an embedded type (no field name)
                        has_field_name = any(
                            c.type == "field_identifier" for c in field.children
                        )
                        if not has_field_name:
                            # This is an embedded type
                            embedded_type = self._resolve_embedded_type(
                                field, content, qualified_pkg, symbol_table
                            )
                            if embedded_type:
                                embedded.append(embedded_type)

        return embedded

    def _extract_interface_embeds(
        self,
        interface_node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> list[str]:
        """Extract embedded interfaces from an interface definition.

        An embedded interface is a type_elem node containing a type_identifier.

        Args:
            interface_node: The interface_type AST node
            content: Source file content
            qualified_pkg: Qualified package name
            symbol_table: Symbol table for type resolution

        Returns:
            List of qualified names of embedded interfaces
        """
        embedded: list[str] = []

        for child in interface_node.children:
            if child.type == "type_elem":
                # type_elem contains embedded interface references
                for type_child in child.children:
                    if type_child.type == "type_identifier":
                        type_name = GoAstUtils.get_node_text(type_child, content)
                        qualified = self._resolve_type_name(
                            type_name, qualified_pkg, symbol_table
                        )
                        if qualified:
                            embedded.append(qualified)
                    elif type_child.type == "qualified_type":
                        # Handle qualified types like pkg.Type
                        qualified = self._resolve_qualified_type(
                            type_child, content, symbol_table
                        )
                        if qualified:
                            embedded.append(qualified)

        return embedded

    def _resolve_embedded_type(
        self,
        field_node: Node,
        content: bytes,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> str | None:
        """Resolve an embedded type from a field declaration.

        Handles:
        - Simple type: `Animal`
        - Pointer type: `*Animal`
        - Qualified type: `pkg.Animal`

        Args:
            field_node: The field_declaration AST node
            content: Source file content
            qualified_pkg: Qualified package name
            symbol_table: Symbol table for type resolution

        Returns:
            Qualified name of the embedded type, or None if not resolved
        """
        for child in field_node.children:
            if child.type == "type_identifier":
                type_name = GoAstUtils.get_node_text(child, content)
                return self._resolve_type_name(type_name, qualified_pkg, symbol_table)
            elif child.type == "pointer_type":
                # Handle *Type embeds
                for ptr_child in child.children:
                    if ptr_child.type == "type_identifier":
                        type_name = GoAstUtils.get_node_text(ptr_child, content)
                        return self._resolve_type_name(type_name, qualified_pkg, symbol_table)
                    elif ptr_child.type == "qualified_type":
                        return self._resolve_qualified_type(ptr_child, content, symbol_table)
            elif child.type == "qualified_type":
                return self._resolve_qualified_type(child, content, symbol_table)

        return None

    def _resolve_type_name(
        self,
        type_name: str,
        qualified_pkg: str,
        symbol_table: SymbolTable,
    ) -> str | None:
        """Resolve a simple type name to its qualified name.

        First checks if the type exists in the same package, then falls back
        to the symbol table.

        Args:
            type_name: Simple type name
            qualified_pkg: Current package's qualified name
            symbol_table: Symbol table for type resolution

        Returns:
            Qualified name of the type, or None if not found
        """
        # First, try same package
        same_pkg_qualified = f"{qualified_pkg}.{type_name}"
        candidates = symbol_table.type_map.get(type_name, [])
        if same_pkg_qualified in candidates:
            return same_pkg_qualified

        # Fall back to first candidate if only one exists
        if len(candidates) == 1:
            return candidates[0]

        # If type not found yet, assume it's in the same package
        # (it may be defined later in the scan)
        return same_pkg_qualified

    def _resolve_qualified_type(
        self,
        qualified_node: Node,
        content: bytes,
        symbol_table: SymbolTable,
    ) -> str | None:
        """Resolve a qualified type (pkg.Type) to its qualified name.

        Args:
            qualified_node: The qualified_type AST node
            content: Source file content
            symbol_table: Symbol table for type resolution

        Returns:
            Qualified name of the type, or None if not found
        """
        # qualified_type has package and name children
        package_node = qualified_node.child_by_field_name("package")
        name_node = qualified_node.child_by_field_name("name")

        if package_node and name_node:
            pkg_name = GoAstUtils.get_node_text(package_node, content)
            type_name = GoAstUtils.get_node_text(name_node, content)

            # Look for matching qualified name in symbol table
            candidates = symbol_table.type_map.get(type_name, [])
            for candidate in candidates:
                # Check if the candidate ends with pkg.Type pattern
                if candidate.endswith(f".{type_name}") and pkg_name in candidate:
                    return candidate

        return None

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
            signature = GoAstUtils.build_signature(node, content)
            symbol_table.add_callable(func_name, qualified_name, signature=signature)

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
                signature = GoAstUtils.build_signature(node, content)
                symbol_table.add_callable(method_name, qualified_name, signature=signature)
