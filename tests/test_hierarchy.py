from raisemap.hierarchy import BUILTIN_ONLY, Hierarchy


def test_an_exception_is_its_own_ancestor():
    assert "ValueError" in BUILTIN_ONLY.ancestors("ValueError")


def test_builtin_ancestry():
    assert "Exception" in BUILTIN_ONLY.ancestors("FileNotFoundError")
    assert "OSError" in BUILTIN_ONLY.ancestors("FileNotFoundError")
    assert "BaseException" in BUILTIN_ONLY.ancestors("FileNotFoundError")


def test_except_exception_catches_ordinary_errors():
    assert BUILTIN_ONLY.catches("Exception", "ValueError")
    assert BUILTIN_ONLY.catches("OSError", "PermissionError")


def test_except_exception_does_not_catch_keyboard_interrupt():
    assert not BUILTIN_ONLY.catches("Exception", "KeyboardInterrupt")
    assert not BUILTIN_ONLY.catches("Exception", "SystemExit")


def test_a_bare_except_catches_everything():
    assert BUILTIN_ONLY.catches("BaseException", "KeyboardInterrupt")
    assert BUILTIN_ONLY.catches("BaseException", "ValueError")


def test_siblings_do_not_catch_each_other():
    assert not BUILTIN_ONLY.catches("KeyError", "IndexError")
    assert not BUILTIN_ONLY.catches("ValueError", "TypeError")


def test_a_project_exception_inherits_from_its_base():
    tree = Hierarchy({"ConfigError": ["ValueError"]})
    assert tree.catches("ValueError", "ConfigError")
    assert tree.catches("Exception", "ConfigError")
    assert not tree.catches("TypeError", "ConfigError")


def test_a_chain_of_project_exceptions():
    tree = Hierarchy({"Base": ["Exception"], "Middle": ["Base"], "Leaf": ["Middle"]})
    assert tree.catches("Base", "Leaf")
    assert tree.catches("Exception", "Leaf")
    assert not tree.catches("Leaf", "Base")


def test_stdlib_exceptions_that_people_catch_by_their_parent():
    assert BUILTIN_ONLY.catches("ValueError", "json.JSONDecodeError")
    assert BUILTIN_ONLY.catches("OSError", "urllib.error.URLError")
    assert BUILTIN_ONLY.catches("subprocess.SubprocessError", "subprocess.CalledProcessError")


def test_a_dotted_name_matches_its_short_form():
    """Code that imports JSONDecodeError directly still catches it."""
    assert BUILTIN_ONLY.catches("JSONDecodeError", "json.JSONDecodeError")


def test_multiple_inheritance_is_followed():
    tree = Hierarchy({"Weird": ["ValueError", "OSError"]})
    assert tree.catches("ValueError", "Weird")
    assert tree.catches("OSError", "Weird")


def test_a_cycle_does_not_hang():
    tree = Hierarchy({"A": ["B"], "B": ["A"]})
    assert tree.ancestors("A") >= {"A", "B"}


def test_an_unknown_exception_is_only_itself():
    assert BUILTIN_ONLY.ancestors("SomeThirdPartyError") == {"SomeThirdPartyError"}


def test_ioerror_is_the_same_class_as_oserror_not_a_subclass():
    """At runtime they are one object, so `except IOError` does catch an OSError."""
    assert BUILTIN_ONLY.catches("IOError", "OSError")
    assert BUILTIN_ONLY.catches("OSError", "IOError")
    assert BUILTIN_ONLY.catches("EnvironmentError", "OSError")


def test_a_dotted_handler_does_not_match_an_unrelated_tail():
    """`except re.error` must not swallow a raised struct.error."""
    assert not BUILTIN_ONLY.catches("re.error", "struct.error")
    assert not BUILTIN_ONLY.catches("binascii.Error", "pkg.Error")


def test_an_undotted_handler_still_matches_a_dotted_ancestor():
    """A name imported directly is written undotted, and does catch."""
    assert BUILTIN_ONLY.catches("JSONDecodeError", "json.JSONDecodeError")
