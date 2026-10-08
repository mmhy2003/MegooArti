from dataclasses import replace
from datetime import UTC, datetime

import pytest
from starlette.datastructures import Headers

from megooarti.errors import ApiError
from megooarti.repositories.serving import Plan, Servable, plan, plan_stream

ITEM = Servable(
    sha256="a" * 64,
    md5="b" * 32,
    sha1="c" * 40,
    sha512="d" * 128,
    size=1000,
    content_type="text/plain",
    last_modified=datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    filename="notes.txt",
)
ETAG = '"' + "a" * 64 + '"'
MODIFIED = "Fri, 02 Jan 2026 03:04:05 GMT"


def make(method: str = "GET", item: Servable = ITEM, **headers: str) -> Plan:
    return plan(
        method, Headers({name.replace("_", "-"): value for name, value in headers.items()}), item
    )


def test_a_plain_get_sends_everything_with_the_full_set_of_headers():
    result = make()

    assert (result.status, result.byte_range) == (200, (0, 999))
    assert result.headers == {
        "Content-Type": "text/plain",
        "Content-Length": "1000",
        "ETag": ETAG,
        "Last-Modified": MODIFIED,
        "Accept-Ranges": "bytes",
        "X-Checksum-Md5": "b" * 32,
        "X-Checksum-Sha1": "c" * 40,
        "X-Checksum-Sha256": "a" * 64,
        "X-Checksum-Sha512": "d" * 128,
        "Content-Disposition": "attachment; filename=\"notes.txt\"; filename*=UTF-8''notes.txt",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }


def test_head_sends_the_headers_and_no_body():
    result = make("HEAD")

    assert (result.status, result.byte_range) == (200, None)
    assert result.headers["Content-Length"] == "1000"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        (
            "notes final.txt",
            "attachment; filename=\"notes_final.txt\"; filename*=UTF-8''notes%20final.txt",
        ),
        (
            "résumé.pdf",
            "attachment; filename=\"r_sum_.pdf\"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf",
        ),
        ('a"b;c.txt', "attachment; filename=\"a_b_c.txt\"; filename*=UTF-8''a%22b%3Bc.txt"),
        ("✓", "attachment; filename=\"_\"; filename*=UTF-8''%E2%9C%93"),
    ],
)
def test_the_download_name_is_safe_in_a_header(filename, expected):
    assert make(item=replace(ITEM, filename=filename)).headers["Content-Disposition"] == expected


@pytest.mark.parametrize("value", [ETAG, "*", f"W/{ETAG}", f'"other", {ETAG}'])
def test_a_matching_if_none_match_is_not_modified(value):
    result = make(if_none_match=value)

    assert (result.status, result.byte_range) == (304, None)
    assert result.headers["ETag"] == ETAG
    assert "Content-Length" not in result.headers


def test_a_different_if_none_match_sends_the_content():
    assert make(if_none_match='"other"').status == 200


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (MODIFIED, 304),
        ("Sat, 03 Jan 2026 00:00:00 GMT", 304),
        ("Thu, 01 Jan 2026 00:00:00 GMT", 200),
        ("not a date", 200),
    ],
)
def test_if_modified_since(value, status):
    assert make(if_modified_since=value).status == status


def test_if_none_match_takes_priority_over_if_modified_since():
    assert make(if_none_match='"other"', if_modified_since=MODIFIED).status == 200


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("bytes=0-0", (0, 0)),
        ("bytes=10-19", (10, 19)),
        ("bytes=990-", (990, 999)),
        ("bytes=999-999", (999, 999)),
        ("bytes=-10", (990, 999)),
        ("bytes=-5000", (0, 999)),
        ("bytes=500-5000", (500, 999)),
        ("BYTES = 5-6", (5, 6)),
    ],
)
def test_one_satisfiable_range_is_partial_content(value, expected):
    result = make(range=value)
    start, end = expected

    assert (result.status, result.byte_range) == (206, expected)
    assert result.headers["Content-Range"] == f"bytes {start}-{end}/1000"
    assert result.headers["Content-Length"] == str(end - start + 1)


