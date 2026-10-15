"""A directory's `APKINDEX.tar.gz`: what apk reads to know the packages in it.

It is two gzip streams. The first is a signature: a tar of one file, named for the key
(`.SIGN.RSA.<key name>`), which holds the RSA signature of the second stream as it is
packed. The second is a tar of `DESCRIPTION` (a line that `apk update` shows) and
`APKINDEX`, a record of each package, written as `apk index` of apk-tools 3 writes it.

A package for no architecture (`noarch`) is listed under the architecture of its
directory, as `abuild` has `apk index` do (`--rewrite-arch`): apk asks for a package
at `<repository>/<architecture>/<name>-<version>.apk`, by what the index says.
"""

import gzip
import io
import tarfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from megooarti.repositories.apk.packages import Apk
from megooarti.repositories.apk.versions import NOARCH

INDEX = "APKINDEX.tar.gz"
_BLOCK = 512


class Signs(Protocol):
    def sign(self, data: bytes) -> bytes: ...


@dataclass(frozen=True)
class Listed:
    """A package that an index lists, and its file."""

    size: int
    apk: Apk


def _joined(info: dict, key: str) -> str:
    said = info.get(key) or []
    return " ".join(said) if isinstance(said, list) else str(said)


def record(listed: Listed, architecture: str) -> str:
    """A package's record, as `apk index` writes it, and the line that ends it.

    `architecture` is its directory's: what a package for no architecture is listed as.
    """
    info = listed.apk.info
    arch = info.get("arch", "")
    lines = [
        f"C:{listed.apk.checksum}",
        f"P:{info.get('pkgname', '')}",
        f"V:{info.get('pkgver', '')}",
        f"A:{architecture if arch == NOARCH else arch}",
        f"S:{listed.size}",
        f"I:{info.get('size', '0')}",
        f"T:{info.get('pkgdesc', '')}",
        f"U:{info.get('url', '')}",
        f"L:{info.get('license', '')}",
    ]
    for key, field in (("o", "origin"), ("m", "maintainer")):
        if info.get(field):
            lines.append(f"{key}:{info[field]}")
    if info.get("builddate", "0") not in ("", "0"):
        lines.append(f"t:{info['builddate']}")
    if info.get("commit"):
        lines.append(f"c:{info['commit']}")
    if info.get("provider_priority", "0") not in ("", "0"):
        lines.append(f"k:{info['provider_priority']}")
    for key, field in (("D", "depend"), ("p", "provides"), ("i", "install_if")):
        said = _joined(info, field)
        if said:
            lines.append(f"{key}:{said}")
    return "\n".join(lines) + "\n\n"


def apkindex(listed: Sequence[Listed], architecture: str) -> str:
    """`APKINDEX`: every package's record, in the order given."""
    return "".join(record(each, architecture) for each in listed)


def _tar_member(name: str, data: bytes, moment: int) -> bytes:
    """One file of a tar: its header and its content, padded to a whole block."""
    member = tarfile.TarInfo(name)
    member.size = len(data)
    member.mtime = moment
    member.mode = 0o644
    member.uname = member.gname = "root"
    header = member.tobuf(format=tarfile.USTAR_FORMAT, encoding="utf-8", errors="strict")
    return header + data + b"\0" * (-len(data) % _BLOCK)


def archive(description: str, text: str, moment: int) -> bytes:
    """The second stream: a tar of `DESCRIPTION` and `APKINDEX`, packed with gzip."""
    tar = (
        _tar_member("DESCRIPTION", description.encode(), moment)
        + _tar_member("APKINDEX", text.encode(), moment)
        + b"\0" * (2 * _BLOCK)
    )
    return gzip.compress(tar, compresslevel=9, mtime=0)


def signature(packed: bytes, key_name: str, signer: Signs, moment: int) -> bytes:
    """The first stream: the signature of the second, as `abuild-sign` makes it.

    A tar of one file and no end, so that the two streams read as one archive.
    """
    signed = signer.sign(packed)
    tar = _tar_member(f".SIGN.RSA.{key_name}", signed, moment)
    return gzip.compress(tar, compresslevel=9, mtime=0)


