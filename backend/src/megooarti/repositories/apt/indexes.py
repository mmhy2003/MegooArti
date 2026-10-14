"""The index files of a hosted APT repository, written from what its packages said.

`Packages` lists each package as dpkg-scanpackages does: its control fields, with
`Filename`, `Size` and the checksums before `Section`. `Release` names every
`Packages` file with its size and checksums. Both are written the same way for the
same packages, byte for byte, so a client that has them already is told so.
"""

import gzip
import hashlib
import lzma
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from megooarti.repositories.apt import control, versions
from megooarti.repositories.apt.paths import COMPONENT

# Where a package's file and checksums go: before the first of these, as dpkg puts them.
_AFTER_FILE = frozenset({"section", "priority", "multi-arch", "homepage", "description", "tag"})
# Listed when a repository has no package of any one architecture, so that a client
# of either of the two most common ones finds the packages for all of them.
DEFAULT_ARCHITECTURES = ("amd64", "arm64")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Listed:
    """A package as an index lists it: what it said of itself, and where its file is."""

    path: str
    size: int
    md5: str
    sha1: str
    sha256: str
    control: control.Paragraph
    package: str
    version: str
    architecture: str


def entry(listed: Listed) -> str:
    """A package's paragraph in `Packages`."""
    file = [
        ("Filename", listed.path),
        ("Size", str(listed.size)),
        ("MD5sum", listed.md5),
        ("SHA1", listed.sha1),
        ("SHA256", listed.sha256),
    ]
    fields = list(listed.control)
    at = next((i for i, (name, _) in enumerate(fields) if name.lower() in _AFTER_FILE), len(fields))
    return control.format_paragraph(fields[:at] + file + fields[at:])


def _order(listed: Listed) -> tuple:
    return (listed.package, versions.version_key(listed.version), listed.architecture)


def packages(listed: Iterable[Listed]) -> bytes:
    """A `Packages` file: the paragraphs, in order of name, version and architecture.

    Each ends with a blank line, the last one too, as dpkg-scanpackages writes them.
    """
    return "".join(entry(one) + "\n" for one in sorted(listed, key=_order)).encode()


def architectures(listed: Iterable[Listed]) -> list[str]:
    """The architectures a repository lists: those of its packages but `all`."""
    found = sorted({one.architecture for one in listed} - {"all"})
    return found or list(DEFAULT_ARCHITECTURES)


def packages_files(listed: Sequence[Listed]) -> dict[str, bytes]:
    """Every `Packages` file of the component, by its path under the suite.

    A package for all architectures is listed under each of them.
    """
    files = {}
    for architecture in architectures(listed):
        mine = [one for one in listed if one.architecture in (architecture, "all")]
        text = packages(mine)
        directory = f"{COMPONENT}/binary-{architecture}"
        files[f"{directory}/Packages"] = text
        files[f"{directory}/Packages.gz"] = gzip.compress(text, compresslevel=9, mtime=0)
        files[f"{directory}/Packages.xz"] = lzma.compress(text)
    return files


def date(moment: datetime) -> str:
    """A moment as `Release` writes it, whatever the locale."""
    utc = moment.astimezone(UTC)
    day, month = _DAYS[utc.weekday()], _MONTHS[utc.month - 1]
    return f"{day}, {utc.day:02d} {month} {utc.year} {utc:%H:%M:%S} UTC"


def release(
    *,
    label: str,
    suite: str,
    moment: datetime,
    architectures: Sequence[str],
    files: dict[str, bytes],
) -> bytes:
    """The `Release` file of a suite whose index files are `files`."""
    lines = [
        "Origin: MegooArti",
        f"Label: {label}",
        f"Suite: {suite}",
        f"Codename: {suite}",
        f"Date: {date(moment)}",
        f"Architectures: {' '.join(architectures)}",
        f"Components: {COMPONENT}",
        "Acquire-By-Hash: no",
    ]
    for heading, algorithm in (("MD5Sum", "md5"), ("SHA256", "sha256")):
        lines.append(f"{heading}:")
        for path, data in sorted(files.items()):
            lines.append(f" {hashlib.new(algorithm, data).hexdigest()} {len(data):>16} {path}")
    return ("\n".join(lines) + "\n").encode()
