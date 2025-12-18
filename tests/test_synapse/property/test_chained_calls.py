"""Property tests for chained call resolution.

Tests for the chained call resolution feature that ensures method calls
chained on other method calls are resolved correctly using the return
type of the inner call.

**Feature: improved-call-resolution, Property 6: Chained call resolution**
**Validates: Requirements 4.1, 4.2, 4.3**
"""

from hypothesis import given, settings, strategies as st

import tree_sitter_java as tsjava
import tree_sitter_go as tsgo
from tree_sitter import Language, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.java import LocalScope as JavaLocalScope, TypeInferrer as JavaTypeInferrer
from synapse.adapters.go.resolver import GoLocalScope
from synapse.adapters.go.type_inferrer import GoTypeInferrer


# Set up parsers
JAVA_LANGUAGE = Language(tsjava.language())
GO_LANGUAGE = Language(tsgo.language())


def create_java_parser() -> Parser:
    """Create a tree-sitter parser for Java."""
    return Parser(JAVA_LANGUAGE)


def create_go_parser() -> Parser:
    """Create a tree-sitter parser for Go."""
    return Parser(GO_LANGUAGE)


# Strategies for generating valid identifiers
java_identifier = st.from_regex(r"[a-z][a-zA-Z0-9]{0,10}", fullmatch=True)
java_class_name = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,10}", fullmatch=True)
go_identifier = st.from_regex(r"[a-z][a-zA-Z0-9]{0,10}", fullmatch=True)
go_type_name = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,10}", fullmatch=True)


# ============================================================================
# Java Chained Call Tests
# ============================================================================


def parse_java_expression(code: str) -> tuple[Parser, bytes]:
    """Parse a Java expression and return the parser and content."""
    wrapped = f"class Test {{ void test() {{ var x = {code}; }} }}"
    return create_java_parser(), wrapped.encode("utf-8")


def find_java_expression_node(root, content: bytes):
    """Find the expression node in a parsed Java tree."""
    for child in root.children:
        if child.type == "class_declaration":
            body = child.child_by_field_name("body")
            if body:
                for member in body.children:
                    if member.type == "method_declaration":
                        method_body = member.child_by_field_name("body")
                        if method_body:
                            for stmt in method_body.children:
                                if stmt.type == "local_variable_declaration":
                                    for decl in stmt.children:
                                        if decl.type == "variable_declarator":
                                            return decl.child_by_field_name("value")
    return None


@given(
    var_name=java_identifier,
    type_a=java_class_name,
    type_b=java_class_name,
    method_a=java_identifier,
    method_b=java_identifier,
)
@settings(max_examples=100)
def test_java_chained_call_with_known_return_types(
    var_name: str,
    type_a: str,
    type_b: str,
    method_a: str,
    method_b: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 6: Chained call resolution**
    **Validates: Requirements 4.1, 4.2, 4.3**

    For any chained method call `a.b().c()` where:
    - `a` has type TypeA
    - `b()` returns TypeB
    - `c()` is a method on TypeB

    The resolver SHALL use the return type of `b()` to resolve `c()`.
    """
    # Ensure unique names to avoid conflicts
    if type_a == type_b or method_a == method_b:
        return  # Skip degenerate cases

    # Create symbol table with types and methods
    symbol_table = SymbolTable()

    # TypeA has method_a that returns TypeB
    qualified_type_a = f"com.test.{type_a}"
    qualified_type_b = f"com.test.{type_b}"
    qualified_method_a = f"{qualified_type_a}.{method_a}"
    qualified_method_b = f"{qualified_type_b}.{method_b}"

    # Add types
    symbol_table.add_type(type_a, qualified_type_a)
    symbol_table.add_type(type_b, qualified_type_b)

    # Add method_a on TypeA that returns TypeB
    symbol_table.add_callable(method_a, qualified_method_a, qualified_type_b)

    # Add method_b on TypeB that returns String
    symbol_table.add_callable(method_b, qualified_method_b, "String")

    # Create local scope with variable of TypeA
    scope = JavaLocalScope()
    scope.add_variable(var_name, qualified_type_a)

    # Create chained call expression: var.methodA().methodB()
    chained_call = f"{var_name}.{method_a}().{method_b}()"
    parser, content = parse_java_expression(chained_call)
    tree = parser.parse(content)
    expr_node = find_java_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package="com.test", imports=[])
    inferrer = JavaTypeInferrer(symbol_table, file_context, scope)

    # The outer call should resolve to String (return type of method_b)
    result = inferrer.infer_type(expr_node, content)

    assert result == "String", (
        f"Expected 'String' for chained call {chained_call}, got '{result}'"
    )


@given(
    var_name=java_identifier,
    type_a=java_class_name,
    method_a=java_identifier,
    method_b=java_identifier,
)
@settings(max_examples=100)
def test_java_chained_call_with_unknown_inner_return_type(
    var_name: str,
    type_a: str,
    method_a: str,
    method_b: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 6: Chained call resolution**
    **Validates: Requirements 4.1, 4.2, 4.3**

    For any chained method call `a.b().c()` where the return type of `b()` is
    unknown, the resolver SHALL return None for the outer call `c()`.
    """
    if method_a == method_b:
        return  # Skip degenerate cases

    # Create symbol table with TypeA but method_a has no return type info
    symbol_table = SymbolTable()

    qualified_type_a = f"com.test.{type_a}"
    qualified_method_a = f"{qualified_type_a}.{method_a}"

    # Add type
    symbol_table.add_type(type_a, qualified_type_a)

    # Add method_a on TypeA with NO return type (simulates unknown return type)
    symbol_table.add_callable(method_a, qualified_method_a, None)

    # Create local scope with variable of TypeA
    scope = JavaLocalScope()
    scope.add_variable(var_name, qualified_type_a)

    # Create chained call expression: var.methodA().methodB()
    chained_call = f"{var_name}.{method_a}().{method_b}()"
    parser, content = parse_java_expression(chained_call)
    tree = parser.parse(content)
    expr_node = find_java_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package="com.test", imports=[])
    inferrer = JavaTypeInferrer(symbol_table, file_context, scope)

    # The outer call should return None because inner call's return type is unknown
    result = inferrer.infer_type(expr_node, content)

    # For chained calls with unknown inner return type, we should get None
    # (not fall back to heuristic resolution)
    assert result is None, (
        f"Expected None for chained call with unknown inner return type, got '{result}'"
    )


