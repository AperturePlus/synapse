"""Property tests for IR serialization roundtrip consistency.

**Feature: synapse-mvp, Property 1: IR 序列化往返一致性**
**Validates: Requirements 6.5**

For any valid IR, serialize then deserialize should produce equivalent IR.
"""

from hypothesis import HealthCheck, given, settings, strategies as st

from synapse.core import (
    Callable,
    CallableKind,
    IR,
    LanguageType,
    Module,
    Type,
    TypeKind,
    UnresolvedReference,
    Visibility,
    deserialize,
    serialize,
)


# Simple, fast strategies for identifiers
simple_identifier = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
simple_qualified_name = st.from_regex(r"[a-z]+(\.[a-z]+){0,3}", fullmatch=True)
simple_path = st.from_regex(r"/[a-z]+(/[a-z]+){0,3}", fullmatch=True)
simple_signature = st.from_regex(r"[a-z]+\([a-zA-Z, ]*\)", fullmatch=True)


@st.composite
def module_strategy(draw: st.DrawFn) -> Module:
    """Generate a valid Module."""
    return Module(
        id=f"mod_{draw(st.integers(min_value=1, max_value=9999))}",
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        path=draw(simple_path),
        language_type=draw(st.sampled_from(list(LanguageType))),
        sub_modules=[],
        declared_types=[],
    )


@st.composite
def type_strategy(draw: st.DrawFn) -> Type:
    """Generate a valid Type."""
    return Type(
        id=f"type_{draw(st.integers(min_value=1, max_value=9999))}",
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=draw(st.sampled_from(list(TypeKind))),
        language_type=draw(st.sampled_from(list(LanguageType))),
        modifiers=draw(
            st.lists(
                st.sampled_from(["public", "private", "abstract", "final"]),
                max_size=2,
                unique=True,
            )
        ),
        extends=[],
        implements=[],
        embeds=[],
        callables=[],
    )


@st.composite
def callable_strategy(draw: st.DrawFn) -> Callable:
    """Generate a valid Callable."""
    return Callable(
        id=f"call_{draw(st.integers(min_value=1, max_value=9999))}",
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=draw(st.sampled_from(list(CallableKind))),
        language_type=draw(st.sampled_from(list(LanguageType))),
        signature=draw(simple_signature),
        is_static=draw(st.booleans()),
        visibility=draw(st.sampled_from(list(Visibility))),
        return_type=None,
        calls=[],
        overrides=None,
    )


@st.composite
def unresolved_reference_strategy(draw: st.DrawFn) -> UnresolvedReference:
    """Generate a valid UnresolvedReference."""
    return UnresolvedReference(
        source_callable=f"call_{draw(st.integers(min_value=1, max_value=9999))}",
        target_name=draw(simple_identifier),
        context=draw(st.none() | st.just("some context")),
        reason="Target not found",
    )


@st.composite
def ir_strategy(draw: st.DrawFn) -> IR:
    """Generate a valid IR structure."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Generate small collections for efficiency
    modules_list = draw(st.lists(module_strategy(), min_size=0, max_size=3))
    types_list = draw(st.lists(type_strategy(), min_size=0, max_size=3))
    callables_list = draw(st.lists(callable_strategy(), min_size=0, max_size=3))
    unresolved = draw(st.lists(unresolved_reference_strategy(), min_size=0, max_size=2))

    # Ensure consistent language type
    for m in modules_list:
        m.language_type = language
    for t in types_list:
        t.language_type = language
    for c in callables_list:
        c.language_type = language

    return IR(
        version="1.0",
        language_type=language,
        modules={m.id: m for m in modules_list},
        types={t.id: t for t in types_list},
        callables={c.id: c for c in callables_list},
        unresolved=unresolved,
    )


@given(ir=ir_strategy())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_ir_roundtrip_consistency(ir: IR) -> None:
    """
    **Feature: synapse-mvp, Property 1: IR 序列化往返一致性**
    **Validates: Requirements 6.5**

    For any valid IR, serialize then deserialize should produce equivalent IR.
    """
    # Serialize to JSON
    json_str = serialize(ir)

    # Deserialize back to IR
    ir_restored = deserialize(json_str)

    # Verify equality
    assert ir == ir_restored, "Roundtrip failed: original != restored"
