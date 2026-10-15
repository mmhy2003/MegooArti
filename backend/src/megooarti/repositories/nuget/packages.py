"""What a NuGet package says of itself: the `.nuspec` in its zip.

A package can be gigabytes, so it is never unpacked. Its zip is read from the end, where
the directory of its entries is, and only the `.nuspec` is inflated, to a bound. The
bytes are asked for by position (`Read`), so that the caller decides where they come
from. Pure, but for that.
"""

import struct
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any
from xml.etree import ElementTree
from xml.parsers import expat

from megooarti.repositories.nuget import versions

# The bounds of what is read of a package (section 9 of the spec).
ENTRIES_MOST = 10_000
NUSPEC_MOST = 1024 * 1024
# A directory of that many files, with names of an ordinary length, is far less than this.
DIRECTORY_MOST = 16 * 1024 * 1024
_DEPTH_MOST = 32
_ELEMENTS_MOST = 20_000
# A zip's end record, and its comment at the most.
_END = b"PK\x05\x06"
_END_SIZE = 22
_TAIL_MOST = _END_SIZE + 0xFFFF
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"
# A file's entry in the directory: its signature, versions, flags, method, time, date,
# CRC, sizes, the lengths of its name, extra field and comment, and where it is.
_CENTRAL_HEADER = "<4sHHHHHHIIIHHHHHII"
_STORED, _DEFLATED = 0, 8
SYMBOLS = "SymbolsPackage"

# The bytes of a package from a position, as many as asked for (fewer at its end).
Read = Callable[[int, int], Awaitable[bytes]]


class InvalidPackage(Exception):
    """A file that is not a NuGet package that can be accepted. The message says why."""


@dataclass(frozen=True)
class Entry:
    """A file in a package's zip, as its directory describes it."""

    name: str
    method: int
    compressed: int
    size: int
    offset: int  # of its local header


@dataclass(frozen=True)
class Dependency:
    id: str
    range: str  # as NuGet writes a range: `[1.0.0, )` for "1.0.0 or later"


@dataclass(frozen=True)
class DependencyGroup:
    target_framework: str  # "" for every framework
    dependencies: tuple[Dependency, ...] = ()


@dataclass(frozen=True)
class Nuspec:
    """What a package's `.nuspec` says: what NuGet's feeds publish of it."""

    id: str
    version: str  # normalized
    original_version: str  # as the package wrote it
    title: str = ""
    authors: str = ""
    owners: str = ""
    description: str = ""
    summary: str = ""
    release_notes: str = ""
    copyright: str = ""
    language: str = ""
    tags: str = ""
    project_url: str = ""
    license_url: str = ""
    license_expression: str = ""
    icon_url: str = ""
    readme: str = ""
    require_license_acceptance: bool = False
    development_dependency: bool = False
    min_client_version: str = ""
    package_types: tuple[str, ...] = ()
    dependency_groups: tuple[DependencyGroup, ...] = field(default=())

    @property
    def is_symbols(self) -> bool:
        """Whether it is a symbol package (`.snupkg`), which goes beside its package."""
        return SYMBOLS in self.package_types

    @property
    def is_prerelease(self) -> bool:
        parsed = versions.parse(self.version)
        return parsed is not None and parsed.is_prerelease

    def as_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, said: dict[str, Any]) -> "Nuspec":
        groups = tuple(
            DependencyGroup(
                group["target_framework"],
                tuple(Dependency(**dependency) for dependency in group["dependencies"]),
            )
            for group in said.get("dependency_groups", [])
        )
        plain = {
            key: value
            for key, value in said.items()
            if key in cls.__dataclass_fields__ and key not in ("dependency_groups", "package_types")
        }
        return cls(
            **plain, package_types=tuple(said.get("package_types", [])), dependency_groups=groups
        )


# --- The zip --------------------------------------------------------------------------


