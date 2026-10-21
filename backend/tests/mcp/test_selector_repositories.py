"""MCP's repositories by selector permissions (spec 10): a repository a selector names is
listed to whoever holds it, through the route the tool calls."""

from megooarti.security import roles
from megooarti.security.models import ContentSelector
from tests.mcp.conftest import structured


async def test_an_agent_lists_the_repositories_its_selectors_reach(
    agent, files, make_user, make_token, db
):
    db.add(ContentSelector(name="acme", expression='path =^ "/acme/"'))
    await roles.create_role(db, "acme", "", ["selector:acme:raw:files:browse"], [])
    await db.commit()
    token = await make_token(await make_user("kim", roles=["acme"]))

    async with agent(token) as client:
        listed = structured(await client.call_tool("list_repositories", {}))

    assert [found["name"] for found in listed["items"]] == ["files"]
