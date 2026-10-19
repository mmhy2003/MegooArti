"""The official MCP client signs in with OAuth (MCP spec 9.3): it finds the server's
metadata from the 401, registers, sends the person to approve, trades the code with
PKCE, and calls a tool."""

import httpx2
from mcp import Client
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from tests.mcp.oauth_steps import BASE, REDIRECT, query_of


class Memory(TokenStorage):
    """What a client keeps between its requests: here, for the test."""

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


async def test_the_official_client_signs_in_with_oauth_and_calls_a_tool(app, browser):
    approved: dict[str, str] = {}

    async def open_in_browser(address: str) -> None:
        # The person's browser: authorize sends it to the consent page, where they approve.
        sent = await browser.get(address)
        sealed = query_of(sent.headers["Location"])["request"]
        said = await browser.post(
            "/api/v1/oauth/consent", json={"request": sealed, "access": "all", "lasts": "1d"}
        )
        approved.update(query_of(said.json()["redirect"]))

    async def come_back() -> AuthorizationCodeResult:
        return AuthorizationCodeResult(code=approved["code"], state=approved.get("state"))

    stored = Memory()
    provider = OAuthClientProvider(
        server_url=f"{BASE}/mcp",
        client_metadata=OAuthClientMetadata(
            client_name="The official client", redirect_uris=[REDIRECT]
        ),
        storage=stored,
        redirect_handler=open_in_browser,
        callback_handler=come_back,
    )
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, auth=provider)
    async with http, Client(streamable_http_client(f"{BASE}/mcp", http_client=http)) as client:
        who = (await client.call_tool("whoami", {})).structured_content

    assert who["username"] == "dev"
    assert (who["token"]["kind"], who["token"]["name"]) == ("oauth", "The official client")
    assert stored.tokens is not None and stored.tokens.access_token.startswith("mgo_")
    assert stored.client is not None and stored.client.token_endpoint_auth_method == "none"
