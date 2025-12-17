"""Entity resolution service for Synapse.

This module provides a small lookup layer to resolve Modules/Types/Callables
from stable identifiers such as (project_id, language_type, qualified_name).

It is intended for external integrations that do not want to depend on internal
Neo4j schema details or precomputed entity IDs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from synapse.core.models import LanguageType

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection


class ModuleRef(BaseModel):
    """Resolved Module information."""

    id: str = Field(..., description="Module ID")
    project_id: str = Field(..., description="Project ID")
    language_type: LanguageType = Field(..., description="Language type")
    name: str = Field(..., description="Simple name")
    qualified_name: str = Field(..., description="Fully qualified name")
    path: str = Field(..., description="Filesystem path")


class TypeRef(BaseModel):
    """Resolved Type information."""

    id: str = Field(..., description="Type ID")
    project_id: str = Field(..., description="Project ID")
    language_type: LanguageType = Field(..., description="Language type")
    name: str = Field(..., description="Simple name")
    qualified_name: str = Field(..., description="Fully qualified name")
    kind: str = Field(..., description="Type kind (CLASS/INTERFACE/STRUCT/...)")


class CallableRef(BaseModel):
    """Resolved Callable information."""

    id: str = Field(..., description="Callable ID")
    project_id: str = Field(..., description="Project ID")
    language_type: LanguageType = Field(..., description="Language type")
    name: str = Field(..., description="Simple name")
    qualified_name: str = Field(..., description="Fully qualified name")
    kind: str = Field(..., description="Callable kind (FUNCTION/METHOD/CONSTRUCTOR)")
    signature: str = Field(..., description="Signature (used to disambiguate overloads)")


class AmbiguousCallableError(Exception):
    """Raised when a callable resolution matches multiple overloads."""

    def __init__(self, matches: list[CallableRef]) -> None:
        self.matches = matches
        super().__init__(f"Ambiguous callable: {len(matches)} matches")


class EntityResolverService:
    """Resolve entities by stable attributes (project/language/qualified_name)."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    def get_module(
        self, *, project_id: str, language_type: LanguageType, qualified_name: str
    ) -> ModuleRef | None:
        """Resolve a Module by unique key."""
        query = """
        MATCH (m:Module {projectId: $projectId, languageType: $languageType, qualifiedName: $qn})
        RETURN m.id AS id, m.projectId AS projectId, m.languageType AS languageType,
               m.name AS name, m.qualifiedName AS qualifiedName, m.path AS path
        """
        with self._connection.session() as session:
            record = session.run(
                query,
                {
                    "projectId": project_id,
                    "languageType": language_type.value,
                    "qn": qualified_name,
                },
            ).single()

        if not record:
            return None

        return ModuleRef(
            id=record["id"],
            project_id=record["projectId"],
            language_type=LanguageType(record["languageType"]),
            name=record["name"],
            qualified_name=record["qualifiedName"],
            path=record["path"],
        )

    def get_type(
        self, *, project_id: str, language_type: LanguageType, qualified_name: str
    ) -> TypeRef | None:
        """Resolve a Type by unique key."""
        query = """
        MATCH (t:Type {projectId: $projectId, languageType: $languageType, qualifiedName: $qn})
        RETURN t.id AS id, t.projectId AS projectId, t.languageType AS languageType,
               t.name AS name, t.qualifiedName AS qualifiedName, t.kind AS kind
        """
        with self._connection.session() as session:
            record = session.run(
                query,
                {
                    "projectId": project_id,
                    "languageType": language_type.value,
                    "qn": qualified_name,
                },
            ).single()

        if not record:
            return None

        return TypeRef(
            id=record["id"],
            project_id=record["projectId"],
            language_type=LanguageType(record["languageType"]),
            name=record["name"],
            qualified_name=record["qualifiedName"],
            kind=record["kind"],
        )

    def find_callables(
        self,
        *,
        project_id: str,
        language_type: LanguageType,
        qualified_name: str,
        signature: str | None = None,
        limit: int = 50,
    ) -> list[CallableRef]:
        """Find callables for a qualified name (optionally disambiguated by signature)."""
        where_signature = "AND c.signature = $sig" if signature is not None else ""
        query = f"""
        MATCH (c:Callable {{projectId: $projectId, languageType: $languageType, qualifiedName: $qn}})
        WHERE true {where_signature}
        RETURN c.id AS id, c.projectId AS projectId, c.languageType AS languageType,
               c.name AS name, c.qualifiedName AS qualifiedName, c.kind AS kind, c.signature AS signature
        ORDER BY c.signature
        LIMIT $limit
        """

        params: dict[str, object] = {
            "projectId": project_id,
            "languageType": language_type.value,
            "qn": qualified_name,
            "limit": limit,
        }
        if signature is not None:
            params["sig"] = signature

        with self._connection.session() as session:
            result = session.run(query, params)
            return [
                CallableRef(
                    id=record["id"],
                    project_id=record["projectId"],
                    language_type=LanguageType(record["languageType"]),
                    name=record["name"],
                    qualified_name=record["qualifiedName"],
                    kind=record["kind"],
                    signature=record["signature"],
                )
                for record in result
            ]

    def resolve_callable(
        self,
        *,
        project_id: str,
        language_type: LanguageType,
        qualified_name: str,
        signature: str | None = None,
    ) -> CallableRef | None:
        """Resolve a single callable (raises on ambiguity)."""
        matches = self.find_callables(
            project_id=project_id,
            language_type=language_type,
            qualified_name=qualified_name,
            signature=signature,
            limit=50,
        )
        if not matches:
            return None
        if len(matches) > 1 and signature is None:
            raise AmbiguousCallableError(matches)
        return matches[0]

