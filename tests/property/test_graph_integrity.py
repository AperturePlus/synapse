"""Property tests for graph integrity.

**Feature: synapse-mvp, Property 4: Module 层级一致性**
**Feature: synapse-mvp, Property 5: Type 关系完整性**
**Feature: synapse-mvp, Property 6: Callable 调用链完整性**
**Validates: Requirements 2.2, 2.3, 3.3, 3.4, 3.5, 4.3, 8.1**

These tests verify that IR data written to Neo4j maintains structural integrity.
"""

from __future__ import annotations

import uuid

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


# Simple strategies
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


# ============================================================================
# Property 4: Module 层级一致性
# ============================================================================

@st.composite
def nested_modules_ir(draw: st.DrawFn) -> IR:
    """Generate IR with nested module hierarchy."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Create parent module
    parent_id = f"mod_parent_{draw(st.integers(min_value=1, max_value=999))}"
    child_ids = [
        f"mod_child_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        for i in range(draw(st.integers(min_value=1, max_value=3)))
    ]

    parent = Module(
        id=parent_id,
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        path=draw(simple_path),
        language_type=language,
        sub_modules=child_ids,
        declared_types=[],
    )

    children = [
        Module(
            id=cid,
            name=draw(simple_identifier),
            qualified_name=f"{parent.qualified_name}.{draw(simple_identifier)}",
            path=f"{parent.path}/{draw(simple_identifier)}",
            language_type=language,
            sub_modules=[],
            declared_types=[],
        )
        for cid in child_ids
    ]

    modules = {parent.id: parent}
    for child in children:
        modules[child.id] = child

    return IR(
        version="1.0",
        language_type=language,
        modules=modules,
        types={},
        callables={},
        unresolved=[],
    )


@given(ir=nested_modules_ir())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_module_hierarchy_consistency(ir: IR, neo4j_connection: Neo4jConnection) -> None:
    """
    **Feature: synapse-mvp, Property 4: Module 层级一致性**
    **Validates: Requirements 2.2, 2.3**

    For any IR with nested modules, after writing to graph:
    - Every Module should exist as a node
    - Parent-child relationships should exist as CONTAINS edges
    """
    project_id = f"test-module-{uuid.uuid4().hex[:8]}"

    try:
        writer = GraphWriter(neo4j_connection)
        result = writer.write_ir(ir, project_id)

        # Verify all modules exist
        for module_id in ir.modules:
            query = "MATCH (m:Module {id: $id, projectId: $projectId}) RETURN m"
            with neo4j_connection.session() as session:
                res = session.run(query, {"id": module_id, "projectId": project_id})
                assert res.single() is not None, f"Module {module_id} not found in graph"

        # Verify CONTAINS relationships
        for module in ir.modules.values():
            for sub_id in module.sub_modules:
                query = """
                MATCH (p:Module {id: $parentId})-[:CONTAINS]->(c:Module {id: $childId})
                WHERE p.projectId = $projectId
                RETURN p, c
                """
                with neo4j_connection.session() as session:
                    res = session.run(query, {
                        "parentId": module.id,
                        "childId": sub_id,
                        "projectId": project_id,
                    })
                    assert res.single() is not None, (
                        f"CONTAINS relationship missing: {module.id} -> {sub_id}"
                    )

    finally:
        writer.clear_project(project_id)


# ============================================================================
# Property 5: Type 关系完整性
# ============================================================================

@st.composite
def types_with_relationships_ir(draw: st.DrawFn) -> IR:
    """Generate IR with type inheritance/implementation/embedding relationships."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Create base type
    base_id = f"type_base_{draw(st.integers(min_value=1, max_value=999))}"
    base_type = Type(
        id=base_id,
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=TypeKind.CLASS if language == LanguageType.JAVA else TypeKind.STRUCT,
        language_type=language,
        modifiers=[],
        extends=[],
        implements=[],
        embeds=[],
        callables=[],
    )

    # Create interface (for Java) or embedded type (for Go)
    interface_id = f"type_iface_{draw(st.integers(min_value=1, max_value=999))}"
    interface_type = Type(
        id=interface_id,
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=TypeKind.INTERFACE if language == LanguageType.JAVA else TypeKind.STRUCT,
        language_type=language,
        modifiers=[],
        extends=[],
        implements=[],
        embeds=[],
        callables=[],
    )

    # Create derived type that extends base and implements/embeds interface
    derived_id = f"type_derived_{draw(st.integers(min_value=1, max_value=999))}"
    derived_type = Type(
        id=derived_id,
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=TypeKind.CLASS if language == LanguageType.JAVA else TypeKind.STRUCT,
        language_type=language,
        modifiers=[],
        extends=[base_id],
        implements=[interface_id] if language == LanguageType.JAVA else [],
        embeds=[interface_id] if language == LanguageType.GO else [],
        callables=[],
    )

    return IR(
        version="1.0",
        language_type=language,
        modules={},
        types={
            base_id: base_type,
            interface_id: interface_type,
            derived_id: derived_type,
        },
        callables={},
        unresolved=[],
    )


