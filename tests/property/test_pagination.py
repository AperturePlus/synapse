"""Property tests for query pagination consistency.

**Feature: synapse-mvp, Property 8: 查询分页一致性**
**Validates: Requirements 8.4**

For any query result set, paginating through all pages and merging
should produce the same results as querying without pagination.
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
    Visibility,
)
from synapse.graph import (
    GraphWriter,
    Neo4jConfig,
    Neo4jConnection,
    QueryService,
    ensure_schema,
)


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
def call_chain_ir(draw: st.DrawFn) -> IR:
    """Generate IR with a call chain for pagination testing.

    Creates a root callable that calls multiple other callables,
    enough to test pagination behavior.
    """
    language = draw(st.sampled_from(list(LanguageType)))

    # Create root callable
    root_id = f"call_root_{draw(st.integers(min_value=1, max_value=999))}"

    # Create enough callees to test pagination (5-15 callees)
    num_callees = draw(st.integers(min_value=5, max_value=15))
    callee_ids = [
        f"call_callee_{i}_{draw(st.integers(min_value=1, max_value=999))}"
        for i in range(num_callees)
    ]

    root = Callable(
        id=root_id,
        name=draw(simple_identifier),
        qualified_name=draw(simple_qualified_name),
        kind=CallableKind.METHOD,
        language_type=language,
        signature=draw(simple_signature),
        is_static=False,
        visibility=Visibility.PUBLIC,
        return_type=None,
        calls=callee_ids,
        overrides=None,
    )

    callables = {root.id: root}

    for cid in callee_ids:
        callee = Callable(
            id=cid,
            name=draw(simple_identifier),
            qualified_name=draw(simple_qualified_name),
            kind=CallableKind.METHOD,
            language_type=language,
            signature=draw(simple_signature),
            is_static=False,
            visibility=Visibility.PUBLIC,
            return_type=None,
            calls=[],
            overrides=None,
        )
        callables[callee.id] = callee

    return IR(
        version="1.0",
        language_type=language,
        modules={},
        types={},
        callables=callables,
        unresolved=[],
    )


@given(ir=call_chain_ir())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_pagination_consistency(ir: IR, neo4j_connection: Neo4jConnection) -> None:
    """
    **Feature: synapse-mvp, Property 8: 查询分页一致性**
    **Validates: Requirements 8.4**

    For any query result set, paginating through all pages and merging
    should produce the same results as querying without pagination.
    """
    project_id = f"test-pagination-{uuid.uuid4().hex[:8]}"

    try:
        # Write test data
        writer = GraphWriter(neo4j_connection)
        writer.write_ir(ir, project_id)

        # Find the root callable (the one with calls)
        root_callable = None
        for c in ir.callables.values():
            if c.calls:
                root_callable = c
                break

        if root_callable is None:
            return  # No call chain to test

        query_service = QueryService(neo4j_connection)

        # Get all callees without pagination
        all_callees = query_service.get_all_callees_unpaginated(root_callable.id)
        all_callee_ids = {c.id for c in all_callees}

        # Get callees with pagination (small page size to force multiple pages)
        page_size = 3
        paginated_callee_ids: set[str] = set()
        page = 1
        max_pages = 20  # Safety limit

        while page <= max_pages:
            result = query_service.get_call_chain(
                root_callable.id,
                direction="callees",
                page=page,
                page_size=page_size,
            )

            for callee in result.callees:
                paginated_callee_ids.add(callee.id)

            # Check if we've retrieved all
            if len(result.callees) < page_size:
                break

            page += 1

        # Verify pagination consistency
        assert paginated_callee_ids == all_callee_ids, (
            f"Pagination inconsistency: "
            f"paginated={len(paginated_callee_ids)}, "
            f"unpaginated={len(all_callee_ids)}, "
            f"missing={all_callee_ids - paginated_callee_ids}, "
            f"extra={paginated_callee_ids - all_callee_ids}"
        )

    finally:
        writer.clear_project(project_id)