# ============================================================================
# Go Chained Call Tests
# ============================================================================


def parse_go_expression(code: str, var_decl: str = "") -> tuple[Parser, bytes]:
    """Parse a Go expression and return the parser and content."""
    wrapped = f"""package main

func test() {{
    {var_decl}
    _ = {code}
}}
"""
    return create_go_parser(), wrapped.encode("utf-8")


def find_go_expression_node(root, content: bytes):
    """Find the expression node in a parsed Go tree."""
    # Navigate to: source_file -> function_declaration -> block -> assignment_statement
    for child in root.children:
        if child.type == "function_declaration":
            body = child.child_by_field_name("body")
            if body:
                for stmt in body.children:
                    if stmt.type == "assignment_statement":
                        # Get the right side of the assignment
                        right = stmt.child_by_field_name("right")
                        if right:
                            # Handle expression_list
                            if right.type == "expression_list":
                                for expr in right.children:
                                    if expr.type != ",":
                                        return expr
                            return right
    return None


@given(
    var_name=go_identifier,
    type_a=go_type_name,
    type_b=go_type_name,
    method_a=go_type_name,  # Go exported methods start with uppercase
    method_b=go_type_name,
)
@settings(max_examples=100)
def test_go_chained_call_with_known_return_types(
    var_name: str,
    type_a: str,
    type_b: str,
    method_a: str,
    method_b: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 6: Chained call resolution**
    **Validates: Requirements 4.1, 4.2, 4.3**

    For any Go chained method call `a.B().C()` where:
    - `a` has type TypeA
    - `B()` returns TypeB
    - `C()` is a method on TypeB

    The resolver SHALL use the return type of `B()` to resolve `C()`.
    """
    # Ensure unique names to avoid conflicts
    if type_a == type_b or method_a == method_b:
        return  # Skip degenerate cases

    # Create symbol table with types and methods
    symbol_table = SymbolTable()

    pkg = "main"
    qualified_type_a = f"{pkg}.{type_a}"
    qualified_type_b = f"{pkg}.{type_b}"
    qualified_method_a = f"{pkg}.{type_a}.{method_a}"
    qualified_method_b = f"{pkg}.{type_b}.{method_b}"

    # Add types
    symbol_table.add_type(type_a, qualified_type_a)
    symbol_table.add_type(type_b, qualified_type_b)

    # Add method_a on TypeA that returns TypeB
    symbol_table.add_callable(method_a, qualified_method_a, qualified_type_b)

    # Add method_b on TypeB that returns string
    symbol_table.add_callable(method_b, qualified_method_b, "string")

    # Create local scope with variable of TypeA
    scope = GoLocalScope()
    scope.add_variable(var_name, qualified_type_a)

    # Create chained call expression: var.MethodA().MethodB()
    var_decl = f"var {var_name} {type_a}"
    chained_call = f"{var_name}.{method_a}().{method_b}()"
    parser, content = parse_go_expression(chained_call, var_decl)
    tree = parser.parse(content)
    expr_node = find_go_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package=pkg, imports=[])
    inferrer = GoTypeInferrer(symbol_table, file_context, scope)

    # The outer call should resolve to string (return type of method_b)
    result = inferrer.infer_type(expr_node, content)

    assert result == "string", (
        f"Expected 'string' for chained call {chained_call}, got '{result}'"
    )


@given(
    var_name=go_identifier,
    type_a=go_type_name,
    method_a=go_type_name,
    method_b=go_type_name,
)
@settings(max_examples=100)
def test_go_chained_call_with_unknown_inner_return_type(
    var_name: str,
    type_a: str,
    method_a: str,
    method_b: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 6: Chained call resolution**
    **Validates: Requirements 4.1, 4.2, 4.3**

    For any Go chained method call `a.B().C()` where the return type of `B()` is
    unknown, the resolver SHALL return None for the outer call `C()`.
    """
    if method_a == method_b:
        return  # Skip degenerate cases

    # Create symbol table with TypeA but method_a has no return type info
    symbol_table = SymbolTable()

    pkg = "main"
    qualified_type_a = f"{pkg}.{type_a}"
    qualified_method_a = f"{pkg}.{type_a}.{method_a}"

    # Add type
    symbol_table.add_type(type_a, qualified_type_a)

    # Add method_a on TypeA with NO return type (simulates unknown return type)
    symbol_table.add_callable(method_a, qualified_method_a, None)

    # Create local scope with variable of TypeA
    scope = GoLocalScope()
    scope.add_variable(var_name, qualified_type_a)

    # Create chained call expression: var.MethodA().MethodB()
    var_decl = f"var {var_name} {type_a}"
    chained_call = f"{var_name}.{method_a}().{method_b}()"
    parser, content = parse_go_expression(chained_call, var_decl)
    tree = parser.parse(content)
    expr_node = find_go_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package=pkg, imports=[])
    inferrer = GoTypeInferrer(symbol_table, file_context, scope)

    # The outer call should return None because inner call's return type is unknown
    result = inferrer.infer_type(expr_node, content)

    assert result is None, (
        f"Expected None for chained call with unknown inner return type, got '{result}'"
    )


