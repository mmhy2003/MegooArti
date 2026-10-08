import hashlib
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

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
