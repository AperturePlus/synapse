"""Property tests for Java type inference.

Tests for the type inference system used in Java method overload resolution.
"""

from hypothesis import given, settings, strategies as st

from synapse.adapters.java import LocalScope


# Strategies for generating valid Java identifiers and type names
java_identifier = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_]{0,15}", fullmatch=True)
java_type_name = st.sampled_from([
    "int", "long", "float", "double", "boolean", "char", "byte", "short",
    "String", "Integer", "Long", "Float", "Double", "Boolean", "Character",
    "Object", "List", "Map", "Set", "ArrayList", "HashMap",
    "int[]", "String[]", "Object[]",
])


@st.composite
def parameter_list_strategy(draw: st.DrawFn) -> list[tuple[str, str]]:
    """Generate a list of unique parameter (name, type) pairs."""
    count = draw(st.integers(min_value=0, max_value=10))
    names = draw(
        st.lists(java_identifier, min_size=count, max_size=count, unique=True)
    )
    types = draw(st.lists(java_type_name, min_size=count, max_size=count))
    return list(zip(names, types))


@st.composite
def variable_list_strategy(draw: st.DrawFn) -> list[tuple[str, str]]:
    """Generate a list of unique variable (name, type) pairs."""
    count = draw(st.integers(min_value=0, max_value=10))
    names = draw(
        st.lists(java_identifier, min_size=count, max_size=count, unique=True)
    )
    types = draw(st.lists(java_type_name, min_size=count, max_size=count))
    return list(zip(names, types))


@given(
    parameters=parameter_list_strategy(),
    variables=variable_list_strategy(),
)
@settings(max_examples=100)
def test_scope_building_completeness(
    parameters: list[tuple[str, str]],
    variables: list[tuple[str, str]],
) -> None:
    """
    **Feature: java-overload-resolution, Property 9: Scope Building Completeness**
    **Validates: Requirements 5.1, 5.2**

    For any method with parameters and local variable declarations, the LocalScope
    SHALL contain entries for all parameters and all declared local variables with
    their correct types.
    """
    scope = LocalScope()

    # Add all parameters
    for name, type_name in parameters:
        scope.add_parameter(name, type_name)

    # Add all variables (filter out names that conflict with parameters)
    param_names = {name for name, _ in parameters}
    unique_variables = [(n, t) for n, t in variables if n not in param_names]
    for name, type_name in unique_variables:
        scope.add_variable(name, type_name)

    # Verify all parameters are retrievable with correct types
    for name, expected_type in parameters:
        actual_type = scope.get_type(name)
        assert actual_type == expected_type, (
            f"Parameter '{name}' expected type '{expected_type}', got '{actual_type}'"
        )

    # Verify all unique variables are retrievable with correct types
    for name, expected_type in unique_variables:
        actual_type = scope.get_type(name)
        assert actual_type == expected_type, (
            f"Variable '{name}' expected type '{expected_type}', got '{actual_type}'"
        )

    # Verify unknown names return None
    assert scope.get_type("__nonexistent_var__") is None


@given(
    parameters=parameter_list_strategy(),
    variables=variable_list_strategy(),
    extra_var=st.tuples(java_identifier, java_type_name),
)
@settings(max_examples=100)
def test_scope_copy_isolation(
    parameters: list[tuple[str, str]],
    variables: list[tuple[str, str]],
    extra_var: tuple[str, str],
) -> None:
    """
    **Feature: java-overload-resolution, Property 9b: Scope Copy Isolation**
    **Validates: Requirements 5.1, 5.2**

    For any LocalScope, creating a copy and modifying the copy SHALL NOT affect
    the original scope.
    """
    original = LocalScope()

    # Add parameters and variables to original
    for name, type_name in parameters:
        original.add_parameter(name, type_name)

    param_names = {name for name, _ in parameters}
    for name, type_name in variables:
        if name not in param_names:
            original.add_variable(name, type_name)

    # Create a copy
    copied = original.copy()

    # Add extra variable to copy only
    extra_name, extra_type = extra_var
    copied.add_variable(extra_name, extra_type)

    # Verify original still has all its entries
    for name, expected_type in parameters:
        assert original.get_type(name) == expected_type

    # Verify copy has the extra variable
    assert copied.get_type(extra_name) == extra_type

    # Verify original does NOT have the extra variable (unless it was already there)
    original_had_extra = any(
        name == extra_name for name, _ in parameters
    ) or any(
        name == extra_name for name, _ in variables if name not in param_names
    )
    if not original_had_extra:
        assert original.get_type(extra_name) is None, (
            f"Original scope should not have '{extra_name}' after copy modification"
        )


import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from synapse.adapters.base import FileContext, SymbolTable
from synapse.adapters.java import TypeInferrer


# Set up Java parser for tests
JAVA_LANGUAGE = Language(tsjava.language())


def create_parser() -> Parser:
    """Create a tree-sitter parser for Java."""
    parser = Parser(JAVA_LANGUAGE)
    return parser


def parse_expression(code: str) -> tuple[Parser, bytes]:
    """Parse a Java expression and return the parser and content."""
    # Wrap expression in a minimal class/method context
    wrapped = f"class Test {{ void test() {{ var x = {code}; }} }}"
    return create_parser(), wrapped.encode("utf-8")


def find_expression_node(root, content: bytes):
    """Find the expression node in a parsed tree."""
    # Navigate to the variable declarator's value
    # class_declaration -> class_body -> method_declaration -> block -> local_variable_declaration
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


# Strategies for generating Java literals
# Note: We blacklist Cs (surrogates) and Cc (control characters like \x00) because
# they are not valid inside Java string literals without proper escaping.
string_literal_strategy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters='"\\'),
    min_size=0,
    max_size=20,
).map(lambda s: f'"{s}"')

