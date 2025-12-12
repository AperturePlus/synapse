"""Graph writer for persisting IR data to Neo4j.

This module implements the GraphWriter with three-phase write logic:
1. Write all nodes (Module, Type, Callable)
2. Write relationships (verify target nodes exist)
3. Record dangling references
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from synapse.core.models import IR
    from synapse.graph.connection import Neo4jConnection


class DanglingReference(BaseModel):
    """Represents a reference to a non-existent target node."""

    source_id: str
    target_id: str
    relationship_type: str
    reason: str


@dataclass
class WriteResult:
    """Result of a graph write operation."""

    modules_written: int = 0
    types_written: int = 0
    callables_written: int = 0
    relationships_written: int = 0
    dangling_references: list[DanglingReference] = field(default_factory=list)

    @property
    def total_nodes(self) -> int:
        """Total number of nodes written."""
        return self.modules_written + self.types_written + self.callables_written

    @property
    def success(self) -> bool:
        """Check if write was successful (no dangling refs)."""
        return len(self.dangling_references) == 0


class GraphWriter:
    """Writes IR data to Neo4j with three-phase logic.

    Phase 1: Write all nodes (Module, Type, Callable)
    Phase 2: Write relationships (verify targets exist)
    Phase 3: Record dangling references

    Uses UNWIND for batch operations and MERGE for idempotency.
    """

    def __init__(self, connection: Neo4jConnection) -> None:
        """Initialize graph writer.

        Args:
            connection: Neo4j connection instance.
        """
        self._connection = connection

    def write_ir(self, ir: IR, project_id: str) -> WriteResult:
        """Write IR data to the graph database.

        Args:
            ir: Intermediate representation to write.
            project_id: Project identifier for scoping.

        Returns:
            WriteResult with counts and any dangling references.
        """
        result = WriteResult()

        # Phase 1: Write all nodes
        result.modules_written = self._write_modules(ir, project_id)
        result.types_written = self._write_types(ir, project_id)
        result.callables_written = self._write_callables(ir, project_id)

        # Collect all valid node IDs for relationship validation
        valid_ids = self._collect_valid_ids(ir, project_id)

        # Phase 2 & 3: Write relationships and record dangling refs
        rels, dangling = self._write_relationships(ir, project_id, valid_ids)
        result.relationships_written = rels
        result.dangling_references = dangling

        return result

    def _write_modules(self, ir: IR, project_id: str) -> int:
        """Write Module nodes using UNWIND batch."""
        if not ir.modules:
            return 0

        modules_data = [
            {
                "id": m.id,
                "name": m.name,
                "qualifiedName": m.qualified_name,
                "path": m.path,
                "languageType": ir.language_type.value,
                "projectId": project_id,
            }
            for m in ir.modules.values()
        ]

        query = """
        UNWIND $modules AS m
        MERGE (mod:Module {id: m.id})
        SET mod.name = m.name,
            mod.qualifiedName = m.qualifiedName,
            mod.path = m.path,
            mod.languageType = m.languageType,
            mod.projectId = m.projectId
        """

        with self._connection.session() as session:
            session.run(query, {"modules": modules_data})

        return len(modules_data)

    def _write_types(self, ir: IR, project_id: str) -> int:
        """Write Type nodes using UNWIND batch."""
        if not ir.types:
            return 0

        types_data = [
            {
                "id": t.id,
                "name": t.name,
                "qualifiedName": t.qualified_name,
                "kind": t.kind.value,
                "modifiers": t.modifiers,
                "languageType": ir.language_type.value,
                "projectId": project_id,
            }
            for t in ir.types.values()
        ]

        query = """
        UNWIND $types AS t
        MERGE (typ:Type {id: t.id})
        SET typ.name = t.name,
            typ.qualifiedName = t.qualifiedName,
            typ.kind = t.kind,
            typ.modifiers = t.modifiers,
            typ.languageType = t.languageType,
            typ.projectId = t.projectId
        """

        with self._connection.session() as session:
            session.run(query, {"types": types_data})

        return len(types_data)

    def _write_callables(self, ir: IR, project_id: str) -> int:
        """Write Callable nodes using UNWIND batch."""
        if not ir.callables:
            return 0

        callables_data = [
            {
                "id": c.id,
                "name": c.name,
                "qualifiedName": c.qualified_name,
                "kind": c.kind.value,
                "signature": c.signature,
                "isStatic": c.is_static,
                "visibility": c.visibility.value,
                "languageType": ir.language_type.value,
                "projectId": project_id,
            }
            for c in ir.callables.values()
        ]

        query = """
        UNWIND $callables AS c
        MERGE (cal:Callable {id: c.id})
        SET cal.name = c.name,
            cal.qualifiedName = c.qualifiedName,
            cal.kind = c.kind,
            cal.signature = c.signature,
            cal.isStatic = c.isStatic,
            cal.visibility = c.visibility,
            cal.languageType = c.languageType,
            cal.projectId = c.projectId
        """

        with self._connection.session() as session:
            session.run(query, {"callables": callables_data})

        return len(callables_data)


    def _collect_valid_ids(self, ir: IR, project_id: str) -> set[str]:
        """Collect all valid node IDs from IR and database.

        Args:
            ir: Current IR being written.
            project_id: Project identifier.

        Returns:
            Set of valid node IDs.
        """
        # Start with IDs from current IR
        valid_ids: set[str] = set()
        valid_ids.update(ir.modules.keys())
        valid_ids.update(ir.types.keys())
        valid_ids.update(ir.callables.keys())

        # Also query existing IDs from database for this project
        query = """
        MATCH (n)
        WHERE n.projectId = $projectId
        RETURN n.id AS id
        """
        with self._connection.session() as session:
            result = session.run(query, {"projectId": project_id})
            for record in result:
                if record["id"]:
                    valid_ids.add(record["id"])

        return valid_ids

    def _write_relationships(
        self, ir: IR, project_id: str, valid_ids: set[str]
    ) -> tuple[int, list[DanglingReference]]:
        """Write relationships and track dangling references.

        Args:
            ir: IR data containing relationships.
            project_id: Project identifier.
            valid_ids: Set of valid target node IDs.

        Returns:
            Tuple of (relationships written, dangling references).
        """
        relationships_written = 0
        dangling: list[DanglingReference] = []

        # Module CONTAINS Module (sub-modules)
        for module in ir.modules.values():
            for sub_id in module.sub_modules:
                if sub_id in valid_ids:
                    self._write_relationship(module.id, sub_id, "CONTAINS", "Module", "Module")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=module.id,
                        target_id=sub_id,
                        relationship_type="CONTAINS",
                        reason="Sub-module not found in graph",
                    ))

            # Module DECLARES Type
            for type_id in module.declared_types:
                if type_id in valid_ids:
                    self._write_relationship(module.id, type_id, "DECLARES", "Module", "Type")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=module.id,
                        target_id=type_id,
                        relationship_type="DECLARES",
                        reason="Declared type not found in graph",
                    ))

        # Type relationships
        for typ in ir.types.values():
            # Type EXTENDS Type
            for ext_id in typ.extends:
                if ext_id in valid_ids:
                    self._write_relationship(typ.id, ext_id, "EXTENDS", "Type", "Type")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id,
                        target_id=ext_id,
                        relationship_type="EXTENDS",
                        reason="Extended type not found in graph",
                    ))

            # Type IMPLEMENTS Type
            for impl_id in typ.implements:
                if impl_id in valid_ids:
                    self._write_relationship(typ.id, impl_id, "IMPLEMENTS", "Type", "Type")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id,
                        target_id=impl_id,
                        relationship_type="IMPLEMENTS",
                        reason="Implemented interface not found in graph",
                    ))

            # Type EMBEDS Type (Go)
            for embed_id in typ.embeds:
                if embed_id in valid_ids:
                    self._write_relationship(typ.id, embed_id, "EMBEDS", "Type", "Type")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id,
                        target_id=embed_id,
                        relationship_type="EMBEDS",
                        reason="Embedded type not found in graph",
                    ))

            # Type CONTAINS Callable
            for callable_id in typ.callables:
                if callable_id in valid_ids:
                    self._write_relationship(typ.id, callable_id, "CONTAINS", "Type", "Callable")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id,
                        target_id=callable_id,
                        relationship_type="CONTAINS",
                        reason="Callable not found in graph",
                    ))

        # Callable relationships
        for callable in ir.callables.values():
            # Callable CALLS Callable
            for call_id in callable.calls:
                if call_id in valid_ids:
                    self._write_relationship(callable.id, call_id, "CALLS", "Callable", "Callable")
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=callable.id,
                        target_id=call_id,
                        relationship_type="CALLS",
                        reason="Called callable not found in graph",
                    ))

            # Callable OVERRIDES Callable
            if callable.overrides:
                if callable.overrides in valid_ids:
                    self._write_relationship(
                        callable.id, callable.overrides, "OVERRIDES", "Callable", "Callable"
                    )
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=callable.id,
                        target_id=callable.overrides,
                        relationship_type="OVERRIDES",
                        reason="Overridden method not found in graph",
                    ))

            # Callable RETURNS Type
            if callable.return_type:
                if callable.return_type in valid_ids:
                    self._write_relationship(
                        callable.id, callable.return_type, "RETURNS", "Callable", "Type"
                    )
                    relationships_written += 1
                else:
                    dangling.append(DanglingReference(
                        source_id=callable.id,
                        target_id=callable.return_type,
                        relationship_type="RETURNS",
                        reason="Return type not found in graph",
                    ))

        return relationships_written, dangling

    def _write_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: str,
        source_label: str,
        target_label: str,
    ) -> None:
        """Write a single relationship using MERGE."""
        query = f"""
        MATCH (s:{source_label} {{id: $sourceId}})
        MATCH (t:{target_label} {{id: $targetId}})
        MERGE (s)-[r:{rel_type}]->(t)
        """
        with self._connection.session() as session:
            session.run(query, {"sourceId": source_id, "targetId": target_id})

    def clear_project(self, project_id: str) -> int:
        """Clear all data for a project.

        Args:
            project_id: Project identifier.

        Returns:
            Number of nodes deleted.
        """
        query = """
        MATCH (n {projectId: $projectId})
        DETACH DELETE n
        RETURN count(n) AS deleted
        """
        with self._connection.session() as session:
            result = session.run(query, {"projectId": project_id})
            record = result.single()
            return record["deleted"] if record else 0
