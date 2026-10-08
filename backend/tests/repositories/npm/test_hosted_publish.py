import base64
import hashlib

import pytest
from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.npm.conftest import (
    URL,
    address,
    create,
    publish,
    publish_body,
    tarball_of,
)

TARBALL_URL = f"{URL}/left-pad/-/left-pad-1.0.0.tgz"


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_a_published_package_can_be_read_back(client, registry, root, db):
    published = await publish(client, root, "left-pad", "1.0.0", description="Pads on the left")

    document = await client.get(f"{URL}/left-pad", headers=root)
    tarball = await client.get(TARBALL_URL, headers=root)

    assert published.status_code == 201, published.text
    assert published.json()["ok"] is True
    body = document.json()
    assert (document.status_code, body["name"], body["_id"]) == (200, "left-pad", "left-pad")
    assert body["dist-tags"] == {"latest": "1.0.0"}
    assert body["description"] == "Pads on the left"
    manifest = body["versions"]["1.0.0"]
    data = tarball_of("left-pad", "1.0.0")
    assert manifest["dist"] == {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": "https://test/repository/npm/left-pad/-/left-pad-1.0.0.tgz",
    }
    assert (tarball.status_code, tarball.content) == (200, data)
    assert tarball.headers["Content-Type"] == "application/octet-stream"
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "left-pad", "1.0.0")
    assert "tarball" not in component.attributes["npm"]["dist"]


async def test_the_document_is_served_like_any_content(client, registry, root):
    await publish(client, root, "left-pad", "1.0.0")
    first = await client.get(f"{URL}/left-pad", headers=root)
    etag = first.headers["ETag"]

    headed = await client.head(f"{URL}/left-pad", headers=root)
    unchanged = await client.get(f"{URL}/left-pad", headers={**root, "If-None-Match": etag})
    await publish(client, root, "left-pad", "1.1.0")
    changed = await client.get(f"{URL}/left-pad", headers={**root, "If-None-Match": etag})

    assert first.headers["Content-Type"] == "application/json"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert "X-Checksum-Md5" not in first.headers
    assert (headed.status_code, headed.content) == (200, b"")
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (changed.status_code, list(changed.json()["versions"])) == (200, ["1.0.0", "1.1.0"])


async def test_a_scoped_package(client, registry, root, db):
    published = await publish(client, root, "@acme/widget", "2.0.0")

    encoded = await client.get(f"{URL}/@acme%2fwidget", headers=root)
    plain = await client.get(f"{URL}/@acme/widget", headers=root)
    tarball = await client.get(f"{URL}/@acme/widget/-/widget-2.0.0.tgz", headers=root)

    assert published.status_code == 201, published.text
    assert encoded.json() == plain.json()
    link = encoded.json()["versions"]["2.0.0"]["dist"]["tarball"]
    assert link == "https://test/repository/npm/@acme/widget/-/widget-2.0.0.tgz"
    assert tarball.content == tarball_of("@acme/widget", "2.0.0")
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("acme", "widget", "2.0.0")


async def test_versions_are_listed_in_order_and_latest_follows_the_publish(client, registry, root):
    for version in ("1.10.0", "1.9.0"):
        await publish(client, root, "left-pad", version)
    await publish(client, root, "left-pad", "2.0.0-beta.1", tag="beta")

    body = (await client.get(f"{URL}/left-pad", headers=root)).json()

    assert list(body["versions"]) == ["1.9.0", "1.10.0", "2.0.0-beta.1"]
    assert body["dist-tags"] == {"latest": "1.9.0", "beta": "2.0.0-beta.1"}
    assert set(body["time"]) == {"created", "modified", "1.9.0", "1.10.0", "2.0.0-beta.1"}


async def test_the_first_version_is_latest_whatever_tag_it_was_published_with(
    client, registry, root
):
    await publish(client, root, "left-pad", "1.0.0-rc.1", tag="next")

    body = (await client.get(f"{URL}/left-pad", headers=root)).json()

    assert body["dist-tags"] == {"latest": "1.0.0-rc.1", "next": "1.0.0-rc.1"}


async def test_one_version_by_number_or_by_tag(client, registry, root):
    await publish(client, root, "left-pad", "1.0.0")
    await publish(client, root, "left-pad", "1.1.0")

    by_number = await client.get(f"{URL}/left-pad/1.0.0", headers=root)
    by_tag = await client.get(f"{URL}/left-pad/latest", headers=root)
    missing = await client.get(f"{URL}/left-pad/9.9.9", headers=root)

    assert by_number.json()["version"] == "1.0.0"
    assert by_number.json()["dist"]["tarball"].endswith("/left-pad/-/left-pad-1.0.0.tgz")
    assert by_tag.json()["version"] == "1.1.0"
    assert (missing.status_code, error_code(missing)) == (404, "not_found")


async def test_links_use_the_configured_public_address(client, registry, root, db):
    await publish(client, root, "left-pad", "1.0.0")
    await set_setting(db, "base_url", "https://packages.example/")
    await db.commit()

    body = (await client.get(f"{URL}/left-pad", headers=root)).json()

    assert body["versions"]["1.0.0"]["dist"]["tarball"] == (
        "https://packages.example/repository/npm/left-pad/-/left-pad-1.0.0.tgz"
    )


