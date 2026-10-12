"""Reading a package's own manifest out of its tarball.

`npm publish` reads `package.json` and sends it beside the tarball. An upload through
the API sends the tarball alone, so the manifest is read out of it here. Pure functions:
nothing is unpacked to a disk, and no more than a bounded amount is ever decompressed.
"""

import gzip
import io
import tarfile
import zlib
from typing import Any

from megooarti.repositories.npm import documents
from megooarti.repositories.npm.documents import InvalidPackage

MANIFEST = "package.json"
# The most that is decompressed looking for the manifest. `npm pack` writes it first;
# a tarball that hides it behind more than this is not one to spend longer on.
SCAN_LIMIT = 256 * 1024 * 1024
_PIECE = 64 * 1024


class _Bounded:
    """A stream that refuses to give more than a set amount."""

    def __init__(self, source: Any, most: int) -> None:
        self._source, self._left = source, most

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size if 0 < size <= _PIECE else _PIECE)
        self._left -= len(data)
        if self._left < 0:
            raise InvalidPackage("its package.json is not near the start of the tarball")
        return data


def _is_manifest(name: str) -> bool:
    """Whether a member is `package.json` in the tarball's one folder, as npm reads it."""
    parts = name.removeprefix("./").split("/")
    return len(parts) == 2 and parts[1] == MANIFEST


def manifest(data: bytes, *, scan_limit: int = SCAN_LIMIT) -> dict[str, Any]:
    """The `package.json` of a package tarball. Raises InvalidPackage."""
    try:
        unpacked = _Bounded(gzip.GzipFile(fileobj=io.BytesIO(data)), scan_limit)
        with tarfile.open(fileobj=unpacked, mode="r|") as archive:  # read in one pass
            for member in archive:
                if not member.isfile() or not _is_manifest(member.name):
                    continue
                if member.size > documents.MAX_MANIFEST_BYTES:
                    raise InvalidPackage("its package.json is larger than 1 MiB")
                held = archive.extractfile(member)
                found = documents.loads(b"" if held is None else held.read(), "its package.json")
                if not isinstance(found, dict):
                    raise InvalidPackage("its package.json is not an object")
                return found
    except (tarfile.TarError, OSError, EOFError, zlib.error):
        raise InvalidPackage("the file is not a package tarball") from None
    raise InvalidPackage("the tarball has no package.json")
