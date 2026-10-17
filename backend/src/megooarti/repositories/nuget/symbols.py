"""What a symbol server (SSQP) keeps of a portable PDB: its key, and its checksum.

Pure functions. A portable PDB is ECMA-335 metadata: it begins with `BSJB`, and its
`#Pdb` stream begins with its id, a GUID and a stamp. A debugger asks for it at
`<name>/<GUID>FFFFFFFF/<name>`, the name in lower case and the GUID as 32 hex digits,
and says which it wants by its checksum (`SymbolChecksum: SHA256:<hex>`): the SHA-256
of the file with its id's 20 bytes set to 0, as the module's debug directory has it.
"""

import hashlib
import re
import struct
import uuid
from dataclasses import dataclass

from megooarti.repositories.nuget import packages
from megooarti.repositories.nuget.packages import InvalidPackage

PREFIX = "symbols/"
# What is read of a symbol package (section 9 of the spec).
PDBS_MOST = 1000
PDB_MOST = 256 * 1024 * 1024
_PORTABLE = b"BSJB"
_WINDOWS = b"Microsoft C/C++ MSF 7.00"
_ID_SIZE = 20
_NAME = re.compile(r"[a-z0-9_.+-]+\.pdb")
_KEY = re.compile(r"[0-9a-f]{32}FFFFFFFF")
# What a client may name in `SymbolChecksum`: SHA-256 alone, as a portable PDB's is.
_CHECKSUM = re.compile(r"SHA256:([0-9A-Fa-f]{64})")


@dataclass(frozen=True)
class Pdb:
    """A portable PDB, as a symbol server keeps it."""

    name: str  # its file's name, in lower case
    guid: str  # 32 hex digits, in lower case
    checksum: str  # SHA-256, 64 hex digits in lower case

    @property
    def path(self) -> str:
        return f"{PREFIX}{self.name}/{self.guid}FFFFFFFF/{self.name}"


def _streams(data: bytes) -> dict[str, tuple[int, int]]:
    """The metadata's streams, by name: where each is, and how long."""
    try:
        (length,) = struct.unpack_from("<I", data, 12)
        at = 16 + ((length + 3) & ~3)
        _, count = struct.unpack_from("<HH", data, at)
        at += 4
        found = {}
        for _ in range(count):
            offset, size = struct.unpack_from("<II", data, at)
            end = data.index(b"\0", at + 8)
            name = data[at + 8 : end].decode("ascii")
            found[name] = (offset, size)
            at = at + 8 + ((end - (at + 8) + 4) & ~3)
        return found
    except (struct.error, ValueError, UnicodeDecodeError):
        raise InvalidPackage("a .pdb in it has metadata that cannot be read") from None


def read(name: str, data: bytes) -> Pdb:
    """A portable PDB, by its file's name. Raises InvalidPackage for a Windows PDB, or
    for a file that is no PDB."""
    lower = name.rsplit("/", 1)[-1].lower()
    if data.startswith(_WINDOWS):
        raise InvalidPackage(f"{lower} is a Windows PDB: a symbol package has portable PDBs")
    if not data.startswith(_PORTABLE):
        raise InvalidPackage(f"{lower} is not a portable PDB")
    if not _NAME.fullmatch(lower):
        raise InvalidPackage(f"{lower} is not a name a symbol server can serve")
    stream = _streams(data).get("#Pdb")
    if stream is None or stream[1] < _ID_SIZE or stream[0] + _ID_SIZE > len(data):
        raise InvalidPackage(f"{lower} has no PDB id")
    start = stream[0]
    pdb_id = data[start : start + _ID_SIZE]
    guid = uuid.UUID(bytes_le=pdb_id[:16]).hex
    zeroed = data[:start] + b"\0" * _ID_SIZE + data[start + _ID_SIZE :]
    return Pdb(lower, guid, hashlib.sha256(zeroed).hexdigest())


def is_path(path: str) -> bool:
    """Whether a path is one a symbol server serves a portable PDB at."""
    parts = path.split("/")
    return (
        len(parts) == 4
        and parts[0] == PREFIX.rstrip("/")
        and parts[1] == parts[3]
        and _NAME.fullmatch(parts[1]) is not None
        and _KEY.fullmatch(parts[2]) is not None
    )


def asked(header: str | None) -> set[str] | None:
    """The checksums a client's `SymbolChecksum` names, in lower case; None if it sent
    none, which asks for the file whatever its checksum."""
    if header is None:
        return None
    return {found.lower() for found in _CHECKSUM.findall(header)}


async def entries(read: packages.Read, size: int) -> list[packages.Entry]:
    """The PDBs of a symbol package: the files of its zip named `.pdb`."""
    found = [
        entry for entry in await packages.entries(read, size) if entry.name.lower().endswith(".pdb")
    ]
    if len(found) > PDBS_MOST:
        raise InvalidPackage(f"it has more than {PDBS_MOST} PDBs")
    return found
