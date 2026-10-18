"""Versions in order: the order of a format that has none of its own, and the help a
format with one needs."""

import re
from collections.abc import Callable, Iterable
from functools import cmp_to_key

_DIGITS = re.compile(r"(\d+)")


def natural_key(version: str) -> tuple:
    """Numbers as numbers and the rest as text, as people read versions: 1.10 after 1.9.

    Versions that read alike are ordered by their text, so the order is always the same.
    """
    chunks = tuple(
        (0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk.lower())
        for chunk in _DIGITS.split(version)
        if chunk
    )
    return chunks, version


def ordered_by(compare: Callable[[str, str], int], texts: Iterable[str]) -> list[str]:
    """Distinct versions, the oldest first, as `compare` orders them. Two it cannot
    compare (it raises `ValueError`) are ordered as people read them."""

    def safely(one: str, other: str) -> int:
        try:
            return compare(one, other)
        except ValueError:
            ours, theirs = natural_key(one), natural_key(other)
            return (ours > theirs) - (ours < theirs)

    return sorted(sorted(set(texts)), key=cmp_to_key(safely))
