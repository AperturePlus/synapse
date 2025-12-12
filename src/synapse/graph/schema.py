"""Neo4j schema initialization for Synapse.

This module handles the creation of indexes and constraints required
for the Synapse graph database schema.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection


# Constraint definitions
CONSTRAINTS = [
    # Project path uniqueness
    """
    CREATE CONSTRAINT project_path IF NOT EXISTS
    FOR (p:Project) REQUIRE p.path IS UNIQUE
    """,
    # Module uniqueness (composite)
    """
    CREATE CONSTRAINT module_unique IF NOT EXISTS
    FOR (m:Module) REQUIRE (m.projectId, m.languageType, m.qualifiedName) IS UNIQUE
    """,
    # Type uniqueness (composite)
    """
    CREATE CONSTRAINT type_unique IF NOT EXISTS
    FOR (t:Type) REQUIRE (t.projectId, t.languageType, t.qualifiedName) IS UNIQUE
    """,
    # Callable uniqueness (composite with signature)
    """
    CREATE CONSTRAINT callable_unique IF NOT EXISTS
    FOR (c:Callable) REQUIRE (c.projectId, c.languageType, c.qualifiedName, c.signature) IS UNIQUE
    """,
]

# Index definitions for query optimization
INDEXES = [
    # Module lookup index
    """
    CREATE INDEX module_lookup IF NOT EXISTS
    FOR (m:Module) ON (m.projectId, m.languageType, m.qualifiedName)
    """,
    # Type lookup index
    """
    CREATE INDEX type_lookup IF NOT EXISTS
    FOR (t:Type) ON (t.projectId, t.languageType, t.qualifiedName)
    """,
    # Callable lookup index
    """
    CREATE INDEX callable_lookup IF NOT EXISTS
    FOR (c:Callable) ON (c.projectId, c.languageType, c.qualifiedName)
    """,
    # Project ID index for fast project-scoped queries
    """
    CREATE INDEX project_id_idx IF NOT EXISTS
    FOR (p:Project) ON (p.id)
    """,
    # Entity ID indexes for relationship lookups
    """
    CREATE INDEX module_id_idx IF NOT EXISTS
    FOR (m:Module) ON (m.id)
    """,
    """
    CREATE INDEX type_id_idx IF NOT EXISTS
    FOR (t:Type) ON (t.id)
    """,
    """
    CREATE INDEX callable_id_idx IF NOT EXISTS
    FOR (c:Callable) ON (c.id)
    """,
]


class SchemaManager:
    """Manages Neo4j schema initialization.

    Handles creation of indexes and constraints required for Synapse.
    """

    def __init__(self, connection: Neo4jConnection) -> None:
        """Initialize schema manager.

        Args:
            connection: Neo4j connection instance.
        """
        self._connection = connection

    def ensure_schema(self) -> SchemaResult:
        """Ensure all indexes and constraints are created.

        This method is idempotent - it can be called multiple times safely.

        Returns:
            SchemaResult with counts of created/existing items.
        """
        constraints_created = 0
        indexes_created = 0
        errors: list[str] = []

        # Create constraints
        for constraint in CONSTRAINTS:
            try:
                with self._connection.session() as session:
                    session.run(constraint.strip())
                constraints_created += 1
            except Exception as e:
                error_msg = str(e)
                # Ignore "already exists" errors
                if "already exists" not in error_msg.lower():
                    errors.append(f"Constraint error: {error_msg}")

        # Create indexes
        for index in INDEXES:
            try:
                with self._connection.session() as session:
                    session.run(index.strip())
                indexes_created += 1
            except Exception as e:
                error_msg = str(e)
                # Ignore "already exists" errors
                if "already exists" not in error_msg.lower():
                    errors.append(f"Index error: {error_msg}")

        return SchemaResult(
            constraints_created=constraints_created,
            indexes_created=indexes_created,
            errors=errors,
        )

    def drop_all_constraints(self) -> int:
        """Drop all constraints (for testing/reset).

        Returns:
            Number of constraints dropped.
        """
        dropped = 0
        with self._connection.session() as session:
            result = session.run("SHOW CONSTRAINTS")
            constraints = [record["name"] for record in result]

        for name in constraints:
            try:
                with self._connection.session() as session:
                    session.run(f"DROP CONSTRAINT {name} IF EXISTS")
                dropped += 1
            except Exception:
                pass

        return dropped

    def drop_all_indexes(self) -> int:
        """Drop all indexes (for testing/reset).

        Returns:
            Number of indexes dropped.
        """
        dropped = 0
        with self._connection.session() as session:
            result = session.run("SHOW INDEXES")
            # Filter out constraint-backing indexes
            indexes = [
                record["name"]
                for record in result
                if record.get("uniqueness") != "UNIQUE"
            ]

        for name in indexes:
            try:
                with self._connection.session() as session:
                    session.run(f"DROP INDEX {name} IF EXISTS")
                dropped += 1
            except Exception:
                pass

        return dropped

    def get_schema_info(self) -> dict:
        """Get current schema information.

        Returns:
            Dictionary with constraints and indexes info.
        """
        with self._connection.session() as session:
            constraints_result = session.run("SHOW CONSTRAINTS")
            constraints = [record.data() for record in constraints_result]

        with self._connection.session() as session:
            indexes_result = session.run("SHOW INDEXES")
            indexes = [record.data() for record in indexes_result]

        return {
            "constraints": constraints,
            "indexes": indexes,
        }


class SchemaResult:
    """Result of schema initialization."""

    def __init__(
        self,
        constraints_created: int,
        indexes_created: int,
        errors: list[str] | None = None,
    ) -> None:
        self.constraints_created = constraints_created
        self.indexes_created = indexes_created
        self.errors = errors or []

    @property
    def success(self) -> bool:
        """Check if schema initialization was successful."""
        return len(self.errors) == 0

    def __repr__(self) -> str:
        return (
            f"SchemaResult(constraints={self.constraints_created}, "
            f"indexes={self.indexes_created}, errors={len(self.errors)})"
        )


def ensure_schema(connection: Neo4jConnection) -> SchemaResult:
    """Convenience function to ensure schema is initialized.

    Args:
        connection: Neo4j connection instance.

    Returns:
        SchemaResult with initialization details.
    """
    manager = SchemaManager(connection)
    return manager.ensure_schema()
