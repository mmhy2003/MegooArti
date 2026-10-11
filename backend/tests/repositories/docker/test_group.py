"""A Docker group: hosted and proxy repositories behind one address."""

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.docker.manifests import OCI_INDEX
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import (
    config_for,
    create,
    digest_of,
    error_code,
    image_manifest,
    index_manifest,
    layer,
    push_image,
)
from tests.repositories.fake_registry import REGISTRY, FakeRegistry

ALL = "/v2/all"
PUBLIC_LAYER = b"\x1f\x8b a layer of the public image"


@pytest.fixture
def registry(app) -> FakeRegistry:
    fake = FakeRegistry()
    app.state.http = fake.client()
    return fake


@pytest.fixture
async def everything(db, registry):
    """A hosted repository and a proxy behind a group, with the proxy listed first."""
    await create(db, "ours")
    await create(db, "hub", proxy={"remote_url": REGISTRY})
    return await create(db, "all", group=["hub", "ours"])


async def take_offline(db, name: str) -> None:
    repository = await service.get_repository(db, name)
    repository.online = False
    await db.commit()


def ours(*texts: str) -> bytes:
    """The manifest `push_image` makes of these layers."""
    return image_manifest(config_for(*texts), *(layer(text) for text in texts))


async def test_an_image_only_the_remote_has_is_pulled_through_the_group(
    client, everything, root, registry, db
):
    manifest = registry.add_image("library/tool", "1.0", PUBLIC_LAYER)

    by_tag = await client.get(f"{ALL}/library/tool/manifests/1.0", headers=root)
    asked = await client.head(f"{ALL}/library/tool/manifests/1.0", headers=root)
    by_digest = await client.get(
        f"{ALL}/library/tool/manifests/{digest_of(manifest)}", headers=root
    )
    blob = await client.get(f"{ALL}/library/tool/blobs/{digest_of(PUBLIC_LAYER)}", headers=root)

    assert by_tag.content == by_digest.content == manifest
    assert asked.headers["Docker-Content-Digest"] == digest_of(manifest)
    assert blob.content == PUBLIC_LAYER
    # It is kept by the proxy, not by the group: a group stores nothing.
    assert f"blobs/{digest_of(PUBLIC_LAYER)}" in set(await db.scalars(select(Asset.path)))


async def test_an_image_that_was_pushed_is_pulled_through_the_group(
    client, everything, root, registry
):
    manifest = await push_image(client, root, "team/app", "1.0", "one", repository="ours")

    by_tag = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    blob = await client.get(f"{ALL}/team/app/blobs/{digest_of(layer('one'))}", headers=root)
    asked = await client.head(f"{ALL}/team/app/blobs/{digest_of(layer('one'))}", headers=root)

    assert by_tag.content == manifest
    assert blob.content == layer("one")
    assert asked.headers["Content-Length"] == str(len(layer("one")))
    assert registry.requests == []  # the remote was not asked about our image


async def test_a_public_image_cannot_stand_in_for_one_that_was_pushed(
    client, everything, root, registry
):
    pushed = await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    theirs = registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    registry.add_image("team/app", "2.0", PUBLIC_LAYER)

    same_tag = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    their_tag = await client.get(f"{ALL}/team/app/manifests/2.0", headers=root)
    their_manifest = await client.get(f"{ALL}/team/app/manifests/{digest_of(theirs)}", headers=root)
    their_blob = await client.get(f"{ALL}/team/app/blobs/{digest_of(PUBLIC_LAYER)}", headers=root)
    tags = await client.get(f"{ALL}/team/app/tags/list", headers=root)

    assert same_tag.content == pushed  # though the proxy is listed first
    assert (their_tag.status_code, error_code(their_tag)) == (404, "MANIFEST_UNKNOWN")
    assert (their_manifest.status_code, error_code(their_manifest)) == (404, "MANIFEST_UNKNOWN")
    assert (their_blob.status_code, error_code(their_blob)) == (404, "BLOB_UNKNOWN")
    assert tags.json() == {"name": "all/team/app", "tags": ["1.0"]}  # no tag is added to it
    assert registry.requests == []  # the remote is not even asked


