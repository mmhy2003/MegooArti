"""A directory's `APKINDEX.tar.gz`, written as apk-tools 3's `apk index` writes it."""

import io
import tarfile
import zlib

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from megooarti.repositories import signing
from megooarti.repositories.apk import index, packages
from tests.repositories.apk.packages import DATA, HELLO, REAL, TOOL, make_apk, pieces, pkginfo


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
