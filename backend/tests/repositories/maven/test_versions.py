from itertools import pairwise

import pytest

from megooarti.repositories.maven.versions import compare, sorted_versions

EQUAL = [
    ("1", "1.0"),
    ("1", "1.0.0"),
    ("1.0", "1-0"),
    ("1", "1-ga"),
    ("1", "1-final"),
    ("1", "1.ga"),
    ("1.0", "1.0-release"),
    ("1.0", "1."),
    ("1.0", "1-"),
    ("1.0-alpha1", "1.0-a1"),
    ("1.0-alpha1", "1.0-alpha-1"),
    ("1.0-beta1", "1.0-b1"),
    ("1.0-milestone1", "1.0-m1"),
    ("1.0-rc1", "1.0-cr1"),
    ("1.0-RC1", "1.0-rc1"),
    ("1.0-SNAPSHOT", "1.0-snapshot"),
    ("1.0.0-foo.0.0", "1-foo"),
    ("1.0.0-0.0.0", "1"),
    # A qualifier after a dot is the same as one after a hyphen.
    ("1.foo", "1-foo"),
    ("1.0.RC1", "1.0-RC1"),
    ("5.0.0.Final", "5.0.0"),
    ("1.2.3.RELEASE", "1.2.3"),
    ("1.0.0.Final-SNAPSHOT", "1.0.0-SNAPSHOT"),
]

OLDER_THEN_NEWER = [
    ("1", "2"),
    ("1.5", "2"),
    ("1", "2.5"),
    ("1.0", "1.1"),
    ("1.1", "1.2"),
    ("1.0.0", "1.1"),
    ("1.0.1", "1.1"),
    ("1.1", "1.2.0"),
    ("1.9", "1.10"),
    ("1.0-alpha-1", "1.0"),
    ("1.0-alpha-1", "1.0-alpha-2"),
    ("1.0-alpha-1", "1.0-beta-1"),
    ("1.0-beta-1", "1.0-milestone-1"),
    ("1.0-milestone-1", "1.0-rc-1"),
    ("1.0-rc-1", "1.0-SNAPSHOT"),
    ("1.0-SNAPSHOT", "1.0"),
    ("1.0-alpha-1-SNAPSHOT", "1.0-alpha-1"),
    ("1.0-SNAPSHOT", "1.1-SNAPSHOT"),
    ("1.0", "1.0-1"),
    ("1.0-1", "1.0-2"),
    ("1.0.0", "1.0-1"),
    ("2.0-1", "2.0.1"),
    ("2.0.1-klm", "2.0.1-lmn"),
    ("2.0.1", "2.0.1-xyz"),
    ("2.0.1", "2.0.1-123"),
    ("2.0.1-xyz", "2.0.1-123"),
    ("1.0", "1.0-sp"),
    ("1.0-sp", "1.0-sp1"),
    ("1.0-sp", "1.0-xyz"),
    ("1-foo2", "1-foo10"),
    ("1-foo", "1-1"),
    ("1-1", "1.1"),
    ("1-ga.1", "1-sp.1"),
    ("1-sp-1", "1-ga-1"),
    ("4.1.0.Beta1", "4.1.0.Final"),
    ("1.0.RC1", "1.0.RC2"),
    # A qualifier that ends at a dot or hyphen stays beside the numbers before it.
    ("2.0.0.BUILD", "2.0.0.BUILD-SNAPSHOT"),
    ("1.0.x", "1.0.x-SNAPSHOT"),
    ("4.5.13.redhat-00001", "4.5.13-redhat-1"),
    # Every part of what one version has extra counts, not only the first.
    ("1.0.0", "1.0.0-0.1"),
    ("5.0.0.Final", "5.0.0.Final.1"),
]


@pytest.mark.parametrize(("left", "right"), EQUAL)
def test_versions_that_differ_only_in_form_are_equal(left, right):
    assert compare(left, right) == 0
    assert compare(right, left) == 0


@pytest.mark.parametrize(("older", "newer"), OLDER_THEN_NEWER)
def test_an_older_version_sorts_before_a_newer_one(older, newer):
    assert compare(older, newer) == -1
    assert compare(newer, older) == 1


def test_the_qualifier_order():
    ordered = [
        "1-alpha2",
        "1-beta-2",
        "1-m2",
        "1-m11",
        "1-rc",
        "1-cr2",
        "1-rc123",
        "1-SNAPSHOT",
        "1",
        "1-sp",
        "1-sp2",
        "1-abc",
        "1-def",
        "1-1",
        "1-2",
        "1-123",
    ]

    for older, newer in pairwise(ordered):
        assert compare(older, newer) == -1, (older, newer)


def test_sorting_is_by_version_not_by_text():
    shuffled = ["1.10", "1.9", "1.0", "1.2-SNAPSHOT", "1.2", "1.0-rc1"]

    assert sorted_versions(shuffled) == ["1.0-rc1", "1.0", "1.2-SNAPSHOT", "1.2", "1.9", "1.10"]


def test_equal_versions_are_kept_apart_in_text_order():
    assert sorted_versions(["1.0.0", "1", "1.0", "1"]) == ["1", "1.0", "1.0.0"]


@pytest.mark.parametrize(
    "odd",
    ["", "-", ".", "..", "--", "RELEASE", "latest", "1..2", "1--2", "ünïcode", "٣.٤", "v1.0", "00"]
    + ["9" * 255, "1-" * 127, "a1" * 127],
)
def test_any_text_can_be_compared(odd):
    assert compare(odd, odd) == 0
    assert compare(odd, "1.0") in (-1, 0, 1)
    assert compare("1.0", odd) == -compare(odd, "1.0")
    assert set(sorted_versions([odd, "1.0"])) == {odd, "1.0"}
