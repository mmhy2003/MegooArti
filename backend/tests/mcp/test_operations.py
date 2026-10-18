"""Running repositories through MCP (spec 6.2): making, changing and deleting them,
clearing a proxy's cache, and going through an index again; shown only to whoever may
change repositories."""

import pytest
import structlog

from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured

OPERATIONS = {
    "create_repository",
    "update_repository",
    "delete_repository",
    "invalidate_proxy_cache",
    "rebuild_search_index",
}
SECRET = "the-remote-password"


@pytest.fixture
async def administrator(make_user):
    return await make_user("root", roles=["admin"])


@pytest.fixture
async def token(administrator, make_token):
    return await make_token(administrator)


async def test_the_operations_are_shown_only_to_whoever_may_change_repositories(
    agent, administrator, make_user, make_token
):
    plain = await make_token(await make_user("dev"))
    reading = await make_token(administrator, "reads", scopes=["admin:*:read", "repository:*"])
    writing = await make_token(administrator, "writes")

    shown = {}
    for name, token in (("plain", plain), ("reading", reading), ("writing", writing)):
        async with agent(token) as client:
            shown[name] = {listed.name for listed in (await client.list_tools()).tools}

    assert shown["plain"] & OPERATIONS == set()
    assert shown["reading"] & OPERATIONS == set()
    assert shown["writing"] >= OPERATIONS


async def test_what_each_operation_says_of_itself(agent, token):
    async with agent(token) as client:
        hints = {
            listed.name: listed.annotations
            for listed in (await client.list_tools()).tools
            if listed.name in OPERATIONS
        }

    assert hints["delete_repository"].destructive_hint is True
    assert hints["create_repository"].idempotent_hint is False
    assert all(not hint.read_only_hint for hint in hints.values())
    assert all(hints[name].idempotent_hint for name in OPERATIONS - {"create_repository"})


async def test_a_proxy_is_made_of_its_formats_public_repository_unless_one_is_given(agent, token):
    async with agent(token) as client:
        central = structured(
            await client.call_tool(
                "create_repository", {"name": "central", "format": "maven", "type": "proxy"}
            )
        )
        choco = structured(
            await client.call_tool(
                "create_repository",
                {
                    "name": "choco",
                    "format": "nuget",
                    "type": "proxy",
                    "format_config": {"protocol": "v2"},
                },
            )
        )
        own = structured(
            await client.call_tool(
                "create_repository",
                {
                    "name": "mirror",
                    "format": "npm",
                    "type": "proxy",
                    "proxy": {"remote_url": "https://npm.example.org/", "blocked": True},
                },
            )
        )
        yum = await client.call_tool(
            "create_repository", {"name": "rocky", "format": "yum", "type": "proxy"}
        )

    assert central["proxy"]["remote_url"] == "https://repo1.maven.org/maven2"
    # As the server keeps a remote: without the slash at its end.
    assert choco["proxy"]["remote_url"] == "https://community.chocolatey.org/api/v2"
    assert (own["proxy"]["remote_url"], own["proxy"]["blocked"]) == (
        "https://npm.example.org",
        True,
    )
    assert refusal(yum).endswith(
        "- proxy.remote_url: This format has no public repository: give the remote's."
    )


async def test_hosted_repositories_and_groups_are_made_as_the_rest_api_makes_them(
    agent, token, client
):
    async with agent(token) as agent_client:
        hosted = structured(
            await agent_client.call_tool(
                "create_repository", {"name": "releases", "format": "maven", "type": "hosted"}
            )
        )
        group = structured(
            await agent_client.call_tool(
                "create_repository",
                {
                    "name": "maven-public",
                    "format": "maven",
                    "type": "group",
                    "members": ["releases"],
                },
            )
        )
        again = await agent_client.call_tool(
            "create_repository", {"name": "releases", "format": "maven", "type": "hosted"}
        )
        wrong = await agent_client.call_tool(
            "create_repository", {"name": "x", "format": "maven", "type": "mirror"}
        )

    assert hosted["hosted"]["deployment_policy"] == "disable_redeploy"  # releases, Maven's own
    assert group["group"]["members"] == ["releases"]
    rest = await client.get("/api/v1/repositories/maven-public", headers=basic("root", PASSWORD))
    assert rest.json() == group
    assert "conflict" in refusal(again)
    assert "type" in refusal(wrong)


@pytest.fixture
async def proxied(client, administrator):
    """`central`, a Maven proxy that signs in to its remote, and `releases`, hosted."""
    root = basic("root", PASSWORD)
    for made in [
        {
            "name": "central",
            "format": "maven",
            "type": "proxy",
            "proxy": {
                "remote_url": "http://remote.test/maven2",
                "remote_auth": {"type": "basic", "username": "robot", "secret": SECRET},
            },
        },
        {"name": "releases", "format": "maven", "type": "hosted"},
    ]:
        assert (
            await client.post("/api/v1/repositories", json=made, headers=root)
        ).status_code == 201


