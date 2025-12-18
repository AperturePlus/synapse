"""Property tests for resolution determinism.

**Feature: improved-call-resolution, Property 7: Resolution determinism**
**Validates: Requirements 5.1, 5.2, 5.3**

For any codebase, running the resolver multiple times (including with shuffled
symbol table order) SHALL produce identical IR output.
"""

from __future__ import annotations

import random
from typing import Any

from hypothesis import given, settings, strategies as st, HealthCheck

from synapse.adapters.base import FileContext, SymbolTable


# Strategies for generating test data
simple_identifier = st.from_regex(r"[a-z][a-z0-9]{0,4}", fullmatch=True)
simple_package = st.from_regex(r"[a-z]+\.[a-z]+", fullmatch=True)


@st.composite
def qualified_type_name(draw: st.DrawFn) -> str:
    """Generate a qualified type name like 'com.app.User'."""
    package = draw(simple_package)
    type_name = draw(simple_identifier).capitalize()
    return f"{package}.{type_name}"


@st.composite
def symbol_table_data(draw: st.DrawFn) -> dict[str, Any]:
    """Generate data for populating a symbol table.

    Returns:
        Dict with types, callables, and type_hierarchy data.
    """
    package = draw(simple_package)

    # Generate 2-4 types
    num_types = draw(st.integers(min_value=2, max_value=4))
    types: list[tuple[str, str]] = []
    for i in range(num_types):
        type_name = f"Type{i}{draw(simple_identifier).capitalize()}"
        qualified = f"{package}.{type_name}"
        types.append((type_name, qualified))

    # Generate 2-4 methods per type
    callables: list[tuple[str, str, str | None]] = []
    for type_name, qualified_type in types:
        num_methods = draw(st.integers(min_value=2, max_value=4))
        for j in range(num_methods):
            method_name = f"method{j}{draw(simple_identifier)}"
            qualified_method = f"{qualified_type}.{method_name}"
            # Some methods have signatures
            signature = f"({draw(simple_identifier).capitalize()})" if draw(st.booleans()) else None
            callables.append((method_name, qualified_method, signature))

    # Generate type hierarchy (some types extend others)
    hierarchy: dict[str, list[str]] = {}
    if len(types) >= 2:
        # First type extends second type
        hierarchy[types[0][1]] = [types[1][1]]
        if len(types) >= 3:
            # Second type extends third type
            hierarchy[types[1][1]] = [types[2][1]]

    return {
        "package": package,
        "types": types,
        "callables": callables,
        "hierarchy": hierarchy,
    }


def build_symbol_table_with_order(
    data: dict[str, Any], shuffle_seed: int | None = None
) -> SymbolTable:
    """Build a symbol table from data, optionally shuffling insertion order.

    Args:
        data: Symbol table data from symbol_table_data strategy.
        shuffle_seed: If provided, shuffle the insertion order using this seed.

    Returns:
        Populated SymbolTable.
    """
    symbol_table = SymbolTable()

    types = list(data["types"])
    callables = list(data["callables"])
    hierarchy = dict(data["hierarchy"])

    # Shuffle if seed provided
    if shuffle_seed is not None:
        rng = random.Random(shuffle_seed)
        rng.shuffle(types)
        rng.shuffle(callables)

    # Add types
    for short_name, qualified in types:
        symbol_table.add_type(short_name, qualified)

    # Add callables
    for short_name, qualified, signature in callables:
        symbol_table.add_callable(short_name, qualified, signature=signature)

    # Add hierarchy (order doesn't matter for dict)
    for type_name, supertypes in hierarchy.items():
        symbol_table.add_type_hierarchy(type_name, supertypes)

    return symbol_table


@given(data=symbol_table_data(), seed1=st.integers(0, 1000), seed2=st.integers(0, 1000))
@settings(max_examples=100, suppress_health_check=[HealthCheck.large_base_example])
def test_resolve_callable_with_receiver_determinism(
    data: dict[str, Any], seed1: int, seed2: int
) -> None:
    """
    **Feature: improved-call-resolution, Property 7: Resolution determinism**
    **Validates: Requirements 5.1, 5.2, 5.3**

    For any symbol table, resolve_callable_with_receiver SHALL produce
    identical results regardless of symbol table insertion order.
    """
    # Build two symbol tables with different insertion orders
    st1 = build_symbol_table_with_order(data, shuffle_seed=seed1)
    st2 = build_symbol_table_with_order(data, shuffle_seed=seed2)

    # Test resolution for each callable
    for method_name, qualified_method, signature in data["callables"]:
        # Extract receiver type from qualified method name
        parts = qualified_method.rsplit(".", 1)
        if len(parts) == 2:
            receiver_type = parts[0]

            # Resolve with both symbol tables
            result1, error1 = st1.resolve_callable_with_receiver(
                method_name, receiver_type, signature
            )
            result2, error2 = st2.resolve_callable_with_receiver(
                method_name, receiver_type, signature
            )

            # Property: results must be identical
            assert result1 == result2, (
                f"Non-deterministic resolution for {method_name} on {receiver_type}: "
                f"got {result1} vs {result2}"
            )
            assert error1 == error2, (
                f"Non-deterministic error for {method_name} on {receiver_type}: "
                f"got {error1} vs {error2}"
            )


