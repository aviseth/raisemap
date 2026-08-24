"""Which exceptions are subclasses of which, so `except` suppression is accurate.

Without this, a project that defines ``class ConfigError(ValueError)`` and
catches ``ValueError`` gets told it still raises ConfigError, which is wrong and
makes the whole report untrustworthy.

Two sources. The builtin tree below is hard-coded, because it is fixed and small.
Project exception classes are read out of the source: a ``class X(ValueError)``
anywhere in the analysed paths teaches the checker that X is a ValueError.

Nothing here imports the code under analysis. A tool that has to import your
package to tell you about it is a tool that runs your import side effects.
"""

from __future__ import annotations

#: Direct parent of each builtin exception, as far up as Exception.
BUILTIN_PARENTS: dict[str, str] = {
    "Exception": "BaseException",
    "ArithmeticError": "Exception",
    "FloatingPointError": "ArithmeticError",
    "OverflowError": "ArithmeticError",
    "ZeroDivisionError": "ArithmeticError",
    "AssertionError": "Exception",
    "AttributeError": "Exception",
    "BufferError": "Exception",
    "EOFError": "Exception",
    "ImportError": "Exception",
    "ModuleNotFoundError": "ImportError",
    "LookupError": "Exception",
    "IndexError": "LookupError",
    "KeyError": "LookupError",
    "MemoryError": "Exception",
    "NameError": "Exception",
    "UnboundLocalError": "NameError",
    "OSError": "Exception",
    "IOError": "OSError",
    "BlockingIOError": "OSError",
    "ChildProcessError": "OSError",
    "ConnectionError": "OSError",
    "BrokenPipeError": "ConnectionError",
    "ConnectionAbortedError": "ConnectionError",
    "ConnectionRefusedError": "ConnectionError",
    "ConnectionResetError": "ConnectionError",
    "FileExistsError": "OSError",
    "FileNotFoundError": "OSError",
    "InterruptedError": "OSError",
    "IsADirectoryError": "OSError",
    "NotADirectoryError": "OSError",
    "PermissionError": "OSError",
    "ProcessLookupError": "OSError",
    "TimeoutError": "OSError",
    "ReferenceError": "Exception",
    "RuntimeError": "Exception",
    "NotImplementedError": "RuntimeError",
    "RecursionError": "RuntimeError",
    "StopAsyncIteration": "Exception",
    "StopIteration": "Exception",
    "SyntaxError": "Exception",
    "IndentationError": "SyntaxError",
    "TabError": "IndentationError",
    "SystemError": "Exception",
    "TypeError": "Exception",
    "ValueError": "Exception",
    "UnicodeError": "ValueError",
    "UnicodeDecodeError": "UnicodeError",
    "UnicodeEncodeError": "UnicodeError",
    "UnicodeTranslateError": "UnicodeError",
    "Warning": "Exception",
    "GeneratorExit": "BaseException",
    "KeyboardInterrupt": "BaseException",
    "SystemExit": "BaseException",
    # Common stdlib exceptions people catch by their parent.
    "json.JSONDecodeError": "ValueError",
    "tomllib.TOMLDecodeError": "ValueError",
    "re.error": "Exception",
    "struct.error": "Exception",
    "binascii.Error": "ValueError",
    "subprocess.SubprocessError": "Exception",
    "subprocess.CalledProcessError": "subprocess.SubprocessError",
    "subprocess.TimeoutExpired": "subprocess.SubprocessError",
    "pickle.UnpicklingError": "Exception",
    "urllib.error.URLError": "OSError",
    "decimal.InvalidOperation": "Exception",
}


class Hierarchy:
    """Ancestry lookup for exception names, builtin plus whatever the project defines."""

    def __init__(self, project: dict[str, list[str]] | None = None) -> None:
        self.project = project or {}

    def ancestors(self, name: str) -> set[str]:
        """Every name ``name`` is a subclass of, including itself."""
        seen: set[str] = set()
        pending = [name]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(self.project.get(current, []))
            # A dotted name may also be known by its last segment, since a
            # project can catch `JSONDecodeError` after importing it directly.
            short = current.split(".")[-1]
            parent = BUILTIN_PARENTS.get(current) or BUILTIN_PARENTS.get(short)
            if parent:
                pending.append(parent)
        return seen

    def catches(self, handler: str, raised: str) -> bool:
        """Would ``except handler`` catch ``raised``?"""
        if handler == "BaseException":
            return True
        ancestry = self.ancestors(raised)
        return handler in ancestry or handler.split(".")[-1] in {a.split(".")[-1] for a in ancestry}


#: Used when no project classes have been collected.
BUILTIN_ONLY = Hierarchy()
