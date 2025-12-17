"""Helpers for CLI export command.

Separated to keep `synapse.cli.main` focused on CLI wiring and user interaction.
"""

from __future__ import annotations

from pathlib import Path


def build_merged_ir(project_id: str, source_path: Path):
    """Analyze supported source files and merge IR across languages.

    Returns None if no supported source files are found.
    """
    from synapse.adapters import GoAdapter, JavaAdapter
    from synapse.core.models import IR, LanguageType

    merged_ir: IR | None = None

    for ext, language in [(".java", LanguageType.JAVA), (".go", LanguageType.GO)]:
        if not list(source_path.rglob(f"*{ext}")):
            continue

        adapter = JavaAdapter(project_id) if language == LanguageType.JAVA else GoAdapter(project_id)
        ir = adapter.analyze(source_path)
        merged_ir = ir if merged_ir is None else merged_ir.merge(ir)

    return merged_ir

