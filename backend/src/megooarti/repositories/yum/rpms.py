"""What an RPM says of itself: its lead and its headers.

An RPM is a lead of 96 bytes, a signature header, padded to a multiple of eight bytes,
the header, and the files, packed. Only the first three are read, as the package
arrives or from where it was stored: the files are never looked at. The headers are
bounded, so a package cannot make the server hold more than 64 MiB of them.

What is read is what `createrepo_c` writes into a repository's metadata, worked out as
it works it out: the same dependencies left out, the same `pre`, the same changelog.
"""

import struct
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from megooarti.repositories.yum import versions

# The most of the two headers that is read: a real one is kilobytes, a large one a few
# megabytes.
HEADER_MOST = 64 * 1024 * 1024
CHANGELOGS_KEPT = 10
_LEAD = 96
_LEAD_MAGIC = b"\xed\xab\xee\xdb"
_HEADER_MAGIC = b"\x8e\xad\xe8\x01"
_SOURCE = 1

# Tags of the header.
_NAME, _VERSION, _RELEASE, _EPOCH = 1000, 1001, 1002, 1003
_SUMMARY, _DESCRIPTION, _BUILDTIME, _BUILDHOST = 1004, 1005, 1006, 1007
_SIZE, _VENDOR, _LICENSE, _PACKAGER, _GROUP, _URL, _ARCH = 1009, 1011, 1014, 1015, 1016, 1020, 1022
_FILEMODES, _FILEFLAGS, _SOURCERPM, _ARCHIVESIZE = 1030, 1037, 1044, 1046
_CHANGELOGTIME, _CHANGELOGNAME, _CHANGELOGTEXT = 1080, 1081, 1082
_SOURCEPACKAGE, _DIRINDEXES, _BASENAMES, _DIRNAMES = 1106, 1116, 1117, 1118
_LONGSIZE = 5009
# The same in the signature header.
_SIG_PAYLOADSIZE, _SIG_LONGARCHIVESIZE = 1007, 271

# Each kind of dependency: its names, flags and versions, in the order createrepo_c
# writes them.
DEPENDENCIES = {
    "provides": (1047, 1112, 1113),
    "requires": (1049, 1048, 1050),
    "conflicts": (1054, 1053, 1055),
    "obsoletes": (1090, 1114, 1115),
    "suggests": (5049, 5051, 5050),
    "enhances": (5055, 5057, 5056),
    "recommends": (5046, 5048, 5047),
    "supplements": (5052, 5054, 5053),
}

# What a dependency's flags say of its version.
_COMPARED = {2: "LT", 4: "GT", 8: "EQ", 10: "LE", 12: "GE"}
# A requirement needed before the package is installed (rpm's `isInstallPreReq`),
# or said with the old `PreReq` (`isLegacyPreReq`): createrepo_c marks these `pre`.
_PREREQ = 1 << 6
_INSTALL_ONLY = (1 << 9) | (1 << 10) | (1 << 24) | (1 << 26) | (1 << 7) | (1 << 5)
_ALL_REQUIRES = _INSTALL_ONLY | _PREREQ | (1 << 8) | (0x1F << 11) | (1 << 19) | (3 << 20)
_RPMFILE_GHOST = 1 << 6
_DIRECTORY = 0o040000
_FILE_TYPE = 0o170000

# Types of a header's values.
_INT16, _INT32, _INT64, _STRING, _BIN, _STRING_ARRAY, _I18NSTRING = 3, 4, 5, 6, 7, 8, 9


class InvalidPackage(ValueError):
    """Bytes that are not an RPM the server can list."""


@dataclass(frozen=True)
class Entry:
    """One dependency, as createrepo_c lists it."""

    name: str
    flags: str = ""  # LT, GT, EQ, LE or GE; empty when no version is said
    epoch: str = ""
    version: str = ""
    release: str = ""
    pre: bool = False


@dataclass(frozen=True)
class Changelog:
    author: str
    date: int
    text: str


@dataclass(frozen=True)
class Rpm:
    """What a package says of itself."""

    name: str
    epoch: str  # "0" when it says none
    version: str
    release: str
    arch: str
    summary: str = ""
    description: str = ""
    packager: str = ""
    url: str = ""
    license: str = ""
    vendor: str = ""
    group: str = ""
    buildhost: str = ""
    sourcerpm: str = ""
    build_time: int = 0
    installed_size: int = 0
    archive_size: int = 0
    header_start: int = 0
    header_end: int = 0
    # By kind, in DEPENDENCIES' order: only the kinds it has.
    dependencies: dict[str, list[Entry]] = field(default_factory=dict)
    # Each path, and "dir", "ghost" or "" for a file.
    files: list[tuple[str, str]] = field(default_factory=list)
    changelogs: list[Changelog] = field(default_factory=list)  # the newest ten, oldest first

    @property
    def evr(self) -> str:
        """Its version as dnf is given it: the epoch only when it has one."""
        return versions.evr(self.epoch, self.version, self.release)

    def as_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, said: dict[str, Any]) -> "Rpm":
        return cls(
            **{
                **said,
                "dependencies": {
                    kind: [Entry(**entry) for entry in entries]
                    for kind, entries in said.get("dependencies", {}).items()
                },
                "files": [(str(path), str(kind)) for path, kind in said.get("files", [])],
                "changelogs": [Changelog(**entry) for entry in said.get("changelogs", [])],
            }
        )


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


