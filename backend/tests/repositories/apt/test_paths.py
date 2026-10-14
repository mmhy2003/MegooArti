import pytest

from megooarti.repositories.apt import paths
from megooarti.repositories.apt.paths import AptPath


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("", AptPath("upload")),
        ("public.key", AptPath("key")),
        ("dists/stable/InRelease", AptPath("release", suite="stable", filename="InRelease")),
        ("dists/stable/Release.gpg", AptPath("release", suite="stable", filename="Release.gpg")),
        (
            "dists/stable/main/binary-amd64/Packages.xz",
            AptPath(
                "packages",
                suite="stable",
                filename="Packages.xz",
                component="main",
                architecture="amd64",
            ),
        ),
        ("dists/stable/main/i18n/Translation-en", AptPath("dists")),
        ("dists/stable/main/binary-amd64/by-hash/SHA256/ab12", AptPath("dists")),
        ("pool/main/h/hello/hello_1.0_all.deb", AptPath("pool")),
        ("pool/main/h/hello/hello_1.0.dsc", AptPath("other")),
        ("README", AptPath("other")),
    ],
)
def test_each_path_of_the_layout_is_known(path, kind):
    assert paths.classify(path) == kind


@pytest.mark.parametrize(
    ("package", "version", "architecture", "path"),
    [
        ("hello", "1.0-1", "all", "pool/main/h/hello/hello_1.0-1_all.deb"),
        ("hello", "1:2.0~rc1-1", "amd64", "pool/main/h/hello/hello_2.0~rc1-1_amd64.deb"),
        ("libssl3", "3.0.2", "arm64", "pool/main/libs/libssl3/libssl3_3.0.2_arm64.deb"),
        ("lib", "1.0", "all", "pool/main/l/lib/lib_1.0_all.deb"),
    ],
)
def test_a_package_is_kept_where_debian_keeps_it(package, version, architecture, path):
    assert paths.pool_path(package, version, architecture) == path
    assert paths.in_pool(path) == (package, version.partition(":")[2] or version, architecture)


def test_a_mirrors_package_is_read_by_its_file_name_whatever_its_directory():
    path = "pool/main/g/glibc/libc6_2.41-6_amd64.deb"

    assert paths.in_pool(path) == ("libc6", "2.41-6", "amd64")


@pytest.mark.parametrize(
    "path",
    [
        "pool/main/h/hello/hello_1.0.deb",
        "pool/main/h/hello/hello_1.0_all_x.deb",
        "pool/main/h/hello/hello__all.deb",
        "pool/main/h/hello/hello_1.0_all.dsc",
        "dists/hello_1.0_all.deb",
    ],
)
def test_a_file_name_that_is_not_a_packages_names_no_package(path):
    assert paths.in_pool(path) is None


@pytest.mark.parametrize(
    ("suite", "valid"), [("stable", True), ("noble-updates", True), ("a/b", False)]
)
def test_a_suite_is_one_part_of_a_path(suite, valid):
    assert (paths.SUITE.fullmatch(suite) is not None) is valid
