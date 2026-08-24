"""Record which exceptions actually leave which functions, by running the code.

Static analysis reads what is written. It cannot see an exception raised by a
C extension, or by a call it could not resolve, or through a dynamic dispatch.
Running the test suite can, and the two disagreeing is the interesting part:

* observed but not inferred means the static pass has a blind spot, and the
  function raises something nobody has written down;
* inferred but not observed means either a path the tests never take, or an
  over-eager inference.

Uses ``sys.monitoring`` (Python 3.12+), whose ``PY_UNWIND`` event fires exactly
when an exception leaves a Python function, which is the question being asked.
Below 3.12 there is no cheap way to do this and the pass is skipped rather than
approximated with a tracer that would change the timing of everything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

RESULT_ENV = "RAISEMAP_OBSERVE_DIR"
ROOTS_ENV = "RAISEMAP_ROOTS"
MIN_VERSION = (3, 12)

_SITECUSTOMIZE = '''\
"""Installed by raisemap for one observation run. Not written to your project."""
import atexit
import os
import sys

_dir = os.environ.get("RAISEMAP_OBSERVE_DIR")
# Directories, each ending in a separator, so a root of /a/b does not also match
# a sibling directory called /a/bc.
_roots = tuple(
    r if r.endswith(os.sep) else r + os.sep
    for r in filter(None, os.environ.get("RAISEMAP_ROOTS", "").split(os.pathsep))
)
_seen = {}


def _record(code, instruction_offset, exception):
    filename = code.co_filename
    if _roots and not filename.startswith(_roots):
        return
    key = filename + "|" + code.co_qualname
    _seen.setdefault(key, set()).add(type(exception).__name__)


def _report():
    # One file per process. Every process started under this PYTHONPATH inherits
    # the variable, so a shared filename would have the last one to exit replace
    # everything the others saw. Under xdist that is most of the run.
    path = os.path.join(_dir, "observed-%d.json" % os.getpid())
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({k: sorted(v) for k, v in _seen.items()}, handle)


if _dir and sys.version_info >= (3, 12):
    import json

    monitoring = sys.monitoring
    _TOOL = monitoring.PROFILER_ID
    try:
        monitoring.use_tool_id(_TOOL, "raisemap")
    except ValueError:
        _TOOL = None
    if _TOOL is not None:
        monitoring.register_callback(_TOOL, monitoring.events.PY_UNWIND, _record)
        monitoring.set_events(_TOOL, monitoring.events.PY_UNWIND)
        atexit.register(_report)

# Do not shadow a sitecustomize the project relies on.
_here = os.path.dirname(os.path.abspath(__file__))
for _entry in sys.path:
    try:
        _same = os.path.samefile(_entry, _here)
    except OSError:
        _same = False
    if _same:
        continue
    _next = os.path.join(_entry, "sitecustomize.py")
    if os.path.isfile(_next):
        with open(_next, encoding="utf-8") as _handle:
            exec(compile(_handle.read(), _next, "exec"), globals())
        break
'''


class Unsupported(RuntimeError):
    """The interpreter is too old for sys.monitoring."""


@dataclass
class Observation:
    """What was seen leaving functions during a run."""

    by_function: dict[str, set[str]] = field(default_factory=dict)
    returncode: int = 0
    stderr: str = ""

    def for_qualname(self, path: str, qualname: str) -> set[str]:
        return self.by_function.get(f"{path}|{qualname}", set())


def usable(python: str | None = None) -> tuple[bool, str]:
    """Whether ``python`` can run the observation pass, and why not if it cannot.

    A path that does not exist is a different problem from an interpreter that
    is too old, and telling someone their Python 3.13 is "older than 3.12" wastes
    their afternoon.
    """
    if python is None:
        if sys.version_info >= MIN_VERSION:
            return True, ""
        return False, f"this interpreter is {sys.version.split()[0]}, older than 3.12"
    probe = "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
    try:
        completed = subprocess.run(
            [python, "-c", probe], capture_output=True, check=False, timeout=30
        )
    except OSError as error:
        return False, f"{python} could not be run: {error}"
    except subprocess.TimeoutExpired:
        return False, f"{python} did not respond within 30s"
    if completed.returncode != 0:
        return False, f"{python} is older than 3.12"
    return True, ""


def supported(python: str | None = None) -> bool:
    return usable(python)[0]


def observe(
    command: Sequence[str],
    *,
    roots: Sequence[str | Path] = (),
    python: str | None = None,
    cwd: str | Path | None = None,
    timeout: float | None = 1800.0,
) -> Observation:
    """Run ``command`` and record every exception that left a Python function."""
    interpreter = python or sys.executable
    ok, why = usable(interpreter)
    if not ok:
        raise Unsupported(
            f"{why}. sys.monitoring is where the runtime pass gets its data, and it "
            "arrived in 3.12. Static analysis works on anything."
        )

    with tempfile.TemporaryDirectory(prefix="raisemap-") as tmp:
        (Path(tmp) / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
        results = Path(tmp) / "observations"
        results.mkdir()
        env = {**os.environ}
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join([tmp, existing]) if existing else tmp
        env[RESULT_ENV] = str(results)
        env[ROOTS_ENV] = os.pathsep.join(str(Path(r).resolve()) for r in roots)

        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                env=env,
                cwd=str(cwd) if cwd else None,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return Observation(returncode=124, stderr=f"timed out after {timeout:g}s")

        merged: dict[str, set[str]] = {}
        for report in sorted(results.glob("observed-*.json")):
            try:
                raw = json.loads(report.read_text(encoding="utf-8"))
            except ValueError:  # pragma: no cover - a process killed mid-write
                continue
            for key, names in raw.items():
                merged.setdefault(key, set()).update(names)

        if not merged:
            return Observation(
                returncode=completed.returncode,
                stderr=(completed.stderr or completed.stdout).strip()[-2000:],
            )

    return Observation(
        by_function=merged,
        returncode=completed.returncode,
        stderr=(completed.stderr or "").strip()[-2000:],
    )
