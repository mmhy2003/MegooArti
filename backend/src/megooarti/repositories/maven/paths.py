"""Maven repository paths: what kind of path this is, and whose file.

Pure functions over the Maven 2 repository layout:
<group dirs>/<artifactId>/<version>/<artifactId>-<version>[-<classifier>].<extension>
"""

import re
from dataclasses import dataclass

CHECKSUM_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")
METADATA_FILE = "maven-metadata.xml"
CATALOG = "archetype-catalog.xml"
SNAPSHOT = "-SNAPSHOT"
VERSION_POLICIES = ("release", "snapshot", "mixed")
LAYOUT_POLICIES = ("strict", "permissive")

# What the component table can hold.
_MAX_VERSION_LENGTH = 255
# The timestamp and build number in a snapshot file name: 20261008.101500-3
_BUILD = re.compile(r"([0-9]{8}\.[0-9]{6})-([0-9]{1,9})")
_CONTENT_TYPES = {
    "pom": "application/xml",
    "xml": "application/xml",
    "jar": "application/java-archive",
    "war": "application/java-archive",
    "ear": "application/java-archive",
    "module": "application/json",
    "asc": "text/plain",
}


@dataclass(frozen=True)
class MavenPath:
    """A path, classified. Fields that do not apply to its kind are left empty."""

    kind: str  # artifact, metadata, snapshot_metadata, catalog or other
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""  # the version directory: 1.0 or 1.0-SNAPSHOT
    classifier: str = ""
    extension: str = ""
    build: tuple[str, int] | None = None  # timestamp and number of a timestamped snapshot
    plugin_group: str = ""  # metadata only: the directory read as a group ID

    @property
    def is_metadata(self) -> bool:
        return self.kind in ("metadata", "snapshot_metadata")

    @property
    def is_snapshot(self) -> bool:
        return self.version.endswith(SNAPSHOT)


_OTHER = MavenPath("other")


def split_checksum(path: str) -> tuple[str, str | None]:
    """The path a checksum file belongs to, and its algorithm; `(path, None)` if not one."""
    target, dot, suffix = path.rpartition(".")
    if dot and target and not target.endswith("/") and suffix in CHECKSUM_ALGORITHMS:
        return target, suffix
    return path, None


def _group_id(directories: list[str]) -> str | None:
    """Directories as a group ID. A dot in one would make two paths share a group ID."""
    if not directories or any("." in directory for directory in directories):
        return None
    return ".".join(directories)


def _is_snapshot_version(version: str) -> bool:
    return version.endswith(SNAPSHOT) and len(version) > len(SNAPSHOT)


def _metadata(directories: list[str]) -> MavenPath | None:
    if not directories:
        return None
    if len(directories) >= 3 and _is_snapshot_version(directories[-1]):
        group_id = _group_id(directories[:-2])
        if group_id is None or len(directories[-1]) > _MAX_VERSION_LENGTH:
            return None
        return MavenPath(
            "snapshot_metadata",
            group_id=group_id,
            artifact_id=directories[-2],
            version=directories[-1],
        )
    # The same directory can be an artifact (com.acme:app) and a group (com.acme.app).
    as_artifact = _group_id(directories[:-1])
    as_group = _group_id(directories)
    if as_artifact is None and as_group is None:
        return None
    return MavenPath(
        "metadata",
        group_id=as_artifact or "",
        artifact_id=directories[-1] if as_artifact else "",
        plugin_group=as_group or "",
    )


def _artifact(segments: list[str]) -> MavenPath | None:
    if len(segments) < 4:
        return None
    *directories, artifact_id, version, filename = segments
    group_id = _group_id(directories)
    if group_id is None or len(version) > _MAX_VERSION_LENGTH:
        return None

    build = None
    if version.endswith(SNAPSHOT):
        if not _is_snapshot_version(version):
            return None
        prefix = f"{artifact_id}-{version.removesuffix(SNAPSHOT)}-"
        if not filename.startswith(prefix):
            return None
        rest = filename[len(prefix) :]
        timestamped = _BUILD.match(rest)
        if timestamped is not None:
            build = (timestamped[1], int(timestamped[2]))
            rest = rest[timestamped.end() :]
        elif rest.startswith("SNAPSHOT"):
            rest = rest.removeprefix("SNAPSHOT")
        else:
            return None
    else:
        prefix = f"{artifact_id}-{version}"
        if not filename.startswith(prefix):
            return None
        rest = filename[len(prefix) :]

    # What is left is "-classifier.extension" or ".extension".
    if rest.startswith("-"):
        classifier, dot, extension = rest[1:].partition(".")
        if not classifier:
            return None
    elif rest.startswith("."):
        classifier, dot, extension = "", ".", rest[1:]
    else:
        return None
    if not dot or not extension:
        return None
    return MavenPath(
        "artifact",
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        classifier=classifier,
        extension=extension,
        build=build,
    )


def classify(path: str) -> MavenPath:
    """What a path is. For a checksum path, classify the path it belongs to."""
    if path == CATALOG:
        return MavenPath("catalog")
    segments = path.split("/")
    if segments[-1] == METADATA_FILE:
        return _metadata(segments[:-1]) or _OTHER
    return _artifact(segments) or _OTHER


def allowed_by(version_policy: str, parsed: MavenPath) -> bool:
    """Whether a repository with this version policy holds such a path."""
    if parsed.kind not in ("artifact", "snapshot_metadata") or version_policy == "mixed":
        return True
    return (version_policy == "snapshot") == parsed.is_snapshot


def content_type(path: str) -> str | None:
    """The content type for a file Maven uses, by its last extension."""
    return _CONTENT_TYPES.get(path.rpartition(".")[2])
