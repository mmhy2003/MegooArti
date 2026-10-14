"""What a path of a YUM repository is, at each depth of its metadata."""

import pytest

from megooarti.repositories.yum import paths
from megooarti.repositories.yum.paths import YumPath

SHA = "d247fdcb83b1e1509c815bdceafa7ec1311a4583562b2678bfb25a51db0be4b2"


@pytest.mark.parametrize(
    ("path", "depth", "classified"),
    [
        ("public.key", 0, YumPath("key")),
        ("repodata/repomd.xml", 0, YumPath("repodata", "", "repomd.xml")),
        (
            "el9/x86_64/repodata/repomd.xml.asc",
            2,
            YumPath("repodata", "el9/x86_64", "repomd.xml.asc"),
        ),
        (f"repodata/{SHA}-primary.xml.gz", 0, YumPath("repodata", "", f"{SHA}-primary.xml.gz")),
        ("hello-1.0-1.noarch.rpm", 0, YumPath("package", "", "hello-1.0-1.noarch.rpm")),
        ("el9/x86_64/Packages/h/hello.rpm", 2, YumPath("package", "el9/x86_64", "hello.rpm")),
        ("el9/hello.rpm", 2, YumPath("package", "", "hello.rpm")),  # not deep enough
        ("repodata/hello.rpm", 0, YumPath("repodata", "", "hello.rpm")),
        ("repodata/a/b.xml", 0, YumPath("other")),
        ("README", 0, YumPath("other")),
    ],
)
def test_a_path_is_a_key_metadata_a_package_or_something_else(path, depth, classified):
    assert paths.classify(path, depth) == classified


@pytest.mark.parametrize(
    ("path", "depth", "directory"),
    [
        ("hello.rpm", 0, ""),
        ("el9/x86_64/hello.rpm", 0, ""),
        ("el9/x86_64/hello.rpm", 2, "el9/x86_64"),
        ("el9/x86_64/Packages/hello.rpm", 2, "el9/x86_64"),
        ("el9/hello.rpm", 2, None),
        ("hello.rpm", 1, None),
    ],
)
def test_a_package_is_listed_by_the_directory_as_deep_as_the_metadata(path, depth, directory):
    assert paths.directory_of(path, depth) == directory


@pytest.mark.parametrize(
    ("directory", "depth", "has"),
    [
        ("", 0, True),
        ("", 2, False),
        ("el9", 2, False),
        ("el9/x86_64", 2, True),
        ("a/b/c", 2, False),
    ],
)
def test_metadata_is_in_the_directories_exactly_as_deep_as_the_depth(directory, depth, has):
    assert paths.at_depth(directory, depth) is has


@pytest.mark.parametrize(
    ("path", "named"),
    [
        ("Packages/b/bash-5.3.9-3.fc44.x86_64.rpm", ("bash", "5.3.9-3.fc44", "x86_64")),
        ("python3-libs-3.14.0-1.fc44.x86_64.rpm", ("python3-libs", "3.14.0-1.fc44", "x86_64")),
        ("hello.rpm", None),
        ("hello-1.0.noarch.rpm", None),
        ("repodata/repomd.xml", None),
    ],
)
def test_a_package_files_name_says_its_name_version_and_architecture(path, named):
    assert paths.named(path) == named


@pytest.mark.parametrize(
    ("filename", "hashed"),
    [(f"{SHA}-primary.xml.gz", True), ("repomd.xml", False), ("primary.xml.gz", False)],
)
def test_a_file_named_by_its_hash_is_told_apart(filename, hashed):
    assert paths.hashed(filename) is hashed
