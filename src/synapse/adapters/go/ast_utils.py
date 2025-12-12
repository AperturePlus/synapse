"""Go AST utility functions.

This module provides utility functions for extracting information
from tree-sitter AST nodes for Go source code.
"""

from __future__ import annotations

from tree_sitter import Node


class GoAstUtils:
    """Go AST utility functions for tree-sitter nodes."""

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
    def get_base_type_name(type_node: Node, content: bytes) -> str:
        """Get the base type name, stripping pointers.

        Args:
            type_node: The type AST node
            content: Source file content

        Returns:
            The base type name
        """
        if type_node.type == "pointer_type":
            for child in type_node.children:
                if child.type == "type_identifier":
                    return GoAstUtils.get_node_text(child, content)
        elif type_node.type == "type_identifier":
            return GoAstUtils.get_node_text(type_node, content)
        return GoAstUtils.get_node_text(type_node, content)

    @staticmethod
    def extract_package(root: Node, content: bytes) -> str:
        """Extract package name from the AST.

        Args:
            root: Root node of the AST
            content: Source file content

        Returns:
            Package name or empty string
        """
        for child in root.children:
            if child.type == "package_clause":
                for node in child.children:
                    if node.type == "package_identifier":
                        return GoAstUtils.get_node_text(node, content)
        return ""

    @staticmethod
    def extract_imports(root: Node, content: bytes) -> list[str]:
        """Extract import statements from the AST.

        Args:
            root: Root node of the AST
            content: Source file content

        Returns:
            List of import paths
        """
        imports: list[str] = []
        for child in root.children:
            if child.type == "import_declaration":
                for spec in child.children:
                    if spec.type == "import_spec":
                        path_node = spec.child_by_field_name("path")
                        if path_node:
                            # Remove quotes from import path
                            import_path = GoAstUtils.get_node_text(path_node, content)
                            imports.append(import_path.strip('"'))
                    elif spec.type == "import_spec_list":
                        for inner_spec in spec.children:
                            if inner_spec.type == "import_spec":
                                path_node = inner_spec.child_by_field_name("path")
                                if path_node:
                                    import_path = GoAstUtils.get_node_text(
                                        path_node, content
                                    )
                                    imports.append(import_path.strip('"'))
        return imports

    @staticmethod
    def extract_receiver_type(receiver_node: Node, content: bytes) -> str | None:
        """Extract the receiver type name from a method receiver.

        Args:
            receiver_node: The receiver parameter list node
            content: Source file content

        Returns:
            The receiver type name (without pointer)
        """
        for child in receiver_node.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node:
                    return GoAstUtils.get_base_type_name(type_node, content)
        return None

    @staticmethod
    def build_signature(node: Node, content: bytes) -> str:
        """Build a function/method signature from parameters.

        Args:
            node: The function/method declaration node
            content: Source file content

        Returns:
            Signature string like "(string, int)"
        """
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return "()"

        param_types: list[str] = []
        for child in params_node.children:
            if child.type == "parameter_declaration":
                type_node = child.child_by_field_name("type")
                if type_node:
                    param_types.append(GoAstUtils.get_base_type_name(type_node, content))

        return f"({', '.join(param_types)})"
