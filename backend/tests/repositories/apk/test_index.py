"""A directory's `APKINDEX.tar.gz`, written as apk-tools 3's `apk index` writes it."""

import gzip
import io
import tarfile
import zlib

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from megooarti.repositories import signing
from megooarti.repositories.apk import index, packages
from tests.repositories.apk.packages import DATA, HELLO, REAL, TOOL, make_apk, pieces, pkginfo


def tarfile_of(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


def streams(data: bytes) -> list[tuple[bytes, bytes]]:
    """A file's gzip streams, each as it is packed and as it unpacks."""
    found, at = [], 0
    while at < len(data):
        unpack = zlib.decompressobj(wbits=31)
        opened = unpack.decompress(data[at:])
        used = len(data) - at - len(unpack.unused_data)
        found.append((data[at : at + used], opened))
        at += used
    return found


def members(opened: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(opened + b"\0" * 1024)) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def apkindex(data: bytes) -> str:
    return members(streams(data)[1][1])["APKINDEX"].decode()


async def listed(name: str) -> index.Listed:
    data = (DATA / name).read_bytes()
    return index.Listed(len(data), await packages.read(pieces(data)))


async def test_the_records_of_our_packages_are_what_apk_index_wrote():
    written = index.apkindex([await listed(HELLO), await listed(TOOL)], "x86_64")

    assert written == apkindex((DATA / "APKINDEX.tar.gz").read_bytes())


async def test_the_records_of_alpines_packages_are_what_its_index_says():
    written = index.apkindex([await listed(name) for name in REAL], "x86_64")

    assert written == (DATA / "alpine-APKINDEX").read_text(encoding="utf-8")


async def test_a_package_for_no_architecture_is_listed_as_its_directorys():
    package = make_apk(pkginfo(arch="noarch"))
    apk = await packages.read(pieces(package))

    assert "\nA:aarch64\n" in index.record(index.Listed(len(package), apk), "aarch64")


async def test_fields_a_package_does_not_say_are_left_out():
    package = make_apk(pkginfo(extra="commit = \nprovider_priority = 0\n"))
    apk = await packages.read(pieces(package))

    written = index.record(index.Listed(len(package), apk), "x86_64")

    assert [line[0] for line in written.splitlines() if line] == list("CPVASITULotD")


@pytest.fixture(scope="module")
def key() -> signing.Material:
    return signing.generate_rsa()


async def test_the_index_is_signed_as_abuild_sign_signs_it(key):
    signer = signing.RsaSigner(key.private_key)

    data = index.index_file(
        [await listed(HELLO)], "x86_64", "MegooArti apk-hosted", "megooarti-x.rsa.pub", signer, 1
    )

    (signature, _), (packed, opened) = streams(data)
    signed = members(streams(data)[0][1])
    assert list(signed) == [".SIGN.RSA.megooarti-x.rsa.pub"]
    public = serialization.load_pem_public_key(key.public_key.encode())
    public.verify(
        signed[".SIGN.RSA.megooarti-x.rsa.pub"], packed, padding.PKCS1v15(), hashes.SHA1()
    )
    assert members(opened)["DESCRIPTION"] == b"MegooArti apk-hosted"
    assert signature.startswith(b"\x1f\x8b")


async def test_the_same_packages_make_the_same_index_but_for_the_signature(key):
    signer = signing.RsaSigner(key.private_key)
    made = [
        index.index_file([await listed(HELLO)], "x86_64", "d", "k.rsa.pub", signer, 7)
        for _ in range(2)
    ]

    assert streams(made[0])[1][0] == streams(made[1])[1][0]


def test_an_empty_index_lists_nothing(key):
    data = index.index_file([], "", "d", "k.rsa.pub", signing.RsaSigner(key.private_key), 1)

    assert apkindex(data) == ""


def test_an_index_abuild_wrote_reads_back_whole():
    read = index.read((DATA / "APKINDEX.tar.gz").read_bytes())

    assert (read.key_name, read.sha256) == ("builder-6ad0887f.rsa.pub", False)
    assert read.text == apkindex((DATA / "APKINDEX.tar.gz").read_bytes())
    assert len(read.signature) == 512


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"not gzip", "not gzip streams"),
        (gzip.compress(b"x" * 100, mtime=0), "not a tar archive"),
        ((DATA / "APKINDEX.tar.gz").read_bytes()[:700], "ends early"),
    ],
)
def test_what_is_not_an_index_a_group_can_read_is_refused(data, reason):
    with pytest.raises(index.InvalidIndex, match=reason):
        index.read(data)


def test_an_index_larger_unpacked_than_the_bound_is_refused():
    with pytest.raises(index.InvalidIndex, match="larger unpacked"):
        index.read((DATA / "APKINDEX.tar.gz").read_bytes(), most=1000)


def test_members_records_are_merged_an_earlier_members_first():
    first = "C:Q1a\nP:hello\nV:1.0-r0\nA:x86_64\n\nC:Q1b\nP:tool\nV:1.0-r0\nA:x86_64\n\n"
    later = (
        "C:Q1c\nP:hello\nV:1.0-r0\nA:x86_64\n\n"  # the same file apk would ask for
        "C:Q1d\nP:hello\nV:2.0-r0\nA:x86_64\n\n"
        "C:Q1e\nA:x86_64\n\n"  # names no package
    )

    merged = index.merged([first, later])

    assert [line for line in merged.splitlines() if line.startswith("C:")] == [
        "C:Q1a",
        "C:Q1b",
        "C:Q1d",
    ]
    assert merged.endswith("\n\n")


def test_an_index_abuild_signed_is_checked_with_its_key_and_no_other():
    read = index.read((DATA / "APKINDEX.tar.gz").read_bytes())
    builder = signing.read_rsa_public_keys(
        (DATA / "builder-6ad0887f.rsa.pub").read_text(encoding="utf-8")
    )
    another = signing.read_rsa_public_keys(signing.generate_rsa().public_key)

    signing.verify_rsa(read.packed, read.signature, another + builder)
    with pytest.raises(signing.Unverified):
        signing.verify_rsa(read.packed, read.signature, another)
    with pytest.raises(signing.Unverified):
        signing.verify_rsa(read.packed + b"x", read.signature, builder)
    with pytest.raises(signing.Unverified):
        signing.verify_rsa(read.packed, read.signature, builder, sha256=True)


def test_an_index_whose_tar_is_packed_again_inside_is_not_unpacked_further():
    """A few hundred bytes would otherwise unpack to hundreds of megabytes, unchecked."""
    inner = gzip.compress(tarfile_of({"APKINDEX": b"C:Q1a\nP:a\nV:1-r0\n\n" * 1000}), mtime=0)

    with pytest.raises(index.InvalidIndex, match="not a tar archive"):
        index.read(gzip.compress(inner, mtime=0))
