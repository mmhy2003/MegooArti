"""Deleting from an npm repository through the content API leaves it as `npm unpublish` would."""

from megooarti.repositories.npm import paths
from tests.accounts import error_code
from tests.repositories.npm.conftest import address, publish

CONTENT = "/api/v1/content/npm"


async def delete_file(client, root, path: str):
    return await client.delete(f"{CONTENT}/asset", params={"path": path}, headers=root)


async def test_a_deleted_tarball_is_a_version_that_was_unpublished(client, registry, root):
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "@acme/tool", version)

    deleted = await delete_file(client, root, paths.tarball_path("@acme/tool", "2.0.0"))
    document = (await client.get(address("@acme/tool"), headers=root)).json()
    tarball = await client.get(
        f"/repository/npm/{paths.tarball_path('@acme/tool', '2.0.0')}", headers=root
    )

    assert deleted.status_code == 204
    assert list(document["versions"]) == ["1.0.0"]
    assert document["dist-tags"] == {"latest": "1.0.0"}  # the tag moved off what is gone
    assert tarball.status_code == 404


async def test_deleting_the_last_version_leaves_no_package(client, registry, root):
    await publish(client, root, "tool", "1.0.0")

    await delete_file(client, root, paths.tarball_path("tool", "1.0.0"))
    document = await client.get(address("tool"), headers=root)
    tree = await client.get(f"{CONTENT}/tree", headers=root)

    assert document.status_code == 404
    assert tree.json()["items"] == []  # its dist-tags went with it


async def test_a_version_is_deleted_as_a_component(client, registry, root):
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "tool", version)
    listed = await client.get(f"{CONTENT}/components", params={"name": "tool"}, headers=root)
    newest = next(item for item in listed.json()["items"] if item["version"] == "2.0.0")

    deleted = await client.delete(f"{CONTENT}/components/{newest['id']}", headers=root)
    document = (await client.get(address("tool"), headers=root)).json()

    assert deleted.status_code == 204
    assert (list(document["versions"]), document["dist-tags"]) == (["1.0.0"], {"latest": "1.0.0"})


async def test_what_the_registry_keeps_for_a_package_does_not_go_by_itself(client, registry, root):
    await publish(client, root, "tool", "1.0.0")

    response = await delete_file(client, root, paths.dist_tags_path("tool"))
    missing = await delete_file(client, root, paths.dist_tags_path("other"))
    document = (await client.get(address("tool"), headers=root)).json()

    assert (response.status_code, error_code(response)) == (409, "managed_by_format")
    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert document["dist-tags"] == {"latest": "1.0.0"}


async def test_a_package_is_deleted_as_a_folder(client, registry, root):
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "tool", version)
    await publish(client, root, "other", "1.0.0")

    response = await client.delete(f"{CONTENT}/tree", params={"path": "tool"}, headers=root)
    gone = await client.get(address("tool"), headers=root)
    kept = await client.get(address("other"), headers=root)

    assert response.json() == {"deleted": 2, "skipped": 0, "next": None}
    assert (gone.status_code, kept.status_code) == (404, 200)
