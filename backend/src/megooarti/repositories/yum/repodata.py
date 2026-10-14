"""A directory's `repodata/`: what dnf reads to know the packages under it.

`primary.xml` lists each package, its dependencies and its files that dnf most often
looks for; `filelists.xml` every file; `other.xml` the changelogs. Each is written as
`createrepo_c` writes it, packed with gzip, and named by its hash; `repomd.xml` names
the three, and is what a repository signs.

They are written from what was read of each package at upload, and from nothing
else: the same packages make the same bytes, in any process.
"""

import gzip
import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from megooarti.repositories.yum.rpms import DEPENDENCIES, Entry, Rpm, is_primary

_COMMON = "http://linux.duke.edu/metadata/common"
_RPM = "http://linux.duke.edu/metadata/rpm"
_START = '<?xml version="1.0" encoding="UTF-8"?>\n'
# Characters XML 1.0 cannot hold: they are left out.
_UNWRITABLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_IN_TEXT = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\r": "&#13;"}
_IN_ATTRIBUTE = {**_IN_TEXT, '"': "&quot;", "\n": "&#10;", "\t": "&#9;"}
_TEXT_ESCAPED = re.compile("[&<>\r]")
_ATTRIBUTE_ESCAPED = re.compile('[&<>"\n\r\t]|[^\x00-\x7f]')


@dataclass(frozen=True)
class Listed:
    """A package that a `repodata/` lists, and its file."""

    location: str  # its path under the directory `repodata/` is in
    size: int
    sha256: str
    time: int  # when its file was stored, in seconds since 1970
    rpm: Rpm


def text(value: str) -> str:
    """Text as libxml2 writes it between tags."""
    return _TEXT_ESCAPED.sub(lambda m: _IN_TEXT[m[0]], _UNWRITABLE.sub("", value))


def attribute(value: str) -> str:
    """Text as libxml2 writes it in an attribute: beyond ASCII as character references."""

    def escaped(found: re.Match[str]) -> str:
        character = found[0]
        return _IN_ATTRIBUTE.get(character) or f"&#x{ord(character):X};"

    return _ATTRIBUTE_ESCAPED.sub(escaped, _UNWRITABLE.sub("", value))


def _version(rpm: Rpm) -> str:
    return (
        f'<version epoch="{attribute(rpm.epoch)}" ver="{attribute(rpm.version)}" '
        f'rel="{attribute(rpm.release)}"/>'
    )


def _entry(entry: Entry, requires: bool) -> str:
    said = [f'name="{attribute(entry.name)}"']
    if entry.flags:
        said.append(f'flags="{entry.flags}"')
        for name, value in (("epoch", entry.epoch), ("ver", entry.version), ("rel", entry.release)):
            if value:
                said.append(f'{name}="{attribute(value)}"')
    if requires and entry.pre:
        said.append('pre="1"')
    return f"      <rpm:entry {' '.join(said)}/>\n"


def _files(files: Iterable[tuple[str, str]], indent: str) -> str:
    written = []
    for path, kind in files:
        typed = f' type="{kind}"' if kind else ""
        written.append(f"{indent}<file{typed}>{text(path)}</file>\n")
    return "".join(written)


