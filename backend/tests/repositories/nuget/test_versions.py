"""NuGet's ids and versions, as NuGet's own client reads them."""

import pytest

from megooarti.repositories.nuget import versions


@pytest.mark.parametrize(
    ("written", "normalized"),
    [
        ("1.0.0", "1.0.0"),
        ("1.0", "1.0.0"),
        ("1", "1.0.0"),
        ("01.002.0003", "1.2.3"),
        ("1.2.3.0", "1.2.3"),
        ("1.2.3.4", "1.2.3.4"),
        ("1.0.0-beta.1", "1.0.0-beta.1"),
        ("1.0.0-Beta", "1.0.0-Beta"),
        ("1.0.0+build.7", "1.0.0"),
        ("1.0.0-rc.1+sha.abc", "1.0.0-rc.1"),
    ],
)
def test_a_version_is_written_as_nuget_writes_it(written, normalized):
    assert versions.normalize(written) == normalized


@pytest.mark.parametrize(
    "written",
    ["", "a.b", "1.0.0.0.0", "1.0.0-", "1.0.0-beta..1", "1.0.0+", "1." + "9" * 11, "v1.0"],
)
def test_what_is_not_a_version_is_none(written):
    assert versions.parse(written) is None


def test_versions_are_in_nugets_order():
    written = ["1.0.0", "1.0.0-beta.2", "1.0.0-beta.10", "1.0.0-alpha", "0.9.0", "1.0.0.1", "2.0"]

    assert versions.ordered(written) == [
        "0.9.0",
        "1.0.0-alpha",
        "1.0.0-beta.2",
        "1.0.0-beta.10",
        "1.0.0",
        "1.0.0.1",
        "2.0",
    ]


def test_a_prerelease_and_a_semver2_version_are_told_apart():
    assert versions.parse("1.0.0-beta").is_prerelease
    assert not versions.parse("1.0.0+meta").is_prerelease
    assert versions.parse("1.0.0-beta.1").is_semver2
    assert versions.parse("1.0.0+meta").is_semver2
    assert not versions.parse("1.0.0-beta").is_semver2


@pytest.mark.parametrize(
    ("text", "taken"),
    [
        ("MegooArti.Hello", True),
        ("Newtonsoft.Json", True),
        ("a-b_c.d", True),
        ("x" * 100, True),
        ("x" * 101, False),
        (".Hello", False),
        ("Hello.", False),
        ("Hel lo", False),
        ("Hel/lo", False),
        ("", False),
    ],
)
def test_an_id_is_what_nuget_takes(text, taken):
    assert versions.is_id(text) is taken
