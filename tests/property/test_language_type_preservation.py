"""Property tests for entity language type preservation.

**Feature: multi-language-type-fix, Property 1: Entity language type preservation on write**
**Validates: Requirements 1.1, 1.2, 1.3**

For any IR containing entities with varying language_type values, when written to Neo4j,
each node's languageType property SHALL equal the corresponding entity's language_type field.
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


pytestmark = pytest.mark.skipif(
    not neo4j_available(),
    reason="Neo4j not available for testing",
)


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


@given(ir=mixed_language_ir())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    deadline=500,
)
def test_entity_language_type_preservation(ir: IR, neo4j_connection: Neo4jConnection) -> None:
    """
    **Feature: multi-language-type-fix, Property 1: Entity language type preservation on write**
    **Validates: Requirements 1.1, 1.2, 1.3**

    For any IR containing entities with varying language_type values, when written to Neo4j,
    each node's languageType property SHALL equal the corresponding entity's language_type field.
    """
    project_id = f"test-lang-{uuid.uuid4().hex[:8]}"

    try:
        writer = GraphWriter(neo4j_connection)
        writer.write_ir(ir, project_id)

        # Verify Module nodes have correct languageType
        for mod_id, module in ir.modules.items():
            query = """
            MATCH (m:Module {id: $id, projectId: $projectId})
            RETURN m.languageType AS languageType
            """
            with neo4j_connection.session() as session:
                result = session.run(query, {"id": mod_id, "projectId": project_id})
                record = result.single()
                assert record is not None, f"Module {mod_id} not found"
                assert record["languageType"] == module.language_type.value, (
                    f"Module {mod_id}: expected languageType={module.language_type.value}, "
                    f"got {record['languageType']}"
                )

        # Verify Type nodes have correct languageType
        for type_id, typ in ir.types.items():
            query = """
            MATCH (t:Type {id: $id, projectId: $projectId})
            RETURN t.languageType AS languageType
            """
            with neo4j_connection.session() as session:
                result = session.run(query, {"id": type_id, "projectId": project_id})
                record = result.single()
                assert record is not None, f"Type {type_id} not found"
                assert record["languageType"] == typ.language_type.value, (
                    f"Type {type_id}: expected languageType={typ.language_type.value}, "
                    f"got {record['languageType']}"
                )

        # Verify Callable nodes have correct languageType
        for call_id, callable in ir.callables.items():
            query = """
            MATCH (c:Callable {id: $id, projectId: $projectId})
            RETURN c.languageType AS languageType
            """
            with neo4j_connection.session() as session:
                result = session.run(query, {"id": call_id, "projectId": project_id})
                record = result.single()
                assert record is not None, f"Callable {call_id} not found"
                assert record["languageType"] == callable.language_type.value, (
                    f"Callable {call_id}: expected languageType={callable.language_type.value}, "
                    f"got {record['languageType']}"
                )

    finally:
        writer.clear_project(project_id)
