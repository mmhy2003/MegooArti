"""How a tool gives a list (E5): a page at a time, and never more than 64 KiB of text,
which an agent reads again on every turn."""

import base64
import binascii
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, Field

from megooarti.errors import ApiError

# What a tool takes for how many items a page has, and for where it goes on.
Limit = Annotated[int, Field(ge=1, le=200, description="How many items, at most: 1 to 200.")]
Cursor = Annotated[
    str | None, Field(max_length=200, description="`next_cursor` of the page before; none first.")
]

# The most a result says, as JSON.
CAP = 64 * 1024
# What a result says besides its items: its own fields, and those of the protocol.
_ROOM = 4 * 1024
_OFFSET = "o:"


def cursor_at(offset: int) -> str:
    """A cursor that leads on from the `offset`th item."""
    return base64.urlsafe_b64encode(f"{_OFFSET}{offset}".encode()).decode()


def offset_of(cursor: str | None) -> int:
    """Where a cursor that `cursor_at` made leads on from; 0 for none. Raises 422."""
    if not cursor:
        return 0
    try:
        said = base64.urlsafe_b64decode(cursor.encode()).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError):
        said = ""
    number = said.removeprefix(_OFFSET)
    if not said.startswith(_OFFSET) or not number.isdigit():
        details = [{"field": "cursor", "message": "Not a cursor a list gave."}]
        raise ApiError(422, "validation_error", "The request is not valid.", details)
    return int(number)


def fitting(items: Sequence[BaseModel]) -> int:
    """How many of the items, from the first, fit in a result (at least one)."""
    used = 0
    for count, item in enumerate(items):
        used += len(item.model_dump_json()) + 1
        if used > CAP - _ROOM and count > 0:
            return count
    return len(items)


class Page[T](BaseModel):
    items: list[T]
    total: int  # how many there are in all
    next_cursor: str | None  # give it as `cursor` for the next page; null at the end
    # Whether fewer items were given than asked for, to keep within 64 KiB.
    truncated: bool


def page_of[T: BaseModel](items: list[T], total: int, offset: int, limit: int) -> Page[T]:
    """A page of the items a list gave from `offset`, cut to fit (E5)."""
    kept = fitting(items)
    following = offset + kept
    return Page[T](
        items=items[:kept],
        total=total,
        next_cursor=cursor_at(following) if following < total else None,
        truncated=kept < min(limit, len(items)),
    )
