"""Reading a package's own manifest out of its tarball.

`npm publish` reads `package.json` and sends it beside the tarball. An upload through
the API sends the tarball alone, so the manifest is read out of it here. Pure functions.

The archive is walked header by header, by this module and not by `tarfile`: whoever
sends a tarball decides how many members it has and how long its headers say they
are, and a general reader keeps something of every member and reads a header whole.
Here nothing is kept of what is passed over, nothing is unpacked to a disk, and what
is decompressed, passed over and read into memory each have a limit.
"""

import gzip
import io
import zlib
from typing import Any

from megooarti.repositories.npm import documents
from megooarti.repositories.npm.documents import InvalidPackage

MANIFEST = "package.json"
# The most that is decompressed looking for the manifest. `npm pack` writes files in
# the order of their names, so a large `dist/` can come before it.
SCAN_LIMIT = 256 * 1024 * 1024
# The most members that are passed over looking for it. Each has a header to check.
MAX_MEMBERS = 100_000
# The most of an extended header or a long name that is read. They hold a name.
_HEADER_LIMIT = 1024 * 1024
_BLOCK = 512
_PIECE = 64 * 1024
# What a member is, by one byte of its header.
_FILES = (b"0", b"\x00", b"7")
_PAX, _LONG_NAME = b"x", b"L"
_NOT_ONE = "the file is not a package tarball"
_NO_MANIFEST = "the tarball has no package.json"


class _Unpacked:
    """The decompressed archive, read forwards, and no further than a set amount."""

    def __init__(self, data: bytes, most: int) -> None:
        self._source = gzip.GzipFile(fileobj=io.BytesIO(data))
        self._left = most
        self._held, self._at = b"", 0

    def _fill(self, wanted: int) -> None:
        """Hold `wanted` bytes from where the reading is, if the archive has them.

        When more has to be decompressed, a piece beyond what is wanted is too: the
        archive is then not touched again for a while, and one that is cut short just
        after its manifest is seen to be.
        """
        have = len(self._held) - self._at
        if have >= wanted:
            return
        pieces = [self._held[self._at :]]
        while have < wanted + _PIECE:
            piece = self._source.read(_PIECE)
            if not piece:
                break
            self._left -= len(piece)
            if self._left < 0:
                raise InvalidPackage("its package.json is not near the start of the tarball")
            pieces.append(piece)
            have += len(piece)
        self._held, self._at = b"".join(pieces), 0

    def read(self, size: int) -> bytes:
        """The next `size` bytes, or fewer at the end. For what is small: it is held."""
        self._fill(size)
        taken = self._held[self._at : self._at + size]
        self._at += len(taken)
        return taken

    def skip(self, size: int) -> None:
        """Pass over `size` bytes, holding no more than a piece of them at a time."""
        while size > 0:
            self._fill(1)
            passed = min(size, len(self._held) - self._at)
            if passed == 0:
                return
            self._at += passed
            size -= passed


def _number(field: bytes) -> int:
    """A number as a header writes it: octal digits, or binary when it is very large."""
    if field[:1] >= b"\x80":
        return int.from_bytes(field[1:], "big")
    digits = field.strip(b" \x00")
    try:
        return int(digits, 8) if digits else 0
    except ValueError:
        raise InvalidPackage(_NOT_ONE) from None


def _checked(header: bytes) -> None:
    """Refuse a block that is not a header: a header holds the sum of its own bytes."""
    summed = sum(header[:148]) + 8 * ord(" ") + sum(header[156:])
    if _number(header[148:156]) != summed:
        raise InvalidPackage(_NOT_ONE)


def _text(field: bytes) -> str:
    return field.partition(b"\x00")[0].decode("utf-8", "replace")


def _name(header: bytes) -> str:
    name = _text(header[:100])
    prefix = _text(header[345:500]) if header[257:262] == b"ustar" else ""
    return f"{prefix}/{name}" if prefix else name


def _pax_path(records: bytes) -> str | None:
    """The `path` an extended header gives the member after it, if it gives one."""
    position = 0
    while position < len(records):
        length, space, _ = records[position : position + 20].partition(b" ")
        if not space or not length.isdigit() or int(length) == 0:
            return None
        record = records[position + len(length) + 1 : position + int(length)]
        key, _, value = record.rstrip(b"\n").partition(b"=")
        if key == b"path":
            return value.decode("utf-8", "replace")
        position += int(length)
    return None


def _is_manifest(name: str) -> bool:
    """Whether a member is `package.json` in the tarball's one folder, as npm reads it."""
    parts = name.removeprefix("./").split("/")
    return len(parts) == 2 and parts[1] == MANIFEST


def _find(archive: _Unpacked, max_members: int) -> dict[str, Any]:
    named: str | None = None  # the name an earlier header gave the member that follows
    for passed in range(max_members + 1):
        header = archive.read(_BLOCK)
        if not header or header == bytes(_BLOCK):  # the end, or the blocks that mark it
            raise InvalidPackage(_NO_MANIFEST if passed else _NOT_ONE)
        if len(header) < _BLOCK:
            raise InvalidPackage(_NOT_ONE)
        _checked(header)
        size, kind = _number(header[124:136]), header[156:157]
        padded = size + (-size % _BLOCK)
        if kind in (_PAX, _LONG_NAME):
            if size > _HEADER_LIMIT:
                raise InvalidPackage("a header of the tarball is larger than 1 MiB")
            content = archive.read(padded)[:size]
            given = _pax_path(content) if kind == _PAX else _text(content)
            named = named if given is None else given
            continue
        name, named = (_name(header) if named is None else named), None
        if kind not in _FILES or not _is_manifest(name):
            archive.skip(padded)
            continue
        if size > documents.MAX_MANIFEST_BYTES:
            raise InvalidPackage("its package.json is larger than 1 MiB")
        raw = archive.read(size)
        if len(raw) < size:
            raise InvalidPackage(_NOT_ONE)
        found = documents.loads(raw, "its package.json")
        if not isinstance(found, dict):
            raise InvalidPackage("its package.json is not an object")
        return found
    raise InvalidPackage(f"the tarball has more than {max_members} files before its package.json")


def manifest(
    data: bytes, *, scan_limit: int = SCAN_LIMIT, max_members: int = MAX_MEMBERS
) -> dict[str, Any]:
    """The `package.json` of a package tarball. Raises InvalidPackage."""
    try:
        return _find(_Unpacked(data, scan_limit), max_members)
    except (OSError, EOFError, zlib.error):
        raise InvalidPackage(_NOT_ONE) from None
