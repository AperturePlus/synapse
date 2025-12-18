"""Property tests for type hierarchy and receiver type resolution.

**Feature: improved-call-resolution, Property 1: Receiver type resolution**
**Validates: Requirements 1.1, 1.4**

For any method call on a variable with a known type, the resolved target SHALL be
a method defined on that type or one of its supertypes.
"""

from hypothesis import given, settings, strategies as st

from synapse.adapters.base import SymbolTable


# Strategies for generating test data
simple_identifier = st.from_regex(r"[a-z][a-z0-9]{0,8}", fullmatch=True)
simple_package = st.from_regex(r"[a-z]+(\.[a-z]+){0,2}", fullmatch=True)


@st.composite
def qualified_type_name(draw: st.DrawFn) -> str:
    """Generate a qualified type name like 'com.app.User'."""
    package = draw(simple_package)
    type_name = draw(simple_identifier).capitalize()
    return f"{package}.{type_name}"


@st.composite
def type_hierarchy_data(draw: st.DrawFn) -> tuple[str, list[str], str, str]:
    """Generate type hierarchy test data.

    Returns:
        Tuple of (receiver_type, supertypes, method_name, expected_owner)
        where expected_owner is one of receiver_type or supertypes.
    """
    receiver_type = draw(qualified_type_name())
    num_supertypes = draw(st.integers(min_value=0, max_value=3))
    supertypes = [draw(qualified_type_name()) for _ in range(num_supertypes)]

    # Ensure supertypes are unique and different from receiver
    supertypes = [s for s in supertypes if s != receiver_type]
    supertypes = list(dict.fromkeys(supertypes))  # Remove duplicates

    method_name = draw(simple_identifier)

    # Pick which type owns the method (receiver or one of supertypes)
    all_types = [receiver_type] + supertypes
    expected_owner = draw(st.sampled_from(all_types))

    return (receiver_type, supertypes, method_name, expected_owner)


@given(data=type_hierarchy_data())
@settings(max_examples=100)
def test_receiver_type_resolution(data: tuple[str, list[str], str, str]) -> None:
    """
    **Feature: improved-call-resolution, Property 1: Receiver type resolution**
    **Validates: Requirements 1.1, 1.4**

    For any method call on a variable with a known type, the resolved target SHALL be
    a method defined on that type or one of its supertypes.
    """
    receiver_type, supertypes, method_name, expected_owner = data

    # Build symbol table with type hierarchy
    symbol_table = SymbolTable()

    # Register the type hierarchy
    if supertypes:
        symbol_table.add_type_hierarchy(receiver_type, supertypes)

    # Register the method on the expected owner
    qualified_method = f"{expected_owner}.{method_name}"
    symbol_table.add_callable(method_name, qualified_method)

    # Resolve the method call
    resolved, error = symbol_table.resolve_callable_with_receiver(
        method_name, receiver_type
    )

    # Property: resolved target must be on receiver type or its supertypes
    assert error is None, f"Expected resolution but got error: {error}"
    assert resolved is not None, "Expected resolved callable"

    # Extract the owner type from the resolved qualified name
    resolved_owner = resolved.rsplit(".", 1)[0]
    valid_owners = [receiver_type] + supertypes

    assert resolved_owner in valid_owners, (
        f"Resolved method owner '{resolved_owner}' not in valid owners: {valid_owners}"
    )


@given(
    receiver_type=qualified_type_name(),
    method_name=simple_identifier,
)
@settings(max_examples=100)
def test_unknown_receiver_returns_error(receiver_type: str, method_name: str) -> None:
    """
    **Feature: improved-call-resolution, Property 2: Unknown receiver produces unresolved**
    **Validates: Requirements 1.2, 3.3**

    For any method call on a variable whose type cannot be determined,
    the call SHALL be recorded as unresolved (not resolved to an arbitrary candidate).
    """
    symbol_table = SymbolTable()

    # Register a method on some type
    qualified_method = f"{receiver_type}.{method_name}"
    symbol_table.add_callable(method_name, qualified_method)

    # Try to resolve with unknown receiver (None)
    resolved, error = symbol_table.resolve_callable_with_receiver(method_name, None)

    # Property: unknown receiver must produce error, not arbitrary resolution
    assert resolved is None, "Should not resolve with unknown receiver"
    assert error == "Unknown receiver type", f"Expected 'Unknown receiver type', got: {error}"
