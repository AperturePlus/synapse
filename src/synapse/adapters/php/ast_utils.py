"""PHP AST utility helpers."""

from __future__ import annotations

from tree_sitter import Node

from synapse.core.models import TypeKind, Visibility


class PhpAstUtils:
    """Utility helpers for tree-sitter-php nodes."""

    @staticmethod
    def get_node_text(node: Node, content: bytes) -> str:
        return content[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")

    @staticmethod
    def extract_namespace(root: Node, content: bytes) -> str:
        for child in root.named_children:
            if child.type != "namespace_definition":
                continue
            name_node = child.child_by_field_name("name")
            if name_node is None:
                return ""
            parts = [
                PhpAstUtils.get_node_text(n, content)
                for n in name_node.named_children
                if n.type == "name"
            ]
            return ".".join(parts)
        return ""

    @staticmethod
    def extract_use_map(root: Node, content: bytes) -> dict[str, str]:
        """Extract `use ...` aliases as {short_name: qualified_name} (dot-separated)."""
        use_map: dict[str, str] = {}
        for child in root.named_children:
            if child.type != "namespace_use_declaration":
                continue
            for clause in child.named_children:
                if clause.type != "namespace_use_clause":
                    continue
                qn = next((c for c in clause.named_children if c.type == "qualified_name"), None)
                if qn is None:
                    continue
                qualified = PhpAstUtils.get_node_text(qn, content).replace("\\\\", ".")
                alias_node = next((c for c in clause.named_children if c.type == "name"), None)
                short = (
                    PhpAstUtils.get_node_text(alias_node, content)
                    if alias_node is not None
                    else qualified.split(".")[-1]
                )
                use_map[short] = qualified
        return use_map

    @staticmethod
    def get_type_kind(node_type: str) -> TypeKind:
        mapping = {
            "class_declaration": TypeKind.CLASS,
            "interface_declaration": TypeKind.INTERFACE,
            "trait_declaration": TypeKind.TRAIT,
        }
        return mapping.get(node_type, TypeKind.CLASS)

    @staticmethod
    def extract_modifiers(node: Node, content: bytes) -> list[str]:
        modifiers: list[str] = []
        for child in node.children:
            if child.type == "visibility_modifier":
                modifiers.append(PhpAstUtils.get_node_text(child, content))
            elif child.type in ("static_modifier", "abstract_modifier", "final_modifier"):
                modifiers.append(child.type.replace("_modifier", ""))
        return modifiers

    @staticmethod
    def get_visibility(modifiers: list[str]) -> Visibility:
        if "private" in modifiers:
            return Visibility.PRIVATE
        if "protected" in modifiers:
            return Visibility.PROTECTED
        return Visibility.PUBLIC

    @staticmethod
    def build_signature(callable_node: Node, content: bytes) -> str:
        params = callable_node.child_by_field_name("parameters")
        if params is None:
            return "()"

        param_types: list[str] = []
        for p in params.named_children:
            if p.type != "simple_parameter":
                continue
            type_node = p.child_by_field_name("type")
            if type_node is None:
                param_types.append("?")
                continue
            type_text = PhpAstUtils.get_node_text(type_node, content)
            type_text = type_text.replace("\\\\", ".").lstrip("?")
            param_types.append(type_text if type_text else "?")

        return f"({', '.join(param_types)})"

