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


async def test_an_agent_that_may_delete_through_a_selector_is_shown_the_tools_that_delete(
    agent, files, make_user, make_token, db
):
    db.add(ContentSelector(name="acme", expression='path =^ "/acme/"'))
    await roles.create_role(db, "acme-deleters", "", ["selector:acme:raw:files:delete"], [])
    await db.commit()
    token = await make_token(await make_user("del", roles=["acme-deleters"]))

    async with agent(token) as client:
        shown = {listed.name for listed in (await client.list_tools()).tools}

    assert {"delete_component", "delete_path"} <= shown
