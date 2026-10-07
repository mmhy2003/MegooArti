import pytest

from megooarti.errors import ApiError
from megooarti.repositories.paths import normalise_path


@pytest.mark.parametrize(
    "path",
    [
        "a.txt",
        "a/b/c.tar.gz",
        "ünï/côde ✓.bin",
        "with space/and (parens).txt",
        ".hidden",
        "a/..b/c..",
        "x" * 1024,
    ],
)
def test_valid_paths_are_returned_unchanged(path):
    assert normalise_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/a",
        "a/",
        "a//b",
        "..",
        "../a",
        "a/../b",
        "a/./b",
        ".",
        "a\\b",
        "a\x00b",
        "a\nb",
        "a\x7fb",
        "x" * 1025,
        "é" * 513,
    ],
)
def test_invalid_paths_are_rejected(path):
    with pytest.raises(ApiError) as caught:
        normalise_path(path)
    assert (caught.value.status_code, caught.value.code) == (400, "invalid_path")
