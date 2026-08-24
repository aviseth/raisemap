"""Find the Python files to analyse, and hold them together as a project."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from raisemap.models import Function
from raisemap.static import Module, analyze_file, collect_hierarchy, propagate

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
    """Analyse every file under ``paths`` and push exceptions along the call graph.

    Two passes, deliberately. The first only needs the exception classes the
    project defines; the second re-reads each file with the whole project's
    hierarchy in hand, so a function that raises its own ValueError subclass and
    catches ValueError in the same body is correctly reported as raising
    nothing. With one pass that suppression falls back to the builtin tree, and
    the tool mis-reports its own source.
    """
    files = python_files(paths)
    first = [module for module in (_read(file) for file in files) if module is not None]
    tree = collect_hierarchy(first)

    modules = [
        module for module in (_read(file, hierarchy=tree) for file in files) if module is not None
    ]
    return propagate(modules, tree), modules


def _read(file: Path, hierarchy: object = None) -> Module | None:
    """Analyse one file, or return None if it cannot be read or parsed.

    One unreadable file should not end the run. A module declaring a non-UTF-8
    encoding raises UnicodeDecodeError and one the process cannot open raises
    OSError, and neither is a SyntaxError.
    """
    try:
        return analyze_file(file, hierarchy=hierarchy)  # type: ignore[arg-type]
    except (SyntaxError, UnicodeDecodeError, OSError, ValueError):
        return None
