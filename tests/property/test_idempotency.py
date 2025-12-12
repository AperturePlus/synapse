"""Property tests for graph write idempotency.

**Feature: synapse-mvp, Property 3: 图写入幂等性**
**Validates: Requirements 5.4**

For any IR data, writing twice to the same project should result in
the same node count as writing once (MERGE semantics).
"""

from __future__ import annotations

import os
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


# Check if Neo4j is available
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


# Skip tests if Neo4j is not available
pytestmark = pytest.mark.skipif(
    not neo4j_available(),
    reason="Neo4j not available for testing",
)


# Simple strategies for identifiers
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
def ir_strategy(draw: st.DrawFn) -> IR:
    """Generate a valid IR structure for idempotency testing."""
    language = draw(st.sampled_from(list(LanguageType)))

    # Generate small collections for efficiency
    modules_list = draw(st.lists(module_strategy(), min_size=1, max_size=3))
    types_list = draw(st.lists(type_strategy(), min_size=0, max_size=3))
    callables_list = draw(st.lists(callable_strategy(), min_size=0, max_size=3))

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
        unresolved=[],
    )


def count_nodes(connection: Neo4jConnection, project_id: str) -> dict[str, int]:
    """Count nodes by label for a project."""
    counts = {}
    for label in ["Module", "Type", "Callable"]:
        query = f"MATCH (n:{label} {{projectId: $projectId}}) RETURN count(n) AS cnt"
        with connection.session() as session:
            result = session.run(query, {"projectId": project_id})
            record = result.single()
            counts[label] = record["cnt"] if record else 0
    return counts


def count_relationships(connection: Neo4jConnection, project_id: str) -> int:
    """Count all relationships for a project."""
    query = """
    MATCH (n {projectId: $projectId})-[r]->()
    RETURN count(r) AS cnt
    """
    with connection.session() as session:
        result = session.run(query, {"projectId": project_id})
        record = result.single()
        return record["cnt"] if record else 0


@pytest.fixture
def neo4j_connection():
    """Provide a Neo4j connection for testing."""
    config = Neo4jConfig.from_env()
    conn = Neo4jConnection(config)
    ensure_schema(conn)
    yield conn
    conn.close()


@given(ir=ir_strategy())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_graph_write_idempotency(ir: IR, neo4j_connection: Neo4jConnection) -> None:
    """
    **Feature: synapse-mvp, Property 3: 图写入幂等性**
    **Validates: Requirements 5.4**

    For any IR data, writing twice to the same project should result in
    the same node count as writing once (MERGE semantics).
    """
    # Use unique project ID for isolation
    project_id = f"test-idempotency-{uuid.uuid4().hex[:8]}"

    try:
        writer = GraphWriter(neo4j_connection)

        # First write
        result1 = writer.write_ir(ir, project_id)
        counts_after_first = count_nodes(neo4j_connection, project_id)
        rels_after_first = count_relationships(neo4j_connection, project_id)

        # Second write (should be idempotent)
        result2 = writer.write_ir(ir, project_id)
        counts_after_second = count_nodes(neo4j_connection, project_id)
        rels_after_second = count_relationships(neo4j_connection, project_id)

        # Verify idempotency: counts should be the same
        assert counts_after_first == counts_after_second, (
            f"Node counts changed after second write: "
            f"{counts_after_first} -> {counts_after_second}"
        )
        assert rels_after_first == rels_after_second, (
            f"Relationship counts changed after second write: "
            f"{rels_after_first} -> {rels_after_second}"
        )

        # Verify write results match expected counts
        assert result1.modules_written == len(ir.modules)
        assert result1.types_written == len(ir.types)
        assert result1.callables_written == len(ir.callables)

    finally:
        # Cleanup: remove test data
        writer.clear_project(project_id)
