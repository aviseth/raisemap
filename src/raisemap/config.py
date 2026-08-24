"""``[tool.raisemap]`` in pyproject.toml.

[tool.raisemap]
paths = ["src"]
lock = "raisemap.lock"
require_docstrings = false   # fail `docs` when a raising function has no Raises: section
ignore = ["NotImplementedError"]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib  # type: ignore[import-not-found]


class ConfigError(ValueError):
    """pyproject.toml has a ``[tool.raisemap]`` section we cannot use."""


@dataclass
class Config:
    paths: list[Path] = field(default_factory=list)
    lock: Path = field(default_factory=lambda: Path("raisemap.lock"))
    require_docstrings: bool = False
    ignore: set[str] = field(default_factory=set)
    source: Path | None = None


def find_pyproject(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def load(path: Path | None = None) -> Config:
    pyproject = path or find_pyproject()
    if pyproject is None:
        return Config()
    try:
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{pyproject}: not valid TOML: {error}") from error

    tool = data.get("tool")
    if tool is None:
        return Config(source=pyproject)
    if not isinstance(tool, dict):
        raise ConfigError(f"{pyproject}: [tool] must be a table, not {type(tool).__name__}")
    section = tool.get("raisemap")
    if section is None:
        return Config(source=pyproject)
    if not isinstance(section, dict):
        raise ConfigError(
            f"{pyproject}: [tool.raisemap] must be a table, not {type(section).__name__}"
        )

    def strings(key: str) -> list[str]:
        value = section.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{pyproject}: {key} must be a list of strings")
        return list(value)

    require = section.get("require_docstrings", False)
    if not isinstance(require, bool):
        raise ConfigError(f"{pyproject}: require_docstrings must be true or false")

    lock = section.get("lock", "raisemap.lock")
    if not isinstance(lock, str) or not lock.strip():
        # str() of a list would give a path of "['a']", which the CLI then
        # reads and writes.
        raise ConfigError(f"{pyproject}: lock must be a path, not {lock!r}")

    return Config(
        paths=[pyproject.parent / p for p in strings("paths")],
        lock=pyproject.parent / lock,
        require_docstrings=require,
        ignore=set(strings("ignore")),
        source=pyproject,
    )
