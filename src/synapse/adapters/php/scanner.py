"""PHP scanner for Phase 1 symbol table construction."""

from __future__ import annotations

import logging
from pathlib import Path

from tree_sitter import Node, Parser

from synapse.adapters.base import SymbolTable
from synapse.adapters.php.ast_utils import PhpAstUtils

logger = logging.getLogger(__name__)


class PhpScanner:
    """Phase 1: Scan PHP files to build symbol table."""

    def __init__(self, parser: Parser) -> None:
        self._parser = parser

    def scan_directory(self, source_path: Path) -> SymbolTable:
        symbol_table = SymbolTable()

        php_files = sorted(source_path.rglob("*.php"))
        for php_file in php_files:
            try:
                self._scan_file_definitions(php_file, symbol_table)
            except Exception as exc:
                logger.warning(f"Failed to scan {php_file}: {exc}")

        return symbol_table

    def _scan_file_definitions(self, file_path: Path, symbol_table: SymbolTable) -> None:
        content = file_path.read_bytes()
        tree = self._parser.parse(content)
        root = tree.root_node

        namespace = PhpAstUtils.extract_namespace(root, content)
        self._scan_declarations(root, content, namespace, symbol_table)

    def _scan_declarations(
        self, node: Node, content: bytes, namespace: str, symbol_table: SymbolTable
    ) -> None:
        for child in node.named_children:
            if child.type in ("class_declaration", "interface_declaration", "trait_declaration"):
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                type_name = PhpAstUtils.get_node_text(name_node, content)
                qualified = f"{namespace}.{type_name}" if namespace else type_name
                symbol_table.add_type(type_name, qualified)

                body = child.child_by_field_name("body")
                if body:
                    self._scan_methods(body, content, qualified, symbol_table)
                continue

            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                func_name = PhpAstUtils.get_node_text(name_node, content)
                qualified = f"{namespace}.{func_name}" if namespace else func_name
                signature = PhpAstUtils.build_signature(child, content)
                symbol_table.add_callable(func_name, qualified, signature=signature)
                continue

            # Recurse for multiple declarations per file
            self._scan_declarations(child, content, namespace, symbol_table)

    def _scan_methods(
        self, body_node: Node, content: bytes, owner_qname: str, symbol_table: SymbolTable
    ) -> None:
        for child in body_node.named_children:
            if child.type != "method_declaration":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            name = PhpAstUtils.get_node_text(name_node, content)
            signature = PhpAstUtils.build_signature(child, content)
            qualified = f"{owner_qname}.{name}"
            symbol_table.add_callable(name, qualified, signature=signature)

