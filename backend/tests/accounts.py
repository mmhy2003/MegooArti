"""Helpers for tests that need people who can sign in."""

import base64

from httpx import AsyncClient, Response

PASSWORD = "correct horse battery"


async def sign_in(client: AsyncClient, username: str, password: str = PASSWORD) -> dict:
    """Sign in through the API. The client keeps the cookie and sends the CSRF token."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


def basic(username: str, secret: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error_code(response: Response) -> str:
    return response.json()["error"]["code"]
