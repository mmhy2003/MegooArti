"""What the proxy engine offers a format that reads what it fetches."""

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from megooarti import secrets_box
from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy, service
from megooarti.repositories.models import NegativeCacheEntry, ProxyState, Repository
from megooarti.repositories.proxy import Absent, Answer, Source, Unavailable
from tests.repositories.fake_registry import REGISTRY, FakeRegistry, basic, digest_of

MANIFEST = f"{REGISTRY}/v2/team/app/manifests/1.0"
LAYER = b"a layer" * 1000
BLOB = f"{REGISTRY}/v2/team/app/blobs/{digest_of(LAYER)}"
ACCEPT = "application/vnd.oci.image.manifest.v1+json"


@pytest.fixture
def registry(app) -> FakeRegistry:
    fake = FakeRegistry()
    fake.add_image("team/app", "1.0", LAYER)
    fake.accounts["ci"] = "secret"
    app.state.http = fake.client()
    return fake


@pytest.fixture
async def upstream(db, settings) -> Repository:
    auth = {"type": "basic", "username": "ci", "secret": secrets_box.seal(settings, "secret")}
    repository = await service.create_repository(
        db,
        name="upstream",
        format="raw",
        type="proxy",
        online=True,
        blob_store=None,
        proxy={"remote_url": REGISTRY, "remote_auth": auth},
    )
    await db.commit()
    return repository


@pytest.fixture
async def context(upstream, context_for, registry, app, monkeypatch):
    context = await context_for(upstream, None, outbound=lambda: app.state.http)
    monkeypatch.setattr(context.format, "remote_signs_in", True)
    return context


def source(url: str = MANIFEST, **options) -> Source:
    return Source(url, accept=ACCEPT, subject="team/app", **options)


async def state(db, repository) -> ProxyState | None:
    return await db.scalar(select(ProxyState).where(ProxyState.repository_id == repository.id))


async def test_a_document_is_fetched_into_memory_with_its_headers(context, registry, db, upstream):
    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=100_000)

    assert not db.in_transaction()  # committed: nothing of the caller's may be pending
    assert isinstance(answer, Answer)
    assert digest_of(answer.body) == answer.headers["Docker-Content-Digest"]
    assert registry.requests[-1]["headers"]["accept"] == ACCEPT
    recorded = await state(db, upstream)
    assert recorded is None or recorded.failures == 0


async def test_asking_signs_in_with_the_repositorys_credential(context, registry):
    await proxy.ask(context, "manifests/app/1.0", source(), limit=100_000)
    registry.requests.clear()
    await proxy.probe(context, "manifests/app/1.0", source())

    assert [account for account, _ in registry.issued.values()] == ["ci"]
    # The next request for the same image sends its token at once.
    assert [seen["headers"]["authorization"] for seen in registry.requests] == ["Bearer token-1"]


async def test_a_format_whose_remotes_issue_no_tokens_does_not_sign_in(
    context, registry, monkeypatch
):
    monkeypatch.setattr(context.format, "remote_signs_in", False)

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=100_000)

    assert isinstance(answer, Unavailable) and answer.status == 401
    assert registry.issued == {}


async def test_asking_about_a_document_fetches_nothing(context, registry):
    answer = await proxy.probe(context, "manifests/app/1.0", source())

    assert isinstance(answer, Answer)
    assert answer.body == b""
    assert answer.headers["docker-content-digest"].startswith("sha256:")
    assert {seen["method"] for seen in registry.requests if seen["path"] != "/token"} == {"HEAD"}


async def test_what_the_remote_does_not_have_is_remembered(context, registry, db):
    missing = f"{REGISTRY}/v2/team/app/manifests/2.0"

    first = await proxy.ask(context, "manifests/app/2.0", source(missing), limit=1000)
    asked = len(registry.requests)
    again = await proxy.probe(context, "manifests/app/2.0", source(missing))

    assert first == again == Absent()
    assert len(registry.requests) == asked  # the second answer came from memory
    assert list(await db.scalars(select(NegativeCacheEntry.path))) == ["manifests/app/2.0"]


async def test_a_miss_is_not_remembered_where_the_path_has_other_addresses(context, registry, db):
    missing = f"{REGISTRY}/v2/team/app/manifests/2.0"
    unremembered = source(missing, remember_missing=False)

    first = await proxy.ask(context, "manifests/app/2.0", unremembered, limit=1000)
    asked = len(registry.requests)
    again = await proxy.ask(context, "manifests/app/2.0", unremembered, limit=1000)

    assert first == again == Absent()
    assert len(registry.requests) > asked
    assert list(await db.scalars(select(NegativeCacheEntry))) == []


async def test_a_remote_that_fails_is_recorded_and_says_what_it_answered(
    context, registry, db, upstream
):
    registry.status = 503

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)

    assert isinstance(answer, Unavailable)
    assert (answer.error.status_code, answer.error.code) == (502, "remote_unavailable")
    assert answer.status == 503
    recorded = await state(db, upstream)
    assert (recorded.failures, recorded.last_error) == (1, "the remote answered 503")


