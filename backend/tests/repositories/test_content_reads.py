import hashlib
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.repositories.content import FileEntry, Stored, TooLarge
from megooarti.repositories.formats import ComponentKey, Format
from tests.repositories.conftest import body, someone

EVERYTHING = someone("repository:raw:files")
WHEN = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
DOCUMENT = b"<metadata>generated</metadata>"


class Packaged(Format):
    """Files at namespace/name/version/file belong to a package; others to none."""

    name = "raw"

    def describe_component(self, path):
        parts = path.split("/")
        return ComponentKey(*parts[:3]) if len(parts) == 4 else None


def request(method: str = "GET", **headers: str) -> Request:
    raw = [(name.replace("_", "-").encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw})


@pytest.fixture
async def context(files, context_for):
    made = await context_for(files, EVERYTHING)
    made.format = Packaged()
    return made


def answer(context, incoming: Request):
    return context.respond_with(
        DOCUMENT,
        incoming,
        filename="maven-metadata.xml",
        content_type="application/xml",
        last_modified=WHEN,
    )


async def test_stat_describes_what_is_at_a_path(context):
    asset, _ = await context.put("acme/app/1.0/app.jar", body(b"jar bytes"))

    stored = await context.stat("acme/app/1.0/app.jar")

    assert stored == Stored(
        path="acme/app/1.0/app.jar",
        kind="asset",
        size=9,
        md5=hashlib.md5(b"jar bytes").hexdigest(),
        sha1=hashlib.sha1(b"jar bytes").hexdigest(),
        sha256=hashlib.sha256(b"jar bytes").hexdigest(),
        sha512=hashlib.sha512(b"jar bytes").hexdigest(),
        content_type=asset.content_type,
        modified=asset.updated_at,
    )
    assert await context.stat("acme/app/1.0/missing.jar") is None


async def test_versions_lists_each_version_with_its_latest_change(context):
    first, _ = await context.put("acme/app/1.0/app.jar", body(b"a"))
    second, _ = await context.put("acme/app/1.0/app.pom", body(b"b"))
    third, _ = await context.put("acme/app/2.0/app.jar", body(b"c"))
    await context.put("acme/other/9.0/other.jar", body(b"d"))
    await context.put("elsewhere/app/7.0/app.jar", body(b"e"))

    versions = await context.versions("acme", "app")

    assert versions == {
        "1.0": max(first.updated_at, second.updated_at),
        "2.0": third.updated_at,
    }
    assert await context.versions("acme", "nothing") == {}


async def test_files_lists_the_files_of_one_version(context):
    jar, _ = await context.put("acme/app/1.0/app.jar", body(b"a"))
    pom, _ = await context.put("acme/app/1.0/app.pom", body(b"b"))
    await context.put("acme/app/2.0/app.jar", body(b"c"))

    assert await context.files("acme", "app", "1.0") == [
        FileEntry("acme/app/1.0/app.jar", jar.updated_at),
        FileEntry("acme/app/1.0/app.pom", pom.updated_at),
    ]
    assert await context.files("acme", "app", "3.0") == []


async def test_names_says_which_packages_exist_in_a_namespace(context):
    await context.put("acme/app/1.0/app.jar", body(b"a"))
    await context.put("acme/tool/1.0/tool.jar", body(b"b"))

    assert await context.names("acme", ["app", "tool", "ghost"]) == {"app", "tool"}
    assert await context.names("acme", []) == set()
    assert await context.names("other", ["app"]) == set()


async def test_read_returns_a_small_file_and_refuses_a_large_one(context):
    await context.put("notes.txt", body(b"x" * 2000))

    assert await context.read("notes.txt", limit=2000) == b"x" * 2000
    assert await context.read("missing.txt", limit=2000) is None
    with pytest.raises(TooLarge):
        await context.read("notes.txt", limit=1999)


