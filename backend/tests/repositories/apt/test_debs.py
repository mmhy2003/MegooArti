import gzip

import pytest

from megooarti.repositories.apt import control, debs
from tests.repositories.apt.packages import (
    DATA,
    REAL,
    ar,
    compressed,
    control_text,
    make_deb,
    pieces,
    tar_of,
)


def scanned() -> dict[str, control.Paragraph]:
    """The paragraphs dpkg-scanpackages wrote, by file name."""
    text = (DATA / "Packages.scanned").read_text(encoding="utf-8")
    paragraphs = [control.parse(part) for part in text.split("\n\n") if part.strip()]
    return {
        control.get(paragraph, "Filename").removeprefix("./"): paragraph for paragraph in paragraphs
    }


@pytest.mark.parametrize("compression", sorted(REAL))
async def test_a_package_dpkg_deb_wrote_says_what_dpkg_scanpackages_read_of_it(compression):
    filename = REAL[compression]
    expected = scanned()[filename.replace("2.0~rc1-1", "1:2.0~rc1-1")]

    deb = await debs.read(pieces((DATA / filename).read_bytes(), size=100))

    without_index = [field for field in expected if field[0].lower() not in debs.INDEX_FIELDS]
    assert sorted(deb.control) == sorted(without_index)
    assert (deb.package, deb.version) == (
        control.get(expected, "Package"),
        control.get(expected, "Version"),
    )
    assert deb.architecture == control.get(expected, "Architecture")


@pytest.mark.parametrize("compression", ["gz", "xz", "zst", "none"])
async def test_each_control_archive_dpkg_writes_is_read(compression):
    deb = await debs.read(pieces(make_deb(compression=compression)))

    assert (deb.package, deb.version, deb.architecture) == ("megooarti-hello", "1.0-1", "all")


async def test_a_member_for_tools_before_the_control_archive_is_passed_over():
    package = make_deb(before_control=[("_gpgorigin", b"a signature")])

    assert (await debs.read(pieces(package))).package == "megooarti-hello"


async def test_what_an_index_says_of_a_file_is_not_taken_from_the_package():
    text = control_text(extra="Filename: ../../../etc/passwd\nSize: 1\nSHA256: 00\n")

    deb = await debs.read(pieces(make_deb(text)))

    assert [name for name, _ in deb.control] == [
        "Package",
        "Version",
        "Architecture",
        "Maintainer",
        "Installed-Size",
        "Description",
    ]


async def test_the_files_of_a_package_are_not_read():
    package = make_deb()
    control_end = package.index(b"data.tar.xz")

    async def until_the_files() -> object:
        yield package[:control_end]
        raise AssertionError("the files were read")

    assert (await debs.read(until_the_files())).package == "megooarti-hello"


def broken_control(text: str) -> bytes:
    return make_deb(text)


@pytest.mark.parametrize(
    ("package", "said"),
    [
        (b"PK\x03\x04 a zip file", "not an ar archive"),
        (b"", "ends early"),
        (make_deb()[:70], "ends early"),
        (ar([("control.tar.gz", b"x")]), "does not begin with debian-binary"),
        (ar([("debian-binary", b"3.0\n")]), "not in the format dpkg 2 writes"),
        (
            ar([("debian-binary", b"2.0\n"), ("data.tar.xz", b"files")]),
            "second member is not the control archive",
        ),
        (
            ar([("debian-binary", b"2.0\n"), ("control.tar.bz2", b"x")]),
            "not one dpkg writes",
        ),
        (
            ar([("debian-binary", b"2.0\n"), ("control.tar.gz", b"not gzip")]),
            "cannot be unpacked",
        ),
        (
            ar([("debian-binary", b"2.0\n"), ("control.tar", tar_of({"./md5sums": b"x"}))]),
            "has no control file",
        ),
        (broken_control("Version: 1.0\nArchitecture: all\n"), "has no Package"),
        (broken_control(control_text(package="Hello")), "not a Debian package name"),
        (broken_control(control_text(version="one")), "not a Debian version"),
        (broken_control(control_text(architecture="any")), "not an architecture"),
        (broken_control(control_text(architecture="x86/64")), "not an architecture"),
        (broken_control("Package: a\n\nPackage: b\n"), "control file is not valid"),
    ],
    ids=lambda value: value if isinstance(value, str) else "package",
)
async def test_what_is_not_a_package_dpkg_could_install_is_refused(package, said):
    with pytest.raises(debs.InvalidPackage, match=said):
        await debs.read(pieces(package))


async def test_a_control_archive_larger_than_is_read_is_refused_before_it_is_read():
    header = f"{'control.tar':<16}{0:<12}{0:<6}{0:<6}{100644:<8}{debs.CONTROL_MOST + 1:<10}`\n"
    package = ar([("debian-binary", b"2.0\n")]) + header.encode()

    with pytest.raises(debs.InvalidPackage, match="larger than this server reads"):
        await debs.read(pieces(package, size=4096))


async def test_a_control_archive_that_unpacks_to_more_than_is_read_is_refused():
    name, packed = "control.tar.gz", gzip.compress(bytes(debs.CONTROL_MOST + 1))
    package = ar([("debian-binary", b"2.0\n"), (name, packed)])

    with pytest.raises(debs.InvalidPackage, match="larger than this server reads"):
        await debs.read(pieces(package, size=65536))


@pytest.mark.parametrize("compression", ["xz", "zst"])
async def test_the_bound_holds_whatever_the_compression(compression):
    name, packed = compressed(bytes(debs.CONTROL_MOST + 1), compression)
    package = ar([("debian-binary", b"2.0\n"), (name, packed)])

    with pytest.raises(debs.InvalidPackage, match="larger than this server reads"):
        await debs.read(pieces(package, size=65536))
