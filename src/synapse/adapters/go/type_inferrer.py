"""Go type inference for method call resolution.

This module provides the GoTypeInferrer class that infers types from Go AST
expression nodes, enabling accurate method call resolution by determining
receiver types at call sites.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tree_sitter import Node

from synapse.adapters.go.ast_utils import GoAstUtils

if TYPE_CHECKING:
    from synapse.adapters.base import FileContext, SymbolTable
    from synapse.adapters.go.resolver import GoLocalScope

logger = logging.getLogger(__name__)


class GoTypeInferrer:
    """Infers types from Go AST expression nodes.

    Used during method call analysis to determine receiver types,
    enabling accurate call resolution.
    """

    def __init__(
        self,
        symbol_table: SymbolTable,
        file_context: FileContext,
        local_scope: GoLocalScope,
    ) -> None:
        """Initialize the type inferrer.

        Args:
            symbol_table: Symbol table containing type and callable definitions.
            file_context: File context with package and import information.
            local_scope: Local scope containing variable type mappings.
        """
        self._symbol_table = symbol_table
        self._file_context = file_context
        self._local_scope = local_scope
        self._visited: set[int] = set()  # Track visited nodes to prevent cycles

    def infer_type(self, node: Node, content: bytes) -> str | None:
        """Infer the type of an expression node.

        Dispatches to specific inference methods based on node type.

        Args:
            node: The AST expression node.
            content: Source file content as bytes.

        Returns:
            The type name (qualified if resolvable) or None if
            the type cannot be determined.
        """
        # Prevent infinite recursion on cycles
        node_id = id(node)
        if node_id in self._visited:
            logger.debug(f"Cycle detected at node {node.type}")
            return None
        self._visited.add(node_id)

        try:
            return self._infer_type_impl(node, content)
        finally:
            self._visited.discard(node_id)

    def _infer_type_impl(self, node: Node, content: bytes) -> str | None:
        """Internal implementation of type inference.

        Args:
            node: The AST expression node.
            content: Source file content as bytes.

        Returns:
            The type name or None if not determinable.
        """
        node_type = node.type

        # Identifier - variable reference
        if node_type == "identifier":
            return self._infer_identifier(node, content)

        # Composite literal - struct/slice/map creation
        if node_type == "composite_literal":
            return self._infer_composite_literal(node, content)

        # Call expression - function/method call return type
        if node_type == "call_expression":
            return self._infer_call_expression(node, content)

        # Selector expression - field access or method call
        if node_type == "selector_expression":
            return self._infer_selector_expression(node, content)

        # Type assertion - explicit type
        if node_type == "type_assertion_expression":
            return self._infer_type_assertion(node, content)

        # Unary expression (e.g., &x, *x)
        if node_type == "unary_expression":
            return self._infer_unary_expression(node, content)

        # Parenthesized expression - unwrap
        if node_type == "parenthesized_expression":
            return self._infer_parenthesized(node, content)

        # Index expression - array/slice/map access
        if node_type == "index_expression":
            return self._infer_index_expression(node, content)

        # Slice expression
        if node_type == "slice_expression":
            return self._infer_slice_expression(node, content)

        # Literals
        if node_type in ("int_literal", "interpreted_string_literal", "raw_string_literal"):
            return self._infer_literal(node, content)

        if node_type == "float_literal":
            return "float64"

        if node_type in ("true", "false"):
            return "bool"

        if node_type == "nil":
            return None  # nil has no specific type

        logger.debug(f"Unknown expression type for inference: {node_type}")
        return None

    def _infer_identifier(self, node: Node, content: bytes) -> str | None:
        """Infer type from variable references using local scope.

        Args:
            node: The identifier AST node.
            content: Source file content.

        Returns:
            The declared type of the variable, or None if not found.
        """
        name = GoAstUtils.get_node_text(node, content)
        return self._local_scope.get_type(name)

    def _infer_composite_literal(self, node: Node, content: bytes) -> str | None:
        """Infer type from composite literals (struct/slice/map creation).

        Args:
            node: The composite_literal AST node.
            content: Source file content.

        Returns:
            The type being instantiated.
        """
        type_node = node.child_by_field_name("type")
        if type_node:
            type_name = GoAstUtils.get_base_type_name(type_node, content)
            # Try to resolve to qualified name
            resolved = self._symbol_table.resolve_type(type_name, self._file_context)
            return resolved or type_name
        return None

    def _infer_call_expression(self, node: Node, content: bytes) -> str | None:
        """Infer return type from function/method calls.

        Handles chained calls by recursively inferring the return type of inner
        calls. For chained calls like `a.b().c()`, this method:
        1. Identifies that the operand of `c()` is a call_expression `a.b()`
        2. Recursively infers the return type of `a.b()`
        3. Uses that return type to resolve `c()`

        Args:
            node: The call_expression AST node.
            content: Source file content.

        Returns:
            The return type of the called function/method, or None if:
            - The function cannot be resolved
            - The receiver type is unknown (for method calls)
            - The inner call's return type is unknown (for chained calls)
        """
        func_node = node.child_by_field_name("function")
        if func_node is None:
            return None

        # Simple function call: funcName()
        if func_node.type == "identifier":
            func_name = GoAstUtils.get_node_text(func_node, content)
            resolved = self._symbol_table.resolve_callable(func_name)
            if resolved:
                return self._symbol_table.get_callable_return_type(resolved)
            return None

        # Method call or package.function: receiver.method() or pkg.Func()
        if func_node.type == "selector_expression":
            field_node = func_node.child_by_field_name("field")
            operand_node = func_node.child_by_field_name("operand")

            if field_node is None:
                return None

            method_name = GoAstUtils.get_node_text(field_node, content)

            # Try to infer receiver type for method resolution
            if operand_node:
                # Check if operand is a chained call (call_expression)
                is_chained_call = operand_node.type == "call_expression"

                receiver_type = self.infer_type(operand_node, content)

                # For chained calls, we MUST have the receiver type from the inner call
                # If the inner call's return type is unknown, we cannot resolve the outer call
                if is_chained_call and receiver_type is None:
                    logger.debug(
                        f"Chained call: inner call return type unknown for method {method_name}"
                    )
                    return None

                if receiver_type:
                    # Look for method on receiver type
                    resolved = self._symbol_table.resolve_callable(
                        method_name, receiver_type
                    )
                    if resolved:
                        return self._symbol_table.get_callable_return_type(resolved)

                    # For chained calls, don't fall back to heuristic resolution
                    # The receiver type is known but method not found on that type
                    if is_chained_call:
                        logger.debug(
                            f"Method {method_name} not found on type {receiver_type}"
                        )
                        return None

            # Fallback: try to resolve as any callable with this name
            # Only used when receiver type is unknown and not a chained call
            resolved = self._symbol_table.resolve_callable(method_name)
            if resolved:
                return self._symbol_table.get_callable_return_type(resolved)

        return None

    def _infer_selector_expression(self, node: Node, content: bytes) -> str | None:
        """Infer type from selector expressions (field access).

        Args:
            node: The selector_expression AST node.
            content: Source file content.

        Returns:
            The type of the selected field.
        """
        field_node = node.child_by_field_name("field")
        operand_node = node.child_by_field_name("operand")

        if field_node is None or operand_node is None:
            return None

        field_name = GoAstUtils.get_node_text(field_node, content)
        owner_type = self.infer_type(operand_node, content)

        if owner_type:
            # Look up field type from symbol table
            field_type = self._symbol_table.get_field_type(owner_type, field_name)
            if field_type:
                return field_type

        return None

    def _infer_type_assertion(self, node: Node, content: bytes) -> str | None:
        """Infer type from type assertion expressions.

        Args:
            node: The type_assertion_expression AST node.
            content: Source file content.

        Returns:
            The asserted type.
        """
        type_node = node.child_by_field_name("type")
        if type_node:
            type_name = GoAstUtils.get_base_type_name(type_node, content)
            resolved = self._symbol_table.resolve_type(type_name, self._file_context)
            return resolved or type_name
        return None

    def _infer_unary_expression(self, node: Node, content: bytes) -> str | None:
        """Infer type from unary expressions.

        Args:
            node: The unary_expression AST node.
            content: Source file content.

        Returns:
            The type of the expression (pointer type for &, dereferenced for *).
        """
        operator_node = node.child_by_field_name("operator")
        operand_node = node.child_by_field_name("operand")

        if operator_node is None or operand_node is None:
            return None

        operator = GoAstUtils.get_node_text(operator_node, content)
        operand_type = self.infer_type(operand_node, content)

        if operand_type is None:
            return None

        if operator == "&":
            # Address-of: T -> *T
            return f"*{operand_type}"
        elif operator == "*":
            # Dereference: *T -> T
            if operand_type.startswith("*"):
                return operand_type[1:]

        return operand_type

    def _infer_parenthesized(self, node: Node, content: bytes) -> str | None:
        """Infer type by unwrapping parenthesized expression.

        Args:
            node: The parenthesized_expression AST node.
            content: Source file content.

        Returns:
            The type of the inner expression.
        """
        for child in node.children:
            if child.type not in ("(", ")"):
                return self.infer_type(child, content)
        return None

    def _infer_index_expression(self, node: Node, content: bytes) -> str | None:
        """Infer element type from index expressions (array/slice/map access).

        Args:
            node: The index_expression AST node.
            content: Source file content.

        Returns:
            The element type.
        """
        operand_node = node.child_by_field_name("operand")
        if operand_node:
            container_type = self.infer_type(operand_node, content)
            if container_type:
                # Strip [] prefix for slice/array types
                if container_type.startswith("[]"):
                    return container_type[2:]
                # For map types, would need more complex parsing
        return None

    def _infer_slice_expression(self, node: Node, content: bytes) -> str | None:
        """Infer type from slice expressions.

        Args:
            node: The slice_expression AST node.
            content: Source file content.

        Returns:
            The slice type (same as operand for slices).
        """
        operand_node = node.child_by_field_name("operand")
        if operand_node:
            return self.infer_type(operand_node, content)
        return None

    def _infer_literal(self, node: Node, content: bytes) -> str | None:
        """Infer type from literal expressions.

        Args:
            node: The literal AST node.
            content: Source file content.

        Returns:
            The Go type name for the literal.
        """
        node_type = node.type

        if node_type == "int_literal":
            return "int"

        if node_type in ("interpreted_string_literal", "raw_string_literal"):
            return "string"

        return None

    def infer_receiver_type(
        self, selector_node: Node, content: bytes
    ) -> str | None:
        """Infer the type of a selector expression's operand (receiver).

        This is the main entry point for determining the receiver type
        of a method call. Handles chained calls by recursively inferring
        inner call return types.

        Args:
            selector_node: The selector_expression AST node.
            content: Source file content.

        Returns:
            The qualified type name of the receiver, or None if unknown.
        """
        operand_node = selector_node.child_by_field_name("operand")
        if operand_node is None:
            return None

        return self.infer_type(operand_node, content)

    def is_chained_call(self, selector_node: Node) -> bool:
        """Check if a selector expression's operand is a call expression.

        This is used to determine if a method call is chained on another
        method call, which affects error reporting.

        Args:
            selector_node: The selector_expression AST node.

        Returns:
            True if the operand is a call_expression, False otherwise.
        """
        operand_node = selector_node.child_by_field_name("operand")
        return operand_node is not None and operand_node.type == "call_expression"
