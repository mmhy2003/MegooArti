"""PyPI project names, request paths and file names.

Pure functions. A project has many spellings and one normal form (PEP 503); everything
stored is keyed by the normal form.
"""

import re
from dataclasses import dataclass

MAX_NAME_LENGTH = 128
_MAX_SEGMENT_LENGTH = 255
_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_RUN = re.compile(r"[-_.]+")
# A version or a file name, as one segment of a path.
_SEGMENT = re.compile(r"[A-Za-z0-9._+!-]+")

# What a hosted repository takes: wheels and source distributions.
UPLOADABLE = (".whl", ".tar.gz", ".zip")
_SOURCE = (".tar.gz", ".zip", ".tar.bz2", ".tar.xz", ".tgz")
# Old binary kinds a proxy still meets. Their names carry more than a version.
_LEGACY = (".egg", ".exe", ".msi")
_METADATA = ".metadata"


@dataclass(frozen=True)
class PypiPath:
    """A path, classified. Fields that do not apply to its kind are left empty."""

    kind: str  # repository, index, page, file, metadata or other
    project: str = ""  # page: as it was written; file and metadata: the normal form
    version: str = ""
    filename: str = ""  # metadata: the name of the file it describes
    slash: bool = False  # whether the path ended in a slash


_OTHER = PypiPath("other")


def normalise(name: str) -> str:
    """A project name in its normal form: lower case, runs of `-_.` as one hyphen."""
    return _RUN.sub("-", name).lower()


def is_valid_name(name: str) -> bool:
    return len(name) <= MAX_NAME_LENGTH and _NAME.fullmatch(name) is not None


def is_valid_segment(text: str) -> bool:
    """Whether this can be a version or a file name in a path."""
    if text in (".", "..") or len(text) > _MAX_SEGMENT_LENGTH:
        return False
    return _SEGMENT.fullmatch(text) is not None


def file_path(project: str, version: str, filename: str) -> str:
    """Where a file is stored, and requested. `project` is in its normal form."""
    return f"packages/{project}/{version}/{filename}"


def version_of(project: str, filename: str) -> str | None:
    """The version a file belongs to, read from its name.

    `project` is in its normal form. None if the name is not that of a file of the
    project: installers ignore such files too.
    """
    if filename.endswith(".whl"):
        parts = filename[: -len(".whl")].split("-")
        if len(parts) not in (5, 6) or normalise(parts[0]) != project:
            return None
        return parts[1] or None
    extension = next((known for known in _SOURCE + _LEGACY if filename.endswith(known)), None)
    if extension is None:
        return None
    stem = filename[: -len(extension)]
    # The longest prefix that is the project's name: names may contain hyphens.
    for position in range(len(stem) - 1, 0, -1):
        if stem[position] == "-" and normalise(stem[:position]) == project:
            rest = stem[position + 1 :]
            return (rest.partition("-")[0] if extension in _LEGACY else rest) or None
    return None


def classify(path: str) -> PypiPath:
    """What a request path is. One trailing slash is ignored, and remembered."""
    if path == "":
        return PypiPath("repository")
    slash = path.endswith("/")
    segments = (path[:-1] if slash else path).split("/")
    if segments == ["simple"]:
        return PypiPath("index", slash=slash)
    if len(segments) == 2 and segments[0] == "simple" and is_valid_name(segments[1]):
        return PypiPath("page", project=segments[1], slash=slash)
    if len(segments) == 4 and segments[0] == "packages" and not slash:
        _, project, version, filename = segments
        kind = "file"
        if filename.endswith(_METADATA):
            kind, filename = "metadata", filename[: -len(_METADATA)]
        valid = (
            is_valid_name(project)
            and project == normalise(project)
            and is_valid_segment(version)
            and is_valid_segment(filename)
        )
        if valid:
            return PypiPath(kind, project=project, version=version, filename=filename)
    return _OTHER