async def test_while_the_repository_that_has_an_image_is_offline_nothing_answers_for_it(
    client, everything, root, registry, db
):
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    registry.add_image("library/tool", "1.0", PUBLIC_LAYER)
    await take_offline(db, "ours")

    attempts = [
        await client.get(f"{ALL}/team/app/manifests/1.0", headers=root),
        await client.get(f"{ALL}/team/app/manifests/{digest_of(ours('ours'))}", headers=root),
        await client.get(f"{ALL}/team/app/blobs/{digest_of(layer('ours'))}", headers=root),
        await client.get(f"{ALL}/team/app/tags/list", headers=root),
    ]
    other = await client.get(f"{ALL}/library/tool/manifests/1.0", headers=root)

    for response in attempts:
        assert response.status_code == 503, response.text
    assert other.status_code == 200  # what it does not have is still served
    assert all("team/app" not in seen["path"] for seen in registry.requests)


async def test_an_image_two_hosted_repositories_have_is_served_by_the_one_that_is_online(
    client, db, root, registry
):
    await create(db, "first")
    await create(db, "second")
    await create(db, "all", group=["first", "second"])
    await push_image(client, root, "team/app", "1.0", "from first", repository="first")
    second = await push_image(client, root, "team/app", "1.0", "from second", repository="second")
    await push_image(client, root, "team/app", "2.0", "newer", repository="second")
    tags = await client.get(f"{ALL}/team/app/tags/list", headers=root)
    await take_offline(db, "first")

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert tags.json()["tags"] == ["1.0", "2.0"]  # of both, each once
    assert response.content == second


async def test_an_image_that_lost_its_tag_is_still_pulled_by_its_digest(
    client, everything, root, registry
):
    manifest = await push_image(client, root, "team/old", "1.0", "kept", repository="ours")
    deleted = await client.delete("/v2/ours/team/old/manifests/1.0", headers=root)

    pinned = await client.get(f"{ALL}/team/old/manifests/{digest_of(manifest)}", headers=root)
    blob = await client.get(f"{ALL}/team/old/blobs/{digest_of(layer('kept'))}", headers=root)

    assert deleted.status_code == 202
    assert (pinned.content, blob.content) == (manifest, layer("kept"))
    assert registry.requests == []


async def test_an_image_for_several_platforms_is_pulled_through_the_group(
    client, everything, root, registry
):
    platforms = [registry.add_image("library/multi", f"p{n}", bytes([n]) * 50) for n in range(2)]
    index = index_manifest(*platforms)
    registry.add_manifest("library/multi", "1.0", index, OCI_INDEX)

    pulled = await client.get(f"{ALL}/library/multi/manifests/1.0", headers=root)
    one = await client.get(f"{ALL}/library/multi/manifests/{digest_of(platforms[1])}", headers=root)

    assert (pulled.content, pulled.headers["Content-Type"]) == (index, OCI_INDEX)
    assert one.content == platforms[1]


async def test_the_tags_of_a_public_image_are_those_of_every_proxy(client, db, root, registry):
    await create(db, "one", proxy={"remote_url": REGISTRY})
    await create(db, "two", proxy={"remote_url": "https://other.registry.test"})
    await create(db, "all", group=["one", "two"])
    for tag in ("1.0", "1.1", "2.0"):
        registry.add_image("library/tool", tag, PUBLIC_LAYER)

    listed = await client.get(f"{ALL}/library/tool/tags/list", headers=root)
    page = await client.get(f"{ALL}/library/tool/tags/list?n=2", headers=root)
    nothing = await client.get(f"{ALL}/library/none/tags/list", headers=root)

    assert listed.json() == {"name": "all/library/tool", "tags": ["1.0", "1.1", "2.0"]}
    assert page.json()["tags"] == ["1.0", "1.1"]
    assert page.headers["Link"] == f'<{ALL}/library/tool/tags/list?n=2&last=1.1>; rel="next"'
    assert (nothing.status_code, error_code(nothing)) == (404, "NAME_UNKNOWN")


async def test_the_catalog_lists_what_the_repositories_behind_a_group_hold(
    client, everything, root, registry, make_user, db
):
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("library/tool", "1.0", PUBLIC_LAYER)
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    await client.get("/v2/hub/library/tool/manifests/1.0", headers=root)
    await client.get("/v2/hub/team/app/manifests/1.0", headers=root)  # directly, not by the group
    await roles.create_role(db, "pullers", "", ["repository:docker:all:read"], [])
    await db.commit()
    await make_user("puller", roles=["pullers"])

    catalog = await client.get("/v2/_catalog", headers=basic("puller", PASSWORD))

    assert catalog.json() == {"repositories": ["all/library/tool", "all/team/app"]}