async def test_what_is_not_there_is_not_found(client, registry, root):
    for path in (
        "left-pad",
        "left-pad/1.0.0",
        "left-pad/-/left-pad-1.0.0.tgz",
        "-/nothing",
        "a/b/c",
    ):
        response = await client.get(f"{URL}/{path}", headers=root)
        assert (response.status_code, error_code(response)) == (404, "not_found"), path


async def test_publishing_a_version_again_follows_the_deployment_policy(client, db, root):
    await create(db, "npm")
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    for repository in ("npm", "once"):
        await publish(client, root, "left-pad", "1.0.0", repository=repository)

    replaced = await publish(
        client, root, "left-pad", "1.0.0", repository="npm", description="again"
    )
    refused = await publish(client, root, "left-pad", "1.0.0", repository="once")

    assert replaced.status_code == 201
    document = (await client.get(address("left-pad"), headers=root)).json()
    assert document["versions"]["1.0.0"]["description"] == "again"
    assert (refused.status_code, error_code(refused)) == (409, "redeploy_disabled")


async def test_a_tarball_that_does_not_match_its_manifest_is_refused(
    client, registry, root, db, settings
):
    wrong_sha1 = publish_body("left-pad", "1.0.0")
    wrong_sha1["versions"]["1.0.0"]["dist"]["shasum"] = "0" * 40
    wrong_integrity = publish_body("left-pad", "1.0.0")
    wrong_integrity["versions"]["1.0.0"]["dist"]["integrity"] = (
        "sha512-" + base64.b64encode(b"\x00" * 64).decode()
    )
    wrong_length = publish_body("left-pad", "1.0.0")
    wrong_length["_attachments"]["left-pad-1.0.0.tgz"]["length"] = 3

    for body in (wrong_sha1, wrong_integrity, wrong_length):
        response = await client.put(f"{URL}/left-pad", json=body, headers=root)
        assert (response.status_code, error_code(response)) == (400, "checksum_mismatch")

    assert await count(db, Asset) == 0
    temporary = settings.data_dir / "blobs" / "default" / "tmp"
    assert not temporary.exists() or list(temporary.iterdir()) == []


async def test_a_publish_must_be_a_package(client, registry, root, db):
    another_name = publish_body("right-pad", "1.0.0")
    no_tarball = publish_body("left-pad", "1.0.0")
    no_tarball["_attachments"] = {"something-else.tgz": {"data": "aGk="}}
    not_a_version = publish_body("left-pad", "1.0")

    for body in (another_name, no_tarball, not_a_version, ["not", "an", "object"]):
        response = await client.put(f"{URL}/left-pad", json=body, headers=root)
        assert (response.status_code, error_code(response)) == (400, "invalid_package")
    not_json = await client.put(f"{URL}/left-pad", content=b"{", headers=root)

    assert (not_json.status_code, error_code(not_json)) == (400, "invalid_package")
    assert await count(db, Asset) == 0


async def test_a_publish_larger_than_the_limit_is_refused(client, registry, root, app, db):
    app.state.settings.npm_max_publish_bytes = 500

    response = await publish(client, root, "left-pad", "1.0.0", readme="x" * 600)

    assert (response.status_code, error_code(response)) == (413, "payload_too_large")
    assert await count(db, Asset) == 0


async def test_a_new_package_needs_a_lower_case_name(client, registry, root):
    response = await publish(client, root, "LeftPad", "1.0.0")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")


async def test_a_tarball_cannot_be_uploaded_on_its_own(client, registry, root):
    response = await client.put(TARBALL_URL, content=b"raw bytes", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, DELETE"


async def test_publishing_needs_add_and_reading_needs_read(client, registry, root, make_user, db):
    await roles.create_role(db, "publishers", "", ["repository:npm:npm:add"], [])
    await roles.create_role(db, "readers", "", ["repository:npm:npm:read"], [])
    await db.commit()
    await make_user("pat", roles=["publishers"])
    await make_user("rae", roles=["readers"])
    publisher, reader = basic("pat", PASSWORD), basic("rae", PASSWORD)

    by_reader = await publish(client, reader, "left-pad", "1.0.0")
    by_nobody = await publish(client, {}, "left-pad", "1.0.0")
    by_publisher = await publish(client, publisher, "left-pad", "1.0.0")
    next_version = await publish(client, publisher, "left-pad", "1.1.0")
    again = await publish(client, publisher, "left-pad", "1.0.0")
    read_by_publisher = await client.get(f"{URL}/left-pad", headers=publisher)
    read_by_reader = await client.get(f"{URL}/left-pad", headers=reader)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert by_nobody.status_code == 401
    assert (by_publisher.status_code, next_version.status_code) == (201, 201)
    assert (again.status_code, error_code(again)) == (403, "forbidden")  # replacing needs edit
    assert read_by_publisher.status_code == 403
    assert list(read_by_reader.json()["versions"]) == ["1.0.0", "1.1.0"]


async def test_a_read_only_repository_takes_no_publish(client, db, root):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await publish(client, root, "left-pad", "1.0.0", repository="frozen")

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_other_methods_are_not_allowed(client, registry, root, method):
    response = await client.request(method, f"{URL}/left-pad", json={}, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
