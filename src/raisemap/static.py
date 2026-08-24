"""Read the source and work out what each function can raise.

Three sources feed the set: a `raise` statement in the body, a call to something
in the same project that raises, and a call to a standard library function that
is documented to raise on bad input.

Everything is filtered through what the function itself catches. A function whose
body is wrapped in `except OSError: return None` does not raise OSError, and
reporting that it does would make the tool noise.

What is deliberately not inferred: the implicit exceptions any expression can
produce. AttributeError from an attribute access, TypeError from arithmetic,
KeyError from a subscript. Model those and every function raises everything.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from raisemap.docstrings import declared_exceptions
from raisemap.hierarchy import BUILTIN_ONLY, Hierarchy
from raisemap.known import known_exceptions
from raisemap.models import DIRECT, KNOWN, PROPAGATED, RERAISE, Function, Source

#: Hard ceiling on propagation passes, as a guard against a bug rather than a
#: tuning knob. One pass moves an exception at least one edge along the call
#: graph, so a chain of N functions needs at most N passes; the real bound is
#: computed from the function count and this only caps pathological input.
MAX_PASSES = 1000


@dataclass
class CallSite:
    """A call, and what the caller catches around it."""

    name: str
    line: int
    caught: frozenset[str] = frozenset()


@dataclass
class Module:
    name: str
    path: str
    functions: dict[str, Function] = field(default_factory=dict)
    call_sites: dict[str, list[CallSite]] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    #: Exception classes defined here, mapped to the bases they were given.
    exception_classes: dict[str, list[str]] = field(default_factory=dict)


def analyze_source(
    source: str,
    path: str | Path,
    module: str,
    hierarchy: Hierarchy | None = None,
) -> Module:
    """Analyze one module's source.

    ``hierarchy`` decides which handlers suppress which exceptions. Pass one
    built from the whole project to get project-defined exception classes right;
    without it only the builtin tree is known.
    """
    tree = ast.parse(source, filename=str(path))
    visitor = _Visitor(module=module, path=str(path), hierarchy=hierarchy or BUILTIN_ONLY)
    visitor.visit(tree)
    return Module(
        name=module,
        path=str(path),
        functions=visitor.functions,
        call_sites=visitor.call_sites,
        imports=visitor.imports,
        exception_classes=visitor.exception_classes,
    )


def analyze_file(
    path: Path, module: str | None = None, hierarchy: Hierarchy | None = None
) -> Module:
    return analyze_source(
        path.read_text(encoding="utf-8"), path, module or module_name(path), hierarchy
    )


def collect_hierarchy(modules: list[Module]) -> Hierarchy:
    """Build the project's exception ancestry from every class it defines."""
    project: dict[str, list[str]] = {}
    for module in modules:
        project.update(module.exception_classes)
    return Hierarchy(project)


def module_name(path: Path) -> str:
    """Dotted name for a file, by walking up through __init__.py files."""
    resolved = path.resolve()
    parts = [resolved.stem] if resolved.stem != "__init__" else []
    directory = resolved.parent
    while (directory / "__init__.py").is_file():
        parts.insert(0, directory.name)
        directory = directory.parent
    return ".".join(parts) or resolved.stem


def propagate(modules: list[Module], hierarchy: Hierarchy | None = None) -> dict[str, Function]:
    """Push exceptions along the call graph until nothing changes.

    Iterated to a fixed point rather than recursed, because two functions calling
    each other would otherwise need cycle detection, and a fixed point handles
    that for free.
    """
    tree = hierarchy or collect_hierarchy(modules)
    functions: dict[str, Function] = {}
    sites: dict[str, list[CallSite]] = {}
    for module in modules:
        functions.update(module.functions)
        sites.update(module.call_sites)

    # Short name -> full key, so a call written as `helper()` can be resolved
    # against a function defined as `pkg.mod.helper`.
    by_short: dict[str, list[str]] = {}
    for key, function in functions.items():
        by_short.setdefault(function.qualname.split(".")[-1], []).append(key)

    passes = min(MAX_PASSES, len(functions) + 1)
    for _ in range(passes):
        changed = False
        for key, function in functions.items():
            for site in sites.get(key, []):
                for target in _resolve(site.name, by_short, functions):
                    if target == key:
                        continue  # direct recursion adds nothing
                    for name, _sources in functions[target].raises.exceptions.items():
                        if any(tree.catches(handler, name) for handler in site.caught):
                            continue
                        before = len(function.raises.exceptions.get(name, []))
                        function.raises.add(
                            name,
                            Source(PROPAGATED, site.line, functions[target].qualname),
                        )
                        if len(function.raises.exceptions[name]) != before:
                            changed = True
        if not changed:
            break
    return functions


