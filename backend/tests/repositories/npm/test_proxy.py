import hashlib
import json

import pytest
from sqlalchemy import select

from megooarti.repositories.models import Asset, Component
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, bearer, error_code
from tests.repositories.npm.conftest import REMOTE, create, remote_document, tarball_of

PROXY = "/repository/npmjs"
HERE = "https://test/repository/npmjs"
TARBALL = f"{PROXY}/left-pad/-/left-pad-1.3.0.tgz"


def asked(remote, method: str = "GET") -> list[str]:
    return [path.removeprefix("/registry/") for path in remote.paths(method)]


def links(response) -> list[str]:
    return [version["dist"]["tarball"] for version in response.json()["versions"].values()]


@pytest.fixture
def remote(fake_remote, npmjs):
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0", "1.3.0")
    fake_remote.files["registry/left-pad/-/left-pad-1.3.0.tgz"] = tarball_of("left-pad", "1.3.0")
    fake_remote.files["registry/@acme/widget"] = remote_document("@acme/widget", "2.0.0")
    return fake_remote


async def test_a_package_document_is_served_with_its_links_pointing_here(client, root, remote):
    first = await client.get(f"{PROXY}/left-pad", headers=root)
    second = await client.get(f"{PROXY}/left-pad", headers=root)

    assert first.status_code == 200, first.text
    assert links(first) == [
        f"{HERE}/left-pad/-/left-pad-1.0.0.tgz",
        f"{HERE}/left-pad/-/left-pad-1.3.0.tgz",
    ]
    assert first.json()["dist-tags"] == {"latest": "1.3.0"}
    assert second.content == first.content
    assert asked(remote) == ["left-pad"]


async def test_the_document_is_answered_as_content_without_a_length(client, root, remote):
    first = await client.get(f"{PROXY}/left-pad", headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(f"{PROXY}/left-pad", headers={**root, "If-None-Match": etag})
    headed = await client.head(f"{PROXY}/left-pad", headers=root)
    ranged = await client.get(f"{PROXY}/left-pad", headers={**root, "Range": "bytes=0-9"})

    assert first.headers["Content-Type"] == "application/json"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert first.headers["Accept-Ranges"] == "none"
    assert "Content-Length" not in first.headers
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (headed.status_code, headed.content, headed.headers["ETag"]) == (200, b"", etag)
    assert "Content-Length" not in headed.headers  # not 0: the length is not known
    assert (ranged.status_code, ranged.content) == (200, first.content)


async def test_a_document_read_back_in_several_pieces_has_every_link_rewritten(
    client, root, npmjs, fake_remote
):
    versions = [f"1.0.{patch}" for patch in range(12_000)]
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", *versions)
    assert len(fake_remote.files["registry/left-pad"]) > 2 * 1024 * 1024  # over two pieces

    response = await client.get(f"{PROXY}/left-pad", headers=root)

    assert links(response) == [f"{HERE}/left-pad/-/left-pad-{version}.tgz" for version in versions]


async def test_a_document_asked_for_by_head_first_is_fetched_once(client, root, remote):
    headed = await client.head(f"{PROXY}/left-pad", headers=root)
    fetched = await client.get(f"{PROXY}/left-pad", headers=root)

    assert (headed.status_code, fetched.status_code) == (200, 200)
    assert (asked(remote), asked(remote, "HEAD")) == (["left-pad"], [])


async def test_a_scoped_package_is_asked_for_as_the_registry_spells_it(client, root, remote):
    encoded = await client.get(f"{PROXY}/@acme%2fwidget", headers=root)
    plain = await client.get(f"{PROXY}/@acme/widget", headers=root)

    assert links(encoded) == [f"{HERE}/@acme/widget/-/widget-2.0.0.tgz"]
    assert plain.content == encoded.content
    assert [seen["raw_path"] for seen in remote.requests] == ["/registry/@acme%2Fwidget"]


async def test_a_tarball_is_fetched_cached_and_given_its_component(client, root, remote, db):
    first = await client.get(TARBALL, headers=root)
    second = await client.get(f"{TARBALL}/-rev/anything", headers=root)

    data = tarball_of("left-pad", "1.3.0")
    assert (first.status_code, first.content, second.content) == (200, data, data)
    assert first.headers["Content-Type"] == "application/octet-stream"
    assert first.headers["X-Checksum-Sha1"] == hashlib.sha1(data).hexdigest()
    assert asked(remote) == ["left-pad/-/left-pad-1.3.0.tgz"]
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "left-pad", "1.3.0")


async def test_a_scoped_tarball_is_fetched_from_its_scoped_path(client, root, remote):
    remote.files["registry/@acme/widget/-/widget-2.0.0.tgz"] = tarball_of("@acme/widget", "2.0.0")

    response = await client.get(f"{PROXY}/@acme/widget/-/widget-2.0.0.tgz", headers=root)

    assert response.content == tarball_of("@acme/widget", "2.0.0")
    assert remote.requests[0]["raw_path"] == "/registry/@acme/widget/-/widget-2.0.0.tgz"


