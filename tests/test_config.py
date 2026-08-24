import pytest

from raisemap.config import ConfigError, load


def write(tmp_path, body):
    path = tmp_path / "pyproject.toml"
    path.write_text(body)
    return path


def test_no_section_gives_defaults(tmp_path):
    config = load(write(tmp_path, '[project]\nname = "x"\n'))
    assert config.paths == []
    assert config.require_docstrings is False


def test_a_full_section(tmp_path):
    path = write(
        tmp_path,
        '[tool.raisemap]\npaths = ["src", "app"]\nlock = "ci/raises.lock"\n'
        'require_docstrings = true\nignore = ["NotImplementedError"]\n',
    )
    config = load(path)
    assert config.paths == [tmp_path / "src", tmp_path / "app"]
    assert config.lock == tmp_path / "ci" / "raises.lock"
    assert config.require_docstrings is True
    assert config.ignore == {"NotImplementedError"}


def test_paths_must_be_strings(tmp_path):
    with pytest.raises(ConfigError, match="list of strings"):
        load(write(tmp_path, "[tool.raisemap]\npaths = [1, 2]\n"))


def test_ignore_must_be_strings(tmp_path):
    with pytest.raises(ConfigError, match="list of strings"):
        load(write(tmp_path, "[tool.raisemap]\nignore = [3]\n"))


def test_require_docstrings_must_be_a_boolean(tmp_path):
    with pytest.raises(ConfigError, match="true or false"):
        load(write(tmp_path, '[tool.raisemap]\nrequire_docstrings = "yes"\n'))


@pytest.mark.parametrize(
    "body",
    ["tool = 1\n", "[tool]\nraisemap = 3\n", '[tool.raisemap]\nlock = ["a"]\n'],
)
def test_everything_invalid_surfaces_as_a_config_error(tmp_path, body):
    """Anything else reaches the user as a traceback, since main only catches ours."""
    with pytest.raises(ConfigError):
        load(write(tmp_path, body))


def test_broken_toml_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load(write(tmp_path, "[tool.raisemap\n"))
