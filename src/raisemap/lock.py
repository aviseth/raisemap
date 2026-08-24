"""A committed record of what the public API raises, so a change to it is visible.

Adding an exception to a public function is a breaking change for anyone catching
around it, and Python gives you no way to notice. This is the same idea as a
lockfile: write down what is true now, and make the diff show up in review when
it stops being true.

Only public functions are recorded. A private helper gaining an exception is not
somebody else's problem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from raisemap.models import Function

LOCK_VERSION = 1
DEFAULT_PATH = "raisemap.lock"


@dataclass
class Drift:
    """What changed for one function."""

    key: str
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def build(functions: dict[str, Function], *, public_only: bool = True) -> dict[str, list[str]]:
    """The lockable view: public functions that raise something."""
    return {
        key: sorted(function.raises.names())
        for key, function in sorted(functions.items())
        if (function.is_public or not public_only) and function.raises
    }


def read(path: str | Path = DEFAULT_PATH) -> dict[str, list[str]]:
    """Read a lock file. A missing file is an empty lock, not an error."""
    file = Path(path)
    if not file.is_file():
        return {}
    data = json.loads(file.read_text(encoding="utf-8"))
    version = data.get("version")
    if version != LOCK_VERSION:
        raise ValueError(
            f"{file}: unsupported lock version {version!r}; delete it and re-run "
            "'raisemap check --update' to regenerate"
        )
    return {k: list(v) for k, v in (data.get("functions") or {}).items()}


def write(path: str | Path, functions: dict[str, list[str]]) -> None:
    """Write the lock file, sorted, with a trailing newline so diffs stay clean."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": LOCK_VERSION, "functions": dict(sorted(functions.items()))}
    file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def compare(locked: dict[str, list[str]], current: dict[str, list[str]]) -> list[Drift]:
    """Diff two lock views, ignoring functions that are new or gone.

    A function that did not exist before has nothing to have changed, and one
    that has been deleted is a separate conversation. Only functions present in
    both are compared, which keeps the output about behaviour rather than churn.
    """
    drifts = []
    for key in sorted(set(locked) & set(current)):
        before, after = set(locked[key]), set(current[key])
        drift = Drift(key=key, added=sorted(after - before), removed=sorted(before - after))
        if drift.changed:
            drifts.append(drift)
    return drifts


def newly_raising(locked: dict[str, list[str]], current: dict[str, list[str]]) -> list[str]:
    """Public functions that raise now and did not appear in the lock at all."""
    return sorted(set(current) - set(locked))
