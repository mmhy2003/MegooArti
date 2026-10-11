"""A Maven repository through the content API."""

CONTENT = "/api/v1/content/releases"
VERSION = "com/acme/app/1.0"


async def deploy(client, root, *paths: str) -> None:
    for path in paths:
        response = await client.put(
            f"/repository/releases/{path}", content=path.encode(), headers=root
        )
        assert response.status_code == 201, response.text


async def test_an_artifact_is_a_component_with_its_files(client, releases, root):
    await deploy(client, root, f"{VERSION}/app-1.0.jar", f"{VERSION}/app-1.0.pom")
    await deploy(client, root, "com/acme/app/1.1/app-1.1.jar", "com/acme/lib/2.0/lib-2.0.jar")

    listed = await client.get(f"{CONTENT}/components", headers=root)
    versions = await client.get(
        f"{CONTENT}/components", params={"namespace": "com.acme", "name": "app"}, headers=root
    )
    first = next(item for item in versions.json()["items"] if item["version"] == "1.0")
    opened = await client.get(f"{CONTENT}/components/{first['id']}", headers=root)
    tree = await client.get(f"{CONTENT}/tree", params={"path": VERSION}, headers=root)

    named = [(item["namespace"], item["name"], item["version"]) for item in listed.json()["items"]]
    assert named == [
        ("com.acme", "app", "1.1"),
        ("com.acme", "app", "1.0"),
        ("com.acme", "lib", "2.0"),
    ]
    assert [file["name"] for file in opened.json()["files"]] == ["app-1.0.jar", "app-1.0.pom"]
    # What Maven computes when it is asked (checksums, metadata) is not a stored file.
    assert [item["name"] for item in tree.json()["items"]] == ["app-1.0.jar", "app-1.0.pom"]
    assert tree.json()["items"][0]["component"]["version"] == "1.0"
