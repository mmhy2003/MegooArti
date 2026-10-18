"""Each format's versions in the order its clients put them, and which are prereleases:
what an agent is told is a package's newest release (MCP spec 6.1, `package_versions`)."""

import pytest

from megooarti.repositories.formats import get_format

ORDERS = [
    ("raw", ["1.10", "1.9", "1.2", "1.9"], ["1.2", "1.9", "1.10"]),
    (
        "npm",
        ["1.0.0", "1.0.0-beta.10", "0.9.0", "1.0.0-beta.2"],
        ["0.9.0", "1.0.0-beta.2", "1.0.0-beta.10", "1.0.0"],
    ),
    (
        "nuget",
        ["10.0.0", "1.0.0", "2.0.0", "1.0.0-rc.1", "not a version"],
        ["not a version", "1.0.0-rc.1", "1.0.0", "2.0.0", "10.0.0"],
    ),
    (
        "maven",
        ["1.10", "1.0", "1.0-SNAPSHOT", "1.9", "1.0-alpha-1"],
        ["1.0-alpha-1", "1.0-SNAPSHOT", "1.0", "1.9", "1.10"],
    ),
    (
        "pypi",
        ["1.0.post1", "1.0", "1.0rc1", "0.9", "1.0.dev1"],
        ["0.9", "1.0.dev1", "1.0rc1", "1.0", "1.0.post1"],
    ),
    (
        "apt",
        ["1:0.5-1", "1.0-2", "1.0-1", "1.0~rc1-1"],
        ["1.0~rc1-1", "1.0-1", "1.0-2", "1:0.5-1"],
    ),
    (
        "yum",
        ["1:0.5-1", "1.0-10", "1.0-2", "1.0-1", "1.0~rc1-1"],
        ["1.0~rc1-1", "1.0-1", "1.0-2", "1.0-10", "1:0.5-1"],
    ),
    (
        "apk",
        ["1.10-r0", "1.0a-r0", "1.0-r1", "1.0-r0", "1.9-r0", "1.0_rc1-r0"],
        ["1.0_rc1-r0", "1.0-r0", "1.0-r1", "1.0a-r0", "1.9-r0", "1.10-r0"],
    ),
]

PRERELEASES = [
    ("raw", "1.0-beta", False),
    ("npm", "1.0.0-beta.1", True),
    ("npm", "1.0.0", False),
    ("nuget", "1.0.0-rc.1", True),
    ("nuget", "1.0.0", False),
    ("maven", "1.0-SNAPSHOT", True),
    ("maven", "1.0-beta-2", True),
    ("maven", "2.0.0-M3", True),
    ("maven", "1.0.RC1", True),
    ("maven", "1.0", False),
    ("maven", "1.0-jre", False),
    ("pypi", "1.0rc1", True),
    ("pypi", "1.0.dev3", True),
    ("pypi", "1.0.post1", False),
    ("pypi", "not a version", False),
    ("apt", "1.0~rc1-1", True),
    ("apt", "1.0-1", False),
    ("yum", "1.0~beta-1", True),
    ("yum", "1.0-1~fc40", False),
    ("apk", "1.0_rc1-r0", True),
    ("apk", "1.0_p2-r0", False),
]


@pytest.mark.parametrize(("name", "given", "ordered"), ORDERS, ids=[o[0] for o in ORDERS])
def test_a_formats_versions_are_in_its_clients_order_each_once(name, given, ordered):
    handler = get_format(name)
    assert handler is not None

    assert handler.ordered_versions(given) == ordered


def test_a_docker_tag_is_a_name_with_no_order():
    handler = get_format("docker")
    assert handler is not None

    assert handler.ordered_versions(["latest", "1.0", "edge"]) is None


@pytest.mark.parametrize(
    ("name", "version", "prerelease"), PRERELEASES, ids=[f"{p[0]}-{p[1]}" for p in PRERELEASES]
)
def test_a_prerelease_is_one_a_client_takes_only_when_asked_for_it(name, version, prerelease):
    handler = get_format(name)
    assert handler is not None

    assert handler.is_prerelease(version) is prerelease
