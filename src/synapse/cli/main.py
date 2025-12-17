"""Synapse CLI - Code topology modeling tool.

This module provides the command-line interface for Synapse,
enabling project registration, code scanning, querying, and export.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

# Load environment variables from .env file
load_dotenv()

# Create main app and sub-apps
app = typer.Typer(
    name="synapse",
    help="Code topology modeling system based on Neo4j",
    no_args_is_help=True,
)

query_app = typer.Typer(
    name="query",
    help="Query code topology data",
    no_args_is_help=True,
)
app.add_typer(query_app, name="query")

# Rich console for formatted output
console = Console()
err_console = Console(stderr=True)

# Global verbose flag
_verbose: bool = False


def set_verbose(verbose: bool) -> None:
    """Set global verbose mode."""
    global _verbose
    _verbose = verbose


def is_verbose() -> bool:
    """Check if verbose mode is enabled."""
    return _verbose


def print_exception(e: Exception) -> None:
    """Print exception details in verbose mode."""
    if _verbose:
        err_console.print("\n[dim]--- Traceback (verbose mode) ---[/dim]")
        err_console.print(f"[dim]{traceback.format_exc()}[/dim]")


@app.callback()
def main_callback(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose output with full tracebacks"),
    ] = False,
) -> None:
    """Synapse CLI - Code topology modeling system."""
    set_verbose(verbose)


def get_connection():
    """Get Neo4j connection with error handling.

    Also ensures the database schema (indexes and constraints) is initialized.
    """
    from synapse.graph.connection import Neo4jConnection, ConnectionError as Neo4jConnError
    from synapse.graph.schema import ensure_schema

    try:
        conn = Neo4jConnection()
        conn.verify_connectivity()
        # Ensure schema is initialized (idempotent)
        ensure_schema(conn)
        return conn
    except Neo4jConnError as e:
        err_console.print(f"[red]Error:[/red] Failed to connect to Neo4j: {e}")
        err_console.print("[yellow]Hint:[/yellow] Check NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD")
        print_exception(e)
        raise typer.Exit(1)


@contextmanager
def open_connection() -> Iterator[object]:
    """Context manager that opens and closes the Neo4j connection."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="Bind host for the HTTP API"),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Bind port for the HTTP API"),
    ] = 8000,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Auto-reload on code changes (dev only)"),
    ] = False,
) -> None:
    """Run Synapse HTTP API server (optional dependency).

    Requires the `api` dependency group (FastAPI + Uvicorn).
    """
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as e:
        err_console.print(
            "[red]Error:[/red] HTTP API dependencies are not installed.\n"
            "[yellow]Hint:[/yellow] Install with: uv sync --group api"
        )
        print_exception(e)
        raise typer.Exit(1)

    uvicorn.run(
        "synapse.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


@app.command()
def init(
    project_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the project directory",
            exists=True,
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
        ),
    ],
    name: Annotated[
        Optional[str],
        typer.Option("--name", "-n", help="Project name (defaults to directory name)"),
    ] = None,
) -> None:
    """Register a project and return its ID.

    Example:
        synapse init /path/to/project
        synapse init /path/to/project --name "My Project"
    """
    from synapse.services.project_service import ProjectService, ProjectExistsError

    with open_connection() as conn:
        service = ProjectService(conn)
        project_name = name or project_path.name

        try:
            result = service.create_project(project_name, str(project_path))
            if result.created:
                console.print(f"[green]✓[/green] Project registered successfully")
            console.print(f"  ID: [cyan]{result.project.id}[/cyan]")
            console.print(f"  Name: {result.project.name}")
            console.print(f"  Path: {result.project.path}")
        except ProjectExistsError as e:
            console.print(f"[yellow]![/yellow] Project already exists at this path")
            console.print(f"  ID: [cyan]{e.existing_project.id}[/cyan]")
            console.print(f"  Name: {e.existing_project.name}")
            print_exception(e)
            raise typer.Exit(1)


