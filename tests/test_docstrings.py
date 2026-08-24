import pytest

from raisemap.docstrings import declared_exceptions

GOOGLE = """Do a thing.

Args:
    x: a thing

Raises:
    ValueError: if x is empty
    OSError: if the file is missing

Returns:
    None
"""

NUMPY = """Do a thing.

Raises
------
ValueError
    if x is empty
KeyError
    if it is missing
"""

SPHINX = """Do a thing.

:param x: a thing
:raises ValueError: if empty
:raise OSError: if missing
"""


def test_google():
    assert declared_exceptions(GOOGLE) == {"ValueError", "OSError"}


def test_numpy():
    assert declared_exceptions(NUMPY) == {"ValueError", "KeyError"}


def test_sphinx():
    assert declared_exceptions(SPHINX) == {"ValueError", "OSError"}


def test_the_raises_block_stops_at_the_next_section():
    """Returns: follows Raises: in the Google example and must not be swallowed."""
    assert "Returns" not in declared_exceptions(GOOGLE)
    assert "None" not in declared_exceptions(GOOGLE)


def test_descriptions_spanning_lines_are_not_read_as_exceptions():
    docstring = """Do a thing.

Raises:
    ValueError: if x is empty
        and also if it is only whitespace
    OSError: nope
"""
    assert declared_exceptions(docstring) == {"ValueError", "OSError"}


def test_dotted_exception_names_survive():
    assert declared_exceptions(":raises json.JSONDecodeError: bad json") == {"json.JSONDecodeError"}


def test_a_docstring_with_no_raises_section():
    assert declared_exceptions("Just a summary.\n\nArgs:\n    x: a thing\n") == set()


@pytest.mark.parametrize("value", ["", "   ", "\n\n"])
def test_empty_docstrings(value):
    assert declared_exceptions(value) == set()


def test_the_singular_spelling_is_accepted():
    assert declared_exceptions("Do it.\n\nRaise:\n    ValueError: nope\n") == {"ValueError"}


def test_a_numpy_section_after_raises_is_not_read_as_an_exception():
    docstring = """Do a thing.

Raises
------
ValueError
    if x is empty

Returns
-------
int
    the answer
"""
    assert declared_exceptions(docstring) == {"ValueError"}
