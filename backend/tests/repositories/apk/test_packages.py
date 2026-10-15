"""Reading an apk package's control part, as it arrives, and what apk knows it by."""

import gzip
import io
import tarfile
import zlib

import pytest

from megooarti.repositories.apk import packages
from tests.repositories.apk.packages import DATA, HELLO, TOOL, make_apk, pieces, pkginfo, tar_of


async def read(data: bytes) -> packages.Apk:
    return await packages.read(pieces(data))


def checksums(index: bytes) -> dict[str, str]:
    """What an `APKINDEX.tar.gz` says each package's checksum is, by its name."""
    first = zlib.decompressobj(wbits=31)
    first.decompress(index)
    opened = zlib.decompressobj(wbits=31).decompress(first.unused_data)
    with tarfile.open(fileobj=io.BytesIO(opened)) as tar:
        text = tar.extractfile("APKINDEX").read().decode()
    found = {}
    for record in text.split("\n\n"):
        said = dict(line.split(":", 1) for line in record.splitlines() if line[1:2] == ":")
        if "P" in said:
            found[said["P"]] = said["C"]
    return found


async def test_a_package_abuild_wrote_says_what_its_apkbuild_said():
    apk = await read((DATA / HELLO).read_bytes())

    assert (apk.name, apk.version, apk.arch) == ("megooarti-hello", "1.0-r0", "noarch")
    assert apk.info["pkgdesc"] == "Says hello"
    assert apk.info["maintainer"] == "MegooArti Tests <tests@example.com>"
    assert apk.info["depend"] == ["busybox"]
    assert apk.info["provides"] == ["hello-tool=1.0", "cmd:megooarti-hello=1.0-r0"]
    assert apk.filename == HELLO


@pytest.mark.parametrize("name", [HELLO, TOOL])
async def test_a_package_is_known_by_the_checksum_its_index_gives(name):
    apk = await read((DATA / name).read_bytes())

    assert apk.checksum == checksums((DATA / "APKINDEX.tar.gz").read_bytes())[apk.name]


async def test_a_package_without_a_signature_is_read_as_well():
    apk = await read(make_apk(signed=False))

    assert apk.name == "megooarti-hello" and apk.checksum.startswith("Q1")


async def test_install_if_is_a_list_and_what_is_said_twice_is_kept_twice():
    apk = await read((DATA / TOOL).read_bytes())

    assert apk.info["install_if"] == ["megooarti-hello", "busybox"]
    assert apk.info["depend"] == ["megooarti-hello>=1.0"]


async def test_what_is_kept_of_a_package_reads_back_as_it_was():
    apk = await read((DATA / TOOL).read_bytes())

    assert packages.Apk.from_json(apk.as_json()) == apk


async def test_only_the_signature_and_the_control_part_are_read():
    data = make_apk(data=b"\0" * 2_000_000)
    taken = []

    async def counted():
        async for piece in pieces(data):
            taken.append(len(piece))
            yield piece

    await packages.read(counted())

    assert sum(taken) < 5000


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"ADBd" + b"\0" * 100, "apk-tools 3's package format"),
        (b"PK\x03\x04 a zip file", "not an apk package"),
        (gzip.compress(b"x" * 10, mtime=0), "not a tar archive"),
        (make_apk()[:300], "ends early"),
        (gzip.compress(tar_of({"README": b"hi"}, end=False), mtime=0) * 2, "no .PKGINFO"),
        (make_apk(pkginfo(name="-rf")), "name"),
        (make_apk(pkginfo(version="one")), "version"),
        (make_apk(pkginfo(arch="x86 64")), "architecture"),
        (make_apk("pkgname = x\n"), "says no pkgname, pkgver or arch"),
        (make_apk(pkginfo() + "this is not a line\n"), "cannot be read"),
    ],
)
async def test_what_is_not_an_apk_package_abuild_writes_is_refused(data, reason):
    with pytest.raises(packages.InvalidPackage, match=reason):
        await read(data)


async def test_a_control_part_larger_than_the_bound_is_refused_before_it_is_read(monkeypatch):
    monkeypatch.setattr(packages, "CONTROL_MOST", 10_000)
    large = make_apk(pkginfo(extra=f"commit = {'a' * 50_000}\n"), signed=False)

    with pytest.raises(packages.InvalidPackage, match="larger than"):
        await read(large)


@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        (f"pkgdesc = {'x' * 70_000}\n", "pkgdesc is longer than"),
        ("depend = " + " ".join(["so:libx"] * 10_000) + "\n", "depend is longer than"),
        ("pkgdesc = a\x00b\n", "NUL"),
    ],
    ids=["description", "dependencies", "nul"],
)
async def test_what_apk_could_not_read_back_from_an_index_is_refused(extra, reason):
    """apk stops reading an index at a line longer than it holds: every package after it."""
    with pytest.raises(packages.InvalidPackage, match=reason):
        await read(make_apk(pkginfo(extra=extra)))


async def test_a_pkginfo_larger_than_a_package_needs_is_refused(monkeypatch):
    monkeypatch.setattr(packages, "INFO_MOST", 1000)

    with pytest.raises(packages.InvalidPackage, match=".PKGINFO is larger than"):
        await read(make_apk(pkginfo(extra="".join(f"replaces = r{n}\n" for n in range(100)))))


async def test_a_tar_header_python_cannot_read_is_refused_as_any_broken_part():
    member = tarfile.TarInfo(".PKGINFO")
    member.size = len(pkginfo())
    member.pax_headers = {"GNU.sparse.size": "abc"}
    control = member.tobuf(format=tarfile.PAX_FORMAT) + pkginfo().encode().ljust(512, b"\0")

    with pytest.raises(packages.InvalidPackage, match="not a tar archive"):
        await read(gzip.compress(control, mtime=0) + gzip.compress(tar_of({}, end=True), mtime=0))


async def test_a_control_part_one_byte_over_the_bound_is_refused_however_it_arrives(monkeypatch):
    package = make_apk(signed=False)
    first = zlib.decompressobj(wbits=31)
    opened = first.decompress(package)
    monkeypatch.setattr(packages, "CONTROL_MOST", len(opened) - 1)

    with pytest.raises(packages.InvalidPackage, match="larger than"):
        await packages.read(pieces(package, size=1))
