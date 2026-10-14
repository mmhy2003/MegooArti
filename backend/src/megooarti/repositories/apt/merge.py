"""Members' `Packages` files made into one, the earlier member's package first.

A `Packages` file of a proxy can be tens of megabytes, so it is not parsed into
fields: each paragraph is kept as the bytes it was, and only the three fields that
say which package it is are looked for in it.
"""

import lzma
import re
import zlib
from collections.abc import Iterable

# The most a member's `Packages` file may be once unpacked (spec, section 9).
UNPACKED_MOST = 1024 * 1024 * 1024
_FIELDS = {
    name: re.compile(rb"^" + name + rb":[ \t]*(\S+)", re.MULTILINE)
    for name in (b"Package", b"Version", b"Architecture")
}


class InvalidIndex(ValueError):
    """A member's index that cannot be unpacked, or is larger than is read."""


def unpacked(name: str, data: bytes, most: int = UNPACKED_MOST) -> bytes:
    """A `Packages` file as text, from the variant `name` says it is."""
    try:
        if name.endswith(".xz"):
            text = lzma.LZMADecompressor().decompress(data, most + 1)
        elif name.endswith(".gz"):
            text = zlib.decompressobj(wbits=47).decompress(data, most + 1)
        else:
            text = data
    except (lzma.LZMAError, zlib.error) as error:
        raise InvalidIndex(f"{name} cannot be unpacked: {error}") from None
    if len(text) > most:
        raise InvalidIndex(f"{name} is larger than this server reads")
    return text


def _paragraphs(text: bytes) -> Iterable[bytes]:
    for paragraph in text.split(b"\n\n"):
        paragraph = paragraph.strip(b"\n")
        if paragraph:
            yield paragraph


def _key(paragraph: bytes) -> tuple[bytes, ...] | None:
    found = [pattern.search(paragraph) for pattern in _FIELDS.values()]
    if any(match is None for match in found):
        return None
    return tuple(match[1] for match in found)


def merged(texts: Iterable[bytes]) -> bytes:
    """One `Packages` file of several, in their order.

    A package (its name, version and architecture) that an earlier one has is left
    out of a later one, and a paragraph that does not say which package it is goes.
    """
    seen: set[tuple[bytes, ...]] = set()
    kept = []
    for text in texts:
        for paragraph in _paragraphs(text):
            key = _key(paragraph)
            if key is None or key in seen:
                continue
            seen.add(key)
            kept.append(paragraph + b"\n\n")
    return b"".join(kept)
