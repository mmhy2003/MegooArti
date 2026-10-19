"""Sign-in at a real OIDC provider (spec 5, 12): Keycloak, in a container beside the built
stack, with a realm of its own (tests/keycloak). A person is sent to Keycloak, signs in
there with its own form, and comes back signed in to MegooArti, with the role their
group gives.

The stack's backend reaches Keycloak as `keycloak:8080`, on the stack's network, and
that is the issuer's name. The test, on the host, reaches it at a published port and
says `keycloak:8080` in the Host header, as a browser would that resolved the name.

Run with `pytest -m docker`.
"""

import html
import re
import subprocess
import time
from urllib.parse import urlsplit

import httpx
import pytest

from tests.containers import BACKEND_DIR, HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "quay.io/keycloak/keycloak:26.0"
CONTAINER = f"{PROJECT}-keycloak"
KEYCLOAK_PORT = "18080"
ISSUER = "http://keycloak:8080/realms/megooarti"
ADDRESS = f"http://127.0.0.1:{HTTP_PORT}"
REALM = BACKEND_DIR / "tests" / "keycloak" / "megooarti-realm.json"


def docker(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, encoding="utf-8", check=False
    )


@pytest.fixture(scope="module")
def keycloak(stack):
    """Keycloak on the stack's network, its realm imported at start."""
    docker("rm", "--force", CONTAINER)
    started = docker(
        "run", "--detach", "--name", CONTAINER,
        "--network", f"{PROJECT}_default", "--network-alias", "keycloak",
        "--publish", f"127.0.0.1:{KEYCLOAK_PORT}:8080",
        "--env", "KC_BOOTSTRAP_ADMIN_USERNAME=admin",
        "--env", "KC_BOOTSTRAP_ADMIN_PASSWORD=admin",
        "--volume", f"{REALM}:/opt/keycloak/data/import/megooarti-realm.json:ro",
        IMAGE, "start-dev", "--import-realm", "--hostname=http://keycloak:8080",
    )  # fmt: skip
    assert started.returncode == 0, started.stderr
    deadline = time.monotonic() + 180
    metadata = f"http://127.0.0.1:{KEYCLOAK_PORT}/realms/megooarti/.well-known/openid-configuration"
    while True:
        try:
            if httpx.get(metadata, headers={"Host": "keycloak:8080"}, timeout=5).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        assert time.monotonic() < deadline, docker("logs", "--tail", "60", CONTAINER).stdout
        time.sleep(2)
    yield
    docker("rm", "--force", CONTAINER)


class Browser:
    """A browser, as far as a sign-in needs one: it keeps each host's cookies, follows no
    redirect by itself, and reaches `keycloak:8080` at the published port."""

    def __init__(self) -> None:
        self.cookies: dict[str, dict[str, str]] = {}

    def go(self, method: str, address: str, data: dict | None = None) -> httpx.Response:
        host = urlsplit(address).netloc
        headers = {}
        if host == "keycloak:8080":
            address = address.replace(
                "http://keycloak:8080", f"http://127.0.0.1:{KEYCLOAK_PORT}", 1
            )
            headers["Host"] = host
        kept = self.cookies.setdefault(host, {})
        if kept:
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in kept.items())
        response = httpx.request(method, address, data=data, headers=headers, timeout=30)
        for line in response.headers.get_list("set-cookie"):
            name, _, value = line.split(";", 1)[0].partition("=")
            if "max-age=0" in line.lower() or value == "":
                kept.pop(name.strip(), None)
            else:
                kept[name.strip()] = value
        return response


@pytest.fixture(scope="module")
def corp(administrator, keycloak) -> str:
    """The base URL Keycloak sends people back to, a role, and the source: its id."""
    status, _, said = call("PUT", "/settings/base-url", {"base_url": ADDRESS}, administrator)
    assert status == 200, said
    role = {
        "name": "developers",
        "description": "",
        "permissions": ["repository:*:*:read"],
        "roles": [],
    }
    status, _, said = call("POST", "/roles", role, administrator)
    assert status == 201, said
    source = {
        "kind": "oidc",
        "name": "Corp SSO",
        "enabled": True,
        "settings": {
            "issuer": ISSUER,
            "client_id": "megooarti",
            "client_secret": "the realm's secret for megooarti",
        },
        "group_mapping": [{"group": "developers", "roles": ["developers"]}],
    }
    status, _, said = call("POST", "/auth-sources", source, administrator)
    assert status == 201, said
    return said["id"]


def test_the_source_is_tested_against_keycloak(administrator, corp):
    status, _, said = call("POST", f"/auth-sources/{corp}/test", {}, administrator)

    assert status == 200
    assert said["ok"] is True, said
    assert said["message"].startswith(f"{ISSUER} answered. It signs with")


def test_a_person_signs_in_at_keycloak_and_comes_back_signed_in(corp):
    browser = Browser()

    started = browser.go("GET", f"{ADDRESS}/api/v1/auth/oidc/{corp}/start?next=/search")
    assert started.status_code == 302, started.text
    assert started.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    page = browser.go("GET", started.headers["location"])
    assert page.status_code == 200, page.text[:2000]
    action = re.search(r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', page.text)
    assert action, page.text[:2000]
    signed_in_there = browser.go(
        "POST",
        html.unescape(action[1]),
        {"username": "kim", "password": "kim's password", "credentialId": ""},
    )
    assert signed_in_there.status_code == 302, signed_in_there.text[:2000]
    back = signed_in_there.headers["location"]
    assert back.startswith(f"{ADDRESS}/api/v1/auth/oidc/{corp}/callback?"), back
    landed = browser.go("GET", back)
    session = browser.go("GET", f"{ADDRESS}/api/v1/auth/session").json()

    assert landed.status_code == 302, landed.text
    assert landed.headers["location"] == f"{ADDRESS}/login?next=%2Fsearch&signed_in=1"
    assert session["authenticated"] is True
    assert (session["user"]["username"], session["user"]["display_name"]) == ("kim", "Kim Lee")
    assert session["user"]["email"] == "kim@corp.example"
    assert "repository:*:*:read" in session["permissions"]  # the group's role
