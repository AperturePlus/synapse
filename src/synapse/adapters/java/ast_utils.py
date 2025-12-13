"""Java AST utility functions.

This module provides utility functions for extracting information
from tree-sitter AST nodes for Java source code.
"""

from __future__ import annotations

from tree_sitter import Node

from synapse.core.models import TypeKind, Visibility


class JavaAstUtils:
    """Java AST utility functions for tree-sitter nodes."""

    @staticmethod
    def get_node_text(node: Node, content: bytes) -> str:
        """Get the text content of a node.

        Args:
            node: The AST node
            content: Source file content

        Returns:
            The text content of the node
        """
        return content[node.start_byte:node.end_byte].decode("utf-8")

    @staticmethod
    def get_type_name(type_node: Node, content: bytes) -> str:
        """Extract type name from a type node.

        Args:
            type_node: The type AST node
            content: Source file content

        Returns:
            Simple type name (without generics)
        """
        if type_node.type == "type_identifier":
            return JavaAstUtils.get_node_text(type_node, content)
        elif type_node.type == "generic_type":
            # Get base type without generics
            for child in type_node.children:
                if child.type == "type_identifier":
                    return JavaAstUtils.get_node_text(child, content)
        elif type_node.type == "array_type":
            element_type = type_node.child_by_field_name("element")
            if element_type:
                return JavaAstUtils.get_type_name(element_type, content) + "[]"
        elif type_node.type in ("integral_type", "floating_point_type", "boolean_type"):
            return JavaAstUtils.get_node_text(type_node, content)
        elif type_node.type == "void_type":
            return "void"
        elif type_node.type == "scoped_type_identifier":
            return JavaAstUtils.get_node_text(type_node, content)

        return JavaAstUtils.get_node_text(type_node, content)

    @staticmethod
    def extract_package(root: Node, content: bytes) -> str:
        """Extract package name from the AST.

        Args:
            root: Root node of the AST
            content: Source file content

        Returns:
            Package name or empty string if no package declaration
        """
        for child in root.children:
            if child.type == "package_declaration":
                # Find the scoped_identifier or identifier
                for node in child.children:
                    if node.type in ("scoped_identifier", "identifier"):
                        return JavaAstUtils.get_node_text(node, content)
        return ""

    @staticmethod
    def extract_imports(root: Node, content: bytes) -> list[str]:
        """Extract import statements from the AST.

        Args:
            root: Root node of the AST
            content: Source file content

        Returns:
            List of import statements
        """
        imports: list[str] = []
        for child in root.children:
            if child.type == "import_declaration":
                # Find the scoped_identifier
                for node in child.children:
                    if node.type in ("scoped_identifier", "identifier"):
                        import_text = JavaAstUtils.get_node_text(node, content)
                        # Check for wildcard import
                        if any(c.type == "asterisk" for c in child.children):
                            import_text += ".*"
                        imports.append(import_text)
                        break
        return imports

    @staticmethod
    def extract_modifiers(node: Node, content: bytes) -> list[str]:
        """Extract modifiers from a declaration node.

        Args:
            node: The declaration AST node
            content: Source file content (unused but kept for consistency)

        Returns:
            List of modifier strings
        """
        modifiers: list[str] = []
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type in (
                        "public", "private", "protected", "static",
                        "final", "abstract", "synchronized", "native",
                    ):
                        modifiers.append(mod.type)
        return modifiers

    @staticmethod
    def build_signature(callable_node: Node, content: bytes) -> str:
        """Build a method signature from parameters.

        Args:
            callable_node: The method/constructor declaration node
            content: Source file content

        Returns:
            Signature string like "(String, int)"
        """
        params_node = callable_node.child_by_field_name("parameters")
        if params_node is None:
            return "()"

        param_types: list[str] = []
        for child in params_node.children:
            if child.type == "formal_parameter":
                type_node = child.child_by_field_name("type")
                if type_node:
                    param_types.append(JavaAstUtils.get_type_name(type_node, content))
            elif child.type == "spread_parameter":
                # spread_parameter doesn't have a 'type' field - type is a direct child
                type_node = child.child_by_field_name("type")
                if type_node is None:
                    # Find type in children
                    for subchild in child.children:
                        if subchild.type in (
                            "integral_type", "floating_point_type", "boolean_type",
                            "type_identifier", "generic_type", "array_type",
                            "scoped_type_identifier",
                        ):
                            type_node = subchild
                            break
                if type_node:
                    param_types.append(
                        JavaAstUtils.get_type_name(type_node, content) + "..."
                    )

        return f"({', '.join(param_types)})"

    @staticmethod
    def get_type_kind(node_type: str) -> TypeKind:
        """Map AST node type to TypeKind.

        Args:
            node_type: The AST node type string

        Returns:
            Corresponding TypeKind enum value
        """
        mapping = {
            "class_declaration": TypeKind.CLASS,
            "interface_declaration": TypeKind.INTERFACE,
            "enum_declaration": TypeKind.ENUM,
            "record_declaration": TypeKind.CLASS,
        }
        return mapping.get(node_type, TypeKind.CLASS)

    @staticmethod
    def get_visibility(modifiers: list[str]) -> Visibility:
        """Determine visibility from modifiers.

        Args:
            modifiers: List of modifier strings

        Returns:
            Visibility enum value
        """
        if "public" in modifiers:
            return Visibility.PUBLIC
        elif "private" in modifiers:
            return Visibility.PRIVATE
        elif "protected" in modifiers:
            return Visibility.PROTECTED
        return Visibility.PACKAGE
