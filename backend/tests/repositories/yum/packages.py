"""RPMs made in memory, laid out as rpmbuild lays them out, and the real ones it wrote."""

import struct
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

DATA = Path(__file__).parent / "data"
# Two packages rpmbuild 6.0 wrote, and what createrepo_c wrote of them: `data/make.sh`
# says how. `STORED_AT` is when createrepo_c found them, as its `<time file>` says.
HELLO = "megooarti-hello-1.0-1.noarch.rpm"
TOOL = "megooarti-tool-0.3-2.x86_64.rpm"
SOURCE = "megooarti-hello-1.0-1.src.rpm"
STORED_AT = 1792005637
# Two of Fedora 44's packages, kept to the end of their headers (all that is read of
# one), and what createrepo_c wrote of the whole files: `data/real.sh` says how. Each
# whole file's size and SHA-256, and when createrepo_c found it.
REAL = {
    "bash-5.3.9-3.fc44.x86_64.rpm": (
        1985877,
        "2ccb046d638f5ad23f5613222a78ee71067dc43f0bdf03b60ce311536bc4bed5",
        1792005894,
    ),
    "setup-2.15.0-28.fc44.noarch.rpm": (
        160947,
        "55d58325996df10b4be2f1a9b963dbec3cea3099e43f9f4295eea6e8adfaf7b8",
        1792005894,
    ),
}

# The types of a header's values, and the tags these tests write.
INT16, INT32, STRING, BIN, STRING_ARRAY, I18NSTRING = 3, 4, 6, 7, 8, 9
NAME, VERSION, RELEASE, EPOCH, SUMMARY, DESCRIPTION, BUILDTIME = range(1000, 1007)
SIZE, LICENSE, ARCH, SOURCERPM, SOURCEPACKAGE = 1009, 1014, 1022, 1044, 1106
FILEMODES, FILEFLAGS, DIRINDEXES, BASENAMES, DIRNAMES = 1030, 1037, 1116, 1117, 1118
REQUIRENAME, REQUIREFLAGS, REQUIREVERSION = 1049, 1048, 1050
PROVIDENAME, PROVIDEFLAGS, PROVIDEVERSION = 1047, 1112, 1113
CHANGELOGTIME, CHANGELOGNAME, CHANGELOGTEXT = 1080, 1081, 1082
PAYLOADSIZE = 1007  # in the signature header

type Value = str | bytes | list[str] | list[int]


def header(tags: dict[int, tuple[int, Value]]) -> bytes:
    """A header: its magic, its index of tags, and its store, each value aligned."""
    index, store = bytearray(), bytearray()
    for tag, (kind, value) in sorted(tags.items()):
        if kind == INT32:
            store += b"\0" * (-len(store) % 4)
            data, count = struct.pack(f">{len(value)}I", *value), len(value)
        elif kind == INT16:
            store += b"\0" * (-len(store) % 2)
            data, count = struct.pack(f">{len(value)}H", *value), len(value)
        elif kind == STRING:
            data, count = value.encode() + b"\0" if isinstance(value, str) else value + b"\0", 1
        elif kind == BIN:
            data, count = value, len(value)
        else:
            data, count = b"".join(item.encode() + b"\0" for item in value), len(value)
        index += struct.pack(">IIII", tag, kind, len(store), count)
        store += data
    count = len(index) // 16
    return b"\x8e\xad\xe8\x01\0\0\0\0" + struct.pack(">II", count, len(store)) + index + store


def lead(name: str, *, source: bool = False) -> bytes:
    return (
        b"\xed\xab\xee\xdb\x03\x00"
        + struct.pack(">HH", 1 if source else 0, 1)
        + name.encode()[:65].ljust(66, b"\0")
        + struct.pack(">HH", 1, 5)
        + b"\0" * 16
    )


def make_rpm(
    name: str = "megooarti-hello",
    version: str = "1.0",
    release: str = "1",
    arch: str = "noarch",
    *,
    epoch: int | None = None,
    summary: str = "Says hello",
    requires: Sequence[tuple[str, int, str]] = (("bash", 0, ""),),
    files: Sequence[str] = ("/usr/bin/megooarti-hello",),
    changelog: Sequence[tuple[int, str, str]] = (),
    source: bool = False,
    extra: dict[int, tuple[int, Value]] | None = None,
    payload: bytes = b"the files, packed",
) -> bytes:
    """An RPM that says what it is given, as rpmbuild lays one out."""
    directories = sorted({path.rpartition("/")[0] + "/" for path in files})
    tags: dict[int, tuple[int, Value]] = {
        NAME: (STRING, name),
        VERSION: (STRING, version),
        RELEASE: (STRING, release),
        SUMMARY: (I18NSTRING, [summary]),
        DESCRIPTION: (I18NSTRING, [f"{summary}, at length."]),
        BUILDTIME: (INT32, [1792000000]),
        SIZE: (INT32, [len(payload)]),
        LICENSE: (STRING, "MIT"),
        ARCH: (STRING, arch),
        PROVIDENAME: (STRING_ARRAY, [name]),
        PROVIDEFLAGS: (INT32, [8]),
        PROVIDEVERSION: (STRING_ARRAY, [f"{version}-{release}"]),
    }
    if epoch is not None:
        tags[EPOCH] = (INT32, [epoch])
    if not source:
        tags[SOURCERPM] = (STRING, f"{name}-{version}-{release}.src.rpm")
    else:
        tags[SOURCEPACKAGE] = (INT32, [1])
    if files:
        tags[BASENAMES] = (STRING_ARRAY, [path.rpartition("/")[2] for path in files])
        tags[DIRNAMES] = (STRING_ARRAY, directories)
        tags[DIRINDEXES] = (
            INT32,
            [directories.index(path.rpartition("/")[0] + "/") for path in files],
        )
        tags[FILEMODES] = (INT16, [0o100644] * len(files))
        tags[FILEFLAGS] = (INT32, [0] * len(files))
    if requires:
        tags[REQUIRENAME] = (STRING_ARRAY, [said for said, _, _ in requires])
        tags[REQUIREFLAGS] = (INT32, [flags for _, flags, _ in requires])
        tags[REQUIREVERSION] = (STRING_ARRAY, [version for _, _, version in requires])
    if changelog:
        tags[CHANGELOGTIME] = (INT32, [time for time, _, _ in changelog])
        tags[CHANGELOGNAME] = (STRING_ARRAY, [author for _, author, _ in changelog])
        tags[CHANGELOGTEXT] = (STRING_ARRAY, [text for _, _, text in changelog])
    tags.update(extra or {})
    signature = header({PAYLOADSIZE: (INT32, [len(payload)])})
    signature += b"\0" * (-len(signature) % 8)
    return lead(f"{name}-{version}-{release}", source=source) + signature + header(tags) + payload


async def pieces(data: bytes, size: int = 1000) -> AsyncIterator[bytes]:
    """Bytes as they arrive, a piece at a time."""
    for at in range(0, len(data), size):
        yield data[at : at + size]
