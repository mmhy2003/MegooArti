import json
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from megooarti.clock import utcnow
from megooarti.repositories import upkeep
from megooarti.repositories.docker.manifests import (
    DOCKER_LIST,
    DOCKER_MANIFEST,
    OCI_INDEX,
    OCI_MANIFEST,
)
from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import (
    V2,
    config_for,
    create,
    digest_of,
    error_code,
    image_manifest,
    index_manifest,
    layer,
    push_blob,
    push_image,
    push_manifest,
)

CONFIG = b'{"architecture": "amd64", "os": "linux"}'


async def stored(db) -> list[str]:
    return list(await db.scalars(select(Asset.path).order_by(Asset.path)))


async def blobs_stored(db) -> int:
    return len([path for path in await stored(db) if path.startswith("blobs/")])


async def test_an_image_is_pushed_and_pulled_by_tag_and_by_digest(client, images, root, db):
    manifest = await push_image(client, root, "team/app", "1.0", "base", "code")
    digest = digest_of(manifest)

    by_tag = await client.get(f"{V2}/team/app/manifests/1.0", headers=root)
    by_digest = await client.get(f"{V2}/team/app/manifests/{digest}", headers=root)
    headed = await client.head(f"{V2}/team/app/manifests/1.0", headers=root)

    for response in (by_tag, by_digest):
        assert (response.status_code, response.content) == (200, manifest)
        assert response.headers["Content-Type"] == OCI_MANIFEST
        assert response.headers["Docker-Content-Digest"] == digest
    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Docker-Content-Digest"] == digest
    assert headed.headers["Content-Length"] == str(len(manifest))
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "team/app", "1.0")
    assert f"manifests/team/app/{digest}" in await stored(db)
    assert "tags/team/app/1.0" in await stored(db)


async def test_pushing_a_manifest_answers_where_it_is(client, images, root):
    for data in (CONFIG, layer("one")):
        await push_blob(client, root, "app", data)
    manifest = image_manifest(CONFIG, layer("one"))

    response = await push_manifest(client, root, "app", "latest", manifest)

    assert (response.status_code, response.content) == (201, b"")
    assert response.headers["Location"] == f"{V2}/app/manifests/{digest_of(manifest)}"
    assert response.headers["Docker-Content-Digest"] == digest_of(manifest)


@pytest.mark.parametrize("media_type", [OCI_MANIFEST, DOCKER_MANIFEST])
async def test_both_kinds_of_image_manifest_are_served_as_they_were_pushed(
    client, images, root, media_type
):
    for data in (CONFIG, layer("one")):
        await push_blob(client, root, "app", data)
    manifest = image_manifest(CONFIG, layer("one"), media_type=media_type)

    await push_manifest(client, root, "app", "latest", manifest)
    pulled = await client.get(f"{V2}/app/manifests/latest", headers=root)

    assert (pulled.content, pulled.headers["Content-Type"]) == (manifest, media_type)


@pytest.mark.parametrize("media_type", [OCI_INDEX, DOCKER_LIST])
async def test_an_image_for_several_platforms_is_one_image(client, images, root, media_type):
    amd64 = await push_image(client, root, "app", "amd64-only", "amd64 code")
    arm64 = await push_image(client, root, "app", "arm64-only", "arm64 code")
    index = index_manifest(amd64, arm64, media_type=media_type)

    pushed = await push_manifest(client, root, "app", "1.0", index)
    pulled = await client.get(f"{V2}/app/manifests/1.0", headers=root)
    platform = await client.get(f"{V2}/app/manifests/{digest_of(arm64)}", headers=root)

    assert pushed.status_code == 201
    assert (pulled.content, pulled.headers["Content-Type"]) == (index, media_type)
    assert platform.content == arm64


async def test_a_manifest_must_refer_to_what_has_been_pushed(client, images, root, db):
    await push_blob(client, root, "app", CONFIG)
    missing_layer = image_manifest(CONFIG, layer("never pushed"))
    platform = await push_image(client, root, "other", "latest", "one")
    missing_platform = index_manifest(platform)  # pushed, but under another image

    for manifest, missing in ((missing_layer, layer("never pushed")), (missing_platform, platform)):
        response = await push_manifest(client, root, "app", "latest", manifest)
        assert (response.status_code, error_code(response)) == (400, "MANIFEST_BLOB_UNKNOWN")
        assert response.json()["errors"][0]["detail"] == [digest_of(missing)]
    assert not [path for path in await stored(db) if path.startswith(("manifests/app", "tags/app"))]


