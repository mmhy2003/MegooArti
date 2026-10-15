"""NuGet's ids and versions: what each may be, how a version is written, and their order.

As NuGet's own client has them: an id is matched without regard to case, and a version
is normalized before it is compared or put into an address (no leading zeros, no
fourth part of 0, no build metadata).
"""

import re
from dataclasses import dataclass

# An id, as NuGet takes one: words joined by dots or hyphens, at most 100 characters.
ID = re.compile(r"[A-Za-z0-9_]+([.-][A-Za-z0-9_]+)*")
ID_MOST = 100
_VERSION = re.compile(
    r"(?P<numbers>[0-9]+(\.[0-9]+){0,3})"
    r"(-(?P<release>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?"
    r"(\+(?P<metadata>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?"
)
# A part of a version is at most this: NuGet keeps each in a 32-bit integer.
_PART_MOST = 2**31 - 1
VERSION_MOST = 64


def is_id(text: str) -> bool:
    return len(text) <= ID_MOST and ID.fullmatch(text) is not None


@dataclass(frozen=True)
class Version:
    """A version as NuGet reads one."""

    numbers: tuple[int, int, int, int]
    release: tuple[str, ...]  # the release labels: none for a stable version
    metadata: str  # build metadata: never part of an address, never compared

    @property
    def normalized(self) -> str:
        """As NuGet writes it: three parts, a fourth only if it is not 0, and the labels."""
        major, minor, patch, revision = self.numbers
        text = f"{major}.{minor}.{patch}" + (f".{revision}" if revision else "")
        return f"{text}-{'.'.join(self.release)}" if self.release else text

    @property
    def is_prerelease(self) -> bool:
        return bool(self.release)

    @property
    def is_semver2(self) -> bool:
        """Whether only a client of SemVer 2.0.0 reads it: labels with dots, or metadata."""
        return len(self.release) > 1 or bool(self.metadata)

    def sort_key(self) -> tuple:
        """Its place among versions: a stable version after its prereleases."""
        labels = tuple(
            (0, int(label), "") if label.isdigit() else (1, 0, label.lower())
            for label in self.release
        )
        return (self.numbers, not self.release, labels)


def parse(text: str) -> Version | None:
    """A version, or None for text that is not one."""
    if len(text) > VERSION_MOST:
        return None
    found = _VERSION.fullmatch(text.strip())
    if found is None:
        return None
    numbers = [int(part) for part in found["numbers"].split(".")]
    if any(number > _PART_MOST for number in numbers):
        return None
    release = tuple(found["release"].split(".")) if found["release"] else ()
    padded = (numbers + [0, 0, 0])[:4]
    return Version((padded[0], padded[1], padded[2], padded[3]), release, found["metadata"] or "")


def normalize(text: str) -> str | None:
    """A version's normalized text, or None for text that is not one."""
    version = parse(text)
    return None if version is None else version.normalized


def ordered(texts: list[str]) -> list[str]:
    """Versions from the oldest to the newest. Text that is not a version is left out."""
    parsed = [(version, text) for text in texts if (version := parse(text)) is not None]
    return [text for _, text in sorted(parsed, key=lambda pair: pair[0].sort_key())]
