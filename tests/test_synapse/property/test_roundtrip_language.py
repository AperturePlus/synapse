"""Property tests for round-trip language type consistency.

**Feature: multi-language-type-fix, Property 3: Round-trip language type consistency**
**Feature: multi-language-type-fix, Property 4: Serialization round-trip preserves language types**
**Validates: Requirements 3.1, 3.2, 1.4**

For any entity written to Neo4j and subsequently queried, the returned languageType
value SHALL equal the original entity's language_type field value.

For any IR structure, serializing to JSON and deserializing back SHALL produce an IR
where all entity language_type fields match the original values.
"""

from __future__ import annotations

import uuid

from dotenv import load_dotenv

load_dotenv()

import pytest
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
    deserialize,
    serialize,
)
from synapse.graph import GraphWriter, Neo4jConfig, Neo4jConnection, ensure_schema


def neo4j_available() -> bool:
    """Check if Neo4j is available for testing."""
    try:
        config = Neo4jConfig.from_env()
        conn = Neo4jConnection(config)
        conn.verify_connectivity()
        conn.close()
        return True
    except Exception:
        return False


# Simple strategies for identifiers
simple_identifier = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,10}", fullmatch=True)
simple_qualified_name = st.from_regex(r"[a-z]+(\.[a-z]+){0,3}", fullmatch=True)
simple_path = st.from_regex(r"/[a-z]+(/[a-z]+){0,3}", fullmatch=True)
simple_signature = st.from_regex(r"[a-z]+\([a-zA-Z, ]*\)", fullmatch=True)


@pytest.fixture
def neo4j_connection():
    """Provide a Neo4j connection for testing."""
    config = Neo4jConfig.from_env()
    conn = Neo4jConnection(config)
    ensure_schema(conn)
    yield conn
    conn.close()


@st.composite
def mixed_language_ir(draw: st.DrawFn) -> IR:
    """Generate IR with entities having different language types.
    
    This simulates a merged IR from scanning both Java and Go code,
    where each entity retains its original language_type.
    """
    # Generate modules with mixed language types
    num_modules = draw(st.integers(min_value=1, max_value=3))
    modules = {}
    for i in range(num_modules):
        lang = draw(st.sampled_from(list(LanguageType)))
        mod_id = f"mod_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        modules[mod_id] = Module(
            id=mod_id,
            name=f"module{i}",
            qualified_name=f"pkg{i}.module{i}",
            path=f"/src/pkg{i}",
            language_type=lang,
            sub_modules=[],
            declared_types=[],
        )

    # Generate types with mixed language types
    num_types = draw(st.integers(min_value=1, max_value=3))
    types = {}
    for i in range(num_types):
        lang = draw(st.sampled_from(list(LanguageType)))
        type_id = f"type_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        types[type_id] = Type(
            id=type_id,
            name=f"Type{i}",
            qualified_name=f"pkg{i}.Type{i}",
            kind=TypeKind.CLASS if lang == LanguageType.JAVA else TypeKind.STRUCT,
            language_type=lang,
            modifiers=[],
            extends=[],
            implements=[],
            embeds=[],
            callables=[],
        )

    # Generate callables with mixed language types
    num_callables = draw(st.integers(min_value=1, max_value=3))
    callables = {}
    for i in range(num_callables):
        lang = draw(st.sampled_from(list(LanguageType)))
        call_id = f"call_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        callables[call_id] = Callable(
            id=call_id,
            name=f"method{i}",
            qualified_name=f"pkg{i}.Type{i}.method{i}",
            kind=CallableKind.METHOD,
            language_type=lang,
            signature=f"method{i}()",
            is_static=False,
            visibility=Visibility.PUBLIC,
            return_type=None,
            calls=[],
            overrides=None,
        )

    # IR root language_type is arbitrary - the bug was using this instead of entity's
    ir_language = draw(st.sampled_from(list(LanguageType)))

    return IR(
        version="1.0",
        language_type=ir_language,
        modules=modules,
        types=types,
        callables=callables,
        unresolved=[],
    )


# =============================================================================
# Property 3: Round-trip language type consistency (Neo4j)
# =============================================================================

neo4j_skip = pytest.mark.skipif(
    not neo4j_available(),
    reason="Neo4j not available for testing",
)