async def test_a_refusal_is_told_apart_from_a_failure(context, registry):
    registry.status_of["GET /v2/team/app/manifests/1.0"] = 403

    refused = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)

    assert isinstance(refused, Unavailable) and refused.status == 403


async def test_a_credential_that_is_refused_is_not_a_refusal_of_what_was_asked_for(
    context, registry
):
    registry.accounts.clear()  # the repository's credential is no longer good

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)

    assert isinstance(answer, Unavailable) and answer.status is None
    assert "its sign-in address refused the credential" in answer.error.message


async def test_a_blocked_remote_is_not_asked(context, registry, db, upstream):
    upstream.config = {**upstream.config, "proxy": {**upstream.config["proxy"], "blocked": True}}
    await db.commit()

    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=1000)
    asked = await proxy.probe(context, "manifests/app/1.0", source())

    assert isinstance(answer, Unavailable) and isinstance(asked, Unavailable)
    assert "blocked" in answer.error.message
    assert registry.requests == []


async def test_a_document_longer_than_its_limit_is_not_read(context, registry, db, upstream):
    answer = await proxy.ask(context, "manifests/app/1.0", source(), limit=10)

    assert isinstance(answer, Unavailable) and answer.status is None
    assert (await state(db, upstream)).blocked_until is None


@pytest.mark.parametrize("address", ["https://127.0.0.1/v2/x", "file:///etc/passwd", "https://"])
async def test_an_address_that_must_not_be_fetched_is_not(context, registry, address):
    answer = await proxy.ask(context, "manifests/app/1.0", source(address), limit=1000)

    assert isinstance(answer, Unavailable)
    assert registry.requests == []


async def test_the_credential_stays_with_the_remotes_own_origin(context, registry):
    elsewhere = "https://mirror.registry.test/v2/team/app/manifests/1.0"

    answer = await proxy.ask(context, "manifests/app/1.0", source(elsewhere), limit=100_000)

    assert isinstance(answer, Answer)
    presented = [seen["headers"].get("authorization") for seen in registry.requests]
    assert basic("ci", "secret") not in presented
    assert [account for account, _ in registry.issued.values()] == [None]


async def test_what_cannot_be_used_is_recorded_against_the_remote(context, db, upstream):
    error = await proxy.refuse(context, "manifests/app/1.0", "it sent something else")

    assert isinstance(error, ApiError) and error.status_code == 502
    assert "it sent something else" in error.message
    assert (await state(db, upstream)).last_error == "it sent something else"


async def test_a_whole_file_is_fetched_with_a_sign_in_and_checked(context, registry, db):
    sha256 = hashlib.sha256(LAYER).hexdigest()
    registry.blobs_at = "https://cdn.registry.test"

    await proxy.ensure_cached(context, "blobs/one", source=source(BLOB, digests={"sha256": sha256}))
    await db.commit()

    assert await context.read("blobs/one", limit=len(LAYER)) == LAYER
    assert registry.asked(host="cdn.registry.test") == [f"/cdn/{digest_of(LAYER)}"]


async def test_a_whole_file_that_is_missing_need_not_be_remembered(context, registry, db):
    data = b"pushed a moment later"
    address = f"{REGISTRY}/v2/team/app/blobs/{digest_of(data)}"
    wanted = source(address, remember_missing=False)

    with pytest.raises(ApiError) as missing:
        await proxy.ensure_cached(context, "blobs/two", source=wanted)
    registry.add_blob("team/app", data)
    await proxy.ensure_cached(context, "blobs/two", source=wanted)

    assert missing.value.status_code == 404
    assert await context.read("blobs/two", limit=100) == data


async def test_a_cached_file_records_what_it_refers_to(context, db):
    staged = await context.stage_bytes(b"a manifest")
    await context.cache(
        "manifests/app/one",
        staged,
        content_type=ACCEPT,
        attributes={},
        now=utcnow(),
        references=["blobs/not-fetched-yet", "blobs/another"],
    )
    again = await context.stage_bytes(b"a manifest")
    await context.cache(
        "manifests/app/one", again, content_type=ACCEPT, attributes={}, now=utcnow()
    )

    # Nothing said the second time: what was recorded stands.
    assert await context.references("manifests/app/one") == [
        "blobs/another",
        "blobs/not-fetched-yet",
    ]
    assert await context.referenced(["blobs/another", "blobs/x"]) == {"blobs/another"}


async def test_what_is_held_can_be_marked_as_still_what_the_remote_has(context, db):
    long_ago = utcnow() - timedelta(days=3)
    staged = await context.stage_bytes(b"a tag")
    await context.cache("tags/app/1.0", staged, content_type=None, attributes={}, now=long_ago)

    await proxy.still_current(context, "tags/app/1.0")
    await proxy.still_current(context, "tags/app/none")  # nothing held: nothing to mark

    assert (await context.stat("tags/app/1.0")).verified > long_ago + timedelta(days=2)
