"""Property tests for IR validator correctness.

**Feature: synapse-mvp, Property 7: IR 验证器正确性**
**Validates: Requirements 7.2**

For any randomly generated IR:
- If IR has valid references (all IDs exist), validator returns valid
- If IR has dangling references (IDs don't exist), validator returns invalid
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
    Visibility,
    validate_ir,
)


# Simple strategies for fast generation
simple_id = st.from_regex(r"[a-z]{3}_[0-9]{1,4}", fullmatch=True)
simple_name = st.from_regex(r"[a-zA-Z][a-zA-Z0-9]{0,8}", fullmatch=True)
simple_qname = st.from_regex(r"[a-z]+(\.[a-z]+){0,2}", fullmatch=True)
simple_path = st.from_regex(r"/[a-z]+(/[a-z]+){0,2}", fullmatch=True)
simple_sig = st.from_regex(r"[a-z]+\(\)", fullmatch=True)


@st.composite
def valid_ir_strategy(draw: st.DrawFn) -> IR:
    """Generate a valid IR with consistent references."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Generate base entities with unique IDs
    num_modules = draw(st.integers(min_value=1, max_value=3))
    num_types = draw(st.integers(min_value=1, max_value=3))
    num_callables = draw(st.integers(min_value=1, max_value=3))

    modules: dict[str, Module] = {}
    types: dict[str, Type] = {}
    callables: dict[str, Callable] = {}

    # Create modules
    for i in range(num_modules):
        mod_id = f"mod_{i}"
        modules[mod_id] = Module(
            id=mod_id,
            name=draw(simple_name),
            qualified_name=draw(simple_qname),
            path=draw(simple_path),
            language_type=language,
            sub_modules=[],
            declared_types=[],
        )

    # Create types
    for i in range(num_types):
        type_id = f"type_{i}"
        types[type_id] = Type(
            id=type_id,
            name=draw(simple_name),
            qualified_name=draw(simple_qname),
            kind=draw(st.sampled_from(list(TypeKind))),
            language_type=language,
            modifiers=[],
            extends=[],
            implements=[],
            embeds=[],
            callables=[],
        )

    # Create callables
    for i in range(num_callables):
        call_id = f"call_{i}"
        callables[call_id] = Callable(
            id=call_id,
            name=draw(simple_name),
            qualified_name=draw(simple_qname),
            kind=draw(st.sampled_from(list(CallableKind))),
            language_type=language,
            signature=draw(simple_sig),
            is_static=draw(st.booleans()),
            visibility=draw(st.sampled_from(list(Visibility))),
            return_type=None,
            calls=[],
            overrides=None,
        )

    # Now add valid references between entities
    module_ids = list(modules.keys())
    type_ids = list(types.keys())
    callable_ids = list(callables.keys())

    # Add valid sub_module references (only to other modules, not self)
    for mod_id, mod in modules.items():
        other_mods = [m for m in module_ids if m != mod_id]
        if other_mods and draw(st.booleans()):
            mod.sub_modules = draw(
                st.lists(st.sampled_from(other_mods), max_size=2, unique=True)
            )

    # Add valid declared_types references
    for mod in modules.values():
        if type_ids and draw(st.booleans()):
            mod.declared_types = draw(
                st.lists(st.sampled_from(type_ids), max_size=2, unique=True)
            )

    # Add valid type references
    for type_id, type_def in types.items():
        other_types = [t for t in type_ids if t != type_id]
        if other_types and draw(st.booleans()):
            type_def.extends = draw(
                st.lists(st.sampled_from(other_types), max_size=1, unique=True)
            )
        if callable_ids and draw(st.booleans()):
            type_def.callables = draw(
                st.lists(st.sampled_from(callable_ids), max_size=2, unique=True)
            )

    # Add valid callable references
    for call_id, call_def in callables.items():
        other_calls = [c for c in callable_ids if c != call_id]
        if other_calls and draw(st.booleans()):
            call_def.calls = draw(
                st.lists(st.sampled_from(other_calls), max_size=2, unique=True)
            )
        if type_ids and draw(st.booleans()):
            call_def.return_type = draw(st.sampled_from(type_ids))

    return IR(
        version="1.0",
        language_type=language,
        modules=modules,
        types=types,
        callables=callables,
        unresolved=[],
    )


@st.composite
def invalid_ir_strategy(draw: st.DrawFn) -> IR:
    """Generate an IR with at least one dangling reference."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Create a minimal valid structure first
    modules: dict[str, Module] = {
        "mod_0": Module(
            id="mod_0",
            name="test",
            qualified_name="test",
            path="/test",
            language_type=language,
            sub_modules=[],
            declared_types=[],
        )
    }
    types: dict[str, Type] = {
        "type_0": Type(
            id="type_0",
            name="Test",
            qualified_name="test.Test",
            kind=TypeKind.CLASS,
            language_type=language,
            modifiers=[],
            extends=[],
            implements=[],
            embeds=[],
            callables=[],
        )
    }
    callables: dict[str, Callable] = {
        "call_0": Callable(
            id="call_0",
            name="test",
            qualified_name="test.Test.test",
            kind=CallableKind.METHOD,
            language_type=language,
            signature="test()",
            is_static=False,
            visibility=Visibility.PUBLIC,
            return_type=None,
            calls=[],
            overrides=None,
        )
    }

    # Introduce a dangling reference
    invalid_ref = "nonexistent_id_12345"
    error_type = draw(
        st.sampled_from(
            [
                "module_sub",
                "module_type",
                "type_extends",
                "type_callable",
                "callable_calls",
                "callable_return",
            ]
        )
    )

    if error_type == "module_sub":
        modules["mod_0"].sub_modules = [invalid_ref]
    elif error_type == "module_type":
        modules["mod_0"].declared_types = [invalid_ref]
    elif error_type == "type_extends":
        types["type_0"].extends = [invalid_ref]
    elif error_type == "type_callable":
        types["type_0"].callables = [invalid_ref]
    elif error_type == "callable_calls":
        callables["call_0"].calls = [invalid_ref]
    elif error_type == "callable_return":
        callables["call_0"].return_type = invalid_ref

    return IR(
        version="1.0",
        language_type=language,
        modules=modules,
        types=types,
        callables=callables,
        unresolved=[],
    )


@given(ir=valid_ir_strategy())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_validator_accepts_valid_ir(ir: IR) -> None:
    """
    **Feature: synapse-mvp, Property 7: IR 验证器正确性**
    **Validates: Requirements 7.2**

    For any IR with valid references (all IDs exist), validator returns valid.
    """
    result = validate_ir(ir)
    assert result.is_valid, f"Valid IR rejected with errors: {result.errors}"


@given(ir=invalid_ir_strategy())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_validator_rejects_invalid_ir(ir: IR) -> None:
    """
    **Feature: synapse-mvp, Property 7: IR 验证器正确性**
    **Validates: Requirements 7.2**

    For any IR with dangling references (IDs don't exist), validator returns invalid.
    """
    result = validate_ir(ir)
    assert not result.is_valid, "Invalid IR was accepted as valid"
    assert len(result.errors) > 0, "Invalid IR has no error details"
