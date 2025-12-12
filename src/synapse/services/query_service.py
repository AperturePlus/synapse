"""Query service for code topology analysis.

This module provides the QueryService as a high-level interface for
querying the code topology graph, wrapping the lower-level graph queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from synapse.graph.queries import (
    CallableInfo,
    CallChainResult,
    ModuleDependency,
    ModuleInfo,
    PaginatedResult,
    QueryService as GraphQueryService,
    TypeHierarchyResult,
    TypeInfo,
)

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection


@dataclass
class CallChainQuery:
    """Parameters for a call chain query."""

    callable_id: str
    direction: Literal["callers", "callees", "both"] = "both"
    max_depth: int = 5
    page: int = 1
    page_size: int = 100


@dataclass
class TypeHierarchyQuery:
    """Parameters for a type hierarchy query."""

    type_id: str
    direction: Literal["ancestors", "descendants", "both"] = "both"
    page: int = 1
    page_size: int = 100


@dataclass
class ModuleDependencyQuery:
    """Parameters for a module dependency query."""

    module_id: str
    page: int = 1
    page_size: int = 100



class QueryService:
    """High-level service for querying code topology.

    Provides a clean interface for querying call chains, type hierarchies,
    and module dependencies from the code topology graph.
    """

    DEFAULT_PAGE_SIZE = 100
    DEFAULT_MAX_DEPTH = 5

    def __init__(self, connection: Neo4jConnection) -> None:
        """Initialize query service.

        Args:
            connection: Neo4j connection instance.
        """
        self._connection = connection
        self._graph_query = GraphQueryService(connection)

    def get_call_chain(
        self,
        callable_id: str,
        direction: Literal["callers", "callees", "both"] = "both",
        max_depth: int = DEFAULT_MAX_DEPTH,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> CallChainResult:
        """Get call chain for a callable.

        Retrieves the callers and/or callees of a callable entity,
        traversing the call graph up to the specified depth.

        Args:
            callable_id: ID of the callable to query.
            direction: Query direction - "callers", "callees", or "both".
            max_depth: Maximum traversal depth (default: 5).
            page: Page number for pagination (1-indexed).
            page_size: Number of results per page (default: 100).

        Returns:
            CallChainResult containing callers and/or callees.
        """
        return self._graph_query.get_call_chain(
            callable_id=callable_id,
            direction=direction,
            max_depth=max_depth,
            page=page,
            page_size=page_size,
        )

    def get_type_hierarchy(
        self,
        type_id: str,
        direction: Literal["ancestors", "descendants", "both"] = "both",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TypeHierarchyResult:
        """Get type inheritance hierarchy.

        Retrieves the ancestors (parent classes/interfaces) and/or
        descendants (child classes) of a type entity.

        Args:
            type_id: ID of the type to query.
            direction: Query direction - "ancestors", "descendants", or "both".
            page: Page number for pagination (1-indexed).
            page_size: Number of results per page (default: 100).

        Returns:
            TypeHierarchyResult containing ancestors and/or descendants.
        """
        return self._graph_query.get_type_hierarchy(
            type_id=type_id,
            direction=direction,
            page=page,
            page_size=page_size,
        )

    def get_module_dependencies(
        self,
        module_id: str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResult:
        """Get direct dependencies of a module.

        Retrieves modules that the specified module depends on,
        based on type relationships (extends, implements, embeds).

        Args:
            module_id: ID of the module to query.
            page: Page number for pagination (1-indexed).
            page_size: Number of results per page (default: 100).

        Returns:
            PaginatedResult containing ModuleDependency items.
        """
        return self._graph_query.get_module_dependencies(
            module_id=module_id,
            page=page,
            page_size=page_size,
        )

    def query_call_chain(self, query: CallChainQuery) -> CallChainResult:
        """Execute a call chain query using query object.

        Args:
            query: CallChainQuery with query parameters.

        Returns:
            CallChainResult containing callers and/or callees.
        """
        return self.get_call_chain(
            callable_id=query.callable_id,
            direction=query.direction,
            max_depth=query.max_depth,
            page=query.page,
            page_size=query.page_size,
        )

    def query_type_hierarchy(self, query: TypeHierarchyQuery) -> TypeHierarchyResult:
        """Execute a type hierarchy query using query object.

        Args:
            query: TypeHierarchyQuery with query parameters.

        Returns:
            TypeHierarchyResult containing ancestors and/or descendants.
        """
        return self.get_type_hierarchy(
            type_id=query.type_id,
            direction=query.direction,
            page=query.page,
            page_size=query.page_size,
        )

    def query_module_dependencies(self, query: ModuleDependencyQuery) -> PaginatedResult:
        """Execute a module dependency query using query object.

        Args:
            query: ModuleDependencyQuery with query parameters.

        Returns:
            PaginatedResult containing ModuleDependency items.
        """
        return self.get_module_dependencies(
            module_id=query.module_id,
            page=query.page,
            page_size=query.page_size,
        )
