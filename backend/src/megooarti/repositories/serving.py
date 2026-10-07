"""Decide how to answer a request for stored content: headers, conditions, ranges.

Pure functions: nothing here touches the database or the blob store.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import quote

from megooarti.errors import ApiError


@dataclass(frozen=True)
class Servable:
    sha256: str
    md5: str
    sha1: str
    sha512: str
    size: int
    content_type: str
    last_modified: datetime
    filename: str


@dataclass(frozen=True)
class Plan:
    status: int
    headers: dict[str, str]
    byte_range: tuple[int, int] | None  # inclusive offsets; None means send no body


_NUMBER = re.compile(r"[0-9]{1,18}")


class RangeNotSatisfiable(Exception):
    """The requested range lies entirely outside the content."""


def _etag(item: Servable) -> str:
    return f'"{item.sha256}"'


def _disposition(filename: str) -> str:
    # Always a download, never rendered: content shares a site with the admin UI.
    safe = "".join(
        character if character.isascii() and (character.isalnum() or character in "._-") else "_"
        for character in filename
    )
    return f"attachment; filename=\"{safe or '_'}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _base_headers(item: Servable) -> dict[str, str]:
    return {
        "Content-Type": item.content_type,
        "ETag": _etag(item),
        "Last-Modified": format_datetime(item.last_modified.astimezone(UTC), usegmt=True),
        "Accept-Ranges": "bytes",
        "X-Checksum-Md5": item.md5,
        "X-Checksum-Sha1": item.sha1,
        "X-Checksum-Sha256": item.sha256,
        "X-Checksum-Sha512": item.sha512,
        "Content-Disposition": _disposition(item.filename),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }


def _etag_matches(header: str, etag: str) -> bool:
    if header.strip() == "*":
        return True
    return etag in [candidate.strip().removeprefix("W/") for candidate in header.split(",")]


def _not_modified_since(header: str, last_modified: datetime) -> bool:
    try:
        since = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return last_modified.replace(microsecond=0) <= since


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """One `bytes=` range as inclusive offsets, or None for "send everything".

    A header that is malformed, uses another unit, or asks for several ranges is ignored,
    as HTTP allows. Raises RangeNotSatisfiable when the range is outside the content.
    """
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, dash, last = (part.strip() for part in spec.partition("-"))
    # Plain ASCII digits of sane length only: str.isdigit() also accepts characters and
    # lengths that int() rejects.
    if not dash or not (first or last):
        return None
    if not all(part == "" or _NUMBER.fullmatch(part) for part in (first, last)):
        return None
    if first == "":
        length = int(last)
        if length == 0 or size == 0:
            raise RangeNotSatisfiable
        return max(size - length, 0), size - 1
    start = int(first)
    if start >= size:
        raise RangeNotSatisfiable
    end = size - 1 if last == "" else min(int(last), size - 1)
    if end < start:
        return None
    return start, end


def plan(method: str, request_headers: Mapping[str, str], item: Servable) -> Plan:
    headers = _base_headers(item)
    etag = _etag(item)

    if_none_match = request_headers.get("if-none-match")
    if if_none_match is not None:
        if _etag_matches(if_none_match, etag):
            return Plan(304, headers, None)
    else:
        since = request_headers.get("if-modified-since")
        if since and _not_modified_since(since, item.last_modified):
            return Plan(304, headers, None)

    byte_range = None
    range_header = request_headers.get("range")
    if_range = request_headers.get("if-range")
    if method == "GET" and range_header and (if_range is None or if_range.strip() == etag):
        try:
            byte_range = parse_range(range_header, item.size)
        except RangeNotSatisfiable:
            raise ApiError(
                416,
                "range_not_satisfiable",
                "The requested range is outside the content.",
                headers={"Content-Range": f"bytes */{item.size}"},
            ) from None

    if byte_range is None:
        headers["Content-Length"] = str(item.size)
        whole = (0, item.size - 1) if method == "GET" and item.size else None
        return Plan(200, headers, whole)

    start, end = byte_range
    headers["Content-Range"] = f"bytes {start}-{end}/{item.size}"
    headers["Content-Length"] = str(end - start + 1)
    return Plan(206, headers, byte_range)
