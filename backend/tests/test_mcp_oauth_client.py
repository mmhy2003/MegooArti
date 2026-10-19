"""An agent signs in with OAuth through the gateway of the built stack, with the official
MCP client (MCP spec 9.3): it finds the server's metadata from the 401, registers, sends
the person to the consent page, which the administrator answers, trades the code with
PKCE, and calls a tool.

Run with `pytest -m docker`.
"""

import httpx2
import pytest
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from tests.containers import HTTP_PORT, call
from tests.mcp.oauth_steps import query_of

pytestmark = pytest.mark.docker

ADDRESS = f"http://127.0.0.1:{HTTP_PORT}"
REDIRECT = "http://127.0.0.1:33418/callback"


class Memory(TokenStorage):
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info


@pytest.fixture(scope="module")
def based(administrator) -> dict[str, str]:
    """The stack's base URL, which OAuth names itself by: its address through the gateway."""
    status, _, answer = call("PUT", "/settings/base-url", {"base_url": ADDRESS}, administrator)
    assert status == 200, answer
    return administrator


async def test_an_agent_signs_in_with_oauth_through_the_gateway_and_calls_a_tool(based):
    approved: dict[str, str] = {}
    person = httpx2.AsyncClient(base_url=ADDRESS, headers=based, follow_redirects=False)

    async def open_in_browser(address: str) -> None:
        # The administrator's browser, already signed in: the consent page, answered.
        sent = await person.get(address)
        assert sent.status_code == 302, sent.text
        sealed = query_of(sent.headers["Location"])["request"]
        said = await person.post(
            "/api/v1/oauth/consent", json={"request": sealed, "access": "read", "lasts": "1d"}
        )
        assert said.status_code == 200, said.text
        approved.update(query_of(said.json()["redirect"]))

    async def come_back() -> AuthorizationCodeResult:
        return AuthorizationCodeResult(code=approved["code"], state=approved.get("state"))

    provider = OAuthClientProvider(
        server_url=f"{ADDRESS}/mcp",
        client_metadata=OAuthClientMetadata(
            client_name="The stack's agent", redirect_uris=[REDIRECT]
        ),
        storage=Memory(),
        redirect_handler=open_in_browser,
        callback_handler=come_back,
    )
    http = httpx2.AsyncClient(auth=provider, timeout=30)
    async with (
        person,
        http,
        Client(streamable_http_client(f"{ADDRESS}/mcp", http_client=http)) as client,
    ):
        tools = {tool.name for tool in (await client.list_tools()).tools}
        who = (await client.call_tool("whoami", {})).structured_content

    assert who["username"] == "admin"
    assert (who["token"]["kind"], who["token"]["name"]) == ("oauth", "The stack's agent")
    assert "search_packages" in tools and "create_repository" not in tools  # reading only
