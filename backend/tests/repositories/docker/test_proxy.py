"""A Docker proxy: a pull-through cache of another registry."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from starlette.responses import JSONResponse, Response

from megooarti import secrets_box
from megooarti.clock import utcnow
from megooarti.repositories.content import build_context
from megooarti.repositories.docker.manifests import DOCKER_MANIFEST, OCI_INDEX, OCI_MANIFEST
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Asset, AssetReference, ProxyState
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import create, digest_of, error_code, index_manifest
from tests.repositories.fake_registry import REGISTRY, FakeRegistry
from tests.repositories.fake_registry import basic as remote_basic

HUB = "/v2/hub"
LAYER = b"\x1f\x8b the first layer " * 500
OTHER = b"\x1f\x8b another layer"
TAG = f"{HUB}/team/app/manifests/1.0"


@pytest.fixture
def registry(app) -> FakeRegistry:
    fake = FakeRegistry()
    app.state.http = fake.client()
    return fake


@pytest.fixture
async def hub(db, registry):
    return await create(db, "hub", proxy={"remote_url": REGISTRY})


@pytest.fixture
def manifest(registry) -> bytes:
    """The image `team/app:1.0` at the remote."""
    return registry.add_image("team/app", "1.0", LAYER, OTHER)


async def make_stale(db) -> None:
    long_ago = utcnow() - timedelta(days=3)
    await db.execute(update(Asset).values(last_verified_at=long_ago))
    await db.commit()


def manifest_requests(registry: FakeRegistry) -> list[tuple[str, str]]:
    return [
        (seen["method"], seen["path"].rpartition("/")[2][:12])
        for seen in registry.requests
        if "/manifests/" in seen["path"] and "authorization" in seen["headers"]
    ]


async def test_an_image_is_pulled_through_the_proxy_and_kept(client, hub, root, registry, manifest):
    digest = digest_of(manifest)

    by_tag = await client.get(TAG, headers=root)
    by_digest = await client.get(f"{HUB}/team/app/manifests/{digest}", headers=root)
    layer = await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)
    asked = len(registry.requests)
    again = [
        await client.get(TAG, headers=root),
        await client.head(TAG, headers=root),
        await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root),
    ]

    assert (by_tag.status_code, by_tag.content) == (200, manifest)
    assert by_tag.headers["Content-Type"] == OCI_MANIFEST
    assert by_tag.headers["Docker-Content-Digest"] == digest
    assert by_digest.content == manifest
    assert (layer.content, layer.headers["Docker-Content-Digest"]) == (LAYER, digest_of(LAYER))
    assert layer.headers["Content-Type"] == "application/octet-stream"
    assert [response.status_code for response in again] == [200, 200, 200]
    assert len(registry.requests) == asked  # all of it from what was kept


async def test_what_is_kept_is_laid_out_as_in_a_hosted_repository(
    client, hub, root, registry, manifest, db
):
    digest = digest_of(manifest)
    await client.get(TAG, headers=root)
    await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)

    paths = sorted(await db.scalars(select(Asset.path)))
    referred = sorted(await db.scalars(select(AssetReference.target)))
    catalog = await client.get("/v2/_catalog", headers=root)
    tags = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert paths == sorted(
        [f"blobs/{digest_of(LAYER)}", f"manifests/team/app/{digest}", "tags/team/app/1.0"]
    )
    # What the manifest refers to is recorded before any of it has been fetched.
    assert len(referred) == 3 and f"blobs/{digest_of(OTHER)}" in referred
    assert catalog.json() == {"repositories": ["hub/team/app"]}
    assert tags.json() == {"name": "hub/team/app", "tags": ["1.0"]}


async def test_the_remote_is_asked_for_every_kind_of_manifest(
    client, hub, root, registry, manifest
):
    await client.get(TAG, headers=root)

    accepted = registry.requests[-1]["headers"]["accept"]
    assert all(kind in accepted for kind in (OCI_MANIFEST, OCI_INDEX, DOCKER_MANIFEST))


async def test_one_sign_in_serves_a_whole_pull(client, hub, root, registry, manifest):
    await client.get(TAG, headers=root)
    for layer in (LAYER, OTHER):
        await client.get(f"{HUB}/team/app/blobs/{digest_of(layer)}", headers=root)

    assert registry.asked(host="auth.registry.test") == ["/token"]


async def test_a_tag_is_only_asked_about_until_it_names_something_else(
    client, hub, root, registry, manifest, db
):
    await client.get(TAG, headers=root)
    registry.requests.clear()

    fresh = await client.get(TAG, headers=root)
    nothing_asked = list(registry.requests)
    await make_stale(db)
    unchanged = await client.get(TAG, headers=root)
    only_asked = manifest_requests(registry)
    moved = registry.add_image("team/app", "1.0", LAYER, b"a new layer")
    await make_stale(db)
    registry.requests.clear()
    changed = await client.get(TAG, headers=root)
    old = await client.get(f"{HUB}/team/app/manifests/{digest_of(manifest)}", headers=root)

    assert (fresh.content, nothing_asked) == (manifest, [])
    assert (unchanged.content, only_asked) == (manifest, [("HEAD", "1.0")])
    assert changed.content == moved
    assert manifest_requests(registry) == [("HEAD", "1.0"), ("GET", digest_of(moved)[:12])]
    assert old.content == manifest  # what a deployment pinned is still here


async def test_a_remote_that_does_not_say_what_a_tag_names_is_asked_for_the_manifest(
    client, hub, root, registry, manifest, db
):
    registry.digest_header = False

    first = await client.get(TAG, headers=root)
    by_digest = await client.get(f"{HUB}/team/app/manifests/{digest_of(manifest)}", headers=root)
    await make_stale(db)
    registry.requests.clear()
    again = await client.get(TAG, headers=root)

    assert first.content == by_digest.content == again.content == manifest
    assert manifest_requests(registry) == [("HEAD", "1.0"), ("GET", "1.0")]
    assert (
        await db.scalar(select(Asset).where(Asset.path == "tags/team/app/1.0"))
    ).last_verified_at > (utcnow() - timedelta(minutes=1))


async def test_what_is_kept_is_served_while_the_remote_is_down(
    client, hub, root, registry, manifest, db
):
    await client.get(TAG, headers=root)
    await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)
    await make_stale(db)
    registry.down = True

    kept = await client.get(TAG, headers=root)
    layer = await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)
    never_fetched = await client.get(f"{HUB}/team/app/blobs/{digest_of(OTHER)}", headers=root)
    other_tag = await client.get(f"{HUB}/team/app/manifests/2.0", headers=root)

    assert (kept.content, layer.content) == (manifest, LAYER)
    for response in (never_fetched, other_tag):
        assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert (await db.scalar(select(ProxyState.failures))) >= 1


async def test_a_tag_the_remote_dropped_is_kept(client, hub, root, registry, manifest, db):
    await client.get(TAG, headers=root)
    del registry.manifests[("team/app", "1.0")]
    await make_stale(db)

    response = await client.get(TAG, headers=root)

    assert response.content == manifest


async def test_what_the_remote_does_not_have_is_unknown(client, hub, root, registry, manifest):
    absent = "sha256:" + "0" * 64

    tag = await client.get(f"{HUB}/team/app/manifests/2.0", headers=root)
    by_digest = await client.get(f"{HUB}/team/app/manifests/{absent}", headers=root)
    blob = await client.get(f"{HUB}/team/app/blobs/{absent}", headers=root)
    asked = await client.head(f"{HUB}/team/app/blobs/{absent}", headers=root)
    tags = await client.get(f"{HUB}/team/nothing/tags/list", headers=root)

    assert (tag.status_code, error_code(tag)) == (404, "MANIFEST_UNKNOWN")
    assert (by_digest.status_code, error_code(by_digest)) == (404, "MANIFEST_UNKNOWN")
    assert (blob.status_code, error_code(blob)) == (404, "BLOB_UNKNOWN")
    assert asked.status_code == 404
    assert (tags.status_code, error_code(tags)) == (404, "NAME_UNKNOWN")


async def test_an_image_the_remote_will_not_show_is_unknown_not_an_outage(
    client, hub, root, registry, manifest, db
):
    registry.private.add("team/app")

    response = await client.get(TAG, headers=root)
    tags = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert (response.status_code, error_code(response)) == (404, "MANIFEST_UNKNOWN")
    assert "does not let this proxy read it" in response.json()["errors"][0]["message"]
    assert (tags.status_code, error_code(tags)) == (404, "NAME_UNKNOWN")
    assert await db.scalar(select(ProxyState.blocked_until)) is None


async def test_a_private_image_is_pulled_with_the_proxys_credential(
    client, db, root, registry, manifest, settings
):
    registry.accounts["ci"] = "secret"
    registry.private.add("team/app")
    registry.blobs_at = "https://cdn.registry.test"
    auth = {"type": "basic", "username": "ci", "secret": secrets_box.seal(settings, "secret")}
    await create(db, "private", proxy={"remote_url": REGISTRY, "remote_auth": auth})

    pulled = await client.get("/v2/private/team/app/manifests/1.0", headers=root)
    layer = await client.get(f"/v2/private/team/app/blobs/{digest_of(LAYER)}", headers=root)

    assert (pulled.content, layer.content) == (manifest, LAYER)
    credential = remote_basic("ci", "secret")
    shown_to = {
        seen["host"]
        for seen in registry.requests
        if seen["headers"].get("authorization") == credential
    }
    assert shown_to == {"registry.test", "auth.registry.test"}  # never where the blobs are kept
    assert "secret" not in pulled.text + layer.headers.get("WWW-Authenticate", "")


@pytest.mark.parametrize(
    ("remote", "image", "asked"),
    [
        ("https://registry-1.docker.io", "alpine", "/v2/library/alpine/manifests/3"),
        ("https://registry-1.docker.io/", "team/app", "/v2/team/app/manifests/3"),
        ("https://ghcr.io", "alpine", "/v2/alpine/manifests/3"),
        ("https://registry.test/mirror", "team/app", "/mirror/v2/team/app/manifests/3"),
    ],
)
async def test_where_an_image_is_at_the_remote(client, db, root, registry, remote, image, asked):
    registry.wants_token = False
    await create(db, "public", proxy={"remote_url": remote})

    await client.get(f"/v2/public/{image}/manifests/3", headers=root)

    assert [seen["path"] for seen in registry.requests] == [asked]


async def test_content_that_is_not_what_its_digest_says_is_not_kept(
    client, hub, root, registry, manifest, db
):
    digest, layer = digest_of(manifest), digest_of(LAYER)
    registry.manifests[("team/app", digest)] = (manifest + b" ", OCI_MANIFEST)  # a manifest still
    registry.blobs[("team/app", layer)] = b"not that layer"

    by_digest = await client.get(f"{HUB}/team/app/manifests/{digest}", headers=root)
    blob = await client.get(f"{HUB}/team/app/blobs/{layer}", headers=root)

    for response in (by_digest, blob):
        assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert "not the one asked for" in by_digest.json()["errors"][0]["message"]
    assert list(await db.scalars(select(Asset.path))) == []


@pytest.mark.parametrize(
    "sent",
    [
        b"<html>not a manifest</html>",
        json.dumps({"schemaVersion": 1, "name": "team/app", "fsLayers": []}).encode(),
        json.dumps({"schemaVersion": 2, "mediaType": "text/html", "layers": []}).encode(),
        b"[" * 100_000,
    ],
    ids=["html", "schema 1", "another type", "deeply nested"],
)
async def test_what_is_not_a_manifest_is_not_kept(client, hub, root, registry, db, sent):
    registry.add_manifest("team/app", "1.0", sent, "application/json")

    response = await client.get(TAG, headers=root)

    assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert "cannot be used" in response.json()["errors"][0]["message"]
    assert list(await db.scalars(select(Asset.path))) == []


async def test_blobs_come_from_where_the_remote_keeps_them(client, hub, root, registry, manifest):
    registry.blobs_at = "https://cdn.registry.test"

    layer = await client.get(f"{HUB}/team/app/blobs/{digest_of(LAYER)}", headers=root)

    assert layer.content == LAYER
    (from_cdn,) = [seen for seen in registry.requests if seen["host"] == "cdn.registry.test"]
    assert "authorization" not in from_cdn["headers"]


async def test_asking_about_a_layer_does_not_fetch_it(client, hub, root, registry, manifest, db):
    address = f"{HUB}/team/app/blobs/{digest_of(LAYER)}"

    asked = await client.head(address, headers=root)

    assert asked.status_code == 200
    assert asked.headers["Content-Length"] == str(len(LAYER))
    assert asked.headers["Docker-Content-Digest"] == digest_of(LAYER)
    assert "GET" not in {seen["method"] for seen in registry.requests if "/blobs/" in seen["path"]}
    assert list(await db.scalars(select(Asset.path))) == []


async def test_a_layer_asked_for_under_the_wrong_image_does_not_hide_it_from_the_right_one(
    client, hub, root, registry, manifest
):
    layer = digest_of(LAYER)

    wrong = await client.get(f"{HUB}/team/unrelated/blobs/{layer}", headers=root)
    right = await client.get(f"{HUB}/team/app/blobs/{layer}", headers=root)
    shared = await client.get(f"{HUB}/team/unrelated/blobs/{layer}", headers=root)

    assert (wrong.status_code, error_code(wrong)) == (404, "BLOB_UNKNOWN")
    assert right.content == LAYER
    assert shared.content == LAYER  # once kept, a layer is the repository's


async def test_an_image_for_several_platforms_is_fetched_piece_by_piece(
    client, hub, root, registry, db
):
    platforms = [registry.add_image("team/multi", f"only-{arch}", arch.encode()) for arch in "ab"]
    del registry.manifests[("team/multi", "only-a")], registry.manifests[("team/multi", "only-b")]
    index = index_manifest(*platforms)
    registry.add_manifest("team/multi", "1.0", index, OCI_INDEX)

    pulled = await client.get(f"{HUB}/team/multi/manifests/1.0", headers=root)
    before = sorted(await db.scalars(select(Asset.path)))
    one = await client.get(f"{HUB}/team/multi/manifests/{digest_of(platforms[0])}", headers=root)

    assert (pulled.content, pulled.headers["Content-Type"]) == (index, OCI_INDEX)
    assert before == sorted([f"manifests/team/multi/{digest_of(index)}", "tags/team/multi/1.0"])
    assert one.content == platforms[0]
    referred = set(await db.scalars(select(AssetReference.target)))
    assert {f"manifests/team/multi/{digest_of(platform)}" for platform in platforms} <= referred


async def test_the_tags_of_an_image_are_the_remotes_read_page_by_page(
    client, hub, root, registry, db
):
    for number in range(7):
        registry.add_image("team/app", f"1.{number}", LAYER)
    registry.page_size = 3

    listed = await client.get(f"{HUB}/team/app/tags/list", headers=root)
    asked = [seen["query"] for seen in registry.requests if seen["path"].endswith("/tags/list")]
    page = await client.get(f"{HUB}/team/app/tags/list?n=2&last=1.1", headers=root)
    requests = len(registry.requests)
    await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert listed.json() == {"name": "hub/team/app", "tags": [f"1.{n}" for n in range(7)]}
    assert {query.get("last") for query in asked} == {None, "1.2", "1.5"}  # three pages
    assert page.json()["tags"] == ["1.2", "1.3"]
    assert page.headers["Link"] == f'<{HUB}/team/app/tags/list?n=2&last=1.3>; rel="next"'
    assert len(registry.requests) == requests  # the list is kept for a while, like a tag


async def test_a_list_of_tags_is_renewed_when_it_is_old_and_kept_if_it_cannot_be(
    client, hub, root, registry, manifest, db
):
    await client.get(f"{HUB}/team/app/tags/list", headers=root)
    registry.add_image("team/app", "2.0", LAYER)

    still = await client.get(f"{HUB}/team/app/tags/list", headers=root)
    await make_stale(db)
    renewed = await client.get(f"{HUB}/team/app/tags/list", headers=root)
    await make_stale(db)
    registry.down = True
    kept = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert still.json()["tags"] == ["1.0"]
    assert renewed.json()["tags"] == kept.json()["tags"] == ["1.0", "2.0"]


@pytest.mark.parametrize("sent", [b"not json", b'{"tags": "1.0"}', b'["1.0"]'])
async def test_a_list_of_tags_that_cannot_be_read_is_not_kept(
    client, hub, root, registry, db, monkeypatch, sent
):
    monkeypatch.setattr(registry, "_tags", lambda request, image: Response(sent))

    response = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert list(await db.scalars(select(Asset.path))) == []


async def test_a_list_of_tags_does_not_lead_the_proxy_to_an_internal_address(
    client, hub, root, registry, monkeypatch
):
    link = {"Link": '<https://169.254.169.254/latest/meta-data>; rel="next"'}
    page = JSONResponse({"tags": ["1.0"]}, headers=link)
    monkeypatch.setattr(registry, "_tags", lambda request, image: page)

    response = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert (response.status_code, error_code(response)) == (502, "UNKNOWN")
    assert {seen["host"] for seen in registry.requests} == {"registry.test", "auth.registry.test"}


async def test_only_tags_that_can_be_tags_are_listed(client, hub, root, registry, monkeypatch):
    sent = {"tags": ["1.0", "", "../../etc", 7, None, "ok_tag", "x" * 200, "1.0"]}
    monkeypatch.setattr(registry, "_tags", lambda request, image: JSONResponse(sent))

    response = await client.get(f"{HUB}/team/app/tags/list", headers=root)

    assert response.json()["tags"] == ["1.0", "ok_tag"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "team/app/blobs/uploads/"),
        ("PUT", "team/app/manifests/1.0"),
        ("DELETE", "team/app/manifests/1.0"),
        ("PATCH", "team/app/blobs/uploads/" + "0" * 32),
        ("DELETE", "team/app/blobs/sha256:" + "0" * 64),
    ],
)
async def test_nothing_is_pushed_to_a_proxy_or_deleted_from_it(
    client, hub, root, registry, method, path
):
    response = await client.request(method, f"{HUB}/{path}", content=b"{}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
    assert response.headers["Allow"] == "GET, HEAD"
    assert registry.requests == []


async def test_pulling_through_a_proxy_needs_read_on_it(
    client, hub, root, registry, manifest, make_user, db
):
    await roles.create_role(db, "pullers", "", ["repository:docker:hub:read"], [])
    await roles.create_role(db, "others", "", ["repository:docker:elsewhere"], [])
    await db.commit()
    await make_user("puller", roles=["pullers"])
    await make_user("other", roles=["others"])

    allowed = await client.get(TAG, headers=basic("puller", PASSWORD))
    denied = await client.get(TAG, headers=basic("other", PASSWORD))
    nobody = await client.get(TAG)

    assert allowed.content == manifest
    assert (denied.status_code, error_code(denied)) == (403, "DENIED")
    assert nobody.status_code == 401
    assert "repository:hub/team/app:pull" in nobody.headers["WWW-Authenticate"]


async def test_maintenance_removes_layers_no_kept_manifest_refers_to(
    client, hub, root, registry, manifest, db, settings
):
    stray = registry.add_blob("team/app", b"fetched by its digest alone")
    await client.get(TAG, headers=root)
    for digest in (digest_of(LAYER), stray):
        await client.get(f"{HUB}/team/app/blobs/{digest}", headers=root)
    await db.execute(update(Asset).values(updated_at=utcnow() - timedelta(days=2)))
    await db.commit()

    context = await build_context(db, settings, hub, None)
    await get_format("docker").maintain(context, utcnow())
    await db.commit()

    held = set(await db.scalars(select(Asset.path)))
    assert f"blobs/{digest_of(LAYER)}" in held
    assert f"blobs/{stray}" not in held