@given(data=symbol_table_data())
@settings(max_examples=100, suppress_health_check=[HealthCheck.large_base_example])
def test_resolve_callable_determinism(data: dict[str, Any]) -> None:
    """
    **Feature: improved-call-resolution, Property 7: Resolution determinism**
    **Validates: Requirements 5.1, 5.3**

    For any symbol table, resolve_callable SHALL produce identical results
    regardless of symbol table insertion order.
    """
    # Build two symbol tables with different insertion orders
    st1 = build_symbol_table_with_order(data, shuffle_seed=42)
    st2 = build_symbol_table_with_order(data, shuffle_seed=123)

    # Test resolution for each callable
    for method_name, qualified_method, _ in data["callables"]:
        # Extract owner type from qualified method name
        parts = qualified_method.rsplit(".", 1)
        if len(parts) == 2:
            owner_type = parts[0]

            # Resolve with both symbol tables
            result1 = st1.resolve_callable(method_name, owner_type)
            result2 = st2.resolve_callable(method_name, owner_type)

            # Property: results must be identical
            assert result1 == result2, (
                f"Non-deterministic resolution for {method_name} with owner {owner_type}: "
                f"got {result1} vs {result2}"
            )


@given(data=symbol_table_data())
@settings(max_examples=100, suppress_health_check=[HealthCheck.large_base_example])
def test_resolve_type_determinism(data: dict[str, Any]) -> None:
    """
    **Feature: improved-call-resolution, Property 7: Resolution determinism**
    **Validates: Requirements 5.1, 5.3**

    For any symbol table, resolve_type SHALL produce identical results
    regardless of symbol table insertion order.
    """
    # Build two symbol tables with different insertion orders
    st1 = build_symbol_table_with_order(data, shuffle_seed=42)
    st2 = build_symbol_table_with_order(data, shuffle_seed=123)

    # Create file context
    context = FileContext(package=data["package"], imports=[])

    # Test resolution for each type
    for short_name, qualified in data["types"]:
        # Resolve with both symbol tables
        result1 = st1.resolve_type(short_name, context)
        result2 = st2.resolve_type(short_name, context)

        # Property: results must be identical
        assert result1 == result2, (
            f"Non-deterministic type resolution for {short_name}: "
            f"got {result1} vs {result2}"
        )


@given(
    method_name=simple_identifier,
    receiver_type=qualified_type_name(),
    num_candidates=st.integers(min_value=2, max_value=5),
)
@settings(max_examples=100)
def test_ambiguous_resolution_determinism(
    method_name: str, receiver_type: str, num_candidates: int
) -> None:
    """
    **Feature: improved-call-resolution, Property 7: Resolution determinism**
    **Validates: Requirements 5.2, 5.3**

    When multiple candidates exist and none can be selected, the resolver
    SHALL consistently mark as unresolved rather than picking arbitrarily.
    """
    # Create multiple symbol tables with different insertion orders
    results: list[tuple[str | None, str | None]] = []

    for seed in range(5):  # Test with 5 different orderings
        symbol_table = SymbolTable()

        # Generate candidate types
        candidates = [f"{receiver_type}.Super{i}" for i in range(num_candidates)]

        # Shuffle candidates before insertion
        rng = random.Random(seed)
        shuffled = list(candidates)
        rng.shuffle(shuffled)

        # Register receiver type with all candidates as supertypes
        symbol_table.add_type_hierarchy(receiver_type, shuffled)

        # Register the same method on all candidate types (in shuffled order)
        for candidate in shuffled:
            qualified_method = f"{candidate}.{method_name}"
            symbol_table.add_callable(method_name, qualified_method)

        # Resolve
        result, error = symbol_table.resolve_callable_with_receiver(
            method_name, receiver_type
        )
        results.append((result, error))

    # Property: all results must be identical
    first_result = results[0]
    for i, result in enumerate(results[1:], 1):
        assert result == first_result, (
            f"Non-deterministic ambiguous resolution: "
            f"ordering 0 gave {first_result}, ordering {i} gave {result}"
        )

    # Also verify it's marked as ambiguous (not resolved to arbitrary candidate)
    assert first_result[0] is None, (
        f"Ambiguous resolution should not resolve, got: {first_result[0]}"
    )
    assert first_result[1] is not None and "Ambiguous" in first_result[1], (
        f"Expected 'Ambiguous' in error, got: {first_result[1]}"
    )