async def test_what_is_not_given_to_a_change_stays_as_it_is_the_secret_too(
    agent, token, proxied, sessionmaker
):
    async with agent(token) as client:
        blocked = structured(
            await client.call_tool(
                "update_repository", {"name": "central", "proxy": {"blocked": True}}
            )
        )
        offline = structured(
            await client.call_tool("update_repository", {"name": "releases", "online": False})
        )
        missing = await client.call_tool("update_repository", {"name": "nowhere", "online": True})

    assert blocked["proxy"]["blocked"] is True
    assert blocked["proxy"]["remote_url"] == "http://remote.test/maven2"
    assert blocked["proxy"]["remote_auth"] == {
        "type": "basic",
        "username": "robot",
        "has_secret": True,
    }
    assert offline["online"] is False
    assert offline["hosted"]["deployment_policy"] == "disable_redeploy"
    assert refusal(missing).endswith("not_found: No such repository.")


async def test_a_groups_members_are_changed_all_at_once_in_their_order(agent, token, proxied):
    async with agent(token) as client:
        made = structured(
            await client.call_tool(
                "create_repository",
                {"name": "all", "format": "maven", "type": "group", "members": ["releases"]},
            )
        )
        changed = structured(
            await client.call_tool(
                "update_repository", {"name": "all", "members": ["central", "releases"]}
            )
        )

    assert made["group"]["members"] == ["releases"]
    assert changed["group"]["members"] == ["central", "releases"]


async def test_a_proxys_cache_is_cleared_an_index_gone_through_and_a_repository_deleted(
    agent, token, proxied, client
):
    async with agent(token) as agent_client:
        cleared = structured(
            await agent_client.call_tool("invalidate_proxy_cache", {"name": "central"})
        )
        rebuilt = structured(
            await agent_client.call_tool("rebuild_search_index", {"name": "releases"})
        )
        deleted = structured(
            await agent_client.call_tool("delete_repository", {"name": "releases"})
        )
        again = await agent_client.call_tool("delete_repository", {"name": "releases"})

    assert cleared == {"repository": "central", "done": "invalidated"}
    assert rebuilt == {"files": 0, "moved": 0, "components": 0, "removed": 0}
    assert deleted == {"repository": "releases", "done": "deleted"}
    assert refusal(again).endswith("not_found: No such repository.")
    gone = await client.get("/api/v1/repositories/releases", headers=basic("root", PASSWORD))
    assert gone.status_code == 404


async def test_an_operation_a_caller_may_not_do_is_no_tool_of_theirs(agent, make_user, make_token):
    token = await make_token(await make_user("dev"))

    async with agent(token) as client:
        refused = await client.call_tool(
            "create_repository", {"name": "mine", "format": "raw", "type": "hosted"}
        )

    assert refusal(refused) == "Unknown tool: create_repository"


async def test_no_password_or_secret_given_to_a_tool_is_written_to_the_log(agent, token):
    with structlog.testing.capture_logs() as logs:
        async with agent(token) as client:
            await client.call_tool(
                "create_user",
                {"username": "dev", "display_name": "Dev", "password": "the-users-password-1"},
            )
            await client.call_tool(
                "create_repository",
                {
                    "name": "private",
                    "format": "npm",
                    "type": "proxy",
                    "proxy": {
                        "remote_url": "https://npm.example.org",
                        "remote_auth": {"type": "basic", "username": "robot", "secret": "basic-1"},
                    },
                },
            )
            await client.call_tool(
                "update_repository",
                {
                    "name": "private",
                    "proxy": {"remote_auth": {"type": "bearer", "secret": "bearer-1"}},
                },
            )

    written = str(logs)
    calls = [entry for entry in logs if entry["event"] == "mcp_tool_called"]
    assert [entry["outcome"] for entry in calls] == ["ok", "ok", "ok"]
    for secret in ("the-users-password-1", "basic-1", "bearer-1"):
        assert secret not in written
    assert calls[0]["arguments"]["password"] == "[redacted]"
    assert calls[2]["arguments"]["proxy"]["remote_auth"] == {
        "type": "bearer",
        "secret": "[redacted]",
    }


async def test_a_token_that_may_only_read_calls_an_operation_by_its_name_in_vain(
    agent, administrator, make_token
):
    reading = await make_token(administrator, "reads", scopes=["admin:*:read", "repository:*"])

    async with agent(reading) as client:
        refused = await client.call_tool(
            "create_repository", {"name": "mine", "format": "raw", "type": "hosted"}
        )

    assert refusal(refused) == "Unknown tool: create_repository"


async def test_the_server_tells_an_agent_what_the_tools_that_change_things_are_for(agent, token):
    async with agent(token) as client:
        instructions = client.instructions or ""

    assert "administer users, their tokens and roles" in instructions
    assert "asks you before" in instructions
