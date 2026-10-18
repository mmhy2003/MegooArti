"""`whoami` and `system_status` (MCP spec 6.1): who an agent acts as, and how the server is."""

from datetime import timedelta

from megooarti import __version__
from megooarti.clock import utcnow
from tests.mcp.conftest import structured


async def test_whoami_is_the_user_and_the_token_that_narrows_what_they_may_do(
    agent, make_user, make_token
):
    expires = utcnow() + timedelta(days=30)
    token = await make_token(
        await make_user("dev"), "laptop", scopes=["repository:*:*:read"], expires_at=expires
    )

    async with agent(token) as client:
        said = structured(await client.call_tool("whoami", {}))

    assert said["username"] == "dev"
    assert said["roles"] == []
    assert said["permissions"] == []
    assert said["token"]["kind"] == "api_token"
    assert said["token"]["name"] == "laptop"
    assert token.startswith(said["token"]["prefix"])
    assert said["token"]["scopes"] == ["repository:*:*:read"]
    assert said["token"]["expires_at"].startswith(expires.isoformat()[:16])


async def test_whoami_of_an_administrator_with_a_token_of_no_scopes(agent, make_user, make_token):
    token = await make_token(await make_user("root", roles=["admin"]))

    async with agent(token) as client:
        said = structured(await client.call_tool("whoami", {}))

    assert (said["roles"], said["permissions"]) == (["admin"], ["*"])
    assert said["token"]["scopes"] is None
    assert said["token"]["expires_at"] is None


async def test_system_status_is_the_version_and_readiness_and_more_only_to_administrators(
    agent, make_user, make_token, files
):
    plain = await make_token(await make_user("dev"))
    admin = await make_token(await make_user("root", roles=["admin"]))

    async with agent(plain) as client:
        theirs = structured(await client.call_tool("system_status", {}))
    async with agent(admin) as client:
        ours = structured(await client.call_tool("system_status", {}))

    assert theirs == {
        "version": __version__,
        "ready": True,
        "database": "ok",
        "database_schema": "ok",
        "runtime": None,
        "blob_stores": None,
    }
    assert ours["runtime"]["database"].startswith("PostgreSQL ")
    assert "default" in [store["name"] for store in ours["blob_stores"]]


async def test_a_token_scoped_to_reading_content_sees_no_administration(
    agent, make_user, make_token
):
    token = await make_token(await make_user("root", roles=["admin"]), scopes=["repository:*"])

    async with agent(token) as client:
        said = structured(await client.call_tool("system_status", {}))

    assert (said["runtime"], said["blob_stores"]) == (None, None)


async def test_a_user_who_must_change_their_password_still_works_with_a_token(
    agent, make_user, make_token
):
    token = await make_token(await make_user("dev", must_change_password=True))

    async with agent(token) as client:
        said = structured(await client.call_tool("whoami", {}))

    assert said["username"] == "dev"
