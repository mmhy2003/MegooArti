"""Deleting through the content API: a file, a component, a folder."""

import pytest

from megooarti.repositories import content_api, service
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

CONTENT = "/api/v1/content"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def put(client, headers, *paths: str, repository: str = "files") -> None:
    for path in paths:
        response = await client.put(
            f"/repository/{repository}/{path}", content=path.encode(), headers=headers
        )
        assert response.status_code == 201, response.text


async def names(client, headers, folder: str = "", repository: str = "files") -> list[str]:
    response = await client.get(
        f"{CONTENT}/{repository}/tree", params={"path": folder}, headers=headers
    )
    return [item["name"] for item in response.json().get("items", [])]


async def test_a_file_is_deleted(client, files, root):
    await put(client, root, "docs/guide.md", "docs/intro.md")

    deleted = await client.delete(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )
    again = await client.delete(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )
    fetched = await client.get("/repository/files/docs/guide.md", headers=root)

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert (again.status_code, error_code(again)) == (404, "not_found")
    assert fetched.status_code == 404
    assert await names(client, root, "docs") == ["intro.md"]


async def test_a_component_is_deleted_with_its_files(client, files, root):
    await put(client, root, "docs/guide.md", "docs/intro.md")
    listed = await client.get(
        f"{CONTENT}/files/components", params={"name": "guide.md"}, headers=root
    )
    address = f"{CONTENT}/files/components/{listed.json()['items'][0]['id']}"

    deleted = await client.delete(address, headers=root)
    again = await client.delete(address, headers=root)

    assert (deleted.status_code, again.status_code) == (204, 404)
    assert await names(client, root, "docs") == ["intro.md"]


async def test_a_folder_is_deleted_with_everything_under_it(client, files, root):
    await put(client, root, "app/one", "app/deep/two", "app/deep/er/three", "app-old/four", "apple")

    response = await client.delete(f"{CONTENT}/files/tree", params={"path": "app/"}, headers=root)
    nothing = await client.delete(f"{CONTENT}/files/tree", params={"path": "app"}, headers=root)

    assert response.json() == {"deleted": 3, "skipped": 0, "next": None}
    assert nothing.json() == {"deleted": 0, "skipped": 0, "next": None}
    assert await names(client, root) == ["app-old", "apple"]  # its neighbours are untouched


async def test_a_large_folder_is_deleted_in_pieces(client, files, root, monkeypatch):
    monkeypatch.setattr(content_api, "_FOLDER_AT_ONCE", 3)
    await put(client, root, *(f"logs/day-{number}" for number in range(8)), "logs-kept")
    counts, after = [], ""

    while after is not None:
        response = await client.delete(
            f"{CONTENT}/files/tree", params={"path": "logs", "after": after}, headers=root
        )
        counts.append(response.json()["deleted"])
        after = response.json()["next"]

    assert counts == [3, 3, 2]
    assert await names(client, root) == ["logs-kept"]


@pytest.mark.parametrize("path", ["", "/", "a/../b", "a//b"])
async def test_a_folder_to_delete_must_be_named(client, files, root, path):
    await put(client, root, "a/b/c")

    response = await client.delete(f"{CONTENT}/files/tree", params={"path": path}, headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert await names(client, root) == ["a"]


async def test_deleting_needs_delete_whatever_else_one_may_do(client, files, root, make_user, db):
    await put(client, root, "docs/guide.md")
    may = ["repository:raw:files:browse", "repository:raw:files:read", "repository:raw:files:add"]
    await roles.create_role(db, "writers", "", may, [])
    await db.commit()
    await make_user("writer", roles=["writers"])
    writer = basic("writer", PASSWORD)
    listed = await client.get(f"{CONTENT}/files/components", headers=writer)
    component = listed.json()["items"][0]["id"]

    attempts = [
        await client.delete(
            f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=writer
        ),
        await client.delete(f"{CONTENT}/files/asset", params={"path": "nothing"}, headers=writer),
        await client.delete(f"{CONTENT}/files/tree", params={"path": "docs"}, headers=writer),
        await client.delete(f"{CONTENT}/files/components/{component}", headers=writer),
    ]
    nobody = await client.delete(f"{CONTENT}/files/asset", params={"path": "docs/guide.md"})

    for response in attempts:
        assert (response.status_code, error_code(response)) == (403, "forbidden")
    assert nobody.status_code == 401
    assert await names(client, root, "docs") == ["guide.md"]


async def test_nothing_is_deleted_from_a_read_only_repository(client, root, db):
    frozen = await service.create_repository(
        db, name="frozen", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    await put(client, root, "a/b", repository="frozen")
    frozen.config = {**frozen.config, "hosted": {"deployment_policy": "read_only"}}
    await db.commit()

    file = await client.delete(f"{CONTENT}/frozen/asset", params={"path": "a/b"}, headers=root)
    folder = await client.delete(f"{CONTENT}/frozen/tree", params={"path": "a"}, headers=root)

    for response in (file, folder):
        assert (response.status_code, error_code(response)) == (403, "repository_read_only")
    assert await names(client, root, "a", repository="frozen") == ["b"]


async def test_a_group_has_nothing_to_delete(client, files, root, db):
    await service.create_repository(
        db,
        name="all",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    await db.commit()
    await put(client, root, "docs/guide.md")

    attempts = [
        await client.delete(f"{CONTENT}/all/asset", params={"path": "docs/guide.md"}, headers=root),
        await client.delete(f"{CONTENT}/all/tree", params={"path": "docs"}, headers=root),
    ]

    for response in attempts:
        assert (response.status_code, error_code(response)) == (409, "not_browsable")
    assert await names(client, root, "docs") == ["guide.md"]


async def test_deleting_from_a_proxy_removes_the_cached_copy(client, mirror, fake_remote, root):
    fake_remote.files["files/lib/a.bin"] = b"from the remote"
    await client.get("/repository/mirror/lib/a.bin", headers=root)

    deleted = await client.delete(
        f"{CONTENT}/mirror/asset", params={"path": "lib/a.bin"}, headers=root
    )
    gone = await names(client, root, repository="mirror")
    fake_remote.files["files/lib/a.bin"] = b"what the remote has now"
    again = await client.get("/repository/mirror/lib/a.bin", headers=root)

    assert (deleted.status_code, gone) == (204, [])
    assert again.content == b"what the remote has now"  # fetched again when asked for
