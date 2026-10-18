"""What tools that change things share (MCP spec E1, E3, 8.1): who is shown them, what
they say of themselves, and a refusal of what they were given."""

import pytest
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request

from megooarti.mcp import tools
from megooarti.mcp.server import Server
from tests.mcp.conftest import refusal
from tests.repositories.conftest import someone


@pytest.mark.parametrize(
    ("patterns", "scopes", "shown"),
    [
        (["*"], None, True),
        (["repository"], None, True),
        (["repository:maven"], None, True),
        (["repository:*:releases:delete"], None, True),
        (["repository:maven:releases:*"], None, True),
        (["repository:maven:releases:read", "admin:users:write"], None, False),
        (["*"], ["repository:*:*:read"], False),  # the token narrows it
        (["*"], ["repository:npm:private:delete"], True),
        ([], None, False),
    ],
)
def test_a_tool_of_contents_is_shown_to_whoever_may_do_it_to_some_repository(
    patterns, scopes, shown
):
    principal = someone(*patterns)
    if scopes is not None:
        principal = type(principal)(principal.user, "token", principal.patterns, frozenset(scopes))

    assert tools.may_somewhere("delete")(principal) is shown


def test_a_tool_of_administration_is_shown_to_whoever_holds_its_permission():
    gate = tools.holding("admin:users:write")

    assert gate(someone("admin:users")) is True
    assert gate(someone("admin:users:read")) is False


def test_what_tools_that_change_things_say_of_themselves():
    assert tools.WRITE == ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
    )
    assert tools.CHANGE == ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )
    assert tools.DESTRUCTIVE == ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    )


@pytest.fixture
def hidden(app, monkeypatch):
    """A tool for those who may read users, and one that is given what it cannot take."""
    monkeypatch.setattr(tools, "TOOLS", list(tools.TOOLS))

    @tools.tool(shown_to=tools.holding("admin:users:read"))
    async def list_everyone(name: str) -> str:
        """Only for those who may read users."""
        return name

    class Named(BaseModel):
        name: str = Field(pattern=r"^[a-z]+$")

    @tools.tool()
    async def take_a_name(name: str) -> str:
        """Takes a name of letters only, as the REST API's body would."""
        return Named(name=name).name

    app.state.mcp = Server()
    return app.state.mcp


def test_a_hidden_tools_schema_is_not_told_to_whoever_may_not_use_it(hidden):
    request = Request({"type": "http", "headers": []})

    tools.enter(tools.Caller(someone("repository:*:*:read"), request))
    unseen = hidden._tool_input_schema("list_everyone")
    tools.enter(tools.Caller(someone("admin:users:read"), request))
    seen = hidden._tool_input_schema("list_everyone")

    assert unseen is None
    assert seen is not None and "name" in seen["properties"]


async def test_what_the_rest_apis_body_would_refuse_is_refused_in_its_words(
    agent, make_user, make_token, hidden
):
    token = await make_token(await make_user("dev"))

    async with agent(token) as client:
        refused = await client.call_tool("take_a_name", {"name": "Not Letters"})

    said = refusal(refused)
    assert (
        "validation_error: The request is not valid.\n- name: String should match pattern" in said
    )