@given(ir=types_with_relationships_ir())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_type_relationship_integrity(ir: IR, neo4j_connection: Neo4jConnection) -> None:
    """
    **Feature: synapse-mvp, Property 5: Type 关系完整性**
    **Validates: Requirements 3.3, 3.4, 3.5**

    For any IR with type relationships, after writing to graph:
    - Every Type should exist as a node
    - EXTENDS relationships should exist for inheritance
    - IMPLEMENTS relationships should exist for interface implementation
    - EMBEDS relationships should exist for Go struct embedding
    """
    project_id = f"test-type-{uuid.uuid4().hex[:8]}"

    try:
        writer = GraphWriter(neo4j_connection)
        writer.write_ir(ir, project_id)

        # Verify all types exist
        for type_id in ir.types:
            query = "MATCH (t:Type {id: $id, projectId: $projectId}) RETURN t"
            with neo4j_connection.session() as session:
                res = session.run(query, {"id": type_id, "projectId": project_id})
                assert res.single() is not None, f"Type {type_id} not found in graph"

        # Verify relationships
        for typ in ir.types.values():
            # Check EXTENDS
            for ext_id in typ.extends:
                query = """
                MATCH (d:Type {id: $derivedId})-[:EXTENDS]->(b:Type {id: $baseId})
                WHERE d.projectId = $projectId
                RETURN d, b
                """
                with neo4j_connection.session() as session:
                    res = session.run(query, {
                        "derivedId": typ.id,
                        "baseId": ext_id,
                        "projectId": project_id,
                    })
                    assert res.single() is not None, (
                        f"EXTENDS relationship missing: {typ.id} -> {ext_id}"
                    )

            # Check IMPLEMENTS
            for impl_id in typ.implements:
                query = """
                MATCH (t:Type {id: $typeId})-[:IMPLEMENTS]->(i:Type {id: $ifaceId})
                WHERE t.projectId = $projectId
                RETURN t, i
                """
                with neo4j_connection.session() as session:
                    res = session.run(query, {
                        "typeId": typ.id,
                        "ifaceId": impl_id,
                        "projectId": project_id,
                    })
                    assert res.single() is not None, (
                        f"IMPLEMENTS relationship missing: {typ.id} -> {impl_id}"
                    )

            # Check EMBEDS
            for embed_id in typ.embeds:
                query = """
                MATCH (t:Type {id: $typeId})-[:EMBEDS]->(e:Type {id: $embedId})
                WHERE t.projectId = $projectId
                RETURN t, e
                """
                with neo4j_connection.session() as session:
                    res = session.run(query, {
                        "typeId": typ.id,
                        "embedId": embed_id,
                        "projectId": project_id,
                    })
                    assert res.single() is not None, (
                        f"EMBEDS relationship missing: {typ.id} -> {embed_id}"
                    )

    finally:
        writer.clear_project(project_id)


