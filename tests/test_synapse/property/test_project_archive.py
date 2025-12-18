"""Property tests for Project archive operations.

Tests the archive-based delete functionality for projects.
"""

from __future__ import annotations

import uuid

from dotenv import load_dotenv

load_dotenv()

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from synapse.graph import Neo4jConfig, Neo4jConnection, ensure_schema
from synapse.services import ProjectService


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
    """Clean up test projects by their paths (including archived)."""
    query = """
    MATCH (p:Project)
    WHERE p.path IN $paths
    DETACH DELETE p
    """
    with connection.session() as session:
        session.run(query, {"paths": paths})


def get_project_archive_state(
    connection: Neo4jConnection, project_id: str
) -> tuple[bool | None, str | None]:
    """Get the archived state and archivedAt timestamp for a project."""
    query = """
    MATCH (p:Project {id: $id})
    RETURN p.archived AS archived, p.archivedAt AS archivedAt
    """
    with connection.session() as session:
        result = session.run(query, {"id": project_id})
        record = result.single()
        if record:
            return record["archived"], record["archivedAt"]
        return None, None


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_archive_operation_sets_correct_state(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 1: Archive operation sets correct state**
    **Validates: Requirements 1.1, 1.2**

    For any valid project, calling delete_project(project_id) should result in
    the project having archived=true and a valid archivedAt timestamp,
    and the method should return True.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Archive the project
        archive_result = service.delete_project(project_id)

        # Should return True on success
        assert archive_result is True

        # Verify the archived state directly in the database
        archived, archived_at = get_project_archive_state(neo4j_connection, project_id)

        # archived should be True
        assert archived is True

        # archivedAt should be set (not None)
        assert archived_at is not None

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])



