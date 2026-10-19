"""The steps of OAuth's sign-in, as a client and a person in a browser take them."""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

from httpx import AsyncClient

BASE = "https://test"
REDIRECT = "http://127.0.0.1:33418/callback"
MCP = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def pkce() -> tuple[str, str]:
    """A code verifier and its S256 challenge (RFC 7636)."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def query_of(address: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(address).query).items()}


async def register(client: AsyncClient, redirect: str = REDIRECT, name: str = "Claude") -> str:
    answer = await client.post(
        "/oauth/register", json={"client_name": name, "redirect_uris": [redirect]}
    )
    assert answer.status_code == 201, answer.text
    return answer.json()["client_id"]


def authorization(client_id: str, challenge: str, **more: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "the-clients-state",
        "resource": f"{BASE}/mcp",
        **more,
    }


async def sealed_request(client: AsyncClient, client_id: str, challenge: str) -> str:
    """What authorize sends the person to the consent page with."""
    answer = await client.get("/oauth/authorize", params=authorization(client_id, challenge))
    assert answer.status_code == 302, answer.text
    assert answer.headers["Location"].startswith(f"{BASE}/connect?request=")
    return query_of(answer.headers["Location"])["request"]


async def approved_code(
    client: AsyncClient,
    browser: AsyncClient,
    access: str = "read",
    lasts: str = "30d",
    redirect: str = REDIRECT,
) -> tuple[str, str]:
    """A client registered, and a code the signed-in `browser` approved for it: the
    client's id, and the code and its verifier, as "code verifier"."""
    client_id = await register(client, redirect)
    verifier, challenge = pkce()
    sealed = await sealed_request(client, client_id, challenge)
    said = await browser.post(
        "/api/v1/oauth/consent", json={"request": sealed, "access": access, "lasts": lasts}
    )
    assert said.status_code == 200, said.text
    back = query_of(said.json()["redirect"])
    assert back["state"] == "the-clients-state"
    return client_id, f"{back['code']} {verifier}"


async def tokens(client: AsyncClient, client_id: str, code_and_verifier: str) -> dict:
    code, verifier = code_and_verifier.split(" ")
    answer = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
            "resource": f"{BASE}/mcp",
        },
    )
    assert answer.status_code == 200, answer.text
    return answer.json()
