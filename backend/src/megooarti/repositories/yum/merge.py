"""Members' `repodata/` merged into one: what a group of YUM repositories serves.

Each member's `primary.xml`, `filelists.xml` and `other.xml` is a list of packages,
each in a `<package>` element of its own. They are merged by those elements, copied
as the member wrote them, without being parsed as a whole: Fedora's `filelists.xml`
is 800 MB of text, read as it is unpacked and written as it is packed. A package (the
same name, epoch, version, release and architecture) that an earlier member has is
left out of a later one's, and so is a later member's package at a path an earlier
member holds with other content: the group could not give a client that file.
"""

import bz2
import hashlib
import io
import lzma
import re
import zlib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from xml.etree import ElementTree

import zstandard

# The most of one of a member's files that is unpacked (spec 9).
UNPACKED_MOST = 1024 * 1024 * 1024
KINDS = ("primary", "filelists", "other")
_PIECE = 1024 * 1024
_REPO = "{http://linux.duke.edu/metadata/repo}"
_START = b'<?xml version="1.0" encoding="UTF-8"?>\n'
_HEADS = {
    "primary": b'<metadata xmlns="http://linux.duke.edu/metadata/common" '
    b'xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="%d">\n',
    "filelists": b'<filelists xmlns="http://linux.duke.edu/metadata/filelists" packages="%d">\n',
    "other": b'<otherdata xmlns="http://linux.duke.edu/metadata/other" packages="%d">\n',
}
_ENDS = {"primary": b"</metadata>", "filelists": b"</filelists>", "other": b"</otherdata>"}
_OPEN, _CLOSE = b"<package ", b"</package>"
_DATA = re.compile(rb'<data type="([^"]+)">.*?</data>', re.DOTALL)
_NAME = re.compile(rb"<name>([^<]*)</name>")
_ARCH = re.compile(rb"<arch>([^<]*)</arch>")
_VERSION = re.compile(rb'<version epoch="([^"]*)" ver="([^"]*)" rel="([^"]*)"/>')
_PKGID = re.compile(rb'<checksum type="[^"]*" pkgid="YES">([^<]*)</checksum>')
_LOCATION = re.compile(rb"<location ([^>]*)/>")
_OWNED = re.compile(rb'<package pkgid="([^"]*)"')
_ALGORITHMS = {"sha": "sha1", "sha1": "sha1", "sha224": "sha224", "sha256": "sha256"}
_ALGORITHMS |= {"sha384": "sha384", "sha512": "sha512"}


class InvalidMetadata(ValueError):
    """A member's metadata that the group cannot read, or that is not what it says."""


@dataclass(frozen=True)
class Data:
    """One file a `repomd.xml` names."""

    type: str
    href: str  # under the directory of `repodata/`
    checksum_type: str
    checksum: str
    element: bytes  # the `<data>` element as the member wrote it


@dataclass(frozen=True)
class Repomd:
    revision: str  # a time, or whatever its writer chose (Rocky says its release)
    moment: int  # the newest of its files' timestamps, 0 if it says none
    data: dict[str, Data]  # by type, in the member's order


