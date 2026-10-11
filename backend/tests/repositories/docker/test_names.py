import pytest

from megooarti.repositories.docker import names
from megooarti.repositories.docker.names import DockerPath, classify

DIGEST = "sha256:" + "a" * 64
UPLOAD = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "image",
    [
        "app",
        "team/app",
        "a/b/c/d",
        "my-app",
        "my--app",
        "my_app",
        "my__app",
        "my.app",
        "0",
        "a1/b2",
    ],
)
def test_valid_image_names(image):
    assert names.is_valid_name(image)


@pytest.mark.parametrize(
    "image",
    [
        "",
        "App",
        "team/App",
        "-app",
        "app-",
        "app..x",
        "app___x",
        "app_.x",
        "/app",
        "app/",
        "a//b",
        "a b",
        "app:latest",
        "app@sha256",
        "ünï",
        "a" * 256,
        "../app",
        ".",
    ],
)
def test_invalid_image_names(image):
    assert not names.is_valid_name(image)


@pytest.mark.parametrize("tag", ["latest", "1.0", "v1.0.0-rc.1", "_internal", "A", "a" * 128, "1"])
def test_valid_tags(tag):
    assert names.is_tag(tag)


@pytest.mark.parametrize(
    "tag", ["", ".hidden", "-dash", "a" * 129, "a/b", "a:b", "a b", DIGEST, "é"]
)
def test_invalid_tags(tag):
    assert not names.is_tag(tag)


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:" + "A" * 64,  # one spelling: lower case
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha256:" + "g" * 64,
        "sha512:" + "a" * 128,
        "a" * 64,
        "sha256:",
        "",
    ],
)
def test_only_a_lower_case_sha256_is_a_digest(digest):
    assert names.is_digest(DIGEST)
    assert not names.is_digest(digest)
    assert names.hex_of(DIGEST) == "a" * 64


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("app/manifests/latest", DockerPath("manifest", "app", "latest")),
        (f"app/manifests/{DIGEST}", DockerPath("manifest", "app", DIGEST)),
        (f"team/app/blobs/{DIGEST}", DockerPath("blob", "team/app", DIGEST)),
        ("team/app/blobs/uploads/", DockerPath("upload_start", "team/app")),
        ("team/app/blobs/uploads", DockerPath("upload_start", "team/app")),
        (f"app/blobs/uploads/{UPLOAD}", DockerPath("upload", "app", UPLOAD)),
        ("a/b/c/tags/list", DockerPath("tags", "a/b/c")),
        (f"app/referrers/{DIGEST}", DockerPath("referrers", "app", DIGEST)),
        # A name may contain the words a path is read by. It is read from its end.
        ("manifests/manifests/latest", DockerPath("manifest", "manifests", "latest")),
        ("blobs/tags/tags/list", DockerPath("tags", "blobs/tags")),
        ("tags/list/manifests/v1", DockerPath("manifest", "tags/list", "v1")),
        (f"a/blobs/uploads/blobs/{DIGEST}", DockerPath("blob", "a/blobs/uploads", DIGEST)),
    ],
)
def test_paths_are_classified(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "",
        "app",
        "app/",
        "manifests/latest",  # no image
        "/manifests/latest",
        "App/manifests/latest",
        "app/manifests/",
        "app/manifests/-bad",
        "app/manifests/a/b",
        "app/manifests/sha512:" + "a" * 128,
        "app/blobs/latest",
        "app/blobs/sha256:" + "A" * 64,
        f"app/blobs/{DIGEST}/extra",
        "app/blobs/uploads/not-an-upload",
        f"app/blobs/uploads/{UPLOAD}/more",
        "app/blobs/uploads/" + UPLOAD.upper(),
        "app/tags",
        "app/tags/list/",
        "tags/list",
        "app/referrers/latest",
        "../app/manifests/latest",
        "app/../manifests/latest",
    ],
)
def test_everything_else_is_other(path):
    assert classify(path).kind == "other"


def test_stored_paths():
    assert names.blob_path(DIGEST) == f"blobs/{DIGEST}"
    assert names.manifest_path("team/app", DIGEST) == f"manifests/team/app/{DIGEST}"
    assert names.tag_path("team/app", "v1") == "tags/team/app/v1"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tags/app/latest", ("app", "latest")),
        ("tags/team/app/v1.0", ("team/app", "v1.0")),
        ("tags/tags/tags", ("tags", "tags")),
        (f"manifests/app/{DIGEST}", None),
        (f"blobs/{DIGEST}", None),
        ("tags/app", None),
        ("tags/app/", None),
        ("tags/App/latest", None),
        ("tags/app/-bad", None),
        ("tags", None),
        ("", None),
    ],
)
def test_a_stored_tag_names_its_image(path, expected):
    assert names.tag_of(path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("manifests/app/sha256:" + "a" * 64, ("app", "sha256:" + "a" * 64)),
        ("manifests/team/app/sha256:" + "a" * 64, ("team/app", "sha256:" + "a" * 64)),
        ("manifests/team/app/latest", None),
        ("manifests/sha256:" + "a" * 64, None),
        ("manifests/Team/sha256:" + "a" * 64, None),
        ("tags/team/app/sha256:" + "a" * 64, None),
        ("blobs/sha256:" + "a" * 64, None),
    ],
)
def test_which_stored_paths_are_manifests_of_an_image(path, expected):
    assert names.manifest_of(path) == expected
