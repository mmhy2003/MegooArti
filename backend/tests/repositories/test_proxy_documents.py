"""A remote's small documents kept as metadata, gzipped ones among them, and what a format
reads of a file its proxy fetched."""

import gzip

import pytest

from megooarti.errors import ApiError
from megooarti.repositories import proxy, service
from megooarti.repositories.proxy import Answer, Source, Unavailable
from megooarti.repositories.raw import RawFormat
from tests.repositories.conftest import someone

REMOTE = "http://remote.test/files"
DOCUMENT = b'{"versions": ["1.0.0"]}'


@pytest.fixture
async def documents(db):
    """A proxy that asks its remote about a document every time it is asked for one."""
    repository = await service.create_repository(
        db,
        name="documents",
        format="raw",
        type="proxy",
        online=True,
        blob_store=None,
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": 0},
    )
    await db.commit()
    return repository


@pytest.fixture
async def context(documents, context_for, fake_remote, app):
    return await context_for(documents, someone("repository:*"), outbound=lambda: app.state.http)


async def test_a_gzipped_document_is_inflated_where_the_remote_is_known_to_send_one(
    context, fake_remote
):
    fake_remote.files["files/index.json"] = gzip.compress(DOCUMENT)
    fake_remote.content_encoding = "gzip"

    inflated = await proxy.ask(
        context, "index.json", Source(f"{REMOTE}/index.json", gzipped=True), limit=1000
    )
    refused = await proxy.ask(context, "index.json", Source(f"{REMOTE}/index.json"), limit=1000)

    assert isinstance(inflated, Answer) and inflated.body == DOCUMENT
    assert isinstance(refused, Unavailable)


async def test_a_gzipped_document_is_held_to_its_bound_once_inflated(context, fake_remote):
    fake_remote.files["files/index.json"] = gzip.compress(b"x" * 5000)
    fake_remote.content_encoding = "gzip"

    answer = await proxy.ask(
        context, "index.json", Source(f"{REMOTE}/index.json", gzipped=True), limit=1000
    )

    assert isinstance(answer, Unavailable)


async def test_a_document_is_kept_and_given_again_when_the_remote_cannot_be_asked(
    context, fake_remote
):
    fake_remote.files["files/index.json"] = DOCUMENT
    source = Source(f"{REMOTE}/index.json")

    first = await proxy.document(
        context, "index.json", source, limit=1000, content_type="application/json"
    )
    fake_remote.files["files/index.json"] = b'{"versions": ["1.0.0", "2.0.0"]}'
    second = await proxy.document(
        context, "index.json", source, limit=1000, content_type="application/json"
    )
    fake_remote.down = True
    third = await proxy.document(
        context, "index.json", source, limit=1000, content_type="application/json"
    )

    assert first == DOCUMENT
    assert second == third == b'{"versions": ["1.0.0", "2.0.0"]}'  # asked again: its age is 0
    assert (await context.stat("index.json")).content_type == "application/json"


async def test_a_document_the_remote_never_had_is_not_found(context, fake_remote):
    with pytest.raises(ApiError) as missing:
        await proxy.document(
            context,
            "absent.json",
            Source(f"{REMOTE}/absent.json"),
            limit=1000,
            content_type="application/json",
        )

    assert missing.value.status_code == 404


async def test_what_a_format_reads_of_a_fetched_file_is_kept_with_it_and_its_component(
    context, fake_remote, monkeypatch
):
    async def describe(self, context, path, staged):
        return {"read": {"title": "Hello"}}

    monkeypatch.setattr(RawFormat, "describe_fetched", describe)
    fake_remote.files["files/docs/hello.txt"] = b"hello"

    await proxy.ensure_cached(context, "docs/hello.txt")

    asset = await context.get("docs/hello.txt")
    assert asset.attributes["read"] == {"title": "Hello"}
    assert "remote_etag" in asset.attributes  # beside what the engine keeps
    (component,) = await context.components("docs", "hello.txt")
    assert component.attributes == {"read": {"title": "Hello"}}
