import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import formats, proxy, service
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset, NegativeCacheEntry, ProxyState, Repository
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.fake_remote import etag_of

URL = "/repository/mirror/lib/a.bin"
REMOTE_FILE = "files/lib/a.bin"
REMOTE_PATH = "/files/lib/a.bin"
CONTENT = b"content held by the remote"
REPOSITORIES = "/api/v1/repositories"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


@pytest.fixture
def remote(fake_remote, mirror):
    fake_remote.files[REMOTE_FILE] = CONTENT
    return fake_remote


async def make_stale(db) -> None:
    long_ago = utcnow() - timedelta(days=3)
    await db.execute(update(Asset).values(last_verified_at=long_ago))
    await db.commit()


async def reconfigure(db, mirror, **settings) -> None:
    current = dict(mirror.config)
    current["proxy"] = {**current["proxy"], **settings}
    mirror.config = current
    await db.commit()


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_a_miss_is_fetched_cached_and_served(client, root, remote):
    first = await client.get(URL, headers=root)
    second = await client.get(URL, headers=root)

    assert (first.status_code, first.content) == (200, CONTENT)
    assert second.content == CONTENT
    assert first.headers["ETag"] == f'"{hashlib.sha256(CONTENT).hexdigest()}"'
    assert first.headers["Content-Type"] == "application/x-remote"
    assert first.headers["Content-Disposition"].startswith('attachment; filename="a.bin"')
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert remote.paths() == [REMOTE_PATH]


async def test_the_cached_file_records_where_it_came_from(client, root, remote, db):
    await client.get(URL, headers=root)

    asset = await db.scalar(select(Asset))

    assert (asset.path, asset.created_by) == ("lib/a.bin", "proxy")
    assert asset.attributes["remote_etag"] == etag_of(CONTENT)
    assert asset.last_verified_at is not None


