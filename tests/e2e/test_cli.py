"""End-to-end tests for Synapse CLI.

Tests the complete CLI workflow including project registration,
scanning, querying, and export functionality.

Requirements: 9.1-9.5
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from synapse.cli.main import app

runner = CliRunner()


@pytest.fixture
def mock_connection():
    """Create a mock Neo4j connection."""
    mock_conn = MagicMock()
    mock_session = MagicMock()
    mock_conn.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_conn.session.return_value.__exit__ = MagicMock(return_value=None)
    mock_conn.verify_connectivity.return_value = True
    return mock_conn


@pytest.fixture
def java_project(tmp_path: Path) -> Path:
    """Create a minimal Java project for testing."""
    project_dir = tmp_path / "java-project"
    project_dir.mkdir()

    # Create a simple Java file
    java_file = project_dir / "Main.java"
    java_file.write_text("""
package com.example;

public class Main {
    public static void main(String[] args) {
        System.out.println("Hello");
    }
}
""")
    return project_dir


class TestCliHelp:
    """Test CLI help and basic commands."""

    def test_main_help(self):
        """Test main help displays correctly."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "synapse" in result.output.lower() or "code topology" in result.output.lower()

    def test_query_help(self):
        """Test query subcommand help."""
        result = runner.invoke(app, ["query", "--help"])
        assert result.exit_code == 0
        assert "calls" in result.output
        assert "types" in result.output
        assert "modules" in result.output


class TestInitCommand:
    """Test the init command."""

    def test_init_nonexistent_path(self):
        """Test init with non-existent path fails."""
        result = runner.invoke(app, ["init", "/nonexistent/path/12345"])
        assert result.exit_code != 0

    def test_init_success(self, tmp_path: Path, mock_connection):
        """Test successful project initialization."""
        from synapse.services.project_service import Project, ProjectCreateResult
        from datetime import datetime, timezone

        project_dir = tmp_path / "test-project"
        project_dir.mkdir()

        mock_project = Project(
            id="abc123",
            name="test-project",
            path=str(project_dir),
            created_at=datetime.now(timezone.utc),
        )
        mock_result = ProjectCreateResult(project=mock_project, created=True)

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.create_project.return_value = mock_result

                result = runner.invoke(app, ["init", str(project_dir)])

                assert result.exit_code == 0
                assert "abc123" in result.output

    def test_init_duplicate_project(self, tmp_path: Path, mock_connection):
        """Test init with duplicate path returns error."""
        from synapse.services.project_service import Project, ProjectExistsError
        from datetime import datetime, timezone

        project_dir = tmp_path / "existing-project"
        project_dir.mkdir()

        existing_project = Project(
            id="existing123",
            name="existing-project",
            path=str(project_dir),
            created_at=datetime.now(timezone.utc),
        )

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.create_project.side_effect = ProjectExistsError(existing_project)

                result = runner.invoke(app, ["init", str(project_dir)])

                assert result.exit_code == 1
                assert "already exists" in result.output



class TestScanCommand:
    """Test the scan command."""

    def test_scan_project_not_found(self, mock_connection):
        """Test scan with non-existent project ID."""
        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_by_id.return_value = None

                result = runner.invoke(app, ["scan", "nonexistent123"])

                assert result.exit_code == 1
                assert "not found" in result.output.lower()

    def test_scan_success(self, tmp_path: Path, mock_connection):
        """Test successful project scan."""
        from synapse.services.project_service import Project
        from synapse.services.scanner_service import ScanResult
        from synapse.core.models import LanguageType
        from datetime import datetime, timezone

        project_dir = tmp_path / "scan-project"
        project_dir.mkdir()

        mock_project = Project(
            id="scan123",
            name="scan-project",
            path=str(project_dir),
            created_at=datetime.now(timezone.utc),
        )

        mock_scan_result = ScanResult(
            project_id="scan123",
            languages_scanned=[LanguageType.JAVA],
            modules_count=2,
            types_count=5,
            callables_count=10,
        )

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockProjectService:
                with patch("synapse.services.scanner_service.ScannerService") as MockScannerService:
                    mock_project_service = MockProjectService.return_value
                    mock_project_service.get_by_id.return_value = mock_project

                    mock_scanner_service = MockScannerService.return_value
                    mock_scanner_service.scan_project.return_value = mock_scan_result

                    result = runner.invoke(app, ["scan", "scan123"])

                    assert result.exit_code == 0
                    assert "completed" in result.output.lower()


