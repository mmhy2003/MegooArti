import pytest

from megooarti.errors import ApiError
from megooarti.repositories.formats import ComponentKey, Format, format_names, get_format, register
from megooarti.repositories.raw import RawFormat


def test_raw_is_registered():
    assert isinstance(get_format("raw"), RawFormat)
    assert "raw" in format_names()
    assert get_format("no-such-format") is None


def test_raw_supports_every_repository_type():
    assert get_format("raw").types == {"hosted", "proxy", "group"}


def test_a_format_without_settings_accepts_only_an_empty_object():
    raw = get_format("raw")

    assert raw.validate_config("hosted", {}) == {}
    with pytest.raises(ApiError) as caught:
        raw.validate_config("hosted", {"anything": 1})
    assert caught.value.code == "validation_error"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/guide/intro.txt", ComponentKey("docs/guide", "intro.txt")),
        ("top.txt", ComponentKey("", "top.txt")),
    ],
)
def test_the_generic_component_is_the_file_in_its_directory(path, expected):
    assert get_format("raw").describe_component(path) == expected


def test_a_format_must_have_a_name_to_be_registered():
    with pytest.raises(ValueError):
        register(Format())
