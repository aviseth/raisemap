"""Work out which exceptions a function can actually raise.

Python has no way to declare this and no way to check it, so the answer lives in
docstrings that drift, or in nobody's head at all. The public surface here is the
``raisemap`` command; nothing is imported at module scope.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