class TestQueryCommands:
    """Test query subcommands."""

    def test_query_calls_invalid_direction(self, mock_connection):
        """Test query calls with invalid direction."""
        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            result = runner.invoke(app, ["query", "calls", "abc123", "--direction", "invalid"])
            assert result.exit_code == 1
            assert "invalid direction" in result.output.lower()

    def test_query_calls_success(self, mock_connection):
        """Test successful call chain query."""
        from synapse.graph.queries import CallChainResult, CallableInfo

        mock_result = CallChainResult(
            root_id="callable123",
            callers=[
                CallableInfo(
                    id="caller1",
                    name="callerMethod",
                    qualified_name="com.example.Caller.callerMethod",
                    kind="METHOD",
                    signature="()V",
                    depth=1,
                )
            ],
            callees=[],
            total_callers=1,
            total_callees=0,
        )

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.query_service.QueryService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_call_chain.return_value = mock_result

                result = runner.invoke(app, ["query", "calls", "callable123"])

                assert result.exit_code == 0
                assert "callerMethod" in result.output

    def test_query_types_success(self, mock_connection):
        """Test successful type hierarchy query."""
        from synapse.graph.queries import TypeHierarchyResult, TypeInfo

        mock_result = TypeHierarchyResult(
            root_id="type123",
            ancestors=[
                TypeInfo(
                    id="parent1",
                    name="ParentClass",
                    qualified_name="com.example.ParentClass",
                    kind="CLASS",
                    depth=1,
                )
            ],
            descendants=[],
            total_ancestors=1,
            total_descendants=0,
        )

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.query_service.QueryService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_type_hierarchy.return_value = mock_result

                result = runner.invoke(app, ["query", "types", "type123"])

                assert result.exit_code == 0
                assert "ParentClass" in result.output

    def test_query_modules_success(self, mock_connection):
        """Test successful module dependency query."""
        from synapse.graph.queries import PaginatedResult, ModuleDependency, ModuleInfo

        mock_result = PaginatedResult(
            items=[
                ModuleDependency(
                    source_module=ModuleInfo(
                        id="mod1",
                        name="source",
                        qualified_name="com.example.source",
                        path="/src/source",
                    ),
                    target_module=ModuleInfo(
                        id="mod2",
                        name="target",
                        qualified_name="com.example.target",
                        path="/src/target",
                    ),
                    dependency_type="EXTENDS",
                )
            ],
            page=1,
            page_size=100,
            total=1,
            has_next=False,
        )

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.query_service.QueryService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_module_dependencies.return_value = mock_result

                result = runner.invoke(app, ["query", "modules", "mod1"])

                assert result.exit_code == 0
                assert "target" in result.output


class TestExportCommand:
    """Test the export command."""

    def test_export_project_not_found(self, mock_connection):
        """Test export with non-existent project."""
        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_by_id.return_value = None

                result = runner.invoke(app, ["export", "nonexistent123"])

                assert result.exit_code == 1
                assert "not found" in result.output.lower()


class TestListProjectsCommand:
    """Test the list-projects command."""

    def test_list_projects_empty(self, mock_connection):
        """Test list projects when no projects exist."""
        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.list_projects.return_value = []

                result = runner.invoke(app, ["list-projects"])

                assert result.exit_code == 0
                assert "no projects" in result.output.lower()

    def test_list_projects_success(self, mock_connection):
        """Test list projects with existing projects."""
        from synapse.services.project_service import Project
        from datetime import datetime, timezone

        mock_projects = [
            Project(
                id="proj1",
                name="Project One",
                path="/path/to/one",
                created_at=datetime.now(timezone.utc),
            ),
            Project(
                id="proj2",
                name="Project Two",
                path="/path/to/two",
                created_at=datetime.now(timezone.utc),
            ),
        ]

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.list_projects.return_value = mock_projects

                result = runner.invoke(app, ["list-projects"])

                assert result.exit_code == 0
                assert "Project One" in result.output
                assert "Project Two" in result.output


class TestDeleteCommand:
    """Test the delete command."""

    def test_delete_project_not_found(self, mock_connection):
        """Test delete with non-existent project."""
        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_by_id.return_value = None

                result = runner.invoke(app, ["delete", "nonexistent123", "--force"])

                assert result.exit_code == 1
                assert "not found" in result.output.lower()

    def test_delete_success_with_force(self, mock_connection):
        """Test successful project deletion with force flag."""
        from synapse.services.project_service import Project
        from datetime import datetime, timezone

        mock_project = Project(
            id="delete123",
            name="delete-project",
            path="/path/to/delete",
            created_at=datetime.now(timezone.utc),
        )

        with patch("synapse.cli.main.get_connection", return_value=mock_connection):
            with patch("synapse.services.project_service.ProjectService") as MockService:
                mock_service = MockService.return_value
                mock_service.get_by_id.return_value = mock_project
                mock_service.delete_project.return_value = True

                result = runner.invoke(app, ["delete", "delete123", "--force"])

                assert result.exit_code == 0
                assert "deleted" in result.output.lower()
