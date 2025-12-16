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
    archived: bool = Field(default=False, description="Whether project is archived")
    archived_at: datetime | None = Field(default=None, description="Archive timestamp")


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


class ProjectNotArchivedError(Exception):
    """Raised when attempting to purge a non-archived project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        super().__init__(f"Project {project_id} is not archived")


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

        if not record:
            raise RuntimeError(f"Failed to create project: {name} at {path}")

        project = Project(
            id=record["id"],
            name=record["name"],
            path=record["path"],
            created_at=datetime.fromisoformat(record["createdAt"]),
        )

        return ProjectCreateResult(project=project, created=True)

    def get_by_id(
        self, project_id: str, *, include_archived: bool = False
    ) -> Project | None:
        """Get a project by its ID.

        Args:
            project_id: Project identifier.
            include_archived: If True, include archived projects. Defaults to False.

        Returns:
            Project if found, None otherwise.
        """
        if include_archived:
            query = """
            MATCH (p:Project {id: $id})
            RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt,
                   p.archived AS archived, p.archivedAt AS archivedAt
            """
        else:
            query = """
            MATCH (p:Project {id: $id})
            WHERE p.archived IS NULL OR p.archived = false
            RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt,
                   p.archived AS archived, p.archivedAt AS archivedAt
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
            archived=record["archived"] or False,
            archived_at=(
                datetime.fromisoformat(record["archivedAt"])
                if record["archivedAt"]
                else None
            ),
        )

    def get_by_path(self, path: str, *, include_archived: bool = False) -> Project | None:
        """Get a project by its file system path.

        Args:
            path: File system path.
            include_archived: If True, include archived projects. Defaults to False.

        Returns:
            Project if found, None otherwise.
        """
        if include_archived:
            query = """
            MATCH (p:Project {path: $path})
            RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt,
                   p.archived AS archived, p.archivedAt AS archivedAt
            """
        else:
            query = """
            MATCH (p:Project {path: $path})
            WHERE p.archived IS NULL OR p.archived = false
            RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt,
                   p.archived AS archived, p.archivedAt AS archivedAt
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
            archived=record["archived"] or False,
            archived_at=(
                datetime.fromisoformat(record["archivedAt"])
                if record["archivedAt"]
                else None
            ),
        )

    def list_projects(self, *, include_archived: bool = False) -> list[Project]:
        """List all registered projects.

        Args:
            include_archived: If True, include archived projects. Defaults to False.

        Returns:
            List of all projects (excluding archived by default).
        """
        if include_archived:
            query = """
            MATCH (p:Project)
            RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt,
                   p.archived AS archived, p.archivedAt AS archivedAt
            ORDER BY p.createdAt DESC
            """
        else:
            query = """
            MATCH (p:Project)
            WHERE p.archived IS NULL OR p.archived = false
            RETURN p.id AS id, p.name AS name, p.path AS path, p.createdAt AS createdAt,
                   p.archived AS archived, p.archivedAt AS archivedAt
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
                    archived=record["archived"] or False,
                    archived_at=(
                        datetime.fromisoformat(record["archivedAt"])
                        if record["archivedAt"]
                        else None
                    ),
                )
                for record in result
            ]

    def delete_project(self, project_id: str) -> bool:
        """Archive a project (logical delete).

        Sets the project's archived flag to true and records the archive timestamp.
        This operation is idempotent - archiving an already archived project returns True.

        Args:
            project_id: Project identifier.

        Returns:
            True if project was archived (or already archived), False if not found.
        """
        archived_at = datetime.now(timezone.utc)

        # Archive the project - this is idempotent
        archive_query = """
        MATCH (p:Project {id: $id})
        SET p.archived = true, p.archivedAt = $archivedAt
        RETURN p.id AS id
        """

        with self._connection.session() as session:
            result = session.run(
                archive_query, {"id": project_id, "archivedAt": archived_at.isoformat()}
            )
            record = result.single()

        return record is not None

    def restore_project(self, project_id: str) -> bool:
        """Restore an archived project.

        Sets the project's archived flag to false and clears the archive timestamp.

        Args:
            project_id: Project identifier.

        Returns:
            True if project was restored, False if not found or not archived.
        """
        # First check if the project exists and is archived
        check_query = """
        MATCH (p:Project {id: $id})
        RETURN p.archived AS archived
        """

        with self._connection.session() as session:
            result = session.run(check_query, {"id": project_id})
            record = result.single()

        # Project not found
        if record is None:
            return False

        # Project exists but is not archived
        if not record["archived"]:
            return False

        # Restore the project
        restore_query = """
        MATCH (p:Project {id: $id})
        WHERE p.archived = true
        SET p.archived = false, p.archivedAt = null
        RETURN p.id AS id
        """

        with self._connection.session() as session:
            result = session.run(restore_query, {"id": project_id})
            record = result.single()

        return record is not None

    def purge_project(self, project_id: str) -> bool:
        """Permanently delete an archived project and all associated data.

        This operation physically removes the project node and all related nodes
        from the database. Only archived projects can be purged.

        Args:
            project_id: Project identifier.

        Returns:
            True if project was purged, False if not found.

        Raises:
            ProjectNotArchivedError: If the project exists but is not archived.
        """
        # First check if the project exists and its archived state
        check_query = """
        MATCH (p:Project {id: $id})
        RETURN p.archived AS archived
        """

        with self._connection.session() as session:
            result = session.run(check_query, {"id": project_id})
            record = result.single()

        # Project not found
        if record is None:
            return False

        # Project exists but is not archived - raise error
        if not record["archived"]:
            raise ProjectNotArchivedError(project_id)

        # Physically delete the project and all associated data
        # DETACH DELETE removes the node and all its relationships
        purge_query = """
        MATCH (p:Project {id: $id})
        DETACH DELETE p
        RETURN count(p) AS deleted
        """

        with self._connection.session() as session:
            result = session.run(purge_query, {"id": project_id})
            record = result.single()

        return record is not None and record["deleted"] > 0