async def entries(read: Read, size: int) -> list[Entry]:
    """The files a package's zip has, from its directory at the end."""
    tail_start = max(0, size - _TAIL_MOST)
    tail = await read(tail_start, size - tail_start)
    at = tail.rfind(_END)
    if at < 0 or len(tail) - at < _END_SIZE:
        raise InvalidPackage("it is not a zip file")
    (_, _, _, _, count, length, start, _) = struct.unpack("<4sHHHHIIH", tail[at : at + _END_SIZE])
    if count == 0xFFFF or length == 0xFFFFFFFF or start == 0xFFFFFFFF:
        raise InvalidPackage("it is a ZIP64 file: a package of 4 GiB or more is not accepted")
    if count > ENTRIES_MOST:
        raise InvalidPackage(f"it has more than {ENTRIES_MOST} files")
    if length > DIRECTORY_MOST:
        raise InvalidPackage(f"its zip directory is larger than {DIRECTORY_MOST} bytes")
    if start + length > size:
        raise InvalidPackage("its zip directory is not where its end says")
    directory = await read(start, length)
    found, position = [], 0
    for _ in range(count):
        header = directory[position : position + 46]
        if len(header) < 46 or header[:4] != _CENTRAL:
            raise InvalidPackage("its zip directory is broken")
        fields = struct.unpack(_CENTRAL_HEADER, header)
        flags, method, compressed, unpacked = fields[3], fields[4], fields[8], fields[9]
        name_length, extra_length, comment_length, offset = (
            fields[10],
            fields[11],
            fields[12],
            fields[16],
        )
        raw = directory[position + 46 : position + 46 + name_length]
        if flags & 0x1:
            raise InvalidPackage("it has an encrypted file")
        name = raw.decode("utf-8" if flags & 0x800 else "cp437", errors="replace")
        found.append(Entry(name, method, compressed, unpacked, offset))
        position += 46 + name_length + extra_length + comment_length
    return found


async def extract(read: Read, entry: Entry, most: int) -> bytes:
    """One file of the zip, inflated: at most `most` bytes of it."""
    if entry.size > most:
        raise InvalidPackage(f"{entry.name} is larger than {most} bytes")
    local = await read(entry.offset, 30)
    if len(local) < 30 or local[:4] != _LOCAL:
        raise InvalidPackage(f"{entry.name} is not where the zip directory says")
    name_length, extra_length = struct.unpack("<HH", local[26:30])
    data = await read(entry.offset + 30 + name_length + extra_length, entry.compressed)
    if len(data) != entry.compressed:
        raise InvalidPackage(f"{entry.name} is cut short")
    if entry.method == _STORED:
        content = data
    elif entry.method == _DEFLATED:
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            content = inflater.decompress(data, most + 1)
        except zlib.error:
            raise InvalidPackage(f"{entry.name} cannot be inflated") from None
    else:
        raise InvalidPackage(f"{entry.name} is compressed in a way NuGet does not use")
    if len(content) > most or len(content) != entry.size:
        raise InvalidPackage(f"{entry.name} is not the size the zip directory says")
    return content


def nuspec_entry(found: list[Entry]) -> Entry:
    """The package's `.nuspec`: the one file of that kind at the zip's top."""
    at_top = [entry for entry in found if "/" not in entry.name and entry.name.endswith(".nuspec")]
    if len(at_top) != 1:
        raise InvalidPackage("it does not have exactly one .nuspec at its top")
    return at_top[0]


@dataclass(frozen=True)
class Package:
    """What was read of a package: what its `.nuspec` says, and the `.nuspec` itself."""

    nuspec: Nuspec
    spec: bytes


async def read(read: Read, size: int) -> Package:
    """What a package says of itself. Raises InvalidPackage."""
    found = await entries(read, size)
    spec = await extract(read, nuspec_entry(found), NUSPEC_MOST)
    return Package(parse_nuspec(spec), spec)


# --- The .nuspec ----------------------------------------------------------------------


def _refuse_doctype(*_: object) -> None:
    raise InvalidPackage("its .nuspec has a DOCTYPE, which is not allowed")


