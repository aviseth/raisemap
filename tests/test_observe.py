"""The runtime pass, against a real interpreter."""

import sys

import pytest

from raisemap.observe import Unsupported, observe, supported

needs_312 = pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring arrived in 3.12")


@pytest.fixture
def package(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text(
        "def explodes():\n"
        "    raise ValueError('no')\n\n\n"
        "def subscripts(values):\n"
        "    return values['missing']\n\n\n"
        "def quiet():\n"
        "    return 1\n"
    )
    (tmp_path / "run.py").write_text(
        "from pkg import core\n\n"
        "for call in (lambda: core.explodes(), lambda: core.subscripts({})):\n"
        "    try:\n"
        "        call()\n"
        "    except Exception:\n"
        "        pass\n"
        "core.quiet()\n"
    )
    return tmp_path


def test_supported_matches_the_running_interpreter():
    assert supported() == (sys.version_info >= (3, 12))


def test_a_missing_interpreter_is_unsupported_not_a_crash():
    assert not supported("/definitely/not/a/python")


@needs_312
def test_exceptions_leaving_a_function_are_recorded(package):
    seen = observe([sys.executable, "run.py"], roots=[package / "pkg"], cwd=package)
    assert seen.returncode == 0
    core = str((package / "pkg" / "core.py").resolve())
    assert seen.for_qualname(core, "explodes") == {"ValueError"}


@needs_312
def test_an_exception_the_static_pass_would_miss_is_caught(package):
    """A subscript raising KeyError is deliberately not inferred statically."""
    seen = observe([sys.executable, "run.py"], roots=[package / "pkg"], cwd=package)
    core = str((package / "pkg" / "core.py").resolve())
    assert seen.for_qualname(core, "subscripts") == {"KeyError"}


@needs_312
def test_a_function_that_never_raises_is_not_recorded(package):
    seen = observe([sys.executable, "run.py"], roots=[package / "pkg"], cwd=package)
    core = str((package / "pkg" / "core.py").resolve())
    assert seen.for_qualname(core, "quiet") == set()


@needs_312
def test_roots_keep_the_report_to_your_own_code(package):
    """Without a root filter every stdlib frame would end up in the report."""
    seen = observe([sys.executable, "run.py"], roots=[package / "pkg"], cwd=package)
    assert all(key.startswith(str((package / "pkg").resolve())) for key in seen.by_function)


@needs_312
def test_a_command_that_fails_still_returns_what_it_saw(package):
    (package / "boom.py").write_text("from pkg import core\ncore.explodes()\n")
    seen = observe([sys.executable, "boom.py"], roots=[package / "pkg"], cwd=package)
    assert seen.returncode != 0
    core = str((package / "pkg" / "core.py").resolve())
    assert "ValueError" in seen.for_qualname(core, "explodes")


@needs_312
def test_a_hanging_command_times_out(package):
    (package / "slow.py").write_text("import time\ntime.sleep(30)\n")
    seen = observe([sys.executable, "slow.py"], roots=[package / "pkg"], cwd=package, timeout=2)
    assert seen.returncode == 124
    assert "timed out" in seen.stderr


def test_an_old_interpreter_is_refused_rather_than_approximated():
    with pytest.raises(Unsupported, match=r"3\.12"):
        observe(["true"], python="/definitely/not/a/python")
