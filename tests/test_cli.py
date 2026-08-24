import json
import sys

import pytest

from raisemap.cli import main


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A package with a documented raise, an undocumented one, and a swallowed one."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n\n[tool.raisemap]\npaths = ["pkg"]\n'
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text(
        'class ConfigError(ValueError):\n    """Bad config."""\n\n\n'
        "def parse_port(text):\n"
        '    """Turn text into a port.\n\n    Raises:\n        ValueError: not a number\n    """\n'
        "    return int(text)\n\n\n"
        "def load(text):\n"
        '    """Read a config."""\n'
        "    port = parse_port(text)\n"
        '    if port > 65535:\n        raise ConfigError("too big")\n'
        "    return port\n\n\n"
        "def swallow(text):\n"
        '    """Never raises."""\n'
        "    try:\n        return load(text)\n    except ValueError:\n        return None\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "raisemap" in capsys.readouterr().out


def test_show_lists_what_each_function_raises(project, capsys):
    assert main(["show", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ValueError" in payload["pkg.core.parse_port"]["raises"]
    assert "ConfigError" in payload["pkg.core.load"]["raises"]


def test_a_swallowed_exception_does_not_appear(project, capsys):
    """swallow() catches ValueError, and ConfigError is a ValueError."""
    assert main(["show", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "ConfigError" not in payload.get("pkg.core.swallow", {}).get("raises", [])


def test_show_can_filter_to_one_function(project, capsys):
    assert main(["show", "--function", "parse_port", "--json"]) == 0
    assert list(json.loads(capsys.readouterr().out)) == ["pkg.core.parse_port"]


def test_show_reports_an_unknown_function(project, capsys):
    assert main(["show", "--function", "nope"]) == 1
    assert "no function called" in capsys.readouterr().err


def test_show_why_gives_provenance(project, capsys):
    assert main(["show", "--why"]) == 0
    out = capsys.readouterr().out
    assert "propagates from a call" in out or "raised here" in out


def test_docs_flags_the_undocumented_exception(project, capsys):
    assert main(["docs"]) == 1
    out = capsys.readouterr().out
    assert "undocumented" in out
    assert "pkg.core.load" in out


def test_docs_is_happy_once_everything_is_declared(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "d"\nversion = "0"\n')
    (tmp_path / "m.py").write_text(
        'def f(x):\n    """Do it.\n\n    Raises:\n        ValueError: no\n    """\n'
        "    raise ValueError('no')\n"
    )
    monkeypatch.chdir(tmp_path)
    assert main(["docs", "."]) == 0
    assert "docstrings agree" in capsys.readouterr().out


def test_check_needs_a_lock_first(project, capsys):
    assert main(["check"]) == 2
    assert "no lock at" in capsys.readouterr().err


def test_check_passes_against_its_own_lock(project, capsys):
    assert main(["check", "--update"]) == 0
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "none changed" in capsys.readouterr().out


def test_check_fails_when_a_public_function_starts_raising_something_new(project, capsys):
    assert main(["check", "--update"]) == 0
    capsys.readouterr()

    core = project / "pkg" / "core.py"
    core.write_text(core.read_text().replace("    return port", "    raise LookupError('x')"))

    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "now raises" in out
    assert "LookupError" in out


def test_check_json(project, capsys):
    assert main(["check", "--update"]) == 0
    capsys.readouterr()
    assert main(["check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


@pytest.mark.skipif(sys.version_info < (3, 12), reason="needs sys.monitoring")
def test_observe_finds_what_static_analysis_missed(project, capsys, monkeypatch):
    core = project / "pkg" / "core.py"
    core.write_text(
        core.read_text()
        + '\n\ndef lookup(values):\n    """Look it up."""\n    return values["k"]\n'
    )
    (project / "run.py").write_text(
        "from pkg import core\n\ntry:\n    core.lookup({})\nexcept KeyError:\n    pass\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(project))
    assert main(["observe", "--command", f"{sys.executable} run.py", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert any("lookup" in key for key in payload["blind_spots"])