int_literal_strategy = st.integers(min_value=-2147483648, max_value=2147483647).map(str)

long_literal_strategy = st.integers(
    min_value=-9223372036854775808, max_value=9223372036854775807
).map(lambda x: f"{x}L")

float_literal_strategy = st.floats(
    min_value=-1e10, max_value=1e10, allow_nan=False, allow_infinity=False
).map(lambda x: f"{x}f")

double_literal_strategy = st.floats(
    min_value=-1e10, max_value=1e10, allow_nan=False, allow_infinity=False
).map(str)

boolean_literal_strategy = st.sampled_from(["true", "false"])

char_literal_strategy = st.characters(
    blacklist_categories=("Cs",), blacklist_characters="'\\"
).map(lambda c: f"'{c}'")

null_literal_strategy = st.just("null")


@given(literal=string_literal_strategy)
@settings(max_examples=100)
def test_string_literal_type_inference(literal: str) -> None:
    """
    **Feature: java-overload-resolution, Property 1: Literal Type Inference Accuracy**
    **Validates: Requirements 1.1**

    For any Java string literal, TypeInferrer.infer_type SHALL return "String".
    """
    parser, content = parse_expression(literal)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "String", f"Expected 'String' for {literal}, got {result}"


@given(literal=int_literal_strategy)
@settings(max_examples=100)
def test_int_literal_type_inference(literal: str) -> None:
    """
    **Feature: java-overload-resolution, Property 1: Literal Type Inference Accuracy**
    **Validates: Requirements 1.1**

    For any Java integer literal (without L suffix), TypeInferrer.infer_type SHALL return "int".
    """
    parser, content = parse_expression(literal)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "int", f"Expected 'int' for {literal}, got {result}"


@given(literal=long_literal_strategy)
@settings(max_examples=100)
def test_long_literal_type_inference(literal: str) -> None:
    """
    **Feature: java-overload-resolution, Property 1: Literal Type Inference Accuracy**
    **Validates: Requirements 1.1**

    For any Java long literal (with L suffix), TypeInferrer.infer_type SHALL return "long".
    """
    parser, content = parse_expression(literal)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "long", f"Expected 'long' for {literal}, got {result}"


@given(literal=boolean_literal_strategy)
@settings(max_examples=100)
def test_boolean_literal_type_inference(literal: str) -> None:
    """
    **Feature: java-overload-resolution, Property 1: Literal Type Inference Accuracy**
    **Validates: Requirements 1.1**

    For any Java boolean literal, TypeInferrer.infer_type SHALL return "boolean".
    """
    parser, content = parse_expression(literal)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "boolean", f"Expected 'boolean' for {literal}, got {result}"


@given(literal=null_literal_strategy)
@settings(max_examples=100)
def test_null_literal_type_inference(literal: str) -> None:
    """
    **Feature: java-overload-resolution, Property 1: Literal Type Inference Accuracy**
    **Validates: Requirements 1.1**

    For any Java null literal, TypeInferrer.infer_type SHALL return "null".
    """
    parser, content = parse_expression(literal)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "null", f"Expected 'null' for {literal}, got {result}"



