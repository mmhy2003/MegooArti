"""What an apk package says of itself: its `.PKGINFO`, and the identity apk knows it by.

A package as `abuild` writes it is gzip streams one after the other: a signature (left
out of an unsigned package), the control part (a tar of `.PKGINFO` and the scripts),
and the files. Only the first two are read, as the package arrives or from where it
was stored: the files, which can be gigabytes, are never looked at. What is read is
bounded, so a package cannot make the server hold or unpack more than a few megabytes.

apk knows a package by the SHA-1 of its control part as it is packed (`Q1` and the
digest in base64): an index lists it so, and apk installs a file only if it is the one
the index named.
"""

import asyncio
import base64
import hashlib
import io
import tarfile
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from megooarti.repositories.apk import versions

# The most of the signature and of the control part that is read, packed and unpacked:
# a real one is a few kilobytes.
CONTROL_MOST = 16 * 1024 * 1024
# The most a `.PKGINFO` may be, and any one field of it, said once or many times: apk
# stops reading an index at a line longer than it holds (128 KiB), and with it every
# package after that line. A real `.PKGINFO` is a few kilobytes.
INFO_MOST = 1024 * 1024
VALUE_MOST = 64 * 1024
_GZIP = b"\x1f\x8b"
_ADB = b"ADB"
# Fields of `.PKGINFO` that may be said more than once, each a list in what is kept.
LISTS = frozenset({"depend", "provides", "install_if", "replaces", "triggers"})


class InvalidPackage(ValueError):
    """Bytes that are not an apk package the server can list."""


@dataclass(frozen=True)
class Apk:
    """What a package says of itself, and its identity."""

    checksum: str  # Q1 and the SHA-1 of the control part, in base64
    info: dict[str, Any] = field(default_factory=dict)  # `.PKGINFO`, by its keys

    @property
    def name(self) -> str:
        return self.info.get("pkgname", "")

    @property
    def version(self) -> str:
        return self.info.get("pkgver", "")

    @property
    def arch(self) -> str:
        return self.info.get("arch", "")

    @property
    def filename(self) -> str:
        """The file's name, as apk asks for it: `<name>-<version>.apk`."""
        return f"{self.name}-{self.version}.apk"

    def as_json(self) -> dict[str, Any]:
        return {"checksum": self.checksum, "info": self.info}

    @classmethod
    def from_json(cls, said: dict[str, Any]) -> "Apk":
        return cls(str(said.get("checksum", "")), dict(said.get("info", {})))


class _Streams:
    """The gzip streams of a file, one at a time, from pieces."""

    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self._chunks = chunks
        self._held = b""
        self.started = False

    async def first_bytes(self, count: int) -> bytes:
        while len(self._held) < count:
            chunk = await anext(self._chunks, None)
            if chunk is None:
                break
            self._held += chunk
        return self._held[:count]

    async def next(self) -> tuple[bytes, bytes]:
        """The next stream as it is packed, and unpacked. Raises InvalidPackage."""
        unpack = zlib.decompressobj(wbits=31)
        packed, opened = bytearray(), bytearray()
        while True:
            if not self._held:
                chunk = await anext(self._chunks, None)
                if chunk is None:
                    raise InvalidPackage("it ends early")
                self._held = chunk
            room = CONTROL_MOST + 1 - len(opened)
            if room <= 0:
                raise InvalidPackage(
                    f"its control part is larger than {CONTROL_MOST // (1024 * 1024)} MiB"
                )
            try:
                opened += unpack.decompress(self._held, room)
            except zlib.error:
                raise InvalidPackage("it is not gzip streams, as apk packages are") from None
            if unpack.unconsumed_tail:
                raise InvalidPackage(
                    f"its control part is larger than {CONTROL_MOST // (1024 * 1024)} MiB"
                )
            used = len(self._held) - len(unpack.unused_data)
            packed += self._held[:used]
            self._held = unpack.unused_data
            if len(packed) > CONTROL_MOST:
                raise InvalidPackage(
                    f"its control part is larger than {CONTROL_MOST // (1024 * 1024)} MiB"
                )
            if unpack.eof:
                if len(opened) > CONTROL_MOST:
                    raise InvalidPackage(
                        f"its control part is larger than {CONTROL_MOST // (1024 * 1024)} MiB"
                    )
                return bytes(packed), bytes(opened)