@pytest.mark.parametrize(
    "value", ["bytes=0-1,5-6", "items=0-1", "bytes=abc", "bytes=5-2", "bytes=-", "bytes", ""]
)
def test_a_range_that_is_not_understood_sends_everything(value):
    result = make(range=value)

    assert (result.status, result.byte_range) == (200, (0, 999))
    assert "Content-Range" not in result.headers


@pytest.mark.parametrize("value", ["bytes=1000-", "bytes=2000-3000", "bytes=-0"])
def test_a_range_outside_the_content_cannot_be_satisfied(value):
    with pytest.raises(ApiError) as caught:
        make(range=value)

    assert (caught.value.status_code, caught.value.code) == (416, "range_not_satisfiable")
    assert caught.value.headers == {"Content-Range": "bytes */1000"}


def test_a_range_is_ignored_for_head():
    assert make("HEAD", range="bytes=0-9").status == 200


@pytest.mark.parametrize(("if_range", "status"), [(ETAG, 206), ('"other"', 200)])
def test_if_range_applies_the_range_only_to_the_same_content(if_range, status):
    assert make(range="bytes=0-9", if_range=if_range).status == status


def test_an_empty_file_has_no_body_and_no_satisfiable_range():
    empty = replace(ITEM, size=0)

    result = make(item=empty)

    assert (result.status, result.byte_range, result.headers["Content-Length"]) == (200, None, "0")
    for value in ("bytes=0-0", "bytes=-5", "bytes=0-"):
        with pytest.raises(ApiError):
            make(item=empty, range=value)


@pytest.mark.parametrize(
    "value",
    [
        "bytes=²-",
        "bytes=-³",
        "bytes=٣-٩",
        "bytes=" + "9" * 5000 + "-",
        "bytes=-" + "9" * 5000,
        "bytes=0-" + "9" * 5000,
    ],
    ids=[
        "superscript-start",
        "superscript-suffix",
        "arabic",
        "huge-start",
        "huge-suffix",
        "huge-end",
    ],
)
def test_digits_that_are_not_plain_or_are_absurdly_long_are_not_understood(value):
    result = plan("GET", Headers(raw=[(b"range", value.encode("latin-1", "replace"))]), ITEM)

    assert (result.status, result.byte_range) == (200, (0, 999))


def test_an_item_can_name_its_own_etag_and_leave_out_checksums():
    item = replace(ITEM, sha256="", md5=None, sha1=None, sha512=None, etag="chosen")

    made = make(item=item)
    unchanged = make(item=item, if_none_match='"chosen"')

    assert made.headers["ETag"] == '"chosen"'
    assert not [name for name in made.headers if name.startswith("X-Checksum")]
    assert made.headers["Content-Security-Policy"] == "sandbox"
    assert (unchanged.status, unchanged.byte_range) == (304, None)


MADE = replace(ITEM, sha256="", md5=None, sha1=None, sha512=None, size=0, etag="made")


def test_content_made_as_it_is_sent_declares_no_length_and_serves_no_range():
    made = plan_stream("GET", Headers({"range": "bytes=0-9"}), MADE)

    assert (made.status, made.send_body) == (200, True)
    assert made.headers["ETag"] == '"made"'
    assert made.headers["Accept-Ranges"] == "none"
    assert "Content-Length" not in made.headers
    assert "Content-Range" not in made.headers
    assert made.headers["Last-Modified"] == MODIFIED
    assert made.headers["Content-Disposition"].startswith('attachment; filename="notes.txt"')
    assert made.headers["X-Content-Type-Options"] == "nosniff"
    assert made.headers["Content-Security-Policy"] == "sandbox"
    assert not [name for name in made.headers if name.startswith("X-Checksum")]


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        ("HEAD", {}, (200, False)),
        ("GET", {"if-none-match": '"made"'}, (304, False)),
        ("GET", {"if-none-match": '"other"'}, (200, True)),
        ("GET", {"if-modified-since": MODIFIED}, (304, False)),
        ("GET", {"if-none-match": '"other"', "if-modified-since": MODIFIED}, (200, True)),
        ("HEAD", {"if-none-match": "*"}, (304, False)),
    ],
)
def test_content_made_as_it_is_sent_honours_head_and_conditions(method, headers, expected):
    made = plan_stream(method, Headers(headers), MADE)

    assert (made.status, made.send_body) == expected
    assert made.headers["ETag"] == '"made"'
