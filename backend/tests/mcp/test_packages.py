"""The package tools (MCP spec 6.1): `search_packages`, `package_versions`,
`package_details` and `browse`, each answering as the REST route beside it does."""

import hashlib

import pytest

from megooarti.mcp import packages
from megooarti.repositories.formats import get_format
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured
from tests.repositories.maven.conftest import REMOTE, create

FOLDER = "com/acme/app"
PUSHED = ["1.0", "1.9", "1.10", "2.0-beta-1"]
FETCHED = b"PK\x03\x04 the remote's 1.9"


def jar(version: str) -> bytes:
    return f"PK\x03\x04 app {version}".encode()


@pytest.fixture
async def maven(app, client, db, make_user, fake_remote):
    """`releases` (hosted) with com.acme:app 1.0, 1.9, 1.10 and 2.0-beta-1 and
    org.other:app 3.0; `central` (a proxy) that has fetched com.acme:app 1.9. Gives the
    administrator who put them there."""
    await create(db, "releases")
    await create(db, "central", type="proxy", proxy={"remote_url": REMOTE})
    administrator = await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    for version in PUSHED:
        stem = f"/repository/releases/{FOLDER}/{version}/app-{version}"
        assert (await client.put(f"{stem}.jar", content=jar(version), headers=root)).is_success
        assert (await client.put(f"{stem}.pom", content=b"<project/>", headers=root)).is_success
    other = "/repository/releases/org/other/app/3.0/app-3.0.jar"
    assert (await client.put(other, content=b"PK other", headers=root)).is_success
    fake_remote.files[f"maven2/{FOLDER}/1.9/app-1.9.jar"] = FETCHED
    fetched = await client.get(f"/repository/central/{FOLDER}/1.9/app-1.9.jar", headers=root)
    assert fetched.content == FETCHED
    return administrator


@pytest.fixture
async def token(make_user, make_token):
    """An API token of a user who may do everything."""
    return await make_token(await make_user("dana", roles=["admin"]))


async def test_a_search_finds_packages_a_page_at_a_time(agent, maven, token):
    async with agent(token) as client:
        first = structured(await client.call_tool("search_packages", {"words": "acme", "limit": 2}))
        rest = structured(
            await client.call_tool(
                "search_packages", {"words": "acme", "limit": 50, "cursor": first["next_cursor"]}
            )
        )

    assert first["total"] == 5  # four pushed, one fetched
    assert len(first["items"]) == 2
    assert first["truncated"] is False
    assert rest["next_cursor"] is None
    found = first["items"] + rest["items"]
    assert sorted((item["repository"], item["version"]) for item in found) == sorted(
        [("releases", version) for version in PUSHED] + [("central", "1.9")]
    )
    assert {(item["format"], item["namespace"], item["name"]) for item in found} == {
        ("maven", "com.acme", "app")
    }


async def test_a_search_by_checksum_finds_the_package_a_file_belongs_to(agent, maven, token):
    sha256 = hashlib.sha256(FETCHED).hexdigest()

    async with agent(token) as client:
        found = structured(await client.call_tool("search_packages", {"checksum": sha256}))
        wrong = await client.call_tool("search_packages", {"checksum": "abc"})

    assert [(item["repository"], item["version"]) for item in found["items"]] == [
        ("central", "1.9")
    ]
    assert refusal(wrong).endswith(
        "validation_error: The request is not valid.\n"
        "- checksum: A checksum is 32, 40, 64 or 128 hexadecimal digits."
    )


async def test_a_cursor_that_no_list_gave_is_refused(agent, maven, token):
    async with agent(token) as client:
        refused = await client.call_tool("search_packages", {"cursor": "not-one"})

    assert refusal(refused).endswith("- cursor: Not a cursor a list gave.")


async def test_a_search_finds_only_what_the_token_may_browse(agent, maven, make_token):
    narrowed = await make_token(maven, "central-only", scopes=["repository:maven:central:*"])

    async with agent(narrowed) as client:
        found = structured(await client.call_tool("search_packages", {"words": "app"}))

    assert {item["repository"] for item in found["items"]} == {"central"}


async def test_a_packages_versions_are_the_newest_first_with_where_each_is(agent, maven, token):
    async with agent(token) as client:
        said = structured(
            await client.call_tool(
                "package_versions", {"format": "maven", "namespace": "com.acme", "name": "app"}
            )
        )

    versions = said["versions"]["items"]
    assert [one["version"] for one in versions] == ["2.0-beta-1", "1.10", "1.9", "1.0"]
    assert [one["prerelease"] for one in versions] == [True, False, False, False]
    assert versions[2]["repositories"] == [
        {"repository": "central", "type": "proxy"},
        {"repository": "releases", "type": "hosted"},
    ]
    assert said["newest_release"] == "1.10"
    assert (said["namespace"], said["incomplete"]) == ("com.acme", False)


async def test_versions_without_a_namespace_that_several_have_ask_for_one(agent, maven, token):
    async with agent(token) as client:
        refused = await client.call_tool("package_versions", {"format": "maven", "name": "app"})
        unknown = await client.call_tool("package_versions", {"format": "cobol", "name": "app"})

    assert refusal(refused).endswith(
        "- namespace: There are packages named app in more than one: com.acme, org.other."
    )
    assert refusal(unknown).endswith("- format: No such format.")


