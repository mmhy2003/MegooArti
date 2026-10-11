"""Deleting from a Maven repository through the content API."""

CONTENT = "/api/v1/content/releases"
APP = "com/acme/app"


async def deploy(client, root, *paths: str) -> None:
    for path in paths:
        response = await client.put(
            f"/repository/releases/{path}", content=path.encode(), headers=root
        )
        assert response.status_code == 201, response.text


async def versions(client, root) -> str:
    response = await client.get(f"/repository/releases/{APP}/maven-metadata.xml", headers=root)
    return response.text if response.status_code == 200 else ""


async def test_a_version_is_deleted_as_a_component_and_the_metadata_follows(client, releases, root):
    await deploy(client, root, f"{APP}/1.0/app-1.0.jar", f"{APP}/1.0/app-1.0.pom")
    await deploy(client, root, f"{APP}/1.1/app-1.1.jar")
    listed = await client.get(f"{CONTENT}/components", params={"name": "app"}, headers=root)
    first = next(item for item in listed.json()["items"] if item["version"] == "1.0")

    deleted = await client.delete(f"{CONTENT}/components/{first['id']}", headers=root)
    metadata = await versions(client, root)
    jar = await client.get(f"/repository/releases/{APP}/1.0/app-1.0.jar", headers=root)
    checksum = await client.get(f"/repository/releases/{APP}/1.0/app-1.0.jar.sha1", headers=root)

    assert deleted.status_code == 204
    assert "<version>1.1</version>" in metadata and "<version>1.0</version>" not in metadata
    assert (jar.status_code, checksum.status_code) == (404, 404)


async def test_one_file_of_a_version_is_deleted_and_the_rest_stays(client, releases, root):
    await deploy(client, root, f"{APP}/1.0/app-1.0.jar", f"{APP}/1.0/app-1.0-sources.jar")

    deleted = await client.delete(
        f"{CONTENT}/asset", params={"path": f"{APP}/1.0/app-1.0-sources.jar"}, headers=root
    )
    tree = await client.get(f"{CONTENT}/tree", params={"path": f"{APP}/1.0"}, headers=root)

    assert deleted.status_code == 204
    assert [item["name"] for item in tree.json()["items"]] == ["app-1.0.jar"]
    assert "<version>1.0</version>" in await versions(client, root)


async def test_an_artifact_is_deleted_as_a_folder(client, releases, root):
    await deploy(client, root, f"{APP}/1.0/app-1.0.jar", f"{APP}/1.1/app-1.1.jar")
    await deploy(client, root, "com/acme/lib/2.0/lib-2.0.jar")

    response = await client.delete(f"{CONTENT}/tree", params={"path": APP}, headers=root)
    left = await client.get(f"{CONTENT}/tree", params={"path": "com/acme"}, headers=root)

    assert response.json() == {"deleted": 2, "skipped": 0, "next": None}
    assert await versions(client, root) == ""
    assert [item["name"] for item in left.json()["items"]] == ["lib"]
