"""Graph module for Neo4j interactions."""

from synapse.graph.connection import (
    ConnectionError,
    Neo4jConfig,
    Neo4jConnection,
    close_connection,
    get_connection,
)
from synapse.graph.queries import (
    CallableInfo,
    CallChainResult,
    GraphQueryExecutor,
    ModuleDependency,
    ModuleInfo,
    PaginatedResult,
    TypeHierarchyResult,
    TypeInfo,
)
from synapse.graph.schema import (
    SchemaManager,
    SchemaResult,
    ensure_schema,
)
from synapse.graph.writer import (
    DanglingReference,
    GraphWriter,
    WriteResult,
)

__all__ = [
    "ConnectionError",
    "Neo4jConfig",
    "Neo4jConnection",
    "close_connection",
    "get_connection",
    "CallableInfo",
    "CallChainResult",
    "GraphQueryExecutor",
    "ModuleDependency",
    "ModuleInfo",
    "PaginatedResult",
    "TypeHierarchyResult",
    "TypeInfo",
    "SchemaManager",
    "SchemaResult",
    "ensure_schema",
    "DanglingReference",
    "GraphWriter",
    "WriteResult",
]
