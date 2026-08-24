# raisemap

Work out which exceptions a Python function can actually raise.

[![PyPI](https://img.shields.io/pypi/v/raisemap.svg)](https://pypi.org/project/raisemap/)
[![Python](https://img.shields.io/pypi/pyversions/raisemap.svg)](https://pypi.org/project/raisemap/)
[![CI](https://github.com/aviseth/raisemap/actions/workflows/ci.yml/badge.svg)](https://github.com/aviseth/raisemap/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Python has no way to declare what a function raises and no way to check it. The answer lives in
docstrings that drift out of date, or in nobody's head at all, and adding an exception to a public
function is a breaking change that nothing will tell you about.

raisemap infers the set from the source, checks it against a running program, compares it with
what the docstrings claim, and fails CI when the public API's exceptions change.

## Installation

```shell
pip install raisemap
```

Requires Python 3.10+. The `observe` command needs 3.12+ for `sys.monitoring`.

## Quick start

```shell
raisemap show src
```

```text
raises                              function
----------------------------------  --------------------
ConfigError, TypeError, ValueError  mypkg.core.load_config
TypeError, ValueError               mypkg.core.parse_port
OSError, json.JSONDecodeError       mypkg.io.read
```

`--why` shows where each one comes from, which is usually the actual question:

```text
$ raisemap show src --function read --why
mypkg.io.read  src/mypkg/io.py:14
  OSError
      known to raise at line 15 (open())
  json.JSONDecodeError
      known to raise at line 16 (json.load())
```

## Where the answers come from

| Source | Example |
| --- | --- |
| A `raise` in the body | `raise ValueError("bad port")` |
| A bare `raise` in a handler | `except OSError: raise` |
| A call to another function in the project | inferred, then pushed along the call graph |
| A curated table of stdlib calls | `int()`, `open()`, `json.loads()`, `subprocess.run()` |

Everything is filtered through what the function catches. A body wrapped in
`except OSError: return None` does not raise OSError, and saying it does would make the report
noise.

Suppression understands the class hierarchy, including your own exception classes. If you define
`class ConfigError(ValueError)` then `except ValueError` suppresses it, and raisemap reads that
relationship out of your source rather than importing your package to find it.

### What is deliberately not inferred

The implicit exceptions any expression can produce: `AttributeError` from an attribute access,
`TypeError` from arithmetic, `KeyError` from a subscript. Model those and every function in the
codebase raises everything, and the output stops being worth reading.

The rule for the stdlib table is that the exception is part of the callee's contract and a caller
is expected to handle it. `int("x")` raising ValueError is a contract. `x.y` raising
AttributeError is a bug.

Argument-dependent contracts are handled: `getattr(x, "y")` raises AttributeError,
`getattr(x, "y", None)` cannot, and the second one is far more common.

## Checking the docstrings

```shell
raisemap docs src
```

```text
fail 3 function(s) whose docstrings do not match

problem                                     function
------------------------------------------  --------------------
undocumented: ValueError                    mypkg.core.load_config
documented but not raised: KeyError         mypkg.io.read
no docstring; undocumented: OSError         mypkg.io.write
```

Google, NumPy and Sphinx conventions are all parsed, so nobody has to reformat a codebase to use
this:

```python
"""Raises:
ValueError: if the input is empty
"""

"""Raises
------
ValueError
    if the input is empty
"""

""":raises ValueError: if the input is empty"""
```

## Checking against a running program

```shell
raisemap observe src -- pytest -q
```

```text
observed 41 function(s) raising during the run

1 function(s) raised something the static pass missed

seen but not inferred  function
---------------------  -----------------
KeyError               mypkg.core.lookup
```

Static analysis reads what is written. It cannot see an exception from a C extension, from a call
it could not resolve, or through dynamic dispatch. Running the suite can. The two disagreeing is
the interesting part:

- **observed but not inferred** means the static pass has a blind spot, and the function raises
  something nobody has written down.
- **inferred but not observed** means either a path the tests never take, or an over-eager
  inference.

This uses `sys.monitoring`'s `PY_UNWIND` event, which fires exactly when an exception leaves a
Python function. Below 3.12 the pass is skipped rather than approximated with a tracer that would
change the timing of everything it measures.

## Guarding the public API in CI

```shell
raisemap check --update   # record what the public API raises today
git add raisemap.lock
```

```toml
[tool.raisemap]
paths = ["src"]
lock = "raisemap.lock"
ignore = ["NotImplementedError"]
```

```text
$ raisemap check
fail 2 change(s) to what the public API raises

change      exceptions   function
----------  -----------  --------------------
now raises  LookupError  mypkg.core.load_config
now raises  LookupError  mypkg.core.safe_load

Adding an exception to a public function breaks anyone catching around it.
Run 'raisemap check --update' if this is intended.
```

Only public functions are locked. A private helper gaining an exception is not somebody else's
problem. Functions that are new or deleted are not reported as drift, since one has no previous
behaviour and the other is a separate conversation.

## Configuration

Keys under `[tool.raisemap]` in `pyproject.toml`. All optional.

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `paths` | list of strings | `[]` | Where to look when no paths are given on the command line |
| `lock` | string | `"raisemap.lock"` | Path to the lock file |
| `require_docstrings` | bool | `false` | Fail `docs` when a raising function has no docstring |
| `ignore` | list of strings | `[]` | Exception names to leave out of `docs` reports |

## Command reference

| Command | What it does |
| --- | --- |
| `raisemap show [paths]` | List what each function raises, `--why` for provenance |
| `raisemap show --function NAME` | Just one function, by dotted or short name |
| `raisemap docs [paths]` | Compare docstrings against what is inferred |
| `raisemap observe [paths] --command "..."` | Run something and reconcile with the static pass |
| `raisemap check` | Fail when the public API's exceptions change, `--update` to record |

Every command takes `--json`, and `show`/`docs` take `--all` to include private functions.

## How it compares

| Tool | Infers the set | Follows calls | Understands your exception classes | Checks docstrings | Runtime check | CI guard |
| --- | --- | --- | --- | --- | --- | --- |
| `tryceratops` | no | no | no | no | no | no |
| `flake8-raise` | no | no | no | no | no | no |
| `darglint` | no | no | no | yes | no | no |
| raisemap | yes | yes | yes | yes | yes | yes |

`tryceratops` last released in 2024 and `flake8-raise` in 2020; both lint how you write `raise`
and `try` rather than working out what escapes.

## Notes

Calls are resolved by name, not by following imports. A call to `helper()` matches every project
function called `helper`, which over-reports when a name is reused across modules. That is the
safer direction: a missed propagation hides a real exception, an extra one is visible and can be
argued with.

Propagation is iterated to a fixed point rather than recursed, so mutual recursion converges
instead of needing cycle detection.

Nothing here imports the code being analysed. A tool that has to import your package to describe
it is a tool that runs your import side effects.

A file that does not parse is skipped rather than aborting the run.

## Contributing

Bug reports and pull requests are welcome, especially additions to the stdlib table in
`src/raisemap/known.py`. The bar for an entry is that the exception is part of the callee's
documented contract. `uv sync` then `uv run pytest` to get started.

## License

MIT.