@app.command()
def scan(
    project_id: Annotated[str, typer.Argument(help="Project ID to scan")],
) -> None:
    """Scan project code and write to Neo4j.

    Example:
        synapse scan abc123def456
    """
    from synapse.services.project_service import ProjectService, ProjectNotFoundError
    from synapse.services.scanner_service import ScannerService

    with open_connection() as conn:
        # Verify project exists
        project_service = ProjectService(conn)
        project = project_service.get_by_id(project_id)
        if not project:
            err_console.print(f"[red]Error:[/red] Project not found: {project_id}")
            raise typer.Exit(1)

        console.print(f"[blue]Scanning project:[/blue] {project.name}")
        console.print(f"  Path: {project.path}")

        # Run scan
        scanner = ScannerService(conn)
        with console.status("[bold blue]Scanning..."):
            result = scanner.scan_project(project_id, Path(project.path))

        if result.success:
            console.print(f"[green]✓[/green] Scan completed successfully")
            console.print(f"  Languages: {', '.join(l.value for l in result.languages_scanned)}")
            console.print(f"  Modules: {result.modules_count}")
            console.print(f"  Types: {result.types_count}")
            console.print(f"  Callables: {result.callables_count}")
            if result.unresolved_count > 0:
                console.print(f"  [yellow]Unresolved references: {result.unresolved_count}[/yellow]")
            if result.warnings:
                console.print(f"  [yellow]Warnings: {len(result.warnings)}[/yellow]")
                for warning in result.warnings:
                    console.print(f"  [yellow]- {warning}[/yellow]")
        else:
            err_console.print(f"[red]Error:[/red] Scan failed")
            for error in result.errors:
                err_console.print(f"  - {error}")
            raise typer.Exit(1)



@query_app.command("calls")
def query_calls(
    callable_id: Annotated[str, typer.Argument(help="Callable ID to query")],
    direction: Annotated[
        str,
        typer.Option("--direction", "-d", help="Query direction: callers, callees, or both"),
    ] = "both",
    depth: Annotated[
        int,
        typer.Option("--depth", help="Maximum traversal depth"),
    ] = 5,
    page: Annotated[
        int,
        typer.Option("--page", "-p", help="Page number"),
    ] = 1,
    page_size: Annotated[
        int,
        typer.Option("--page-size", "-s", help="Results per page"),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON"),
    ] = False,
) -> None:
    """Query call chain for a callable.

    Example:
        synapse query calls abc123 --direction callees --depth 3
    """
    from synapse.services.query_service import QueryService
    from synapse.cli._tables import build_depth_named_table

    if direction not in ("callers", "callees", "both"):
        err_console.print(f"[red]Error:[/red] Invalid direction: {direction}")
        err_console.print("  Valid options: callers, callees, both")
        raise typer.Exit(1)

    with open_connection() as conn:
        service = QueryService(conn)
        result = service.get_call_chain(
            callable_id=callable_id,
            direction=direction,  # type: ignore
            max_depth=depth,
            page=page,
            page_size=page_size,
        )

        if json_output:
            typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return

        console.print(f"[blue]Call chain for:[/blue] {callable_id}")

        if direction in ("callers", "both") and result.callers:
            console.print(f"\n[green]Callers ({result.total_callers} total):[/green]")
            console.print(build_depth_named_table(result.callers))

        if direction in ("callees", "both") and result.callees:
            console.print(f"\n[green]Callees ({result.total_callees} total):[/green]")
            console.print(build_depth_named_table(result.callees))

        if not result.callers and not result.callees:
            console.print("[yellow]No call chain data found[/yellow]")


