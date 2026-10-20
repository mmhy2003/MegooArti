"""A trusted header through the built stack (spec 8): the gateway adds the address it sees
to X-Forwarded-For, the backend (uvicorn no longer reading it) believes what is past the
proxies an administrator trusts, and a header source's header is taken through them only.

Run with `pytest -m docker`.
"""

import json
import urllib.error
import urllib.request

import pytest

from tests.containers import HTTP_PORT, call

pytestmark = pytest.mark.docker


def session_as(name: str, forwarded: str | None = None) -> tuple[int, dict | None]:
    headers = {"X-Forwarded-User": name, "X-Forwarded-Groups": "developers"}
    if forwarded is not None:
        headers["X-Forwarded-For"] = forwarded
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1/auth/session", headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, None


@pytest.fixture(scope="module")
def header_source(administrator) -> None:
    role = {
        "name": "developers",
        "description": "",
        "permissions": ["repository:*:*:read"],
        "roles": [],
    }
    status, _, said = call("POST", "/roles", role, administrator)
    assert status == 201, said
    source = {
        "kind": "header",
        "name": "Corp SSO proxy",
        "enabled": True,
        "settings": {"groups_header": "X-Forwarded-Groups"},
        "group_mapping": [{"group": "developers", "roles": ["developers"]}],
    }
    status, _, said = call("POST", "/auth-sources", source, administrator)
    assert status == 201, said


def test_the_header_is_refused_until_the_proxy_it_comes_through_is_trusted(
    administrator, header_source
):
    # What a client writes of itself is not believed: the gateway's own word is last.
    spoofed, _ = session_as("admin", forwarded="10.0.0.5")
    refused, _ = session_as("kim")
    # Every address trusted: as an SSO proxy on any address in front of the gateway.
    status, _, said = call(
        "PUT",
        "/settings/trusted-proxies",
        {"trusted_proxies": ["0.0.0.0/0", "::/0"]},
        administrator,
    )
    assert status == 200, said
    taken, kim = session_as("kim")
    call("PUT", "/settings/trusted-proxies", {"trusted_proxies": []}, administrator)
    after, _ = session_as("kim")

    assert (spoofed, refused) == (401, 401)
    assert taken == 200
    assert (kim["method"], kim["user"]["username"]) == ("header", "kim")
    assert "repository:*:*:read" in kim["permissions"]
    assert after == 401
