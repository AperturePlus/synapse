"""Project management service for Synapse.

This module provides the ProjectService for managing code projects,
including registration, querying, and deletion operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection


class Project(BaseModel):
    """Project entity representing a code repository."""

    id: str = Field(..., description="Unique project identifier")
    name: str = Field(..., description="Project name")
    path: str = Field(..., description="File system path")
    created_at: datetime = Field(..., description="Creation timestamp")


class ProjectExistsError(Exception):
    """Raised when attempting to create a project with duplicate path."""

    def __init__(self, existing_project: Project) -> None:
        self.existing_project = existing_project
        super().__init__(f"Project already exists at path: {existing_project.path}")


class ProjectNotFoundError(Exception):
    """Raised when a project is not found."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Project not found: {identifier}")


@dataclass
class ProjectCreateResult:
    """Result of project creation operation."""

    project: Project
    created: bool  # True if newly created, False if already existed



class ProjectService:
    """Service for managing code projects.

    Handles project registration, querying, and deletion with Neo4j persistence.
    Enforces unique path constraint for projects.
    """

    def __init__(self, connection: Neo4jConnection) -> None:
        """Initialize project service.

        Args:
            connection: Neo4j connection instance.
        """
        self._connection = connection

    def create_project(self, name: str, path: str) -> ProjectCreateResult:
        """Create a new project or return existing one.

        Args:
            name: Project name.
            path: File system path (must be unique).

        Returns:
            ProjectCreateResult with project and creation status.

        Raises:
            ProjectExistsError: If a project with the same path already exists.
        """
        # Check for existing project with same path
        existing = self.get_by_path(path)
        if existing:
            raise ProjectExistsError(existing)

        # Generate unique ID and timestamp
        import hashlib

        from synapse.core.config import get_config

        config = get_config()
        project_id = hashlib.sha256(path.encode()).hexdigest()[: config.id_length]
        created_at = datetime.now(timezone.utc)

        # Create project node
        query = """
        CREATE (p:Project {
            id: $id,
            name: $name,
            path: $path,
            createdAt: $createdAt
        })
        RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt
        """

        with self._connection.session() as session:
            result = session.run(
                query,
                {
                    "id": project_id,
                    "name": name,
                    "path": path,
                    "createdAt": created_at.isoformat(),
                },
            )
            record = result.single()

        project = Project(
            id=record["id"],
            name=record["name"],
            path=record["path"],
            created_at=datetime.fromisoformat(record["createdAt"]),
        )

        return ProjectCreateResult(project=project, created=True)

    def get_by_id(self, project_id: str) -> Project | None:
        """Get a project by its ID.

        Args:
            project_id: Project identifier.

        Returns:
            Project if found, None otherwise.
        """
        query = """
        MATCH (p:Project {id: $id})
        RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt
        """

        with self._connection.session() as session:
            result = session.run(query, {"id": project_id})
            record = result.single()

        if not record:
            return None

        return Project(
            id=record["id"],
            name=record["name"],
            path=record["path"],
            created_at=datetime.fromisoformat(record["createdAt"]),
        )

    def get_by_path(self, path: str) -> Project | None:
        """Get a project by its file system path.

        Args:
            path: File system path.

        Returns:
            Project if found, None otherwise.
        """
        query = """
        MATCH (p:Project {path: $path})
        RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt
        """

        with self._connection.session() as session:
            result = session.run(query, {"path": path})
            record = result.single()

        if not record:
            return None

        return Project(
            id=record["id"],
            name=record["name"],
            path=record["path"],
            created_at=datetime.fromisoformat(record["createdAt"]),
        )

    def list_projects(self) -> list[Project]:
        """List all registered projects.

        Returns:
            List of all projects.
        """
        query = """
        MATCH (p:Project)
        RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt
        ORDER BY p.createdAt DESC
        """

        with self._connection.session() as session:
            result = session.run(query)
            return [
                Project(
                    id=record["id"],
                    name=record["name"],
                    path=record["path"],
                    created_at=datetime.fromisoformat(record["createdAt"]),
                )
                for record in result
            ]

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and all its associated data atomically.

        Uses a single transaction to ensure data consistency.

        Args:
            project_id: Project identifier.

        Returns:
            True if project was deleted, False if not found.
        """
        # First check if project exists
        existing = self.get_by_id(project_id)
        if not existing:
            return False

        # Single query to delete project and all associated data atomically
        delete_query = """
        MATCH (p:Project {id: $id})
        OPTIONAL MATCH (n {projectId: $projectId})
        WITH p, collect(n) AS nodes
        DETACH DELETE p
        WITH nodes
        UNWIND nodes AS n
        DETACH DELETE n
        RETURN count(*) AS deleted
        """

        with self._connection.session() as session:
            result = session.run(
                delete_query, {"id": project_id, "projectId": project_id}
            )
            record = result.single()

        return record is not None and record["deleted"] > 0