@query_app.command("types")
def query_types(
    type_id: Annotated[str, typer.Argument(help="Type ID to query")],
    direction: Annotated[
        str,
        typer.Option("--direction", "-d", help="Query direction: ancestors, descendants, or both"),
    ] = "both",
    page: Annotated[
        int,
        typer.Option("--page", "-p", help="Page number"),
    ] = 1,
    page_size: Annotated[
        int,
        typer.Option("--page-size", "-s", help="Results per page"),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON"),
    ] = False,
) -> None:
    """Query type inheritance hierarchy.

    Example:
        synapse query types abc123 --direction ancestors
    """
    from synapse.services.query_service import QueryService
    from synapse.cli._tables import build_depth_named_table

    if direction not in ("ancestors", "descendants", "both"):
        err_console.print(f"[red]Error:[/red] Invalid direction: {direction}")
        err_console.print("  Valid options: ancestors, descendants, both")
        raise typer.Exit(1)

    with open_connection() as conn:
        service = QueryService(conn)
        result = service.get_type_hierarchy(
            type_id=type_id,
            direction=direction,  # type: ignore
            page=page,
            page_size=page_size,
        )

        if json_output:
            typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return

        console.print(f"[blue]Type hierarchy for:[/blue] {type_id}")

        if direction in ("ancestors", "both") and result.ancestors:
            console.print(f"\n[green]Ancestors ({result.total_ancestors} total):[/green]")
            console.print(build_depth_named_table(result.ancestors))

        if direction in ("descendants", "both") and result.descendants:
            console.print(f"\n[green]Descendants ({result.total_descendants} total):[/green]")
            console.print(build_depth_named_table(result.descendants))

        if not result.ancestors and not result.descendants:
            console.print("[yellow]No type hierarchy data found[/yellow]")


@query_app.command("modules")
def query_modules(
    module_id: Annotated[str, typer.Argument(help="Module ID to query")],
    page: Annotated[
        int,
        typer.Option("--page", "-p", help="Page number"),
    ] = 1,
    page_size: Annotated[
        int,
        typer.Option("--page-size", "-s", help="Results per page"),
    ] = 100,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON"),
    ] = False,
) -> None:
    """Query module dependencies.

    Example:
        synapse query modules abc123
    """
    from synapse.services.query_service import QueryService
    from synapse.cli._tables import build_module_dependencies_table

    with open_connection() as conn:
        service = QueryService(conn)
        result = service.get_module_dependencies(
            module_id=module_id,
            page=page,
            page_size=page_size,
        )

        if json_output:
            typer.echo(json.dumps(asdict(result), ensure_ascii=False, indent=2))
            return

        console.print(f"[blue]Module dependencies for:[/blue] {module_id}")
        console.print(f"Total: {result.total}")

        if result.items:
            console.print(build_module_dependencies_table(result.items))

            if result.has_next:
                console.print(f"[dim]Page {result.page} of more. Use --page to see more.[/dim]")
        else:
            console.print("[yellow]No dependencies found[/yellow]")


@app.command()
def export(
    project_id: Annotated[str, typer.Argument(help="Project ID to export")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output file path"),
    ] = Path("export.json"),
) -> None:
    """Export project IR data to JSON file.

    Example:
        synapse export abc123 -o project.json
    """
    from synapse.services.project_service import ProjectService
    from synapse.core.serializer import serialize
    from synapse.cli._export_helpers import build_merged_ir

    with open_connection() as conn:
        # Verify project exists
        project_service = ProjectService(conn)
        project = project_service.get_by_id(project_id)
        if not project:
            err_console.print(f"[red]Error:[/red] Project not found: {project_id}")
            raise typer.Exit(1)

        console.print(f"[blue]Exporting project:[/blue] {project.name}")

        # Scan to get IR (without writing to graph)
        with console.status("[bold blue]Generating IR..."):
            source_path = Path(project.path)
            merged_ir = build_merged_ir(project_id, source_path)

            if merged_ir is None:
                err_console.print("[red]Error:[/red] No source files found")
                raise typer.Exit(1)

            # Serialize and write
            json_str = serialize(merged_ir)
            output.write_text(json_str, encoding="utf-8")

        console.print(f"[green]✓[/green] Exported to: {output}")
        console.print(f"  Modules: {len(merged_ir.modules)}")
        console.print(f"  Types: {len(merged_ir.types)}")
        console.print(f"  Callables: {len(merged_ir.callables)}")


@app.command()
def list_projects(
    include_archived: Annotated[
        bool,
        typer.Option("--include-archived", "-a", help="Include archived projects"),
    ] = False,
) -> None:
    """List all registered projects.

    Example:
        synapse list-projects
        synapse list-projects --include-archived
    """
    from synapse.services.project_service import ProjectService
    from synapse.cli._tables import build_projects_table

    with open_connection() as conn:
        service = ProjectService(conn)
        projects = service.list_projects(include_archived=include_archived)

        if not projects:
            if include_archived:
                console.print("[yellow]No projects registered[/yellow]")
            else:
                console.print("[yellow]No active projects registered[/yellow]")
            return

        console.print(build_projects_table(projects, include_archived=include_archived))