async def test_versions_of_a_format_without_an_order_are_the_last_pushed_first(
    agent, maven, token, monkeypatch
):
    monkeypatch.setattr(type(get_format("maven")), "ordered_versions", lambda self, texts: None)

    async with agent(token) as client:
        said = structured(
            await client.call_tool(
                "package_versions", {"format": "maven", "namespace": "com.acme", "name": "app"}
            )
        )

    # 1.9 was fetched last of all, then 2.0-beta-1 was pushed last.
    assert [one["version"] for one in said["versions"]["items"]] == [
        "1.9",
        "2.0-beta-1",
        "1.10",
        "1.0",
    ]
    assert said["newest_release"] is None


async def test_a_versions_details_are_its_files_and_how_a_project_uses_it(agent, maven, token):
    async with agent(token) as client:
        by_name = structured(
            await client.call_tool(
                "package_details",
                {
                    "repository": "releases",
                    "namespace": "com.acme",
                    "name": "app",
                    "version": "1.10",
                },
            )
        )
        by_id = structured(
            await client.call_tool(
                "package_details", {"repository": "releases", "component_id": by_name["id"]}
            )
        )

    assert by_id == by_name
    assert (by_name["format"], by_name["version"], by_name["truncated"]) == ("maven", "1.10", False)
    files = {file["path"]: file for file in by_name["files"]}
    pushed = files[f"{FOLDER}/1.10/app-1.10.jar"]
    assert pushed["sha256"] == hashlib.sha256(jar("1.10")).hexdigest()
    assert pushed["size"] == len(jar("1.10"))
    assert pushed["download"] == f"https://test/repository/releases/{FOLDER}/1.10/app-1.10.jar"
    maven_usage = next(one for one in by_name["usage"] if one["label"] == "Maven")
    assert "<artifactId>app</artifactId>" in maven_usage["text"]
    assert "<version>1.10</version>" in maven_usage["text"]


async def test_details_of_a_version_there_is_not_or_of_nothing_named_are_refused(
    agent, maven, token
):
    async with agent(token) as client:
        missing = await client.call_tool(
            "package_details", {"repository": "releases", "name": "app", "version": "9.9"}
        )
        unnamed = await client.call_tool("package_details", {"repository": "releases"})
        elsewhere = await client.call_tool(
            "package_details", {"repository": "nowhere", "name": "app", "version": "1.0"}
        )

    assert refusal(missing).endswith("not_found: No such component.")
    assert refusal(unnamed).endswith(
        "- component_id: Give `component_id`, or `name` and `version`."
    )
    assert refusal(elsewhere).endswith("not_found: No such repository.")


async def test_browse_walks_a_repositorys_folders_to_a_versions_files(agent, maven, token):
    async with agent(token) as client:
        top = structured(await client.call_tool("browse", {"repository": "releases"}))
        version = structured(
            await client.call_tool("browse", {"repository": "releases", "path": f"{FOLDER}/1.10"})
        )
        paged = structured(
            await client.call_tool(
                "browse", {"repository": "releases", "path": f"{FOLDER}", "limit": 1}
            )
        )

    assert [(item["name"], item["kind"]) for item in top["items"]] == [
        ("com", "folder"),
        ("org", "folder"),
    ]
    jar_entry = next(item for item in version["items"] if item["name"] == "app-1.10.jar")
    assert jar_entry["component"]["version"] == "1.10"
    assert len(paged["items"]) == 1
    assert paged["next_cursor"] is not None


async def test_a_search_finds_what_the_rest_api_finds_for_the_same_token(
    agent, maven, make_token, client
):
    narrowed = await make_token(maven, "central-only", scopes=["repository:maven:central:*"])
    rest = await client.get(
        "/api/v1/search", params={"q": "app"}, headers={"Authorization": f"Bearer {narrowed}"}
    )

    async with agent(narrowed) as agent_client:
        found = structured(await agent_client.call_tool("search_packages", {"words": "app"}))

    assert [item["id"] for item in found["items"]] == [item["id"] for item in rest.json()["items"]]
    assert found["total"] == rest.json()["total"]


async def test_what_anyone_may_browse_is_found_whatever_the_tokens_scopes(
    agent, maven, make_token, db
):
    # A token's scopes narrow what its owner may do; what is public stays public.
    await set_setting(db, "anonymous_access", {"enabled": True})
    await roles.create_role(db, "public", "", ["repository:maven:releases:browse"], [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await db.commit()
    narrowed = await make_token(maven, "central-only", scopes=["repository:maven:central:*"])

    async with agent(narrowed) as client:
        found = structured(await client.call_tool("search_packages", {"words": "app"}))

    assert {item["repository"] for item in found["items"]} == {"central", "releases"}


async def test_browse_refuses_a_group_and_a_path_out_of_the_repository(agent, maven, token, db):
    await create(db, "maven-public", type="group", group={"members": ["releases"]})

    async with agent(token) as client:
        group = await client.call_tool("browse", {"repository": "maven-public"})
        outside = await client.call_tool(
            "browse", {"repository": "releases", "path": "com/../../etc"}
        )

    assert refusal(group).endswith(
        "not_browsable: A group holds nothing of its own. Browse its members."
    )
    assert refusal(outside).endswith(
        "invalid_path: The path is not valid: it has an empty, '.' or '..' segment."
    )


async def test_versions_past_the_copies_that_are_read_say_they_are_incomplete(
    agent, maven, token, monkeypatch
):
    monkeypatch.setattr(packages, "_COPIES_MOST", 3)

    async with agent(token) as client:
        said = structured(
            await client.call_tool(
                "package_versions", {"format": "maven", "namespace": "com.acme", "name": "app"}
            )
        )

    assert said["incomplete"] is True
