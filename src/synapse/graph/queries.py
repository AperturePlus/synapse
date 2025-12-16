"""Query encapsulation for Neo4j graph operations.

This module provides high-level query interfaces for:
- Call chain queries
- Type inheritance tree queries
- Module dependency queries

All queries support pagination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection


@dataclass
class CallableInfo:
    """Information about a callable entity."""

    id: str
    name: str
    qualified_name: str
    kind: str
    signature: str
    depth: int = 0


@dataclass
class CallChainResult:
    """Result of a call chain query."""

    root_id: str
    callers: list[CallableInfo] = field(default_factory=list)
    callees: list[CallableInfo] = field(default_factory=list)
    total_callers: int = 0
    total_callees: int = 0


@dataclass
class TypeInfo:
    """Information about a type entity."""

    id: str
    name: str
    qualified_name: str
    kind: str
    depth: int = 0


@dataclass
class TypeHierarchyResult:
    """Result of a type hierarchy query."""

    root_id: str
    ancestors: list[TypeInfo] = field(default_factory=list)
    descendants: list[TypeInfo] = field(default_factory=list)
    total_ancestors: int = 0
    total_descendants: int = 0


@dataclass
class ModuleInfo:
    """Information about a module entity."""

    id: str
    name: str
    qualified_name: str
    path: str


@dataclass
class ModuleDependency:
    """Module dependency information."""

    source_module: ModuleInfo
    target_module: ModuleInfo
    dependency_type: str  # "DECLARES", "IMPORTS", etc.


@dataclass
class PaginatedResult:
    """Generic paginated result."""

    items: list
    page: int
    page_size: int
    total: int
    has_next: bool


class GraphQueryExecutor:
    """Executor for Neo4j graph queries.

    Provides low-level query execution with Cypher for call chains,
    type hierarchies, and module dependencies. Pagination supported.
    """

    def __init__(self, connection: Neo4jConnection) -> None:
        """Initialize query executor.

        Args:
            connection: Neo4j connection instance.
        """
        from synapse.core.config import get_config

        self._connection = connection
        self._config = get_config()

    @property
    def default_page_size(self) -> int:
        """Get default page size from config."""
        return self._config.default_page_size

    @property
    def default_max_depth(self) -> int:
        """Get default max depth from config."""
        return self._config.default_max_depth

    def get_call_chain(
        self,
        callable_id: str,
        direction: Literal["callers", "callees", "both"] = "both",
        max_depth: int | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> CallChainResult:
        """Get call chain for a callable.

        Args:
            callable_id: ID of the callable to query.
            direction: Query direction - callers, callees, or both.
            max_depth: Maximum traversal depth (uses config default if None).
            page: Page number (1-indexed).
            page_size: Number of results per page (uses config default if None).

        Returns:
            CallChainResult with callers and/or callees.
        """
        max_depth = max_depth or self.default_max_depth
        page_size = page_size or self.default_page_size
        result = CallChainResult(root_id=callable_id)
        skip = (page - 1) * page_size

        if direction in ("callers", "both"):
            callers, total = self._get_callers(callable_id, max_depth, skip, page_size)
            result.callers = callers
            result.total_callers = total

        if direction in ("callees", "both"):
            callees, total = self._get_callees(callable_id, max_depth, skip, page_size)
            result.callees = callees
            result.total_callees = total

        return result

    def _get_callers(
        self, callable_id: str, max_depth: int, skip: int, limit: int
    ) -> tuple[list[CallableInfo], int]:
        """Get callers of a callable."""
        # Count query
        count_query = f"""
        MATCH (caller:Callable)-[:CALLS*1..{max_depth}]->(target:Callable {{id: $id}})
        RETURN count(DISTINCT caller) AS total
        """

        # Data query with depth
        data_query = f"""
        MATCH path = (caller:Callable)-[:CALLS*1..{max_depth}]->(target:Callable {{id: $id}})
        WITH caller, min(length(path)) AS depth
        RETURN DISTINCT caller.id AS id, caller.name AS name,
               caller.qualifiedName AS qualifiedName, caller.kind AS kind,
               caller.signature AS signature, depth
        ORDER BY depth, caller.qualifiedName
        SKIP $skip LIMIT $limit
        """

        with self._connection.session() as session:
            count_result = session.run(count_query, {"id": callable_id})
            total = count_result.single()["total"]

        with self._connection.session() as session:
            data_result = session.run(
                data_query, {"id": callable_id, "skip": skip, "limit": limit}
            )
            callers = [
                CallableInfo(
                    id=record["id"],
                    name=record["name"],
                    qualified_name=record["qualifiedName"],
                    kind=record["kind"],
                    signature=record["signature"],
                    depth=record["depth"],
                )
                for record in data_result
            ]

        return callers, total

    def _get_callees(
        self, callable_id: str, max_depth: int, skip: int, limit: int
    ) -> tuple[list[CallableInfo], int]:
        """Get callees of a callable."""
        count_query = f"""
        MATCH (source:Callable {{id: $id}})-[:CALLS*1..{max_depth}]->(callee:Callable)
        RETURN count(DISTINCT callee) AS total
        """

        data_query = f"""
        MATCH path = (source:Callable {{id: $id}})-[:CALLS*1..{max_depth}]->(callee:Callable)
        WITH callee, min(length(path)) AS depth
        RETURN DISTINCT callee.id AS id, callee.name AS name,
               callee.qualifiedName AS qualifiedName, callee.kind AS kind,
               callee.signature AS signature, depth
        ORDER BY depth, callee.qualifiedName
        SKIP $skip LIMIT $limit
        """

        with self._connection.session() as session:
            count_result = session.run(count_query, {"id": callable_id})
            total = count_result.single()["total"]

        with self._connection.session() as session:
            data_result = session.run(
                data_query, {"id": callable_id, "skip": skip, "limit": limit}
            )
            callees = [
                CallableInfo(
                    id=record["id"],
                    name=record["name"],
                    qualified_name=record["qualifiedName"],
                    kind=record["kind"],
                    signature=record["signature"],
                    depth=record["depth"],
                )
                for record in data_result
            ]

        return callees, total


    def get_type_hierarchy(
        self,
        type_id: str,
        direction: Literal["ancestors", "descendants", "both"] = "both",
        page: int = 1,
        page_size: int | None = None,
    ) -> TypeHierarchyResult:
        """Get type inheritance hierarchy.

        Args:
            type_id: ID of the type to query.
            direction: Query direction - ancestors, descendants, or both.
            page: Page number (1-indexed).
            page_size: Number of results per page (uses config default if None).

        Returns:
            TypeHierarchyResult with ancestors and/or descendants.
        """
        page_size = page_size or self.default_page_size
        result = TypeHierarchyResult(root_id=type_id)
        skip = (page - 1) * page_size

        if direction in ("ancestors", "both"):
            ancestors, total = self._get_ancestors(type_id, skip, page_size)
            result.ancestors = ancestors
            result.total_ancestors = total

        if direction in ("descendants", "both"):
            descendants, total = self._get_descendants(type_id, skip, page_size)
            result.descendants = descendants
            result.total_descendants = total

        return result

    def _get_ancestors(
        self, type_id: str, skip: int, limit: int
    ) -> tuple[list[TypeInfo], int]:
        """Get ancestor types (via EXTENDS)."""
        count_query = """
        MATCH (t:Type {id: $id})-[:EXTENDS*1..]->(ancestor:Type)
        RETURN count(DISTINCT ancestor) AS total
        """

        data_query = """
        MATCH path = (t:Type {id: $id})-[:EXTENDS*1..]->(ancestor:Type)
        WITH ancestor, min(length(path)) AS depth
        RETURN DISTINCT ancestor.id AS id, ancestor.name AS name,
               ancestor.qualifiedName AS qualifiedName, ancestor.kind AS kind, depth
        ORDER BY depth, ancestor.qualifiedName
        SKIP $skip LIMIT $limit
        """

        with self._connection.session() as session:
            count_result = session.run(count_query, {"id": type_id})
            total = count_result.single()["total"]

        with self._connection.session() as session:
            data_result = session.run(
                data_query, {"id": type_id, "skip": skip, "limit": limit}
            )
            ancestors = [
                TypeInfo(
                    id=record["id"],
                    name=record["name"],
                    qualified_name=record["qualifiedName"],
                    kind=record["kind"],
                    depth=record["depth"],
                )
                for record in data_result
            ]

        return ancestors, total

    def _get_descendants(
        self, type_id: str, skip: int, limit: int
    ) -> tuple[list[TypeInfo], int]:
        """Get descendant types (via EXTENDS)."""
        count_query = """
        MATCH (descendant:Type)-[:EXTENDS*1..]->(t:Type {id: $id})
        RETURN count(DISTINCT descendant) AS total
        """

        data_query = """
        MATCH path = (descendant:Type)-[:EXTENDS*1..]->(t:Type {id: $id})
        WITH descendant, min(length(path)) AS depth
        RETURN DISTINCT descendant.id AS id, descendant.name AS name,
               descendant.qualifiedName AS qualifiedName, descendant.kind AS kind, depth
        ORDER BY depth, descendant.qualifiedName
        SKIP $skip LIMIT $limit
        """

        with self._connection.session() as session:
            count_result = session.run(count_query, {"id": type_id})
            total = count_result.single()["total"]

        with self._connection.session() as session:
            data_result = session.run(
                data_query, {"id": type_id, "skip": skip, "limit": limit}
            )
            descendants = [
                TypeInfo(
                    id=record["id"],
                    name=record["name"],
                    qualified_name=record["qualifiedName"],
                    kind=record["kind"],
                    depth=record["depth"],
                )
                for record in data_result
            ]

        return descendants, total

    def get_module_dependencies(
        self,
        module_id: str,
        page: int = 1,
        page_size: int | None = None,
    ) -> PaginatedResult:
        """Get direct dependencies of a module.

        Dependencies are determined by types in this module that reference
        types in other modules.

        Args:
            module_id: ID of the module to query.
            page: Page number (1-indexed).
            page_size: Number of results per page (uses config default if None).

        Returns:
            PaginatedResult containing ModuleDependency items.
        """
        page_size = page_size or self.default_page_size
        skip = (page - 1) * page_size

        # Count query
        count_query = """
        MATCH (m:Module {id: $id})-[:DECLARES]->(t:Type)
        MATCH (t)-[:EXTENDS|IMPLEMENTS|EMBEDS]->(dep:Type)<-[:DECLARES]-(depMod:Module)
        WHERE depMod.id <> m.id
        RETURN count(DISTINCT depMod) AS total
        """

        # Data query
        data_query = """
        MATCH (m:Module {id: $id})-[:DECLARES]->(t:Type)
        MATCH (t)-[r:EXTENDS|IMPLEMENTS|EMBEDS]->(dep:Type)<-[:DECLARES]-(depMod:Module)
        WHERE depMod.id <> m.id
        WITH m, depMod, type(r) AS relType
        RETURN DISTINCT
            m.id AS sourceId, m.name AS sourceName,
            m.qualifiedName AS sourceQualifiedName, m.path AS sourcePath,
            depMod.id AS targetId, depMod.name AS targetName,
            depMod.qualifiedName AS targetQualifiedName, depMod.path AS targetPath,
            relType
        ORDER BY depMod.qualifiedName
        SKIP $skip LIMIT $limit
        """

        with self._connection.session() as session:
            count_result = session.run(count_query, {"id": module_id})
            total = count_result.single()["total"]

        with self._connection.session() as session:
            data_result = session.run(
                data_query, {"id": module_id, "skip": skip, "limit": limit}
            )
            dependencies = [
                ModuleDependency(
                    source_module=ModuleInfo(
                        id=record["sourceId"],
                        name=record["sourceName"],
                        qualified_name=record["sourceQualifiedName"],
                        path=record["sourcePath"],
                    ),
                    target_module=ModuleInfo(
                        id=record["targetId"],
                        name=record["targetName"],
                        qualified_name=record["targetQualifiedName"],
                        path=record["targetPath"],
                    ),
                    dependency_type=record["relType"],
                )
                for record in data_result
            ]

        return PaginatedResult(
            items=dependencies,
            page=page,
            page_size=page_size,
            total=total,
            has_next=(skip + len(dependencies)) < total,
        )

    def get_all_callees_unpaginated(
        self, callable_id: str, max_depth: int | None = None
    ) -> list[CallableInfo]:
        """Get all callees without pagination (for testing).

        Args:
            callable_id: ID of the callable.
            max_depth: Maximum traversal depth (uses config default if None).

        Returns:
            List of all callees.
        """
        max_depth = max_depth or self.default_max_depth
        query = f"""
        MATCH path = (source:Callable {{id: $id}})-[:CALLS*1..{max_depth}]->(callee:Callable)
        WITH callee, min(length(path)) AS depth
        RETURN DISTINCT callee.id AS id, callee.name AS name,
               callee.qualifiedName AS qualifiedName, callee.kind AS kind,
               callee.signature AS signature, depth
        ORDER BY depth, callee.qualifiedName
        """

        with self._connection.session() as session:
            result = session.run(query, {"id": callable_id})
            return [
                CallableInfo(
                    id=record["id"],
                    name=record["name"],
                    qualified_name=record["qualifiedName"],
                    kind=record["kind"],
                    signature=record["signature"],
                    depth=record["depth"],
                )
                for record in result
            ]
