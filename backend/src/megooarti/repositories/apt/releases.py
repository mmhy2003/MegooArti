"""A suite's `Release`: what it says of itself, and of each file it names.

A group reads its members' `Release` files to know what each offers, and writes one of
its own for every suite it serves. Only the `SHA256` list is read and written: it is
what apt checks every file against.
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
# What a `Release` says of whose suite it is, which a group's says as its member's does:
# apt refuses a suite whose Origin, Label or Codename changes, and pins by them.
HEADER = ("Origin", "Label", "Suite", "Version", "Codename", "Changelogs", "Description")


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
    header: control.Paragraph  # the fields of HEADER it has, in its order
    components: list[str]
    architectures: list[str]
    entries: dict[str, Entry]  # by path under the suite
    moment: datetime | None  # its `Date`, if it says one
    valid_until: datetime | None  # its `Valid-Until`, if it says one
    by_hash: bool  # whether its files are also found by their hash (`Acquire-By-Hash`)


def _moment(said: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(said) if said else None
    except (TypeError, ValueError):
        return None


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
    wanted = {name.lower() for name in HEADER}
    return Release(
        text=text if text.endswith(b"\n") else text + b"\n",
        header=[(name, value) for name, value in paragraph if name.lower() in wanted],
        components=(control.get(paragraph, "Components") or "").split(),
        architectures=(control.get(paragraph, "Architectures") or "").split(),
        entries=entries,
        moment=_moment(control.get(paragraph, "Date")),
        valid_until=_moment(control.get(paragraph, "Valid-Until")),
        by_hash=(control.get(paragraph, "Acquire-By-Hash") or "").lower() == "yes",
    )


def compose(
    *,
    header: control.Paragraph,
    moment: datetime,
    valid_until: datetime | None = None,
    components: Sequence[str],
    architectures: Sequence[str],
    entries: Iterable[tuple[str, Entry]],
    by_hash: bool = False,
) -> bytes:
    """A group's `Release` of a suite: whose it is (`header`), and the files it names."""
    lines = [control.format_paragraph(header).rstrip("\n")] if header else []
    lines.append(f"Date: {date(moment)}")
    if valid_until is not None:
        lines.append(f"Valid-Until: {date(valid_until)}")
    lines += [
        f"Architectures: {' '.join(architectures)}",
        f"Components: {' '.join(components)}",
        f"Acquire-By-Hash: {'yes' if by_hash else 'no'}",
        "SHA256:",
    ]
    for path, entry in sorted(entries):
        lines.append(f" {entry.sha256} {entry.size:>16} {path}")
    return ("\n".join(lines) + "\n").encode()
