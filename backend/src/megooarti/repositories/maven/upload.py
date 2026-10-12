"""An upload form for a Maven repository, turned into the files it asks to be stored.

Pure functions: no database, no files. The form gives the coordinates once; each file
says what it is by the name of its part and the end of its own name:

    file               the artifact itself            app-1.0.jar
    file.<classifier>  a file beside it               app-1.0-sources.jar
    pom                the POM, whatever it is named  app-1.0.pom
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

from megooarti.repositories.maven import paths

FIELDS = ("group", "artifact", "version", "packaging", "generate_pom")
_ID = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
_VERSION = re.compile(r"[A-Za-z0-9_.+-]+")
_CLASSIFIER = re.compile(r"[A-Za-z0-9_-]+")
_EXTENSION = re.compile(r"[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*")
# Ends of a name that are one extension though they have a dot in them.
_COMPOUND = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst")
_SIGNATURE = ".asc"
_BOOLEANS = {"true": True, "false": False}


class InvalidUpload(Exception):
    """The form does not say what to store. `field` is where, and the message says why."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Plan:
    paths: tuple[str, ...]  # where each file of the form goes, in the form's order
    pom_path: str  # where this version's POM is
    pom: bytes | None  # a POM to store there if the repository has none: None if one was sent


def extension_of(filename: str) -> str | None:
    """What a file is, by the end of its name: `jar`, `tar.gz`, `jar.asc`. None if nothing."""
    if filename.lower().endswith(_SIGNATURE):
        signed = extension_of(filename[: -len(_SIGNATURE)])
        return None if signed is None else f"{signed}{filename[-len(_SIGNATURE) :]}"
    for compound in _COMPOUND:
        if filename.lower().endswith(f".{compound}") and len(filename) > len(compound) + 1:
            return filename[-len(compound) :]
    stem, dot, extension = filename.rpartition(".")
    return extension if dot and stem and extension else None


def generated_pom(group: str, artifact: str, version: str, packaging: str) -> bytes:
    """The least a POM can say: what this is. Enough for a build that depends on it."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:schemaLocation="http://maven.apache.org/POM/4.0.0'
        ' https://maven.apache.org/xsd/maven-4.0.0.xsd">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        f"  <groupId>{escape(group)}</groupId>\n"
        f"  <artifactId>{escape(artifact)}</artifactId>\n"
        f"  <version>{escape(version)}</version>\n"
        f"  <packaging>{escape(packaging)}</packaging>\n"
        "</project>\n"
    ).encode()


def _coordinate(fields: Mapping[str, str], name: str, pattern: re.Pattern[str]) -> str:
    value = fields.get(name, "").strip()
    if not value:
        raise InvalidUpload(name, "This is needed.")
    if not pattern.fullmatch(value) or value in (".", ".."):
        raise InvalidUpload(name, "This has a character, or a form, that Maven does not take.")
    return value


def _target(part: str, filename: str) -> tuple[str, str]:
    """The classifier and the extension a part of the form asks for."""
    if part == "pom":
        return "", "pom"
    name, dot, classifier = part.partition(".")
    if name != "file" or (dot and not _CLASSIFIER.fullmatch(classifier)):
        raise InvalidUpload(part, "A file is sent as `file`, `file.<classifier>` or `pom`.")
    extension = extension_of(filename)
    if extension is None or not _EXTENSION.fullmatch(extension):
        raise InvalidUpload(part, f"The name {filename} does not end in what the file is.")
    return classifier, extension


def plan(fields: Mapping[str, str], files: Sequence[tuple[str, str]]) -> Plan:
    """Where the files of a form go. `files` are (part name, file name). Raises InvalidUpload."""
    for name in fields:
        if name not in FIELDS:
            raise InvalidUpload(name, "This is not a field of an upload to a Maven repository.")
    group = _coordinate(fields, "group", _ID)
    artifact = _coordinate(fields, "artifact", _ID)
    version = _coordinate(fields, "version", _VERSION)
    packaging = fields.get("packaging", "").strip() or "jar"
    if not _ID.fullmatch(packaging):
        raise InvalidUpload("packaging", "This is not a packaging.")
    generate = _BOOLEANS.get(fields.get("generate_pom", "true").strip().lower())
    if generate is None:
        raise InvalidUpload("generate_pom", "Must be true or false.")
    if not files:
        raise InvalidUpload("file", "At least one file is needed.")

    directory = f"{group.replace('.', '/')}/{artifact}/{version}"
    targets: list[str] = []
    for part, filename in files:
        classifier, extension = _target(part, filename)
        suffix = f"-{classifier}" if classifier else ""
        path = f"{directory}/{artifact}-{version}{suffix}.{extension}"
        parsed = paths.classify(path)
        read = (parsed.group_id, parsed.artifact_id, parsed.version, parsed.classifier)
        if parsed.kind != "artifact" or read != (group, artifact, version, classifier):
            # Everything else reads a path to know what a file is, so the path must
            # read back as what was given: a version of `-SNAPSHOT` alone does not.
            raise InvalidUpload(part, "The group, artifact and version do not make a Maven path.")
        if path in targets:
            raise InvalidUpload(part, f"Two files of the form would be {path.rpartition('/')[2]}.")
        targets.append(path)
    pom_path = f"{directory}/{artifact}-{version}.pom"
    wanted = generate and pom_path not in targets
    pom = generated_pom(group, artifact, version, packaging) if wanted else None
    return Plan(paths=tuple(targets), pom_path=pom_path, pom=pom)
