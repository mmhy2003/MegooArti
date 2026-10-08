"""maven-metadata.xml: build it from what a repository holds, read it safely, write it.

Pure functions. Reading uses expat directly so that any DOCTYPE is refused before an
entity can be declared: metadata never needs one, and entities are how XML is abused.
"""

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.parsers import expat

from megooarti.repositories.maven.paths import SNAPSHOT, MavenPath
from megooarti.repositories.maven.versions import sorted_versions

# Longer than any real coordinate; a field beyond it is ignored.
_MAX_FIELD = 255
_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'
# Real metadata nests five levels and lists a few thousand versions at most. These
# bound what a document can cost to read, whoever sent it.
_MAX_DEPTH = 16
_MAX_ELEMENTS = 100_000


class InvalidMetadata(Exception):
    """The bytes are not a metadata document. The message says why."""


@dataclass(frozen=True)
class Plugin:
    name: str
    prefix: str
    artifact_id: str


@dataclass(frozen=True)
class SnapshotVersion:
    classifier: str
    extension: str
    value: str  # the version in the file name: 1.0-20261008.101500-3
    updated: str


@dataclass(frozen=True)
class Metadata:
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    versions: tuple[str, ...] = ()
    latest: str = ""
    release: str = ""
    snapshot_timestamp: str = ""
    snapshot_build: int | None = None
    snapshot_versions: tuple[SnapshotVersion, ...] = ()
    last_updated: str = ""
    plugins: tuple[Plugin, ...] = ()


def stamp(moment: datetime) -> str:
    """A time as metadata writes it: yyyyMMddHHmmss, in UTC."""
    return moment.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def for_artifact(
    group_id: str,
    artifact_id: str,
    versions: Mapping[str, datetime],
    plugins: Iterable[Plugin] = (),
) -> Metadata | None:
    """The document for an artifact's directory: its versions, and any plugins there.

    `versions` maps each version to when its files last changed.
    """
    plugins = tuple(plugins)
    if not versions:
        return Metadata(plugins=plugins) if plugins else None
    ordered = sorted_versions(versions)
    releases = [version for version in ordered if not version.endswith(SNAPSHOT)]
    return Metadata(
        group_id=group_id,
        artifact_id=artifact_id,
        versions=tuple(ordered),
        latest=ordered[-1],
        release=releases[-1] if releases else "",
        last_updated=stamp(max(versions.values())),
        plugins=plugins,
    )


def for_snapshot(
    group_id: str,
    artifact_id: str,
    version: str,
    files: Iterable[tuple[MavenPath, datetime]],
) -> Metadata | None:
    """The document for a snapshot version's directory, from its files.

    For each classifier and extension it names the highest build. An old-style name
    (app-1.0-SNAPSHOT.jar) counts as the lowest build of all.
    """
    base = version.removesuffix(SNAPSHOT)
    highest: dict[tuple[str, str], tuple[tuple[int, str], str, datetime]] = {}
    latest_build: tuple[int, str] | None = None
    changed: datetime | None = None
    for parsed, modified in files:
        if parsed.build is None:
            rank, value = (-1, ""), version
        else:
            timestamp, number = parsed.build
            rank, value = (number, timestamp), f"{base}-{timestamp}-{number}"
            if latest_build is None or rank > latest_build:
                latest_build = rank
        key = (parsed.classifier, parsed.extension)
        if key not in highest or rank > highest[key][0]:
            highest[key] = (rank, value, modified)
        if changed is None or modified > changed:
            changed = modified
    if changed is None:
        return None
    return Metadata(
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        snapshot_timestamp="" if latest_build is None else latest_build[1],
        snapshot_build=None if latest_build is None else latest_build[0],
        snapshot_versions=tuple(
            SnapshotVersion(classifier, extension, value, stamp(modified))
            for (classifier, extension), (_, value, modified) in sorted(highest.items())
        ),
        last_updated=stamp(changed),
    )


def merge_plugins(stored: Iterable[Plugin], uploaded: Iterable[Plugin]) -> tuple[Plugin, ...]:
    """Stored plugin entries with uploaded ones added, the upload winning per artifact."""
    by_artifact = {plugin.artifact_id: plugin for plugin in stored}
    by_artifact.update({plugin.artifact_id: plugin for plugin in uploaded})
    return tuple(
        sorted(by_artifact.values(), key=lambda plugin: (plugin.prefix, plugin.artifact_id))
    )


def merge(documents: Sequence[Metadata]) -> Metadata | None:
    """Several repositories' documents for one path, as one. None if there are none.

    Versions are the union, and `latest` and `release` are worked out again from it:
    a member's own answer describes only that member. Where two documents disagree
    about the same thing, the earlier one wins.
    """
    if not documents:
        return None
    versions = sorted_versions(version for document in documents for version in document.versions)
    releases = [version for version in versions if not version.endswith(SNAPSHOT)]

    def built(document: Metadata) -> tuple[str, int]:
        build = -1 if document.snapshot_build is None else document.snapshot_build
        return document.snapshot_timestamp, build

    newest = max(documents, key=built)

    files: dict[tuple[str, str], SnapshotVersion] = {}
    plugins: dict[str, Plugin] = {}
    for document in documents:
        for entry in document.snapshot_versions:
            key = (entry.classifier, entry.extension)
            if key not in files or entry.updated > files[key].updated:
                files[key] = entry
        for plugin in document.plugins:
            plugins.setdefault(plugin.prefix, plugin)

    def first(values: Iterable[str]) -> str:
        return next((value for value in values if value), "")

    return Metadata(
        group_id=first(document.group_id for document in documents),
        artifact_id=first(document.artifact_id for document in documents),
        version=first(document.version for document in documents),
        versions=tuple(versions),
        latest=versions[-1] if versions else "",
        release=releases[-1] if releases else "",
        snapshot_timestamp=newest.snapshot_timestamp,
        snapshot_build=newest.snapshot_build,
        snapshot_versions=tuple(files[key] for key in sorted(files)),
        last_updated=max(document.last_updated for document in documents),
        plugins=tuple(
            sorted(plugins.values(), key=lambda plugin: (plugin.prefix, plugin.artifact_id))
        ),
    )


