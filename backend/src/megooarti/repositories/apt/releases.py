"""A suite's `Release`: what it says of itself, and of each file it names.

A group reads its members' `Release` files to know what each offers, and writes one of
its own for a suite that several members offer. Only the `SHA256` list is read and
written: it is what apt checks every file against.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from megooarti.repositories.apt import control
from megooarti.repositories.apt.indexes import date

# A line of a checksum list: the checksum, the size and the path under the suite.
_ENTRY = re.compile(r"([0-9a-f]{64})\s+([0-9]{1,18})\s+(\S+)")


class InvalidRelease(ValueError):
    """Text that is not a `Release` file a group can read."""


@dataclass(frozen=True)
class Entry:
    """A file a `Release` names: how large it is, and its SHA-256."""

    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    text: bytes  # as signed, with its last line ending
    components: list[str]
    architectures: list[str]
    entries: dict[str, Entry]  # by path under the suite
    moment: datetime | None  # its `Date`, if it says one


def parse(text: bytes) -> Release:
    """What a `Release` says. Raises InvalidRelease."""
    try:
        paragraph = control.parse(text.decode("utf-8"))
    except (UnicodeDecodeError, control.InvalidControl) as error:
        raise InvalidRelease(f"it is not a Release file: {error}") from None
    listed = control.get(paragraph, "SHA256")
    if listed is None:
        raise InvalidRelease("it has no SHA256 list")
    entries = {}
    for line in listed.strip().splitlines():
        found = _ENTRY.fullmatch(line.strip())
        if found is None:
            raise InvalidRelease(f"a line of its SHA256 list cannot be read: {line[:80]!r}")
        entries[found[3]] = Entry(int(found[2]), found[1])
    said = control.get(paragraph, "Date")
    try:
        moment = parsedate_to_datetime(said) if said else None
    except (TypeError, ValueError):
        moment = None
    return Release(
        text=text if text.endswith(b"\n") else text + b"\n",
        components=(control.get(paragraph, "Components") or "").split(),
        architectures=(control.get(paragraph, "Architectures") or "").split(),
        entries=entries,
        moment=moment,
    )


def compose(
    *,
    label: str,
    suite: str,
    moment: datetime,
    components: Sequence[str],
    architectures: Sequence[str],
    entries: Iterable[tuple[str, Entry]],
) -> bytes:
    """A group's `Release` of a suite several members offer."""
    lines = [
        "Origin: MegooArti",
        f"Label: {label}",
        f"Suite: {suite}",
        f"Codename: {suite}",
        f"Date: {date(moment)}",
        f"Architectures: {' '.join(architectures)}",
        f"Components: {' '.join(components)}",
        "Acquire-By-Hash: no",
        "SHA256:",
    ]
    for path, entry in sorted(entries):
        lines.append(f" {entry.sha256} {entry.size:>16} {path}")
    return ("\n".join(lines) + "\n").encode()
