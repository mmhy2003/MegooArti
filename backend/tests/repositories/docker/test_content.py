"""A Docker repository through the content API."""

from tests.repositories.docker.conftest import digest_of, layer, push_image

CONTENT = "/api/v1/content/images"


async def test_a_registry_is_given_as_a_host_and_a_name(client, images, root):
    view = await client.get(CONTENT, headers=root)

    assert view.json()["url"] == "test/images"


async def test_tags_are_the_components_and_everything_is_in_the_tree(client, images, root):
    manifest = await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "team/app", "2.0", "one", "two")
    digest = digest_of(manifest)

    listed = await client.get(f"{CONTENT}/components", headers=root)
    top = await client.get(f"{CONTENT}/tree", headers=root)
    manifests = await client.get(
        f"{CONTENT}/tree", params={"path": "manifests/team/app"}, headers=root
    )
    by_digest = await client.get(
        f"{CONTENT}/asset", params={"path": f"manifests/team/app/{digest}"}, headers=root
    )
    tag = await client.get(f"{CONTENT}/asset", params={"path": "tags/team/app/1.0"}, headers=root)

    named = [(item["name"], item["version"]) for item in listed.json()["items"]]
    assert sorted(named) == [("team/app", "1.0"), ("team/app", "2.0")]  # no digests among them
    assert [item["name"] for item in top.json()["items"]] == ["blobs", "manifests", "tags"]
    assert digest in [item["name"] for item in manifests.json()["items"]]
    # A manifest's component is the registry's own: nothing points at what cannot be opened.
    assert [item["component"] for item in manifests.json()["items"]] == [None, None]
    assert by_digest.json()["component"] is None
    assert tag.json()["component"]["version"] == "1.0"


async def test_what_is_stored_is_fetched_through_the_registry(client, images, root):
    manifest = await push_image(client, root, "team/app", "1.0", "one")
    digest = digest_of(manifest)

    async def download(path: str) -> str | None:
        response = await client.get(f"{CONTENT}/asset", params={"path": path}, headers=root)
        return response.json()["download"]

    assert await download("tags/team/app/1.0") == "https://test/v2/images/team/app/manifests/1.0"
    by_digest = await download(f"manifests/team/app/{digest}")
    assert by_digest == f"https://test/v2/images/team/app/manifests/{digest}"
    # A layer is fetched as part of an image: by itself it belongs to none.
    assert await download(f"blobs/{digest_of(layer('one'))}") is None
    fetched = await client.get(by_digest.removeprefix("https://test"), headers=root)
    assert fetched.content == manifest
