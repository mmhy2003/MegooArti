"""Deleting content through MCP (spec 6.2): a version of a package, a file, a folder;
shown to whoever may delete in some repository, refused where they may not."""

import pytest

from megooarti.repositories import service
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured
from tests.repositories.maven.conftest import create

DELETES = {"delete_component", "delete_path"}


@pytest.fixture
async def content(client, db, make_user):
    """`files` (raw) with `top.txt`, `docs/a.txt`, `docs/b.txt` and `docs/sub/c.txt`;
    `releases` (Maven) with com.acme:app 1.0 and 2.0. Gives the administrator."""
    administrator = await make_user("root", roles=["admin"])
    await service.create_repository(
        db,
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=None,
        proxy=None,
        group=None,
        format_config={},
    )
    await create(db, "releases")
    root = basic("root", PASSWORD)
    for path in ["top.txt", "docs/a.txt", "docs/b.txt", "docs/sub/c.txt"]:
        assert (
            await client.put(f"/repository/files/{path}", content=b"x", headers=root)
        ).is_success
    for version in ("1.0", "2.0"):
        stem = f"/repository/releases/com/acme/app/{version}/app-{version}"
        assert (await client.put(f"{stem}.jar", content=b"PK", headers=root)).is_success
        assert (await client.put(f"{stem}.pom", content=b"<project/>", headers=root)).is_success
    return administrator


@pytest.fixture
async def token(content, make_token):
    return await make_token(content)


async def test_the_deletes_are_shown_to_whoever_may_delete_in_some_repository(
    agent, content, make_user, make_token, db
):
    await roles.create_role(db, "files-deleters", "", ["repository:raw:files:delete"], [])
    await db.commit()
    deleter = await make_token(await make_user("dana", roles=["files-deleters"]))
    reader = await make_token(content, "reads", scopes=["repository:*:*:read"])

    async with agent(deleter) as client:
        theirs = {listed.name for listed in (await client.list_tools()).tools}
    async with agent(reader) as client:
        readers = {listed.name for listed in (await client.list_tools()).tools}

    assert theirs >= DELETES
    assert readers & DELETES == set()


async def test_a_file_and_a_folder_with_all_under_it_are_deleted(agent, token):
    async with agent(token) as client:
        file = structured(
            await client.call_tool("delete_path", {"repository": "files", "path": "top.txt"})
        )
        folder = structured(
            await client.call_tool("delete_path", {"repository": "files", "path": "docs"})
        )
        missing = await client.call_tool("delete_path", {"repository": "files", "path": "docs"})
        left = structured(await client.call_tool("browse", {"repository": "files"}))

    assert file == {"repository": "files", "deleted": 1, "skipped": 0}
    assert folder == {"repository": "files", "deleted": 3, "skipped": 0}
    assert refusal(missing).endswith("not_found: No such file or folder.")
    assert left["items"] == []


async def test_a_version_of_a_package_is_deleted_by_its_name_and_the_others_stay(agent, token):
    async with agent(token) as client:
        deleted = structured(
            await client.call_tool(
                "delete_component",
                {
                    "repository": "releases",
                    "namespace": "com.acme",
                    "name": "app",
                    "version": "1.0",
                },
            )
        )
        versions = structured(
            await client.call_tool(
                "package_versions", {"format": "maven", "namespace": "com.acme", "name": "app"}
            )
        )
        again = await client.call_tool(
            "delete_component",
            {"repository": "releases", "namespace": "com.acme", "name": "app", "version": "1.0"},
        )

    assert deleted == {"repository": "releases", "deleted": 2, "skipped": 0}
    assert [one["version"] for one in versions["versions"]["items"]] == ["2.0"]
    assert refusal(again).endswith("not_found: No such component.")


async def test_a_delete_where_the_caller_may_not_delete_is_refused(
    agent, content, token, make_user, make_token, db
):
    await roles.create_role(db, "files-deleters", "", ["repository:raw:files:delete"], [])
    await roles.create_role(db, "maven-readers", "", ["repository:maven:releases:browse"], [])
    await db.commit()
    dana = await make_token(await make_user("dana", roles=["files-deleters", "maven-readers"]))

    async with agent(dana) as client:
        refused = await client.call_tool(
            "delete_path", {"repository": "releases", "path": "com/acme/app/1.0/app-1.0.jar"}
        )
    async with agent(token) as client:
        outside = await client.call_tool(
            "delete_path", {"repository": "files", "path": "docs/../../etc"}
        )

    assert refusal(refused).endswith("forbidden: You do not have permission to do this.")
    assert refusal(outside).endswith(
        "invalid_path: The path is not valid: it has an empty, '.' or '..' segment."
    )


async def test_a_folder_is_deleted_whatever_slashes_it_is_written_with_but_never_the_root(
    agent, token
):
    async with agent(token) as client:
        trailing = structured(
            await client.call_tool("delete_path", {"repository": "files", "path": "docs/sub/"})
        )
        leading = structured(
            await client.call_tool("delete_path", {"repository": "files", "path": "/docs"})
        )
        root = await client.call_tool("delete_path", {"repository": "files", "path": "/"})
        left = structured(await client.call_tool("browse", {"repository": "files"}))

    assert (trailing["deleted"], leading["deleted"]) == (1, 2)
    assert refusal(root).endswith(
        "- path: Give a file or a folder. To delete everything, delete the repository."
    )
    assert [item["name"] for item in left["items"]] == ["top.txt"]