class _Header:
    """One header's values, by tag."""

    def __init__(self, index: bytes, store: bytes) -> None:
        self._store = store
        self._index: dict[int, tuple[int, int, int]] = {}
        for at in range(0, len(index), 16):
            tag, kind, offset, count = struct.unpack(">IIII", index[at : at + 16])
            if offset >= len(store) and count:
                raise InvalidPackage("its header points outside itself")
            self._index[tag] = (kind, offset, count)

    def __contains__(self, tag: int) -> bool:
        return tag in self._index

    def _strings(self, tag: int) -> list[str]:
        kind, offset, count = self._index.get(tag, (0, 0, 0))
        if kind not in (_STRING, _STRING_ARRAY, _I18NSTRING):
            return []
        found, at = [], offset
        for _ in range(count if kind != _STRING else 1):
            end = self._store.find(b"\0", at)
            if end < 0:
                raise InvalidPackage("a string of its header does not end")
            found.append(_text(self._store[at:end]))
            at = end + 1
        return found

    def string(self, tag: int) -> str:
        """A string, or the first of several (a summary has one for each language)."""
        strings = self._strings(tag)
        return strings[0] if strings else ""

    def strings(self, tag: int) -> list[str]:
        return self._strings(tag)

    def numbers(self, tag: int) -> list[int]:
        kind, offset, count = self._index.get(tag, (0, 0, 0))
        width = {_INT16: 2, _INT32: 4, _INT64: 8}.get(kind)
        if width is None:
            return []
        data = self._store[offset : offset + width * count]
        if len(data) != width * count:
            raise InvalidPackage("a number of its header lies outside it")
        return list(struct.unpack(f">{count}{'HIQ'[width // 4]}", data))

    def number(self, *tags: int) -> int:
        """The first of the tags it has, as a number."""
        for tag in tags:
            numbers = self.numbers(tag)
            if numbers:
                return numbers[0]
        return 0


