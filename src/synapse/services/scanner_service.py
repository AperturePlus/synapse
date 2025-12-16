"""Scanner service for coordinating code analysis.

This module provides the ScannerService for orchestrating language parsers,
merging multi-language IR data, and writing to the graph database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from synapse.adapters import GoAdapter, JavaAdapter, LanguageAdapter
from synapse.core.models import IR, LanguageType
from synapse.graph import GraphWriter

if TYPE_CHECKING:
    from synapse.graph.connection import Neo4jConnection
    from synapse.graph.writer import WriteResult


@dataclass
class ScanResult:
    """Result of a code scan operation."""

    project_id: str
    languages_scanned: list[LanguageType] = field(default_factory=list)
    modules_count: int = 0
    types_count: int = 0
    callables_count: int = 0
    unresolved_count: int = 0
    nodes_cleared: int = 0
    write_result: WriteResult | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if scan was successful."""
        return len(self.errors) == 0


class ScannerService:
    """Service for scanning code and building the topology graph.

    Coordinates language adapters to parse source code, merges IR from
    multiple languages, and writes the result to Neo4j.
    """

    # Mapping of file extensions to language types
    LANGUAGE_EXTENSIONS: dict[str, LanguageType] = {
        ".java": LanguageType.JAVA,
        ".go": LanguageType.GO,
    }

    def __init__(self, connection: Neo4jConnection) -> None:
        """Initialize scanner service.

        Args:
            connection: Neo4j connection instance.
        """
        self._connection = connection
        self._writer = GraphWriter(connection)


    def scan_project(
        self,
        project_id: str,
        source_path: Path,
        clear_before_scan: bool = True,
    ) -> ScanResult:
        """Scan a project's source code and write to graph.

        Detects languages present in the source directory, runs appropriate
        adapters, merges IR data, and writes to Neo4j.

        Args:
            project_id: Project identifier for scoping.
            source_path: Root directory of source code.
            clear_before_scan: If True, clears existing project data before
                writing new data. This ensures deleted/renamed code entities
                don't remain as stale nodes. Default is True.

        Returns:
            ScanResult with statistics and any errors.
        """
        result = ScanResult(project_id=project_id)

        if not source_path.exists():
            result.errors.append(f"Source path does not exist: {source_path}")
            return result

        # Clear existing project data to avoid stale nodes from deleted/renamed code
        if clear_before_scan:
            result.nodes_cleared = self._writer.clear_project(project_id)

        # Detect languages present in the source directory
        detected_languages = self._detect_languages(source_path)

        if not detected_languages:
            result.errors.append("No supported source files found")
            return result

        # Create adapters for detected languages
        adapters = self._create_adapters(project_id, detected_languages)

        # Run each adapter and collect IR
        merged_ir: IR | None = None

        for adapter in adapters:
            try:
                ir = adapter.analyze(source_path)
                result.languages_scanned.append(adapter.language_type)

                if merged_ir is None:
                    merged_ir = ir
                else:
                    merged_ir = merged_ir.merge(ir)

            except Exception as e:
                result.errors.append(
                    f"Error scanning {adapter.language_type.value}: {e}"
                )

        if merged_ir is None:
            result.errors.append("No IR data produced from scan")
            return result

        # Update counts
        result.modules_count = len(merged_ir.modules)
        result.types_count = len(merged_ir.types)
        result.callables_count = len(merged_ir.callables)
        result.unresolved_count = len(merged_ir.unresolved)

        # Write to graph
        try:
            write_result = self._writer.write_ir(merged_ir, project_id)
            result.write_result = write_result
        except Exception as e:
            result.errors.append(f"Error writing to graph: {e}")

        return result

    def _detect_languages(self, source_path: Path) -> set[LanguageType]:
        """Detect programming languages present in source directory.

        Args:
            source_path: Root directory to scan.

        Returns:
            Set of detected language types.
        """
        detected: set[LanguageType] = set()

        for ext, lang in self.LANGUAGE_EXTENSIONS.items():
            # Check if any files with this extension exist
            if list(source_path.rglob(f"*{ext}")):
                detected.add(lang)

        return detected

    def _create_adapters(
        self, project_id: str, languages: set[LanguageType]
    ) -> list[LanguageAdapter]:
        """Create language adapters for the specified languages.

        Args:
            project_id: Project identifier.
            languages: Set of languages to create adapters for.

        Returns:
            List of language adapter instances.
        """
        adapters: list[LanguageAdapter] = []

        for lang in languages:
            if lang == LanguageType.JAVA:
                adapters.append(JavaAdapter(project_id))
            elif lang == LanguageType.GO:
                adapters.append(GoAdapter(project_id))

        return adapters

    def get_supported_languages(self) -> list[LanguageType]:
        """Get list of supported programming languages.

        Returns:
            List of supported language types.
        """
        return list(LanguageType)
