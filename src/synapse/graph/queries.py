"""Query encapsulation for Neo4j graph operations.

This module provides high-level query interfaces for:
- Call chain queries
- Type inheritance tree queries
- Module dependency queries

All queries support pagination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection


# =============================================================================
# Query Templates
# =============================================================================

class _CallChainTemplates:
    """Cypher query templates for call chain operations."""

    CALLERS_MATCH = """
    MATCH path = (caller:Callable)-[:CALLS*1..{max_depth}]->(target:Callable {{id: $id}})
    """

    CALLEES_MATCH = """
    MATCH path = (source:Callable {{id: $id}})-[:CALLS*1..{max_depth}]->(callee:Callable)
    """

    COUNT_RETURN = "RETURN count(DISTINCT {node}) AS total"

    DATA_RETURN = """
    WITH {node}, min(length(path)) AS depth
    RETURN DISTINCT {node}.id AS id, {node}.name AS name,
           {node}.qualifiedName AS qualifiedName, {node}.kind AS kind,
           {node}.signature AS signature, depth
    ORDER BY depth, {node}.qualifiedName
    SKIP $skip LIMIT $limit
    """

    DATA_RETURN_UNPAGINATED = """
    WITH {node}, min(length(path)) AS depth
    RETURN DISTINCT {node}.id AS id, {node}.name AS name,
           {node}.qualifiedName AS qualifiedName, {node}.kind AS kind,
           {node}.signature AS signature, depth
    ORDER BY depth, {node}.qualifiedName
    """


class _TypeHierarchyTemplates:
    """Cypher query templates for type hierarchy operations."""

    ANCESTORS_MATCH = """
    MATCH path = (t:Type {id: $id})-[:EXTENDS*1..]->(ancestor:Type)
    """

    DESCENDANTS_MATCH = """
    MATCH path = (descendant:Type)-[:EXTENDS*1..]->(t:Type {id: $id})
    """

    COUNT_RETURN = "RETURN count(DISTINCT {node}) AS total"

    DATA_RETURN = """
    WITH {node}, min(length(path)) AS depth
    RETURN DISTINCT {node}.id AS id, {node}.name AS name,
           {node}.qualifiedName AS qualifiedName, {node}.kind AS kind, depth
    ORDER BY depth, {node}.qualifiedName
    SKIP $skip LIMIT $limit
    """


class _ModuleDependencyTemplates:
    """Cypher query templates for module dependency operations."""

    MATCH = """
    MATCH (m:Module {id: $id})-[:DECLARES]->(t:Type)
    MATCH (t)-[r:EXTENDS|IMPLEMENTS|EMBEDS]->(dep:Type)<-[:DECLARES]-(depMod:Module)
    WHERE depMod.id <> m.id
    """

    COUNT_RETURN = "RETURN count(DISTINCT depMod) AS total"

    DATA_RETURN = """
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


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CallableInfo:
    """Information about a callable entity."""

    id: str
    name: str
    qualified_name: str
    kind: str
    signature: str
    depth: int = 0

    @classmethod
    def from_record(cls, record: Any) -> CallableInfo:
        """Create CallableInfo from a Neo4j record."""
        return cls(
            id=record["id"],
            name=record["name"],
            qualified_name=record["qualifiedName"],
            kind=record["kind"],
            signature=record["signature"],
            depth=record["depth"],
        )


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

    @classmethod
    def from_record(cls, record: Any) -> TypeInfo:
        """Create TypeInfo from a Neo4j record."""
        return cls(
            id=record["id"],
            name=record["name"],
            qualified_name=record["qualifiedName"],
            kind=record["kind"],
            depth=record["depth"],
        )


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

    @classmethod
    def from_record(cls, record: Any) -> ModuleDependency:
        """Create ModuleDependency from a Neo4j record."""
        return cls(
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


@dataclass
class PaginatedResult:
    """Generic paginated result."""

    items: list[Any]
    page: int
    page_size: int
    total: int
    has_next: bool


# =============================================================================
# Query Builder
# =============================================================================

class _QueryBuilder:
    """Builder for constructing Cypher queries from templates."""

    @staticmethod
    def build_count_query(match_clause: str, node_alias: str) -> str:
        """Build a count query from match clause."""
        count_return = _CallChainTemplates.COUNT_RETURN.format(node=node_alias)
        return match_clause + count_return

    @staticmethod
    def build_call_chain_query(
        match_clause: str, node_alias: str, paginated: bool = True
    ) -> str:
        """Build a call chain data query."""
        if paginated:
            return_clause = _CallChainTemplates.DATA_RETURN.format(node=node_alias)
        else:
            return_clause = _CallChainTemplates.DATA_RETURN_UNPAGINATED.format(node=node_alias)
        return match_clause + return_clause

    @staticmethod
    def build_type_hierarchy_query(match_clause: str, node_alias: str) -> str:
        """Build a type hierarchy data query."""
        return_clause = _TypeHierarchyTemplates.DATA_RETURN.format(node=node_alias)
        return match_clause + return_clause


# =============================================================================
# Query Executor
# =============================================================================

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

    def _execute_count_query(self, query: str, params: dict[str, Any]) -> int:
        """Execute a count query and return the total."""
        with self._connection.session() as session:
            result = session.run(query, params)
            record = result.single()
            return int(record["total"]) if record else 0

    def _execute_data_query(
        self,
        query: str,
        params: dict[str, Any],
        mapper: Any,
    ) -> list[Any]:
        """Execute a data query and map results using the mapper's from_record method."""
        with self._connection.session() as session:
            result = session.run(query, params)
            return [mapper.from_record(record) for record in result]

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
            callers, total = self._get_call_chain_direction(
                callable_id, max_depth, skip, page_size, is_callers=True
            )
            result.callers = callers
            result.total_callers = total

        if direction in ("callees", "both"):
            callees, total = self._get_call_chain_direction(
                callable_id, max_depth, skip, page_size, is_callers=False
            )
            result.callees = callees
            result.total_callees = total

        return result

    def _get_call_chain_direction(
        self,
        callable_id: str,
        max_depth: int,
        skip: int,
        limit: int,
        *,
        is_callers: bool,
    ) -> tuple[list[CallableInfo], int]:
        """Get callers or callees of a callable."""
        if is_callers:
            match_clause = _CallChainTemplates.CALLERS_MATCH.format(max_depth=max_depth)
            node_alias = "caller"
        else:
            match_clause = _CallChainTemplates.CALLEES_MATCH.format(max_depth=max_depth)
            node_alias = "callee"

        count_query = _QueryBuilder.build_count_query(match_clause, node_alias)
        data_query = _QueryBuilder.build_call_chain_query(match_clause, node_alias)

        params = {"id": callable_id}
        total = self._execute_count_query(count_query, params)

        params_with_pagination = {"id": callable_id, "skip": skip, "limit": limit}
        items = self._execute_data_query(data_query, params_with_pagination, CallableInfo)

        return items, total

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
            ancestors, total = self._get_type_hierarchy_direction(
                type_id, skip, page_size, is_ancestors=True
            )
            result.ancestors = ancestors
            result.total_ancestors = total

        if direction in ("descendants", "both"):
            descendants, total = self._get_type_hierarchy_direction(
                type_id, skip, page_size, is_ancestors=False
            )
            result.descendants = descendants
            result.total_descendants = total

        return result

    def _get_type_hierarchy_direction(
        self,
        type_id: str,
        skip: int,
        limit: int,
        *,
        is_ancestors: bool,
    ) -> tuple[list[TypeInfo], int]:
        """Get ancestors or descendants of a type."""
        if is_ancestors:
            match_clause = _TypeHierarchyTemplates.ANCESTORS_MATCH
            node_alias = "ancestor"
        else:
            match_clause = _TypeHierarchyTemplates.DESCENDANTS_MATCH
            node_alias = "descendant"

        count_query = _QueryBuilder.build_count_query(match_clause, node_alias)
        data_query = _QueryBuilder.build_type_hierarchy_query(match_clause, node_alias)

        params = {"id": type_id}
        total = self._execute_count_query(count_query, params)

        params_with_pagination = {"id": type_id, "skip": skip, "limit": limit}
        items = self._execute_data_query(data_query, params_with_pagination, TypeInfo)

        return items, total

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

        count_query = _ModuleDependencyTemplates.MATCH + _ModuleDependencyTemplates.COUNT_RETURN
        data_query = _ModuleDependencyTemplates.MATCH + _ModuleDependencyTemplates.DATA_RETURN

        params = {"id": module_id}
        total = self._execute_count_query(count_query, params)

        params_with_pagination = {"id": module_id, "skip": skip, "limit": page_size}
        dependencies = self._execute_data_query(
            data_query, params_with_pagination, ModuleDependency
        )

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
        match_clause = _CallChainTemplates.CALLEES_MATCH.format(max_depth=max_depth)
        query = _QueryBuilder.build_call_chain_query(match_clause, "callee", paginated=False)

        return self._execute_data_query(query, {"id": callable_id}, CallableInfo)