def parse_repomd(text: bytes) -> Repomd:
    """What a `repomd.xml` names. Raises InvalidMetadata."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise InvalidMetadata(f"its repomd.xml cannot be read: {error}") from None
    if root.tag != f"{_REPO}repomd":
        raise InvalidMetadata("its repomd.xml is not one")
    elements = {found[1].decode(): found[0] for found in _DATA.finditer(text)}
    data, moments = {}, [0]
    for node in root.iter(f"{_REPO}data"):
        kind = node.get("type", "")
        checksum = node.find(f"{_REPO}checksum")
        location = node.find(f"{_REPO}location")
        if checksum is None or location is None or kind not in elements:
            raise InvalidMetadata(f"its repomd.xml names {kind or 'a file'} without its checksum")
        data[kind] = Data(
            kind,
            location.get("href", ""),
            checksum.get("type", ""),
            (checksum.text or "").strip(),
            elements[kind],
        )
        stamp = (node.findtext(f"{_REPO}timestamp") or "").strip()
        moments.append(int(stamp) if stamp.isascii() and stamp.isdigit() else 0)
    return Repomd((root.findtext(f"{_REPO}revision") or "").strip(), max(moments), data)


def check(data: Data, packed: bytes) -> None:
    """Raise InvalidMetadata unless a file is the one `repomd.xml` names."""
    algorithm = _ALGORITHMS.get(data.checksum_type)
    if algorithm is None:
        raise InvalidMetadata(f"its {data.type} has a checksum of an unknown kind")
    if hashlib.new(algorithm, packed).hexdigest() != data.checksum.lower():
        raise InvalidMetadata(f"its {data.type} is not the one its repomd.xml names")


_UNPACKERS = {
    ".gz": lambda: zlib.decompressobj(wbits=47),
    ".xz": lzma.LZMADecompressor,
    ".bz2": bz2.BZ2Decompressor,
    ".zst": lambda: zstandard.ZstdDecompressor().decompressobj(),
}
_BROKEN = (zlib.error, lzma.LZMAError, OSError, zstandard.ZstdError, ValueError, EOFError)


def _pieces(href: str, packed: bytes) -> Iterator[bytes]:
    """A packed file's text, in pieces, however many streams it was packed in."""
    name = href.rpartition("/")[2]
    if href.endswith(".xml"):
        yield from (packed[at : at + _PIECE] for at in range(0, len(packed), _PIECE))
        return
    make = _UNPACKERS.get(href[href.rfind(".") :])
    if make is None:
        raise InvalidMetadata(f"{name} is packed in a way this server cannot read")
    unpack = make()
    for at in range(0, len(packed), _PIECE // 16):
        data = packed[at : at + _PIECE // 16]
        while data:
            if unpack.eof:
                unpack = make()  # the next stream, as gzip, xz, bzip2 and zstd allow
            try:
                yield unpack.decompress(data)
            except _BROKEN as error:
                raise InvalidMetadata(f"{name} cannot be unpacked: {error}") from None
            data = unpack.unused_data if unpack.eof else b""
    if not unpack.eof:
        raise InvalidMetadata(f"{name} ends before its end")


def unpacked(href: str, packed: bytes, most: int = UNPACKED_MOST) -> Iterator[bytes]:
    """A packed file's text, in pieces. Raises InvalidMetadata beyond `most` bytes."""
    total = 0
    for piece in _pieces(href, packed):
        total += len(piece)
        if total > most:
            raise InvalidMetadata(f"{href.rpartition('/')[2]} is larger than this server reads")
        if piece:
            yield piece


def packages(pieces: Iterable[bytes]) -> Iterator[bytes]:
    """Each `<package>` element of a text, as it was written."""
    held = b""
    for piece in pieces:
        held += piece
        at = 0
        while True:
            start = held.find(_OPEN, at)
            if start < 0:
                at = max(at, len(held) - len(_OPEN))
                break
            end = held.find(_CLOSE, start)
            if end < 0:
                at = start
                break
            at = end + len(_CLOSE)
            yield held[start:at]
        held = held[at:]


def _identity(element: bytes) -> tuple[tuple[bytes, ...], bytes, bytes]:
    """A package's name, epoch, version, release and architecture; its id; its path."""
    name, arch = _NAME.search(element), _ARCH.search(element)
    version, pkgid = _VERSION.search(element), _PKGID.search(element)
    location = _LOCATION.search(element)
    if not (name and arch and version and pkgid and location):
        raise InvalidMetadata("a package of its primary.xml cannot be read")
    nevra = (name[1], *version.groups(), arch[1])
    return nevra, pkgid[1], location[1]


def _id_of(kind: str, element: bytes) -> bytes:
    """A package's id: its checksum, which `filelists.xml` and `other.xml` call `pkgid`."""
    if kind == "primary":
        return _identity(element)[1]
    found = _OWNED.search(element)
    if found is None:
        raise InvalidMetadata(f"a package of its {kind}.xml cannot be read")
    return found[1]


def kept(primaries: Sequence[tuple[str, bytes]]) -> list[set[bytes]]:
    """Which packages of each member's `primary.xml` the group lists, by their ids.

    `primaries` are each member's, packed, with the name it has. Raises InvalidMetadata,
    with the member's index as its second argument.
    """
    seen: set[tuple[bytes, ...]] = set()
    held: dict[bytes, bytes] = {}  # by path, the id of what an earlier member has there
    found: list[set[bytes]] = []
    for number, (href, packed) in enumerate(primaries):
        mine: set[bytes] = set()
        try:
            for element in packages(unpacked(href, packed)):
                nevra, pkgid, location = _identity(element)
                if nevra in seen or held.get(location, pkgid) != pkgid:
                    continue
                seen.add(nevra)
                held.setdefault(location, pkgid)
                mine.add(pkgid)
        except InvalidMetadata as error:
            raise InvalidMetadata(str(error), number) from None
        found.append(mine)
    return found


@dataclass(frozen=True)
class Merged:
    """One merged file: packed, and what `repomd.xml` says of it."""

    kind: str
    packed: bytes
    open_checksum: str
    open_size: int

    @property
    def name(self) -> str:
        return f"{hashlib.sha256(self.packed).hexdigest()}-{self.kind}.xml.zst"


def merged(kind: str, members: Sequence[tuple[str, bytes]], kept: Sequence[set[bytes]]) -> Merged:
    """Members' files of one kind, merged: each member's packages that `kept` keeps.

    Packed with zstd, which takes seconds for Fedora's whole `filelists.xml` where gzip
    would take most of a minute.
    """
    sink = io.BytesIO()
    opened = hashlib.sha256()
    size = 0
    with zstandard.ZstdCompressor(level=3).stream_writer(sink, closefd=False) as packer:

        def write(text: bytes) -> None:
            nonlocal size
            opened.update(text)
            size += len(text)
            packer.write(text)

        write(_START + _HEADS[kind] % sum(len(mine) for mine in kept))
        for number, (href, packed) in enumerate(members):
            wanted, written = kept[number], set()
            try:
                for element in packages(unpacked(href, packed)):
                    pkgid = _id_of(kind, element)
                    if pkgid in wanted and pkgid not in written:
                        written.add(pkgid)
                        write(element + b"\n")
            except InvalidMetadata as error:
                raise InvalidMetadata(str(error), number) from None
        write(_ENDS[kind])
    return Merged(kind, sink.getvalue(), opened.hexdigest(), size)


def repomd(revision: str, parts: Sequence[Merged], passed: Sequence[Data]) -> bytes:
    """The group's `repomd.xml`: its merged files, and what it passes on of a member's."""
    data = []
    for part in parts:
        checksum = hashlib.sha256(part.packed).hexdigest()
        data.append(
            f'  <data type="{part.kind}">\n'
            f'    <checksum type="sha256">{checksum}</checksum>\n'
            f'    <open-checksum type="sha256">{part.open_checksum}</open-checksum>\n'
            f'    <location href="repodata/{part.name}"/>\n'
            f"    <timestamp>{revision}</timestamp>\n"
            f"    <size>{len(part.packed)}</size>\n"
            f"    <open-size>{part.open_size}</open-size>\n"
            "  </data>\n".encode()
        )
    data.extend(b"  " + element.strip() + b"\n" for element in (each.element for each in passed))
    return (
        _START
        + b'<repomd xmlns="http://linux.duke.edu/metadata/repo" '
        + b'xmlns:rpm="http://linux.duke.edu/metadata/rpm">\n'
        + f"  <revision>{revision}</revision>\n".encode()
        + b"".join(data)
        + b"</repomd>\n"
    )
