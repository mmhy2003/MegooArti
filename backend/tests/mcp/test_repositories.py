"""The repository tools (MCP spec 6.1): `list_repositories` and `repository_details`.
What the content routes give anyone who may browse; settings and a proxy's state only to
those who may read them."""

import pytest

from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured

REMOTE = "http://remote.test/maven2"
SECRET = "the-remote-password"


@pytest.fixture
async def repositories(client, make_user, fake_remote):
    """`releases` (Maven, hosted), `central` (Maven, a proxy that signs in to its
    remote), `maven-public` (a group of both) and `nuget-hosted`. Gives the
    administrator who made them."""
    administrator = await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    for made in [
        {"name": "releases", "format": "maven", "type": "hosted"},
        {
            "name": "central",
            "format": "maven",
            "type": "proxy",
            "proxy": {
                "remote_url": REMOTE,
                "remote_auth": {"type": "basic", "username": "robot", "secret": SECRET},
            },
        },
        {
            "name": "maven-public",
            "format": "maven",
            "type": "group",
            "group": {"members": ["releases", "central"]},
        },
        {"name": "nuget-hosted", "format": "nuget", "type": "hosted"},
    ]:
        answer = await client.post("/api/v1/repositories", json=made, headers=root)
        assert answer.status_code == 201, answer.text
    return administrator


async def test_an_administrator_lists_every_repository_and_each_proxys_remote(
    agent, repositories, make_token
):
    token = await make_token(repositories)

    async with agent(token) as client:
        every = structured(await client.call_tool("list_repositories", {}))
        proxies = structured(await client.call_tool("list_repositories", {"type": "proxy"}))
        nuget = structured(await client.call_tool("list_repositories", {"format": "nuget"}))

    assert [(one["name"], one["type"]) for one in every["items"]] == [
        ("central", "proxy"),
        ("maven-public", "group"),
        ("nuget-hosted", "hosted"),
        ("releases", "hosted"),
    ]
    shown = {one["name"]: one for one in every["items"]}
    assert shown["central"]["remote"] == {"url": REMOTE, "blocked": False}
    assert shown["releases"]["remote"] is None
    assert shown["releases"]["url"] == "https://test/repository/releases/"
    assert shown["releases"]["online"] is True
    assert [one["name"] for one in proxies["items"]] == ["central"]
    assert [one["name"] for one in nuget["items"]] == ["nuget-hosted"]


async def test_a_token_that_may_browse_some_sees_those_and_no_settings(
    agent, repositories, make_token
):
    scopes = ["repository:maven:releases:browse", "repository:maven:maven-public:browse"]
    token = await make_token(repositories, "some", scopes=scopes)

    async with agent(token) as client:
        listed = structured(await client.call_tool("list_repositories", {}))
        group = structured(await client.call_tool("repository_details", {"name": "maven-public"}))
        hidden = await client.call_tool("repository_details", {"name": "central"})

    assert [one["name"] for one in listed["items"]] == ["maven-public", "releases"]
    assert all(one["remote"] is None for one in listed["items"])
    assert group["members"] == ["releases"]  # not central, which it may not browse
    assert (group["settings"], group["status"]) == (None, None)
    assert refusal(hidden).endswith("forbidden: You do not have permission to do this.")


async def test_a_repositorys_details_say_how_a_client_is_set_up_to_use_it(
    agent, repositories, make_token
):
    token = await make_token(repositories)

    async with agent(token) as client:
        said = structured(await client.call_tool("repository_details", {"name": "nuget-hosted"}))

    assert said["url"] == "https://test/repository/nuget-hosted/"
    labels = [one["label"] for one in said["setup"]]
    assert labels[:2] == ["dotnet", "nuget.config"]
    config = said["setup"][1]
    assert config["language"] == "xml"
    assert "https://test/repository/nuget-hosted/index.json" in config["text"]
    assert said["settings"]["hosted"]["deployment_policy"] == "disable_redeploy"


async def test_a_proxys_details_are_its_settings_without_its_secret_and_its_last_error(
    agent, repositories, make_token, fake_remote, client
):
    fake_remote.down = True
    failed = await client.get(
        "/repository/central/com/acme/app/1.0/app-1.0.jar", headers=basic("root", PASSWORD)
    )
    assert failed.status_code == 502
    token = await make_token(repositories)

    async with agent(token) as agent_client:
        result = await agent_client.call_tool("repository_details", {"name": "central"})

    said = structured(result)
    assert said["settings"]["proxy"]["remote_url"] == REMOTE
    assert said["settings"]["proxy"]["remote_auth"] == {
        "type": "basic",
        "username": "robot",
        "has_secret": True,
    }
    assert SECRET not in str(result.content) + str(result.structured_content)
    assert said["status"]["failures"] == 1
    assert said["status"]["blocked"] is False
    assert said["status"]["last_error_untrusted"]


async def test_a_repository_there_is_not_is_not_found(agent, repositories, make_token):
    token = await make_token(repositories)

    async with agent(token) as client:
        missing = await client.call_tool("repository_details", {"name": "nowhere"})

    assert refusal(missing).endswith("not_found: No such repository.")


async def test_a_repositorys_setup_is_what_the_rest_api_gives(
    agent, repositories, make_token, client
):
    token = await make_token(repositories)
    rest = await client.get(
        "/api/v1/content/nuget-hosted", headers={"Authorization": f"Bearer {token}"}
    )

    async with agent(token) as agent_client:
        said = structured(
            await agent_client.call_tool("repository_details", {"name": "nuget-hosted"})
        )

    assert said["setup"] == rest.json()["setup"]
    assert (said["url"], said["members"]) == (rest.json()["url"], rest.json()["members"])
