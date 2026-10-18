"""An agent's session with `/mcp`: the official MCP client, calling the application
in-process over Streamable HTTP, as it calls a real server."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult


@asynccontextmanager
async def connected(app: FastAPI, token: str) -> AsyncIterator[Client]:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    )
    async with http, Client(streamable_http_client("https://test/mcp", http_client=http)) as client:
        yield client


@pytest.fixture
def agent(app: FastAPI) -> Callable[[str], AbstractAsyncContextManager[Client]]:
    """`async with agent(token) as client`: an MCP session signed in with an API token."""
    return lambda token: connected(app, token)


def structured(result: CallToolResult) -> Any:
    """What a tool gave, as data; the test fails, saying why, if the tool refused."""
    assert not result.is_error, result.content
    return result.structured_content


def refusal(result: CallToolResult) -> str:
    """What a tool that refused said."""
    assert result.is_error, result.structured_content
    return "\n".join(getattr(part, "text", "") for part in result.content)