async def test_a_reader_needs_only_read_to_fill_the_cache(client, remote, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:raw:mirror:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    response = await client.get(URL, headers=basic("rae", PASSWORD))

    assert (response.status_code, response.content) == (200, CONTENT)


async def test_a_path_with_unusual_characters_is_encoded_for_the_remote(client, root, remote):
    remote.files["files/with space/ünï.bin"] = b"odd name"

    response = await client.get("/repository/mirror/with%20space/%C3%BCn%C3%AF.bin", headers=root)

    assert response.content == b"odd name"


async def test_what_the_remote_lacks_is_not_found_and_remembered(client, root, remote, db):
    missing = "/repository/mirror/nothing/here.bin"

    first = await client.get(missing, headers=root)
    second = await client.get(missing, headers=root)

    assert (first.status_code, error_code(first)) == (404, "not_found")
    assert second.status_code == 404
    assert remote.paths() == ["/files/nothing/here.bin"]

    await db.execute(update(NegativeCacheEntry).values(expires_at=utcnow() - timedelta(seconds=1)))
    await db.commit()
    await client.get(missing, headers=root)

    assert len(remote.paths()) == 2


async def test_with_the_negative_cache_off_the_remote_is_asked_every_time(
    client, root, remote, mirror, db
):
    await reconfigure(db, mirror, negative_cache={"enabled": False, "ttl_minutes": 1440})

    for _ in range(2):
        await client.get("/repository/mirror/nothing.bin", headers=root)

    assert len(remote.paths()) == 2


async def test_a_stale_file_is_revalidated_and_kept_when_unchanged(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)

    response = await client.get(URL, headers=root)

    assert response.content == CONTENT
    conditional = remote.requests[1]["headers"]
    assert conditional["if-none-match"] == etag_of(CONTENT)
    verified = await db.scalar(select(Asset.last_verified_at))
    assert utcnow() - verified < timedelta(minutes=1)


async def test_a_stale_file_is_replaced_when_the_remote_changed(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.files[REMOTE_FILE] = b"a newer version"

    response = await client.get(URL, headers=root)

    assert response.content == b"a newer version"
    assert await count(db, Asset) == 1


async def test_a_maximum_age_of_minus_one_never_revalidates(client, root, remote, mirror, db):
    await reconfigure(db, mirror, content_max_age_minutes=-1)
    await client.get(URL, headers=root)
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    await db.execute(update(Asset).values(last_verified_at=long_ago))
    await db.commit()

    await client.get(URL, headers=root)

    assert len(remote.paths()) == 1


def test_metadata_paths_use_the_metadata_age():
    class WithIndex(Format):
        def is_metadata(self, path: str) -> bool:
            return path.endswith("index.json")

    ages = {"content_max_age_minutes": -1, "metadata_max_age_minutes": 10}
    verified = datetime(2026, 1, 1, tzinfo=UTC)
    asset = Asset(last_verified_at=verified)
    later = verified + timedelta(minutes=11)

    assert proxy.is_fresh(ages, WithIndex(), asset, "pkg/thing.tgz", later) is True
    assert proxy.is_fresh(ages, WithIndex(), asset, "pkg/index.json", later) is False
    assert proxy.is_fresh(ages, WithIndex(), Asset(), "pkg/thing.tgz", later) is False


async def test_a_cached_file_is_served_while_the_remote_is_down(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.down = True

    first = await client.get(URL, headers=root)
    asked = len(remote.requests)
    second = await client.get(URL, headers=root)

    assert (first.status_code, first.content) == (200, CONTENT)
    assert second.content == CONTENT
    state = await db.scalar(select(ProxyState))
    assert (state.failures, state.last_error) == (1, "ConnectError")
    assert state.blocked_until > utcnow()
    assert len(remote.requests) == asked  # blocked: the remote was left alone


async def test_a_miss_while_the_remote_is_down_is_bad_gateway_then_blocked(
    client, root, remote, db
):
    remote.down = True

    first = await client.get(URL, headers=root)
    remote.down = False
    second = await client.get(URL, headers=root)

    assert (first.status_code, error_code(first)) == (502, "remote_unavailable")
    assert (second.status_code, error_code(second)) == (502, "remote_unavailable")
    assert remote.paths() == []  # the second request never reached the working remote


async def test_the_block_ends_and_a_success_clears_it(client, root, remote, db):
    remote.down = True
    await client.get(URL, headers=root)
    remote.down = False
    await db.execute(update(ProxyState).values(blocked_until=utcnow() - timedelta(seconds=1)))
    await db.commit()

    response = await client.get(URL, headers=root)

    assert response.content == CONTENT
    state = await db.scalar(select(ProxyState).execution_options(populate_existing=True))
    assert (state.failures, state.blocked_until, state.last_error) == (0, None, None)


async def test_a_proxy_blocked_by_hand_serves_its_cache_and_fetches_nothing(
    client, root, remote, mirror, db
):
    await client.get(URL, headers=root)
    await reconfigure(db, mirror, blocked=True)
    await make_stale(db)

    cached = await client.get(URL, headers=root)
    uncached = await client.get("/repository/mirror/other.bin", headers=root)

    assert cached.content == CONTENT
    assert (uncached.status_code, error_code(uncached)) == (502, "remote_unavailable")
    assert len(remote.paths()) == 1


async def test_a_refused_credential_fails_each_request_without_blocking(client, root, remote):
    remote.status = 401

    first = await client.get(URL, headers=root)
    second = await client.get(URL, headers=root)

    assert (first.status_code, error_code(first)) == (502, "remote_unavailable")
    assert "401" in first.json()["error"]["message"]
    assert second.status_code == 502
    assert len(remote.paths()) == 2


async def test_an_incomplete_download_caches_nothing(client, root, remote, db):
    remote.declared_extra = 7

    response = await client.get(URL, headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert await count(db, Asset) == 0


async def test_an_incomplete_refresh_keeps_the_previous_copy(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.files[REMOTE_FILE] = b"a newer version"
    remote.declared_extra = 7

    response = await client.get(URL, headers=root)

    assert (response.status_code, response.content) == (200, CONTENT)


async def test_a_cached_file_survives_the_remote_dropping_it(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.files.clear()

    response = await client.get(URL, headers=root)
    again = await client.get(URL, headers=root)

    assert (response.status_code, response.content) == (200, CONTENT)
    assert again.content == CONTENT
    assert len(remote.paths()) == 2  # asked once more, then trusted for the maximum age
    assert await count(db, NegativeCacheEntry) == 0


async def test_the_stored_credential_is_sent_to_the_remote(admin_client, fake_remote):
    fake_remote.files["files/lib/a.bin"] = CONTENT
    await admin_client.post(
        REPOSITORIES,
        json={
            "name": "private",
            "format": "raw",
            "type": "proxy",
            "proxy": {
                "remote_url": "http://remote.test/files",
                "remote_auth": {"type": "basic", "username": "robot", "secret": "s3cret"},
            },
        },
    )

    response = await admin_client.get("/repository/private/lib/a.bin")

    assert response.content == CONTENT
    expected = "Basic " + base64.b64encode(b"robot:s3cret").decode()
    assert fake_remote.requests[0]["headers"]["authorization"] == expected


async def test_a_credential_that_cannot_be_unsealed_is_reported_without_asking(
    client, root, remote, mirror, db
):
    broken = {"type": "bearer", "username": "", "secret": "enc:v1:not-sealed-with-this-key"}
    await reconfigure(db, mirror, remote_auth=broken)

    response = await client.get(URL, headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert "credential" in response.json()["error"]["message"]
    assert remote.requests == []


async def test_head_for_an_uncached_file_asks_the_remote_and_caches_nothing(
    client, root, remote, db
):
    head = await client.head(URL, headers=root)
    missing = await client.head("/repository/mirror/nothing.bin", headers=root)

    assert (head.status_code, head.content) == (200, b"")
    assert head.headers["Content-Length"] == str(len(CONTENT))
    assert head.headers["Content-Type"] == "application/x-remote"
    assert missing.status_code == 404
    assert [seen["method"] for seen in remote.requests] == ["HEAD", "HEAD"]
    assert await count(db, Asset) == 0


async def test_head_for_a_cached_file_is_answered_from_the_cache(client, root, remote):
    await client.get(URL, headers=root)

    head = await client.head(URL, headers=root)

    assert head.headers["Content-Length"] == str(len(CONTENT))
    assert head.headers["ETag"] == f'"{hashlib.sha256(CONTENT).hexdigest()}"'
    assert len(remote.requests) == 1


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
async def test_a_proxy_repository_cannot_be_written_to(client, root, remote, method, db):
    response = await client.request(method, URL, content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
    assert await count(db, Asset) == 0


async def test_invalidating_the_cache_makes_the_proxy_ask_again(admin_client, remote, db):
    await admin_client.get(URL)
    await admin_client.get("/repository/mirror/nothing.bin")
    assert len(remote.paths()) == 2

    response = await admin_client.post(f"{REPOSITORIES}/mirror/invalidate-cache")
    await admin_client.get(URL)
    await admin_client.get("/repository/mirror/nothing.bin")

    assert response.status_code == 204
    assert len(remote.paths()) == 4
    assert remote.requests[2]["headers"]["if-none-match"] == etag_of(CONTENT)


async def test_invalidating_needs_a_proxy_and_the_permission(admin_client, other_client, files):
    not_a_proxy = await admin_client.post(f"{REPOSITORIES}/files/invalidate-cache")
    unknown = await admin_client.post(f"{REPOSITORIES}/ghost/invalidate-cache")
    anonymous = await other_client.post(f"{REPOSITORIES}/files/invalidate-cache")

    assert (not_a_proxy.status_code, error_code(not_a_proxy)) == (409, "not_a_proxy")
    assert unknown.status_code == 404
    assert anonymous.status_code == 401


async def test_the_repository_api_shows_the_blocking_state(admin_client, remote, db):
    remote.down = True
    await admin_client.get(URL)

    status = (await admin_client.get(f"{REPOSITORIES}/mirror")).json()["status"]

    assert (status["blocked"], status["failures"], status["last_error"]) == (
        False,
        1,
        "ConnectError",
    )
    assert status["auto_blocked_until"] is not None
    assert await db.scalar(select(Repository.type).where(Repository.name == "mirror")) == "proxy"


async def test_an_unreadable_credential_is_recorded_where_an_administrator_will_see_it(
    client, root, remote, mirror, db
):
    broken = {"type": "bearer", "username": "", "secret": "enc:v1:not-sealed-with-this-key"}
    await reconfigure(db, mirror, remote_auth=broken)

    await client.get(URL, headers=root)

    state = await db.scalar(select(ProxyState))
    assert "credential" in state.last_error
    assert (state.failures, state.blocked_until) == (0, None)


async def test_one_broken_path_on_the_remote_does_not_block_the_proxy(client, root, remote):
    remote.status = 500
    await client.get(URL, headers=root)
    remote.status = None

    response = await client.get(URL, headers=root)

    assert response.content == CONTENT


class Typed(Format):
    """A format that decides the content type of what it stores."""

    name = "raw"

    def content_type(self, path, declared):
        return "application/x-chosen"


async def test_the_format_chooses_the_type_recorded_for_a_fetched_file(
    client, root, remote, monkeypatch
):
    monkeypatch.setitem(formats._registry, "raw", Typed())

    response = await client.get(URL, headers=root)

    assert response.headers["Content-Type"] == "application/x-chosen"


async def test_ensure_cached_fetches_a_missing_file_once(app, context_for, mirror, remote):
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    await proxy.ensure_cached(context, "lib/a.bin")
    await proxy.ensure_cached(context, "lib/a.bin")

    assert await context.read("lib/a.bin", limit=1000) == CONTENT
    assert remote.paths() == [REMOTE_PATH]


async def test_ensure_cached_raises_what_the_engine_would_answer(app, context_for, mirror, remote):
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    with pytest.raises(ApiError) as missing:
        await proxy.ensure_cached(context, "lib/absent.bin")
    remote.down = True
    with pytest.raises(ApiError) as unavailable:
        await proxy.ensure_cached(context, "lib/other.bin")

    assert (missing.value.status_code, missing.value.code) == (404, "not_found")
    assert (unavailable.value.status_code, unavailable.value.code) == (
        502,
        "remote_unavailable",
    )


async def test_ensure_cached_keeps_a_stale_copy_when_the_remote_is_down(
    app, context_for, mirror, remote, db
):
    context = await context_for(mirror, None, outbound=lambda: app.state.http)
    await proxy.ensure_cached(context, "lib/a.bin")
    await make_stale(db)
    remote.down = True

    await proxy.ensure_cached(context, "lib/a.bin")

    assert await context.read("lib/a.bin", limit=1000) == CONTENT


async def test_a_context_without_an_outbound_client_cannot_fetch(context_for, mirror):
    context = await context_for(mirror, None)

    with pytest.raises(RuntimeError):
        await proxy.ensure_cached(context, "lib/a.bin")


ELSEWHERE = "http://files.test/store/ab/a.bin"  # what a remote's index says, on another host
DIGESTS = {"sha256": hashlib.sha256(CONTENT).hexdigest(), "md5": hashlib.md5(CONTENT).hexdigest()}


async def asked(remote_seen) -> list[tuple[str, str]]:
    return [(seen["host"], seen["path"]) for seen in remote_seen.requests]


async def test_a_file_is_fetched_from_the_address_given_for_it(
    app, context_for, mirror, fake_remote
):
    fake_remote.files["store/ab/a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)
    source = proxy.Source(ELSEWHERE, DIGESTS)

    await proxy.ensure_cached(context, "lib/a.bin", source=source)
    await proxy.ensure_cached(context, "lib/a.bin", source=source)

    assert await context.read("lib/a.bin", limit=1000) == CONTENT
    assert await asked(fake_remote) == [("files.test", "/store/ab/a.bin")]


async def test_a_file_that_does_not_match_its_hash_is_not_kept(
    app, context_for, mirror, fake_remote, db, settings
):
    fake_remote.files["store/ab/a.bin"] = b"not the file the index describes"
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    for _ in range(6):  # more often than a failing remote is allowed before it is blocked
        with pytest.raises(ApiError) as refused:
            await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE, DIGESTS))

    assert (refused.value.status_code, refused.value.code) == (502, "remote_unavailable")
    assert "hash" in refused.value.message
    assert await count(db, Asset) == 0
    store = settings.data_dir / "blobs" / "default"
    assert not [path for path in store.rglob("*") if path.is_file()]
    state = await db.scalar(select(ProxyState))
    assert "hash" in state.last_error
    assert state.blocked_until is None  # one wrong file does not block the remote


async def test_an_algorithm_that_cannot_be_checked_is_a_mismatch(
    app, context_for, mirror, fake_remote
):
    fake_remote.files["store/ab/a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    with pytest.raises(ApiError) as refused:
        await proxy.ensure_cached(
            context, "lib/a.bin", source=proxy.Source(ELSEWHERE, {"blake2b": "0" * 64})
        )

    assert refused.value.status_code == 502


async def test_the_remotes_credential_stays_with_the_remote(
    admin_client, app, context_for, db, fake_remote
):
    for path in ("files/lib/a.bin", "store/ab/a.bin", "other/b.bin"):
        fake_remote.files[path] = CONTENT
    private = {
        "name": "private",
        "format": "raw",
        "type": "proxy",
        "proxy": {
            "remote_url": "http://remote.test/files",
            "remote_auth": {"type": "basic", "username": "robot", "secret": "s3cret"},
        },
    }
    await admin_client.post(REPOSITORIES, json=private)
    repository = await service.get_repository(db, "private")
    context = await context_for(repository, None, outbound=lambda: app.state.http)

    await proxy.ensure_cached(context, "lib/a.bin")
    await proxy.ensure_cached(context, "one", source=proxy.Source(ELSEWHERE))
    await proxy.ensure_cached(context, "two", source=proxy.Source("http://remote.test/other/b.bin"))
    await proxy.ensure_cached(
        context, "three", source=proxy.Source("http://remote.test:8080/other/b.bin")
    )
    await proxy.ensure_cached(
        context, "four", source=proxy.Source("https://remote.test/other/b.bin")
    )

    sent = [
        (seen["host"], seen["path"], "authorization" in seen["headers"])
        for seen in fake_remote.requests
    ]
    assert sent == [
        ("remote.test", "/files/lib/a.bin", True),
        ("files.test", "/store/ab/a.bin", False),  # another host
        ("remote.test", "/other/b.bin", True),  # the remote's own origin
        ("remote.test", "/other/b.bin", False),  # another port
        ("remote.test", "/other/b.bin", False),  # another scheme
    ]


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1/a.bin",
        "http://localhost:8000/a.bin",
        "http://LOCALHOST/a.bin",
        "http://10.0.0.5/a.bin",
        "http://192.168.1.1/a.bin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/a.bin",
        # The same places, written in other ways.
        "http://2130706433/a.bin",
        "http://0x7f000001/a.bin",
        "http://127.1/a.bin",
        "http://017700000001/a.bin",
        "http://0/a.bin",
        "http://2852039166/latest/meta-data",
        "http://localhost./a.bin",
        "http://127.0.0.1./a.bin",
        "http://anything.localhost/a.bin",
        "http://[::ffff:127.0.0.1]/a.bin",
        "http://100.64.0.1/a.bin",
        "ftp://files.test/a.bin",
        "file:///etc/passwd",
        "//files.test/a.bin",
        "/store/ab/a.bin",
        "",
    ],
)
async def test_an_address_a_remote_must_not_send_us_to_is_refused(
    app, context_for, mirror, fake_remote, db, address
):
    fake_remote.files["a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    with pytest.raises(ApiError) as refused:
        await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(address))

    assert (refused.value.status_code, refused.value.code) == (502, "remote_unavailable")
    assert fake_remote.requests == []
    assert await count(db, Asset) == 0


async def test_a_remote_on_an_internal_network_may_name_its_own_host(
    admin_client, app, context_for, db, fake_remote
):
    fake_remote.files["elsewhere/a.bin"] = CONTENT
    inside = {
        "name": "inside",
        "format": "raw",
        "type": "proxy",
        "proxy": {"remote_url": "http://10.1.2.3/files"},
    }
    await admin_client.post(REPOSITORIES, json=inside)
    repository = await service.get_repository(db, "inside")
    context = await context_for(repository, None, outbound=lambda: app.state.http)

    await proxy.ensure_cached(
        context, "a.bin", source=proxy.Source("http://10.1.2.3/elsewhere/a.bin")
    )
    with pytest.raises(ApiError) as refused:
        await proxy.ensure_cached(context, "b.bin", source=proxy.Source("http://10.9.9.9/b.bin"))

    assert await context.read("a.bin", limit=1000) == CONTENT
    assert refused.value.status_code == 502
    assert await asked(fake_remote) == [("10.1.2.3", "/elsewhere/a.bin")]


async def test_a_stale_file_that_is_not_the_one_described_is_asked_for_whole(
    app, context_for, mirror, fake_remote, db
):
    # What is held is not what the index now describes. Asking the remote "has it
    # changed?" could be answered "no" and leave the wrong file in place.
    fake_remote.files["store/ab/a.bin"] = b"what was there before"
    context = await context_for(mirror, None, outbound=lambda: app.state.http)
    await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE))
    await make_stale(db)

    with pytest.raises(ApiError):
        await proxy.ensure_cached(context, "lib/b.bin", source=proxy.Source(ELSEWHERE, DIGESTS))
    await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE, DIGESTS))
    kept = await context.read("lib/a.bin", limit=1000)
    fake_remote.files["store/ab/a.bin"] = CONTENT
    await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE, DIGESTS))

    conditional = ["if-none-match" in seen["headers"] for seen in fake_remote.requests]
    assert conditional == [False, False, False, False]
    assert kept == b"what was there before"  # the remote had nothing better; it is kept
    assert await context.read("lib/a.bin", limit=1000) == CONTENT


async def test_a_stale_file_that_is_the_one_described_is_only_asked_about(
    app, context_for, mirror, fake_remote, db
):
    fake_remote.files["store/ab/a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)
    await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE, DIGESTS))
    await make_stale(db)

    await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE, DIGESTS))

    assert fake_remote.requests[1]["headers"]["if-none-match"] == etag_of(CONTENT)
