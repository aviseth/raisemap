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

LOCK_VERSION = 2
DEFAULT_PATH = "raisemap.lock"


@dataclass
class Lock:
    """What a lock file holds.

    ``public`` is every public function the recording run saw, not only the ones
    that raise. Without it a key missing from ``functions`` is ambiguous: the
    function might be new, or it might have existed and started raising, and only
    the second is a change in behaviour worth failing a build over.
    """

    functions: dict[str, list[str]] = field(default_factory=dict)
    public: set[str] = field(default_factory=set)


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


def lockable_keys(functions: dict[str, Function], *, public_only: bool = True) -> set[str]:
    """Every function the lock could contain, whether it raises anything or not."""
    return {key for key, function in functions.items() if function.is_public or not public_only}


def read(path: str | Path = DEFAULT_PATH) -> Lock:
    """Read a lock file. A missing file is an empty lock, not an error."""
    file = Path(path)
    if not file.is_file():
        return Lock()
    data = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        # A corrupt but parsable lock is realistic after a bad merge, and an
        # AttributeError out of here reaches the user as a traceback.
        raise ValueError(
            f"{file}: expected an object at the top level, found {type(data).__name__}"
        )
    version = data.get("version")
    if version != LOCK_VERSION:
        raise ValueError(
            f"{file}: unsupported lock version {version!r}; delete it and re-run "
            "'raisemap check --update' to regenerate"
        )
    functions = data.get("functions") or {}
    public = data.get("public") or []
    if not isinstance(functions, dict) or not isinstance(public, list):
        raise ValueError(f"{file}: 'functions' must be an object and 'public' a list")
    return Lock(
        functions={k: list(v) for k, v in functions.items()},
        public=set(public),
    )


def write(path: str | Path, lock: Lock) -> None:
    """Write the lock file, sorted, with a trailing newline so diffs stay clean."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": LOCK_VERSION,
        "functions": dict(sorted(lock.functions.items())),
        "public": sorted(lock.public),
    }
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


def newly_raising(lock: Lock, current: dict[str, list[str]]) -> list[str]:
    """Functions that existed and have started raising.

    A key absent from ``lock.functions`` means either the function is new or it
    existed and raised nothing. Reporting both would contradict ``compare``,
    which deliberately says nothing about functions that did not exist before.
    ``lock.public`` is what tells them apart.
    """
    return sorted((set(current) - set(lock.functions)) & lock.public)
