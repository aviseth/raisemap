"""Pull the declared exceptions out of a docstring.

Three conventions are in wide use and none of them agree, so all three are
parsed rather than making anyone reformat their codebase:

Google::

    Raises:
        ValueError: if the input is empty
        OSError: if the file is missing

NumPy::

    Raises
    ------
    ValueError
        if the input is empty

Sphinx::

    :raises ValueError: if the input is empty
    :raise OSError: if the file is missing
"""

from __future__ import annotations

import re

_SPHINX = re.compile(r"^\s*:raises?\s+([A-Za-z_][\w.]*)\s*:", re.MULTILINE)
_GOOGLE_HEADER = re.compile(r"^\s*(Raises|Raise)\s*:\s*$", re.MULTILINE)
_NUMPY_HEADER = re.compile(r"^\s*Raises\s*\n\s*-{3,}\s*$", re.MULTILINE)
_ENTRY = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(?::|$)")
#: A line starting another Google-style section ends the Raises block.
_SECTION = re.compile(
    r"^\s*(Args|Arguments|Returns|Yields|Raises|Note|Notes|Example|Examples|Attributes)\s*:\s*$"
)


def declared_exceptions(docstring: str) -> set[str]:
    """Every exception a docstring says the function raises."""
    if not docstring:
        return set()
    found = set(_SPHINX.findall(docstring))
    found |= _block(docstring, _GOOGLE_HEADER)
    found |= _block(docstring, _NUMPY_HEADER, skip=1)
    return found


def _block(docstring: str, header: re.Pattern[str], skip: int = 0) -> set[str]:
    """Names listed under a section header, until the block ends."""
    match = header.search(docstring)
    if match is None:
        return set()
    lines = docstring[match.end() :].splitlines()[skip:]
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    if not indents:
        return set()
    base = indents[0]

    found: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent < base or _SECTION.match(line):
            break
        if indent > base:
            continue  # continuation of the previous entry's description
        entry = _ENTRY.match(line)
        if entry:
            found.add(entry.group(1))
    return found
