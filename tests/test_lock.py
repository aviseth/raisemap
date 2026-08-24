import json

import pytest

from raisemap import lock as lockfile
from raisemap.models import Function, Raises, Source


def function(key: str, *exceptions: str, public: bool = True) -> Function:
    module, _, qualname = key.rpartition(".")
    f = Function(qualname=qualname, module=module, path="x.py", line=1, is_public=public)
    for name in exceptions:
        f.raises.add(name, Source("raised here", 1))
    return f


def test_build_records_public_functions_that_raise():
    functions = {
        "m.public": function("m.public", "ValueError"),
        "m._private": function("m._private", "OSError", public=False),
        "m.quiet": function("m.quiet"),
    }
    assert lockfile.build(functions) == {"m.public": ["ValueError"]}


def test_build_can_include_private_functions():
    functions = {"m._private": function("m._private", "OSError", public=False)}
    assert lockfile.build(functions, public_only=False) == {"m._private": ["OSError"]}


def test_round_trip(tmp_path):
    path = tmp_path / "raisemap.lock"
    lockfile.write(
        path, lockfile.Lock(functions={"m.f": ["OSError", "ValueError"]}, public={"m.f", "m.g"})
    )
    assert path.read_text().endswith("\n")
    back = lockfile.read(path)
    assert back.functions == {"m.f": ["OSError", "ValueError"]}
    assert back.public == {"m.f", "m.g"}


def test_a_missing_lock_reads_as_empty(tmp_path):
    empty = lockfile.read(tmp_path / "nope.lock")
    assert empty.functions == {}
    assert empty.public == set()


def test_an_unknown_version_is_an_error(tmp_path):
    path = tmp_path / "raisemap.lock"
    path.write_text(json.dumps({"version": 99, "functions": {}}))
    with pytest.raises(ValueError, match="unsupported lock version"):
        lockfile.read(path)


def test_a_new_exception_shows_up_as_added():
    drifts = lockfile.compare({"m.f": ["ValueError"]}, {"m.f": ["OSError", "ValueError"]})
    assert [(d.key, d.added, d.removed) for d in drifts] == [("m.f", ["OSError"], [])]


def test_a_removed_exception_shows_up_too():
    drifts = lockfile.compare({"m.f": ["OSError", "ValueError"]}, {"m.f": ["ValueError"]})
    assert drifts[0].removed == ["OSError"]


def test_nothing_changing_is_no_drift():
    assert lockfile.compare({"m.f": ["ValueError"]}, {"m.f": ["ValueError"]}) == []


def test_a_function_that_did_not_exist_before_is_not_drift():
    """A new function has no previous behaviour to have changed."""
    assert lockfile.compare({}, {"m.new": ["ValueError"]}) == []


def test_a_deleted_function_is_not_drift_either():
    assert lockfile.compare({"m.gone": ["ValueError"]}, {}) == []


def test_a_function_that_existed_and_started_raising_is_reported():
    lock = lockfile.Lock(functions={"m.f": ["ValueError"]}, public={"m.f", "m.g"})
    current = {"m.f": ["ValueError"], "m.g": ["OSError"]}
    assert lockfile.newly_raising(lock, current) == ["m.g"]


def test_a_function_that_did_not_exist_before_is_not_reported():
    """compare says nothing about new functions, and this has to agree with it."""
    lock = lockfile.Lock(functions={"m.f": ["ValueError"]}, public={"m.f"})
    current = {"m.f": ["ValueError"], "m.brand_new": ["OSError"]}
    assert lockfile.newly_raising(lock, current) == []


def test_the_lock_is_written_sorted(tmp_path):
    path = tmp_path / "raisemap.lock"
    lockfile.write(path, lockfile.Lock(functions={"z": ["A"], "a": ["B"], "m": ["C"]}))
    text = path.read_text()
    assert text.index('"a"') < text.index('"m"') < text.index('"z"')


def test_a_lock_that_is_not_an_object_is_a_value_error(tmp_path):
    path = tmp_path / "raisemap.lock"
    path.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="expected an object"):
        lockfile.read(path)


def test_lockable_keys_includes_functions_that_raise_nothing():
    functions = {
        "m.raises": function("m.raises", "ValueError"),
        "m.quiet": function("m.quiet"),
        "m._private": function("m._private", "OSError", public=False),
    }
    assert lockfile.lockable_keys(functions) == {"m.raises", "m.quiet"}


def test_raises_merge_keeps_provenance_from_both():
    left, right = Raises(), Raises()
    left.add("ValueError", Source("raised here", 1))
    right.add("ValueError", Source("propagates from a call", 9))
    left.merge(right)
    assert len(left.exceptions["ValueError"]) == 2


def test_raises_without_drops_the_caught_ones():
    r = Raises()
    r.add("ValueError", Source("raised here", 1))
    r.add("OSError", Source("raised here", 2))
    assert r.without({"OSError"}).names() == {"ValueError"}


def test_the_same_source_is_not_recorded_twice():
    r = Raises()
    r.add("ValueError", Source("raised here", 1))
    r.add("ValueError", Source("raised here", 1))
    assert len(r.exceptions["ValueError"]) == 1
