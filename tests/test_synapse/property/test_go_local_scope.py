"""Property tests for Go local scope and type inference.

**Feature: improved-call-resolution**

Tests that verify GoLocalScope correctly tracks variable types from various
Go declaration and assignment patterns.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from synapse.adapters.go import GoLocalScope


# Strategies for generating valid Go identifiers and type names
go_identifier = st.from_regex(r"[a-zA-Z_][a-zA-Z0-9_]{0,15}", fullmatch=True)
go_type_name = st.sampled_from([
    "int", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64",
    "float32", "float64", "string", "bool", "byte", "rune",
    "error", "any", "User", "Config", "Service", "Handler",
    "*User", "*Config", "[]int", "[]string", "map[string]int",
])


@st.composite
def variable_list_strategy(draw: st.DrawFn) -> list[tuple[str, str]]:
    """Generate a list of unique variable (name, type) pairs."""
    count = draw(st.integers(min_value=0, max_value=10))
    names = draw(
        st.lists(go_identifier, min_size=count, max_size=count, unique=True)
    )
    types = draw(st.lists(go_type_name, min_size=count, max_size=count))
    return list(zip(names, types))


@given(variables=variable_list_strategy())
@settings(max_examples=100)
def test_go_scope_building_completeness(
    variables: list[tuple[str, str]],
) -> None:
    """
    **Feature: improved-call-resolution, Property 4: Go type inference from assignment**
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

    For any Go variable with a declared type added to GoLocalScope, the scope
    SHALL contain the correct type mapping and return the type when queried.
    """
    scope = GoLocalScope()

    # Add all variables
    for name, type_name in variables:
        scope.add_variable(name, type_name)

    # Verify all variables are retrievable with correct types
    for name, expected_type in variables:
        actual_type = scope.get_type(name)
        assert actual_type == expected_type, (
            f"Variable '{name}' expected type '{expected_type}', got '{actual_type}'"
        )

    # Verify unknown names return None
    assert scope.get_type("__nonexistent_var__") is None


@given(
    variables=variable_list_strategy(),
    extra_var=st.tuples(go_identifier, go_type_name),
)
@settings(max_examples=100)
def test_go_scope_copy_isolation(
    variables: list[tuple[str, str]],
    extra_var: tuple[str, str],
) -> None:
    """
    **Feature: improved-call-resolution, Property 4: Go type inference from assignment**
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

    For any GoLocalScope, creating a copy and modifying the copy SHALL NOT affect
    the original scope. This ensures nested scopes (blocks, closures) are isolated.
    """
    original = GoLocalScope()

    # Add variables to original
    for name, type_name in variables:
        original.add_variable(name, type_name)

    # Create a copy
    copied = original.copy()

    # Add extra variable to copy only
    extra_name, extra_type = extra_var
    copied.add_variable(extra_name, extra_type)

    # Verify original still has all its entries
    for name, expected_type in variables:
        assert original.get_type(name) == expected_type

    # Verify copy has the extra variable
    assert copied.get_type(extra_name) == extra_type

    # Verify original does NOT have the extra variable (unless it was already there)
    original_had_extra = any(name == extra_name for name, _ in variables)
    if not original_had_extra:
        assert original.get_type(extra_name) is None, (
            f"Original scope should not have '{extra_name}' after copy modification"
        )


@given(
    var_name=go_identifier,
    initial_type=go_type_name,
    new_type=go_type_name,
)
@settings(max_examples=100)
def test_go_scope_variable_shadowing(
    var_name: str,
    initial_type: str,
    new_type: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 4: Go type inference from assignment**
    **Validates: Requirements 2.1, 2.4**

    For any variable that is re-declared in a nested scope (shadowing), the
    inner scope SHALL have the new type while the outer scope retains the
    original type.
    """
    outer_scope = GoLocalScope()
    outer_scope.add_variable(var_name, initial_type)

    # Create inner scope (copy of outer)
    inner_scope = outer_scope.copy()
    # Shadow the variable with a new type
    inner_scope.add_variable(var_name, new_type)

    # Inner scope should have the new type
    assert inner_scope.get_type(var_name) == new_type, (
        f"Inner scope should have type '{new_type}' for '{var_name}'"
    )

    # Outer scope should retain the original type
    assert outer_scope.get_type(var_name) == initial_type, (
        f"Outer scope should retain type '{initial_type}' for '{var_name}'"
    )


@given(var_name=go_identifier)
@settings(max_examples=100)
def test_go_scope_unknown_variable_returns_none(var_name: str) -> None:
    """
    **Feature: improved-call-resolution, Property 4: Go type inference from assignment**
    **Validates: Requirements 2.1**

    For any variable name not in scope, GoLocalScope.get_type SHALL return None.
    """
    scope = GoLocalScope()

    # Empty scope should return None for any variable
    result = scope.get_type(var_name)
    assert result is None, (
        f"Expected None for unknown variable '{var_name}', got '{result}'"
    )


@given(
    var_name=go_identifier,
    var_type=go_type_name,
)
@settings(max_examples=100)
def test_go_scope_explicit_type_declaration(
    var_name: str,
    var_type: str,
) -> None:
    """
    **Feature: improved-call-resolution, Property 4: Go type inference from assignment**
    **Validates: Requirements 2.1**

    WHEN a variable is declared with an explicit type (var x Type)
    THEN the GoLocalScope SHALL record the variable-to-type mapping correctly.
    """
    scope = GoLocalScope()

    # Simulate: var x Type
    scope.add_variable(var_name, var_type)

    result = scope.get_type(var_name)
    assert result == var_type, (
        f"Expected type '{var_type}' for variable '{var_name}', got '{result}'"
    )
