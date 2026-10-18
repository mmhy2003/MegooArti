"""An agent through the gateway of the built stack, with the official MCP client (MCP
spec 9.3): it signs in with an API token, lists the tools, finds a file it uploaded,
and reads how a repository is used.

Run with `pytest -m docker`.
"""

import base64
import urllib.error
import urllib.request

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from tests.containers import HTTP_PORT, call

pytestmark = pytest.mark.docker

ADDRESS = f"http://127.0.0.1:{HTTP_PORT}"


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A raw repository with a file in it, and the administrator's API token."""
    body = {"name": "agent-files", "format": "raw", "type": "hosted"}
    status, _, answer = call("POST", "/repositories", body, administrator)
    assert status == 201, answer
    status, _, created = call("POST", "/me/tokens", {"name": "agent"}, administrator)
    assert status == 201, created
    secret = created["token"]
    request = urllib.request.Request(
        f"{ADDRESS}/repository/agent-files/notes/hello.txt",
        method="PUT",
        data=b"hello, agent",
        headers={
            "Authorization": "Basic " + base64.b64encode(f"__token__:{secret}".encode()).decode()
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status in (200, 201)
    return secret


async def test_an_agent_signs_in_with_a_token_and_finds_what_is_there(token):
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with http, Client(streamable_http_client(f"{ADDRESS}/mcp", http_client=http)) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        me = (await client.call_tool("whoami", {})).structured_content
        found = (await client.call_tool("search_packages", {"words": "hello"})).structured_content
        listed = (await client.call_tool("list_repositories", {})).structured_content

    assert {"search_packages", "package_versions", "repository_details", "whoami"} <= tools
    assert me["username"] == "admin"
    assert [(item["repository"], item["name"]) for item in found["items"]] == [
        ("agent-files", "hello.txt")
    ]
    assert "agent-files" in [one["name"] for one in listed["items"]]


def test_mcp_without_a_token_is_refused_through_the_gateway(stack):
    request = urllib.request.Request(
        f"{ADDRESS}/mcp",
        method="POST",
        data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=30)

    assert refused.value.code == 401
    assert refused.value.headers["WWW-Authenticate"].startswith("Bearer ")
