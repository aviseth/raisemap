"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from raisemap import __version__
from raisemap.models import Function

EPILOG = """\
examples:
  raisemap show src
  raisemap show src --function mypkg.io.load_config
  raisemap docs src
  raisemap observe src --command "pytest -q"
  raisemap check --update
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="raisemap",
        description="Work out which exceptions a function can actually raise.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"raisemap {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="list what each function can raise")
    show.add_argument("paths", nargs="*", type=Path)
    show.add_argument("--function", help="only this function, by dotted name")
    show.add_argument("--all", dest="show_all", action="store_true", help="include private ones")
    show.add_argument("--why", action="store_true", help="show where each exception comes from")
    show.add_argument("--json", action="store_true")

    docs = sub.add_parser("docs", help="compare docstrings against what is raised")
    docs.add_argument("paths", nargs="*", type=Path)
    docs.add_argument("--all", dest="show_all", action="store_true")
    docs.add_argument("--require", action="store_true", help="fail when a docstring is missing")
    docs.add_argument("--json", action="store_true")

    observe = sub.add_parser("observe", help="run a command and reconcile with the static pass")
    observe.add_argument("paths", nargs="*", type=Path)
    # dest is not "command": that is the subparser's own dest, and argparse
    # would overwrite the subcommand name with this value.
    observe.add_argument("--command", dest="run", help="what to run, defaults to pytest")
    observe.add_argument("--timeout", type=float, default=1800.0)
    observe.add_argument("--json", action="store_true")

    check = sub.add_parser("check", help="fail when the public API's exceptions change")
    check.add_argument("paths", nargs="*", type=Path)
    check.add_argument("--config", type=Path)
    check.add_argument("--update", action="store_true", help="rewrite the lock and pass")
    check.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "show":
            return _show(args)
        if args.command == "docs":
            return _docs(args)
        if args.command == "observe":
            return _observe(args)
        if args.command == "check":
            return _check(args)
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except (ValueError, OSError) as error:
        print(f"raisemap: {error}", file=sys.stderr)
        return 2
    return 2


def _paths(args: argparse.Namespace) -> list[Path]:
    from raisemap.config import load

    if args.paths:
        return list(args.paths)
    configured = load(getattr(args, "config", None)).paths
    return configured or [Path()]


def _analyze(args: argparse.Namespace) -> dict[str, Function]:
    from raisemap.discover import analyze

    functions, _ = analyze(_paths(args))
    return functions


def _visible(functions: dict[str, Function], show_all: bool) -> dict[str, Function]:
    return {
        key: function
        for key, function in sorted(functions.items())
        if (show_all or function.is_public) and function.raises
    }


def _show(args: argparse.Namespace) -> int:
    from raisemap.report import style, table

    functions = _analyze(args)
    if args.function:
        matches = {
            k: v
            for k, v in functions.items()
            if k == args.function or k.endswith(f".{args.function}")
        }
        if not matches:
            print(f"raisemap: no function called {args.function!r}", file=sys.stderr)
            return 1
        visible = matches
    else:
        visible = _visible(functions, args.show_all)

    if args.json:
        print(
            json.dumps(
                {
                    key: {
                        "raises": sorted(f.raises.names()),
                        "location": f.location,
                        "public": f.is_public,
                        "why": {
                            name: [str(s) for s in sources]
                            for name, sources in sorted(f.raises.exceptions.items())
                        },
                    }
                    for key, f in visible.items()
                },
                indent=2,
            )
        )
        return 0

    if not visible:
        print("nothing raises anything that can be inferred")
        return 0

    if args.why:
        for key, function in visible.items():
            print(style(key, "bold") + style(f"  {function.location}", "dim"))
            for name, sources in sorted(function.raises.exceptions.items()):
                print(f"  {name}")
                for source in sources:
                    print(f"      {source}")
            print()
        return 0

    print(
        table(
            ["raises", "function"],
            [(", ".join(sorted(f.raises.names())), key) for key, f in visible.items()],
        )
    )
    return 0


def _docs(args: argparse.Namespace) -> int:
    from raisemap.config import load
    from raisemap.report import style, table

    config = load()
    functions = _analyze(args)
    visible = _visible(functions, args.show_all)

    rows = []
    problems = 0
    for key, function in visible.items():
        missing = sorted(function.undocumented() - config.ignore)
        extra = sorted(function.overdocumented() - config.ignore)
        needs_docstring = (args.require or config.require_docstrings) and not function.has_docstring
        if not missing and not extra and not needs_docstring:
            continue
        problems += 1
        note = []
        if needs_docstring:
            note.append("no docstring")
        if missing:
            note.append("undocumented: " + ", ".join(missing))
        if extra:
            note.append("documented but not raised: " + ", ".join(extra))
        rows.append(("; ".join(note), key))

    if args.json:
        print(json.dumps({"problems": problems, "functions": [r[1] for r in rows]}, indent=2))
        return 0 if not problems else 1

    if not rows:
        print(style(f"ok   {len(visible)} raising function(s), docstrings agree", "green"))
        return 0
    print(style(f"fail {problems} function(s) whose docstrings do not match", "red"))
    print()
    print(table(["problem", "function"], rows))
    return 1


def _observe(args: argparse.Namespace) -> int:
    from raisemap.observe import Unsupported, observe
    from raisemap.report import style, table

    paths = _paths(args)
    functions = _analyze(args)
    # posix=False on Windows: the default treats a backslash as an escape, so
    # --command "C:\\Python\\python.exe -m pytest" would lose its separators.
    command = (
        shlex.split(args.run, posix=os.name != "nt")
        if args.run
        else [sys.executable, "-m", "pytest", "-q"]
    )

    try:
        seen = observe(command, roots=paths, timeout=args.timeout)
    except Unsupported as error:
        print(f"raisemap: {error}", file=sys.stderr)
        return 2

    if not seen.by_function and seen.returncode not in (0, 1):
        print("raisemap: the command did not produce any observations. It said:", file=sys.stderr)
        print(seen.stderr, file=sys.stderr)
        return 2

    rows = []
    for key, function in sorted(functions.items()):
        observed = seen.for_qualname(str(Path(function.path).resolve()), function.qualname)
        if not observed:
            continue
        inferred = function.raises.names()
        missed = sorted(observed - {n.split(".")[-1] for n in inferred})
        if missed:
            rows.append((", ".join(missed), key))

    if args.json:
        print(json.dumps({"blind_spots": {r[1]: r[0].split(", ") for r in rows}}, indent=2))
        return 0

    print(f"observed {len(seen.by_function)} function(s) raising during the run")
    if not rows:
        print(style("\nthe static pass already knew about all of them", "green"))
        return 0
    print(style(f"\n{len(rows)} function(s) raised something the static pass missed", "yellow"))
    print()
    print(table(["seen but not inferred", "function"], rows))
    return 0


def _check(args: argparse.Namespace) -> int:
    from raisemap import lock as lockfile
    from raisemap.config import load
    from raisemap.report import style, table

    config = load(args.config)
    functions = _analyze(args)
    current = lockfile.build(functions)
    lock = lockfile.Lock(functions=current, public=lockfile.lockable_keys(functions))
    locked = lockfile.read(config.lock)

    if args.update:
        lockfile.write(config.lock, lock)
        print(f"wrote {config.lock} with {len(current)} raising public function(s)")
        return 0

    if not locked.functions and not locked.public:
        print(
            f"raisemap: no lock at {config.lock}. Run 'raisemap check --update' to record "
            f"what the public API raises today.",
            file=sys.stderr,
        )
        return 2

    drifts = lockfile.compare(locked.functions, current)
    added = lockfile.newly_raising(locked, current)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not drifts and not added,
                    "changed": [
                        {"function": d.key, "added": d.added, "removed": d.removed} for d in drifts
                    ],
                    "newly_raising": added,
                },
                indent=2,
            )
        )
        return 0 if not drifts and not added else 1

    if not drifts and not added:
        print(style(f"ok   {len(current)} public function(s), none changed", "green"))
        return 0

    print(style(f"fail {len(drifts) + len(added)} change(s) to what the public API raises", "red"))
    print()
    rows = []
    for drift in drifts:
        if drift.added:
            rows.append(("now raises", ", ".join(drift.added), drift.key))
        if drift.removed:
            rows.append(("no longer raises", ", ".join(drift.removed), drift.key))
    for key in added:
        rows.append(("newly raising", ", ".join(current[key]), key))
    print(table(["change", "exceptions", "function"], rows))
    print()
    print("Adding an exception to a public function breaks anyone catching around it.")
    print("Run 'raisemap check --update' if this is intended.")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