@app.command()
def delete(
    project_id: Annotated[str, typer.Argument(help="Project ID to archive")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Archive a project (soft delete).

    Archives the project by marking it as deleted. The project data is preserved
    and can be restored later using the 'restore' command, or permanently removed
    using the 'purge' command.

    Example:
        synapse delete abc123
        synapse delete abc123 --force
    """
    from synapse.services.project_service import ProjectService

    with open_connection() as conn:
        service = ProjectService(conn)
        project = service.get_by_id(project_id)

        if not project:
            err_console.print(f"[red]Error:[/red] Project not found: {project_id}")
            raise typer.Exit(1)

        if not force:
            console.print(f"[yellow]Warning:[/yellow] This will archive project '{project.name}'")
            console.print(f"  Path: {project.path}")
            console.print("[dim]Use 'restore' to recover or 'purge' to permanently delete[/dim]")
            confirm = typer.confirm("Are you sure?")
            if not confirm:
                console.print("Cancelled")
                raise typer.Exit(0)

        if service.delete_project(project_id):
            console.print(f"[green]✓[/green] Project archived: {project.name}")
        else:
            err_console.print(f"[red]Error:[/red] Failed to archive project")
            raise typer.Exit(1)


@app.command()
def restore(
    project_id: Annotated[str, typer.Argument(help="Project ID to restore")],
) -> None:
    """Restore an archived project.

    Restores a previously archived project, making it active again.

    Example:
        synapse restore abc123
    """
    from synapse.services.project_service import ProjectService

    with open_connection() as conn:
        service = ProjectService(conn)
        # Check if project exists (including archived)
        project = service.get_by_id(project_id, include_archived=True)

        if not project:
            err_console.print(f"[red]Error:[/red] Project not found: {project_id}")
            raise typer.Exit(1)

        if not project.archived:
            console.print(f"[yellow]![/yellow] Project '{project.name}' is not archived")
            raise typer.Exit(0)

        if service.restore_project(project_id):
            console.print(f"[green]✓[/green] Project restored: {project.name}")
        else:
            err_console.print(f"[red]Error:[/red] Failed to restore project")
            raise typer.Exit(1)


@app.command()
def purge(
    project_id: Annotated[str, typer.Argument(help="Project ID to permanently delete")],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation"),
    ] = False,
) -> None:
    """Permanently delete an archived project.

    This operation cannot be undone. The project must be archived first
    using the 'delete' command before it can be purged.

    Example:
        synapse purge abc123
        synapse purge abc123 --force
    """
    from synapse.services.project_service import ProjectService, ProjectNotArchivedError

    with open_connection() as conn:
        service = ProjectService(conn)
        # Check if project exists (including archived)
        project = service.get_by_id(project_id, include_archived=True)

        if not project:
            err_console.print(f"[red]Error:[/red] Project not found: {project_id}")
            raise typer.Exit(1)

        if not force:
            console.print(
                f"[red]Warning:[/red] This will PERMANENTLY delete project '{project.name}'"
            )
            console.print(f"  Path: {project.path}")
            console.print("[red]This action cannot be undone![/red]")
            confirm = typer.confirm("Are you absolutely sure?")
            if not confirm:
                console.print("Cancelled")
                raise typer.Exit(0)

        try:
            if service.purge_project(project_id):
                console.print(f"[green]✓[/green] Project permanently deleted: {project.name}")
            else:
                err_console.print(f"[red]Error:[/red] Failed to purge project")
                raise typer.Exit(1)
        except ProjectNotArchivedError:
            err_console.print(f"[red]Error:[/red] Project must be archived before purging")
            err_console.print("[yellow]Hint:[/yellow] Use 'synapse delete' first to archive")
            print_exception(ProjectNotArchivedError(project_id))
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
