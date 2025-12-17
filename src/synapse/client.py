"""Public client interface for Synapse.

Synapse already exposes lower-level building blocks (graph/ and services/).
This module provides a stable, ergonomic entrypoint for external callers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from synapse.graph.connection import Neo4jConfig, Neo4jConnection
from synapse.graph.schema import SchemaResult, ensure_schema
from synapse.services.project_service import ProjectService
from synapse.services.query_service import QueryService
from synapse.services.resolver_service import EntityResolverService
from synapse.services.scanner_service import ScannerService

if TYPE_CHECKING:
    from types import TracebackType


class SynapseClient:
    """High-level client that owns a Neo4j connection and exposes services."""

    def __init__(
        self,
        connection: Neo4jConnection | None = None,
        *,
        config: Neo4jConfig | None = None,
        ensure_schema_on_init: bool = True,
        verify_connectivity_on_init: bool = True,
    ) -> None:
        """Create a Synapse client.

        Args:
            connection: Optional pre-built connection (ownership stays with caller).
            config: Optional Neo4j config (only used when `connection` is not provided).
            ensure_schema_on_init: If True, ensures constraints/indexes exist.
            verify_connectivity_on_init: If True, verifies Neo4j connectivity.
        """
        self._owns_connection = connection is None
        self._connection = connection or Neo4jConnection(config)

        self._projects: ProjectService | None = None
        self._scanner: ScannerService | None = None
        self._query: QueryService | None = None
        self._resolver: EntityResolverService | None = None

        if verify_connectivity_on_init:
            self._connection.verify_connectivity()
        if ensure_schema_on_init:
            ensure_schema(self._connection)

    @property
    def connection(self) -> Neo4jConnection:
        """Access the underlying Neo4j connection."""
        return self._connection

    def ensure_schema(self) -> SchemaResult:
        """Ensure schema (constraints/indexes) exists (idempotent)."""
        return ensure_schema(self._connection)

    @property
    def projects(self) -> ProjectService:
        """Project management service."""
        if self._projects is None:
            self._projects = ProjectService(self._connection)
        return self._projects

    @property
    def scanner(self) -> ScannerService:
        """Code scanning service."""
        if self._scanner is None:
            self._scanner = ScannerService(self._connection)
        return self._scanner

    @property
    def query(self) -> QueryService:
        """Topology query service."""
        if self._query is None:
            self._query = QueryService(self._connection)
        return self._query

    @property
    def resolver(self) -> EntityResolverService:
        """Entity resolution service (qualified name -> id)."""
        if self._resolver is None:
            self._resolver = EntityResolverService(self._connection)
        return self._resolver

    def close(self) -> None:
        """Close resources owned by this client."""
        if self._owns_connection:
            self._connection.close()

    def __enter__(self) -> SynapseClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

