"""Rich table builders used by the CLI.

Kept separate to reduce duplication and keep the command module smaller.
"""

from __future__ import annotations

from rich.table import Table


def build_depth_named_table(items) -> Table:
    """Build a standard (Depth, Name, Qualified Name, Kind) table."""
    table = Table(show_header=True)
    table.add_column("Depth")
    table.add_column("Name")
    table.add_column("Qualified Name")
    table.add_column("Kind")
    for item in items:
        table.add_row(
            str(item.depth),
            item.name,
            item.qualified_name,
            item.kind,
        )
    return table


def build_module_dependencies_table(items) -> Table:
    """Build module dependency table for `query modules`."""
    table = Table(show_header=True)
    table.add_column("Target Module")
    table.add_column("Qualified Name")
    table.add_column("Dependency Type")
    for dep in items:
        table.add_row(
            dep.target_module.name,
            dep.target_module.qualified_name,
            dep.dependency_type,
        )
    return table


def build_projects_table(projects, include_archived: bool) -> Table:
    """Build projects listing table."""
    title = "All Projects" if include_archived else "Active Projects"
    table = Table(show_header=True, title=title)
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Path")
    table.add_column("Created At")
    if include_archived:
        table.add_column("Status")

    for project in projects:
        if include_archived:
            status = "[red]Archived[/red]" if project.archived else "[green]Active[/green]"
            table.add_row(
                project.id,
                project.name,
                project.path,
                project.created_at.strftime("%Y-%m-%d %H:%M"),
                status,
            )
        else:
            table.add_row(
                project.id,
                project.name,
                project.path,
                project.created_at.strftime("%Y-%m-%d %H:%M"),
            )

    return table