def _resolve(
    name: str, by_short: dict[str, list[str]], functions: dict[str, Function]
) -> list[str]:
    """Find project functions a call might refer to.

    Resolution is by name, not by import graph. A call to `helper()` matches
    every project function called `helper`, which over-reports when a name is
    reused. That is the safer direction: a missed propagation hides a real
    exception, an extra one is visible and can be argued with.
    """
    if name in functions:
        return [name]
    tail = name.split(".")[-1]
    return by_short.get(tail, [])


class _Visitor(ast.NodeVisitor):
    """Walks a module, building one Function per def and recording its calls."""

    def __init__(self, module: str, path: str, hierarchy: Hierarchy) -> None:
        self.module = module
        self.path = path
        self.hierarchy = hierarchy
        self.functions: dict[str, Function] = {}
        self.call_sites: dict[str, list[CallSite]] = {}
        self.imports: dict[str, str] = {}
        self.exception_classes: dict[str, list[str]] = {}
        #: What the enclosing `except` caught, for resolving a bare `raise`.
        self._reraise: frozenset[str] = frozenset()
        self._scope: list[str] = []
        self._caught: list[frozenset[str]] = []
        self._current: Function | None = None

    # --- imports, so dotted calls can be recognised ---------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name.split(".")[0]] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name] = f"{node.module or ''}.{alias.name}"

    # --- definitions ----------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [n for n in (_exception_name(b) for b in node.bases) if n]
        if bases:
            # Recorded for every class, not just ones that look like exceptions.
            # Deciding by name would miss `class Problem(ValueError)`.
            self.exception_classes[node.name] = bases
        self._scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._scope.append(node.name)
        qualname = ".".join(self._scope)
        docstring = ast.get_docstring(node)
        function = Function(
            qualname=qualname,
            module=self.module,
            path=self.path,
            line=node.lineno,
            declared=declared_exceptions(docstring or ""),
            has_docstring=bool(docstring),
            is_public=not any(part.startswith("_") for part in qualname.split(".")),
        )
        self.functions[function.key] = function
        self.call_sites[function.key] = []

        previous, self._current = self._current, function
        previous_caught, self._caught = self._caught, []
        for child in node.body:
            self.visit(child)
        # A nested def is its own function; its raises do not belong to the parent
        # unless the parent calls it, which the call graph handles.
        self._current, self._caught = previous, previous_caught
        self._scope.pop()

    # --- statements that matter ----------------------------------------------

    def visit_Try(self, node: ast.Try) -> None:
        handled = frozenset(name for handler in node.handlers for name in _handler_names(handler))
        self._caught.append(handled)
        for child in [*node.body, *node.orelse]:
            self.visit(child)
        self._caught.pop()

        # A raise inside an except block is not caught by that same try.
        for handler in node.handlers:
            self._in_handler(handler)
        for child in node.finalbody:
            self.visit(child)

    def visit_TryStar(self, node: ast.Try) -> None:
        """`except*` groups, on 3.11+. The suppression rules are the same here."""
        self.visit_Try(node)

    def _in_handler(self, handler: ast.ExceptHandler) -> None:
        previous: frozenset[str] = self._reraise
        self._reraise = frozenset(_handler_names(handler))
        for child in handler.body:
            self.visit(child)
        self._reraise = previous

    def visit_Raise(self, node: ast.Raise) -> None:
        if self._current is None:
            return
        if node.exc is None:
            # A bare `raise` re-raises whatever the handler caught.
            for name in self._reraise:
                if not self._is_caught(name):
                    self._current.raises.add(name, Source(RERAISE, node.lineno))
            return
        raised = _exception_name(node.exc)
        if raised and not self._is_caught(raised):
            self._current.raises.add(raised, Source(DIRECT, node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        if self._current is not None:
            name = _call_name(node.func)
            if name:
                self.call_sites[self._current.key].append(
                    CallSite(
                        name=name,
                        line=node.lineno,
                        caught=frozenset().union(*self._caught) if self._caught else frozenset(),
                    )
                )
                for raised in known_exceptions(name, node):
                    if not self._is_caught(raised):
                        self._current.raises.add(raised, Source(KNOWN, node.lineno, f"{name}()"))
        self.generic_visit(node)

    def _is_caught(self, name: str) -> bool:
        return any(
            self.hierarchy.catches(handler, name)
            for handlers in self._caught
            for handler in handlers
        )


def _handler_names(handler: ast.ExceptHandler) -> list[str]:
    if handler.type is None:
        return ["BaseException"]  # a bare except catches everything
    if isinstance(handler.type, ast.Tuple):
        return [n for n in (_exception_name(e) for e in handler.type.elts) if n]
    name = _exception_name(handler.type)
    return [name] if name else []


def _exception_name(node: ast.expr) -> str | None:
    """The name of the exception in `raise X`, `raise X(...)` or `except X`."""
    if isinstance(node, ast.Call):
        return _exception_name(node.func)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def _call_name(node: ast.expr) -> str | None:
    """Dotted name of whatever is being called, where it can be worked out."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None
