"""What a path of an apk repository is."""

import pytest

from megooarti.repositories.apk import paths
from megooarti.repositories.apk.paths import ApkPath


@pytest.mark.parametrize(
    ("path", "classified"),
    [
        ("megooarti-apk-hosted.rsa.pub", ApkPath("key", filename="megooarti-apk-hosted.rsa.pub")),
        (
            "v3.24/main/x86_64/APKINDEX.tar.gz",
            ApkPath("index", "v3.24/main/x86_64", "APKINDEX.tar.gz"),
        ),
        ("APKINDEX.tar.gz", ApkPath("index", "", "APKINDEX.tar.gz")),
        ("v3.24/main/x86_64/a-1.0-r0.apk", ApkPath("package", "v3.24/main/x86_64", "a-1.0-r0.apk")),
        ("a-1.0-r0.apk", ApkPath("other", "", "a-1.0-r0.apk")),
        ("megooarti-other.rsa.pub", ApkPath("other", "", "megooarti-other.rsa.pub")),
        ("v3.24/README", ApkPath("other", "v3.24", "README")),
    ],
)
def test_a_path_is_a_key_an_index_a_package_or_something_else(path, classified):
    assert paths.classify(path, "apk-hosted") == classified


def test_a_directorys_architecture_is_its_last_part():
    assert paths.classify("v3.24/main/aarch64/APKINDEX.tar.gz", "r").architecture == "aarch64"


@pytest.mark.parametrize(
    ("path", "named"),
    [
        ("v3.24/main/x86_64/yash-binsh-2.60-r0.apk", ("yash-binsh", "2.60-r0")),
        ("x86_64/megooarti-tool-0.3_rc1-r2.apk", ("megooarti-tool", "0.3_rc1-r2")),
        ("x86_64/hello.apk", None),
        ("x86_64/hello-1.0.apk", None),
        ("x86_64/APKINDEX.tar.gz", None),
    ],
)
def test_a_package_files_name_says_its_name_and_version(path, named):
    assert paths.named(path) == named
