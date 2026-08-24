# Changelog

## 0.1.0

First release.

- `raisemap show` infers the exception set for every function from `raise` statements, bare
  re-raises, calls to other project functions pushed along the call graph, and a curated table of
  standard library calls. `--why` gives the provenance of each entry.
- Suppression understands the exception class hierarchy, including project-defined classes read
  out of the source, so `except ValueError` correctly suppresses your own `ValueError` subclass.
- Argument-dependent contracts are handled: `getattr(x, "y", None)` cannot raise AttributeError
  and is not reported as if it could.
- `raisemap docs` compares the inferred set against Google, NumPy and Sphinx style `Raises:`
  sections.
- `raisemap observe` runs a command under `sys.monitoring` and reports what escaped a function
  that the static pass did not predict.
- `raisemap check` locks what the public API raises and fails when it changes.
- Implicit exceptions from ordinary expressions are deliberately not inferred, and nothing is
  imported from the code under analysis.
