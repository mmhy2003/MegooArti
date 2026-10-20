"""MCP's changes in the audit log (spec 9): recorded by the routes the tools call, as the
token's user, and as `oauth` for an application a person approved; and OAuth's own
changes: a client registered, an approval given and revoked."""

from tests.audit import last
from tests.mcp.conftest import structured
from tests.mcp.oauth_steps import approved_code, tokens

ROLE = {"name": "ops", "description": "", "permissions": [], "roles": []}


async def test_a_tools_change_is_recorded_as_its_tokens_user(
    agent, make_user, make_token, sessionmaker
):
    token = await make_token(await make_user("root", roles=["admin"]))

    async with agent(token) as client:
        structured(await client.call_tool("create_role", ROLE))

    made = await last(sessionmaker, "role.created")
    assert (made.actor, made.method, made.target_name) == ("root", "token", "ops")


async def test_an_approved_applications_change_is_recorded_as_oauth(
    agent, client, browser, sessionmaker
):
    client_id, code = await approved_code(client, browser, access="all")
    access = (await tokens(client, client_id, code))["access_token"]

    async with agent(access) as mcp:
        structured(await mcp.call_tool("create_role", ROLE))

    made = await last(sessionmaker, "role.created")
    assert (made.actor, made.method) == ("dev", "oauth")


async def test_a_client_registered_and_an_approval_given_and_revoked_are_recorded(
    client, browser, sessionmaker
):
    client_id, code = await approved_code(client, browser)
    (app,) = (await browser.get("/api/v1/me/connected-apps")).json()["items"]
    await browser.delete(f"/api/v1/me/connected-apps/{app['id']}")

    registered = await last(sessionmaker, "oauth_client.registered")
    approved = await last(sessionmaker, "connected_app.approved")
    revoked = await last(sessionmaker, "connected_app.revoked")
    assert (registered.actor, registered.target_name) == (None, "Claude")
    assert registered.changes == {
        "redirect_uris": {"before": None, "after": ["http://127.0.0.1:33418/callback"]}
    }
    assert (approved.actor, approved.target_name) == ("dev", "dev/Claude")
    assert approved.changes == {
        "access": {"before": None, "after": "read"},
        "lasts": {"before": None, "after": "30d"},
    }
    assert (revoked.actor, revoked.target_name) == ("dev", "dev/Claude")
