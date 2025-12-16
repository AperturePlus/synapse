"""PHP resolver for Phase 2 IR construction."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable as CallableFunc

from tree_sitter import Node, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.php.ast_utils import PhpAstUtils
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


class PhpResolver:
    """Phase 2: Build IR and resolve basic references."""

    def __init__(
        self,
        parser: Parser,
        project_id: str,
        language_type: LanguageType,
        id_generator: CallableFunc[[str, str | None], str],
    ) -> None:
        self._parser = parser
        self._project_id = project_id
        self._language_type = language_type
        self._generate_id = id_generator

    def resolve_directory(self, source_path: Path, symbol_table: SymbolTable) -> IR:
        ir = IR(language_type=self._language_type)

        php_files = sorted(source_path.rglob("*.php"))
        for php_file in php_files:
            try:
                self._process_file(php_file, source_path, symbol_table, ir)
            except Exception as exc:
                logger.warning(f"Failed to process {php_file}: {exc}")

        return ir

    def _process_file(
        self, file_path: Path, source_root: Path, symbol_table: SymbolTable, ir: IR
    ) -> None:
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        namespace = PhpAstUtils.extract_namespace(root, content)
        use_map = PhpAstUtils.extract_use_map(root, content)
        imports = sorted(set(use_map.values()))
        context = FileContext(package=namespace, imports=imports, local_types=use_map)

        # Create module for namespace
        module_id = None
        if namespace:
            module_id = self._generate_id(namespace, None)
            if module_id not in ir.modules:
                rel_path = file_path.relative_to(source_root).parent
                ir.modules[module_id] = Module(
                    id=module_id,
                    name=namespace.split(".")[-1],
                    qualified_name=namespace,
                    path=str(rel_path),
                    language_type=self._language_type,
                )

        self._process_declarations(root, content, context, symbol_table, ir, module_id)

    def _process_declarations(
        self,
        node: Node,
        content: bytes,
        context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
        module_id: str | None,
    ) -> None:
        for child in node.named_children:
            if child.type in ("class_declaration", "interface_declaration", "trait_declaration"):
                self._process_type(child, content, context, symbol_table, ir, module_id)
                continue

            if child.type == "function_definition":
                self._process_function(child, content, context, symbol_table, ir)
                continue

            self._process_declarations(child, content, context, symbol_table, ir, module_id)

    def _process_type(
        self,
        type_node: Node,
        content: bytes,
        context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
        module_id: str | None,
    ) -> None:
        name_node = type_node.child_by_field_name("name")
        if name_node is None:
            return
        type_name = PhpAstUtils.get_node_text(name_node, content)
        qualified_name = f"{context.package}.{type_name}" if context.package else type_name

        type_id = self._generate_id(qualified_name, None)
        typ = Type(
            id=type_id,
            name=type_name,
            qualified_name=qualified_name,
            kind=PhpAstUtils.get_type_kind(type_node.type),
            language_type=self._language_type,
            modifiers=PhpAstUtils.extract_modifiers(type_node, content),
        )

        # extends / implements
        for named in type_node.named_children:
            if named.type == "base_clause":
                for name_child in named.named_children:
                    if name_child.type != "name":
                        continue
                    base_name = PhpAstUtils.get_node_text(name_child, content)
                    resolved = symbol_table.resolve_type(base_name, context)
                    if resolved:
                        typ.extends.append(self._generate_id(resolved, None))
            if named.type == "class_interface_clause":
                for name_child in named.named_children:
                    if name_child.type != "name":
                        continue
                    iface_name = PhpAstUtils.get_node_text(name_child, content)
                    resolved = symbol_table.resolve_type(iface_name, context)
                    if resolved:
                        typ.implements.append(self._generate_id(resolved, None))

        ir.types[type_id] = typ
        if module_id and module_id in ir.modules:
            ir.modules[module_id].declared_types.append(type_id)

        body = type_node.child_by_field_name("body")
        if body:
            self._process_methods(body, content, typ, context, symbol_table, ir)

    def _process_methods(
        self,
        body_node: Node,
        content: bytes,
        owner_type: Type,
        context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        for child in body_node.named_children:
            if child.type != "method_declaration":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            name = PhpAstUtils.get_node_text(name_node, content)

            signature = PhpAstUtils.build_signature(child, content)
            qualified_name = f"{owner_type.qualified_name}.{name}"

            kind = CallableKind.CONSTRUCTOR if name == "__construct" else CallableKind.METHOD
            modifiers = PhpAstUtils.extract_modifiers(child, content)
            visibility = PhpAstUtils.get_visibility(modifiers)
            is_static = "static" in modifiers

            callable_id = self._generate_id(qualified_name, signature)
            ir.callables[callable_id] = Callable(
                id=callable_id,
                name=name,
                qualified_name=qualified_name,
                kind=kind,
                language_type=self._language_type,
                signature=signature,
                is_static=is_static,
                visibility=visibility,
            )
            owner_type.callables.append(callable_id)

            # Best-effort: PHP call resolution is not implemented yet.
            # Record a placeholder for dynamic frameworks if needed.
            if name == "__call":
                ir.unresolved.append(
                    UnresolvedReference(
                        source_callable=callable_id,
                        target_name="*",
                        context="__call dynamic dispatch",
                        reason="Dynamic method dispatch in PHP",
                    )
                )

    def _process_function(
        self,
        func_node: Node,
        content: bytes,
        context: FileContext,
        symbol_table: SymbolTable,
        ir: IR,
    ) -> None:
        name_node = func_node.child_by_field_name("name")
        if name_node is None:
            return
        name = PhpAstUtils.get_node_text(name_node, content)
        signature = PhpAstUtils.build_signature(func_node, content)
        qualified_name = f"{context.package}.{name}" if context.package else name
        callable_id = self._generate_id(qualified_name, signature)

        ir.callables[callable_id] = Callable(
            id=callable_id,
            name=name,
            qualified_name=qualified_name,
            kind=CallableKind.FUNCTION,
            language_type=self._language_type,
            signature=signature,
            is_static=False,
            visibility=PhpAstUtils.get_visibility([]),
        )

