import gzip
import lzma

import pytest

from megooarti.repositories.apt import merge


def paragraph(name: str, version: str, architecture: str = "amd64", file: str = "x") -> bytes:
    return (
        f"Package: {name}\nVersion: {version}\nArchitecture: {architecture}\n"
        f"Filename: pool/{file}.deb\nDescription: d\n continued\n"
    ).encode()


def packages(*paragraphs: bytes) -> bytes:
    return b"".join(one + b"\n" for one in paragraphs)


@pytest.mark.parametrize(
    ("name", "pack"),
    [
        ("Packages", lambda text: text),
        ("Packages.gz", gzip.compress),
        ("Packages.xz", lzma.compress),
    ],
)
def test_each_variant_of_packages_is_unpacked(name, pack):
    text = packages(paragraph("a", "1"))

    assert merge.unpacked(name, pack(text)) == text


@pytest.mark.parametrize(
    ("name", "pack"), [("Packages.gz", gzip.compress), ("Packages.xz", lzma.compress)]
)
def test_what_unpacks_to_more_than_is_read_is_refused(name, pack):
    with pytest.raises(merge.InvalidIndex, match="larger than this server reads"):
        merge.unpacked(name, pack(bytes(1001)), most=1000)


def test_what_is_not_packed_as_its_name_says_is_refused():
    with pytest.raises(merge.InvalidIndex, match="cannot be unpacked"):
        merge.unpacked("Packages.xz", b"plain text")


def test_packages_are_merged_in_order_and_a_package_an_earlier_one_has_is_left_out():
    ours = packages(paragraph("hello", "1.0", file="ours"), paragraph("tool", "2"))
    theirs = packages(
        paragraph("hello", "1.0", file="theirs"),
        paragraph("hello", "1.0", "arm64", file="theirs-arm"),
        paragraph("libc6", "2.41"),
    )

    text = merge.merged([ours, theirs])

    assert text.count(b"Package: ") == 4
    assert b"pool/ours.deb" in text and b"pool/theirs.deb" not in text
    assert b"pool/theirs-arm.deb" in text
    assert text.index(b"Package: tool") < text.index(b"Package: libc6")
    assert text.endswith(b"continued\n\n")


def test_a_paragraph_that_does_not_say_which_package_it_is_is_left_out():
    text = merge.merged([b"Package: a\nVersion: 1\n\nPackage: b\nVersion: 1\nArchitecture: all\n"])

    assert text == b"Package: b\nVersion: 1\nArchitecture: all\n\n"


def test_a_field_is_only_found_at_the_start_of_a_line():
    tricky = b"Package: a\nVersion: 1\nArchitecture: all\nDescription: x\n Package: b\n"

    assert (
        merge.merged([tricky, b"Package: b\nVersion: 1\nArchitecture: all\n"]).count(
            b"Package: b\nVersion"
        )
        == 1
    )
