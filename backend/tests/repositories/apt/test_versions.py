import pytest

from megooarti.repositories.apt import versions


@pytest.mark.parametrize(
    ("version", "parts"),
    [
        ("1.0", (0, "1.0", "")),
        ("1.0-1", (0, "1.0", "1")),
        ("1:2.0~rc1-1", (1, "2.0~rc1", "1")),
        ("2.0-beta-3", (0, "2.0-beta", "3")),
        ("0.3+dfsg1-2ubuntu1", (0, "0.3+dfsg1", "2ubuntu1")),
    ],
)
def test_a_version_is_split_into_epoch_upstream_and_revision(version, parts):
    assert versions.split(version) == parts


@pytest.mark.parametrize(
    "version",
    ["", "a1.0", "1.0-", "x:1.0", "1.0_1", "1.0 1", "1:", "1:2:3", "1.0-a_b", "1" * 256],
)
def test_a_version_dpkg_would_refuse_is_refused(version):
    assert versions.split(version) is None


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.0", "1.1"),
        ("1.0~rc1", "1.0"),
        ("1.0~~", "1.0~"),
        ("1.0~", "1.0"),
        ("1.0", "1.0a"),
        ("1.0a", "1.0+b1"),
        ("1.0", "1.0-1"),
        ("1.0-1", "1.0-2"),
        ("1.0-9", "1.0-10"),
        ("2.0", "1:0.1"),
        ("1.9", "1.10"),
        ("1.0-1", "1.0-1ubuntu1"),
    ],
)
def test_versions_are_ordered_as_dpkg_orders_them(lower, higher):
    assert versions.compare(lower, higher) == -1
    assert versions.compare(higher, lower) == 1


@pytest.mark.parametrize(("left", "right"), [("1.0", "1.0"), ("1.002", "1.2"), ("0:1.0", "1.0")])
def test_versions_dpkg_takes_for_the_same_are_equal(left, right):
    assert versions.compare(left, right) == 0


def test_versions_sort_by_their_order():
    given = ["1.0-1", "1:0.1", "1.0~rc1", "1.0", "0.9"]

    assert sorted(given, key=versions.version_key) == ["0.9", "1.0~rc1", "1.0", "1.0-1", "1:0.1"]


def test_a_file_name_has_the_version_without_its_epoch():
    assert versions.without_epoch("1:2.0~rc1-1") == "2.0~rc1-1"
    assert versions.without_epoch("2.0") == "2.0"


@pytest.mark.parametrize(("name", "valid"), [("hello", True), ("lib-x+2.0", True), ("a", False)])
def test_a_package_name_is_lower_case_and_at_least_two_long(name, valid):
    assert (versions.NAME.fullmatch(name) is not None) is valid
