"""RPM's versions: written, split and compared as rpm and createrepo_c do."""

import pytest

from megooarti.repositories.yum import versions


@pytest.mark.parametrize(("epoch", "expected"), [("0", "1.0-1"), ("", "1.0-1"), ("2", "2:1.0-1")])
def test_a_version_has_its_epoch_only_when_it_is_not_0(epoch, expected):
    assert versions.evr(epoch, "1.0", "1") == expected


@pytest.mark.parametrize(
    ("said", "split"),
    [
        ("1.0-1", ("0", "1.0", "1")),
        ("1.0", ("0", "1.0", "")),
        ("2:0.3-2", ("2", "0.3", "2")),
        ("1.0-1.fc44-x", ("0", "1.0", "1.fc44-x")),  # the version ends at the first dash
        ("abc:1.0", ("0", "1.0", "")),  # an epoch that is not a number is none
    ],
)
def test_a_dependencys_version_is_split_as_createrepo_c_splits_it(said, split):
    assert versions.split_evr(said) == split


@pytest.mark.parametrize(
    ("evr", "split"),
    [
        ("1.0-1", ("0", "1.0", "1")),
        ("2:0.3-2.fc44", ("2", "0.3", "2.fc44")),
        ("1.0~rc1-1", ("0", "1.0~rc1", "1")),
        ("1.0", None),
        ("x:1.0-1", None),
        ("1.0;reboot-1", None),
        ("1.0-1 2", None),
    ],
)
def test_a_components_version_is_taken_into_a_command_only_as_rpm_writes_one(evr, split):
    assert versions.split(evr) == split


@pytest.mark.parametrize(
    ("one", "two", "order"),
    [
        ("1.0", "1.0", 0),
        ("1.0", "1.1", -1),
        ("2.10", "2.9", 1),
        ("1.0010", "1.9", 1),
        ("1.05", "1.5", 0),
        ("1.0~rc1", "1.0", -1),
        ("1.0~rc1", "1.0~rc2", -1),
        ("1.0^git1", "1.0", 1),
        ("1.0^git1", "1.0.1", -1),
        ("1.0a", "1.0", 1),
        ("1.a", "1.1", -1),
        ("1_0", "1.0", 0),
        ("GLIBC_2.38", "GLIBC_2.4", 1),
        ("", "GLIBC_2.2.5", -1),
    ],
)
def test_versions_are_compared_as_rpmvercmp_compares_them(one, two, order):
    assert versions.compare(one, two) == order
    assert versions.compare(two, one) == -order
