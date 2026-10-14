"""Debian package names, versions and architectures, and the order dpkg puts versions in.

A version is `[epoch:]upstream[-revision]`. Two versions are compared as dpkg compares
them: the epoch as a number, then the upstream part and the revision piece by piece,
with `~` before everything, even the end.
"""

import re
from functools import cmp_to_key

NAME = re.compile(r"[a-z0-9][a-z0-9+.-]+")
ARCHITECTURE = re.compile(r"[a-z0-9][a-z0-9-]*")
_UPSTREAM = re.compile(r"[0-9][A-Za-z0-9.+~-]*")
_REVISION = re.compile(r"[A-Za-z0-9.+~]+")
_EPOCH = re.compile(r"[0-9]{1,9}")
_LONGEST = 255


def split(version: str) -> tuple[int, str, str] | None:
    """Epoch, upstream part and revision, or None for a version dpkg would refuse.

    A colon in the upstream part is refused as well: the part is in the file's name.
    """
    if not version or len(version) > _LONGEST:
        return None
    epoch, colon, rest = version.partition(":")
    if not colon:
        epoch, rest = "0", version
    elif _EPOCH.fullmatch(epoch) is None:
        return None
    upstream, hyphen, revision = rest.rpartition("-")
    if not hyphen:
        upstream, revision = rest, ""
    elif _REVISION.fullmatch(revision) is None:
        return None
    if _UPSTREAM.fullmatch(upstream) is None:
        return None
    return int(epoch), upstream, revision


def without_epoch(version: str) -> str:
    """The version as a file's name has it."""
    return version.partition(":")[2] if ":" in version else version


def _order(character: str) -> int:
    if character == "~":
        return -1
    if character.isalpha():
        return ord(character)
    return ord(character) + 256


def _compare_part(left: str, right: str) -> int:
    """dpkg's `verrevcmp`: letters before non-letters, `~` before all, digits as numbers."""
    i = j = 0
    while i < len(left) or j < len(right):
        difference = 0
        while (i < len(left) and not left[i].isdigit()) or (
            j < len(right) and not right[j].isdigit()
        ):
            ours = _order(left[i]) if i < len(left) and not left[i].isdigit() else 0
            theirs = _order(right[j]) if j < len(right) and not right[j].isdigit() else 0
            if ours != theirs:
                return -1 if ours < theirs else 1
            i += 1
            j += 1
        while i < len(left) and left[i] == "0":
            i += 1
        while j < len(right) and right[j] == "0":
            j += 1
        while i < len(left) and left[i].isdigit() and j < len(right) and right[j].isdigit():
            if not difference:
                difference = ord(left[i]) - ord(right[j])
            i += 1
            j += 1
        if i < len(left) and left[i].isdigit():
            return 1
        if j < len(right) and right[j].isdigit():
            return -1
        if difference:
            return -1 if difference < 0 else 1
    return 0


def compare(left: str, right: str) -> int:
    """-1, 0 or 1, as dpkg orders two valid versions."""
    ours, theirs = split(left), split(right)
    if ours is None or theirs is None:
        raise ValueError("only valid versions are compared")
    if ours[0] != theirs[0]:
        return -1 if ours[0] < theirs[0] else 1
    return _compare_part(ours[1], theirs[1]) or _compare_part(ours[2], theirs[2])


version_key = cmp_to_key(compare)
