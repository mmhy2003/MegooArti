"""Maven's version order.

Written from the Version Order Specification in the Maven POM reference
(https://maven.apache.org/pom.html#version-order-specification).

A version is parsed into a list of numbers and qualifiers. A hyphen and a change
between digits and letters each open a nested list, and so does a qualifier that ends
the version or has a digit directly after it. So "1.0-rc1", "1.0.rc1" and "1.0-rc-1"
all become [1, ["rc", [1]]] once trailing zeros are trimmed, while the "build" of
"2.0.0.build-snapshot" stays beside the numbers before it. Nesting is what makes "1-1"
(a list after the 1) older than "1.1" (a number after it).

The specification leaves some of this open. Where it does, this follows what Maven 3.9
does, and tests/test_maven_client.py compares the two on a list of versions.
"""

import re
from collections.abc import Iterable
from functools import cmp_to_key

# Oldest first. The empty qualifier is a plain release.
_QUALIFIERS = ("alpha", "beta", "milestone", "rc", "snapshot", "", "sp")
_ALIASES = {"ga": "", "final": "", "release": "", "cr": "rc"}
# Only when a digit follows directly: 1.0-a1 is 1.0-alpha-1.
_SHORT = {"a": "alpha", "b": "beta", "m": "milestone"}

Item = int | str | list


def _qualifier(text: str, followed_by_digit: bool) -> str:
    if followed_by_digit:
        text = _SHORT.get(text, text)
    return _ALIASES.get(text, text)


def _rank(qualifier: str) -> tuple[int, str]:
    """Known qualifiers in their order, then every other one alphabetically."""
    if qualifier in _QUALIFIERS:
        return _QUALIFIERS.index(qualifier), ""
    return len(_QUALIFIERS), qualifier


def _is_null(item: Item) -> bool:
    return item in (0, "", [])


def _trim(items: list) -> None:
    """Drop trailing parts that mean nothing: "1.0.0" is "1"."""
    for index in range(len(items) - 1, -1, -1):
        if _is_null(items[index]):
            del items[index]
        elif not isinstance(items[index], list):
            break


def _parse(version: str) -> list:
    text = version.lower()
    items: list = []
    opened = [items]

    def descend() -> None:
        if opened[-1]:  # an empty list is still waiting for its first part
            nested: list = []
            opened[-1].append(nested)
            opened.append(nested)

    def add(piece: str, digits: bool, *, ends_part: bool = False, digit_next: bool = False) -> None:
        if digits:
            opened[-1].append(int(piece))
            return
        if ends_part or digit_next:
            descend()  # "1.rc1" is "1-rc1", and "1.final" is "1-final"
        opened[-1].append(_qualifier(piece, digit_next))

    digits = False
    start = 0
    for index, character in enumerate(text):
        if character in ".-":
            if index == start:
                opened[-1].append(0)
            else:
                add(text[start:index], digits)
            start = index + 1
            if character == "-":
                descend()
        elif character in "0123456789":
            if not digits and index > start:
                add(text[start:index], False, digit_next=True)
                start = index
                descend()
            digits = True
        else:
            if digits and index > start:
                add(text[start:index], True)
                start = index
                descend()
            digits = False
    if len(text) > start:
        add(text[start:], digits, ends_part=True)

    for nested in reversed(opened):
        _trim(nested)
    return items


def _sign(left, right) -> int:
    return (left > right) - (left < right)


def _compare(left: Item, right: Item | None) -> int:
    """Compare two parts. `right` is None where the other version has run out."""
    if isinstance(left, int):
        if right is None:
            return _sign(left, 0)
        if isinstance(right, int):
            return _sign(left, right)
        return 1  # a number after a dot is newer than a qualifier or a nested list
    if isinstance(left, str):
        if right is None:
            return _sign(_rank(left), _rank(""))
        if isinstance(right, str):
            return _sign(_rank(left), _rank(right))
        return -1  # a qualifier is older than a number or a nested list
    if right is None:
        # Against nothing, the first part that is not itself nothing decides.
        return next((result for item in left if (result := _compare(item, None))), 0)
    if isinstance(right, int):
        return -1
    if isinstance(right, str):
        return 1
    for index in range(max(len(left), len(right))):
        ours = left[index] if index < len(left) else None
        theirs = right[index] if index < len(right) else None
        result = -_compare(theirs, None) if ours is None else _compare(ours, theirs)
        if result:
            return result
    return 0


# Qualifiers Maven orders below a release: alpha, beta, milestone, release candidate,
# and their one-letter forms when a number follows (`1.0-a1`, `1.0-M2`).
_BEFORE_RELEASE = re.compile(r"(?i)[.-](?:alpha|beta|milestone|rc|cr|[abm](?=\d))")


def is_prerelease(version: str) -> bool:
    """A snapshot, or a version that Maven orders below its release (`1.0-beta-2`)."""
    return version.endswith("-SNAPSHOT") or _BEFORE_RELEASE.search(version) is not None


def compare(left: str, right: str) -> int:
    """-1 if `left` is the older version, 1 if it is the newer, 0 if they are the same."""
    return _compare(_parse(left), _parse(right))


def sorted_versions(versions: Iterable[str]) -> list[str]:
    """Distinct versions, oldest first. Versions that are equal stay in text order."""
    parsed = {version: _parse(version) for version in versions}
    return sorted(
        sorted(parsed), key=cmp_to_key(lambda one, other: _compare(parsed[one], parsed[other]))
    )