async def test_a_layer_kept_elsewhere_need_not_be_pushed(client, images, root):
    await push_blob(client, root, "app", CONFIG)
    document = json.loads(image_manifest(CONFIG, layer("foreign")))
    document["layers"][0]["urls"] = ["https://elsewhere.example/layer"]

    response = await push_manifest(client, root, "app", "latest", json.dumps(document).encode())

    assert response.status_code == 201


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"not json", OCI_MANIFEST),
        (b"{}", OCI_MANIFEST),
        (b'{"schemaVersion": 1}', "application/vnd.docker.distribution.manifest.v1+prettyjws"),
        (image_manifest(CONFIG), DOCKER_MANIFEST),  # says OCI inside
        (b" " * (4 * 1024 * 1024 + 1), OCI_MANIFEST),
    ],
    ids=["not-json", "empty", "schema-1", "two-types", "too-large"],
)
async def test_what_is_not_a_manifest_is_refused(client, images, root, db, body, content_type):
    response = await client.put(
        f"{V2}/app/manifests/latest", content=body, headers={**root, "Content-Type": content_type}
    )

    assert (response.status_code, error_code(response)) == (400, "MANIFEST_INVALID")
    assert await stored(db) == []


async def test_a_manifest_pushed_by_digest_must_be_that_manifest(client, images, root):
    for data in (CONFIG, layer("one")):
        await push_blob(client, root, "app", data)
    manifest = image_manifest(CONFIG, layer("one"))

    wrong = await push_manifest(client, root, "app", "sha256:" + "0" * 64, manifest)
    right = await push_manifest(client, root, "app", digest_of(manifest), manifest)
    untagged = await client.get(f"{V2}/app/tags/list", headers=root)

    assert (wrong.status_code, error_code(wrong)) == (400, "DIGEST_INVALID")
    assert right.status_code == 201
    assert (untagged.status_code, error_code(untagged)) == (404, "NAME_UNKNOWN")  # no tag yet


async def test_a_tag_moves_unless_the_repository_says_tags_stay(client, db, root):
    await create(db, "images")
    await create(db, "releases", hosted={"deployment_policy": "disable_redeploy"})
    for repository in ("images", "releases"):
        first = await push_image(client, root, "app", "1.0", "first", repository=repository)

    second = await push_image(client, root, "app", "1.0", "second")
    moved = await client.get(f"{V2}/app/manifests/1.0", headers=root)
    old = await client.get(f"{V2}/app/manifests/{digest_of(first)}", headers=root)
    for data in (config_for("second"), layer("second")):
        await push_blob(client, root, "app", data, "releases")
    refused = await push_manifest(client, root, "app", "1.0", second, "releases")
    again = await push_manifest(client, root, "app", "1.0", first, "releases")
    other_tag = await push_manifest(client, root, "app", "1.1", second, "releases")

    assert moved.content == second
    assert old.content == first  # what the tag named before can still be pulled by digest
    assert (refused.status_code, error_code(refused)) == (409, "DENIED")
    assert again.status_code == 201  # the same image under the same tag changes nothing
    assert other_tag.status_code == 201


async def test_each_change_needs_its_own_permission(client, images, root, make_user, db):
    for action in ("add", "edit", "delete"):
        permissions = [f"repository:docker:images:{action}", "repository:docker:images:read"]
        await roles.create_role(db, f"may-{action}", "", permissions, [])
    await db.commit()
    for action in ("add", "edit", "delete"):
        await make_user(f"{action}er", roles=[f"may-{action}"])
    adder, editor, deleter = (
        basic(f"{action}er", PASSWORD) for action in ("add", "edit", "delete")
    )
    first = await push_image(client, adder, "app", "1.0", "first")
    second = await push_image(client, adder, "app", "2.0", "second")

    add_again = await push_manifest(client, adder, "app", "1.0", first)
    add_moves = await push_manifest(client, adder, "app", "1.0", second)
    edit_moves = await push_manifest(client, editor, "app", "1.0", second)
    edit_new = await push_manifest(client, editor, "app", "3.0", second)
    edit_deletes = await client.delete(f"{V2}/app/manifests/2.0", headers=editor)
    delete_pushes = await client.post(f"{V2}/app/blobs/uploads/", headers=deleter)
    delete_deletes = await client.delete(f"{V2}/app/manifests/2.0", headers=deleter)

    assert (add_again.status_code, edit_moves.status_code, delete_deletes.status_code) == (
        201,
        201,
        202,
    )
    for response in (add_moves, edit_new, edit_deletes, delete_pushes):
        assert (response.status_code, error_code(response)) == (403, "DENIED")