async def test_receive_reads_a_small_upload_and_gives_up_on_a_large_one(context):
    assert await context.receive(body(b"y" * 1500), limit=1500) == b"y" * 1500
    assert await context.receive(body(b"y" * 1501), limit=1500) is None
    assert await context.receive(body(b""), limit=10) == b""


async def test_generated_bytes_are_answered_like_a_stored_file(context):
    response = answer(context, request())

    digest = hashlib.sha256(DOCUMENT).hexdigest()
    assert (response.status_code, response.body) == (200, DOCUMENT)
    assert response.headers["ETag"] == f'"{digest}"'
    assert response.headers["X-Checksum-Sha1"] == hashlib.sha1(DOCUMENT).hexdigest()
    assert response.headers["Content-Type"] == "application/xml"
    assert response.headers["Content-Length"] == str(len(DOCUMENT))
    assert response.headers["Last-Modified"] == "Wed, 04 Mar 2026 05:06:07 GMT"
    assert response.headers["Content-Disposition"].startswith(
        'attachment; filename="maven-metadata.xml"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox"


async def test_generated_bytes_honour_head_conditions_and_ranges(context):
    etag = answer(context, request()).headers["ETag"]

    head = answer(context, request("HEAD"))
    unchanged = answer(context, request(if_none_match=etag))
    partial = answer(context, request(range="bytes=1-8"))

    assert (head.status_code, head.body) == (200, b"")
    assert head.headers["Content-Length"] == str(len(DOCUMENT))
    assert (unchanged.status_code, unchanged.body) == (304, b"")
    assert (partial.status_code, partial.body) == (206, DOCUMENT[1:9])
    assert partial.headers["Content-Range"] == f"bytes 1-8/{len(DOCUMENT)}"


async def test_a_response_with_its_own_etag_is_not_hashed(context):
    def respond(incoming: Request):
        return context.respond_with(
            DOCUMENT,
            incoming,
            filename="package.json",
            content_type="application/json",
            last_modified=WHEN,
            etag="known-already",
        )

    response = respond(request())
    unchanged = respond(request(if_none_match='"known-already"'))

    assert (response.status_code, response.body) == (200, DOCUMENT)
    assert response.headers["ETag"] == '"known-already"'
    assert not [name for name in response.headers if name.lower().startswith("x-checksum")]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert (unchanged.status_code, unchanged.body) == (304, b"")


class Shout:
    """Upper-cases what passes through, and holds the last byte back until the end."""

    def __init__(self) -> None:
        self._held = b""

    def feed(self, chunk: bytes) -> bytes:
        data = self._held + chunk.upper()
        self._held = data[-1:]
        return data[:-1]

    def finish(self) -> bytes:
        return self._held + b"!"


async def letters():
    for letter in (b"a", b"b", b"c"):
        yield letter


async def test_a_stored_file_can_be_read_as_a_stream(context):
    await context.put("notes/big.txt", body(b"0123456789" * 200_000))
    stored = await context.stat("notes/big.txt")

    pieces = [piece async for piece in context.open(stored)]

    assert b"".join(pieces) == b"0123456789" * 200_000
    assert len(pieces) > 1  # never one piece of two megabytes


def streamed(context, incoming: Request, etag: str = "known"):
    return context.respond_stream(
        incoming,
        letters,
        etag=etag,
        content_type="text/html; charset=utf-8",
        filename="index.html",
        last_modified=WHEN,
    )


async def test_a_stream_is_answered_like_content_without_a_length(context):
    response = await streamed(context, request())

    assert (response.status_code, await sent(response)) == (200, b"abc")
    assert response.headers["ETag"] == '"known"'
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.headers["Last-Modified"] == "Wed, 04 Mar 2026 05:06:07 GMT"
    assert response.headers["Accept-Ranges"] == "none"
    assert "content-length" not in response.headers
    assert response.headers["Content-Disposition"].startswith('attachment; filename="index.html"')
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox"


async def test_a_stream_is_not_started_when_it_is_not_sent(context, db):
    started = []

    def body_of_the_answer():
        started.append(True)
        return letters()

    def answer(incoming: Request):
        return context.respond_stream(
            incoming,
            body_of_the_answer,
            etag="known",
            content_type="text/plain",
            filename="x.txt",
            last_modified=WHEN,
        )

    head = await answer(request("HEAD"))
    unchanged = await answer(request(if_none_match='"known"'))
    ranged = await answer(request(range="bytes=0-0"))

    assert (head.status_code, await sent(head)) == (200, b"")
    assert "content-length" not in head.headers
    assert (unchanged.status_code, unchanged.body) == (304, b"")
    assert started == [True]  # only for the one that sends it
    assert (ranged.status_code, await sent(ranged)) == (200, b"abc")
    assert db.in_transaction() is False  # the connection is given back before the body


async def sent(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


async def shouted(context, incoming: Request, variant: str = "shout", **options):
    return await context.respond_transformed(
        "notes/readme.txt", incoming, Shout(), variant=variant, **options
    )


async def test_a_stored_file_is_sent_through_a_transformer(context):
    await context.put("notes/readme.txt", body(b"hello, " * 100_000 + b"world"))

    response = await shouted(context, request())

    assert response.status_code == 200
    assert await sent(response) == b"HELLO, " * 100_000 + b"WORLD!"
    assert "content-length" not in response.headers
    assert response.headers["Accept-Ranges"] == "none"
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="readme.txt"')
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert not [name for name in response.headers if name.lower().startswith("x-checksum")]


async def test_the_etag_of_a_transformed_file_names_the_file_and_the_transformation(context):
    await context.put("notes/readme.txt", body(b"one"))
    first = (await shouted(context, request())).headers["ETag"]
    again = (await shouted(context, request())).headers["ETag"]
    another_way = (await shouted(context, request(), "whisper")).headers["ETag"]
    await context.put("notes/readme.txt", body(b"two"))
    another_file = (await shouted(context, request())).headers["ETag"]

    stored = hashlib.sha256(b"one").hexdigest()
    assert first == '"' + hashlib.sha256(f"{stored}\nshout".encode()).hexdigest() + '"'
    assert again == first
    assert len({first, another_way, another_file}) == 3


async def test_a_transformed_file_honours_head_and_conditions_and_serves_no_range(context):
    await context.put("notes/readme.txt", body(b"hello"))
    etag = (await shouted(context, request())).headers["ETag"]

    head = await shouted(context, request("HEAD"))
    unchanged = await shouted(context, request(if_none_match=etag))
    ranged = await shouted(context, request(range="bytes=0-1"))

    assert (head.status_code, await sent(head), head.headers["ETag"]) == (200, b"", etag)
    assert "content-length" not in head.headers  # not 0: the length is simply not known
    assert (unchanged.status_code, unchanged.body) == (304, b"")
    assert (ranged.status_code, await sent(ranged)) == (200, b"HELLO!")
    assert "content-range" not in ranged.headers


async def test_a_transformed_response_can_name_its_type_and_its_file(context):
    await context.put("notes/readme.txt", body(b"{}"))

    response = await shouted(
        context, request(), content_type="application/json", filename="package.json"
    )

    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="package.json"')


async def test_transforming_a_file_that_is_not_stored_is_not_found(context):
    with pytest.raises(ApiError) as caught:
        await shouted(context, request())

    assert (caught.value.status_code, caught.value.code) == (404, "not_found")


async def test_sending_a_transformed_file_notes_the_download_and_keeps_no_transaction(context, db):
    asset, _ = await context.put("notes/readme.txt", body(b"hello"))
    await db.commit()

    await shouted(context, request("HEAD"))
    after_head = asset.last_downloaded_at
    response = await shouted(context, request())
    in_transaction = db.in_transaction()
    await sent(response)

    assert after_head is None
    assert asset.last_downloaded_at is not None
    assert in_transaction is False  # the connection is given back before the body is sent
