import pytest

from megooarti.repositories.npm import paths
from megooarti.repositories.npm.paths import NpmPath, classify

OTHER = NpmPath("other")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("left-pad", NpmPath("document", package="left-pad")),
        ("@acme/widget", NpmPath("document", package="@acme/widget")),
        ("left-pad/-rev/3-abc", NpmPath("document", package="left-pad")),
        ("@acme/widget/-rev/3-abc", NpmPath("document", package="@acme/widget")),
        ("JSONStream", NpmPath("document", package="JSONStream")),
        ("left-pad/1.3.0", NpmPath("version", package="left-pad", version="1.3.0")),
        ("left-pad/latest", NpmPath("version", package="left-pad", version="latest")),
        ("@acme/widget/2.0.0", NpmPath("version", package="@acme/widget", version="2.0.0")),
        (
            "left-pad/-/left-pad-1.3.0.tgz",
            NpmPath("tarball", package="left-pad", version="1.3.0", filename="left-pad-1.3.0.tgz"),
        ),
        (
            "@acme/widget/-/widget-2.0.0-beta.1.tgz",
            NpmPath(
                "tarball",
                package="@acme/widget",
                version="2.0.0-beta.1",
                filename="widget-2.0.0-beta.1.tgz",
            ),
        ),
        (
            "left-pad/-/left-pad-1.3.0.tgz/-rev/4-def",
            NpmPath("tarball", package="left-pad", version="1.3.0", filename="left-pad-1.3.0.tgz"),
        ),
    ],
)
def test_package_paths(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("-/ping", NpmPath("ping")),
        ("-/whoami", NpmPath("whoami")),
        ("-/v1/search", NpmPath("search")),
        ("-/user/org.couchdb.user:dana", NpmPath("login", username="dana")),
        ("-/user/org.couchdb.user:dana/-rev/1-abc", NpmPath("login", username="dana")),
        ("-/user/token/mga_abc", NpmPath("logout", token="mga_abc")),
        ("-/package/left-pad/dist-tags", NpmPath("dist_tags", package="left-pad")),
        ("-/package/left-pad/dist-tags/beta", NpmPath("dist_tags", package="left-pad", tag="beta")),
        (
            "-/package/@acme/widget/dist-tags/next",
            NpmPath("dist_tags", package="@acme/widget", tag="next"),
        ),
    ],
)
def test_registry_paths(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "-",
        "-/v1/login",
        "-/npm/v1/security/advisories/bulk",
        "-/user/org.couchdb.user:",
        "-/user/someone",
        "-/user/token",
        "-/package/left-pad",
        "-/package/@acme/dist-tags",
        "-/package/left-pad/dist-tags/a/b",
        "@acme",
        "@/widget",
        ".hidden",
        "_private",
        "has space",
        "a" * 215,
        "left-pad/-",
        "left-pad/-/other-1.3.0.tgz",
        "left-pad/-/left-pad-.tgz",
        "left-pad/-/left-pad-1.3.0.zip",
        "left-pad/-/left-pad-1.3.0.tgz/extra",
        "@acme/widget/-/@acme/widget-2.0.0.tgz",
        "left-pad/1.3.0/extra",
    ],
)
def test_everything_else_is_other(path):
    assert classify(path) == OTHER


def test_a_path_knows_its_scope_and_name():
    scoped = classify("@acme/widget/-/widget-2.0.0.tgz")
    plain = classify("left-pad")

    assert (scoped.scope, scoped.name) == ("acme", "widget")
    assert (plain.scope, plain.name) == ("", "left-pad")


@pytest.mark.parametrize(
    ("package", "valid"),
    [
        ("left-pad", True),
        ("@acme/widget", True),
        ("a.b_c~d", True),
        ("JSONStream", True),
        ("a" * 214, True),
        ("a" * 215, False),
        ("", False),
        ("@acme", False),
        ("@acme/", False),
        ("@acme/widget/more", False),
        (".hidden", False),
        ("@acme/_private", False),
        ("with/slash", False),
        ("ünïcode", False),
        ("percent%2f", False),
    ],
)
def test_package_names(package, valid):
    assert paths.is_valid_name(package) is valid


def test_where_things_are_stored():
    assert paths.tarball_path("left-pad", "1.3.0") == "left-pad/-/left-pad-1.3.0.tgz"
    assert paths.tarball_path("@acme/widget", "2.0.0") == "@acme/widget/-/widget-2.0.0.tgz"
    assert paths.dist_tags_path("@acme/widget") == "-/package/@acme/widget/dist-tags"
    assert classify(paths.tarball_path("@acme/widget", "2.0.0")).kind == "tarball"
    assert classify(paths.dist_tags_path("@acme/widget")).kind == "dist_tags"
