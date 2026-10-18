"""`/mcp` (MCP spec 4, 5, 8): signed in with an API token only, each caller shown only
the tools it could use, a refusal said as the REST API says it, each call recorded."""

from datetime import timedelta

import pytest
import structlog
from mcp.types import ToolAnnotations

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.mcp import tools
from megooarti.mcp.server import Server
from megooarti.security import users
from tests.accounts import sign_in
from tests.mcp.conftest import refusal, structured

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


async def test_an_agent_with_a_token_is_told_what_this_is_and_shown_the_read_tools(
    agent, make_user, make_token
):
    token = await make_token(await make_user("dev"))

    async with agent(token) as client:
        listed = await client.list_tools()
        instructions = client.instructions

    names = {listed_tool.name for listed_tool in listed.tools}
    assert {"whoami", "system_status"} <= names
    for shown in listed.tools:
        assert shown.description, shown.name  # what the agent chooses a tool by
        assert shown.annotations is not None
        assert shown.annotations.read_only_hint is True, shown.name
        assert shown.annotations.destructive_hint is False, shown.name
    assert "MegooArti is an artifact manager" in (instructions or "")
    assert "`_untrusted`" in (instructions or "")  # E4: what third parties wrote is data


@pytest.mark.parametrize(
    "header",
    [None, "Basic ZGV2OnBhc3N3b3Jk", "Bearer not-a-token", "Bearer mga_" + "x" * 43, "Token mga_x"],
    ids=["none", "password", "not-a-token", "unknown-token", "other-scheme"],
)
async def test_mcp_is_refused_without_an_api_token_as_a_bearer_token(client, header):
    headers = MCP_HEADERS | ({} if header is None else {"Authorization": header})

    answer = await client.post("/mcp", json=INITIALIZE, headers=headers)

    assert answer.status_code == 401, answer.text
    assert answer.headers["WWW-Authenticate"].startswith("Bearer ")
    assert answer.json()["error"]["code"] == "unauthorized"


async def test_a_session_cookie_does_not_sign_in_to_mcp(client, make_user):
    await make_user("dev")
    await sign_in(client, "dev")

    answer = await client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)

    assert answer.status_code == 401


async def test_an_expired_token_or_a_disabled_user_is_refused_at_the_next_request(
    client, make_user, make_token, sessionmaker
):
    dev = await make_user("dev")
    expired = await make_token(dev, "old", expires_at=utcnow() - timedelta(minutes=1))
    current = await make_token(dev, "current")
    bearer = MCP_HEADERS | {"Authorization": f"Bearer {current}"}
    assert (await client.post("/mcp", json=INITIALIZE, headers=bearer)).status_code == 200

    async with sessionmaker() as db:
        held = await users.get_user(db, dev.id)
        assert held is not None
        await users.update_user(db, held, {"status": "disabled"})
        await db.commit()
    gone = await client.post("/mcp", json=INITIALIZE, headers=bearer)
    old = await client.post(
        "/mcp", json=INITIALIZE, headers=MCP_HEADERS | {"Authorization": f"Bearer {expired}"}
    )

    assert (gone.status_code, old.status_code) == (401, 401)


async def test_mcp_is_not_part_of_the_rest_apis_description(client):
    described = (await client.get("/api/v1/openapi.json")).json()

    assert "/mcp" not in described["paths"]


@pytest.fixture
def extra_tools(app, monkeypatch):
    """Tools only these tests have: one for administrators, and two that fail."""
    registered = list(tools.TOOLS)
    monkeypatch.setattr(tools, "TOOLS", registered)

    @tools.tool(shown_to=lambda principal: principal.allows("admin:users:read"))
    async def list_everyone() -> str:
        """Only for those who may read users."""
        return "everyone"

    @tools.tool()
    async def refuse(name: str) -> str:
        """Refuses as the REST API does."""
        raise ApiError(
            403,
            "forbidden",
            "You do not have permission to do this.",
            [{"field": "name", "message": f"Not {name}."}],
        )

    @tools.tool()
    async def break_down() -> str:
        """Fails as nothing should."""
        raise RuntimeError("a secret detail")

    app.state.mcp = Server()


async def test_a_tool_a_caller_could_not_use_is_neither_shown_nor_called(
    agent, make_user, make_token, extra_tools
):
    plain = await make_token(await make_user("dev"))
    admin = await make_token(await make_user("root", roles=["admin"]))

    async with agent(plain) as client:
        hidden = {shown.name for shown in (await client.list_tools()).tools}
        called = await client.call_tool("list_everyone", {})
    async with agent(admin) as client:
        shown = {shown.name for shown in (await client.list_tools()).tools}
        allowed = await client.call_tool("list_everyone", {})

    assert "list_everyone" not in hidden
    assert refusal(called) == "Unknown tool: list_everyone"  # as for a tool there is not
    assert "list_everyone" in shown
    assert not allowed.is_error


async def test_a_refusal_is_the_rest_apis_code_and_message_and_a_failure_says_nothing_of_it(
    agent, make_user, make_token, extra_tools
):
    token = await make_token(await make_user("dev"))

    async with agent(token) as client:
        refused = await client.call_tool("refuse", {"name": "that"})
        broken = await client.call_tool("break_down", {})

    # The SDK names the tool before what it said.
    assert refusal(refused) == (
        "Error executing tool refuse: forbidden: You do not have permission to do this.\n"
        "- name: Not that."
    )
    assert refusal(broken) == (
        "Error executing tool break_down: internal_error: Something went wrong. It has been logged."
    )
    assert "a secret detail" not in refusal(broken)


async def test_each_call_is_recorded_with_who_made_it_what_it_asked_and_how_it_ended(
    agent, make_user, make_token, extra_tools
):
    dev = await make_user("dev")
    token = await make_token(dev)

    with structlog.testing.capture_logs() as logs:
        async with agent(token) as client:
            structured(await client.call_tool("whoami", {}))
            await client.call_tool("refuse", {"name": "that"})

    calls = [entry for entry in logs if entry["event"] == "mcp_tool_called"]
    assert [(entry["tool"], entry["outcome"]) for entry in calls] == [
        ("whoami", "ok"),
        ("refuse", "forbidden"),
    ]
    assert {entry["user"] for entry in calls} == {"dev"}
    assert calls[1]["arguments"] == {"name": "that"}
    assert all(entry["token"] and entry["duration_ms"] >= 0 for entry in calls)


def test_a_read_tool_says_it_changes_nothing():
    assert tools.READ == ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
