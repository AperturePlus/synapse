"""Property tests for Project uniqueness constraint.

**Feature: synapse-mvp, Property 2: Project 唯一性约束**
**Validates: Requirements 1.2, 1.3**

For any two Project creation requests:
- If they have the same path, the second request should be rejected
- If they have different paths, both projects should have different IDs
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from synapse.graph import Neo4jConfig, Neo4jConnection, ensure_schema
from synapse.services import ProjectExistsError, ProjectService


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


# Simple strategies for project attributes
simple_name = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_-]{0,20}", fullmatch=True)
simple_path = st.from_regex(r"/[a-z]+(/[a-z]+){0,4}", fullmatch=True)


@pytest.fixture
def neo4j_connection():
    """Provide a Neo4j connection for testing."""
    config = Neo4jConfig.from_env()
    conn = Neo4jConnection(config)
    ensure_schema(conn)
    yield conn
    conn.close()



def cleanup_test_projects(connection: Neo4jConnection, paths: list[str]) -> None:
    """Clean up test projects by their paths."""
    query = """
    MATCH (p:Project)
    WHERE p.path IN $paths
    DETACH DELETE p
    """
    with connection.session() as session:
        session.run(query, {"paths": paths})


@given(
    name1=simple_name,
    name2=simple_name,
    path=simple_path,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_duplicate_path_rejected(
    name1: str,
    name2: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: synapse-mvp, Property 2: Project 唯一性约束**
    **Validates: Requirements 1.2, 1.3**

    For any path, creating a second project with the same path should be rejected.
    """
    # Make path unique per test run to avoid conflicts
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # First creation should succeed
        result1 = service.create_project(name1, unique_path)
        assert result1.created is True
        assert result1.project.path == unique_path

        # Second creation with same path should raise ProjectExistsError
        with pytest.raises(ProjectExistsError) as exc_info:
            service.create_project(name2, unique_path)

        # Verify the error contains the existing project info
        assert exc_info.value.existing_project.id == result1.project.id
        assert exc_info.value.existing_project.path == unique_path

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(
    name1=simple_name,
    name2=simple_name,
    path1=simple_path,
    path2=simple_path,
)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_different_paths_different_ids(
    name1: str,
    name2: str,
    path1: str,
    path2: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: synapse-mvp, Property 2: Project 唯一性约束**
    **Validates: Requirements 1.2, 1.3**

    For any two different paths, the created projects should have different IDs.
    """
    # Make paths unique per test run
    unique_suffix = uuid.uuid4().hex[:8]
    unique_path1 = f"{path1}/a_{unique_suffix}"
    unique_path2 = f"{path2}/b_{unique_suffix}"

    # Ensure paths are actually different
    if unique_path1 == unique_path2:
        unique_path2 = f"{path2}/c_{unique_suffix}"

    try:
        service = ProjectService(neo4j_connection)

        # Create both projects
        result1 = service.create_project(name1, unique_path1)
        result2 = service.create_project(name2, unique_path2)

        # Both should be created successfully
        assert result1.created is True
        assert result2.created is True

        # IDs should be different
        assert result1.project.id != result2.project.id

        # Paths should be preserved correctly
        assert result1.project.path == unique_path1
        assert result2.project.path == unique_path2

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path1, unique_path2])
