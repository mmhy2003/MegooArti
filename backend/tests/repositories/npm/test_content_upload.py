"""Uploading to an npm repository through the content API leaves it as `npm publish` would."""

import base64
import hashlib

import pytest

from megooarti.repositories.npm import paths
from tests.accounts import error_code
from tests.repositories.npm.conftest import address, create, package_tarball, packed, publish

UPLOAD = "/api/v1/content/npm/upload"


async def send(client, root, data: bytes, *, to: str = UPLOAD, **fields):
    return await client.post(to, data=fields, files=[("file", ("package.tgz", data))], headers=root)


async def test_an_uploaded_tarball_is_a_published_version(client, registry, root):
    data = package_tarball("tool", "1.0.0", description="A tool", keywords=["handy"])

    response = await send(client, root, data)
    document = (await client.get(address("tool"), headers=root)).json()
    tarball = await client.get(
        f"/repository/npm/{paths.tarball_path('tool', '1.0.0')}", headers=root
    )

    assert response.status_code == 201, response.text
    stored = response.json()
    assert [file["path"] for file in stored["files"]] == ["tool/-/tool-1.0.0.tgz"]
    assert [(c["namespace"], c["name"], c["version"]) for c in stored["components"]] == [
        ("", "tool", "1.0.0")
    ]
    assert document["dist-tags"] == {"latest": "1.0.0"}
    version = document["versions"]["1.0.0"]
    assert (version["name"], version["description"]) == ("tool", "A tool")
    assert version["_id"] == "tool@1.0.0"
    assert version["dist"]["shasum"] == hashlib.sha1(data).hexdigest()
    assert version["dist"]["integrity"] == (
        "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    )
    assert version["dist"]["tarball"].endswith("/repository/npm/tool/-/tool-1.0.0.tgz")
    assert tarball.content == data


async def test_a_scoped_package_goes_under_its_scope(client, registry, root):
    response = await send(client, root, package_tarball("@acme/tool", "2.1.0"))
    document = (await client.get(address("@acme/tool"), headers=root)).json()

    assert response.status_code == 201, response.text
    assert response.json()["files"][0]["path"] == "@acme/tool/-/tool-2.1.0.tgz"
    component = response.json()["components"][0]
    assert (component["namespace"], component["name"]) == ("acme", "tool")
    assert list(document["versions"]) == ["2.1.0"]


async def test_versions_uploaded_and_published_are_one_package(client, registry, root):
    await publish(client, root, "tool", "1.0.0")

    response = await send(client, root, package_tarball("tool", "1.1.0"))
    document = (await client.get(address("tool"), headers=root)).json()

    assert response.status_code == 201, response.text
    assert list(document["versions"]) == ["1.0.0", "1.1.0"]
    assert document["dist-tags"] == {"latest": "1.1.0"}


async def test_a_tag_other_than_latest_can_be_given(client, registry, root):
    await send(client, root, package_tarball("tool", "1.0.0"))

    response = await send(client, root, package_tarball("tool", "2.0.0-beta.1"), tag="beta")
    document = (await client.get(address("tool"), headers=root)).json()

    assert response.status_code == 201, response.text
    assert document["dist-tags"] == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}


async def test_uploading_a_version_again_follows_the_deployment_policy(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    to = "/api/v1/content/once/upload"
    first = await send(client, root, package_tarball("tool", "1.0.0"), to=to)

    again = await send(client, root, package_tarball("tool", "1.0.0", description="new"), to=to)
    document = (await client.get(address("tool", "once"), headers=root)).json()

    assert first.status_code == 201, first.text
    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert "description" not in document["versions"]["1.0.0"]


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"this is not a tarball", "not a package tarball"),
        (packed({"package/index.js": b"1"}), "no package.json"),
        (packed({"package/package.json": {"version": "1.0.0"}}), "does not name a package"),
        (packed({"package/package.json": {"name": "a b", "version": "1.0.0"}}), "does not name"),
        (packed({"package/package.json": {"name": "tool"}}), "no version"),
        (package_tarball("tool", "one"), "not a valid version"),
        (package_tarball("Tool", "1.0.0"), "lower case"),
        (package_tarball("tool", "1.0.0", private=True), "private"),
    ],
    ids=[
        "text",
        "no-manifest",
        "unnamed",
        "bad-name",
        "no-version",
        "bad-version",
        "case",
        "private",
    ],
)
async def test_what_is_not_a_package_to_publish_is_refused(client, registry, root, data, reason):
    response = await send(client, root, data)
    tree = await client.get("/api/v1/content/npm/tree", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert reason in response.json()["error"]["message"]
    assert tree.json()["items"] == []


async def test_a_form_needs_one_tarball_and_nothing_it_does_not_know(client, registry, root):
    tarball = ("package.tgz", package_tarball("tool", "1.0.0"))
    none = await client.post(UPLOAD, data={"tag": "latest"}, files=[], headers=root)
    two = await client.post(UPLOAD, files=[("file", tarball), ("file", tarball)], headers=root)
    other = await client.post(UPLOAD, files=[("tarball", tarball)], headers=root)
    tagged = await send(client, root, tarball[1], tag="a/b")
    misspelt = await send(client, root, tarball[1], tga="beta")

    for response in (none, two, other, tagged, misspelt):
        assert (response.status_code, error_code(response)) == (422, "validation_error")
    fields = [r.json()["error"]["details"][0]["field"] for r in (two, other, tagged, misspelt)]
    assert fields == ["file", "file", "tag", "tga"]


async def test_a_tarball_larger_than_a_publish_may_be_is_refused(client, registry, root, app):
    app.state.settings.npm_max_publish_bytes = 200
    data = package_tarball("tool", "1.0.0", readme="x" * 5000, noise=list(range(500)))

    response = await send(client, root, data)

    assert len(data) > 200
    assert (response.status_code, error_code(response)) == (413, "payload_too_large")