async def test_the_tags_of_an_image_are_listed_in_order_a_page_at_a_time(client, images, root):
    for tag in ("1.10", "1.2", "latest", "1.9"):
        await push_image(client, root, "team/app", tag, "one")

    everything = await client.get(f"{V2}/team/app/tags/list", headers=root)
    first = await client.get(f"{V2}/team/app/tags/list", params={"n": 2}, headers=root)
    rest = await client.get(first.headers["Link"].split(">")[0].lstrip("<"), headers=root)
    unknown = await client.get(f"{V2}/no/such/image/tags/list", headers=root)

    assert everything.json() == {
        "name": "images/team/app",
        "tags": ["1.10", "1.2", "1.9", "latest"],
    }
    assert "Link" not in everything.headers
    assert first.json()["tags"] == ["1.10", "1.2"]
    assert first.headers["Link"] == (f'<{V2}/team/app/tags/list?n=2&last=1.2>; rel="next"')
    assert (rest.json()["tags"], "Link" in rest.headers) == (["1.9", "latest"], False)
    assert (unknown.status_code, error_code(unknown)) == (404, "NAME_UNKNOWN")


async def test_the_catalog_lists_the_images_a_caller_may_read(client, db, root, make_user):
    await create(db, "images")
    await create(db, "private")
    await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "base", "1.0", "one")
    await push_image(client, root, "secret", "1.0", "one", repository="private")
    await push_blob(client, root, "never/tagged", layer("only a layer"))
    await roles.create_role(db, "readers", "", ["repository:docker:images:read"], [])
    await db.commit()
    await make_user("reader", roles=["readers"])

    everything = await client.get("/v2/_catalog", headers=root)
    limited = await client.get("/v2/_catalog", headers=basic("reader", PASSWORD))
    first = await client.get("/v2/_catalog", params={"n": 2}, headers=root)
    rest = await client.get(first.headers["Link"].split(">")[0].lstrip("<"), headers=root)
    without = await client.get("/v2/_catalog")

    assert everything.json() == {
        "repositories": ["images/base", "images/team/app", "private/secret"]
    }
    assert limited.json() == {"repositories": ["images/base", "images/team/app"]}
    assert first.json() == {"repositories": ["images/base", "images/team/app"]}
    assert first.headers["Link"] == '</v2/_catalog?n=2&last=images/team/app>; rel="next"'
    assert rest.json() == {"repositories": ["private/secret"]}
    assert (without.status_code, error_code(without)) == (401, "UNAUTHORIZED")


async def test_deleting_an_image_removes_what_only_it_used(client, images, root, db):
    kept = await push_image(client, root, "app", "1.0", "base", "code v1")
    gone = await push_image(client, root, "app", "2.0", "base", "code v2")
    await push_manifest(client, root, "app", "latest", gone)
    before = await blobs_stored(db)

    removed = await client.delete(f"{V2}/app/manifests/{digest_of(gone)}", headers=root)
    again = await client.delete(f"{V2}/app/manifests/{digest_of(gone)}", headers=root)

    assert (removed.status_code, before) == (202, 5)  # two configurations, three layers
    assert (again.status_code, error_code(again)) == (404, "MANIFEST_UNKNOWN")
    assert await stored(db) == sorted(
        [
            f"blobs/{digest_of(layer('base'))}",  # the other image uses it
            f"blobs/{digest_of(layer('code v1'))}",
            f"blobs/{digest_of(config_for('base', 'code v1'))}",
            f"manifests/app/{digest_of(kept)}",
            "tags/app/1.0",
        ]
    )
    for tag in ("2.0", "latest"):
        response = await client.get(f"{V2}/app/manifests/{tag}", headers=root)
        assert (response.status_code, error_code(response)) == (404, "MANIFEST_UNKNOWN")
    assert (await client.get(f"{V2}/app/manifests/1.0", headers=root)).content == kept