def _text(raw: bytes) -> str:
    """A header's string. Old packages wrote Latin-1, which createrepo_c reads as such."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


async def _header(reader: _Reader, budget: int) -> tuple[_Header, int]:
    """The next header, and how many bytes it is."""
    intro = await reader.exactly(16)
    if intro[:4] != _HEADER_MAGIC:
        raise InvalidPackage("it has no RPM header where one belongs")
    count, size = struct.unpack(">II", intro[8:16])
    length = 16 + 16 * count + size
    if length > budget:
        raise InvalidPackage(f"its headers are larger than {HEADER_MOST // (1024 * 1024)} MiB")
    index = await reader.exactly(16 * count)
    store = await reader.exactly(size)
    return _Header(index, store), length


def _flags(number: int) -> str:
    return _COMPARED.get(number & 0xF, "")


def _is_pre(number: int) -> bool:
    return bool(number & _INSTALL_ONLY) or number & _ALL_REQUIRES == _PREREQ


def is_primary(path: str) -> bool:
    """Whether createrepo_c lists a file in `primary.xml`, where dnf finds it at once."""
    return path.startswith("/etc/") or "bin/" in path or path == "/usr/lib/sendmail"


def _libc_version(name: str) -> str:
    """What is between the first parentheses of `libc.so.6(GLIBC_2.38)(64bit)`."""
    start = name.find("(")
    end = name.find(")", start)
    return name[start + 1 : end] if start >= 0 and end >= 0 else ""


def _dependencies(header: _Header, files: set[str]) -> dict[str, list[Entry]]:
    """Each kind of dependency, as createrepo_c lists it.

    Of what a package requires, it leaves out what rpm itself provides (`rpmlib(...)`),
    its own files that `primary.xml` lists, what the package provides itself in the
    same words, and what it requires twice; of `libc.so.6`, it keeps the highest
    version alone, last.
    """
    found: dict[str, list[Entry]] = {}
    provided: dict[str, tuple[str, str, bool]] = {}
    for kind, (names_tag, flags_tag, versions_tag) in DEPENDENCIES.items():
        names = header.strings(names_tag)
        numbers = header.numbers(flags_tag)
        said = header.strings(versions_tag)
        if len(numbers) != len(names) or len(said) != len(names):
            numbers = (numbers + [0] * len(names))[: len(names)]
            said = (said + [""] * len(names))[: len(names)]
        entries: list[Entry] = []
        seen: dict[str, tuple[str, str, bool]] = {}
        libc: Entry | None = None
        for name, number, version in zip(names, numbers, said, strict=True):
            flags = _flags(number)
            pre = False
            if kind == "requires":
                if name.startswith("rpmlib("):
                    continue
                if name.startswith("/") and name in files and is_primary(name):
                    continue
                if provided.get(name) == (flags, version, pre):
                    continue
                pre = _is_pre(number)
                if seen.get(name) == (flags, version, pre):
                    continue
            epoch, ver, rel = versions.split_evr(version) if version else ("", "", "")
            entry = Entry(name, flags, epoch, ver, rel, pre)
            if kind == "provides":
                provided[name] = (flags, version, pre)
            if kind == "requires":
                if name.startswith("libc.so.6"):
                    if (
                        libc is None
                        or versions.compare(_libc_version(libc.name), _libc_version(name)) < 0
                    ):
                        libc = entry
                    continue
                seen[name] = (flags, version, pre)
            entries.append(entry)
        if libc is not None:
            entries.append(libc)
        if entries:
            found[kind] = entries
    return found


def _files(header: _Header) -> list[tuple[str, str]]:
    basenames = header.strings(_BASENAMES)
    directories = header.strings(_DIRNAMES)
    indexes = header.numbers(_DIRINDEXES)
    modes = header.numbers(_FILEMODES)
    flags = header.numbers(_FILEFLAGS)
    if not (len(indexes) == len(basenames) and len(modes) in (0, len(basenames))):
        raise InvalidPackage("its list of files does not hold together")
    files = []
    for number, (basename, index) in enumerate(zip(basenames, indexes, strict=True)):
        if index >= len(directories):
            raise InvalidPackage("its list of files names a directory it does not have")
        mode = modes[number] if modes else 0
        if mode & _FILE_TYPE == _DIRECTORY:
            kind = "dir"
        elif number < len(flags) and flags[number] & _RPMFILE_GHOST:
            kind = "ghost"
        else:
            kind = ""
        files.append((directories[index] + basename, kind))
    return files


def _changelogs(header: _Header) -> list[Changelog]:
    """The newest ten entries, oldest first.

    Of two entries with the same time, createrepo_c moves the newer one a second
    later, and so on along a run of them, so that each has a time of its own.
    """
    times = header.numbers(_CHANGELOGTIME)
    names = header.strings(_CHANGELOGNAME)
    texts = header.strings(_CHANGELOGTEXT)
    kept: list[list[Any]] = []  # oldest first
    last = None
    for time, name, text in list(zip(times, names, texts, strict=False))[:CHANGELOGS_KEPT]:
        kept.insert(0, [name.rstrip(" ") or name[:1], time, text])
        if time == last:
            moved = time
            for previous in kept[1:]:
                if previous[1] != moved:
                    break
                previous[1] += 1
                moved += 1
        else:
            last = time
    return [Changelog(author, date, text) for author, date, text in kept]


def describe(header: _Header, signature: _Header, start: int, end: int) -> Rpm:
    """What a package's headers say, as createrepo_c would list it."""
    name = header.string(_NAME)
    version = header.string(_VERSION)
    release = header.string(_RELEASE)
    arch = header.string(_ARCH)
    if not (name and version and release and arch):
        raise InvalidPackage("it says no name, version, release or architecture")
    if versions.NAME.fullmatch(name) is None:
        raise InvalidPackage(f"its name cannot be a package's: {name[:80]!r}")
    files = _files(header)
    epoch = header.numbers(_EPOCH)
    return Rpm(
        name=name,
        epoch=str(epoch[0]) if epoch else "0",
        version=version,
        release=release,
        arch=arch,
        summary=header.string(_SUMMARY),
        description=header.string(_DESCRIPTION),
        packager=header.string(_PACKAGER),
        url=header.string(_URL),
        license=header.string(_LICENSE),
        vendor=header.string(_VENDOR),
        group=header.string(_GROUP),
        buildhost=header.string(_BUILDHOST),
        sourcerpm=header.string(_SOURCERPM),
        build_time=header.number(_BUILDTIME),
        installed_size=header.number(_LONGSIZE, _SIZE),
        archive_size=signature.number(_SIG_LONGARCHIVESIZE, _SIG_PAYLOADSIZE)
        or header.number(_ARCHIVESIZE),
        header_start=start,
        header_end=end,
        dependencies=_dependencies(header, {path for path, _ in files}),
        files=files,
        changelogs=_changelogs(header),
    )


async def read(chunks: AsyncIterator[bytes]) -> Rpm:
    """What an RPM says of itself. Raises InvalidPackage.

    Reads no more of `chunks` than the lead and the headers: the caller closes them.
    """
    reader = _Reader(chunks)
    lead = await reader.exactly(_LEAD)
    if lead[:4] != _LEAD_MAGIC:
        raise InvalidPackage("it is not an RPM")
    if struct.unpack(">H", lead[6:8])[0] == _SOURCE:
        raise InvalidPackage("it is a source RPM, which dnf does not install")
    signature, length = await _header(reader, HEADER_MOST)
    padding = -length % 8
    await reader.exactly(padding)
    start = _LEAD + length + padding
    header, size = await _header(reader, HEADER_MOST - length)
    if _SOURCEPACKAGE in header:
        raise InvalidPackage("it is a source RPM, which dnf does not install")
    return describe(header, signature, start, start + size)