def _tree(data: bytes) -> ElementTree.Element:
    """The `.nuspec`'s elements, by their names without a namespace."""
    builder = ElementTree.TreeBuilder()
    depth = elements = 0

    def start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal depth, elements
        depth, elements = depth + 1, elements + 1
        if depth > _DEPTH_MOST or elements > _ELEMENTS_MOST:
            raise InvalidPackage("its .nuspec is too large to read")
        local = {name.rpartition(" ")[2]: value for name, value in attributes.items()}
        builder.start(tag.rpartition(" ")[2], local)

    def end(tag: str) -> None:
        nonlocal depth
        depth -= 1
        builder.end(tag.rpartition(" ")[2])

    # A namespace is given as `<uri> <name>`: each schema's `.nuspec` is read alike.
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise InvalidPackage(f"its .nuspec is not well-formed XML (line {error.lineno})") from None
    except (ValueError, LookupError):
        raise InvalidPackage("its .nuspec is in an encoding that cannot be read") from None
    return builder.close()


def _text(parent: ElementTree.Element, name: str) -> str:
    child = parent.find(name)
    return "" if child is None else (child.text or "").strip()


def _flag(parent: ElementTree.Element, name: str) -> bool:
    return _text(parent, name).lower() == "true"


def _range(written: str) -> str:
    """A dependency's range as NuGet writes one: a bare version is that version or later."""
    written = written.strip()
    if not written:
        return "(, )"
    if written[0] in "[(":
        return written
    normalized = versions.normalize(written)
    return f"[{normalized or written}, )"


def _dependencies(parent: ElementTree.Element) -> tuple[Dependency, ...]:
    return tuple(
        Dependency(element.get("id", "").strip(), _range(element.get("version", "")))
        for element in parent.findall("dependency")
        if element.get("id", "").strip()
    )


def _groups(metadata: ElementTree.Element) -> tuple[DependencyGroup, ...]:
    dependencies = metadata.find("dependencies")
    if dependencies is None:
        return ()
    groups = [
        DependencyGroup(group.get("targetFramework", "").strip(), _dependencies(group))
        for group in dependencies.findall("group")
    ]
    flat = _dependencies(dependencies)
    if flat:
        groups.insert(0, DependencyGroup("", flat))
    return tuple(groups)


def parse_nuspec(data: bytes) -> Nuspec:
    """What a `.nuspec` says. Raises InvalidPackage."""
    root = _tree(data)
    metadata = root.find("metadata") if root.tag == "package" else None
    if metadata is None:
        raise InvalidPackage("its .nuspec has no <package><metadata>")
    package_id = _text(metadata, "id")
    if not versions.is_id(package_id):
        raise InvalidPackage(f"its id is not one NuGet takes: {package_id[:100]!r}")
    written = _text(metadata, "version")
    version = versions.parse(written)
    if version is None:
        raise InvalidPackage(f"its version is not one NuGet takes: {written[:64]!r}")
    license_element = metadata.find("license")
    expression = ""
    if license_element is not None and license_element.get("type") == "expression":
        expression = (license_element.text or "").strip()
    types = metadata.find("packageTypes")
    package_types = (
        ()
        if types is None
        else tuple(
            element.get("name", "")
            for element in types.findall("packageType")
            if element.get("name")
        )
    )
    return Nuspec(
        id=package_id,
        version=version.normalized,
        original_version=written,
        title=_text(metadata, "title"),
        authors=_text(metadata, "authors"),
        owners=_text(metadata, "owners"),
        description=_text(metadata, "description"),
        summary=_text(metadata, "summary"),
        release_notes=_text(metadata, "releaseNotes"),
        copyright=_text(metadata, "copyright"),
        language=_text(metadata, "language"),
        tags=_text(metadata, "tags"),
        project_url=_text(metadata, "projectUrl"),
        license_url=_text(metadata, "licenseUrl"),
        license_expression=expression,
        icon_url=_text(metadata, "iconUrl"),
        readme=_text(metadata, "readme"),
        require_license_acceptance=_flag(metadata, "requireLicenseAcceptance"),
        development_dependency=_flag(metadata, "developmentDependency"),
        min_client_version=metadata.get("minClientVersion", ""),
        package_types=package_types,
        dependency_groups=_groups(metadata),
    )