# ============================================================================
# Property 6: Callable 调用链完整性
# ============================================================================

@st.composite
def callables_with_calls_ir(draw: st.DrawFn) -> IR:
    """Generate IR with callable call relationships."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Create caller callable
    caller_id = f"call_caller_{draw(st.integers(min_value=1, max_value=999))}"
    
    # Create callee callables
    callee_ids = [
        f"call_callee_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        for i in range(draw(st.integers(min_value=1, max_value=3)))
    ]

    caller = Callable(
        id=caller_id,
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=draw(st.sampled_from(list(CallableKind))),
        language_type=language,
        signature=draw(simple_signature),
        is_static=draw(st.booleans()),
        visibility=draw(st.sampled_from(list(Visibility))),
        return_type=None,
        calls=callee_ids,
        overrides=None,
    )

    callees = [
        Callable(
            id=cid,
            name=draw(simple_identifier),
            qualified_name=draw(simple_qualified_name),
            kind=draw(st.sampled_from(list(CallableKind))),
            language_type=language,
            signature=draw(simple_signature),
            is_static=draw(st.booleans()),
            visibility=draw(st.sampled_from(list(Visibility))),
            return_type=None,
            calls=[],
            overrides=None,
        )
        for cid in callee_ids
    ]

    callables = {caller.id: caller}
    for callee in callees:
        callables[callee.id] = callee

    return IR(
        version="1.0",
        language_type=language,
        modules={},
        types={},
        callables=callables,
        unresolved=[],
    )


@given(ir=callables_with_calls_ir())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_callable_call_chain_integrity(ir: IR, neo4j_connection: Neo4jConnection) -> None:
    """
    **Feature: synapse-mvp, Property 6: Callable 调用链完整性**
    **Validates: Requirements 4.3, 8.1**

    For any IR with call relationships, after writing to graph:
    - Every Callable should exist as a node
    - CALLS relationships should exist for method calls
    - Call chain queries should return all reachable callables
    """
    project_id = f"test-callable-{uuid.uuid4().hex[:8]}"

    try:
        writer = GraphWriter(neo4j_connection)
        writer.write_ir(ir, project_id)

        # Verify all callables exist
        for callable_id in ir.callables:
            query = "MATCH (c:Callable {id: $id, projectId: $projectId}) RETURN c"
            with neo4j_connection.session() as session:
                res = session.run(query, {"id": callable_id, "projectId": project_id})
                assert res.single() is not None, f"Callable {callable_id} not found in graph"

        # Verify CALLS relationships
        for callable in ir.callables.values():
            for call_id in callable.calls:
                query = """
                MATCH (caller:Callable {id: $callerId})-[:CALLS]->(callee:Callable {id: $calleeId})
                WHERE caller.projectId = $projectId
                RETURN caller, callee
                """
                with neo4j_connection.session() as session:
                    res = session.run(query, {
                        "callerId": callable.id,
                        "calleeId": call_id,
                        "projectId": project_id,
                    })
                    assert res.single() is not None, (
                        f"CALLS relationship missing: {callable.id} -> {call_id}"
                    )

        # Verify call chain query returns all callees
        for callable in ir.callables.values():
            if callable.calls:
                query = """
                MATCH (c:Callable {id: $id})-[:CALLS*1..5]->(callee:Callable)
                WHERE c.projectId = $projectId
                RETURN DISTINCT callee.id AS calleeId
                """
                with neo4j_connection.session() as session:
                    res = session.run(query, {"id": callable.id, "projectId": project_id})
                    found_ids = {record["calleeId"] for record in res}
                    
                    # All direct callees should be reachable
                    for call_id in callable.calls:
                        assert call_id in found_ids, (
                            f"Callee {call_id} not reachable from {callable.id}"
                        )

    finally:
        writer.clear_project(project_id)
