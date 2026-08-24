"""What an inferred exception set looks like, and where each entry came from.

A bare list of exception names is not much use on its own. "This raises OSError"
invites the question "from where", and if the answer takes ten minutes to find,
the tool has not saved anyone anything. So every exception carries its provenance
and the line that put it there.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: How an exception came to be part of a function's set.
DIRECT = "raised here"
RERAISE = "re-raised"
PROPAGATED = "propagates from a call"
KNOWN = "known to raise"
OBSERVED = "seen at runtime"
DECLARED = "declared in the docstring"


@dataclass(frozen=True)
class Source:
    """One reason an exception is in the set."""

    kind: str
    line: int = 0
    detail: str = ""

    def __str__(self) -> str:
        where = f" at line {self.line}" if self.line else ""
        detail = f" ({self.detail})" if self.detail else ""
        return f"{self.kind}{where}{detail}"


@dataclass
class Raises:
    """The exceptions one function can raise, with provenance for each."""

    exceptions: dict[str, list[Source]] = field(default_factory=dict)

    def add(self, name: str, source: Source) -> None:
        sources = self.exceptions.setdefault(name, [])
        if source not in sources:
            sources.append(source)

    def merge(self, other: Raises) -> None:
        for name, sources in other.exceptions.items():
            for source in sources:
                self.add(name, source)

    def names(self) -> set[str]:
        return set(self.exceptions)

    def without(self, caught: set[str]) -> Raises:
        """Drop anything an enclosing handler catches."""
        kept = Raises()
        for name, sources in self.exceptions.items():
            if name not in caught:
                kept.exceptions[name] = list(sources)
        return kept

    def __bool__(self) -> bool:
        return bool(self.exceptions)

    def __len__(self) -> int:
        return len(self.exceptions)


@dataclass
class Function:
    """One function or method, and what it can raise."""

    qualname: str
    module: str
    path: str
    line: int
    raises: Raises = field(default_factory=Raises)
    declared: set[str] = field(default_factory=set)
    has_docstring: bool = False
    is_public: bool = True
    calls: set[str] = field(default_factory=set)

    @property
    def key(self) -> str:
        return f"{self.module}.{self.qualname}"

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"

    def undocumented(self) -> set[str]:
        """Raised, but the docstring does not mention it."""
        return self.raises.names() - self.declared

    def overdocumented(self) -> set[str]:
        """Documented, but nothing suggests it is raised."""
        return self.declared - self.raises.names()
