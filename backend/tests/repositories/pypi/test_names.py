import pytest

from megooarti.repositories.pypi import names
from megooarti.repositories.pypi.names import PypiPath, classify, version_of


@pytest.mark.parametrize(
    ("written", "normal"),
    [
        ("requests", "requests"),
        ("Django", "django"),
        ("zope.interface", "zope-interface"),
        ("typing_extensions", "typing-extensions"),
        ("A__weird.-_Name", "a-weird-name"),
    ],
)
def test_a_name_has_one_normal_form(written, normal):
    assert names.normalise(written) == normal
    assert names.normalise(normal) == normal


@pytest.mark.parametrize("name", ["requests", "Django", "zope.interface", "a", "A1", "x-y_z.0"])
def test_valid_names(name):
    assert names.is_valid_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-leading",
        "trailing-",
        ".hidden",
        "has space",
        "sl/ash",
        "ünïcode",
        "a" * 129,
        "..",
        "a@b",
    ],
)
def test_invalid_names(name):
    assert not names.is_valid_name(name)


@pytest.mark.parametrize(
    "segment", ["1.0", "1!2.0", "1.0+local.1", "pkg-1.0-py3-none-any.whl", "2.0.0a1", "a_b"]
)
def test_valid_versions_and_file_names(segment):
    assert names.is_valid_segment(segment)


@pytest.mark.parametrize("segment", ["", ".", "..", "a/b", "a b", "a%2fb", "a\\b", "x" * 256, "é"])
def test_invalid_versions_and_file_names(segment):
    assert not names.is_valid_segment(segment)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", PypiPath("repository")),
        ("simple", PypiPath("index")),
        ("simple/", PypiPath("index", slash=True)),
        ("simple/requests/", PypiPath("page", project="requests", slash=True)),
        ("simple/Zope.Interface", PypiPath("page", project="Zope.Interface")),
        (
            "packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl",
            PypiPath(
                "file",
                project="requests",
                version="2.31.0",
                filename="requests-2.31.0-py3-none-any.whl",
            ),
        ),
        (
            "packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl.metadata",
            PypiPath(
                "metadata",
                project="requests",
                version="2.31.0",
                filename="requests-2.31.0-py3-none-any.whl",
            ),
        ),
        (
            "packages/zope-interface/1!6.0+local/zope.interface-6.0.tar.gz",
            PypiPath(
                "file",
                project="zope-interface",
                version="1!6.0+local",
                filename="zope.interface-6.0.tar.gz",
            ),
        ),
    ],
)
def test_paths_are_classified(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "simple/-bad-",
        "simple/requests/extra",
        "simple//",
        "packages",
        "packages/requests",
        "packages/requests/2.31.0",
        "packages/Requests/2.31.0/requests-2.31.0.tar.gz",  # not the normal form
        "packages/zope.interface/6.0/zope.interface-6.0.tar.gz",
        "packages/requests/../requests-2.31.0.tar.gz",
        "packages/requests/2.31.0/requests-2.31.0.tar.gz/",
        "packages/requests/2.31.0/requests-2.31.0.tar.gz/more",
        "packages/requests/2.31.0/.metadata",
        "pypi/requests/json",
        "simple/requests/index.html",
    ],
)
def test_everything_else_is_other(path):
    assert classify(path).kind == "other"


@pytest.mark.parametrize(
    ("project", "filename", "version"),
    [
        ("requests", "requests-2.31.0-py3-none-any.whl", "2.31.0"),
        ("requests", "requests-2.31.0.tar.gz", "2.31.0"),
        ("zope-interface", "zope.interface-6.0-cp312-cp312-manylinux_2_17_x86_64.whl", "6.0"),
        ("zope-interface", "zope_interface-6.0.tar.gz", "6.0"),
        ("typing-extensions", "typing_extensions-4.9.0-py3-none-any.whl", "4.9.0"),
        ("some-pkg", "some_pkg-1.0-1-py3-none-any.whl", "1.0"),  # with a build number
        ("my-package", "my-package-1.0.tar.gz", "1.0"),  # an old name with a hyphen
        ("my-package", "My.Package-1.0.zip", "1.0"),
        ("pyyaml", "PyYAML-3.10.tar.bz2", "3.10"),
        ("pkg", "pkg-1.0+local.tgz", "1.0+local"),
        ("pkg", "pkg-1.0.tar.xz", "1.0"),
        ("pkg", "pkg-1.0-py2.7.egg", "1.0"),
        ("pkg", "pkg-1.0.win32-py2.7.exe", "1.0.win32"),
        ("a-b", "a-b-c-1.0.tar.gz", "c-1.0"),  # the name is the project's, the rest is not ours
    ],
)
def test_the_version_is_read_from_the_file_name(project, filename, version):
    assert version_of(project, filename) == version


@pytest.mark.parametrize(
    ("project", "filename"),
    [
        ("requests", "urllib3-2.0.0-py3-none-any.whl"),
        ("requests", "urllib3-2.0.0.tar.gz"),
        ("requests", "requests-2.31.0-py3-none.whl"),  # too few parts for a wheel
        ("requests", "requests-2.31.0-1-py3-none-any-extra.whl"),
        ("requests", "requests--py3-none-any.whl"),
        ("requests", "requests.tar.gz"),
        ("requests", "requests-.tar.gz"),
        ("requests", "requests-2.31.0.txt"),
        ("requests", "requests-2.31.0"),
        ("requests", "-2.31.0.tar.gz"),
        ("requests", ""),
        # A version that could not be one segment of a path is no version.
        ("pkg", "pkg-..tar.gz"),
        ("pkg", "pkg-..zip"),
        ("pkg", "pkg-..-py3-none-any.whl"),
    ],
)
def test_a_file_that_does_not_fit_its_project_has_no_version(project, filename):
    assert version_of(project, filename) is None


def test_stored_paths():
    assert names.file_path("requests", "2.31.0", "requests-2.31.0.tar.gz") == (
        "packages/requests/2.31.0/requests-2.31.0.tar.gz"
    )
    assert classify(names.file_path("requests", "2.31.0", "requests-2.31.0.tar.gz")).kind == "file"
    assert names.page_path("requests") == "simple/requests"
    assert classify(names.page_path("requests")) == PypiPath("page", project="requests")


@pytest.mark.parametrize(
    ("filename", "named"),
    [
        ("greeter-1.0-py3-none-any.whl", ("greeter", "1.0")),
        ("My_Package-2.0.post1-7-cp313-cp313-win_amd64.whl", ("My_Package", "2.0.post1")),
        ("greeter-1.0.tar.gz", ("greeter", "1.0")),
        ("my-package-1.0rc1.tar.gz", ("my-package", "1.0rc1")),
        ("my_package-2!1.0+local.zip", ("my_package", "2!1.0+local")),
        ("greeter.tar.gz", None),
        ("-1.0.tar.gz", None),
        ("greeter-.tar.gz", None),
        ("greeter-1.0-py3-none.whl", None),
        ("greeter-1.0.tar.bz2", None),
        ("greeter-1.0.egg", None),
        ("notes.txt", None),
        ("", None),
    ],
)
def test_a_files_name_says_its_project_and_version(filename, named):
    assert names.named(filename) == named
