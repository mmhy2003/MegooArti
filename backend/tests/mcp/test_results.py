"""A tool's list a page at a time, never more than 64 KiB (MCP spec E5)."""

import pytest
from pydantic import BaseModel

from megooarti.errors import ApiError
from megooarti.mcp.results import CAP, cursor_at, fitting, offset_of, page_of


class Item(BaseModel):
    text: str


def items(count: int, size: int) -> list[Item]:
    return [Item(text="x" * size) for _ in range(count)]


def test_a_page_that_fits_is_given_whole_with_a_cursor_to_the_next():
    given = page_of(items(3, 10), total=10, offset=4, limit=3)

    assert len(given.items) == 3
    assert given.truncated is False
    assert offset_of(given.next_cursor) == 7


def test_the_last_page_has_no_cursor():
    given = page_of(items(2, 10), total=6, offset=4, limit=50)

    assert given.next_cursor is None


def test_a_page_too_long_is_cut_and_says_so_and_its_cursor_leads_on_from_the_cut():
    given = page_of(items(5, 20_000), total=5, offset=0, limit=5)

    assert len(given.items) == 3  # 60 KB of text, then the room the rest needs
    assert given.truncated is True
    assert offset_of(given.next_cursor) == 3
    assert len(given.model_dump_json()) <= CAP


def test_one_item_longer_than_a_page_is_still_given():
    assert fitting(items(2, CAP)) == 1


# Not base64; base64 cut short; base64 of "o:q", which names no item.
@pytest.mark.parametrize("cursor", ["not-one", cursor_at(3)[:-2] + "!!", "bzpx"])
def test_a_cursor_no_list_gave_is_refused(cursor):
    with pytest.raises(ApiError) as refused:
        offset_of(cursor)

    assert (refused.value.code, refused.value.details) == (
        "validation_error",
        [{"field": "cursor", "message": "Not a cursor a list gave."}],
    )


def test_no_cursor_is_the_first_page():
    assert (offset_of(None), offset_of("")) == (0, 0)
