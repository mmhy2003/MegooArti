"""Merging members' `repodata/`: by `<package>` element, an earlier member's first."""

import bz2
import gzip
import hashlib
import lzma
import re
from xml.etree import ElementTree

import pytest
import zstandard

from megooarti.repositories.yum import merge
from tests.repositories.yum.packages import DATA

REPO = "{http://linux.duke.edu/metadata/repo}"
COMMON = "{http://linux.duke.edu/metadata/common}"
PACKERS = {
    "gz": lambda data: gzip.compress(data, mtime=0),
    "xz": lzma.compress,
    "zst": zstandard.ZstdCompressor().compress,
    "bz2": bz2.compress,
}


def text(name: str) -> bytes:
    return (DATA / name).read_bytes()


def packed(name: str, kind: str = "gz") -> tuple[str, bytes]:
    """A file createrepo_c wrote, packed as a member could have it, with its name."""
    return f"repodata/x-{name}.{kind}", PACKERS[kind](text(name))


def unpacked(merged: merge.Merged) -> bytes:
    return zstandard.ZstdDecompressor().decompressobj().decompress(merged.packed)


def element(name: str, version: str = "1.0", pkgid: str = "a" * 64, href: str = "") -> bytes:
    """A package of a `primary.xml`, as createrepo_c writes one, cut to what is read."""
    return (
        f'<package type="rpm">\n  <name>{name}</name>\n  <arch>noarch</arch>\n'
        f'  <version epoch="0" ver="{version}" rel="1"/>\n'
        f'  <checksum type="sha256" pkgid="YES">{pkgid}</checksum>\n'
        f'  <location href="{href or name + ".rpm"}"/>\n</package>'
    ).encode()


def primary(*elements: bytes) -> tuple[str, bytes]:
    head = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n<metadata xmlns="http://linux.duke.edu/'
        b'metadata/common" xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="9">\n'
    )
    return "repodata/p-primary.xml.gz", gzip.compress(
        head + b"\n".join(elements) + b"\n</metadata>", mtime=0
    )


def test_a_repomd_says_each_file_it_names_and_its_checksum():
    said = merge.parse_repomd(text("rocky-10-baseos-repomd.xml"))

    assert list(said.data)[:3] == ["primary", "filelists", "other"]
    assert {"group", "group_xz", "updateinfo", "primary_db"} <= set(said.data)
    primary_data = said.data["primary"]
    assert primary_data.href.startswith("repodata/") and primary_data.href.endswith(
        "-primary.xml.gz"
    )
    assert (primary_data.checksum_type, len(primary_data.checksum)) == ("sha256", 64)
    assert primary_data.element.startswith(b'<data type="primary">')
    assert primary_data.element.endswith(b"</data>")
    assert said.revision == "10.2"  # Rocky says its release, not a time
    assert said.moment == 1791964571  # the newest of its files


@pytest.mark.parametrize(
    "text",
    [
        b"not xml",
        b"<other/>",
        b'<repomd xmlns="http://linux.duke.edu/metadata/repo"><data type="primary"/></repomd>',
    ],
)
def test_what_is_not_a_repomd_that_can_be_read_is_refused(text):
    with pytest.raises(merge.InvalidMetadata):
        merge.parse_repomd(text)


def test_a_file_is_checked_against_the_checksum_its_repomd_names():
    data = merge.Data(
        "primary", "repodata/p.xml.gz", "sha256", hashlib.sha256(b"x").hexdigest(), b""
    )

    merge.check(data, b"x")
    with pytest.raises(merge.InvalidMetadata, match="not the one its repomd.xml names"):
        merge.check(data, b"y")
    with pytest.raises(merge.InvalidMetadata, match="unknown kind"):
        merge.check(merge.Data("primary", "p", "md5", "x", b""), b"x")


@pytest.mark.parametrize("kind", sorted(PACKERS))
def test_a_file_is_unpacked_however_it_was_packed(kind):
    href, data = packed("createrepo-primary.xml", kind)

    assert b"".join(merge.unpacked(href, data)) == text("createrepo-primary.xml")


def test_a_file_larger_unpacked_than_the_bound_or_broken_is_refused():
    href, data = packed("createrepo-filelists.xml")

    with pytest.raises(merge.InvalidMetadata, match="larger than"):
        list(merge.unpacked(href, data, most=100))
    with pytest.raises(merge.InvalidMetadata, match="cannot be unpacked"):
        list(merge.unpacked(href, data[:20] + b"\xff" * 50))
    with pytest.raises(merge.InvalidMetadata, match="packed in a way"):
        list(merge.unpacked("repodata/x-primary.xml.lz4", data))


