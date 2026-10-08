from itertools import pairwise

import pytest

from megooarti.repositories.npm import semver

# The precedence example from section 11 of the specification, lowest first.
PRECEDENCE = [
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-alpha.beta",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.11",
    "1.0.0-rc.1",
    "1.0.0",
    "1.0.1",
    "1.1.0",
    "1.10.0",
    "2.0.0",
    "10.0.0",
]


@pytest.mark.parametrize(
    "version",
    ["0.0.0", "1.2.3", "10.20.30", "1.0.0-alpha", "1.0.0-0.3.7", "1.0.0-x.7.z.92", "1.0.0-x-y-z.--"]
    + ["1.0.0+20130313144700", "1.0.0-beta+exp.sha.5114f85", "1.0.0+21AF26D3----117B344092BD"],
)
def test_valid_versions(version):
    assert semver.is_valid(version) is True


@pytest.mark.parametrize(
    "version",
    ["", "1", "1.2", "1.2.3.4", "v1.2.3", "01.2.3", "1.02.3", "1.2.3-", "1.2.3-01", "1.2.3+"]
    + ["1.2.3-a..b", "1.2.3 ", "latest", "1.2.x", "١.٢.٣", "1." * 200 + "1"],
)
def test_invalid_versions(version):
    assert semver.is_valid(version) is False


def test_the_order_is_the_specifications():
    for lower, higher in pairwise(PRECEDENCE):
        assert semver.sort_key(lower) < semver.sort_key(higher), (lower, higher)


def test_sorting_is_by_precedence_not_by_text():
    shuffled = list(reversed(PRECEDENCE))

    assert semver.sorted_versions(shuffled) == PRECEDENCE
    assert semver.highest(shuffled) == "10.0.0"


def test_build_metadata_does_not_change_precedence():
    plain, built = semver.sort_key("1.0.0"), semver.sort_key("1.0.0+build.5")

    assert plain[:-1] == built[:-1]
    assert semver.sorted_versions(["1.0.0+b", "1.0.0+a", "1.0.0"]) == [
        "1.0.0",
        "1.0.0+a",
        "1.0.0+b",
    ]


def test_invalid_versions_sort_before_valid_ones_and_never_fail():
    odd = ["latest", "", "1.2", "v9.9.9", "١.٢.٣"]

    ordered = semver.sorted_versions([*odd, "0.0.1"])

    assert ordered[-1] == "0.0.1"
    assert set(ordered[:-1]) == set(odd)


def test_the_highest_of_nothing_is_nothing():
    assert semver.highest([]) is None
    assert semver.sorted_versions(["1.0.0", "1.0.0"]) == ["1.0.0"]


def test_a_version_fits_where_it_is_stored():
    longest = "1.0.0-" + "a" * 249

    assert (len(longest), semver.is_valid(longest)) == (255, True)
    assert semver.is_valid(longest + "a") is False