@given(name=simple_name, path=simple_path, num_calls=st.integers(min_value=2, max_value=5))
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_archive_idempotency(
    name: str,
    path: str,
    num_calls: int,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 2: Archive idempotency**
    **Validates: Requirements 1.4**

    For any project (archived or not), calling delete_project(project_id)
    multiple times should always return True and leave the project in archived state.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Call delete_project multiple times
        for i in range(num_calls):
            archive_result = service.delete_project(project_id)
            # Every call should return True
            assert archive_result is True, f"Call {i + 1} returned False"

        # Verify final state is archived
        archived, archived_at = get_project_archive_state(neo4j_connection, project_id)
        assert archived is True
        assert archived_at is not None

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_archive_nonexistent_project_returns_false(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 1: Archive operation sets correct state**
    **Validates: Requirements 1.3**

    For any non-existent project ID, calling delete_project should return False.
    """
    # Generate a random non-existent project ID
    fake_project_id = uuid.uuid4().hex[:16]

    service = ProjectService(neo4j_connection)

    # Archiving a non-existent project should return False
    result = service.delete_project(fake_project_id)
    assert result is False


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_archived_projects_excluded_from_default_queries(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 3: Archived projects excluded from default queries**
    **Validates: Requirements 2.1, 2.2, 2.3**

    For any set of projects with mixed archived states, list_projects() should only
    return projects where archived is false or null. Similarly, get_by_id() and
    get_by_path() should return None for archived projects.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Verify project is visible before archiving
        assert service.get_by_id(project_id) is not None
        assert service.get_by_path(unique_path) is not None
        assert any(p.id == project_id for p in service.list_projects())

        # Archive the project
        archive_result = service.delete_project(project_id)
        assert archive_result is True

        # Verify archived project is excluded from default queries
        # get_by_id should return None for archived project
        assert service.get_by_id(project_id) is None

        # get_by_path should return None for archived project
        assert service.get_by_path(unique_path) is None

        # list_projects should not include archived project
        projects = service.list_projects()
        assert not any(p.id == project_id for p in projects)

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_include_archived_parameter_returns_all_projects(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 4: Include archived parameter returns all projects**
    **Validates: Requirements 2.4**

    For any set of projects, calling query methods with include_archived=True
    should return all projects regardless of archived state.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Archive the project
        archive_result = service.delete_project(project_id)
        assert archive_result is True

        # Verify archived project is visible with include_archived=True
        # get_by_id with include_archived=True should return the project
        project = service.get_by_id(project_id, include_archived=True)
        assert project is not None
        assert project.id == project_id
        assert project.archived is True

        # get_by_path with include_archived=True should return the project
        project = service.get_by_path(unique_path, include_archived=True)
        assert project is not None
        assert project.id == project_id
        assert project.archived is True

        # list_projects with include_archived=True should include the project
        projects = service.list_projects(include_archived=True)
        assert any(p.id == project_id for p in projects)

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_archive_restore_round_trip(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 5: Archive-restore round trip**
    **Validates: Requirements 1.1, 3.1**

    For any project, archiving then restoring should return the project to active
    state with archived=false and archivedAt=None.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Verify initial state - project is active (not archived)
        initial_project = service.get_by_id(project_id, include_archived=True)
        assert initial_project is not None
        assert initial_project.archived is False
        assert initial_project.archived_at is None

        # Archive the project
        archive_result = service.delete_project(project_id)
        assert archive_result is True

        # Verify archived state
        archived_project = service.get_by_id(project_id, include_archived=True)
        assert archived_project is not None
        assert archived_project.archived is True
        assert archived_project.archived_at is not None

        # Restore the project
        restore_result = service.restore_project(project_id)
        assert restore_result is True

        # Verify restored state - project should be back to active
        restored_project = service.get_by_id(project_id, include_archived=True)
        assert restored_project is not None
        assert restored_project.archived is False
        assert restored_project.archived_at is None

        # Project should be visible in default queries again
        assert service.get_by_id(project_id) is not None
        assert service.get_by_path(unique_path) is not None

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_restore_nonexistent_project_returns_false(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 5: Archive-restore round trip**
    **Validates: Requirements 3.3**

    For any non-existent project ID, calling restore_project should return False.
    """
    # Generate a random non-existent project ID
    fake_project_id = uuid.uuid4().hex[:16]

    service = ProjectService(neo4j_connection)

    # Restoring a non-existent project should return False
    result = service.restore_project(fake_project_id)
    assert result is False


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_restore_non_archived_project_returns_false(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 5: Archive-restore round trip**
    **Validates: Requirements 3.3**

    For any project that is not archived, calling restore_project should return False.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project (not archived)
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Restoring a non-archived project should return False
        restore_result = service.restore_project(project_id)
        assert restore_result is False

        # Project should still be in active state
        project = service.get_by_id(project_id)
        assert project is not None
        assert project.archived is False

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_purge_removes_all_project_data(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 6: Purge removes all project data**
    **Validates: Requirements 4.1, 4.2**

    For any archived project, calling purge_project(project_id) should remove
    the project and all associated data, and subsequent queries should return None.
    """
    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Archive the project first (required before purge)
        archive_result = service.delete_project(project_id)
        assert archive_result is True

        # Verify project exists (archived)
        project = service.get_by_id(project_id, include_archived=True)
        assert project is not None
        assert project.archived is True

        # Purge the project
        purge_result = service.purge_project(project_id)
        assert purge_result is True

        # Verify project is completely removed
        # get_by_id should return None even with include_archived=True
        assert service.get_by_id(project_id, include_archived=True) is None

        # get_by_path should return None even with include_archived=True
        assert service.get_by_path(unique_path, include_archived=True) is None

        # list_projects should not include the project
        projects = service.list_projects(include_archived=True)
        assert not any(p.id == project_id for p in projects)

    finally:
        # Cleanup is not needed since project is purged, but ensure cleanup
        cleanup_test_projects(neo4j_connection, [unique_path])


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_purge_nonexistent_project_returns_false(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 6: Purge removes all project data**
    **Validates: Requirements 4.3**

    For any non-existent project ID, calling purge_project should return False.
    """
    # Generate a random non-existent project ID
    fake_project_id = uuid.uuid4().hex[:16]

    service = ProjectService(neo4j_connection)

    # Purging a non-existent project should return False
    result = service.purge_project(fake_project_id)
    assert result is False


@given(name=simple_name, path=simple_path)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_purge_guard_on_non_archived_projects(
    name: str,
    path: str,
    neo4j_connection: Neo4jConnection,
) -> None:
    """
    **Feature: project-delete-fix, Property 7: Purge guard on non-archived projects**
    **Validates: Requirements 4.4**

    For any non-archived project, calling purge_project(project_id) should
    raise ProjectNotArchivedError.
    """
    from synapse.services import ProjectNotArchivedError

    unique_path = f"{path}/{uuid.uuid4().hex[:8]}"

    try:
        service = ProjectService(neo4j_connection)

        # Create a project (not archived)
        result = service.create_project(name, unique_path)
        assert result.created is True
        project_id = result.project.id

        # Verify project is not archived
        project = service.get_by_id(project_id)
        assert project is not None
        assert project.archived is False

        # Attempting to purge a non-archived project should raise error
        import pytest

        with pytest.raises(ProjectNotArchivedError) as exc_info:
            service.purge_project(project_id)

        # Verify the exception contains the correct project_id
        assert exc_info.value.project_id == project_id

        # Verify project still exists after failed purge attempt
        project = service.get_by_id(project_id)
        assert project is not None

    finally:
        cleanup_test_projects(neo4j_connection, [unique_path])