def _add(parent: ET.Element, name: str, value: str) -> None:
    if value:
        ET.SubElement(parent, name).text = value


def serialise(metadata: Metadata) -> bytes:
    """The document as XML, with elements in the order Maven writes them."""
    root = ET.Element("metadata")
    if metadata.snapshot_versions:
        root.set("modelVersion", "1.1.0")
    _add(root, "groupId", metadata.group_id)
    _add(root, "artifactId", metadata.artifact_id)
    _add(root, "version", metadata.version)

    versioning = ET.Element("versioning")
    _add(versioning, "latest", metadata.latest)
    _add(versioning, "release", metadata.release)
    if metadata.snapshot_timestamp or metadata.snapshot_build is not None:
        snapshot = ET.SubElement(versioning, "snapshot")
        _add(snapshot, "timestamp", metadata.snapshot_timestamp)
        if metadata.snapshot_build is not None:
            _add(snapshot, "buildNumber", str(metadata.snapshot_build))
    if metadata.versions:
        versions = ET.SubElement(versioning, "versions")
        for version in metadata.versions:
            _add(versions, "version", version)
    _add(versioning, "lastUpdated", metadata.last_updated)
    if metadata.snapshot_versions:
        listed = ET.SubElement(versioning, "snapshotVersions")
        for entry in metadata.snapshot_versions:
            element = ET.SubElement(listed, "snapshotVersion")
            _add(element, "classifier", entry.classifier)
            _add(element, "extension", entry.extension)
            _add(element, "value", entry.value)
            _add(element, "updated", entry.updated)
    if len(versioning):
        root.append(versioning)

    if metadata.plugins:
        plugins = ET.SubElement(root, "plugins")
        for plugin in metadata.plugins:
            element = ET.SubElement(plugins, "plugin")
            _add(element, "name", plugin.name)
            _add(element, "prefix", plugin.prefix)
            _add(element, "artifactId", plugin.artifact_id)

    ET.indent(root)
    return _DECLARATION + ET.tostring(root, encoding="utf-8") + b"\n"


def _refuse_doctype(*_: object) -> None:
    raise InvalidMetadata("it has a DOCTYPE, which is not allowed")


def _tree(data: bytes) -> ET.Element:
    builder = ET.TreeBuilder()
    depth = 0
    elements = 0

    def start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal depth, elements
        depth += 1
        elements += 1
        if depth > _MAX_DEPTH:
            raise InvalidMetadata("it is nested too deeply")
        if elements > _MAX_ELEMENTS:
            raise InvalidMetadata("it has too many elements")
        builder.start(tag, attributes)

    def end(tag: str) -> None:
        nonlocal depth
        depth -= 1
        builder.end(tag)

    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise InvalidMetadata(f"it is not well-formed XML (line {error.lineno})") from None
    except (ValueError, LookupError):
        # It declares an encoding expat cannot read: a multi-byte one, or one unknown.
        raise InvalidMetadata("it is in an encoding that cannot be read") from None
    return builder.close()


def _text(parent: ET.Element | None, name: str) -> str:
    """A child element's text, or "" if it is absent, empty or implausibly long."""
    child = None if parent is None else parent.find(name)
    if child is None:
        return ""
    text = (child.text or "").strip()
    return text if len(text) <= _MAX_FIELD else ""


def _own_text(element: ET.Element) -> str:
    text = (element.text or "").strip()
    return text if len(text) <= _MAX_FIELD else ""


def _number(text: str) -> int | None:
    return int(text) if text.isascii() and text.isdigit() and len(text) <= 9 else None


def parse(data: bytes) -> Metadata:
    """Read a metadata document. Raises InvalidMetadata; unknown elements are ignored."""
    root = _tree(data)
    if root.tag != "metadata":
        raise InvalidMetadata("its root element is not <metadata>")
    versioning = root.find("versioning")
    snapshot = None if versioning is None else versioning.find("snapshot")

    versions = [] if versioning is None else versioning.findall("versions/version")
    listed = [] if versioning is None else versioning.findall("snapshotVersions/snapshotVersion")
    snapshot_versions = [
        SnapshotVersion(
            classifier=_text(entry, "classifier"),
            extension=_text(entry, "extension"),
            value=_text(entry, "value"),
            updated=_text(entry, "updated"),
        )
        for entry in listed
    ]
    plugins = [
        Plugin(
            name=_text(entry, "name"),
            prefix=_text(entry, "prefix"),
            artifact_id=_text(entry, "artifactId"),
        )
        for entry in root.findall("plugins/plugin")
    ]
    return Metadata(
        group_id=_text(root, "groupId"),
        artifact_id=_text(root, "artifactId"),
        version=_text(root, "version"),
        versions=tuple(text for element in versions if (text := _own_text(element))),
        latest=_text(versioning, "latest"),
        release=_text(versioning, "release"),
        snapshot_timestamp=_text(snapshot, "timestamp"),
        snapshot_build=_number(_text(snapshot, "buildNumber")),
        snapshot_versions=tuple(
            entry for entry in snapshot_versions if entry.extension and entry.value
        ),
        last_updated=_text(versioning, "lastUpdated"),
        plugins=tuple(plugin for plugin in plugins if plugin.prefix and plugin.artifact_id),
    )
