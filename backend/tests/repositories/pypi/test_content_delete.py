"""Deleting from a PyPI repository through the content API."""

from tests.repositories.pypi.conftest import upload

CONTENT = "/api/v1/content/pypi"
WHEEL = "greeter-1.0-py3-none-any.whl"
SDIST = "greeter-1.0.tar.gz"
NEWER = "greeter-2.0-py3-none-any.whl"


async def page(client, root) -> str:
    response = await client.get("/repository/pypi/simple/greeter/", headers=root)
    return response.text if response.status_code == 200 else ""


async def test_a_deleted_file_is_off_its_projects_page(client, index, root):
    for filename in (WHEEL, SDIST, NEWER):
        assert (await upload(client, root, filename)).status_code == 200

    deleted = await client.delete(
        f"{CONTENT}/asset", params={"path": f"packages/greeter/1.0/{SDIST}"}, headers=root
    )
    listed = await page(client, root)

    assert deleted.status_code == 204
    assert WHEEL in listed and NEWER in listed and SDIST not in listed


async def test_a_release_is_deleted_as_a_component(client, index, root):
    for filename in (WHEEL, SDIST, NEWER):
        await upload(client, root, filename)
    found = await client.get(f"{CONTENT}/components", params={"name": "greeter"}, headers=root)
    first = next(item for item in found.json()["items"] if item["version"] == "1.0")

    deleted = await client.delete(f"{CONTENT}/components/{first['id']}", headers=root)
    listed = await page(client, root)

    assert deleted.status_code == 204
    assert NEWER in listed and WHEEL not in listed and SDIST not in listed


async def test_a_project_is_deleted_as_a_folder(client, index, root):
    for filename in (WHEEL, SDIST, NEWER):
        await upload(client, root, filename)

    response = await client.delete(
        f"{CONTENT}/tree", params={"path": "packages/greeter"}, headers=root
    )

    assert response.json() == {"deleted": 3, "skipped": 0, "next": None}
    assert await page(client, root) == ""
