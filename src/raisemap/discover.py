"""Find the Python files to analyse, and hold them together as a project."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from raisemap.models import Function
from raisemap.static import Module, analyze_file, propagate

EXCLUDED = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".eggs",
}


def python_files(paths: Sequence[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            found.append(path)
        elif path.is_dir():
            found.extend(
                p for p in sorted(path.rglob("*.py")) if not EXCLUDED.intersection(p.parts)
            )
    return found


def analyze(paths: Sequence[Path]) -> tuple[dict[str, Function], list[Module]]:
    """Analyse every file under ``paths`` and push exceptions along the call graph."""
    modules = []
    for file in python_files(paths):
        try:
            modules.append(analyze_file(file))
        except SyntaxError:
            # A file that does not parse is not analysable. Skipping it is better
            # than refusing to analyse the rest of the project.
            continue
    return propagate(modules), modules