async def test_deleting_a_tag_removes_nothing_else(client, images, root, db):
    manifest = await push_image(client, root, "app", "1.0", "one")
    before = await stored(db)

    removed = await client.delete(f"{V2}/app/manifests/1.0", headers=root)
    again = await client.delete(f"{V2}/app/manifests/1.0", headers=root)
    pinned = await client.get(f"{V2}/app/manifests/{digest_of(manifest)}", headers=root)

    assert removed.status_code == 202
    assert (again.status_code, error_code(again)) == (404, "MANIFEST_UNKNOWN")
    assert pinned.content == manifest  # a deployment may have pinned it by its digest
    assert await stored(db) == [path for path in before if path != "tags/app/1.0"]


async def test_deleting_an_image_for_several_platforms_removes_its_platforms(
    client, images, root, db
):
    amd64 = await push_image(client, root, "app", "amd64", "shared", "amd64 code")
    arm64 = await push_image(client, root, "app", "scratch", "shared", "arm64 code")
    await client.delete(f"{V2}/app/manifests/scratch", headers=root)  # arm64 has no tag now
    index = index_manifest(amd64, arm64)
    await push_manifest(client, root, "app", "1.0", index)

    removed = await client.delete(f"{V2}/app/manifests/{digest_of(index)}", headers=root)

    assert removed.status_code == 202
    remaining = await stored(db)
    # The platform with a tag of its own stays whole; the other went with the index.
    assert f"manifests/app/{digest_of(amd64)}" in remaining
    assert f"manifests/app/{digest_of(arm64)}" not in remaining
    assert f"blobs/{digest_of(layer('shared'))}" in remaining
    assert f"blobs/{digest_of(layer('amd64 code'))}" in remaining
    assert f"blobs/{digest_of(layer('arm64 code'))}" not in remaining
    assert "tags/app/1.0" not in remaining and "tags/app/amd64" in remaining


async def test_the_same_manifest_under_two_images_keeps_its_layers_until_both_go(
    client, images, root, db
):
    manifest = await push_image(client, root, "one", "1.0", "shared")
    await push_manifest(client, root, "two", "1.0", manifest)

    await client.delete(f"/v2/images/one/manifests/{digest_of(manifest)}", headers=root)
    still = await blobs_stored(db)
    pulled = await client.get("/v2/images/two/manifests/1.0", headers=root)
    await client.delete(f"/v2/images/two/manifests/{digest_of(manifest)}", headers=root)

    assert (still, pulled.content) == (2, manifest)
    assert await stored(db) == []


async def test_maintenance_removes_blobs_no_manifest_has_used_for_a_day(
    client, images, root, db, sessionmaker, settings
):
    await push_image(client, root, "app", "1.0", "used")
    await push_blob(client, root, "app", layer("abandoned push"))
    await push_blob(client, root, "app", layer("pushed just now"))
    old = [f"blobs/{digest_of(layer(text))}" for text in ("used", "abandoned push")]
    await db.execute(
        update(Asset).where(Asset.path.in_(old)).values(updated_at=utcnow() - timedelta(days=2))
    )
    await db.commit()

    await upkeep.run(sessionmaker, settings, utcnow())

    remaining = await stored(db)
    assert f"blobs/{digest_of(layer('abandoned push'))}" not in remaining
    assert f"blobs/{digest_of(layer('used'))}" in remaining
    assert f"blobs/{digest_of(layer('pushed just now'))}" in remaining  # a push may be under way
    assert (await client.get(f"{V2}/app/manifests/1.0", headers=root)).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "app/manifests/latest"),
        ("PATCH", "app/manifests/latest"),
        ("POST", "app/tags/list"),
    ],
)
async def test_what_a_manifest_or_a_tag_list_does_not_do(client, images, root, method, path):
    response = await client.request(method, f"{V2}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
