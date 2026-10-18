"""Administering accounts through MCP (spec 6.2): users, their tokens, and roles, each
shown only to whoever holds its permission, each named as people name it."""

import pytest

from megooarti.security import roles
from tests.mcp.conftest import refusal, structured

READING = {"list_users", "user_details", "list_roles"}
WRITING = {
    "create_user",
    "update_user",
    "delete_user",
    "revoke_token",
    "create_role",
    "update_role",
    "delete_role",
}
MCP = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@pytest.fixture
async def administrator(make_user):
    return await make_user("root", roles=["admin"])


@pytest.fixture
async def token(administrator, make_token):
    return await make_token(administrator)


async def test_each_tool_is_shown_to_whoever_holds_its_permission(
    agent, administrator, make_user, make_token, db
):
    await roles.create_role(db, "user-readers", "", ["admin:users:read"], [])
    await db.commit()
    reader = await make_token(await make_user("dana", roles=["user-readers"]))
    everything = await make_token(administrator)

    async with agent(reader) as client:
        theirs = {listed.name for listed in (await client.list_tools()).tools}
    async with agent(everything) as client:
        ours = {listed.name for listed in (await client.list_tools()).tools}

    assert theirs & (READING | WRITING) == {"list_users", "user_details"}
    assert ours >= READING | WRITING


async def test_a_user_is_made_with_a_password_they_must_change_and_listed(agent, token):
    async with agent(token) as client:
        made = structured(
            await client.call_tool(
                "create_user",
                {
                    "username": "dev",
                    "display_name": "Dev",
                    "password": "a password of the right length",
                    "email": "dev@example.org",
                    "roles": ["admin"],
                },
            )
        )
        listed = structured(await client.call_tool("list_users", {}))
        wrong = await client.call_tool(
            "create_user", {"username": "no spaces", "display_name": "X", "password": "x" * 20}
        )

    assert (made["username"], made["must_change_password"], made["roles"]) == (
        "dev",
        True,
        ["admin"],
    )
    assert [user["username"] for user in listed["items"]] == ["admin", "anonymous", "dev", "root"]
    assert "username" in refusal(wrong)


async def test_a_user_is_changed_only_in_what_is_given(agent, token, make_user):
    await make_user("dev")

    async with agent(token) as client:
        changed = structured(
            await client.call_tool("update_user", {"username": "dev", "status": "disabled"})
        )
        renamed = structured(
            await client.call_tool("update_user", {"username": "dev", "display_name": "D. Ev"})
        )
        themselves = await client.call_tool(
            "update_user", {"username": "root", "status": "disabled"}
        )

    assert changed["status"] == "disabled"
    assert (renamed["status"], renamed["display_name"]) == ("disabled", "D. Ev")
    assert refusal(themselves).endswith("self_protected: You cannot disable your own account.")


async def test_a_users_tokens_are_shown_by_name_never_their_values_and_revoked(
    agent, token, make_user, make_token, client
):
    dev = await make_user("dev")
    theirs = await make_token(dev, "laptop")

    async with agent(token) as agent_client:
        details = structured(await agent_client.call_tool("user_details", {"username": "dev"}))
        revoked = structured(
            await agent_client.call_tool("revoke_token", {"username": "dev", "token": "laptop"})
        )
        missing = await agent_client.call_tool(
            "revoke_token", {"username": "dev", "token": "laptop"}
        )

    assert [one["name"] for one in details["tokens"]] == ["laptop"]
    assert theirs.startswith(details["tokens"][0]["display_prefix"])
    assert theirs not in str(details)
    assert revoked == {"deleted": "laptop"}
    assert refusal(missing).endswith("not_found: No such token.")
    after = await client.post(
        "/mcp", json=LIST_TOOLS, headers=MCP | {"Authorization": f"Bearer {theirs}"}
    )
    assert after.status_code == 401


async def test_who_may_read_users_but_not_tokens_is_not_shown_tokens(
    agent, administrator, make_user, make_token
):
    await make_user("dev")
    scoped = await make_token(administrator, "users-only", scopes=["admin:users:read"])

    async with agent(scoped) as client:
        details = structured(await client.call_tool("user_details", {"username": "dev"}))

    assert details["tokens"] is None


async def test_a_user_is_deleted_but_not_oneself(agent, token, make_user):
    await make_user("dev")

    async with agent(token) as client:
        gone = structured(await client.call_tool("delete_user", {"username": "dev"}))
        again = await client.call_tool("delete_user", {"username": "dev"})
        themselves = await client.call_tool("delete_user", {"username": "root"})

    assert gone == {"deleted": "dev"}
    assert refusal(again).endswith("not_found: No such user.")
    assert refusal(themselves).endswith("self_protected: You cannot delete your own account.")


async def test_a_role_is_made_changed_in_what_is_given_and_deleted(agent, token):
    async with agent(token) as client:
        made = structured(
            await client.call_tool(
                "create_role",
                {
                    "name": "maven-readers",
                    "description": "Read Maven",
                    "permissions": ["repository:maven:*:read"],
                },
            )
        )
        changed = structured(
            await client.call_tool(
                "update_role",
                {"name": "maven-readers", "permissions": ["repository:maven:*:browse"]},
            )
        )
        listed = structured(await client.call_tool("list_roles", {}))
        gone = structured(await client.call_tool("delete_role", {"name": "maven-readers"}))
        builtin = await client.call_tool("delete_role", {"name": "admin"})

    assert made["permissions"] == ["repository:maven:*:read"]
    assert (changed["description"], changed["permissions"]) == (
        "Read Maven",
        ["repository:maven:*:browse"],
    )
    assert "maven-readers" in [role["name"] for role in listed["items"]]
    assert gone == {"deleted": "maven-readers"}
    assert refusal(builtin).endswith("builtin_protected: Built-in roles cannot be deleted.")


async def test_the_last_administrator_is_not_taken_away(agent, token):
    async with agent(token) as client:
        refused = await client.call_tool("update_user", {"username": "root", "roles": []})
        role = await client.call_tool("update_role", {"name": "admin", "permissions": []})

    assert "last_administrator" in refusal(refused)
    assert refusal(role).endswith("builtin_protected: The admin role cannot be changed.")


async def test_a_token_is_revoked_by_its_name_however_many_its_user_has(
    agent, token, make_user, make_token
):
    dev = await make_user("dev")
    oldest = await make_token(dev, "the-first")
    for number in range(201):
        await make_token(dev, f"later-{number}")

    async with agent(token) as client:
        details = structured(await client.call_tool("user_details", {"username": "dev"}))
        revoked = structured(
            await client.call_tool("revoke_token", {"username": "dev", "token": "the-first"})
        )

    assert len(details["tokens"]) == 202
    assert revoked == {"deleted": "the-first"}
    assert oldest