async def test_reading_through_a_group_needs_read_on_the_group_only(
    client, everything, root, registry, make_user, db
):
    manifest = await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    await roles.create_role(db, "pullers", "", ["repository:docker:all:read"], [])
    await roles.create_role(db, "others", "", ["repository:docker:ours:read"], [])
    await db.commit()
    await make_user("puller", roles=["pullers"])
    await make_user("other", roles=["others"])

    allowed = await client.get(f"{ALL}/team/app/manifests/1.0", headers=basic("puller", PASSWORD))
    directly = await client.get(
        "/v2/ours/team/app/manifests/1.0", headers=basic("puller", PASSWORD)
    )
    denied = await client.get(f"{ALL}/team/app/manifests/1.0", headers=basic("other", PASSWORD))

    assert allowed.content == manifest
    assert (directly.status_code, error_code(directly)) == (403, "DENIED")
    assert (denied.status_code, error_code(denied)) == (403, "DENIED")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "team/app/blobs/uploads/"),
        ("PUT", "team/app/manifests/1.0"),
        ("DELETE", "team/app/manifests/1.0"),
        ("PATCH", "team/app/blobs/uploads/" + "0" * 32),
    ],
)
async def test_nothing_is_pushed_to_a_group_or_deleted_from_it(
    client, everything, root, registry, method, path
):
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")

    response = await client.request(method, f"{ALL}/{path}", content=b"{}", headers=root)
    still = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
    assert response.headers["Allow"] == "GET, HEAD"
    assert still.status_code == 200


async def test_a_remote_that_is_down_is_an_outage_not_a_missing_image(client, db, root, registry):
    await create(db, "one", proxy={"remote_url": REGISTRY})
    await create(db, "all", group=["one"])
    manifest = registry.add_image("library/tool", "1.0", PUBLIC_LAYER)
    await client.get(f"{ALL}/library/tool/manifests/1.0", headers=root)
    registry.down = True

    kept = await client.get(f"{ALL}/library/tool/manifests/{digest_of(manifest)}", headers=root)
    never = await client.get(f"{ALL}/library/other/manifests/1.0", headers=root)
    blob = await client.get(f"{ALL}/library/tool/blobs/{digest_of(PUBLIC_LAYER)}", headers=root)
    tags = await client.get(f"{ALL}/library/other/tags/list", headers=root)

    assert kept.content == manifest
    for response in (never, blob, tags):
        assert (response.status_code, error_code(response)) == (502, "UNKNOWN")


async def test_what_no_repository_has_is_unknown(client, everything, root, registry):
    absent = "sha256:" + "0" * 64

    tag = await client.get(f"{ALL}/library/none/manifests/1.0", headers=root)
    blob = await client.get(f"{ALL}/library/none/blobs/{absent}", headers=root)
    referrers = await client.get(f"{ALL}/library/none/referrers/{absent}", headers=root)
    nonsense = await client.get(f"{ALL}/library/none/something", headers=root)

    assert (tag.status_code, error_code(tag)) == (404, "MANIFEST_UNKNOWN")
    assert (blob.status_code, error_code(blob)) == (404, "BLOB_UNKNOWN")
    assert referrers.status_code == nonsense.status_code == 404


async def test_groups_within_groups_are_looked_through(client, db, root, registry):
    await create(db, "ours")
    await create(db, "hub", proxy={"remote_url": REGISTRY})
    await create(db, "inner", group=["ours"])
    await create(db, "all", group=["hub", "inner", "ours"])
    pushed = await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    await take_offline(db, "inner")
    still = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert response.content == still.content == pushed  # it is also reached directly
    assert registry.requests == []


async def test_a_hosted_repository_behind_an_offline_group_still_keeps_its_names(
    client, db, root, registry
):
    await create(db, "ours")
    await create(db, "hub", proxy={"remote_url": REGISTRY})
    await create(db, "inner", group=["ours"])
    await create(db, "all", group=["hub", "inner"])
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    await take_offline(db, "inner")

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert response.status_code == 503
    assert registry.requests == []


async def test_a_group_with_nothing_behind_it_has_nothing(client, db, root, registry):
    await create(db, "all", group=[])

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    catalog = await client.get("/v2/_catalog", headers=root)

    assert (response.status_code, error_code(response)) == (404, "MANIFEST_UNKNOWN")
    assert catalog.json() == {"repositories": []}
