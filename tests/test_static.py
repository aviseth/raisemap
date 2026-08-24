from raisemap.static import analyze_source, collect_hierarchy, propagate


def analyze(source: str, module: str = "demo"):
    m = analyze_source(source, f"{module}.py", module)
    return propagate([m])


def raises(source: str, key: str) -> set[str]:
    return analyze(source)[key].raises.names()


def test_a_direct_raise():
    assert raises("def f():\n    raise ValueError('no')\n", "demo.f") == {"ValueError"}


def test_a_raise_without_a_call():
    assert raises("def f():\n    raise ValueError\n", "demo.f") == {"ValueError"}


def test_a_dotted_exception():
    source = "import json\n\n\ndef f():\n    raise json.JSONDecodeError('a', 'b', 0)\n"
    assert raises(source, "demo.f") == {"json.JSONDecodeError"}


def test_an_exception_the_function_catches_is_not_raised():
    source = (
        "def f():\n    try:\n        raise ValueError('no')\n"
        "    except ValueError:\n        return None\n"
    )
    assert raises(source, "demo.f") == set()


def test_a_handler_for_a_parent_class_still_suppresses():
    source = (
        "def f():\n    try:\n        raise FileNotFoundError('no')\n"
        "    except OSError:\n        return None\n"
    )
    assert raises(source, "demo.f") == set()


def test_a_handler_for_a_sibling_does_not_suppress():
    source = (
        "def f():\n    try:\n        raise KeyError('no')\n"
        "    except IndexError:\n        return None\n"
    )
    assert raises(source, "demo.f") == {"KeyError"}


def test_a_raise_inside_the_handler_is_not_caught_by_its_own_try():
    source = (
        "def f():\n    try:\n        pass\n"
        "    except ValueError:\n        raise RuntimeError('boom')\n"
    )
    assert raises(source, "demo.f") == {"RuntimeError"}


def test_a_bare_raise_re_raises_what_was_caught():
    source = "def f():\n    try:\n        pass\n    except (OSError, ValueError):\n        raise\n"
    assert raises(source, "demo.f") == {"OSError", "ValueError"}


def test_a_tuple_handler_catches_all_of_its_members():
    source = (
        "def f():\n    try:\n        raise KeyError('a')\n"
        "    except (KeyError, IndexError):\n        return None\n"
    )
    assert raises(source, "demo.f") == set()


def test_a_bare_except_catches_everything():
    source = "def f():\n    try:\n        raise SystemExit(1)\n    except:\n        pass\n"
    assert raises(source, "demo.f") == set()


def test_except_exception_does_not_catch_keyboard_interrupt():
    source = (
        "def f():\n    try:\n        raise KeyboardInterrupt()\n"
        "    except Exception:\n        pass\n"
    )
    assert raises(source, "demo.f") == {"KeyboardInterrupt"}


def test_a_known_stdlib_raiser():
    assert raises("def f(x):\n    return int(x)\n", "demo.f") == {"ValueError", "TypeError"}


def test_getattr_with_a_default_cannot_raise():
    """The two-argument form raises AttributeError; the three-argument form cannot."""
    assert raises("def f(x):\n    return getattr(x, 'y')\n", "demo.f") == {"AttributeError"}
    assert raises("def f(x):\n    return getattr(x, 'y', None)\n", "demo.f") == set()


def test_next_with_a_default_cannot_raise():
    assert raises("def f(it):\n    return next(it)\n", "demo.f") == {"StopIteration"}
    assert raises("def f(it):\n    return next(it, None)\n", "demo.f") == set()


def test_exceptions_propagate_along_a_call():
    source = "def inner():\n    raise ValueError('no')\n\n\ndef outer():\n    return inner()\n"
    assert raises(source, "demo.outer") == {"ValueError"}


def test_propagation_is_transitive():
    source = (
        "def a():\n    raise ValueError('no')\n\n\n"
        "def b():\n    return a()\n\n\n"
        "def c():\n    return b()\n"
    )
    assert raises(source, "demo.c") == {"ValueError"}


def test_a_caller_that_catches_stops_the_propagation():
    source = (
        "def inner():\n    raise ValueError('no')\n\n\n"
        "def outer():\n    try:\n        return inner()\n"
        "    except ValueError:\n        return None\n"
    )
    assert raises(source, "demo.outer") == set()


def test_mutual_recursion_terminates():
    source = (
        "def a(n):\n    if n:\n        return b(n - 1)\n    raise ValueError('done')\n\n\n"
        "def b(n):\n    return a(n)\n"
    )
    functions = analyze(source)
    assert functions["demo.a"].raises.names() == {"ValueError"}
    assert functions["demo.b"].raises.names() == {"ValueError"}


def test_a_project_exception_class_is_understood_as_its_base():
    source = (
        "class ConfigError(ValueError):\n    pass\n\n\n"
        "def inner():\n    raise ConfigError('no')\n\n\n"
        "def outer():\n    try:\n        return inner()\n"
        "    except ValueError:\n        return None\n"
    )
    assert raises(source, "demo.outer") == set()


def test_the_hierarchy_is_collected_from_class_definitions():
    m = analyze_source("class Bad(ValueError):\n    pass\n", "demo.py", "demo")
    assert collect_hierarchy([m]).catches("ValueError", "Bad")


def test_methods_are_keyed_by_their_qualified_name():
    source = "class C:\n    def method(self):\n        raise ValueError('no')\n"
    functions = analyze(source)
    assert "demo.C.method" in functions


def test_a_private_function_is_marked_private():
    functions = analyze("def _hidden():\n    raise ValueError('no')\n")
    assert not functions["demo._hidden"].is_public


def test_a_method_on_a_private_class_is_private():
    source = "class _Internal:\n    def method(self):\n        raise ValueError('no')\n"
    assert not analyze(source)["demo._Internal.method"].is_public


def test_async_functions_are_analysed():
    assert raises("async def f():\n    raise ValueError('no')\n", "demo.f") == {"ValueError"}


def test_a_nested_function_is_its_own_entry():
    source = "def outer():\n    def inner():\n        raise ValueError('no')\n    return inner\n"
    functions = analyze(source)
    assert functions["demo.outer.inner"].raises.names() == {"ValueError"}
    # Returning a function is not calling it, so outer does not raise.
    assert functions["demo.outer"].raises.names() == set()


def test_docstring_declarations_are_recorded():
    source = (
        "def f():\n"
        '    """Do it.\n\n    Raises:\n        ValueError: no\n    """\n'
        '    raise ValueError("no")\n'
    )
    function = analyze(source)["demo.f"]
    assert function.declared == {"ValueError"}
    assert function.undocumented() == set()


def test_an_undocumented_exception_is_reported():
    source = 'def f():\n    """Do it."""\n    raise ValueError("no")\n'
    assert analyze(source)["demo.f"].undocumented() == {"ValueError"}


def test_a_documented_exception_that_is_not_raised_is_reported():
    source = 'def f():\n    """Do it.\n\n    Raises:\n        OSError: no\n    """\n    return 1\n'
    assert analyze(source)["demo.f"].overdocumented() == {"OSError"}


def test_provenance_is_recorded_for_every_exception():
    source = "def inner():\n    raise ValueError('no')\n\n\ndef outer():\n    return inner()\n"
    sources = analyze(source)["demo.outer"].raises.exceptions["ValueError"]
    assert any("propagates" in str(s) for s in sources)
