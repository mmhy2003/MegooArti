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
import tarfile
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
