"""A curated table of standard library calls that raise on their inputs.

Deliberately small. The temptation is to model every implicit exception the
interpreter can produce: a subscript raises KeyError or IndexError, an attribute
access raises AttributeError, arithmetic raises TypeError and ZeroDivisionError.
Follow that through and every function in the codebase raises everything, and the
output stops being worth reading.

So the rule for being in this table is that the exception is part of the callee's
documented contract, and a caller is expected to handle it. `int("x")` raising
ValueError is a contract. `x.y` raising AttributeError is a bug.
"""

from __future__ import annotations

import ast

#: Dotted call name -> exceptions it is documented to raise on bad input.
KNOWN_RAISERS: dict[str, tuple[str, ...]] = {
    # builtins
    "int": ("ValueError", "TypeError"),
    "float": ("ValueError", "TypeError"),
    "complex": ("ValueError", "TypeError"),
    "open": ("OSError",),
    "next": ("StopIteration",),
    "getattr": ("AttributeError",),
    # json
    "json.load": ("json.JSONDecodeError",),
    "json.loads": ("json.JSONDecodeError",),
    "json.dump": ("TypeError",),
    "json.dumps": ("TypeError",),
    # os and pathlib
    "os.remove": ("OSError",),
    "os.unlink": ("OSError",),
    "os.rename": ("OSError",),
    "os.mkdir": ("OSError",),
    "os.makedirs": ("OSError",),
    "os.rmdir": ("OSError",),
    "os.listdir": ("OSError",),
    "os.stat": ("OSError",),
    "shutil.copy": ("OSError",),
    "shutil.move": ("OSError",),
    "shutil.rmtree": ("OSError",),
    "Path.read_text": ("OSError",),
    "Path.read_bytes": ("OSError",),
    "Path.write_text": ("OSError",),
    "Path.write_bytes": ("OSError",),
    "Path.mkdir": ("OSError",),
    "Path.unlink": ("OSError",),
    "Path.rename": ("OSError",),
    "Path.resolve": ("OSError",),
    # subprocess
    "subprocess.run": ("subprocess.SubprocessError", "OSError"),
    "subprocess.check_output": ("subprocess.CalledProcessError", "OSError"),
    "subprocess.check_call": ("subprocess.CalledProcessError", "OSError"),
    "subprocess.Popen": ("OSError",),
    # text and data
    "re.compile": ("re.error",),
    "struct.pack": ("struct.error",),
    "struct.unpack": ("struct.error",),
    "base64.b64decode": ("binascii.Error",),
    "datetime.strptime": ("ValueError",),
    "date.fromisoformat": ("ValueError",),
    "datetime.fromisoformat": ("ValueError",),
    "uuid.UUID": ("ValueError",),
    "decimal.Decimal": ("decimal.InvalidOperation",),
    # config and serialisation
    "tomllib.load": ("tomllib.TOMLDecodeError",),
    "tomllib.loads": ("tomllib.TOMLDecodeError",),
    "pickle.load": ("pickle.UnpicklingError",),
    "pickle.loads": ("pickle.UnpicklingError",),
    # network
    "socket.create_connection": ("OSError",),
    "urllib.request.urlopen": ("urllib.error.URLError",),
}


def known_exceptions(name: str, node: ast.AST | None = None) -> tuple[str, ...]:
    """What a call to ``name`` is documented to raise, given how it was called.

    The node is used for the handful of calls whose contract depends on their
    arguments. ``getattr(x, "y")`` raises AttributeError; ``getattr(x, "y", None)``
    cannot, and reporting it would be a false positive in very common code.
    """
    if name == "getattr" and isinstance(node, ast.Call) and len(node.args) >= 3:
        return ()
    if name == "next" and isinstance(node, ast.Call) and len(node.args) >= 2:
        return ()
    return KNOWN_RAISERS.get(name, ())
