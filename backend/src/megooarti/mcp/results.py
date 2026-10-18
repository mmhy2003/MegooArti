"""How a tool gives a list (E5): a page at a time, and never more than 64 KiB of text,
which an agent reads again on every turn."""

import base64
import binascii
from collections.abc import Callable
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_core import to_json

from megooarti.errors import ApiError

# What a tool takes for how many items a page has, and for where it goes on.
Limit = Annotated[int, Field(ge=1, le=200, description="How many items, at most: 1 to 200.")]
Cursor = Annotated[
    str | None, Field(max_length=200, description="`next_cursor` of the page before; none first.")
]

# The most a result says: its text, which is its JSON as the SDK writes it, indented.
CAP = 64 * 1024
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


def size(result: BaseModel) -> int:
    """How long a result's text is: its JSON, indented as the SDK writes it for the agent."""
    return len(to_json(result.model_dump(mode="json"), indent=2))


def most_that_fit(count: int, result_of: Callable[[int], BaseModel]) -> int:
    """How many items, from the first, a result can have within the cap: `result_of(n)` is
    the result with `n` of them. At least one, so that a list always goes on."""
    if count == 0 or size(result_of(count)) <= CAP:
        return count
    fits, too_many = 1, count
    while too_many - fits > 1:
        middle = (fits + too_many) // 2
        if size(result_of(middle)) <= CAP:
            fits = middle
        else:
            too_many = middle
    return fits


class Page[T](BaseModel):
    items: list[T]
    total: int  # how many there are in all
    next_cursor: str | None  # give it as `cursor` for the next page; null at the end
    # Whether fewer items were given than asked for, to keep within 64 KiB.
    truncated: bool


def page_of[T: BaseModel](
    items: list[T],
    total: int,
    offset: int,
    limit: int,
    within: Callable[[Page[T]], BaseModel] = lambda page: page,
) -> Page[T]:
    """A page of the items a list gave from `offset`, cut so that the result fits (E5).
    `within` is the result the page is part of, where it is not the result itself."""

    def page(kept: int) -> Page[T]:
        following = offset + kept
        return Page[T](
            items=items[:kept],
            total=total,
            next_cursor=cursor_at(following) if following < total else None,
            truncated=kept < min(limit, len(items)),
        )

    return page(most_that_fit(len(items), lambda kept: within(page(kept))))
