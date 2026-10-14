"""What a `.deb` says of itself: the `control` file inside it.

A `.deb` is an `ar` archive of three members, in this order: `debian-binary`, the
control archive (`control.tar`, compressed with gzip, xz, zstd or nothing), and the
files. Only the first two are read, as the package arrives or from where it was
stored: the files, which can be gigabytes, are never looked at. What is read is
bounded, so a package cannot make the server hold or unpack more than a few megabytes.
"""

import io
import lzma
import tarfile
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass

import zstandard

from megooarti.repositories.apt import control, versions

# The most of the control archive that is read, packed and unpacked: a real one is a
# few kilobytes.
CONTROL_MOST = 16 * 1024 * 1024
_MAGIC = b"!<arch>\n"
_HEADER = 60
# Fields the server writes into an index itself: a package cannot say them.
INDEX_FIELDS = frozenset({"filename", "size", "md5sum", "sha1", "sha256", "sha512"})


class InvalidPackage(ValueError):
    """Bytes that are not a Debian package the server can list."""


@dataclass(frozen=True)
class Deb:
    """What a package says of itself."""

    control: control.Paragraph
    package: str
    version: str
    architecture: str


class _Reader:
    """Bytes from pieces, a given number at a time."""

    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks
        self._held = bytearray()

    async def exactly(self, count: int) -> bytes:
        while len(self._held) < count:
            chunk = await anext(self._chunks, None)
            if chunk is None:
                raise InvalidPackage("it ends early")
            self._held += chunk
        taken = bytes(self._held[:count])
        del self._held[:count]
        return taken

    async def skip(self, count: int) -> None:
        while count > 0:
            if not self._held:
                chunk = await anext(self._chunks, None)
                if chunk is None:
                    raise InvalidPackage("it ends early")
                self._held += chunk
            dropped = min(count, len(self._held))
            del self._held[:dropped]
            count -= dropped


async def _member(reader: _Reader) -> tuple[str, int]:
    """The next member's name and size."""
    header = await reader.exactly(_HEADER)
    if header[58:60] != b"`\n":
        raise InvalidPackage("it is not an ar archive")
    name = header[0:16].decode("ascii", "replace").rstrip(" ").rstrip("/")
    size_text = header[48:58].decode("ascii", "replace").strip()
    if not size_text.isdigit():
        raise InvalidPackage("a member of it has no size")
    return name, int(size_text)


def _unpacked(name: str, packed: bytes) -> bytes:
    """The control archive, decompressed as its name says, and no larger than allowed."""
    try:
        if name == "control.tar":
            data = packed
        elif name == "control.tar.gz":
            data = zlib.decompressobj(wbits=47).decompress(packed, CONTROL_MOST + 1)
        elif name == "control.tar.xz":
            data = lzma.LZMADecompressor().decompress(packed, CONTROL_MOST + 1)
        elif name == "control.tar.zst":
            reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(packed))
            data = b""
            while len(data) <= CONTROL_MOST:
                piece = reader.read(CONTROL_MOST + 1 - len(data))
                if not piece:
                    break
                data += piece
        else:
            raise InvalidPackage(f"its control archive is {name}, which is not one dpkg writes")
    except (zlib.error, lzma.LZMAError, zstandard.ZstdError) as error:
        raise InvalidPackage(f"its control archive cannot be unpacked: {error}") from None
    if len(data) > CONTROL_MOST:
        raise InvalidPackage("its control archive is larger than this server reads")
    return data


def _control_file(archive: bytes) -> str:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for entry in tar:
                if entry.isfile() and entry.name in ("control", "./control"):
                    data = tar.extractfile(entry).read()
                    break
            else:
                raise InvalidPackage("its control archive has no control file")
    except tarfile.TarError as error:
        raise InvalidPackage(f"its control archive is not a tar archive: {error}") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidPackage("its control file is not UTF-8") from None


def describe(text: str) -> Deb:
    """What a control file says, checked as dpkg would check a binary package's."""
    try:
        paragraph = control.parse(text)
    except control.InvalidControl as error:
        raise InvalidPackage(f"its control file is not valid: {error}") from None
    said = {name: control.get(paragraph, name) for name in ("Package", "Version", "Architecture")}
    for name, value in said.items():
        if not value:
            raise InvalidPackage(f"its control file has no {name}")
    package, version, architecture = said["Package"], said["Version"], said["Architecture"]
    if versions.NAME.fullmatch(package) is None:
        raise InvalidPackage(f"{package[:60]!r} is not a Debian package name")
    if versions.split(version) is None:
        raise InvalidPackage(f"{version[:60]!r} is not a Debian version")
    if architecture == "any" or versions.ARCHITECTURE.fullmatch(architecture) is None:
        raise InvalidPackage(f"{architecture[:60]!r} is not an architecture")
    kept = [(name, value) for name, value in paragraph if name.lower() not in INDEX_FIELDS]
    return Deb(kept, package, version, architecture)


async def read(chunks: AsyncIterator[bytes]) -> Deb:
    """What the package in these pieces says of itself. Raises InvalidPackage."""
    reader = _Reader(chunks)
    if await reader.exactly(len(_MAGIC)) != _MAGIC:
        raise InvalidPackage("it is not an ar archive")
    name, size = await _member(reader)
    if name != "debian-binary" or size > 16:
        raise InvalidPackage("it does not begin with debian-binary")
    if not (await reader.exactly(size)).startswith(b"2."):
        raise InvalidPackage("it is not in the format dpkg 2 writes")
    await reader.skip(size % 2)
    while True:
        name, size = await _member(reader)
        if not name.startswith("_"):  # a member for tools, which dpkg skips
            break
        await reader.skip(size + size % 2)
    if not name.startswith("control.tar"):
        raise InvalidPackage("its second member is not the control archive")
    if size > CONTROL_MOST:
        raise InvalidPackage("its control archive is larger than this server reads")
    return describe(_control_file(_unpacked(name, await reader.exactly(size))))