async def test_documents_are_asked_about_again_and_tarballs_are_not(client, root, db, fake_remote):
    ages = {"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": -1}
    await create(db, "eager", type="proxy", proxy=ages)
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.3.0")
    fake_remote.files["registry/left-pad/-/left-pad-1.3.0.tgz"] = tarball_of("left-pad", "1.3.0")

    for _ in range(2):
        await client.get("/repository/eager/left-pad", headers=root)
        await client.get("/repository/eager/left-pad/-/left-pad-1.3.0.tgz", headers=root)

    assert asked(fake_remote) == ["left-pad", "left-pad/-/left-pad-1.3.0.tgz", "left-pad"]


async def test_a_new_version_at_the_remote_appears_and_changes_the_etag(
    client, root, db, fake_remote
):
    await create(
        db, "eager", type="proxy", proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0}
    )
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0")
    before = await client.get("/repository/eager/left-pad", headers=root)
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0", "1.3.0")

    after = await client.get(
        "/repository/eager/left-pad", headers={**root, "If-None-Match": before.headers["ETag"]}
    )

    assert (after.status_code, list(after.json()["versions"])) == (200, ["1.0.0", "1.3.0"])
    assert after.headers["ETag"] != before.headers["ETag"]


async def test_what_the_remote_lacks_is_not_found_and_remembered(client, root, remote):
    first = await client.get(f"{PROXY}/no-such-package", headers=root)
    again = await client.get(f"{PROXY}/no-such-package", headers=root)

    assert (first.status_code, error_code(first)) == (404, "not_found")
    assert again.status_code == 404
    assert asked(remote) == ["no-such-package"]


async def test_a_cached_document_is_served_while_the_remote_is_down(client, root, db, fake_remote):
    await create(
        db, "eager", type="proxy", proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0}
    )
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0")
    cached = await client.get("/repository/eager/left-pad", headers=root)
    fake_remote.down = True

    still = await client.get("/repository/eager/left-pad", headers=root)
    never_seen = await client.get("/repository/eager/right-pad", headers=root)

    assert (still.status_code, still.content) == (200, cached.content)
    assert (never_seen.status_code, error_code(never_seen)) == (502, "remote_unavailable")


async def test_links_use_the_configured_public_address(client, root, remote, db):
    by_request = await client.get(f"{PROXY}/left-pad", headers=root)
    await set_setting(db, "base_url", "https://packages.example")
    await db.commit()

    configured = await client.get(f"{PROXY}/left-pad", headers=root)

    assert links(configured)[0] == (
        "https://packages.example/repository/npmjs/left-pad/-/left-pad-1.0.0.tgz"
    )
    assert configured.headers["ETag"] != by_request.headers["ETag"]


async def test_a_link_written_with_escaped_slashes_is_left_as_it_is(client, root, remote):
    escaped = remote_document("left-pad", "1.0.0").replace(b"/", b"\\/")
    remote.files["registry/odd"] = escaped

    response = await client.get(f"{PROXY}/odd", headers=root)

    assert response.content == escaped
    assert json.loads(response.content)["versions"]["1.0.0"]["dist"]["tarball"].startswith(REMOTE)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "left-pad"),
        ("DELETE", "left-pad"),
        ("DELETE", "left-pad/-/left-pad-1.3.0.tgz"),
        ("PUT", "-/package/left-pad/dist-tags/beta"),
        ("POST", "-/v1/search"),
    ],
)
async def test_a_proxy_cannot_be_written_to(client, root, remote, method, path):
    response = await client.request(method, f"{PROXY}/{path}", json={}, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert asked(remote) == []


@pytest.mark.parametrize(
    "path", ["left-pad/1.3.0", "left-pad/latest", "-/package/left-pad/dist-tags"]
)
async def test_what_only_a_hosted_repository_answers_is_not_allowed(client, root, remote, path):
    response = await client.get(f"{PROXY}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert asked(remote) == []


async def test_signing_in_works_on_a_proxy(client, npmjs, make_user):
    await make_user("dana", roles=["admin"])
    login = f"{PROXY}/-/user/org.couchdb.user:dana"

    signed_in = await client.put(login, json={"name": "dana", "password": PASSWORD})
    token = signed_in.json()["token"]
    who = await client.get(f"{PROXY}/-/whoami", headers=bearer(token))
    signed_out = await client.delete(f"{PROXY}/-/user/token/{token}", headers=bearer(token))

    assert (signed_in.status_code, who.json()) == (201, {"username": "dana"})
    assert signed_out.status_code == 200
    assert (await client.get(f"{PROXY}/-/ping", headers=bearer(token))).status_code == 401


async def test_search_finds_what_the_proxy_has_cached(client, root, remote, db):
    before = await client.get(f"{PROXY}/-/v1/search", params={"text": "pad"}, headers=root)
    await client.get(TARBALL, headers=root)

    after = await client.get(f"{PROXY}/-/v1/search", params={"text": "pad"}, headers=root)

    assert before.json()["objects"] == []
    found = after.json()["objects"]
    assert [(entry["package"]["name"], entry["package"]["version"]) for entry in found] == [
        ("left-pad", "1.3.0")
    ]
    assert list(await db.scalars(select(Asset.path))) == ["left-pad/-/left-pad-1.3.0.tgz"]