@given(
    var_name=java_identifier,
    var_type=java_type_name,
)
@settings(max_examples=100)
def test_variable_type_resolution(var_name: str, var_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 2: Variable Type Resolution**
    **Validates: Requirements 1.2, 5.3**

    For any local variable or parameter with a declared type in scope, when that
    variable is referenced in a method invocation argument, the TypeInferrer SHALL
    return the declared type.
    """
    # Create a scope with the variable
    scope = LocalScope()
    scope.add_variable(var_name, var_type)

    # Parse an expression that references the variable
    parser, content = parse_expression(var_name)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == var_type, (
        f"Expected '{var_type}' for variable '{var_name}', got '{result}'"
    )


@given(
    param_name=java_identifier,
    param_type=java_type_name,
)
@settings(max_examples=100)
def test_parameter_type_resolution(param_name: str, param_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 2: Variable Type Resolution**
    **Validates: Requirements 1.2, 5.3**

    For any parameter with a declared type in scope, when that parameter is
    referenced, the TypeInferrer SHALL return the declared type.
    """
    # Create a scope with the parameter
    scope = LocalScope()
    scope.add_parameter(param_name, param_type)

    # Parse an expression that references the parameter
    parser, content = parse_expression(param_name)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == param_type, (
        f"Expected '{param_type}' for parameter '{param_name}', got '{result}'"
    )


@given(var_name=java_identifier)
@settings(max_examples=100)
def test_unknown_variable_returns_none(var_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 2: Variable Type Resolution**
    **Validates: Requirements 1.2, 5.3**

    For any variable reference not in scope, the TypeInferrer SHALL return None.
    """
    # Create an empty scope (variable not declared)
    scope = LocalScope()

    # Parse an expression that references the variable
    parser, content = parse_expression(var_name)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result is None, (
        f"Expected None for unknown variable '{var_name}', got '{result}'"
    )



# Strategy for generating valid Java class names (PascalCase)
java_class_name = st.from_regex(r"[A-Z][a-zA-Z0-9]{0,15}", fullmatch=True)


@given(class_name=java_class_name)
@settings(max_examples=100)
def test_constructor_type_inference(class_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 4: Constructor Type Inference**
    **Validates: Requirements 1.4**

    For any `new` expression used as an argument, the TypeInferrer SHALL return
    the instantiated class name.
    """
    # Create a new expression
    new_expr = f"new {class_name}()"
    parser, content = parse_expression(new_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == class_name, (
        f"Expected '{class_name}' for new {class_name}(), got '{result}'"
    )


@given(class_name=java_class_name)
@settings(max_examples=100)
def test_constructor_with_args_type_inference(class_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 4: Constructor Type Inference**
    **Validates: Requirements 1.4**

    For any `new` expression with arguments, the TypeInferrer SHALL return
    the instantiated class name.
    """
    # Create a new expression with arguments
    new_expr = f'new {class_name}("arg", 42)'
    parser, content = parse_expression(new_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == class_name, (
        f"Expected '{class_name}' for new {class_name}(...), got '{result}'"
    )



# Strategy for cast target types (reference types and primitives)
cast_target_type = st.sampled_from([
    "int", "long", "float", "double", "byte", "short", "char",
    "String", "Object", "Integer", "Long", "Double",
])


@given(target_type=cast_target_type)
@settings(max_examples=100)
def test_cast_type_inference(target_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 5: Cast Type Inference**
    **Validates: Requirements 1.5**

    For any cast expression used as an argument, the TypeInferrer SHALL return
    the target type of the cast.
    """
    # Create a cast expression
    cast_expr = f"({target_type}) someValue"

    # We need to add someValue to scope for the expression to be valid
    scope = LocalScope()
    scope.add_variable("someValue", "Object")

    parser, content = parse_expression(cast_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == target_type, (
        f"Expected '{target_type}' for ({target_type}) cast, got '{result}'"
    )


@given(target_type=java_class_name)
@settings(max_examples=100)
def test_cast_to_class_type_inference(target_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 5: Cast Type Inference**
    **Validates: Requirements 1.5**

    For any cast expression to a class type, the TypeInferrer SHALL return
    the target class name.
    """
    # Create a cast expression to a class type
    cast_expr = f"({target_type}) obj"

    scope = LocalScope()
    scope.add_variable("obj", "Object")

    parser, content = parse_expression(cast_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == target_type, (
        f"Expected '{target_type}' for ({target_type}) cast, got '{result}'"
    )


# Property 3: Method Return Type Inference tests

# Strategy for generating method names (camelCase)
java_method_name = st.from_regex(r"[a-z][a-zA-Z0-9]{0,15}", fullmatch=True)

# Strategy for return types
return_type_strategy = st.sampled_from([
    "int", "long", "float", "double", "boolean", "char", "byte", "short",
    "String", "Integer", "Long", "Float", "Double", "Boolean",
    "Object", "List", "Map", "Set", "void",
])


@given(
    method_name=java_method_name,
    return_type=return_type_strategy,
)
@settings(max_examples=100)
def test_method_return_type_from_symbol_table(method_name: str, return_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 3: Method Return Type Inference**
    **Validates: Requirements 1.3**

    For any method invocation used as an argument, where the called method exists
    in the symbol table with a known return type, the TypeInferrer SHALL return
    that return type.
    """
    # Create a symbol table with the method and its return type
    symbol_table = SymbolTable()
    qualified_name = f"com.test.TestClass.{method_name}"
    symbol_table.add_callable(method_name, qualified_name, return_type)

    # Create a method invocation expression
    method_call = f"{method_name}()"
    parser, content = parse_expression(method_call)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == return_type, (
        f"Expected '{return_type}' for {method_name}(), got '{result}'"
    )


@given(
    method_name=java_method_name,
    return_type=return_type_strategy,
    arg_literal=int_literal_strategy,
)
@settings(max_examples=100)
def test_method_return_type_with_args_from_symbol_table(
    method_name: str, return_type: str, arg_literal: str
) -> None:
    """
    **Feature: java-overload-resolution, Property 3: Method Return Type Inference**
    **Validates: Requirements 1.3**

    For any method invocation with arguments, where the called method exists
    in the symbol table with a known return type, the TypeInferrer SHALL return
    that return type.
    """
    # Create a symbol table with the method and its return type
    symbol_table = SymbolTable()
    qualified_name = f"com.test.TestClass.{method_name}"
    symbol_table.add_callable(method_name, qualified_name, return_type)

    # Create a method invocation expression with an argument
    method_call = f"{method_name}({arg_literal})"
    parser, content = parse_expression(method_call)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == return_type, (
        f"Expected '{return_type}' for {method_name}({arg_literal}), got '{result}'"
    )


# Test common method heuristics
@given(method_name=st.sampled_from([
    "toString", "substring", "toLowerCase", "toUpperCase",
    "trim", "concat", "replace", "valueOf",
]))
@settings(max_examples=100)
def test_common_string_returning_methods(method_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 3: Method Return Type Inference**
    **Validates: Requirements 1.3**

    For common String-returning methods, the TypeInferrer SHALL return "String"
    even without symbol table information.
    """
    # Create an empty symbol table (no method info)
    symbol_table = SymbolTable()

    # Create a method invocation expression
    method_call = f'obj.{method_name}()'
    
    # We need to add 'obj' to scope
    scope = LocalScope()
    scope.add_variable("obj", "Object")

    parser, content = parse_expression(method_call)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "String", (
        f"Expected 'String' for {method_name}(), got '{result}'"
    )


@given(method_name=st.sampled_from([
    "equals", "isEmpty", "contains", "startsWith", "endsWith",
    "hasNext", "isPresent",
]))
@settings(max_examples=100)
def test_common_boolean_returning_methods(method_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 3: Method Return Type Inference**
    **Validates: Requirements 1.3**

    For common boolean-returning methods, the TypeInferrer SHALL return "boolean"
    even without symbol table information.
    """
    # Create an empty symbol table (no method info)
    symbol_table = SymbolTable()

    # Create a method invocation expression
    method_call = f'obj.{method_name}()'
    
    scope = LocalScope()
    scope.add_variable("obj", "Object")

    parser, content = parse_expression(method_call)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "boolean", (
        f"Expected 'boolean' for {method_name}(), got '{result}'"
    )


@given(method_name=st.sampled_from([
    "length", "size", "indexOf", "lastIndexOf", "compareTo", "hashCode",
]))
@settings(max_examples=100)
def test_common_int_returning_methods(method_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 3: Method Return Type Inference**
    **Validates: Requirements 1.3**

    For common int-returning methods, the TypeInferrer SHALL return "int"
    even without symbol table information.
    """
    # Create an empty symbol table (no method info)
    symbol_table = SymbolTable()

    # Create a method invocation expression
    method_call = f'obj.{method_name}()'
    
    scope = LocalScope()
    scope.add_variable("obj", "Object")

    parser, content = parse_expression(method_call)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "int", (
        f"Expected 'int' for {method_name}(), got '{result}'"
    )


# Property 10: Binary Expression Type Promotion tests

# Strategy for numeric types with their hierarchy rank
numeric_types_with_rank = [
    ("byte", 0),
    ("short", 1),
    ("char", 2),
    ("int", 3),
    ("long", 4),
    ("float", 5),
    ("double", 6),
]

# Strategy for numeric literals by type
numeric_literal_by_type = {
    "byte": "42",
    "short": "42",
    "char": "'a'",
    "int": "42",
    "long": "42L",
    "float": "3.14f",
    "double": "3.14",
}

# Strategy for arithmetic operators
arithmetic_operators = st.sampled_from(["+", "-", "*", "/", "%"])

# Strategy for comparison operators
comparison_operators = st.sampled_from(["==", "!=", "<", ">", "<=", ">="])

# Strategy for logical operators
logical_operators = st.sampled_from(["&&", "||"])


def get_expected_promoted_type(type1: str, type2: str) -> str:
    """Get the expected promoted type according to Java rules."""
    hierarchy = ["byte", "short", "char", "int", "long", "float", "double"]
    
    rank1 = hierarchy.index(type1) if type1 in hierarchy else -1
    rank2 = hierarchy.index(type2) if type2 in hierarchy else -1
    
    if rank1 < 0 or rank2 < 0:
        return "int"  # Default
    
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
    return "int"


@given(
    left_type=st.sampled_from(["int", "long", "float", "double"]),
    right_type=st.sampled_from(["int", "long", "float", "double"]),
    operator=arithmetic_operators,
)
@settings(max_examples=100)
def test_binary_numeric_type_promotion(left_type: str, right_type: str, operator: str) -> None:
    """
    **Feature: java-overload-resolution, Property 10: Binary Expression Type Promotion**
    **Validates: Requirements 4.3**

    For any binary expression with numeric operands, the inferred type SHALL follow
    Java's type promotion rules (widening to the larger type).
    """
    # Create variables with the specified types
    scope = LocalScope()
    scope.add_variable("left", left_type)
    scope.add_variable("right", right_type)

    # Create a binary expression
    binary_expr = f"left {operator} right"
    parser, content = parse_expression(binary_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    expected = get_expected_promoted_type(left_type, right_type)
    assert result == expected, (
        f"Expected '{expected}' for {left_type} {operator} {right_type}, got '{result}'"
    )


@given(operator=comparison_operators)
@settings(max_examples=100)
def test_comparison_operators_return_boolean(operator: str) -> None:
    """
    **Feature: java-overload-resolution, Property 10: Binary Expression Type Promotion**
    **Validates: Requirements 4.3**

    For any comparison operator, the inferred type SHALL be boolean.
    """
    scope = LocalScope()
    scope.add_variable("a", "int")
    scope.add_variable("b", "int")

    binary_expr = f"a {operator} b"
    parser, content = parse_expression(binary_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "boolean", (
        f"Expected 'boolean' for comparison {operator}, got '{result}'"
    )


@given(operator=logical_operators)
@settings(max_examples=100)
def test_logical_operators_return_boolean(operator: str) -> None:
    """
    **Feature: java-overload-resolution, Property 10: Binary Expression Type Promotion**
    **Validates: Requirements 4.3**

    For any logical operator, the inferred type SHALL be boolean.
    """
    scope = LocalScope()
    scope.add_variable("a", "boolean")
    scope.add_variable("b", "boolean")

    binary_expr = f"a {operator} b"
    parser, content = parse_expression(binary_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "boolean", (
        f"Expected 'boolean' for logical {operator}, got '{result}'"
    )


@given(
    left_is_string=st.booleans(),
    other_type=st.sampled_from(["int", "double", "boolean", "Object"]),
)
@settings(max_examples=100)
def test_string_concatenation_returns_string(left_is_string: bool, other_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 10: Binary Expression Type Promotion**
    **Validates: Requirements 4.3**

    For any string concatenation (+ with String operand), the inferred type SHALL be String.
    """
    scope = LocalScope()
    
    if left_is_string:
        scope.add_variable("left", "String")
        scope.add_variable("right", other_type)
    else:
        scope.add_variable("left", other_type)
        scope.add_variable("right", "String")

    binary_expr = "left + right"
    parser, content = parse_expression(binary_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == "String", (
        f"Expected 'String' for string concatenation, got '{result}'"
    )


# Property 6: Placeholder Fallback tests

from synapse.adapters.java import JavaResolver
from synapse.core.models import LanguageType


def parse_method_invocation(code: str) -> tuple[Parser, bytes]:
    """Parse a Java method invocation and return the parser and content."""
    # Wrap invocation in a minimal class/method context
    wrapped = f"class Test {{ void test() {{ {code}; }} }}"
    return create_parser(), wrapped.encode("utf-8")


def find_method_invocation_node(root, content: bytes):
    """Find the method_invocation node in a parsed tree."""
    # Navigate to the method invocation in the method body
    for child in root.children:
        if child.type == "class_declaration":
            body = child.child_by_field_name("body")
            if body:
                for member in body.children:
                    if member.type == "method_declaration":
                        method_body = member.child_by_field_name("body")
                        if method_body:
                            for stmt in method_body.children:
                                if stmt.type == "expression_statement":
                                    for expr in stmt.children:
                                        if expr.type == "method_invocation":
                                            return expr
    return None


@given(
    method_name=java_method_name,
    num_unknown_args=st.integers(min_value=1, max_value=5),
)
@settings(max_examples=100)
def test_placeholder_fallback_for_unknown_variables(
    method_name: str, num_unknown_args: int
) -> None:
    """
    **Feature: java-overload-resolution, Property 6: Placeholder Fallback**
    **Validates: Requirements 2.1**

    For any expression where type inference fails, the inferred signature SHALL
    contain `?` at that argument position.
    """
    # Create unknown variable names that won't be in scope
    unknown_vars = [f"unknownVar{i}" for i in range(num_unknown_args)]
    args_str = ", ".join(unknown_vars)
    method_call = f"{method_name}({args_str})"

    parser, content = parse_method_invocation(method_call)
    tree = parser.parse(content)
    invocation_node = find_method_invocation_node(tree.root_node, content)

    if invocation_node is None:
        return  # Skip if parsing failed

    # Create empty scope (variables not declared)
    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    # Create a resolver to test _infer_signature
    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    result = resolver._infer_signature(
        invocation_node, content, file_context, symbol_table, scope
    )

    # Expected signature should have all placeholders
    expected = f"({', '.join(['?'] * num_unknown_args)})"
    assert result == expected, (
        f"Expected '{expected}' for unknown variables, got '{result}'"
    )


@given(
    method_name=java_method_name,
    known_types=st.lists(java_type_name, min_size=1, max_size=3),
    num_unknown=st.integers(min_value=1, max_value=2),
)
@settings(max_examples=100)
def test_placeholder_fallback_mixed_known_unknown(
    method_name: str, known_types: list[str], num_unknown: int
) -> None:
    """
    **Feature: java-overload-resolution, Property 6: Placeholder Fallback**
    **Validates: Requirements 2.1**

    For any method invocation with a mix of resolvable and unresolvable arguments,
    the inferred signature SHALL contain the resolved types and `?` placeholders
    in the correct positions.
    """
    # Create scope with known variables
    scope = LocalScope()
    known_vars = []
    for i, type_name in enumerate(known_types):
        var_name = f"knownVar{i}"
        scope.add_variable(var_name, type_name)
        known_vars.append(var_name)

    # Create unknown variable names
    unknown_vars = [f"unknownVar{i}" for i in range(num_unknown)]

    # Interleave known and unknown variables
    all_args = []
    expected_types = []
    known_idx = 0
    unknown_idx = 0

    # Alternate between known and unknown
    for i in range(len(known_vars) + len(unknown_vars)):
        if i % 2 == 0 and known_idx < len(known_vars):
            all_args.append(known_vars[known_idx])
            expected_types.append(known_types[known_idx])
            known_idx += 1
        elif unknown_idx < len(unknown_vars):
            all_args.append(unknown_vars[unknown_idx])
            expected_types.append("?")
            unknown_idx += 1
        elif known_idx < len(known_vars):
            all_args.append(known_vars[known_idx])
            expected_types.append(known_types[known_idx])
            known_idx += 1

    args_str = ", ".join(all_args)
    method_call = f"{method_name}({args_str})"

    parser, content = parse_method_invocation(method_call)
    tree = parser.parse(content)
    invocation_node = find_method_invocation_node(tree.root_node, content)

    if invocation_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    result = resolver._infer_signature(
        invocation_node, content, file_context, symbol_table, scope
    )

    expected = f"({', '.join(expected_types)})"
    assert result == expected, (
        f"Expected '{expected}' for mixed args, got '{result}'"
    )


@given(method_name=java_method_name)
@settings(max_examples=100)
def test_placeholder_fallback_no_context(method_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 6: Placeholder Fallback**
    **Validates: Requirements 2.1**

    When _infer_signature is called without file_context, symbol_table, or
    local_scope, it SHALL fall back to placeholder-only signatures.
    """
    method_call = f'{method_name}("arg1", 42, true)'

    parser, content = parse_method_invocation(method_call)
    tree = parser.parse(content)
    invocation_node = find_method_invocation_node(tree.root_node, content)

    if invocation_node is None:
        return  # Skip if parsing failed

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    # Call without optional parameters
    result = resolver._infer_signature(invocation_node, content)

    # Should fall back to placeholders
    expected = "(?, ?, ?)"
    assert result == expected, (
        f"Expected '{expected}' without context, got '{result}'"
    )


# Property 7: Signature Format Consistency (Round-Trip) tests

from synapse.adapters.java.ast_utils import JavaAstUtils


def parse_method_declaration(code: str) -> tuple[Parser, bytes]:
    """Parse a Java method declaration and return the parser and content."""
    wrapped = f"class Test {{ {code} }}"
    return create_parser(), wrapped.encode("utf-8")


def find_method_declaration_node(root, content: bytes):
    """Find the method_declaration node in a parsed tree."""
    for child in root.children:
        if child.type == "class_declaration":
            body = child.child_by_field_name("body")
            if body:
                for member in body.children:
                    if member.type == "method_declaration":
                        return member
    return None


# Strategy for generating parameter type lists
param_type_list_strategy = st.lists(
    st.sampled_from([
        "int", "long", "float", "double", "boolean", "char", "byte", "short",
        "String", "Integer", "Long", "Object",
    ]),
    min_size=0,
    max_size=5,
)


def type_to_literal(type_name: str) -> str:
    """Convert a type name to a representative literal value."""
    literals = {
        "int": "42",
        "long": "42L",
        "float": "3.14f",
        "double": "3.14",
        "boolean": "true",
        "char": "'a'",
        "byte": "(byte) 1",
        "short": "(short) 1",
        "String": '"hello"',
        "Integer": "Integer.valueOf(42)",
        "Long": "Long.valueOf(42L)",
        "Object": "new Object()",
    }
    return literals.get(type_name, "null")


@given(param_types=param_type_list_strategy)
@settings(max_examples=100)
def test_signature_format_round_trip(param_types: list[str]) -> None:
    """
    **Feature: java-overload-resolution, Property 7: Signature Format Consistency (Round-Trip)**
    **Validates: Requirements 3.1**

    For any method declaration with a signature built by build_signature, when a
    call to that method uses arguments of matching types, the inferred signature
    SHALL equal the declared signature.
    """
    # Build a method declaration with the given parameter types
    params = ", ".join(
        f"{ptype} param{i}" for i, ptype in enumerate(param_types)
    )
    method_decl = f"void testMethod({params}) {{}}"

    parser, content = parse_method_declaration(method_decl)
    tree = parser.parse(content)
    method_node = find_method_declaration_node(tree.root_node, content)

    if method_node is None:
        return  # Skip if parsing failed

    # Get the declared signature using build_signature
    declared_sig = JavaAstUtils.build_signature(method_node, content)

    # Now create a method invocation with matching argument types
    # We'll use variables with the correct types
    scope = LocalScope()
    arg_names = []
    for i, ptype in enumerate(param_types):
        var_name = f"arg{i}"
        scope.add_variable(var_name, ptype)
        arg_names.append(var_name)

    args_str = ", ".join(arg_names)
    method_call = f"testMethod({args_str})"

    parser2, content2 = parse_method_invocation(method_call)
    tree2 = parser2.parse(content2)
    invocation_node = find_method_invocation_node(tree2.root_node, content2)

    if invocation_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser2,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    inferred_sig = resolver._infer_signature(
        invocation_node, content2, file_context, symbol_table, scope
    )

    assert inferred_sig == declared_sig, (
        f"Inferred signature '{inferred_sig}' does not match "
        f"declared signature '{declared_sig}' for types {param_types}"
    )


@given(param_types=param_type_list_strategy)
@settings(max_examples=100)
def test_signature_format_with_literals(param_types: list[str]) -> None:
    """
    **Feature: java-overload-resolution, Property 7: Signature Format Consistency (Round-Trip)**
    **Validates: Requirements 3.1**

    For any method declaration, when a call uses literal arguments of matching
    types, the inferred signature SHALL equal the declared signature.
    """
    # Skip types that don't have simple literals
    simple_types = ["int", "long", "float", "double", "boolean", "String"]
    filtered_types = [t for t in param_types if t in simple_types]

    if not filtered_types:
        return  # Skip if no simple types

    # Build a method declaration
    params = ", ".join(
        f"{ptype} param{i}" for i, ptype in enumerate(filtered_types)
    )
    method_decl = f"void testMethod({params}) {{}}"

    parser, content = parse_method_declaration(method_decl)
    tree = parser.parse(content)
    method_node = find_method_declaration_node(tree.root_node, content)

    if method_node is None:
        return  # Skip if parsing failed

    declared_sig = JavaAstUtils.build_signature(method_node, content)

    # Create method invocation with literal arguments
    literals = []
    for ptype in filtered_types:
        if ptype == "int":
            literals.append("42")
        elif ptype == "long":
            literals.append("42L")
        elif ptype == "float":
            literals.append("3.14f")
        elif ptype == "double":
            literals.append("3.14")
        elif ptype == "boolean":
            literals.append("true")
        elif ptype == "String":
            literals.append('"hello"')

    args_str = ", ".join(literals)
    method_call = f"testMethod({args_str})"

    parser2, content2 = parse_method_invocation(method_call)
    tree2 = parser2.parse(content2)
    invocation_node = find_method_invocation_node(tree2.root_node, content2)

    if invocation_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser2,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    inferred_sig = resolver._infer_signature(
        invocation_node, content2, file_context, symbol_table, scope
    )

    assert inferred_sig == declared_sig, (
        f"Inferred signature '{inferred_sig}' does not match "
        f"declared signature '{declared_sig}' for literal types {filtered_types}"
    )


# Property 8: Type Format Consistency tests


# Strategy for base types that can be arrays
array_base_type = st.sampled_from([
    "int", "long", "float", "double", "boolean", "char", "byte", "short",
    "String", "Integer", "Object",
])


@given(base_type=array_base_type)
@settings(max_examples=100)
def test_array_type_format_consistency(base_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 8: Type Format Consistency**
    **Validates: Requirements 3.2, 3.3, 3.4**

    For any array type expression, the inferred type format SHALL match the
    format produced by JavaAstUtils.get_type_name (arrays as Type[]).
    """
    # Create a variable with array type
    array_type = f"{base_type}[]"
    scope = LocalScope()
    scope.add_variable("arr", array_type)

    # Parse an expression that references the array variable
    parser, content = parse_expression("arr")
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    assert result == array_type, (
        f"Expected '{array_type}' for array variable, got '{result}'"
    )


@given(base_type=array_base_type)
@settings(max_examples=100)
def test_array_access_element_type_format(base_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 8: Type Format Consistency**
    **Validates: Requirements 3.2, 3.3, 3.4**

    For any array access expression, the inferred type SHALL be the element
    type (array type with [] stripped).
    """
    # Create a variable with array type
    array_type = f"{base_type}[]"
    scope = LocalScope()
    scope.add_variable("arr", array_type)

    # Parse an array access expression
    parser, content = parse_expression("arr[0]")
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    # Array access should return the element type
    assert result == base_type, (
        f"Expected '{base_type}' for array access, got '{result}'"
    )


@given(base_type=array_base_type)
@settings(max_examples=100)
def test_array_creation_type_format(base_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 8: Type Format Consistency**
    **Validates: Requirements 3.2, 3.3, 3.4**

    For any array creation expression, the inferred type SHALL include the
    array notation (Type[]).
    """
    # Create an array creation expression
    array_creation = f"new {base_type}[10]"

    parser, content = parse_expression(array_creation)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    expected = f"{base_type}[]"
    assert result == expected, (
        f"Expected '{expected}' for array creation, got '{result}'"
    )


# Strategy for generic type names
generic_base_type = st.sampled_from([
    "List", "Set", "Map", "ArrayList", "HashMap", "Optional",
])


@given(
    generic_type=generic_base_type,
    type_param=st.sampled_from(["String", "Integer", "Object"]),
)
@settings(max_examples=100)
def test_generic_type_uses_raw_type(generic_type: str, type_param: str) -> None:
    """
    **Feature: java-overload-resolution, Property 8: Type Format Consistency**
    **Validates: Requirements 3.2, 3.3, 3.4**

    For any generic type expression, the inferred type SHALL use the raw type
    name without generic parameters.
    """
    # Create a new expression with generic type
    new_expr = f"new {generic_type}<{type_param}>()"

    parser, content = parse_expression(new_expr)
    tree = parser.parse(content)
    expr_node = find_expression_node(tree.root_node, content)

    if expr_node is None:
        return  # Skip if parsing failed

    scope = LocalScope()
    symbol_table = SymbolTable()
    file_context = FileContext(package="test", imports=[])

    inferrer = TypeInferrer(symbol_table, file_context, scope)
    result = inferrer.infer_type(expr_node, content)

    # Should return raw type without generic parameters
    assert result == generic_type, (
        f"Expected raw type '{generic_type}' for generic, got '{result}'"
    )


@given(base_type=array_base_type)
@settings(max_examples=100)
def test_varargs_parameter_type_format(base_type: str) -> None:
    """
    **Feature: java-overload-resolution, Property 8: Type Format Consistency**
    **Validates: Requirements 3.2, 3.3, 3.4**

    For any varargs parameter, the declared signature SHALL use the varargs
    format (Type...) and the parameter type in scope SHALL be an array.
    """
    # Build a method declaration with varargs
    method_decl = f"void testMethod({base_type}... args) {{}}"

    parser, content = parse_method_declaration(method_decl)
    tree = parser.parse(content)
    method_node = find_method_declaration_node(tree.root_node, content)

    if method_node is None:
        return  # Skip if parsing failed

    # Get the declared signature - should have varargs format
    declared_sig = JavaAstUtils.build_signature(method_node, content)
    expected_sig = f"({base_type}...)"

    assert declared_sig == expected_sig, (
        f"Expected varargs signature '{expected_sig}', got '{declared_sig}'"
    )


# Property 11: Ambiguous Overload Detection tests


@st.composite
def overloaded_method_strategy(draw: st.DrawFn) -> tuple[str, list[list[str]]]:
    """Generate a method name and multiple distinct signatures for overloading.

    Returns:
        A tuple of (method_name, list of parameter type lists).
    """
    method_name = draw(java_method_name)
    num_overloads = draw(st.integers(min_value=2, max_value=4))

    # Generate distinct signatures (different arities or types)
    signatures: list[list[str]] = []
    for _ in range(num_overloads):
        arity = draw(st.integers(min_value=0, max_value=3))
        param_types = draw(
            st.lists(java_type_name, min_size=arity, max_size=arity)
        )
        # Ensure uniqueness
        if param_types not in signatures:
            signatures.append(param_types)

    # Ensure we have at least 2 distinct signatures
    if len(signatures) < 2:
        signatures.append(["String"])  # Add a fallback distinct signature

    return method_name, signatures


@given(
    method_name=java_method_name,
    param_types1=st.lists(java_type_name, min_size=1, max_size=3),
    param_types2=st.lists(java_type_name, min_size=1, max_size=3),
)
@settings(max_examples=100)
def test_ambiguous_overload_with_same_arity_placeholders(
    method_name: str,
    param_types1: list[str],
    param_types2: list[str],
) -> None:
    """
    **Feature: java-overload-resolution, Property 11: Ambiguous Overload Detection**
    **Validates: Requirements 2.3**

    For any method invocation where multiple callable candidates match the inferred
    signature (including partial matches with placeholders), the system SHALL record
    an unresolved reference with reason "Ambiguous overload".
    """
    # Ensure both signatures have the same arity but are different
    if len(param_types1) != len(param_types2):
        param_types2 = param_types1.copy()
        if param_types2:
            # Make them different by changing the first type
            param_types2[0] = "Object" if param_types2[0] != "Object" else "String"

    # Skip if signatures are identical
    if param_types1 == param_types2:
        return

    # Create symbol table with two overloaded methods
    symbol_table = SymbolTable()
    qualified_name1 = f"com.test.TestClass.{method_name}"
    qualified_name2 = f"com.test.OtherClass.{method_name}"

    sig1 = f"({', '.join(param_types1)})"
    sig2 = f"({', '.join(param_types2)})"

    symbol_table.add_callable(method_name, qualified_name1, signature=sig1)
    symbol_table.add_callable(method_name, qualified_name2, signature=sig2)

    # Create a partial signature with placeholders (same arity)
    placeholder_sig = f"({', '.join(['?'] * len(param_types1))})"

    # Create resolver
    parser = create_parser()

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    # Match should return ambiguous
    resolved, error_reason = resolver._match_callable(
        method_name, placeholder_sig, symbol_table
    )

    assert resolved is None, (
        f"Expected no resolution for ambiguous overload, got '{resolved}'"
    )
    assert error_reason is not None and "Ambiguous" in error_reason, (
        f"Expected 'Ambiguous' error, got '{error_reason}'"
    )


@given(
    method_name=java_method_name,
    param_types=st.lists(java_type_name, min_size=1, max_size=3),
)
@settings(max_examples=100)
def test_exact_match_resolves_uniquely(
    method_name: str,
    param_types: list[str],
) -> None:
    """
    **Feature: java-overload-resolution, Property 11: Ambiguous Overload Detection**
    **Validates: Requirements 2.3**

    For any method invocation where exactly one callable candidate matches the
    inferred signature exactly, the system SHALL resolve to that callable.
    """
    # Create symbol table with one method
    symbol_table = SymbolTable()
    qualified_name = f"com.test.TestClass.{method_name}"
    sig = f"({', '.join(param_types)})"

    symbol_table.add_callable(method_name, qualified_name, signature=sig)

    # Create resolver
    parser = create_parser()

    def dummy_id_gen(name: str, sig_param: str | None) -> str:
        return f"{name}#{sig_param}" if sig_param else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    # Exact match should resolve
    resolved, error_reason = resolver._match_callable(method_name, sig, symbol_table)

    assert resolved == qualified_name, (
        f"Expected '{qualified_name}' for exact match, got '{resolved}'"
    )
    assert error_reason is None, (
        f"Expected no error for exact match, got '{error_reason}'"
    )


@given(
    method_name=java_method_name,
    param_types=st.lists(java_type_name, min_size=1, max_size=3),
)
@settings(max_examples=100)
def test_single_candidate_resolves_uniquely(
    method_name: str,
    param_types: list[str],
) -> None:
    """
    **Feature: java-overload-resolution, Property 11: Ambiguous Overload Detection**
    **Validates: Requirements 2.3**

    For any method invocation where only one callable candidate exists,
    the system SHALL resolve to that callable without ambiguity.
    """
    # Create symbol table with one method
    symbol_table = SymbolTable()
    qualified_name = f"com.test.TestClass.{method_name}"
    sig = f"({', '.join(param_types)})"

    symbol_table.add_callable(method_name, qualified_name, signature=sig)

    # Create resolver
    parser = create_parser()

    def dummy_id_gen(name: str, sig_param: str | None) -> str:
        return f"{name}#{sig_param}" if sig_param else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    # Match with exact signature should resolve
    resolved, error_reason = resolver._match_callable(method_name, sig, symbol_table)

    assert resolved == qualified_name, (
        f"Expected '{qualified_name}' for single candidate, got '{resolved}'"
    )
    assert error_reason is None, (
        f"Expected no error for single candidate, got '{error_reason}'"
    )


@given(method_name=java_method_name)
@settings(max_examples=100)
def test_no_candidates_returns_not_found(method_name: str) -> None:
    """
    **Feature: java-overload-resolution, Property 11: Ambiguous Overload Detection**
    **Validates: Requirements 2.3**

    For any method invocation where no callable candidates exist in the symbol
    table, the system SHALL return an appropriate error reason.
    """
    # Create empty symbol table
    symbol_table = SymbolTable()

    # Create resolver
    parser = create_parser()

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    # Match should return not found
    resolved, error_reason = resolver._match_callable(
        method_name, "(String)", symbol_table
    )

    assert resolved is None, (
        f"Expected no resolution for missing method, got '{resolved}'"
    )
    assert error_reason == "Method not found in symbol table", (
        f"Expected 'Method not found in symbol table' error, got '{error_reason}'"
    )


@given(
    method_name=java_method_name,
    param_types=st.lists(java_type_name, min_size=1, max_size=3),
    known_indices=st.lists(st.booleans(), min_size=1, max_size=3),
)
@settings(max_examples=100)
def test_partial_signature_with_some_known_types(
    method_name: str,
    param_types: list[str],
    known_indices: list[bool],
) -> None:
    """
    **Feature: java-overload-resolution, Property 11: Ambiguous Overload Detection**
    **Validates: Requirements 2.3**

    For any method invocation with a partial signature (some known types, some
    placeholders), the system SHALL match against callables with compatible
    known types.
    """
    # Ensure same length
    if len(known_indices) != len(param_types):
        known_indices = [True] * len(param_types)

    # Create symbol table with one method
    symbol_table = SymbolTable()
    qualified_name = f"com.test.TestClass.{method_name}"
    declared_sig = f"({', '.join(param_types)})"

    symbol_table.add_callable(method_name, qualified_name, signature=declared_sig)

    # Create partial signature with some placeholders
    inferred_types = [
        param_types[i] if known_indices[i] else "?"
        for i in range(len(param_types))
    ]
    inferred_sig = f"({', '.join(inferred_types)})"

    # Create resolver
    parser = create_parser()

    def dummy_id_gen(name: str, sig: str | None) -> str:
        return f"{name}#{sig}" if sig else name

    resolver = JavaResolver(
        parser=parser,
        project_id="test-project",
        language_type=LanguageType.JAVA,
        id_generator=dummy_id_gen,
    )

    # Should resolve to the single candidate
    resolved, error_reason = resolver._match_callable(
        method_name, inferred_sig, symbol_table
    )

    assert resolved == qualified_name, (
        f"Expected '{qualified_name}' for partial match, got '{resolved}'"
    )
    assert error_reason is None, (
        f"Expected no error for partial match, got '{error_reason}'"
    )