# ============================================================================
# Helper method tests for is_chained_call
# ============================================================================


@given(
    var_name=java_identifier,
    method_a=java_identifier,
    method_b=java_identifier,
)
@settings(max_examples=100)
def test_java_is_chained_call_detection(
    var_name: str,
    method_a: str,
    method_b: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 6: Chained call resolution**
    **Validates: Requirements 4.1, 4.2, 4.3**

    The is_chained_call method SHALL correctly identify when a method invocation's
    object is another method invocation.
    """
    if method_a == method_b:
        return

    symbol_table = SymbolTable()
    scope = JavaLocalScope()
    scope.add_variable(var_name, "Object")
    file_context = FileContext(package="test", imports=[])

    # Test chained call: var.methodA().methodB()
    chained_call = f"{var_name}.{method_a}().{method_b}()"
    parser, content = parse_java_expression(chained_call)
    tree = parser.parse(content)
    expr_node = find_java_expression_node(tree.root_node, content)

    if expr_node is None:
        return

    inferrer = JavaTypeInferrer(symbol_table, file_context, scope)
    assert inferrer.is_chained_call(expr_node) is True, (
        f"Expected is_chained_call=True for {chained_call}"
    )

    # Test simple call: var.methodA()
    simple_call = f"{var_name}.{method_a}()"
    parser2, content2 = parse_java_expression(simple_call)
    tree2 = parser2.parse(content2)
    expr_node2 = find_java_expression_node(tree2.root_node, content2)

    if expr_node2 is None:
        return

    inferrer2 = JavaTypeInferrer(symbol_table, file_context, scope)
    assert inferrer2.is_chained_call(expr_node2) is False, (
        f"Expected is_chained_call=False for {simple_call}"
    )


@given(
    var_name=go_identifier,
    method_a=go_type_name,
    method_b=go_type_name,
)
@settings(max_examples=100)
def test_go_is_chained_call_detection(
    var_name: str,
    method_a: str,
    method_b: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 6: Chained call resolution**
    **Validates: Requirements 4.1, 4.2, 4.3**

    The is_chained_call method SHALL correctly identify when a selector expression's
    operand is a call expression.
    """
    if method_a == method_b:
        return

    symbol_table = SymbolTable()
    scope = GoLocalScope()
    scope.add_variable(var_name, "main.SomeType")
    file_context = FileContext(package="main", imports=[])

    # Test chained call: var.MethodA().MethodB()
    var_decl = f"var {var_name} SomeType"
    chained_call = f"{var_name}.{method_a}().{method_b}()"
    parser, content = parse_go_expression(chained_call, var_decl)
    tree = parser.parse(content)
    expr_node = find_go_expression_node(tree.root_node, content)

    if expr_node is None:
        return

    # For Go, we need to get the selector_expression (the function part of the call)
    func_node = expr_node.child_by_field_name("function")
    if func_node is None or func_node.type != "selector_expression":
        return

    inferrer = GoTypeInferrer(symbol_table, file_context, scope)
    assert inferrer.is_chained_call(func_node) is True, (
        f"Expected is_chained_call=True for {chained_call}"
    )

    # Test simple call: var.MethodA()
    simple_call = f"{var_name}.{method_a}()"
    parser2, content2 = parse_go_expression(simple_call, var_decl)
    tree2 = parser2.parse(content2)
    expr_node2 = find_go_expression_node(tree2.root_node, content2)

    if expr_node2 is None:
        return

    func_node2 = expr_node2.child_by_field_name("function")
    if func_node2 is None or func_node2.type != "selector_expression":
        return

    inferrer2 = GoTypeInferrer(symbol_table, file_context, scope)
    assert inferrer2.is_chained_call(func_node2) is False, (
        f"Expected is_chained_call=False for {simple_call}"
    )