def _primary_package(listed: Listed) -> str:
    rpm = listed.rpm
    parts = [
        '<package type="rpm">\n',
        f"  <name>{text(rpm.name)}</name>\n",
        f"  <arch>{text(rpm.arch)}</arch>\n",
        f"  {_version(rpm)}\n",
        f'  <checksum type="sha256" pkgid="YES">{listed.sha256}</checksum>\n',
        f"  <summary>{text(rpm.summary)}</summary>\n",
        f"  <description>{text(rpm.description)}</description>\n",
        f"  <packager>{text(rpm.packager)}</packager>\n",
        f"  <url>{text(rpm.url)}</url>\n",
        f'  <time file="{listed.time}" build="{rpm.build_time}"/>\n',
        f'  <size package="{listed.size}" installed="{rpm.installed_size}" '
        f'archive="{rpm.archive_size}"/>\n',
        f'  <location href="{attribute(listed.location)}"/>\n',
        "  <format>\n",
        f"    <rpm:license>{text(rpm.license)}</rpm:license>\n",
        f"    <rpm:vendor>{text(rpm.vendor)}</rpm:vendor>\n",
        f"    <rpm:group>{text(rpm.group)}</rpm:group>\n",
        f"    <rpm:buildhost>{text(rpm.buildhost)}</rpm:buildhost>\n",
        f"    <rpm:sourcerpm>{text(rpm.sourcerpm)}</rpm:sourcerpm>\n",
        f'    <rpm:header-range start="{rpm.header_start}" end="{rpm.header_end}"/>\n',
    ]
    for kind in DEPENDENCIES:
        entries = rpm.dependencies.get(kind)
        if entries:
            parts.append(f"    <rpm:{kind}>\n")
            parts.extend(_entry(entry, kind == "requires") for entry in entries)
            parts.append(f"    </rpm:{kind}>\n")
    parts.append(_files(((p, k) for p, k in rpm.files if is_primary(p)), "    "))
    parts.append("  </format>\n</package>\n")
    return "".join(parts)


def primary(listed: Sequence[Listed]) -> bytes:
    """`primary.xml`: every package, as createrepo_c writes it."""
    head = f'<metadata xmlns="{_COMMON}" xmlns:rpm="{_RPM}" packages="{len(listed)}">\n'
    body = "".join(_primary_package(each) for each in listed)
    return (_START + head + body + "</metadata>").encode()


def _owned(listed: Listed) -> str:
    rpm = listed.rpm
    return (
        f'<package pkgid="{listed.sha256}" name="{attribute(rpm.name)}" '
        f'arch="{attribute(rpm.arch)}">\n  {_version(rpm)}\n'
    )


def filelists(listed: Sequence[Listed]) -> bytes:
    """`filelists.xml`: every file of every package."""
    head = (
        f'<filelists xmlns="http://linux.duke.edu/metadata/filelists" packages="{len(listed)}">\n'
    )
    body = "".join(_owned(each) + _files(each.rpm.files, "  ") + "</package>\n" for each in listed)
    return (_START + head + body + "</filelists>").encode()


def other(listed: Sequence[Listed]) -> bytes:
    """`other.xml`: the changelogs that were kept of every package."""
    head = f'<otherdata xmlns="http://linux.duke.edu/metadata/other" packages="{len(listed)}">\n'
    parts = [_START, head]
    for each in listed:
        parts.append(_owned(each))
        for entry in each.rpm.changelogs:
            parts.append(
                f'  <changelog author="{attribute(entry.author)}" date="{entry.date}">'
                f"{text(entry.text)}</changelog>\n"
            )
        parts.append("</package>\n")
    parts.append("</otherdata>")
    return "".join(parts).encode()


def pack(data: bytes) -> bytes:
    """Packed with gzip, with no date or name in it: the same bytes every time."""
    return gzip.compress(data, compresslevel=6, mtime=0)


def repodata(listed: Sequence[Listed], moment: int) -> dict[str, bytes]:
    """Every file of a `repodata/`, by its name in it. `moment` is the revision's time."""
    files: dict[str, bytes] = {}
    data = []
    for kind, write in (("primary", primary), ("filelists", filelists), ("other", other)):
        opened = write(listed)
        packed = pack(opened)
        digest = hashlib.sha256(packed).hexdigest()
        name = f"{digest}-{kind}.xml.gz"
        files[name] = packed
        data.append(
            f'  <data type="{kind}">\n'
            f'    <checksum type="sha256">{digest}</checksum>\n'
            f'    <open-checksum type="sha256">{hashlib.sha256(opened).hexdigest()}'
            "</open-checksum>\n"
            f'    <location href="repodata/{name}"/>\n'
            f"    <timestamp>{moment}</timestamp>\n"
            f"    <size>{len(packed)}</size>\n"
            f"    <open-size>{len(opened)}</open-size>\n"
            "  </data>\n"
        )
    files["repomd.xml"] = (
        f'{_START}<repomd xmlns="http://linux.duke.edu/metadata/repo" xmlns:rpm="{_RPM}">\n'
        f"  <revision>{moment}</revision>\n" + "".join(data) + "</repomd>\n"
    ).encode()
    return files