def _members(opened: bytes) -> dict[str, bytes]:
    """The files of a tar that may lack its end, as a signature and a control part do."""
    found = {}
    try:
        # `r:`, as it is: unpacked again, a few bytes could be gigabytes.
        with tarfile.open(fileobj=io.BytesIO(opened + b"\0" * 1024), mode="r:") as tar:
            for member in tar.getmembers():
                if member.isfile():
                    found[member.name] = tar.extractfile(member).read()
    except (tarfile.TarError, ValueError, OverflowError):
        raise InvalidPackage("a part of it is not a tar archive") from None
    return found


def parse_info(text: str) -> dict[str, Any]:
    """`.PKGINFO`: `key = value` lines; a key of LISTS may be said more than once.

    Refuses what an index could not hold, or apk not read back: a NUL, and a field
    longer than VALUE_MOST, said once or in all.
    """
    if "\0" in text:
        raise InvalidPackage("its .PKGINFO holds a NUL")
    info: dict[str, Any] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, equals, value = line.partition(" = ")
        if not equals:
            raise InvalidPackage(f"a line of its .PKGINFO cannot be read: {line[:80]!r}")
        if key in LISTS:
            info.setdefault(key, []).extend(value.split())
        else:
            info[key] = value
    for key, value in info.items():
        said = " ".join(value) if isinstance(value, list) else value
        if len(said.encode()) > VALUE_MOST:
            raise InvalidPackage(
                f"its {key} is longer than {VALUE_MOST // 1024} KiB, "
                "which apk cannot read in an index"
            )
    return info


def describe(control: bytes, opened: bytes) -> Apk:
    """What a control part says, as it was packed and as it unpacks."""
    files = _members(opened)
    if ".PKGINFO" not in files:
        raise InvalidPackage("its control part has no .PKGINFO")
    if len(files[".PKGINFO"]) > INFO_MOST:
        raise InvalidPackage(f"its .PKGINFO is larger than {INFO_MOST // 1024} KiB")
    try:
        info = parse_info(files[".PKGINFO"].decode("utf-8"))
    except UnicodeDecodeError:
        raise InvalidPackage("its .PKGINFO is not UTF-8") from None
    name, version, arch = info.get("pkgname"), info.get("pkgver"), info.get("arch")
    if not (name and version and arch):
        raise InvalidPackage("its .PKGINFO says no pkgname, pkgver or arch")
    if versions.NAME.fullmatch(name) is None:
        raise InvalidPackage(f"its name cannot be a package's: {name[:80]!r}")
    if versions.VERSION.fullmatch(version) is None:
        raise InvalidPackage(f"its version cannot be a package's: {version[:80]!r}")
    if versions.ARCH.fullmatch(arch) is None:
        raise InvalidPackage(f"its architecture cannot be one: {arch[:80]!r}")
    checksum = "Q1" + base64.b64encode(hashlib.sha1(control).digest()).decode()
    return Apk(checksum, info)


async def read(chunks: AsyncIterator[bytes]) -> Apk:
    """What an apk package says of itself. Raises InvalidPackage.

    Reads no more of `chunks` than its signature and control part: the caller closes them.
    """
    streams = _Streams(chunks)
    start = await streams.first_bytes(3)
    if start == _ADB:
        raise InvalidPackage(
            "it is in apk-tools 3's package format (ADB), which this server does not read yet; "
            "build it with abuild as Alpine does, in the format of apk-tools 2"
        )
    if start[:2] != _GZIP:
        raise InvalidPackage("it is not an apk package")
    packed, opened = await streams.next()
    if any(name.startswith(".SIGN.") for name in _members(opened)):
        packed, opened = await streams.next()  # the signature: the control part is next
    # Reading a large one is work: not on the loop that serves everyone.
    return await asyncio.to_thread(describe, packed, opened)