def index_file(
    listed: Sequence[Listed],
    architecture: str,
    description: str,
    key_name: str,
    signer: Signs,
    moment: int,
) -> bytes:
    """A whole `APKINDEX.tar.gz`, signed."""
    packed = archive(description, apkindex(listed, architecture), moment)
    return signature(packed, key_name, signer, moment) + packed


# --- What a group reads of its members' indexes ----------------------------------------

# The most of a member's index that is read unpacked (spec 9).
UNPACKED_MOST = 1024 * 1024 * 1024
_SIGNED = {".SIGN.RSA.": False, ".SIGN.RSA256.": True}  # by its prefix: whether SHA-256


class InvalidIndex(ValueError):
    """Bytes that are not an `APKINDEX.tar.gz` a group can read."""


@dataclass(frozen=True)
class Read:
    """What an index is: who signed it and how, its second stream, and its records."""

    key_name: str  # of the key it says signed it; empty if it is not signed
    sha256: bool  # whether its signature is of SHA-256 (`.SIGN.RSA256.`) or SHA-1
    signature: bytes
    packed: bytes  # the stream it signs, as it is packed
    text: str  # APKINDEX


def _stream(data: bytes, most: int) -> tuple[bytes, bytes, bytes]:
    """The first gzip stream of `data`, packed and unpacked, and what follows it."""
    unpack = zlib.decompressobj(wbits=31)
    try:
        opened = unpack.decompress(data, most + 1)
    except zlib.error:
        raise InvalidIndex("it is not gzip streams, as an APKINDEX.tar.gz is") from None
    if len(opened) > most or unpack.unconsumed_tail:
        raise InvalidIndex("it is larger unpacked than this server reads")
    if not unpack.eof:
        raise InvalidIndex("it ends early")
    rest = unpack.unused_data
    return data[: len(data) - len(rest)], opened, rest


def _files(opened: bytes) -> dict[str, bytes]:
    try:
        with tarfile.open(fileobj=io.BytesIO(opened + b"\0" * 1024)) as tar:
            return {
                member.name: tar.extractfile(member).read()
                for member in tar.getmembers()
                if member.isfile()
            }
    except (tarfile.TarError, ValueError, OverflowError):
        raise InvalidIndex("a part of it is not a tar archive") from None


def read(data: bytes, most: int = UNPACKED_MOST) -> Read:
    """What an `APKINDEX.tar.gz` says, and of its signature. Raises InvalidIndex."""
    packed, opened, rest = _stream(data, most)
    first = _files(opened)
    signed = [name for name in first if name.startswith(".SIGN.")]
    key_name, sha256, signature = "", False, b""
    if signed:
        name = signed[0]
        prefix = next((p for p in _SIGNED if name.startswith(p)), None)
        if prefix is None:
            raise InvalidIndex(f"it is signed in a way this server cannot check ({name})")
        key_name, sha256, signature = name.removeprefix(prefix), _SIGNED[prefix], first[name]
        packed, opened, _ = _stream(rest, most)
        first = _files(opened)
    if "APKINDEX" not in first:
        raise InvalidIndex("it has no APKINDEX")
    try:
        text = first["APKINDEX"].decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidIndex("its APKINDEX is not UTF-8") from None
    return Read(key_name, sha256, signature, packed, text)


def merged(texts: Sequence[str]) -> str:
    """Members' `APKINDEX`, in their order: of a name and version in a directory (the
    file apk would ask for), the first member's record alone."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for text in texts:
        for record in text.split("\n\n"):
            fields = dict(line.split(":", 1) for line in record.splitlines() if line[1:2] == ":")
            named = (fields.get("P", ""), fields.get("V", ""))
            if not all(named) or named in seen:
                continue
            seen.add(named)
            kept.append(record.strip("\n") + "\n\n")
    return "".join(kept)
