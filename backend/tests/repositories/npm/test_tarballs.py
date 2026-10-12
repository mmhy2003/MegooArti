"""Reading a package's manifest out of its tarball."""

import gzip
import json
import tarfile

import pytest

from megooarti.repositories.npm import documents, tarballs
from megooarti.repositories.npm.documents import InvalidPackage
from tests.repositories.npm.conftest import packed

TOOL = {"name": "tool", "version": "1.0.0", "description": "A tool"}


def test_the_manifest_is_the_package_json_in_the_tarballs_folder():
    data = packed({"package/package.json": TOOL, "package/index.js": b"module.exports = 1"})

    assert tarballs.manifest(data) == TOOL


@pytest.mark.parametrize(
    "name", ["package/package.json", "./package/package.json", "tool-1.0.0/package.json"]
)
def test_the_folder_may_have_any_name(name):
    assert tarballs.manifest(packed({name: TOOL})) == TOOL


def test_a_package_json_deeper_down_is_some_other_packages():
    data = packed(
        {
            "package/node_modules/dep/package.json": {"name": "dep", "version": "9.9.9"},
            "package/package.json": TOOL,
        }
    )
    without = packed({"package/lib/package.json": TOOL, "package.json": TOOL})

    assert tarballs.manifest(data) == TOOL
    with pytest.raises(InvalidPackage, match="has no package.json"):
        tarballs.manifest(without)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"this is not a tarball at all",
        gzip.compress(b"compressed, and still not a tarball"),
        packed({"package/package.json": TOOL})[:-20],
        packed({"package/package.json": TOOL})[:60],
    ],
    ids=["empty", "text", "gzip-of-text", "cut-short", "cut-early"],
)
def test_what_is_not_a_tarball_is_refused(data):
    with pytest.raises(InvalidPackage, match="not a package tarball|has no package.json"):
        tarballs.manifest(data)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"{not json", "its package.json is not JSON"),
        (b'["a", "list"]', "its package.json is not an object"),
        (b'{"name": "a\\u0000b"}', "NUL"),
        (json.dumps({"readme": "x" * documents.MAX_MANIFEST_BYTES}).encode(), "larger than 1 MiB"),
    ],
    ids=["broken", "list", "nul", "huge"],
)
def test_a_manifest_that_cannot_be_kept_is_refused(content, reason):
    with pytest.raises(InvalidPackage, match=reason):
        tarballs.manifest(packed({"package/package.json": content}))


def test_no_more_than_a_set_amount_is_unpacked_to_find_the_manifest():
    # A megabyte of zeros is a kilobyte to send, and whoever sends it can send a gigabyte.
    data = packed({"package/padding.bin": bytes(1024 * 1024), "package/package.json": TOOL})

    assert len(data) < 10_000
    assert tarballs.manifest(data) == TOOL
    with pytest.raises(InvalidPackage, match="not near the start"):
        tarballs.manifest(data, scan_limit=100_000)


def test_a_link_named_as_the_manifest_is_not_read():
    data = packed({"package/package.json": "-> /etc/passwd"})

    with pytest.raises(InvalidPackage, match="has no package.json"):
        tarballs.manifest(data)


def test_a_tarball_of_very_many_files_is_not_walked_to_its_end():
    """Half a million empty files are three megabytes to send."""
    members = {f"package/empty-{number}": b"" for number in range(300)}
    data = packed({**members, "package/package.json": TOOL})

    assert tarballs.manifest(data) == TOOL
    with pytest.raises(InvalidPackage, match="more than 100 files"):
        tarballs.manifest(data, max_members=100)


def test_a_header_larger_than_any_name_is_not_read():
    """An extended header says how long it is, and what reads it whole holds all of it."""
    data = packed({"package/package.json": TOOL}, pax={"comment": "x" * 2_000_000})

    assert len(data) < 20_000
    with pytest.raises(InvalidPackage, match="header"):
        tarballs.manifest(data)


@pytest.mark.parametrize(
    ("folder", "format"),
    [
        ("pâckage", tarfile.PAX_FORMAT),  # its name is in an extended header
        ("f" * 120, tarfile.PAX_FORMAT),
        ("f" * 120, tarfile.GNU_FORMAT),  # in a member of its own, before it
        ("f" * 120, tarfile.USTAR_FORMAT),  # in two fields of the header
        ("package", tarfile.USTAR_FORMAT),
        ("package", tarfile.GNU_FORMAT),
    ],
    ids=["pax", "pax-long", "gnu-long", "ustar-prefix", "ustar", "gnu"],
)
def test_a_name_is_read_however_the_archive_writes_it(folder, format):
    data = packed({f"{folder}/README.md": b"# Tool", f"{folder}/package.json": TOOL}, format=format)

    assert tarballs.manifest(data) == TOOL


def test_a_small_extended_header_is_passed_over():
    data = packed({"package/package.json": TOOL}, pax={"comment": "built on a Tuesday"})

    assert tarballs.manifest(data) == TOOL


def test_a_header_that_is_not_one_ends_the_reading():
    whole = gzip.decompress(packed({"package/a.txt": b"a", "package/package.json": TOOL}))
    broken = bytearray(whole)
    broken[512 * 2 + 10] ^= 0xFF  # a byte of the second header: its checksum is now wrong

    with pytest.raises(InvalidPackage, match="not a package tarball"):
        tarballs.manifest(gzip.compress(bytes(broken)))
