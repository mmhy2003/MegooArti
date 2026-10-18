"""A tool's list a page at a time, never more than 64 KiB (MCP spec E5)."""

import pytest
from pydantic import BaseModel

from megooarti.errors import ApiError
from megooarti.mcp.results import CAP, cursor_at, most_that_fit, offset_of, page_of, size


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

    assert len(given.items) == 3
    assert given.truncated is True
    assert offset_of(given.next_cursor) == 3
    assert size(given) <= CAP


class Wide(BaseModel):
    """Short fields, many of them: what indenting makes longer by half again, or more."""

    a: int = 1
    b: int = 2
    c: int = 3
    d: int = 4
    e: int = 5
    f: int = 6


def test_the_cap_is_of_the_text_the_agent_reads_as_the_sdk_indents_it():
    many = [Wide() for _ in range(1000)]  # some 40 KB as compact JSON, far more indented

    given = page_of(many, total=1000, offset=0, limit=1000)

    assert given.truncated is True
    assert size(given) <= CAP
    assert size(page_of(many[: len(given.items) + 1], 1000, 0, 1000)) > CAP or given.truncated


def test_one_item_longer_than_a_page_is_still_given():
    assert most_that_fit(2, lambda kept: Item(text="x" * CAP * kept)) == 1


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
