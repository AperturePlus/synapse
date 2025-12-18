"""Property tests for ambiguity tracking in call resolution.

**Feature: improved-call-resolution, Property 5: Ambiguity tracking**
**Validates: Requirements 3.1, 3.2**

For any call site where multiple callables match with equal confidence,
the resolver SHALL record an UnresolvedReference with reason containing
"Ambiguous" and the candidate count.
"""

from hypothesis import given, settings, strategies as st, HealthCheck

from synapse.adapters.base import SymbolTable


# Strategies for generating test data - simplified for performance
simple_identifier = st.from_regex(r"[a-z][a-z0-9]{0,4}", fullmatch=True)
simple_package = st.from_regex(r"[a-z]+\.[a-z]+", fullmatch=True)


@st.composite
def qualified_type_name(draw: st.DrawFn) -> str:
    """Generate a qualified type name like 'com.app.User'."""
    package = draw(simple_package)
    type_name = draw(simple_identifier).capitalize()
    return f"{package}.{type_name}"


@st.composite
def ambiguous_method_data(draw: st.DrawFn) -> tuple[str, str, list[str]]:
    """Generate data for ambiguous method resolution.

    Returns:
        Tuple of (receiver_type, method_name, owner_types)
        where owner_types contains 2+ types that all have the same method.
    """
    # Use simpler generation to avoid health check issues
    package = draw(simple_package)
    receiver_name = draw(simple_identifier).capitalize()
    receiver_type = f"{package}.{receiver_name}"
    method_name = draw(simple_identifier)

    # Generate exactly 2-3 different types
    num_owners = draw(st.integers(min_value=2, max_value=3))
    owner_types = []
    for i in range(num_owners):
        owner_name = f"Owner{i}{draw(simple_identifier).capitalize()}"
        owner = f"{package}.{owner_name}"
        owner_types.append(owner)

    return (receiver_type, method_name, owner_types)


@given(data=ambiguous_method_data())
@settings(max_examples=100, suppress_health_check=[HealthCheck.large_base_example])
def test_ambiguous_methods_on_supertypes_returns_ambiguous(
    data: tuple[str, str, list[str]]
) -> None:
    """
    **Feature: improved-call-resolution, Property 5: Ambiguity tracking**
    **Validates: Requirements 3.1, 3.2**

    For any call site where multiple callables match with equal confidence,
    the resolver SHALL record an UnresolvedReference with reason containing
    "Ambiguous" and the candidate count.
    """
    receiver_type, method_name, owner_types = data

    # Build symbol table with type hierarchy
    symbol_table = SymbolTable()

    # Register all owner types as supertypes of receiver
    symbol_table.add_type_hierarchy(receiver_type, owner_types)

    # Register the same method on all owner types
    for owner in owner_types:
        qualified_method = f"{owner}.{method_name}"
        symbol_table.add_callable(method_name, qualified_method)

    # Resolve the method call
    resolved, error = symbol_table.resolve_callable_with_receiver(
        method_name, receiver_type
    )

    # Property: multiple matches must produce ambiguous error
    assert resolved is None, (
        f"Should not resolve ambiguous method, got: {resolved}"
    )
    assert error is not None, "Expected error for ambiguous resolution"
    assert "Ambiguous" in error, f"Expected 'Ambiguous' in error, got: {error}"
    assert str(len(owner_types)) in error, (
        f"Expected candidate count {len(owner_types)} in error, got: {error}"
    )


@given(
    receiver_type=qualified_type_name(),
    method_name=simple_identifier,
    signature=st.from_regex(r"\([A-Z][a-z]+\)", fullmatch=True),
)
@settings(max_examples=100)
def test_ambiguous_overloads_with_same_signature_returns_ambiguous(
    receiver_type: str, method_name: str, signature: str
) -> None:
    """
    **Feature: improved-call-resolution, Property 5: Ambiguity tracking**
    **Validates: Requirements 3.1, 3.2**

    For any call site where multiple overloads match the same signature,
    the resolver SHALL record an UnresolvedReference with reason containing
    "Ambiguous" and the candidate count.
    """
    symbol_table = SymbolTable()

    # Create two different types with the same method and signature
    type1 = f"{receiver_type}1"
    type2 = f"{receiver_type}2"

    # Register both as supertypes
    symbol_table.add_type_hierarchy(receiver_type, [type1, type2])

    # Register the same method with same signature on both types
    qualified_method1 = f"{type1}.{method_name}"
    qualified_method2 = f"{type2}.{method_name}"
    symbol_table.add_callable(method_name, qualified_method1, signature=signature)
    symbol_table.add_callable(method_name, qualified_method2, signature=signature)

    # Resolve with signature
    resolved, error = symbol_table.resolve_callable_with_receiver(
        method_name, receiver_type, signature=signature
    )

    # Property: multiple signature matches must produce ambiguous error
    assert resolved is None, (
        f"Should not resolve ambiguous overload, got: {resolved}"
    )
    assert error is not None, "Expected error for ambiguous resolution"
    assert "Ambiguous" in error, f"Expected 'Ambiguous' in error, got: {error}"
    assert "2" in error, f"Expected '2' candidates in error, got: {error}"


@given(
    receiver_type=qualified_type_name(),
    method_name=simple_identifier,
)
@settings(max_examples=100)
def test_missing_type_info_returns_specific_reason(
    receiver_type: str, method_name: str
) -> None:
    """
    **Feature: improved-call-resolution, Property 5: Ambiguity tracking**
    **Validates: Requirements 3.2**

    When a call cannot be resolved due to missing type information,
    the resolver SHALL record the specific reason in the UnresolvedReference.
    """
    symbol_table = SymbolTable()

    # Register a method on a different type (not the receiver)
    other_type = f"other.{receiver_type}"
    qualified_method = f"{other_type}.{method_name}"
    symbol_table.add_callable(method_name, qualified_method)

    # Try to resolve on receiver type (which doesn't have the method)
    resolved, error = symbol_table.resolve_callable_with_receiver(
        method_name, receiver_type
    )

    # Property: missing method should produce specific error
    assert resolved is None, f"Should not resolve missing method, got: {resolved}"
    assert error is not None, "Expected error for missing method"
    assert "not found" in error.lower(), (
        f"Expected 'not found' in error, got: {error}"
    )


@given(method_name=simple_identifier)
@settings(max_examples=100)
def test_no_candidates_returns_method_not_found(method_name: str) -> None:
    """
    **Feature: improved-call-resolution, Property 5: Ambiguity tracking**
    **Validates: Requirements 3.2**

    When no callables exist with the given name, the resolver SHALL
    record "Method not found" as the reason.
    """
    symbol_table = SymbolTable()

    # Empty symbol table - no methods registered
    resolved, error = symbol_table.resolve_callable_with_receiver(
        method_name, "com.app.SomeType"
    )

    # Property: no candidates should produce "Method not found" error
    assert resolved is None, f"Should not resolve non-existent method, got: {resolved}"
    assert error is not None, "Expected error for non-existent method"
    assert "not found" in error.lower(), (
        f"Expected 'not found' in error, got: {error}"
    )
