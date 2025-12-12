"""Go resolver for Phase 2 reference resolution.

This module resolves references in Go source files using the symbol table
built in Phase 1.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable as CallableFunc

from tree_sitter import Node, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.go.ast_utils import GoAstUtils
from synapse.core.models import (
    IR,
    Callable,
    CallableKind,
    LanguageType,
    Module,
    Type,
    TypeKind,
    UnresolvedReference,
    Visibility,
)

logger = logging.getLogger(__name__)


class GoResolver:
    """Phase 2: Resolve references using symbol table."""

    def __init__(
        self,
        parser: Parser,
        project_id: str,
        language_type: LanguageType,
        id_generator: CallableFunc[[str, str | None], str],
    ) -> None:
        """Initialize the resolver.

        Args:
            parser: Configured tree-sitter parser for Go
            project_id: The project identifier
            language_type: The language type (GO)
            id_generator: Function to generate entity IDs
        """
        self._parser = parser
        self._project_id = project_id
        self._language_type = language_type
        self._generate_id = id_generator
        self._ast = GoAstUtils()
        self._module_name: str = ""

    def resolve_directory(
        self, source_path: Path, symbol_table: SymbolTable, module_name: str = ""
    ) -> IR:
        """Resolve references in all Go files and return IR.

        Args:
            source_path: Root directory of Go source code
            symbol_table: Symbol table from Phase 1
            module_name: Module name from go.mod

        Returns:
            IR with resolved references
        """
        self._module_name = module_name
        ir = IR(language_type=self._language_type)

        for go_file in source_path.rglob("*.go"):
            if go_file.name.endswith("_test.go"):
                continue
            if "vendor" in go_file.parts:
                continue

            try:
                self._process_file(go_file, source_path, symbol_table, ir)
            except Exception as e:
                logger.warning(f"Failed to process {go_file}: {e}")

        return ir

    def _process_file(
        self,
        file_path: Path,
        source_root: Path,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a single Go file and populate IR.

        Args:
            file_path: Path to the Go file
            source_root: Root directory for relative path calculation
            symbol_table: Symbol table from Phase 1
            ir: IR to populate
        """
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        # Extract package name and build qualified name
        package_name = GoAstUtils.extract_package(root, content)
        if not package_name:
            return

        rel_path = file_path.relative_to(source_root).parent
        rel_path_str = str(rel_path).replace("\\", "/")
        if self._module_name:
            if rel_path_str == "." or rel_path_str == "":
                qualified_pkg = self._module_name
            else:
                qualified_pkg = f"{self._module_name}/{rel_path_str}"
        else:
            qualified_pkg = rel_path_str or package_name

        # Extract imports for file context
        imports = GoAstUtils.extract_imports(root, content)
        file_context = FileContext(package=qualified_pkg, imports=imports)

        # Create or get module
        module_id = self._generate_id(qualified_pkg, None)
        if module_id not in ir.modules:
            ir.modules[module_id] = Module(
                id=module_id,
                name=package_name,
                qualified_name=qualified_pkg,
                path=rel_path_str or ".",
                language_type=self._language_type,
            )

        # Process declarations
        self._process_declarations(
            root, content, qualified_pkg, file_context, symbol_table, ir
        )

    def _process_declarations(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process type and function declarations.

        Args:
            node: Current AST node
            content: Source file content
            qualified_pkg: Qualified package name
            file_context: File context for symbol resolution
            symbol_table: Symbol table from Phase 1
            ir: IR to populate
        """
        for child in node.children:
            if child.type == "type_declaration":
                self._process_type_declaration(
                    child, content, qualified_pkg, file_context, symbol_table, ir
                )
            elif child.type == "function_declaration":
                self._process_function_declaration(
                    child, content, qualified_pkg, file_context, symbol_table, ir
                )
            elif child.type == "method_declaration":
                self._process_method_declaration(
                    child, content, qualified_pkg, file_context, symbol_table, ir
                )

    def _process_type_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a type declaration and create Type nodes."""
        for child in node.children:
            if child.type == "type_spec":
                name_node = child.child_by_field_name("name")
                type_node = child.child_by_field_name("type")

                if not name_node:
                    continue

                type_name = GoAstUtils.get_node_text(name_node, content)
                qualified_name = f"{qualified_pkg}.{type_name}"

                # Determine type kind
                kind = TypeKind.STRUCT
                if type_node:
                    if type_node.type == "interface_type":
                        kind = TypeKind.INTERFACE
                    elif type_node.type == "struct_type":
                        kind = TypeKind.STRUCT

                # Determine visibility (exported if starts with uppercase)
                visibility = (
                    Visibility.PUBLIC if type_name[0].isupper() else Visibility.PACKAGE
                )

                type_id = self._generate_id(qualified_name, None)
                type_obj = Type(
                    id=type_id,
                    name=type_name,
                    qualified_name=qualified_name,
                    kind=kind,
                    language_type=self._language_type,
                    modifiers=["exported"] if visibility == Visibility.PUBLIC else [],
                )

                # Process struct embeds
                if type_node and type_node.type == "struct_type":
                    self._process_struct_embeds(
                        type_node, content, file_context, symbol_table, type_obj
                    )

                ir.types[type_id] = type_obj

                # Add to module's declared_types
                module_id = self._generate_id(qualified_pkg, None)
                if module_id in ir.modules:
                    ir.modules[module_id].declared_types.append(type_id)

    def _process_struct_embeds(
        self,
        struct_node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        type_obj: Type,
    ) -> None:
        """Process struct field declarations to find embedded types."""
        for child in struct_node.children:
            if child.type == "field_declaration_list":
                for field in child.children:
                    if field.type == "field_declaration":
                        # Check if this is an embedded field (no name, just type)
                        name_nodes = [
                            c for c in field.children if c.type == "field_identifier"
                        ]
                        type_node = field.child_by_field_name("type")

                        if not name_nodes and type_node:
                            # This is an embedded type
                            embedded_type_name = GoAstUtils.get_base_type_name(
                                type_node, content
                            )
                            resolved = symbol_table.resolve_type(
                                embedded_type_name, file_context
                            )
                            if resolved:
                                type_obj.embeds.append(
                                    self._generate_id(resolved, None)
                                )

    def _process_function_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a function declaration."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        func_name = GoAstUtils.get_node_text(name_node, content)
        qualified_name = f"{qualified_pkg}.{func_name}"
        signature = GoAstUtils.build_signature(node, content)

        visibility = (
            Visibility.PUBLIC if func_name[0].isupper() else Visibility.PACKAGE
        )

        callable_id = self._generate_id(qualified_name, signature)
        callable_obj = Callable(
            id=callable_id,
            name=func_name,
            qualified_name=qualified_name,
            kind=CallableKind.FUNCTION,
            language_type=self._language_type,
            signature=signature,
            is_static=True,  # Go functions are essentially static
            visibility=visibility,
        )

        # Get return type
        result_node = node.child_by_field_name("result")
        if result_node:
            return_type_name = GoAstUtils.get_base_type_name(result_node, content)
            resolved = symbol_table.resolve_type(return_type_name, file_context)
            if resolved:
                callable_obj.return_type = self._generate_id(resolved, None)

        # Find function calls in body
        body_node = node.child_by_field_name("body")
        if body_node:
            self._find_function_calls(
                body_node, content, file_context, symbol_table, callable_obj, ir
            )

        ir.callables[callable_id] = callable_obj

    def _process_method_declaration(
        self,
        node: Node,
        content: bytes,
        qualified_pkg: str,
        file_context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        """Process a method declaration (with receiver)."""
        name_node = node.child_by_field_name("name")
        receiver_node = node.child_by_field_name("receiver")

        if not name_node or not receiver_node:
            return

        method_name = GoAstUtils.get_node_text(name_node, content)
        receiver_type = GoAstUtils.extract_receiver_type(receiver_node, content)

        if not receiver_type:
            return

        qualified_name = f"{qualified_pkg}.{receiver_type}.{method_name}"
        signature = GoAstUtils.build_signature(node, content)

        visibility = (
            Visibility.PUBLIC if method_name[0].isupper() else Visibility.PACKAGE
        )

        callable_id = self._generate_id(qualified_name, signature)
        callable_obj = Callable(
            id=callable_id,
            name=method_name,
            qualified_name=qualified_name,
            kind=CallableKind.METHOD,
            language_type=self._language_type,
            signature=signature,
            is_static=False,
            visibility=visibility,
        )

        # Get return type
        result_node = node.child_by_field_name("result")
        if result_node:
            return_type_name = GoAstUtils.get_base_type_name(result_node, content)
            resolved = symbol_table.resolve_type(return_type_name, file_context)
            if resolved:
                callable_obj.return_type = self._generate_id(resolved, None)

        # Find function calls in body
        body_node = node.child_by_field_name("body")
        if body_node:
            self._find_function_calls(
                body_node, content, file_context, symbol_table, callable_obj, ir
            )

        ir.callables[callable_id] = callable_obj

        # Add to owner type's callables
        owner_qualified = f"{qualified_pkg}.{receiver_type}"
        owner_id = self._generate_id(owner_qualified, None)
        if owner_id in ir.types:
            ir.types[owner_id].callables.append(callable_id)

    def _find_function_calls(
        self,
        node: Node,
        content: bytes,
        file_context: FileContext,
        symbol_table: SymbolTable,
        caller: Callable,
        ir: IR,
    ) -> None:
        """Find function/method calls in a code block (heuristic linking)."""
        if node.type == "call_expression":
            func_node = node.child_by_field_name("function")
            if func_node:
                if func_node.type == "identifier":
                    # Simple function call
                    func_name = GoAstUtils.get_node_text(func_node, content)
                    resolved = symbol_table.resolve_callable(func_name)
                    if resolved:
                        callee_id = self._generate_id(resolved, "()")
                        if callee_id not in caller.calls:
                            caller.calls.append(callee_id)
                    else:
                        ir.unresolved.append(UnresolvedReference(
                            source_callable=caller.id,
                            target_name=func_name,
                            reason="Function not found in symbol table",
                        ))
                elif func_node.type == "selector_expression":
                    # Method call or package.function call
                    field_node = func_node.child_by_field_name("field")
                    if field_node:
                        method_name = GoAstUtils.get_node_text(field_node, content)
                        resolved = symbol_table.resolve_callable(method_name)
                        if resolved:
                            callee_id = self._generate_id(resolved, "()")
                            if callee_id not in caller.calls:
                                caller.calls.append(callee_id)
                        # Don't mark as unresolved - could be external package

        # Recurse into children
        for child in node.children:
            self._find_function_calls(
                child, content, file_context, symbol_table, caller, ir
            )
