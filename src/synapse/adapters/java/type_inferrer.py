"""Java type inference for method overload resolution.

This module provides the TypeInferrer class that infers types from Java AST
expression nodes, enabling accurate method overload resolution by determining
argument types at call sites.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from tree_sitter import Node

from synapse.adapters.java.ast_utils import JavaAstUtils

if TYPE_CHECKING:
    from synapse.adapters.base import FileContext, SymbolTable
    from synapse.adapters.java.resolver import LocalScope

logger = logging.getLogger(__name__)


class TypeInferrer:
    """Infers types from Java AST expression nodes.

    Used during method invocation analysis to determine argument types,
    enabling accurate overload resolution.
    """

    def __init__(
        self,
        symbol_table: SymbolTable,
        file_context: FileContext,
        local_scope: LocalScope,
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

    def infer_type(self, node: Node, content: bytes) -> str | None:
        """Infer the type of an expression node.

        Dispatches to specific inference methods based on node type.

        Args:
            node: The AST expression node.
            content: Source file content as bytes.

        Returns:
            The type name (e.g., "String", "int", "String[]") or None if
            the type cannot be determined.
        """
        # Dispatch based on node type
        node_type = node.type

        # Literal types
        if node_type in (
            "string_literal",
            "decimal_integer_literal",
            "hex_integer_literal",
            "octal_integer_literal",
            "binary_integer_literal",
            "decimal_floating_point_literal",
            "hex_floating_point_literal",
            "true",
            "false",
            "character_literal",
            "null_literal",
        ):
            return self._infer_literal(node, content)

        # Variable/identifier reference
        if node_type == "identifier":
            return self._infer_identifier(node, content)

        # Object creation (new expressions)
        if node_type == "object_creation_expression":
            return self._infer_object_creation(node, content)

        # Cast expression
        if node_type == "cast_expression":
            return self._infer_cast(node, content)

        # Method invocation (return type)
        if node_type == "method_invocation":
            return self._infer_method_invocation(node, content)

        # Field access
        if node_type == "field_access":
            return self._infer_field_access(node, content)

        # Array access
        if node_type in ("array_access", "subscript_expression"):
            return self._infer_array_access(node, content)

        # Binary expression
        if node_type == "binary_expression":
            return self._infer_binary(node, content)

        # Ternary expression
        if node_type == "ternary_expression":
            return self._infer_ternary(node, content)

        # Parenthesized expression - unwrap
        if node_type == "parenthesized_expression":
            return self._infer_parenthesized(node, content)

        # Unary expression
        if node_type == "unary_expression":
            return self._infer_unary(node, content)

        # This expression
        if node_type == "this":
            return self._infer_this(node, content)

        # Array creation
        if node_type == "array_creation_expression":
            return self._infer_array_creation(node, content)

        logger.debug(f"Unknown expression type for inference: {node_type}")
        return None

    def _infer_literal(self, node: Node, content: bytes) -> str | None:
        """Infer type from literal expressions.

        Args:
            node: The literal AST node.
            content: Source file content.

        Returns:
            The Java type name for the literal.
        """
        node_type = node.type
        text = JavaAstUtils.get_node_text(node, content)

        if node_type == "string_literal":
            return "String"

        if node_type in (
            "decimal_integer_literal",
            "hex_integer_literal",
            "octal_integer_literal",
            "binary_integer_literal",
        ):
            # Check for long suffix
            if text.endswith("L") or text.endswith("l"):
                return "long"
            return "int"

        if node_type in ("decimal_floating_point_literal", "hex_floating_point_literal"):
            # Check for float suffix
            if text.endswith("f") or text.endswith("F"):
                return "float"
            # Default is double (with or without 'd'/'D' suffix)
            return "double"

        if node_type in ("true", "false"):
            return "boolean"

        if node_type == "character_literal":
            return "char"

        if node_type == "null_literal":
            return "null"

        return None

    def _infer_identifier(self, node: Node, content: bytes) -> str | None:
        """Infer type from variable references using local scope.

        Args:
            node: The identifier AST node.
            content: Source file content.

        Returns:
            The declared type of the variable, or None if not found.
        """
        name = JavaAstUtils.get_node_text(node, content)
        return self._local_scope.get_type(name)

    def _infer_object_creation(self, node: Node, content: bytes) -> str | None:
        """Infer type from new expressions.

        Args:
            node: The object_creation_expression AST node.
            content: Source file content.

        Returns:
            The instantiated class name.
        """
        # Find the type being instantiated
        type_node = node.child_by_field_name("type")
        if type_node:
            return JavaAstUtils.get_type_name(type_node, content)

        # Fallback: look for type_identifier child
        for child in node.children:
            if child.type in ("type_identifier", "generic_type", "scoped_type_identifier"):
                return JavaAstUtils.get_type_name(child, content)

        return None

    def _infer_cast(self, node: Node, content: bytes) -> str | None:
        """Infer type from cast expressions.

        Args:
            node: The cast_expression AST node.
            content: Source file content.

        Returns:
            The target type of the cast.
        """
        type_node = node.child_by_field_name("type")
        if type_node:
            return JavaAstUtils.get_type_name(type_node, content)

        # Fallback: first child that looks like a type
        for child in node.children:
            if child.type in (
                "type_identifier",
                "generic_type",
                "array_type",
                "integral_type",
                "floating_point_type",
                "boolean_type",
            ):
                return JavaAstUtils.get_type_name(child, content)

        return None

    def _infer_method_invocation(self, node: Node, content: bytes) -> str | None:
        """Infer return type from method calls.

        Attempts to resolve the called method and determine its return type.
        This requires the method to be in the symbol table with return type
        information available.

        Args:
            node: The method_invocation AST node.
            content: Source file content.

        Returns:
            The return type of the called method, or None if not resolvable.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return None

        method_name = JavaAstUtils.get_node_text(name_node, content)

        # Check if there's a receiver object to determine owner type
        object_node = node.child_by_field_name("object")
        owner_type: str | None = None

        if object_node:
            # Try to infer the receiver's type
            owner_type = self.infer_type(object_node, content)

        # Try to resolve from symbol table
        resolved = self._symbol_table.resolve_callable(method_name, owner_type)
        if resolved:
            # Check if we have return type info in the callable_return_types map
            return_type = self._symbol_table.get_callable_return_type(resolved)
            if return_type:
                return return_type

        # Common method return type patterns (heuristics for well-known methods)
        return self._infer_common_method_return_type(method_name, object_node, content)

    def _infer_field_access(self, node: Node, content: bytes) -> str | None:
        """Infer type from field access expressions.

        Attempts to resolve the field's declared type by:
        1. Inferring the owner object's type
        2. Looking up the field in the symbol table
        3. Falling back to common field type heuristics

        Args:
            node: The field_access AST node.
            content: Source file content.

        Returns:
            The field's declared type, or None if not resolvable.
        """
        # Get the field name
        field_node = node.child_by_field_name("field")
        if field_node is None:
            # Try to find field in children
            for child in node.children:
                if child.type == "identifier":
                    field_node = child
                    break

        if field_node is None:
            return None

        field_name = JavaAstUtils.get_node_text(field_node, content)

        # Get the owner object
        object_node = node.child_by_field_name("object")
        if object_node is None:
            # Try first child that's not the field
            for child in node.children:
                if child.type not in (".", "identifier") or child != field_node:
                    if child.type != ".":
                        object_node = child
                        break

        owner_type: str | None = None
        if object_node:
            owner_type = self.infer_type(object_node, content)

        # Try to look up field type from symbol table
        if owner_type:
            field_type = self._symbol_table.get_field_type(owner_type, field_name)
            if field_type:
                return field_type

        # Common field type heuristics
        return self._infer_common_field_type(field_name, owner_type)

    def _infer_array_access(self, node: Node, content: bytes) -> str | None:
        """Infer element type from array access.

        Args:
            node: The array_access AST node.
            content: Source file content.

        Returns:
            The array's element type (array type with [] stripped).
        """
        # Get the array expression
        array_node = node.child_by_field_name("array")
        if array_node is None:
            # Try first child
            for child in node.children:
                if child.type not in ("[", "]"):
                    array_node = child
                    break

        if array_node:
            array_type = self.infer_type(array_node, content)
            if array_type and array_type.endswith("[]"):
                return array_type[:-2]  # Strip []

        return None

    def _infer_binary(self, node: Node, content: bytes) -> str | None:
        """Infer result type from binary expressions using Java type promotion.

        Args:
            node: The binary_expression AST node.
            content: Source file content.

        Returns:
            The result type based on Java type promotion rules.
        """
        operator_node = node.child_by_field_name("operator")
        if operator_node is None:
            # Find operator in children
            for child in node.children:
                if child.type in (
                    "+", "-", "*", "/", "%",
                    "==", "!=", "<", ">", "<=", ">=",
                    "&&", "||", "&", "|", "^",
                    "<<", ">>", ">>>",
                ):
                    operator_node = child
                    break

        if operator_node is None:
            return None

        operator = JavaAstUtils.get_node_text(operator_node, content)

        # Comparison and logical operators always return boolean
        if operator in ("==", "!=", "<", ">", "<=", ">=", "&&", "||"):
            return "boolean"

        # Get operand types
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")

        if left_node is None or right_node is None:
            # Try positional children
            children = [c for c in node.children if c.type not in ("+", "-", "*", "/", "%")]
            if len(children) >= 2:
                left_node = children[0]
                right_node = children[-1]

        if left_node is None or right_node is None:
            return None

        left_type = self.infer_type(left_node, content)
        right_type = self.infer_type(right_node, content)

        # String concatenation
        if operator == "+" and (left_type == "String" or right_type == "String"):
            return "String"

        # Numeric type promotion
        return self._promote_numeric_types(left_type, right_type)

    def _promote_numeric_types(self, type1: str | None, type2: str | None) -> str | None:
        """Apply Java numeric type promotion rules.

        Args:
            type1: First operand type.
            type2: Second operand type.

        Returns:
            The promoted type according to Java rules.
        """
        if type1 is None and type2 is None:
            return None

        # Promotion hierarchy (higher index = wider type)
        numeric_hierarchy = ["byte", "short", "char", "int", "long", "float", "double"]

        def get_rank(t: str | None) -> int:
            if t is None:
                return -1
            try:
                return numeric_hierarchy.index(t)
            except ValueError:
                return -1

        rank1 = get_rank(type1)
        rank2 = get_rank(type2)

        if rank1 < 0 and rank2 < 0:
            return None

        # If either is double, result is double
        if type1 == "double" or type2 == "double":
            return "double"

        # If either is float, result is float
        if type1 == "float" or type2 == "float":
            return "float"

        # If either is long, result is long
        if type1 == "long" or type2 == "long":
            return "long"

        # Otherwise, result is int (byte, short, char promote to int)
        if rank1 >= 0 or rank2 >= 0:
            return "int"

        return None

    def _infer_ternary(self, node: Node, content: bytes) -> str | None:
        """Infer common type from ternary expressions.

        Args:
            node: The ternary_expression AST node.
            content: Source file content.

        Returns:
            The common type of both branches if determinable.
        """
        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")

        if consequence is None or alternative is None:
            return None

        type1 = self.infer_type(consequence, content)
        type2 = self.infer_type(alternative, content)

        # If both are the same, return that type
        if type1 == type2:
            return type1

        # If one is null, return the other
        if type1 == "null":
            return type2
        if type2 == "null":
            return type1

        # Try numeric promotion
        promoted = self._promote_numeric_types(type1, type2)
        if promoted:
            return promoted

        # Return first non-None type as fallback
        return type1 or type2

    def _infer_parenthesized(self, node: Node, content: bytes) -> str | None:
        """Infer type by unwrapping parenthesized expression.

        Args:
            node: The parenthesized_expression AST node.
            content: Source file content.

        Returns:
            The type of the inner expression.
        """
        # Find the inner expression (skip parentheses)
        for child in node.children:
            if child.type not in ("(", ")"):
                return self.infer_type(child, content)
        return None

    def _infer_unary(self, node: Node, content: bytes) -> str | None:
        """Infer type from unary expressions.

        Args:
            node: The unary_expression AST node.
            content: Source file content.

        Returns:
            The type of the operand (unary ops preserve type).
        """
        operand = node.child_by_field_name("operand")
        if operand is None:
            # Try to find operand in children
            for child in node.children:
                if child.type not in ("!", "-", "+", "~", "++", "--"):
                    operand = child
                    break

        if operand:
            return self.infer_type(operand, content)
        return None

    def _infer_this(self, node: Node, content: bytes) -> str | None:
        """Infer type from 'this' expression.

        Args:
            node: The 'this' AST node.
            content: Source file content.

        Returns:
            The enclosing class type, or None if not determinable.
        """
        # Would need enclosing class context - not available in current scope
        return None

    def _infer_array_creation(self, node: Node, content: bytes) -> str | None:
        """Infer type from array creation expressions.

        Args:
            node: The array_creation_expression AST node.
            content: Source file content.

        Returns:
            The array type (e.g., "int[]", "String[]").
        """
        type_node = node.child_by_field_name("type")
        if type_node:
            base_type = JavaAstUtils.get_type_name(type_node, content)
            # Count dimensions
            dimensions = sum(1 for c in node.children if c.type == "dimensions")
            if dimensions == 0:
                # Check for dimensions_expr
                dimensions = sum(1 for c in node.children if c.type == "dimensions_expr")
            return base_type + "[]" * max(1, dimensions)

        return None

    def _infer_common_field_type(
        self, field_name: str, owner_type: str | None
    ) -> str | None:
        """Infer type for common/well-known fields.

        Provides heuristic field type inference for commonly used Java fields
        when the symbol table doesn't have the information.

        Args:
            field_name: The name of the field being accessed.
            owner_type: The type of the owner object (if known).

        Returns:
            The inferred field type, or None if unknown.
        """
        # Common array field
        if field_name == "length":
            return "int"

        # Common class fields
        if field_name == "class":
            return "Class"

        # Common System fields
        if field_name in ("out", "err"):
            return "PrintStream"
        if field_name == "in":
            return "InputStream"

        # Common enum/constant patterns (typically uppercase)
        # These are harder to infer without more context

        return None

    def _infer_common_method_return_type(
        self, method_name: str, object_node: Node | None, content: bytes
    ) -> str | None:
        """Infer return type for common/well-known methods.

        Provides heuristic return type inference for commonly used Java methods
        when the symbol table doesn't have the information.

        Args:
            method_name: The name of the method being called.
            object_node: The receiver object node (if any).
            content: Source file content.

        Returns:
            The inferred return type, or None if unknown.
        """
        # Common String methods
        string_returning_methods = {
            "toString", "substring", "toLowerCase", "toUpperCase",
            "trim", "strip", "concat", "replace", "replaceAll",
            "replaceFirst", "valueOf", "format", "join",
        }
        if method_name in string_returning_methods:
            return "String"

        # Common boolean-returning methods
        boolean_returning_methods = {
            "equals", "equalsIgnoreCase", "isEmpty", "isBlank",
            "contains", "startsWith", "endsWith", "matches",
            "hasNext", "hasNextLine", "isPresent", "isEmpty",
            "containsKey", "containsValue", "exists", "canRead",
            "canWrite", "isDirectory", "isFile", "isAbsolute",
        }
        if method_name in boolean_returning_methods:
            return "boolean"

        # Common int-returning methods
        int_returning_methods = {
            "length", "size", "indexOf", "lastIndexOf",
            "compareTo", "compareToIgnoreCase", "hashCode",
            "intValue", "read", "available",
        }
        if method_name in int_returning_methods:
            return "int"

        # Common long-returning methods
        long_returning_methods = {"longValue", "currentTimeMillis", "nanoTime"}
        if method_name in long_returning_methods:
            return "long"

        # Common double-returning methods
        double_returning_methods = {"doubleValue", "parseDouble"}
        if method_name in double_returning_methods:
            return "double"

        # charAt returns char
        if method_name == "charAt":
            return "char"

        # getBytes returns byte[]
        if method_name == "getBytes":
            return "byte[]"

        # toCharArray returns char[]
        if method_name == "toCharArray":
            return "char[]"

        # split returns String[]
        if method_name == "split":
            return "String[]"

        return None