def test_package_elements_are_found_whatever_pieces_the_text_comes_in():
    whole = text("real-createrepo-primary.xml")
    expected = re.findall(rb"<package .*?</package>", whole, re.DOTALL)

    for size in (1, 7, 100, len(whole)):
        pieces = [whole[at : at + size] for at in range(0, len(whole), size)]
        assert list(merge.packages(pieces)) == expected


@pytest.mark.parametrize("kind", merge.KINDS)
@pytest.mark.parametrize("prefix", ["createrepo", "real-createrepo", "empty-createrepo"])
def test_one_members_files_merged_alone_are_what_createrepo_c_wrote(prefix, kind):
    members = [packed(f"{prefix}-{kind}.xml")]
    kept = merge.kept([packed(f"{prefix}-primary.xml")])

    merged = merge.merged(kind, members, kept)

    assert unpacked(merged) == text(f"{prefix}-{kind}.xml")
    assert merged.open_checksum == hashlib.sha256(text(f"{prefix}-{kind}.xml")).hexdigest()
    assert merged.open_size == len(text(f"{prefix}-{kind}.xml"))
    assert merged.name == f"{hashlib.sha256(merged.packed).hexdigest()}-{kind}.xml.zst"


def test_two_members_files_are_merged_the_earlier_first():
    kept = merge.kept([packed("real-createrepo-primary.xml"), packed("createrepo-primary.xml")])

    merged = {
        kind: unpacked(
            merge.merged(
                kind,
                [packed(f"real-createrepo-{kind}.xml"), packed(f"createrepo-{kind}.xml")],
                kept,
            )
        )
        for kind in merge.KINDS
    }

    names = [p.findtext(f"{COMMON}name") for p in ElementTree.fromstring(merged["primary"])]
    assert names == ["bash", "setup", "megooarti-hello", "megooarti-tool"]
    assert b'packages="4"' in merged["primary"]
    for kind in ("filelists", "other"):
        tree = ElementTree.fromstring(merged[kind])
        assert [package.get("name") for package in tree] == names


def test_a_package_an_earlier_member_has_is_left_out_of_a_later_ones():
    first = primary(element("hello", pkgid="1" * 64), element("tool", pkgid="2" * 64))
    later = primary(
        element("hello", pkgid="3" * 64, href="other/hello.rpm"),  # the same package
        element("hello", "2.0", pkgid="4" * 64, href="hello-2.rpm"),  # another version
        element("other", pkgid="5" * 64, href="tool.rpm"),  # at the earlier's tool's path
        element("again", pkgid="6" * 64),
        element("again", pkgid="6" * 64),  # twice in one member
    )

    assert merge.kept([first, later]) == [{b"1" * 64, b"2" * 64}, {b"4" * 64, b"6" * 64}]


def test_a_member_whose_primary_cannot_be_read_is_named():
    broken = primary(b'<package type="rpm"><name>x</name></package>')

    with pytest.raises(merge.InvalidMetadata) as raised:
        merge.kept([primary(element("hello")), broken])

    assert raised.value.args[1] == 1


def test_the_groups_repomd_names_what_it_wrote_and_what_it_passes_on():
    kept = merge.kept([packed("createrepo-primary.xml")])
    parts = [merge.merged(kind, [packed(f"createrepo-{kind}.xml")], kept) for kind in merge.KINDS]
    comps = merge.parse_repomd(text("rocky-10-baseos-repomd.xml")).data["group"]

    written = merge.repomd("1792005637", parts, [comps])

    tree = ElementTree.fromstring(written)
    assert tree.findtext(f"{REPO}revision") == "1792005637"
    data = {node.get("type"): node for node in tree.iter(f"{REPO}data")}
    assert list(data) == ["primary", "filelists", "other", "group"]
    for part in parts:
        node = data[part.kind]
        assert node.find(f"{REPO}location").get("href") == f"repodata/{part.name}"
        assert node.findtext(f"{REPO}checksum") == hashlib.sha256(part.packed).hexdigest()
        assert node.findtext(f"{REPO}open-checksum") == part.open_checksum
        assert node.findtext(f"{REPO}size") == str(len(part.packed))
    assert comps.element in written


@pytest.mark.parametrize("kind", sorted(PACKERS))
def test_a_file_packed_in_several_streams_is_unpacked_whole(kind):
    first, second = text("createrepo-primary.xml"), text("real-createrepo-primary.xml")
    data = PACKERS[kind](first) + PACKERS[kind](second)

    assert b"".join(merge.unpacked(f"repodata/x.xml.{kind}", data)) == first + second


@pytest.mark.parametrize("kind", ["bz2", "xz", "gz"])
def test_a_file_that_ends_inside_a_stream_is_refused(kind):
    data = PACKERS[kind](text("createrepo-primary.xml"))

    with pytest.raises(merge.InvalidMetadata):
        list(merge.unpacked(f"repodata/x.xml.{kind}", data[: len(data) // 2]))