@neo4j_skip
@given(ir=mixed_language_ir())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    deadline=500,
)
def test_roundtrip_language_type_consistency(
    ir: IR, neo4j_connection: Neo4jConnection
) -> None:
    """
    **Feature: multi-language-type-fix, Property 3: Round-trip language type consistency**
    **Validates: Requirements 3.1, 1.4**

    For any entity written to Neo4j and subsequently queried, the returned
    languageType value SHALL equal the original entity's language_type field value.
    """
    project_id = f"test-rt-{uuid.uuid4().hex[:8]}"

    try:
        writer = GraphWriter(neo4j_connection)
        writer.write_ir(ir, project_id)

        # Query back and verify Module languageType matches original
        for mod_id, module in ir.modules.items():
            query = """
            MATCH (m:Module {id: $id, projectId: $projectId})
            RETURN m.languageType AS languageType
            """
            with neo4j_connection.session() as session:
                result = session.run(query, {"id": mod_id, "projectId": project_id})
                record = result.single()
                assert record is not None, f"Module {mod_id} not found after write"
                assert record["languageType"] == module.language_type.value, (
                    f"Round-trip failed for Module {mod_id}: "
                    f"expected {module.language_type.value}, got {record['languageType']}"
                )

        # Query back and verify Type languageType matches original
        for type_id, typ in ir.types.items():
            query = """
            MATCH (t:Type {id: $id, projectId: $projectId})
            RETURN t.languageType AS languageType
            """
            with neo4j_connection.session() as session:
                result = session.run(query, {"id": type_id, "projectId": project_id})
                record = result.single()
                assert record is not None, f"Type {type_id} not found after write"
                assert record["languageType"] == typ.language_type.value, (
                    f"Round-trip failed for Type {type_id}: "
                    f"expected {typ.language_type.value}, got {record['languageType']}"
                )

        # Query back and verify Callable languageType matches original
        for call_id, callable in ir.callables.items():
            query = """
            MATCH (c:Callable {id: $id, projectId: $projectId})
            RETURN c.languageType AS languageType
            """
            with neo4j_connection.session() as session:
                result = session.run(query, {"id": call_id, "projectId": project_id})
                record = result.single()
                assert record is not None, f"Callable {call_id} not found after write"
                assert record["languageType"] == callable.language_type.value, (
                    f"Round-trip failed for Callable {call_id}: "
                    f"expected {callable.language_type.value}, got {record['languageType']}"
                )

    finally:
        writer.clear_project(project_id)



# =============================================================================
# Property 4: Serialization round-trip preserves language types
# =============================================================================


@given(ir=mixed_language_ir())
@settings(max_examples=100)
def test_serialization_roundtrip_preserves_language_types(ir: IR) -> None:
    """
    **Feature: multi-language-type-fix, Property 4: Serialization round-trip preserves language types**
    **Validates: Requirements 3.2**

    For any IR structure, serializing to JSON and deserializing back SHALL produce
    an IR where all entity language_type fields match the original values.
    """
    # Store original language types before serialization
    original_module_langs = {mod_id: m.language_type for mod_id, m in ir.modules.items()}
    original_type_langs = {type_id: t.language_type for type_id, t in ir.types.items()}
    original_callable_langs = {call_id: c.language_type for call_id, c in ir.callables.items()}
    original_ir_lang = ir.language_type

    # Serialize to JSON
    json_str = serialize(ir)

    # Deserialize back to IR
    restored_ir = deserialize(json_str)

    # Verify IR root language_type is preserved
    assert restored_ir.language_type == original_ir_lang, (
        f"IR language_type not preserved: expected {original_ir_lang}, "
        f"got {restored_ir.language_type}"
    )

    # Verify all modules retain their original language_type
    assert len(restored_ir.modules) == len(original_module_langs), (
        f"Module count mismatch: expected {len(original_module_langs)}, "
        f"got {len(restored_ir.modules)}"
    )
    for mod_id, module in restored_ir.modules.items():
        assert mod_id in original_module_langs, f"Unknown module {mod_id} after deserialization"
        assert module.language_type == original_module_langs[mod_id], (
            f"Module {mod_id}: expected language_type={original_module_langs[mod_id]}, "
            f"got {module.language_type}"
        )

    # Verify all types retain their original language_type
    assert len(restored_ir.types) == len(original_type_langs), (
        f"Type count mismatch: expected {len(original_type_langs)}, "
        f"got {len(restored_ir.types)}"
    )
    for type_id, typ in restored_ir.types.items():
        assert type_id in original_type_langs, f"Unknown type {type_id} after deserialization"
        assert typ.language_type == original_type_langs[type_id], (
            f"Type {type_id}: expected language_type={original_type_langs[type_id]}, "
            f"got {typ.language_type}"
        )

    # Verify all callables retain their original language_type
    assert len(restored_ir.callables) == len(original_callable_langs), (
        f"Callable count mismatch: expected {len(original_callable_langs)}, "
        f"got {len(restored_ir.callables)}"
    )
    for call_id, call in restored_ir.callables.items():
        assert call_id in original_callable_langs, (
            f"Unknown callable {call_id} after deserialization"
        )
        assert call.language_type == original_callable_langs[call_id], (
            f"Callable {call_id}: expected language_type={original_callable_langs[call_id]}, "
            f"got {call.language_type}"
        )
