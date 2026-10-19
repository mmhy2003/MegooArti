"""Connected apps (MCP spec 7.6): the applications a user let sign in as them with OAuth,
listed and revoked by the user, by an administrator, and by an agent that may."""

from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured
from tests.mcp.oauth_steps import LIST_TOOLS, MCP, approved_code, tokens


async def test_a_user_sees_what_they_connected_and_revokes_it(client, browser, make_token):
    client_id, code = await approved_code(client, browser)
    access = (await tokens(client, client_id, code))["access_token"]

    listed = await browser.get("/api/v1/me/connected-apps")
    (app,) = listed.json()["items"]
    revoked = await browser.delete(f"/api/v1/me/connected-apps/{app['id']}")
    again = await browser.delete(f"/api/v1/me/connected-apps/{app['id']}")
    after = await client.post(
        "/mcp", json=LIST_TOOLS, headers=MCP | {"Authorization": f"Bearer {access}"}
    )

    assert (app["client"], app["redirect_host"]) == ("Claude", "127.0.0.1")
    assert app["scopes"] == ["repository:*:*:browse", "repository:*:*:read", "admin:*:read"]
    assert app["expires_at"] is not None and app["last_used_at"] is None
    assert revoked.status_code == 204
    assert again.status_code == 404
    assert after.status_code == 401
    assert (await browser.get("/api/v1/me/connected-apps")).json()["items"] == []


async def test_only_a_person_signed_in_lists_their_connected_apps(
    client, browser, make_user, make_token
):
    token = await make_token(await make_user("other"))

    by_token = await client.get(
        "/api/v1/me/connected-apps", headers={"Authorization": f"Bearer {token}"}
    )

    assert by_token.status_code == 403


async def test_an_administrator_sees_and_revokes_a_users_connected_apps(
    client, browser, make_user, sessionmaker
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    await approved_code(client, browser)
    users = (await client.get("/api/v1/users", headers=root)).json()["items"]
    dev = next(user for user in users if user["username"] == "dev")

    listed = await client.get(f"/api/v1/users/{dev['id']}/connected-apps", headers=root)
    (app,) = listed.json()["items"]
    revoked = await client.delete(
        f"/api/v1/users/{dev['id']}/connected-apps/{app['id']}", headers=root
    )

    assert revoked.status_code == 204
    assert (await client.get(f"/api/v1/users/{dev['id']}/connected-apps", headers=root)).json()[
        "items"
    ] == []


async def test_an_agent_that_may_sees_a_users_connected_apps_and_revokes_one(
    client, browser, agent, make_user, make_token
):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    await approved_code(client, browser)

    async with agent(token) as session:
        details = structured(await session.call_tool("user_details", {"username": "dev"}))
        (app,) = details["connected_apps"]
        revoked = structured(
            await session.call_tool("revoke_token", {"username": "dev", "connected_app": app["id"]})
        )
        neither = await session.call_tool("revoke_token", {"username": "dev"})
        after = structured(await session.call_tool("user_details", {"username": "dev"}))

    assert app["client"] == "Claude"
    assert revoked == {"deleted": app["id"]}
    assert refusal(neither).endswith("- token: Give a token's name, or a connected app's id.")
    assert after["connected_apps"] == []
