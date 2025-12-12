"""Java resolver for Phase 2 reference resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable as CallableFunc

from tree_sitter import Node, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.java.ast_utils import JavaAstUtils
from synapse.core.models import (
    IR,
    Callable,
    CallableKind,
    LanguageType,
    Module,
    Type,
    UnresolvedReference,
)

logger = logging.getLogger(__name__)


class JavaResolver:
    """Phase 2: Resolve references using symbol table."""

    def __init__(
        self,
        parser: Parser,
        project_id: str,
        language_type: LanguageType,
        id_generator: CallableFunc[[str, str | None], str],
    ) -> None:
        """Initialize the resolver."""
        self._parser = parser
        self._project_id = project_id
        self._language_type = language_type
        self._generate_id = id_generator
        self._ast = JavaAstUtils()

    def resolve_directory(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        """Resolve references in all Java files and return IR."""
        ir = IR(language_type=self._language_type)

        for java_file in source_path.rglob("*.java"):
            try:
                self._process_file(java_file, source_path, symbol_table, ir)
            except Exception as e:
                logger.warning(f"Failed to process {java_file}: {e}")

        return ir

    def _process_file(
        self, file_path: Path, source_root: Path, symbol_table: SymbolTable, ir: IR
    ) -> None:
        """Process a single Java file and populate IR."""
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        # Extract package and imports for file context
        package_name = JavaAstUtils.extract_package(root, content)
        imports = JavaAstUtils.extract_imports(root, content)
        file_context = FileContext(package=package_name, imports=imports)

        # Create or get module
        if package_name:
            module_id = self._generate_id(package_name, None)
            if module_id not in ir.modules:
                rel_path = file_path.relative_to(source_root).parent
                ir.modules[module_id] = Module(
                    id=module_id,
                    name=package_name.split(".")[-1],
                    qualified_name=package_name,
                    path=str(rel_path),
                    language_type=self._language_type,
                )

        # Process type declarations
        self._process_type_declarations(
            root, content, package_name, file_context, symbol_table, ir
        )

    def _process_type_declarations(
        self, node: Node, content: bytes, package_name: str, file_context: FileContext,
        symbol_table: SymbolTable, ir: IR, parent_type_id: str | None = None,
    ) -> None:
        """Process type declarations and populate IR."""
        type_declarations = (
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
        )

        for child in node.children:
            if child.type in type_declarations:
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue

                type_name = JavaAstUtils.get_node_text(name_node, content)

                # Build qualified name
                parent_qualified = None
                if parent_type_id and parent_type_id in ir.types:
                    parent_qualified = ir.types[parent_type_id].qualified_name

                if parent_qualified:
                    qualified_name = f"{parent_qualified}.{type_name}"
                elif package_name:
                    qualified_name = f"{package_name}.{type_name}"
                else:
                    qualified_name = type_name

                # Determine type kind
                kind = JavaAstUtils.get_type_kind(child.type)

                # Extract modifiers
                modifiers = JavaAstUtils.extract_modifiers(child, content)

                # Create type
                type_id = self._generate_id(qualified_name, None)
                type_obj = Type(
                    id=type_id,
                    name=type_name,
                    qualified_name=qualified_name,
                    kind=kind,
                    language_type=self._language_type,
                    modifiers=modifiers,
                )

                # Resolve extends/implements
                self._resolve_type_relations(
                    child, content, file_context, symbol_table, type_obj
                )

                ir.types[type_id] = type_obj

                # Add to module's declared_types
                if package_name:
                    module_id = self._generate_id(package_name, None)
                    if module_id in ir.modules:
                        ir.modules[module_id].declared_types.append(type_id)

                # Process methods in this type
                body_node = child.child_by_field_name("body")
                if body_node:
                    self._process_callable_declarations(
                        body_node, content, type_obj, file_context, symbol_table, ir
                    )
                    # Recursively process nested types
                    self._process_type_declarations(
                        body_node, content, package_name, file_context,
                        symbol_table, ir, type_id
                    )

            elif child.type in ("class_body", "interface_body", "enum_body"):
                self._process_type_declarations(
                    child, content, package_name, file_context,
                    symbol_table, ir, parent_type_id
                )

    def _resolve_type_relations(
        self, type_node: Node, content: bytes, file_context: FileContext,
        symbol_table: SymbolTable, type_obj: Type,
    ) -> None:
        """Resolve extends and implements relations for a type."""
        for child in type_node.children:
            if child.type == "superclass":
                # extends clause
                for type_ref in child.children:
                    if type_ref.type in ("type_identifier", "generic_type"):
                        type_name = JavaAstUtils.get_type_name(type_ref, content)
                        resolved = symbol_table.resolve_type(type_name, file_context)
                        if resolved:
                            type_obj.extends.append(self._generate_id(resolved, None))

            elif child.type == "super_interfaces":
                # implements clause
                for type_ref in child.children:
                    if type_ref.type in ("type_identifier", "generic_type", "type_list"):
                        if type_ref.type == "type_list":
                            for t in type_ref.children:
                                if t.type in ("type_identifier", "generic_type"):
                                    type_name = JavaAstUtils.get_type_name(t, content)
                                    resolved = symbol_table.resolve_type(
                                        type_name, file_context
                                    )
                                    if resolved:
                                        type_obj.implements.append(
                                            self._generate_id(resolved, None)
                                        )
                        else:
                            type_name = JavaAstUtils.get_type_name(type_ref, content)
                            resolved = symbol_table.resolve_type(type_name, file_context)
                            if resolved:
                                type_obj.implements.append(
                                    self._generate_id(resolved, None)
                                )

    def _process_callable_declarations(
        self, body_node: Node, content: bytes, owner_type: Type,
        file_context: FileContext, symbol_table: SymbolTable, ir: IR,
    ) -> None:
        """Process method and constructor declarations."""
        callable_declarations = ("method_declaration", "constructor_declaration")

        for child in body_node.children:
            if child.type in callable_declarations:
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    if child.type == "constructor_declaration":
                        name = owner_type.name
                    else:
                        continue
                else:
                    name = JavaAstUtils.get_node_text(name_node, content)

                signature = JavaAstUtils.build_signature(child, content)
                qualified_name = f"{owner_type.qualified_name}.{name}"

                # Determine callable kind
                if child.type == "constructor_declaration":
                    kind = CallableKind.CONSTRUCTOR
                else:
                    kind = CallableKind.METHOD

                # Extract visibility and static
                modifiers = JavaAstUtils.extract_modifiers(child, content)
                visibility = JavaAstUtils.get_visibility(modifiers)
                is_static = "static" in modifiers

                # Get return type
                return_type_id = None
                if child.type == "method_declaration":
                    return_type_node = child.child_by_field_name("type")
                    if return_type_node and return_type_node.type != "void_type":
                        type_name = JavaAstUtils.get_type_name(return_type_node, content)
                        resolved = symbol_table.resolve_type(type_name, file_context)
                        if resolved:
                            return_type_id = self._generate_id(resolved, None)

                callable_id = self._generate_id(qualified_name, signature)
                callable_obj = Callable(
                    id=callable_id,
                    name=name,
                    qualified_name=qualified_name,
                    kind=kind,
                    language_type=self._language_type,
                    signature=signature,
                    is_static=is_static,
                    visibility=visibility,
                    return_type=return_type_id,
                )

                # Find method calls in body
                method_body = child.child_by_field_name("body")
                if method_body:
                    self._find_method_calls(
                        method_body, content, file_context, symbol_table,
                        callable_obj, ir
                    )

                ir.callables[callable_id] = callable_obj
                owner_type.callables.append(callable_id)

    def _find_method_calls(
        self, node: Node, content: bytes, file_context: FileContext,
        symbol_table: SymbolTable, caller: Callable, ir: IR,
    ) -> None:
        """Find method invocations in a code block (heuristic linking)."""
        if node.type == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node:
                method_name = JavaAstUtils.get_node_text(name_node, content)

                # Try to resolve the method
                resolved = symbol_table.resolve_callable(method_name)
                if resolved:
                    # Use first match (heuristic)
                    callee_id = self._generate_id(
                        resolved, self._infer_signature(node, content)
                    )
                    if callee_id not in caller.calls:
                        caller.calls.append(callee_id)
                else:
                    # Record as unresolved
                    ir.unresolved.append(UnresolvedReference(
                        source_callable=caller.id,
                        target_name=method_name,
                        reason="Method not found in symbol table",
                    ))

        # Recurse into children
        for child in node.children:
            self._find_method_calls(
                child, content, file_context, symbol_table, caller, ir
            )

    def _infer_signature(self, invocation_node: Node, content: bytes) -> str:
        """Infer signature from method invocation arguments (simplified)."""
        args_node = invocation_node.child_by_field_name("arguments")
        if args_node is None:
            return "()"

        # Count arguments (simplified - doesn't infer types)
        arg_count = sum(
            1 for c in args_node.children
            if c.type not in ("(", ")", ",")
        )
        return f"({', '.join(['?'] * arg_count)})"
