"""Property tests for IR merge language type preservation.

**Feature: multi-language-type-fix, Property 2: IR merge preserves entity language types**
**Validates: Requirements 2.1, 2.2**

For any two IR structures with different language_type values at the root level,
when merged, all entities from both IRs SHALL retain their original language_type
field values unchanged.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from synapse.core import (
    Callable,
    CallableKind,
    IR,
    LanguageType,
    Module,
    Type,
    TypeKind,
    Visibility,
)


@st.composite
def single_language_ir(draw: st.DrawFn, language: LanguageType) -> IR:
    """Generate an IR with all entities having the specified language type."""
    # Generate modules
    num_modules = draw(st.integers(min_value=1, max_value=3))
    modules = {}
    for i in range(num_modules):
        mod_id = f"{language.value}_mod_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        modules[mod_id] = Module(
            id=mod_id,
            name=f"module{i}",
            qualified_name=f"{language.value}.pkg{i}.module{i}",
            path=f"/src/{language.value}/pkg{i}",
            language_type=language,
            sub_modules=[],
            declared_types=[],
        )

    # Generate types
    num_types = draw(st.integers(min_value=1, max_value=3))
    types = {}
    for i in range(num_types):
        type_id = f"{language.value}_type_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        types[type_id] = Type(
            id=type_id,
            name=f"Type{i}",
            qualified_name=f"{language.value}.pkg{i}.Type{i}",
            kind=TypeKind.CLASS if language == LanguageType.JAVA else TypeKind.STRUCT,
            language_type=language,
            modifiers=[],
            extends=[],
            implements=[],
            embeds=[],
            callables=[],
        )

    # Generate callables
    num_callables = draw(st.integers(min_value=1, max_value=3))
    callables = {}
    for i in range(num_callables):
        call_id = f"{language.value}_call_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        callables[call_id] = Callable(
            id=call_id,
            name=f"method{i}",
            qualified_name=f"{language.value}.pkg{i}.Type{i}.method{i}",
            kind=CallableKind.METHOD,
            language_type=language,
            signature=f"method{i}()",
            is_static=False,
            visibility=Visibility.PUBLIC,
            return_type=None,
            calls=[],
            overrides=None,
        )

    return IR(
        version="1.0",
        language_type=language,
        modules=modules,
        types=types,
        callables=callables,
        unresolved=[],
    )


@st.composite
def two_different_language_irs(draw: st.DrawFn) -> tuple[IR, IR]:
    """Generate two IRs with different root language types."""
    # First IR is Java
    java_ir = draw(single_language_ir(LanguageType.JAVA))
    # Second IR is Go
    go_ir = draw(single_language_ir(LanguageType.GO))
    return java_ir, go_ir


@given(irs=two_different_language_irs())
@settings(max_examples=100)
def test_ir_merge_preserves_entity_language_types(irs: tuple[IR, IR]) -> None:
    """
    **Feature: multi-language-type-fix, Property 2: IR merge preserves entity language types**
    **Validates: Requirements 2.1, 2.2**

    For any two IR structures with different language_type values at the root level,
    when merged, all entities from both IRs SHALL retain their original language_type
    field values unchanged.
    """
    java_ir, go_ir = irs

    # Store original language types before merge
    original_module_langs = {}
    original_type_langs = {}
    original_callable_langs = {}

    for mod_id, module in java_ir.modules.items():
        original_module_langs[mod_id] = module.language_type
    for mod_id, module in go_ir.modules.items():
        original_module_langs[mod_id] = module.language_type

    for type_id, typ in java_ir.types.items():
        original_type_langs[type_id] = typ.language_type
    for type_id, typ in go_ir.types.items():
        original_type_langs[type_id] = typ.language_type

    for call_id, call in java_ir.callables.items():
        original_callable_langs[call_id] = call.language_type
    for call_id, call in go_ir.callables.items():
        original_callable_langs[call_id] = call.language_type

    # Merge the IRs
    merged_ir = java_ir.merge(go_ir)

    # Verify all modules retain their original language_type
    for mod_id, module in merged_ir.modules.items():
        assert mod_id in original_module_langs, f"Unknown module {mod_id} in merged IR"
        assert module.language_type == original_module_langs[mod_id], (
            f"Module {mod_id}: expected language_type={original_module_langs[mod_id]}, "
            f"got {module.language_type}"
        )

    # Verify all types retain their original language_type
    for type_id, typ in merged_ir.types.items():
        assert type_id in original_type_langs, f"Unknown type {type_id} in merged IR"
        assert typ.language_type == original_type_langs[type_id], (
            f"Type {type_id}: expected language_type={original_type_langs[type_id]}, "
            f"got {typ.language_type}"
        )

    # Verify all callables retain their original language_type
    for call_id, call in merged_ir.callables.items():
        assert call_id in original_callable_langs, f"Unknown callable {call_id} in merged IR"
        assert call.language_type == original_callable_langs[call_id], (
            f"Callable {call_id}: expected language_type={original_callable_langs[call_id]}, "
            f"got {call.language_type}"
        )

    # Verify merged IR contains entities from both languages
    java_modules = [m for m in merged_ir.modules.values() if m.language_type == LanguageType.JAVA]
    go_modules = [m for m in merged_ir.modules.values() if m.language_type == LanguageType.GO]
    assert len(java_modules) > 0, "Merged IR should contain Java modules"
    assert len(go_modules) > 0, "Merged IR should contain Go modules"

    java_types = [t for t in merged_ir.types.values() if t.language_type == LanguageType.JAVA]
    go_types = [t for t in merged_ir.types.values() if t.language_type == LanguageType.GO]
    assert len(java_types) > 0, "Merged IR should contain Java types"
    assert len(go_types) > 0, "Merged IR should contain Go types"

    java_callables = [
        c for c in merged_ir.callables.values() if c.language_type == LanguageType.JAVA
    ]
    go_callables = [c for c in merged_ir.callables.values() if c.language_type == LanguageType.GO]
    assert len(java_callables) > 0, "Merged IR should contain Java callables"
    assert len(go_callables) > 0, "Merged IR should contain Go callables"
