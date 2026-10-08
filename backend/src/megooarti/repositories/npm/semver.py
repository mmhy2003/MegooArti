"""Semantic Versioning 2.0.0: which versions are valid, and their order.

Pure functions, written from https://semver.org/spec/v2.0.0.html.
"""

import re
from collections.abc import Iterable

_NUMBER = r"(?:0|[1-9][0-9]*)"
_IDENTIFIER = rf"(?:{_NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = re.compile(
    rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})"
    rf"(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
# No real version is longer, and a bound keeps the numbers small enough to compare.
_MAX_LENGTH = 256

Key = tuple


def is_valid(version: str) -> bool:
    return len(version) <= _MAX_LENGTH and _SEMVER.fullmatch(version) is not None


def sort_key(version: str) -> Key:
    """A key that orders versions by precedence. Invalid versions come before valid ones.

    Build metadata does not count. Versions equal in precedence are ordered by their
    text, so the order is always the same.
    """
    match = _SEMVER.fullmatch(version) if len(version) <= _MAX_LENGTH else None
    if match is None:
        return (0, version)
    major, minor, patch, prerelease = match.groups()
    if prerelease is None:
        ranked: tuple = (1,)  # a release comes after every pre-release of it
    else:
        # Numeric identifiers are lower than alphanumeric ones, and compare as numbers.
        ranked = (
            0,
            tuple(
                (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier)
                for identifier in prerelease.split(".")
            ),
        )
    return (1, int(major), int(minor), int(patch), ranked, version)


def sorted_versions(versions: Iterable[str]) -> list[str]:
    """Distinct versions, lowest first."""
    return sorted(set(versions), key=sort_key)


def highest(versions: Iterable[str]) -> str | None:
    """The highest version, or None if there are none."""
    return max(versions, key=sort_key, default=None)
