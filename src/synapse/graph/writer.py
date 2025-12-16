"""Graph writer for persisting IR data to Neo4j.

This module implements the GraphWriter with three-phase write logic:
1. Write all nodes (Module, Type, Callable)
2. Write relationships (verify target nodes exist)
3. Record dangling references
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from synapse.core.models import IR
    from synapse.graph.connection import Neo4jConnection

# Valid Neo4j labels and relationship types (alphanumeric + underscore)
_VALID_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Allowed labels for nodes
_ALLOWED_LABELS = frozenset({"Module", "Type", "Callable", "Project"})

# Allowed relationship types
_ALLOWED_REL_TYPES = frozenset({
    "CONTAINS", "DECLARES", "EXTENDS", "IMPLEMENTS",
    "EMBEDS", "CALLS", "OVERRIDES", "RETURNS",
})


def _validate_identifier(value: str, allowed: frozenset[str], kind: str) -> None:
    """Validate a Cypher identifier against allowed values.

    Args:
        value: The identifier to validate.
        allowed: Set of allowed values.
        kind: Description for error message (e.g., "label", "relationship type").

    Raises:
        ValueError: If identifier is not in allowed set or has invalid format.
    """
    if value not in allowed:
        raise ValueError(f"Invalid {kind}: {value!r}. Allowed: {sorted(allowed)}")
    if not _VALID_IDENTIFIER_PATTERN.match(value):
        raise ValueError(f"Invalid {kind} format: {value!r}")


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
        from synapse.core.config import get_config

        self._connection = connection
        self._config = get_config()
        self._batch_size = self._config.batch_write_size

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
        """Write Module nodes using UNWIND batch with chunking."""
        if not ir.modules:
            return 0

        modules_data = [
            {
                "id": m.id,
                "name": m.name,
                "qualifiedName": m.qualified_name,
                "path": m.path,
                "languageType": m.language_type.value,
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

        self._write_in_chunks(query, modules_data, "modules")
        return len(modules_data)

    def _write_types(self, ir: IR, project_id: str) -> int:
        """Write Type nodes using UNWIND batch with chunking."""
        if not ir.types:
            return 0

        types_data = [
            {
                "id": t.id,
                "name": t.name,
                "qualifiedName": t.qualified_name,
                "kind": t.kind.value,
                "modifiers": t.modifiers,
                "languageType": t.language_type.value,
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

        self._write_in_chunks(query, types_data, "types")
        return len(types_data)

    def _write_callables(self, ir: IR, project_id: str) -> int:
        """Write Callable nodes using UNWIND batch with chunking."""
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
                "languageType": c.language_type.value,
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

        self._write_in_chunks(query, callables_data, "callables")
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
        """Write relationships and track dangling references using batch operations.

        Args:
            ir: IR data containing relationships.
            project_id: Project identifier.
            valid_ids: Set of valid target node IDs.

        Returns:
            Tuple of (relationships written, dangling references).
        """
        dangling: list[DanglingReference] = []

        # Collect relationships by type for batch processing
        rels: dict[tuple[str, str, str], list[tuple[str, str]]] = {
            ("Module", "CONTAINS", "Module"): [],
            ("Module", "DECLARES", "Type"): [],
            ("Type", "EXTENDS", "Type"): [],
            ("Type", "IMPLEMENTS", "Type"): [],
            ("Type", "EMBEDS", "Type"): [],
            ("Type", "CONTAINS", "Callable"): [],
            ("Callable", "CALLS", "Callable"): [],
            ("Callable", "OVERRIDES", "Callable"): [],
            ("Callable", "RETURNS", "Type"): [],
        }

        # Module relationships
        for module in ir.modules.values():
            for sub_id in module.sub_modules:
                if sub_id in valid_ids:
                    rels[("Module", "CONTAINS", "Module")].append((module.id, sub_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=module.id, target_id=sub_id,
                        relationship_type="CONTAINS", reason="Sub-module not found",
                    ))
            for type_id in module.declared_types:
                if type_id in valid_ids:
                    rels[("Module", "DECLARES", "Type")].append((module.id, type_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=module.id, target_id=type_id,
                        relationship_type="DECLARES", reason="Declared type not found",
                    ))

        # Type relationships
        for typ in ir.types.values():
            for ext_id in typ.extends:
                if ext_id in valid_ids:
                    rels[("Type", "EXTENDS", "Type")].append((typ.id, ext_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id, target_id=ext_id,
                        relationship_type="EXTENDS", reason="Extended type not found",
                    ))
            for impl_id in typ.implements:
                if impl_id in valid_ids:
                    rels[("Type", "IMPLEMENTS", "Type")].append((typ.id, impl_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id, target_id=impl_id,
                        relationship_type="IMPLEMENTS", reason="Implemented interface not found",
                    ))
            for embed_id in typ.embeds:
                if embed_id in valid_ids:
                    rels[("Type", "EMBEDS", "Type")].append((typ.id, embed_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id, target_id=embed_id,
                        relationship_type="EMBEDS", reason="Embedded type not found",
                    ))
            for callable_id in typ.callables:
                if callable_id in valid_ids:
                    rels[("Type", "CONTAINS", "Callable")].append((typ.id, callable_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=typ.id, target_id=callable_id,
                        relationship_type="CONTAINS", reason="Callable not found",
                    ))

        # Callable relationships
        for call in ir.callables.values():
            for call_id in call.calls:
                if call_id in valid_ids:
                    rels[("Callable", "CALLS", "Callable")].append((call.id, call_id))
                else:
                    dangling.append(DanglingReference(
                        source_id=call.id, target_id=call_id,
                        relationship_type="CALLS", reason="Called callable not found",
                    ))
            if call.overrides and call.overrides in valid_ids:
                rels[("Callable", "OVERRIDES", "Callable")].append((call.id, call.overrides))
            elif call.overrides:
                dangling.append(DanglingReference(
                    source_id=call.id, target_id=call.overrides,
                    relationship_type="OVERRIDES", reason="Overridden method not found",
                ))
            if call.return_type and call.return_type in valid_ids:
                rels[("Callable", "RETURNS", "Type")].append((call.id, call.return_type))
            elif call.return_type:
                dangling.append(DanglingReference(
                    source_id=call.id, target_id=call.return_type,
                    relationship_type="RETURNS", reason="Return type not found",
                ))

        # Batch write all relationships
        total_written = 0
        for (src_label, rel_type, tgt_label), pairs in rels.items():
            if pairs:
                total_written += self._write_relationships_batch(
                    pairs, rel_type, src_label, tgt_label
                )

        return total_written, dangling

    def _write_relationships_batch(
        self,
        pairs: list[tuple[str, str]],
        rel_type: str,
        source_label: str,
        target_label: str,
    ) -> int:
        """Write relationships in batch using UNWIND with chunking.

        Args:
            pairs: List of (source_id, target_id) tuples.
            rel_type: Relationship type (must be in _ALLOWED_REL_TYPES).
            source_label: Source node label (must be in _ALLOWED_LABELS).
            target_label: Target node label (must be in _ALLOWED_LABELS).

        Returns:
            Number of relationships written.

        Raises:
            ValueError: If labels or relationship type are not allowed.
        """
        if not pairs:
            return 0

        # Validate to prevent Cypher injection
        _validate_identifier(source_label, _ALLOWED_LABELS, "label")
        _validate_identifier(target_label, _ALLOWED_LABELS, "label")
        _validate_identifier(rel_type, _ALLOWED_REL_TYPES, "relationship type")

        data = [{"s": s, "t": t} for s, t in pairs]

        query = f"""
        UNWIND $rels AS r
        MATCH (s:{source_label} {{id: r.s}})
        MATCH (t:{target_label} {{id: r.t}})
        MERGE (s)-[rel:{rel_type}]->(t)
        """
        self._write_in_chunks(query, data, "rels")
        return len(pairs)

    def _write_in_chunks(
        self, query: str, data: list[dict], param_name: str
    ) -> None:
        """Write data in chunks to avoid oversized requests.

        Args:
            query: Cypher query with UNWIND.
            data: List of data items to write.
            param_name: Parameter name in the query.
        """
        with self._connection.session() as session:
            for i in range(0, len(data), self._batch_size):
                chunk = data[i : i + self._batch_size]
                session.run(query, {param_name: chunk})

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
