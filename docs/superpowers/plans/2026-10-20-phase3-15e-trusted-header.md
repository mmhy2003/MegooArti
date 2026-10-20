# External Identity: Trusted Header and Trusted Proxies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator lists the proxies in front of the gateway. Their `X-Forwarded-For` is then believed, for the client's address and scheme. A trusted header source signs people in by the header such a proxy sets (an SSO gateway's `X-Forwarded-User`), with their groups. The header is taken from a trusted proxy only, and its changes from the server's own pages only. The plan proves this through the built stack.

**Architecture:** `megooarti/proxies.py` is an ASGI middleware that replaces uvicorn's proxy headers. It reads `X-Forwarded-For` from the right, past the gateway (trusted by the deployment's `MEGOOARTI_FORWARDED_ALLOW_IPS`) and past the `trusted_proxies` setting, which is changed at once through `PUT /api/v1/settings/trusted-proxies`. It sets the request's client and `state.proxied`. The gateway now adds the address it sees to the header instead of replacing it. `security/header.py` is the `header` kind of plan 15a's registry. `authentication.resolve_principal` reads its header before anything else and refuses it without a trusted proxy. A change made under the header must pass a strict same-origin check. The web UI adds a Trusted proxies panel under Authentication and a Trusted header kind on the source form.

**Tech Stack:** Python 3.13, FastAPI/Starlette (ASGI middleware), SQLAlchemy, nginx; Next.js, React, Vitest; Docker for the container test.

**Spec:** [docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md](../specs/2026-10-19-identity-audit-selectors-design.md): section 8, with 4, 11, 12, 14 and the row of plan 15e in 13; E1, E2; the "Settled" tables of 15a to 15d (C8: one process).

## Decisions this plan settles

Task 4 writes these into the spec, as "Settled while building plan 15e".

| # | Decision | Reason |
| --- | --- | --- |
| H1 | Who a request comes from is `megooarti.proxies.ProxiesMiddleware`'s to say, and uvicorn's proxy headers are off: `X-Forwarded-For` is read from the right. The backend's peer is believed as the deployment's (`MEGOOARTI_FORWARDED_ALLOW_IPS`, the gateway, `*` under Compose) or as a trusted proxy, every address before it as a trusted proxy only; the first not believed is the client. A hop that is not an address makes the client `unknown`. The request's `client` is that address; `state.proxied` says whether a proxy the administrator trusts passed it on. | Section 8: uvicorn trusts one list given at start; an administrator's changes while it runs. |
| H2 | The gateway adds the address it sees to `X-Forwarded-For` (`$proxy_add_x_forwarded_for`), where it wrote its own in its place: what a client wrote is left of it, and believed only past proxies the administrator trusts. | Section 8, 14: a proxy in front of the gateway can be heard; a client cannot speak for itself. |
| H3 | `X-Forwarded-Proto` is taken when the peer is believed, so the scheme of the addresses the server writes (an OIDC redirect without a base URL) is the client's. | As uvicorn did with its proxy headers. |
| H4 | `trusted_proxies` is a setting of addresses and networks, at most 100, each kept as its network (`10.0.0.5` as `10.0.0.5/32`), once: `PUT /api/v1/settings/trusted-proxies` with `admin:security:write`, and shown in `GET /api/v1/settings/sign-in`. One that is neither is refused at its place (`trusted_proxies.<n>`). It is read at start and changed at once with the setting, as 15c's certificates (C8: one process). | Section 8. |
| H5 | A header source's settings: `user_header` (`X-Forwarded-User` unless said) and `groups_header` (none unless said), a header's name each (an HTTP token, at most 64 characters), not `Authorization`, `Cookie`, `Host`, `X-Forwarded-For` or `X-Forwarded-Proto`, and not the same. It has no secret and takes no password; Test says what it reads. | Section 8. |
| H6 | The header is read before `Authorization`, for every enabled header source in order: present without a trusted proxy, it is `401` and `trusted_header_refused` is logged; a name that is empty, longer than 256 characters or with control characters is `401`. The name is the user's identity at the source and their user name; at most 200 groups are read, separated by commas. A request with it is the user's, as `header`, an interactive principal, provisioned (4.2) at each request; a disabled user is `401`. | Section 8, 4.2. |
| H7 | A change (`POST`, `PUT`, `PATCH`, `DELETE`) by a header's principal must say it comes from the server's own pages: `Sec-Fetch-Site` `same-origin` or `none`, or without it an `Origin` of the server's host or base URL; anything else, or neither, is `403 cross_site_request`. | Section 8: there is no CSRF token without a session, and a browser sends the proxy's sign-in to every page's request. |
| H8 | Authentication has a Trusted proxies panel, a line an address or a network, a refused line said by itself; a source's kind is OIDC, LDAP or Trusted header, whose form is the two headers. | Section 4.3, 15d's L9. |
| H9 | The container test sends the header through the gateway: refused, even with an `X-Forwarded-For` a client wrote, until every address is trusted; then the user is made with their group's role. | Section 12. |

## Global Constraints

- **`X-Forwarded-For` is honoured from trusted proxies only, its addresses read from the right past them** (section 8, 14). The gateway is trusted where Compose runs it.
- **The trusted header is honoured only from a trusted proxy; from any other address, a request with it is refused (`401`)** (section 8).
- **A request with the header is that user's, created or refreshed as 4.2, as a session's: its changes need the same-origin check** (section 8).
- **The built-in `admin` always signs in locally** (E1). **A user belongs to one source, known by the header's name there** (E2).
- **Every test of the stack is marked `docker`.**
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

These are the failures that would hurt a person using this most, each with the test in this plan that pins it.

1. **A client that writes a trusted proxy's address in `X-Forwarded-For`, and the header, to sign in as anyone.** The header is refused: a client's own words are left of the gateway's. Pinned by Task 2's `test_the_header_from_anywhere_else_is_refused[spoofed]` and Task 4's `test_the_header_is_refused_until_the_proxy_it_comes_through_is_trusted`.
2. **A page on another site that makes changes with the proxy's sign-in, which a browser sends anywhere.** It is refused unless the request says it comes from the server's own pages. Pinned by Task 2's `test_a_change_is_taken_from_the_servers_own_pages_only`.
3. **A header source turned on before its proxy is trusted.** Every request with the header gets `401`, said, rather than being taken as nobody's. Pinned by Task 2's `test_the_header_from_anywhere_else_is_refused[direct]`.
4. **A mistyped proxy (a host name, `10.0.0.0/33`).** It is refused at its own line, rather than saved to trust nothing or everything. An address in `X-Forwarded-For` that is not one makes the client `unknown`. Pinned by Task 1's `test_what_is_no_address_or_network_is_refused_where_it_is` and `test_the_client_is_the_first_address_from_the_right_that_is_no_trusted_proxy`.
5. **A user an administrator disabled, still named by the proxy.** They are refused, as a disabled user is everywhere. Pinned by Task 2's `test_a_user_of_the_header_has_no_password_and_is_refused_once_disabled`.

---

### Task 1: Trusted proxies

**Files:**
- Create: `backend/src/megooarti/proxies.py`
- Modify: `backend/src/megooarti/main.py`, `backend/src/megooarti/__main__.py`, `backend/src/megooarti/system/settings_store.py`, `backend/src/megooarti/system/settings_api.py`, `gateway/nginx.conf`, `docs/installation.md`, `docs/configuration.md`, `frontend/openapi.json` (written by the snapshot test with `MEGOOARTI_UPDATE_OPENAPI=1`)
- Test: `backend/tests/test_proxies.py`; modify `backend/tests/test_compose.py`, `backend/tests/test_launcher.py`, `backend/tests/test_settings_store.py`, `backend/tests/security/test_sign_in_settings.py`

**Interfaces:**
- Consumes: `Settings.forwarded_allow_ips`; `settings_store.get_setting`, `set_setting`, `DEFAULTS`; `settings_api._sign_in`, `SignInSettings`; `authentication.client_ip` (reads `request.client`).
- Produces:
  - `proxies.networks(entries) -> list[Network]` (raises `ValueError`), `address(hop) -> str | None`, `UNKNOWN`, `Deployment(allowed)` with `trusts(peer)`, `resolve(peer, forwarded, deployment, proxies) -> tuple[str, bool]`, `ProxiesMiddleware(app, *, deployment, proxies)`.
  - `request.state.proxied: bool`, `app.state.trusted_proxies: list[Network]`.
  - The setting `trusted_proxies` (`[]` unless set). `PUT /api/v1/settings/trusted-proxies` takes `{"trusted_proxies": [...]}` and answers `SignInSettings`, which now has `trusted_proxies: list[str]`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_proxies.py`:

```python
"""Who a request comes from, behind proxies (spec 8): X-Forwarded-For read from the right,
past the gateway and the proxies an administrator trusts; the rest never believed."""

import pytest
from sqlalchemy import select

from megooarti.proxies import UNKNOWN, Deployment, address, networks, resolve
from megooarti.security.models import UserSession
from tests.accounts import PASSWORD, error_code

GATEWAY = "172.18.0.4"
SIGN_IN = "/api/v1/settings/sign-in"
PROXIES = "/api/v1/settings/trusted-proxies"


@pytest.mark.parametrize(
    ("peer", "forwarded", "deployment", "proxies", "client", "proxied"),
    [
        # The gateway alone: what it saw is the client.
        (GATEWAY, ["203.0.113.7"], "*", [], "203.0.113.7", False),
        # What the client wrote of itself, before the gateway's word, is not believed.
        (GATEWAY, ["1.1.1.1", "203.0.113.7"], "*", [], "203.0.113.7", False),
        # A proxy of the administrator's in front of the gateway: past it.
        (GATEWAY, ["198.51.100.9", "10.0.0.5"], "*", ["10.0.0.5"], "198.51.100.9", True),
        (
            GATEWAY,
            ["6.6.6.6", "198.51.100.9", "10.0.0.5"],
            "*",
            ["10.0.0.0/8"],
            "198.51.100.9",
            True,
        ),
        # Without the gateway: a trusted proxy that reaches the backend itself.
        ("10.0.0.5", ["198.51.100.9"], "127.0.0.1", ["10.0.0.5"], "198.51.100.9", True),
        # A peer nobody trusts: whatever it says is its own.
        ("192.0.2.1", ["198.51.100.9"], "127.0.0.1", [], "192.0.2.1", False),
        # The deployment's addresses are trusted as the peer only, never further left.
        (
            GATEWAY,
            ["127.0.0.1", "203.0.113.7"],
            "127.0.0.1,172.18.0.0/16",
            [],
            "203.0.113.7",
            False,
        ),
        # What is not an address, where an address must be.
        (GATEWAY, ["not an address"], "*", [], UNKNOWN, False),
        (GATEWAY, ["198.51.100.9", "garbage"], "*", [], UNKNOWN, False),
        # Every one trusted: the furthest is the client.
        (GATEWAY, ["10.0.0.6", "10.0.0.5"], "*", ["10.0.0.0/8"], "10.0.0.6", True),
        (None, [], "*", [], UNKNOWN, False),
    ],
)
def test_the_client_is_the_first_address_from_the_right_that_is_no_trusted_proxy(
    peer, forwarded, deployment, proxies, client, proxied
):
    assert resolve(peer, forwarded, Deployment(deployment), networks(proxies)) == (client, proxied)


@pytest.mark.parametrize(
    ("written", "read"),
    [
        ("203.0.113.7", "203.0.113.7"),
        (" 203.0.113.7:51234 ", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("unknown", None),
        ("", None),
    ],
)
def test_an_address_is_read_as_proxies_write_it(written, read):
    assert address(written) == read


async def session_ip(sessionmaker) -> str:
    async with sessionmaker() as db:
        return await db.scalar(
            select(UserSession.ip).order_by(UserSession.created_at.desc()).limit(1)
        )


async def test_a_sessions_address_is_the_one_the_proxies_say(client, make_user, sessionmaker):
    # The tests' client comes from 127.0.0.1, which the deployment trusts as the gateway.
    await make_user("dana")

    await client.post(
        "/api/v1/auth/login",
        json={"username": "dana", "password": PASSWORD},
        headers={"X-Forwarded-For": "6.6.6.6, 203.0.113.7"},
    )

    assert await session_ip(sessionmaker) == "203.0.113.7"


async def test_trusted_proxies_are_kept_checked_and_believed_at_once(
    admin_client, other_client, make_user, sessionmaker
):
    await make_user("dana")
    chain = {"X-Forwarded-For": "198.51.100.9, 10.0.0.5"}
    login = {"username": "dana", "password": PASSWORD}

    await other_client.post("/api/v1/auth/login", json=login, headers=chain)
    before = await session_ip(sessionmaker)
    kept = await admin_client.put(
        PROXIES, json={"trusted_proxies": ["10.0.0.5", "10.0.0.0/8", "10.0.0.5"]}
    )
    await other_client.post("/api/v1/auth/login", json=login, headers=chain)
    after = await session_ip(sessionmaker)
    shown = (await admin_client.get(SIGN_IN)).json()

    assert (before, after) == ("10.0.0.5", "198.51.100.9")
    assert kept.json()["trusted_proxies"] == ["10.0.0.5/32", "10.0.0.0/8"]
    assert shown["trusted_proxies"] == ["10.0.0.5/32", "10.0.0.0/8"]


@pytest.mark.parametrize("entry", ["10.0.0.0/33", "proxy.corp.example", "", "10.0.0.5/8/1"])
async def test_what_is_no_address_or_network_is_refused_where_it_is(admin_client, entry):
    refused = await admin_client.put(PROXIES, json={"trusted_proxies": ["10.0.0.5", entry]})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == "trusted_proxies.1"


async def test_trusted_proxies_need_the_security_permission(client, make_user):
    from tests.accounts import basic

    await make_user("sam")

    refused = await client.put(
        PROXIES, json={"trusted_proxies": ["10.0.0.5"]}, headers=basic("sam", PASSWORD)
    )

    assert refused.status_code == 403


async def test_the_scheme_a_trusted_peer_says_is_believed(admin_client):
    # The address a provider sends people back to is written from it (15b).
    made = await admin_client.post(
        "/api/v1/auth-sources",
        json={
            "kind": "oidc",
            "name": "Corp SSO",
            "settings": {"issuer": "https://sso.example", "client_id": "megooarti"},
        },
    )
    said = await admin_client.get(
        f"/api/v1/auth-sources/{made.json()['id']}", headers={"X-Forwarded-Proto": "http"}
    )

    assert made.json()["redirect_uri"].startswith("https://test/")
    assert said.json()["redirect_uri"].startswith("http://test/")
```

Change `backend/tests/test_compose.py`:

```diff
@@ -94,9 +94,9 @@ def test_the_gateway_passes_a_path_on_exactly_as_it_was_sent():
         "proxy_buffering off;",
         "proxy_http_version 1.1;",
         "proxy_set_header Host $http_host;",
-        # The client's own address, and nothing the client said of itself: the gateway
-        # is the edge, and the backend takes its word.
-        "proxy_set_header X-Forwarded-For $remote_addr;",
+        # The address the gateway sees, added: the backend reads from the right, past
+        # trusted proxies only, so what the client wrote of itself is never believed.
+        "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
         "proxy_set_header X-Forwarded-Proto $scheme;",
         "proxy_read_timeout 600s;",
     ],
```

Change `backend/tests/test_launcher.py`:

```diff
@@ -7,7 +7,6 @@ def test_launcher_serves_the_app_factory_with_values_from_settings(monkeypatch,
     monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "postgresql://u:p@db:5432/m")
     monkeypatch.setenv("MEGOOARTI_PORT", "9001")
     monkeypatch.setenv("MEGOOARTI_SHUTDOWN_GRACE_SECONDS", "7")
-    monkeypatch.setenv("MEGOOARTI_FORWARDED_ALLOW_IPS", "10.0.0.1")
     monkeypatch.setenv("MEGOOARTI_LOG_LEVEL", "warning")
     monkeypatch.chdir(tmp_path)
     calls, levels = [], []
@@ -25,8 +24,8 @@ def test_launcher_serves_the_app_factory_with_values_from_settings(monkeypatch,
         "factory": True,
         "host": "0.0.0.0",
         "port": 9001,
-        "proxy_headers": True,
-        "forwarded_allow_ips": "10.0.0.1",
+        # Who a request comes from is the application's to say (megooarti.proxies).
+        "proxy_headers": False,
         "timeout_graceful_shutdown": 7,
         "log_config": None,
     }
```

Change `backend/tests/test_settings_store.py`:

```diff
@@ -8,7 +8,14 @@ async def test_defaults_apply_when_nothing_is_stored(db):
     assert await get_setting(db, "anonymous_access") == {"enabled": False}
     assert await get_setting(db, "default_role") is None
     assert await get_setting(db, "local_sign_in") == {"enabled": True}
-    assert set(DEFAULTS) == {"base_url", "anonymous_access", "default_role", "local_sign_in"}
+    assert await get_setting(db, "trusted_proxies") == []
+    assert set(DEFAULTS) == {
+        "base_url",
+        "anonymous_access",
+        "default_role",
+        "local_sign_in",
+        "trusted_proxies",
+    }
 
 
 async def test_a_stored_value_replaces_the_default(db):
```

Change `backend/tests/security/test_sign_in_settings.py`:

```diff
@@ -45,7 +45,11 @@ async def test_reading_and_changing_need_the_security_permissions(client, make_u
 async def test_by_default_there_is_no_default_role_and_our_own_users_sign_in(admin_client):
     said = await admin_client.get(SIGN_IN)
 
-    assert said.json() == {"default_role": None, "local_sign_in": {"enabled": True}}
+    assert said.json() == {
+        "default_role": None,
+        "local_sign_in": {"enabled": True},
+        "trusted_proxies": [],
+    }
 
 
 async def test_the_default_role_is_every_signed_in_users_and_kept_on_none(
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/test_proxies.py tests/test_compose.py tests/test_launcher.py tests/test_settings_store.py tests/security/test_sign_in_settings.py`
Expected: The tests do not load: `ModuleNotFoundError: No module named 'megooarti.proxies'`.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/proxies.py`:

```python
"""Who a request comes from, behind proxies (spec 8).

A request reaches the backend from the gateway (or a proxy of the installation's own, in
its place: the addresses of `MEGOOARTI_FORWARDED_ALLOW_IPS`), which may have it from other
proxies an administrator trusts (the `trusted_proxies` setting). `X-Forwarded-For` is read
from the right, past every trusted proxy: the first address that is not one is the
client's. What is left of it was written by the client, and is never believed.

The request's `client` is that address, for throttling, sessions and the log, and
`state.proxied` says whether a proxy the administrator trusts passed it on: a trusted
header (a header source's) is taken only then.
"""

import ipaddress
from collections.abc import Callable, Sequence

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

Network = ipaddress.IPv4Network | ipaddress.IPv6Network
_SCHEMES = {"http", "https"}
UNKNOWN = "unknown"


def networks(entries: Sequence[str]) -> list[Network]:
    """Addresses and networks (CIDR), as they are written: a bare address is a network
    of one. Raises ValueError for one that is neither."""
    return [ipaddress.ip_network(entry.strip(), strict=False) for entry in entries]


def address(hop: str) -> str | None:
    """An address as a proxy writes it, without a port: None for what is not one."""
    hop = hop.strip()
    if hop.startswith("["):  # [2001:db8::1]:443
        hop = hop[1 : hop.find("]")] if "]" in hop else ""
    elif hop.count(":") == 1:  # 203.0.113.7:51234
        hop = hop.split(":")[0]
    try:
        return str(ipaddress.ip_address(hop))
    except ValueError:
        return None


def _within(hop: str | None, among: Sequence[Network]) -> bool:
    if hop is None:
        return False
    found = ipaddress.ip_address(hop)
    return any(found in network for network in among)


class Deployment:
    """The addresses that reach the backend directly and are believed: the gateway's."""

    def __init__(self, allowed: str) -> None:
        entries = [entry.strip() for entry in allowed.split(",") if entry.strip()]
        self.anyone = "*" in entries
        self.networks = networks([entry for entry in entries if entry != "*"])

    def trusts(self, peer: str | None) -> bool:
        return peer is not None and (self.anyone or _within(peer, self.networks))


def resolve(
    peer: str | None, forwarded: Sequence[str], deployment: Deployment, proxies: Sequence[Network]
) -> tuple[str, bool]:
    """The client's address, and whether a proxy the administrator trusts passed it on.

    `forwarded` is `X-Forwarded-For`'s addresses, as written (the client's first). The
    peer is believed as the deployment's, or as a trusted proxy; every address before it
    only as a trusted proxy."""
    hops = [peer, *(address(hop) for hop in reversed(forwarded))]
    client, proxied = peer, False
    for index, hop in enumerate(hops):
        if hop is None:  # no peer, or what is not an address where one should be
            return UNKNOWN, proxied
        by_deployment = index == 0 and deployment.trusts(hop)
        by_administrator = _within(hop, proxies)
        if not (by_deployment or by_administrator):
            return hop, proxied
        proxied = proxied or by_administrator
        client = hop
    return client or UNKNOWN, proxied  # all of them trusted: the furthest is the client


class ProxiesMiddleware:
    """Sets the request's client (and scheme) from what trusted proxies say of it."""

    def __init__(
        self, app: ASGIApp, *, deployment: str, proxies: Callable[[], Sequence[Network]]
    ) -> None:
        self.app = app
        self.deployment = Deployment(deployment)
        self.proxies = proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        forwarded = [
            hop
            for value in headers.getlist("x-forwarded-for")
            for hop in value.split(",")
            if hop.strip()
        ]
        peer = address(scope["client"][0]) if scope.get("client") else None
        proxies = self.proxies()
        client, proxied = resolve(peer, forwarded, self.deployment, proxies)
        believed = self.deployment.trusts(peer) or _within(peer, proxies)
        scope["client"] = (client, 0)
        scope.setdefault("state", {})["proxied"] = proxied
        scheme = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if believed and scheme in _SCHEMES:
            scope["scheme"] = scheme if scope["type"] == "http" else scheme.replace("http", "ws")
        await self.app(scope, receive, send)
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -18,6 +18,7 @@ from megooarti.errors import ERROR_RESPONSES, UnhandledErrorMiddleware, register
 from megooarti.maintenance import run_exclusively, run_periodically
 from megooarti.mcp.endpoint import router as mcp_router
 from megooarti.mcp.server import Server as McpServer
+from megooarti.proxies import ProxiesMiddleware, networks
 from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
 from megooarti.repositories import remote, upkeep
 from megooarti.repositories.api import router as repositories_router
@@ -51,6 +52,7 @@ from megooarti.system import certificates
 from megooarti.system.certificates_api import router as certificates_router
 from megooarti.system.information_api import router as information_router
 from megooarti.system.settings_api import router as settings_router
+from megooarti.system.settings_store import get_setting
 from megooarti.system.status import router as status_router
 
 log = structlog.get_logger(__name__)
@@ -68,6 +70,7 @@ async def _first_start(app: FastAPI) -> None:
     )
     async with app.state.sessionmaker() as db:
         remote.trust(app, await certificates.trusted_pems(db))  # before anything goes out
+        app.state.trusted_proxies = networks(await get_setting(db, "trusted_proxies"))
 
 
 async def _first_start_when_possible(app: FastAPI, last_error: str) -> None:
@@ -172,6 +175,9 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.state.retired = []  # clients replaced, closed at shutdown: their requests may be long
     # One change of what is trusted at a time: its list is read and given as it was kept.
     app.state.trust_lock = asyncio.Lock()
+    # The proxies an administrator trusts in front of the gateway (spec 8): read at start,
+    # and changed with the setting.
+    app.state.trusted_proxies = []
     register_error_handlers(app)
     app.include_router(docs_router(f"{API_PREFIX}/openapi.json", "MegooArti API"))
     app.include_router(status_router, prefix=API_PREFIX)
@@ -201,5 +207,11 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     # first, so its 500 response passes through every other middleware, and keep
     # RequestIdMiddleware last, so everything else runs with a request ID.
     app.add_middleware(UnhandledErrorMiddleware)
+    # Who a request comes from, before anything reads it.
+    app.add_middleware(
+        ProxiesMiddleware,
+        deployment=settings.forwarded_allow_ips,
+        proxies=lambda: app.state.trusted_proxies,
+    )
     app.add_middleware(RequestIdMiddleware)
     return app
```

Change `backend/src/megooarti/__main__.py`:

```diff
@@ -20,8 +20,9 @@ def main() -> None:
         factory=True,
         host=settings.host,
         port=settings.port,
-        proxy_headers=True,
-        forwarded_allow_ips=settings.forwarded_allow_ips,
+        # Who a request comes from is the application's to say (megooarti.proxies): it
+        # believes proxies an administrator trusts, past the gateway, as uvicorn cannot.
+        proxy_headers=False,
         timeout_graceful_shutdown=settings.shutdown_grace_seconds,
         log_config=None,  # keep the JSON logging configured above
     )
```

Change `backend/src/megooarti/system/settings_store.py`:

```diff
@@ -13,6 +13,9 @@ DEFAULTS: dict[str, Any] = {
     "default_role": None,
     # Whether MegooArti's own users sign in: off, only the built-in `admin` does (E1).
     "local_sign_in": {"enabled": True},
+    # The proxies in front of the gateway whose X-Forwarded-For is believed, and whose
+    # trusted header signs people in (spec 8): addresses and networks (CIDR).
+    "trusted_proxies": [],
 }
 
 
```

Change `backend/src/megooarti/system/settings_api.py`:

```diff
@@ -3,12 +3,13 @@
 from urllib.parse import urlsplit
 
 import structlog
-from fastapi import APIRouter, Depends
+from fastapi import APIRouter, Depends, Request
 from pydantic import BaseModel, Field, field_validator
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
+from megooarti.proxies import networks
 from megooarti.security import users
 from megooarti.security.authentication import Principal, require
 from megooarti.security.guards import ensure_administrator_remains
@@ -37,12 +38,18 @@ class DefaultRole(BaseModel):
     default_role: str | None = Field(max_length=64)
 
 
+class TrustedProxies(BaseModel):
+    trusted_proxies: list[str] = Field(max_length=100)
+
+
 class SignInSettings(BaseModel):
     """How people sign in, besides the sources (spec 4.1): the role every signed-in user
-    has, and whether MegooArti's own users sign in."""
+    has, whether MegooArti's own users sign in, and the proxies trusted to say who a
+    request comes from (spec 8)."""
 
     default_role: str | None
     local_sign_in: LocalSignIn
+    trusted_proxies: list[str]
 
 
 class BaseUrl(BaseModel):
@@ -76,6 +83,7 @@ async def _sign_in(db: AsyncSession) -> SignInSettings:
     return SignInSettings(
         default_role=await get_setting(db, "default_role"),
         local_sign_in=LocalSignIn(**await get_setting(db, "local_sign_in")),
+        trusted_proxies=await get_setting(db, "trusted_proxies"),
     )
 
 
@@ -166,3 +174,34 @@ async def set_local_sign_in(
         "setting_changed", setting="local_sign_in", enabled=body.enabled, by=principal.user.username
     )
     return result
+
+
+@router.put("/trusted-proxies", response_model=SignInSettings)
+async def set_trusted_proxies(
+    body: TrustedProxies,
+    request: Request,
+    principal: Principal = Depends(require("admin:security:write")),
+    db: AsyncSession = Depends(get_session),
+) -> SignInSettings:
+    """The proxies in front of the gateway, by address or network (CIDR): their
+    X-Forwarded-For is believed, and a header source's header is taken from them only."""
+    kept: list[str] = []
+    for index, entry in enumerate(body.trusted_proxies):
+        try:
+            network = str(networks([entry])[0])
+        except ValueError:
+            details = [
+                {
+                    "field": f"trusted_proxies.{index}",
+                    "message": "An address, or a network as 10.0.0.0/8.",
+                }
+            ]
+            raise ApiError(422, "validation_error", "The request is not valid.", details) from None
+        if network not in kept:
+            kept.append(network)
+    await set_setting(db, "trusted_proxies", kept or None)
+    result = await _sign_in(db)
+    await db.commit()
+    request.app.state.trusted_proxies = networks(kept)  # at once, for the next request
+    log.info("setting_changed", setting="trusted_proxies", proxies=kept, by=principal.user.username)
+    return result
```

Change `gateway/nginx.conf`:

```diff
@@ -21,12 +21,12 @@ server {
     # The backend writes addresses from these: the host and port the client used, the
     # client's own address, and whether it came by HTTPS.
     #
-    # The client's address is the one nginx sees, and nothing the client sent: this is
-    # the edge, and whatever `X-Forwarded-For` arrives here was written by the client.
-    # The backend counts failed sign-ins by this address. Behind another proxy of your
-    # own, pass on what that proxy says instead.
+    # The address nginx sees is added at the right of `X-Forwarded-For`. The backend
+    # reads it from the right, past the proxies an administrator trusts (none, unless
+    # set): what a client wrote there itself is never believed, and a proxy of your own
+    # in front of this one is believed once it is trusted (Administration, Authentication).
     proxy_set_header Host $http_host;
-    proxy_set_header X-Forwarded-For $remote_addr;
+    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
     proxy_set_header X-Forwarded-Proto $scheme;
 
     # An artifact has no size limit here, and goes to the backend as it arrives: it is
```

Change `docs/installation.md`:

````diff
@@ -143,18 +143,22 @@ in it changes. Your proxy sends every request to the gateway's port, and:
 1. The gateway is published where only your proxy reaches it. For a proxy on the
    same machine, `MEGOOARTI_HTTP_PORT=127.0.0.1:8000` in `.env` publishes it on that
    machine alone.
-2. The gateway passes on what your proxy says of the client, in place of what it
-   sees itself, which is now your proxy. In `gateway/nginx.conf`:
+2. Your proxy is trusted: add its address (or its network) under Administration,
+   Authentication, Trusted proxies, or at `PUT /api/v1/settings/trusted-proxies`. The
+   gateway adds the address it sees to `X-Forwarded-For`, and the backend reads it from
+   the right, past the gateway and the proxies you trust: the client is the first
+   address that is not one. Until your proxy is trusted, every client has its address:
+   all of them share one limit of failed sign-ins, and the log names the proxy for
+   each. What a client writes in `X-Forwarded-For` itself is never believed.
+3. For the backend to know that clients came by HTTPS, the gateway passes on what your
+   proxy says, in `gateway/nginx.conf`:
 
    ```nginx
-   proxy_set_header X-Forwarded-For $http_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    ```
 
-   and then `docker compose up --detach --force-recreate gateway`. Left as it was,
-   the gateway gives every client your proxy's address: all of them share one limit
-   of failed sign-ins, the log names the proxy for each, and the backend takes every
-   request for plain HTTP, so that the [base URL](#the-base-url) has to be set.
+   and then `docker compose up --detach --force-recreate gateway`. Or set the
+   [base URL](#the-base-url), from which the backend writes its addresses.
 
 **In the gateway's place.** Your proxy does what the gateway does, by the table
 above. The Compose file has to be changed for that: it publishes neither the backend
@@ -180,11 +184,11 @@ Either way, your proxy must do what the gateway does towards the backend:
   the addresses it gives to clients (tarball links, the registry's token address)
   from them, unless the base URL is set in the system settings. It believes them
   only from the addresses in `MEGOOARTI_FORWARDED_ALLOW_IPS`.
-- **Write `X-Forwarded-For` yourself, from the address you see.** Do not pass on the
-  one a client sent: the backend counts failed sign-ins by that address and writes it
-  to its log, and a client that could choose it could evade the limit or lock out
-  somebody else's address. (`gateway/nginx.conf` sets it to `$remote_addr`. If your
-  proxy is itself behind another one that you trust, pass on what that one says.)
+- **Add the address you see to `X-Forwarded-For`** (`$proxy_add_x_forwarded_for` in
+  nginx), as the gateway does. The backend reads it from the right, past the trusted
+  proxies only: the address before the first one it does not trust is the client's, by
+  which it counts failed sign-ins and which it logs. Trust the proxies in front of
+  yours under Administration, Authentication, Trusted proxies.
 - **Terminate TLS**, and add `Strict-Transport-Security` if you want it. The frontend
   leaves compression to you as well.
 
````

Change `docs/configuration.md`:

```diff
@@ -13,7 +13,7 @@ All configuration of a deployment is by environment variable.
 | `MEGOOARTI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
 | `MEGOOARTI_HOST` | `0.0.0.0` | Address the HTTP server binds to |
 | `MEGOOARTI_PORT` | `8000` | Port the HTTP server listens on |
-| `MEGOOARTI_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Comma-separated reverse-proxy addresses whose `X-Forwarded-*` headers are trusted |
+| `MEGOOARTI_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Comma-separated addresses (or networks, or `*` for any) that reach the backend directly and whose `X-Forwarded-*` headers are believed: the gateway's. Proxies further out are trusted at runtime, under Administration, Authentication |
 | `MEGOOARTI_SHUTDOWN_GRACE_SECONDS` | `30` | How long in-flight requests may finish after a shutdown signal |
 | `MEGOOARTI_DATA_DIR` | `/var/lib/megooarti` | Directory for files MegooArti writes. Mount a volume here |
 | `MEGOOARTI_SESSION_IDLE_SECONDS` | `3600` | A UI session ends after this long without a request |
@@ -34,8 +34,9 @@ reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
 published on `127.0.0.1` only. `MEGOOARTI_HTTP_PORT` is the gateway's: the backend and
 the frontend are not published. Compose passes `MEGOOARTI_SESSION_COOKIE_SECURE` on to
 the backend, and sets `MEGOOARTI_FORWARDED_ALLOW_IPS` to `*` there: requests from
-outside reach it only through the gateway, which writes the client's address itself
-and overwrites whatever a client says of its own.
+outside reach it only through the gateway, which adds the address it sees to
+`X-Forwarded-For`. The backend reads that header from the right, past the gateway and
+the trusted proxies only, so whatever a client says of its own is never believed.
 
 The frontend container has no configuration. It reads `PORT` (default `3000`) and
 `HOSTNAME` (default `0.0.0.0`), and nothing else: it holds no secret and never calls
```

Change `frontend/openapi.json`:

```diff
@@ -2309,7 +2309,7 @@
         "type": "object"
       },
       "SignInSettings": {
-        "description": "How people sign in, besides the sources (spec 4.1): the role every signed-in user\nhas, and whether MegooArti's own users sign in.",
+        "description": "How people sign in, besides the sources (spec 4.1): the role every signed-in user\nhas, whether MegooArti's own users sign in, and the proxies trusted to say who a\nrequest comes from (spec 8).",
         "properties": {
           "default_role": {
             "anyOf": [
@@ -2324,11 +2324,19 @@
           },
           "local_sign_in": {
             "$ref": "#/components/schemas/LocalSignIn"
+          },
+          "trusted_proxies": {
+            "items": {
+              "type": "string"
+            },
+            "title": "Trusted Proxies",
+            "type": "array"
           }
         },
         "required": [
           "default_role",
-          "local_sign_in"
+          "local_sign_in",
+          "trusted_proxies"
         ],
         "title": "SignInSettings",
         "type": "object"
@@ -2891,6 +2899,23 @@
         "title": "TokenInfo",
         "type": "object"
       },
+      "TrustedProxies": {
+        "properties": {
+          "trusted_proxies": {
+            "items": {
+              "type": "string"
+            },
+            "maxItems": 100,
+            "title": "Trusted Proxies",
+            "type": "array"
+          }
+        },
+        "required": [
+          "trusted_proxies"
+        ],
+        "title": "TrustedProxies",
+        "type": "object"
+      },
       "Uploaded": {
         "properties": {
           "components": {
@@ -6247,6 +6272,48 @@
         ]
       }
     },
+    "/api/v1/settings/trusted-proxies": {
+      "put": {
+        "description": "The proxies in front of the gateway, by address or network (CIDR): their\nX-Forwarded-For is believed, and a header source's header is taken from them only.",
+        "operationId": "set_trusted_proxies_api_v1_settings_trusted_proxies_put",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/TrustedProxies"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/SignInSettings"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Set Trusted Proxies",
+        "tags": [
+          "settings"
+        ]
+      }
+    },
     "/api/v1/status/live": {
       "get": {
         "description": "The process is running and can answer HTTP requests.",
```

Then (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`, which writes `frontend/openapi.json` as above.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/test_proxies.py tests/test_compose.py tests/test_launcher.py tests/test_settings_store.py tests/security tests/test_app.py tests/test_openapi_snapshot.py tests/test_route_guards.py tests/test_documents.py`
Expected: 628 passed.

- [ ] **Step 5: Commit**

```bash
git add backend gateway docs frontend/openapi.json
git commit -m "feat(security): trusted proxies: X-Forwarded-For is read from the right past the gateway and the proxies an administrator lists, changed at once; the gateway adds the address it sees"
```

---

### Task 2: The trusted header source

**Files:**
- Create: `backend/src/megooarti/security/header.py`
- Modify: `backend/src/megooarti/security/authentication.py`, `backend/src/megooarti/main.py`
- Test: `backend/tests/security/test_header_source.py`

**Interfaces:**
- Consumes: Task 1's `request.state.proxied` and `PUT /api/v1/settings/trusted-proxies`. From 15a: `sources.Kind`, `register`, `invalid`, `Identity`, `Tested`, `in_order`, `provision`. Also `users.can_act`, `build_principal`, `unauthorized`, `client_ip`, and `get_setting(db, "base_url")`.
- Produces:
  - `header.KIND`, `DEFAULTS`, `HeaderKind`, `identity(settings, headers) -> Identity | None`.
  - `Method` gains `"header"`, which `Principal.is_interactive` includes.
  - `authentication._from_trusted_header` and `_require_same_origin`. The log event `trusted_header_refused`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_header_source.py`:

```python
"""A trusted header source (spec 8, SEC-17): a proxy in front says who a request is in a
header; taken from a trusted proxy only, refused from anywhere else, and its changes
accepted from the server's own pages only."""

import pytest
from sqlalchemy import select

from megooarti.security import roles
from megooarti.security.models import User
from tests.accounts import PASSWORD, basic, error_code

SOURCES = "/api/v1/auth-sources"
SESSION = "/api/v1/auth/session"
PROXY = "10.0.0.5"
# As the gateway passes a request on from the SSO proxy: the client, then the proxy.
THROUGH_PROXY = {"X-Forwarded-For": f"198.51.100.9, {PROXY}"}
DEVELOPERS = [{"group": "developers", "roles": ["developers"]}]


def as_(name: str, groups: str | None = None, **more: str) -> dict[str, str]:
    said = {**THROUGH_PROXY, "X-Forwarded-User": name, **more}
    if groups is not None:
        said["X-Forwarded-Groups"] = groups
    return said


@pytest.fixture
async def header_source(admin_client, sessionmaker):
    """A header source, on, with groups, and the SSO proxy trusted."""
    async with sessionmaker() as db:
        await roles.create_role(db, "developers", "", ["repository:*:*:read"], [])
        await db.commit()
    made = await admin_client.post(
        SOURCES,
        json={
            "kind": "header",
            "name": "Corp SSO proxy",
            "enabled": True,
            "settings": {"groups_header": "X-Forwarded-Groups"},
            "group_mapping": DEVELOPERS,
        },
    )
    assert made.status_code == 201, made.text
    trusted = await admin_client.put(
        "/api/v1/settings/trusted-proxies", json={"trusted_proxies": [PROXY]}
    )
    assert trusted.status_code == 200
    return made.json()


async def test_a_header_source_is_kept_with_its_defaults_and_its_test_says_what_it_takes(
    admin_client,
):
    made = await admin_client.post(
        SOURCES, json={"kind": "header", "name": "Proxy", "settings": {}}
    )
    tested = await admin_client.post(f"{SOURCES}/{made.json()['id']}/test", json={})

    assert made.json()["settings"] == {"user_header": "X-Forwarded-User", "groups_header": None}
    assert tested.json()["ok"] is True
    assert "X-Forwarded-User names who is signed in" in tested.json()["message"]
    assert "Taken only from a trusted proxy." in tested.json()["message"]


@pytest.mark.parametrize(
    ("sent", "field"),
    [
        ({"user_header": "X Forwarded User"}, "settings.user_header"),
        ({"user_header": "Authorization"}, "settings.user_header"),
        ({"user_header": "x-forwarded-for"}, "settings.user_header"),
        ({"groups_header": "X-Forwarded-User"}, "settings.groups_header"),
        ({"groups_header": "Cookie"}, "settings.groups_header"),
    ],
)
async def test_what_is_wrong_with_a_header_source_is_said_where_it_is(admin_client, sent, field):
    refused = await admin_client.post(
        SOURCES, json={"kind": "header", "name": "Proxy", "settings": sent}
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_the_header_from_a_trusted_proxy_signs_the_person_in_with_their_groups(
    other_client, header_source, sessionmaker
):
    said = await other_client.get(SESSION, headers=as_("Kim.Lee", "developers, staff"))
    async with sessionmaker() as db:
        kim = await db.scalar(select(User).where(User.username == "kim.lee"))

    assert said.status_code == 200, said.text
    assert (said.json()["method"], said.json()["user"]["username"]) == ("header", "kim.lee")
    assert "repository:*:*:read" in said.json()["permissions"]
    assert (str(kim.source_id), kim.external_id, kim.password_hash) == (
        header_source["id"],
        "Kim.Lee",
        None,
    )


async def test_each_request_brings_the_groups_up_to_date(other_client, header_source):
    await other_client.get(SESSION, headers=as_("kim", "developers"))

    left = await other_client.get(SESSION, headers=as_("kim", ""))

    assert "repository:*:*:read" not in left.json()["permissions"]


@pytest.mark.parametrize(
    "chain",
    [
        {},  # straight to the gateway
        {"X-Forwarded-For": f"{PROXY}, 203.0.113.7"},  # the proxy's address, written by a client
        {"X-Forwarded-For": "198.51.100.9, 10.0.0.6"},  # another proxy, not trusted
    ],
    ids=["direct", "spoofed", "untrusted"],
)
async def test_the_header_from_anywhere_else_is_refused(other_client, header_source, chain):
    refused = await other_client.get(SESSION, headers={**chain, "X-Forwarded-User": "admin"})

    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


async def test_without_a_header_source_on_the_header_is_nobodys(admin_client, other_client):
    said = await other_client.get(SESSION, headers=as_("admin"))

    assert said.status_code == 200
    assert said.json()["authenticated"] is False


async def test_a_header_that_names_nobody_is_refused(other_client, header_source):
    refused = await other_client.get(SESSION, headers=as_("   "))

    assert refused.status_code == 401


async def test_a_change_is_taken_from_the_servers_own_pages_only(other_client, header_source):
    token = {"name": "ci"}

    bare = await other_client.post("/api/v1/me/tokens", json=token, headers=as_("kim"))
    cross = await other_client.post(
        "/api/v1/me/tokens", json=token, headers=as_("kim", **{"Sec-Fetch-Site": "same-site"})
    )
    elsewhere = await other_client.post(
        "/api/v1/me/tokens", json=token, headers=as_("kim", Origin="https://evil.example")
    )
    own = await other_client.post(
        "/api/v1/me/tokens", json=token, headers=as_("kim", **{"Sec-Fetch-Site": "same-origin"})
    )
    own_origin = await other_client.post(
        "/api/v1/me/tokens", json={"name": "ci2"}, headers=as_("kim", Origin="https://test")
    )

    for refused in (bare, cross, elsewhere):
        assert (refused.status_code, error_code(refused)) == (403, "cross_site_request")
    assert (own.status_code, own_origin.status_code) == (201, 201)


async def test_a_user_of_the_header_has_no_password_and_is_refused_once_disabled(
    admin_client, other_client, header_source, sessionmaker
):
    await other_client.get(SESSION, headers=as_("kim"))
    async with sessionmaker() as db:
        kim = await db.scalar(select(User).where(User.username == "kim"))
    by_password = await other_client.get(SESSION, headers=basic("kim", PASSWORD))
    await admin_client.patch(f"/api/v1/users/{kim.id}", json={"status": "disabled"})

    disabled = await other_client.get(SESSION, headers=as_("kim"))

    assert by_password.status_code == 401
    assert disabled.status_code == 401
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_header_source.py`
Expected: 6 failed, 1 passed, 8 errors: `header` is not a kind of source (`422` at `kind`), so the fixture that makes one fails; only the test without a header source passes.

- [ ] **Step 3: Write the code**

Create `backend/src/megooarti/security/header.py`:

```python
"""Trusted header sources (spec 8, SEC-17): a proxy in front, that signs people in itself
(an SSO gateway), says who they are in a header. Taken only from a trusted proxy (see
`megooarti.proxies`); from anywhere else, a request with the header is refused.
"""

import re
from typing import Any

from megooarti.security import sources
from megooarti.security.sources import Identity, Tested, invalid

KIND = "header"
DEFAULTS = {"user_header": "X-Forwarded-User", "groups_header": None}
# A header's name as HTTP has it (a token), and not one the server reads for itself.
_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}")
_RESERVED = {"authorization", "cookie", "host", "x-forwarded-for", "x-forwarded-proto"}
# At most this many groups are read from the groups header.
_GROUP_LIMIT = 200


def _header(value: Any, field: str, *, required: bool) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise invalid(field, "A header's name is required, as X-Forwarded-User.")
        return None
    if not _NAME.fullmatch(text) or text.lower() in _RESERVED:
        raise invalid(
            field, "A header's name, as X-Forwarded-User, and not one HTTP gives meaning."
        )
    return text


class HeaderKind(sources.Kind):
    name = KIND

    def checked(self, settings: dict[str, Any]) -> dict[str, Any]:
        user_header = _header(
            settings.get("user_header") or DEFAULTS["user_header"],
            "settings.user_header",
            required=True,
        )
        groups_header = _header(
            settings.get("groups_header"), "settings.groups_header", required=False
        )
        if groups_header is not None and groups_header.lower() == user_header.lower():
            raise invalid("settings.groups_header", "The groups come in a header of their own.")
        return {"user_header": user_header, "groups_header": groups_header}

    async def test(self, outbound, settings, name, password) -> Tested:
        groups = settings.get("groups_header")
        said = f"{settings['user_header']} names who is signed in"
        said += f", {groups} their groups (separated by commas)." if groups else "."
        return Tested(True, f"{said} Taken only from a trusted proxy.")


def identity(settings: dict[str, Any], headers: Any) -> Identity | None:
    """Who the headers say someone is, or None when they name nobody."""
    name = (headers.get(settings["user_header"]) or "").strip()
    if not name or len(name) > 256 or any(ord(character) < 32 for character in name):
        return None
    groups: list[str] = []
    if settings.get("groups_header"):
        said = headers.get(settings["groups_header"]) or ""
        groups = [group.strip() for group in said.split(",") if group.strip()][:_GROUP_LIMIT]
    return Identity(external_id=name, username=name, display_name=name, groups=frozenset(groups))


sources.register(HeaderKind())
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -16,7 +16,16 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from megooarti.clock import utcnow
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
-from megooarti.security import oauth, registry_tokens, sessions, sources, throttle, tokens, users
+from megooarti.security import (
+    header,
+    oauth,
+    registry_tokens,
+    sessions,
+    sources,
+    throttle,
+    tokens,
+    users,
+)
 from megooarti.security.keys import TOKEN_PREFIX
 from megooarti.security.models import ApiToken, User, UserSession
 from megooarti.security.passwords import hash_password, needs_rehash, verify_password
@@ -32,7 +41,8 @@ API_KEY_HEADER = "X-NuGet-ApiKey"
 INVALID_CREDENTIALS = "Invalid credentials."
 _UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
 
-Method = Literal["session", "password", "token", "anonymous"]
+# "header": a trusted proxy said who it is (spec 8), as a session does for a browser.
+Method = Literal["session", "password", "token", "anonymous", "header"]
 Scheme = Literal["Bearer", "Basic"]
 
 
@@ -59,8 +69,9 @@ class Principal:
 
     @property
     def is_interactive(self) -> bool:
-        """Signed in as a person (cookie or password), not with an API token."""
-        return self.method in ("session", "password")
+        """Signed in as a person (cookie, password, or a trusted proxy's header), not
+        with an API token."""
+        return self.method in ("session", "password", "header")
 
     def allows(self, permission: str) -> bool:
         if not is_valid_permission(permission):
@@ -338,6 +349,30 @@ async def issue_registry_token(
     return registry_tokens.issue(request.app.state.settings, claims, utcnow())
 
 
+async def _from_trusted_header(request: Request, db: AsyncSession) -> Principal | None:
+    """The user a trusted proxy's header names (spec 8), or None without one. The header of
+    an enabled header source is refused (401) unless a trusted proxy passed the request on:
+    anyone else could write it."""
+    for source in await sources.in_order(db):
+        if not source.enabled or source.kind != header.KIND:
+            continue
+        if source.settings["user_header"] not in request.headers:
+            continue
+        if not getattr(request.state, "proxied", False):
+            log.warning("trusted_header_refused", source=source.name, ip=client_ip(request))
+            raise unauthorized(
+                f"{source.settings['user_header']} is taken from a trusted proxy only."
+            )
+        said = header.identity(source.settings, request.headers)
+        if said is None:
+            raise unauthorized(f"{source.settings['user_header']} names nobody.")
+        user = await sources.provision(db, source, said)
+        if not await users.can_act(db, user):
+            raise unauthorized()
+        return await build_principal(db, user, "header")
+    return None
+
+
 async def resolve_principal(
     request: Request, db: AsyncSession, *, registry: bool = False, api_key: bool = False
 ) -> Principal | None:
@@ -349,9 +384,12 @@ async def resolve_principal(
     that an API token in `X-NuGet-ApiKey` is one, where there is no Authorization
     header: a NuGet client sends it so, and nothing else with it.
     """
-    header = request.headers.get("Authorization")
-    if header:
-        return await _from_header(db, request, header, registry=registry)
+    proxied = await _from_trusted_header(request, db)
+    if proxied is not None:
+        return proxied
+    authorization = request.headers.get("Authorization")
+    if authorization:
+        return await _from_header(db, request, authorization, registry=registry)
     key = request.headers.get(API_KEY_HEADER, "").strip() if api_key else ""
     if key:
         user, token = await _authenticate_token(db, request, key)
@@ -410,6 +448,32 @@ async def _refuse_cross_site(request: Request, db: AsyncSession) -> None:
         raise refusal
 
 
+async def _require_same_origin(request: Request, db: AsyncSession) -> None:
+    """Refuse a change that does not say it comes from this server's own pages: with
+    `Sec-Fetch-Site: same-origin` (or `none`, typed by the person), or an `Origin` of
+    ours. Stricter than `_refuse_cross_site`, which lets a request that says nothing
+    through: a trusted header's request has no token to show instead."""
+    refusal = ApiError(
+        403,
+        "cross_site_request",
+        "Requests that change something are accepted from this server's own pages only.",
+    )
+    site = request.headers.get("Sec-Fetch-Site")
+    if site is not None:
+        if site not in ("same-origin", "none"):
+            raise refusal
+        return
+    origin = request.headers.get("Origin")
+    if origin is None:
+        raise refusal
+    ours = {request.headers.get("Host", "").lower()}
+    base_url = await get_setting(db, "base_url")
+    if base_url:
+        ours.add(urlsplit(base_url).netloc.lower())
+    if urlsplit(origin).netloc.lower() not in ours:
+        raise refusal
+
+
 async def refuse_cross_site(request: Request, db: AsyncSession = Depends(get_session)) -> None:
     """For a route that identifies nobody and still changes something: signing in.
 
@@ -435,6 +499,9 @@ async def _identify(
             raise
         raise unauthorized(error.message, scheme=scheme) from None
     await db.commit()  # last-seen times, cleared failure counts, upgraded password hashes
+    if principal is not None and principal.method == "header" and request.method in _UNSAFE_METHODS:
+        # No CSRF token without a session: a change must come from this server's own pages.
+        await _require_same_origin(request, db)
     if (
         principal is not None
         and principal.session is not None
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -36,6 +36,7 @@ from megooarti.repositories.search_api import router as search_router
 from megooarti.repositories.yum import format as _yum_format  # noqa: F401  (registers it)
 from megooarti.request_id import RequestIdMiddleware
 from megooarti.security import directory_check, oauth
+from megooarti.security import header as _header  # noqa: F401  (registers the kind of source)
 from megooarti.security import ldap as _ldap  # noqa: F401  (registers the kind of source)
 from megooarti.security import oidc as _oidc  # noqa: F401  (registers the kind of source)
 from megooarti.security.api import auth as auth_api
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security tests/test_proxies.py tests/mcp`
Expected: 577 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(security): a trusted header source: the header a trusted proxy sets signs the person in with their groups; refused from anywhere else; its changes from the server's own pages only"
```

---

### Task 3: The Trusted proxies panel and the header form

**Files:**
- Modify: `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api` from Task 1's `openapi.json`), `frontend/src/lib/security.ts`, `frontend/src/components/source-fields.tsx`, `frontend/src/screens/source.tsx`, `frontend/src/screens/authentication.tsx`, `frontend/messages/en.json`, `docs/web-ui.md`
- Test: modify `frontend/src/screens/source.test.tsx`, `frontend/src/screens/authentication.test.tsx`

**Interfaces:**
- Consumes:
  - Task 1's `SignInSettings.trusted_proxies` and `PUT /settings/trusted-proxies`, with its refusal at `trusted_proxies.<n>`. Task 2's header settings.
  - From 15d: `SOURCE_KINDS`, `KindForm`, `FieldsProps`, `kept`, `stored`, `text`. Also `refusalsOf`, `isApiError` and `TextAreaField`.
- Produces:
  - `useSetTrustedProxies()`. `KindName` gains `"header"`.
  - The messages `source.titles.*`, `source.kinds.header`, `source.kinds.headerHint`, `source.header.*`, and `authentication.trustedProxies*`, `proxyRefused`, `proxiesSaved`, `saveProxies`.
  - `source.providerTitle` and `source.ldap.title` are removed.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/screens/source.test.tsx`:

```diff
@@ -202,11 +202,11 @@ describe("an OIDC source", () => {
 
   test("of another kind is said to be set up through the API", async () => {
     oneSource({
-      "GET /auth-sources/corp": { json: { ...CORP, kind: "header", redirect_uri: null } },
+      "GET /auth-sources/corp": { json: { ...CORP, kind: "saml", redirect_uri: null } },
     });
 
     expect(
-      await screen.findByText("A source of the kind header is set up through the API."),
+      await screen.findByText("A source of the kind saml is set up through the API."),
     ).toBeVisible();
     expect(within(document.body).queryByLabelText("Issuer")).toBeNull();
   });
@@ -330,3 +330,71 @@ describe("an LDAP source (spec 7)", () => {
     expect(sent.settings.groups).toBe("search");
   });
 });
+
+describe("a trusted header source (spec 8)", () => {
+  test("is made with the headers that name a person and their groups", async () => {
+    const user = userEvent.setup();
+    const { calls } = newSource({
+      "POST /auth-sources": (call) => ({
+        status: 201,
+        json: {
+          ...CORP,
+          id: "proxy",
+          kind: "header",
+          ...(call.body as object),
+          redirect_uri: null,
+        },
+      }),
+    });
+
+    await user.click(await screen.findByRole("radio", { name: /Trusted header/ }));
+    await user.type(screen.getByLabelText("Name"), "Corp SSO proxy");
+    expect(screen.getByLabelText("User name header")).toHaveValue("X-Forwarded-User");
+    await user.type(screen.getByLabelText("Groups header"), "X-Forwarded-Groups");
+    await expectAccessible();
+    await user.click(screen.getByRole("button", { name: "Create source" }));
+
+    await waitFor(() =>
+      expect(notices()).toHaveTextContent("Created the sign-in source Corp SSO proxy."),
+    );
+    expect(of(calls, "POST")[0]?.body).toEqual({
+      kind: "header",
+      name: "Corp SSO proxy",
+      enabled: false,
+      settings: { user_header: "X-Forwarded-User", groups_header: "X-Forwarded-Groups" },
+      group_mapping: [],
+    });
+  });
+
+  test("needs the header that names a person, and sends no groups header left empty", async () => {
+    const user = userEvent.setup();
+    const { calls } = newSource({
+      "POST /auth-sources": (call) => ({
+        status: 201,
+        json: {
+          ...CORP,
+          id: "proxy",
+          kind: "header",
+          ...(call.body as object),
+          redirect_uri: null,
+        },
+      }),
+    });
+
+    await user.click(await screen.findByRole("radio", { name: /Trusted header/ }));
+    await user.type(screen.getByLabelText("Name"), "Proxy");
+    await user.clear(screen.getByLabelText("User name header"));
+    await user.click(screen.getByRole("button", { name: "Create source" }));
+    expect(screen.getByLabelText("User name header")).toHaveAccessibleDescription(/is needed/);
+    expect(of(calls, "POST")).toHaveLength(0);
+
+    await user.type(screen.getByLabelText("User name header"), "X-Remote-User");
+    await user.click(screen.getByRole("button", { name: "Create source" }));
+
+    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
+    expect((of(calls, "POST")[0]?.body as { settings: object }).settings).toEqual({
+      user_header: "X-Remote-User",
+      groups_header: null,
+    });
+  });
+});
```

Change `frontend/src/screens/authentication.test.tsx`:

```diff
@@ -31,7 +31,7 @@ const source = (name: string, position: number, more: Record<string, unknown> =
 });
 const CORP = source("Corp LDAP", 0);
 const LAB = source("Lab LDAP", 1, { enabled: false, users: 0 });
-const SIGN_IN = { default_role: null, local_sign_in: { enabled: true } };
+const SIGN_IN = { default_role: null, local_sign_in: { enabled: true }, trusted_proxies: [] };
 const ROLES = page(
   ["admin", "anonymous", "deployers"].map((name) => ({
     name,
@@ -281,3 +281,51 @@ describe("the default role (SEC-16)", () => {
     expect(of(calls, "PUT")[0]?.body).toEqual({ default_role: null });
   });
 });
+
+describe("the trusted proxies (spec 8)", () => {
+  test("are shown a line each, and saved as typed, without blank lines", async () => {
+    const user = userEvent.setup();
+    const { calls } = authentication({
+      "GET /settings/sign-in": { json: { ...SIGN_IN, trusted_proxies: ["10.0.0.5/32"] } },
+      "PUT /settings/trusted-proxies": (call) => ({
+        json: { ...SIGN_IN, ...(call.body as object) },
+      }),
+    });
+
+    const field = await screen.findByLabelText("Addresses and networks");
+    expect(field).toHaveValue("10.0.0.5/32");
+    await user.clear(field);
+    await user.type(field, " 10.0.0.5 {Enter}{Enter}10.1.0.0/16");
+    await user.click(screen.getByRole("button", { name: "Save trusted proxies" }));
+
+    await waitFor(() => expect(notices()).toHaveTextContent("2 proxies are trusted."));
+    expect(of(calls, "PUT")[0]?.body).toEqual({ trusted_proxies: ["10.0.0.5", "10.1.0.0/16"] });
+  });
+
+  test("say which line the server refuses", async () => {
+    const user = userEvent.setup();
+    authentication({
+      "PUT /settings/trusted-proxies": failure(
+        422,
+        "validation_error",
+        "The request is not valid.",
+        [{ field: "trusted_proxies.1", message: "An address, or a network as 10.0.0.0/8." }],
+      ),
+    });
+
+    const field = await screen.findByLabelText("Addresses and networks");
+    await user.type(field, "10.0.0.5{Enter}proxy.corp.example");
+    await user.click(screen.getByRole("button", { name: "Save trusted proxies" }));
+
+    await waitFor(() =>
+      expect(field).toHaveAccessibleDescription(/proxy.corp.example is not an address/),
+    );
+  });
+
+  test("are shown, and not changed, to whoever may only read them", async () => {
+    authentication({}, holding("admin:security:read"));
+
+    expect(await screen.findByLabelText("Addresses and networks")).toBeDisabled();
+    expect(screen.queryByRole("button", { name: "Save trusted proxies" })).toBeNull();
+  });
+});
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/screens/source.test.tsx src/screens/authentication.test.tsx`
Expected: 5 failed, 25 passed: there is no Trusted proxies panel, and no Trusted header among the kinds.

- [ ] **Step 3: Write the code**

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -908,6 +908,27 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/settings/trusted-proxies": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        /**
+         * Set Trusted Proxies
+         * @description The proxies in front of the gateway, by address or network (CIDR): their
+         *     X-Forwarded-For is believed, and a header source's header is taken from them only.
+         */
+        put: operations["set_trusted_proxies_api_v1_settings_trusted_proxies_put"];
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/status/live": {
         parameters: {
             query?: never;
@@ -1984,12 +2005,15 @@ export interface components {
         /**
          * SignInSettings
          * @description How people sign in, besides the sources (spec 4.1): the role every signed-in user
-         *     has, and whether MegooArti's own users sign in.
+         *     has, whether MegooArti's own users sign in, and the proxies trusted to say who a
+         *     request comes from (spec 8).
          */
         SignInSettings: {
             /** Default Role */
             default_role: string | null;
             local_sign_in: components["schemas"]["LocalSignIn"];
+            /** Trusted Proxies */
+            trusted_proxies: string[];
         };
         /**
          * SignInSource
@@ -2208,6 +2232,11 @@ export interface components {
             /** Scopes */
             scopes: string[] | null;
         };
+        /** TrustedProxies */
+        TrustedProxies: {
+            /** Trusted Proxies */
+            trusted_proxies: string[];
+        };
         /** Uploaded */
         Uploaded: {
             /** Components */
@@ -4349,6 +4378,39 @@ export interface operations {
             };
         };
     };
+    set_trusted_proxies_api_v1_settings_trusted_proxies_put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["TrustedProxies"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["SignInSettings"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
     live_api_v1_status_live_get: {
         parameters: {
             query?: never;
```

Change `frontend/src/lib/security.ts`:

```diff
@@ -344,6 +344,16 @@ export function useSetLocalSignIn() {
   });
 }
 
+/** The proxies in front of the gateway that are believed (spec 8): at once, for every request. */
+export function useSetTrustedProxies() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (proxies: string[]) =>
+      api.put<SignInSettings>("/settings/trusted-proxies", { trusted_proxies: proxies }),
+    onSuccess: (settings) => client.setQueryData([SIGN_IN], settings),
+  });
+}
+
 /** Every source, in the order they are asked: there are few, and their order is the point. */
 export function useSources() {
   return useQuery({
```

Change `frontend/src/components/source-fields.tsx`:

```diff
@@ -12,7 +12,7 @@ import { TextField } from "@/components/ui/field";
 import { CheckboxField, ChoiceGroup } from "@/components/ui/inputs";
 import type { SourceOut } from "@/lib/api/types";
 
-export type KindName = "oidc" | "ldap";
+export type KindName = "oidc" | "ldap" | "header";
 export type Values = Record<string, string | boolean>;
 type Translate = ReturnType<typeof useTranslations<"source">>;
 
@@ -369,7 +369,56 @@ const LDAP: KindForm = {
   Fields: LdapFields,
 };
 
-export const SOURCE_KINDS: Record<KindName, KindForm> = { oidc: OIDC, ldap: LDAP };
+// --- A trusted header (spec 8) -----------------------------------------------------------
+
+function HeaderFields({ values, change, at, own }: FieldsProps) {
+  const t = useTranslations("source");
+  return (
+    <div className="grid gap-4 sm:grid-cols-2">
+      <TextField
+        label={t("header.userHeader")}
+        hint={t("header.hints.userHeader")}
+        required
+        spellCheck={false}
+        autoComplete="off"
+        value={values.user_header as string}
+        error={at("user_header", own.user_header)}
+        onChange={(event) => change({ user_header: event.target.value })}
+      />
+      <TextField
+        label={t("header.groupsHeader")}
+        hint={t("header.hints.groupsHeader")}
+        spellCheck={false}
+        autoComplete="off"
+        value={values.groups_header as string}
+        error={at("groups_header")}
+        onChange={(event) => change({ groups_header: event.target.value })}
+      />
+    </div>
+  );
+}
+
+const HEADER: KindForm = {
+  secret: "",
+  fields: ["user_header", "groups_header"],
+  initial: (source) => {
+    const settings = kept(source);
+    return {
+      user_header: stored(settings, "user_header", "X-Forwarded-User"),
+      groups_header: stored(settings, "groups_header"),
+    };
+  },
+  own: (values, t) => ({
+    user_header: text(values.user_header) === "" ? t("header.userHeaderNeeded") : undefined,
+  }),
+  sent: (values) => ({
+    user_header: text(values.user_header),
+    groups_header: text(values.groups_header) || null,
+  }),
+  Fields: HeaderFields,
+};
+
+export const SOURCE_KINDS: Record<KindName, KindForm> = { oidc: OIDC, ldap: LDAP, header: HEADER };
 
 export function isKindName(kind: string): kind is KindName {
   return kind in SOURCE_KINDS;
```

Change `frontend/src/screens/source.tsx`:

```diff
@@ -100,7 +100,7 @@ function SourceForm({
         {
           onSuccess: () => {
             notify(t("saved", { name }));
-            setValues({ ...values, [fields.secret]: "" });
+            if (fields.secret !== "") setValues({ ...values, [fields.secret]: "" });
           },
         },
       );
@@ -111,7 +111,7 @@ function SourceForm({
     <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
       <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-6 border-0 p-0">
         <Panel className="flex flex-col gap-5 p-6">
-          <h2 className={H2}>{kind === "ldap" ? t("ldap.title") : t("providerTitle")}</h2>
+          <h2 className={H2}>{t(`titles.${kind}`)}</h2>
           <TextField
             label={t("fields.name")}
             hint={t("hints.name")}
@@ -126,7 +126,7 @@ function SourceForm({
             change={(changed) => setValues({ ...values, ...changed })}
             at={at}
             own={own}
-            hasSecret={source?.secrets.includes(fields.secret) ?? false}
+            hasSecret={fields.secret !== "" && (source?.secrets.includes(fields.secret) ?? false)}
           />
         </Panel>
         <Panel className="p-6">
@@ -184,6 +184,7 @@ export function NewSourceScreen() {
           options={[
             { value: "oidc", label: t("kinds.oidc"), hint: t("kinds.oidcHint") },
             { value: "ldap", label: t("kinds.ldap"), hint: t("kinds.ldapHint") },
+            { value: "header", label: t("kinds.header"), hint: t("kinds.headerHint") },
           ]}
         />
       </Panel>
```

Change `frontend/src/screens/authentication.tsx`:

```diff
@@ -8,20 +8,24 @@ import { Alert, StatusTag } from "@/components/ui/alert";
 import { Button } from "@/components/ui/button";
 import { ConfirmDialog } from "@/components/ui/confirm-dialog";
 import { Fact, Facts } from "@/components/ui/details";
+import { TextAreaField } from "@/components/ui/field";
 import { SelectField } from "@/components/ui/inputs";
 import { AppLink } from "@/components/ui/link";
 import { useNotify } from "@/components/ui/notifications";
 import { PageHeader, Panel } from "@/components/ui/panel";
 import { ErrorState, LoadingState } from "@/components/ui/states";
 import { Table, Td, Th } from "@/components/ui/table";
+import { isApiError } from "@/lib/api/client";
 import type { SourceOut } from "@/lib/api/types";
 import { NEW_SOURCE, sourceHref } from "@/lib/paths";
+import { refusalsOf } from "@/lib/refusals";
 import {
   useDeleteSource,
   useEveryRole,
   useOrderSources,
   useSetDefaultRole,
   useSetLocalSignIn,
+  useSetTrustedProxies,
   useSignInSettings,
   useSources,
   useTestSource,
@@ -302,6 +306,69 @@ function DefaultRole({ mayWrite }: { mayWrite: boolean }) {
   );
 }
 
+/**
+ * The proxies in front of the gateway (spec 8): one an address or a network a line. Their
+ * X-Forwarded-For is believed, and a header source's header is taken from them only.
+ */
+function TrustedProxies({ mayWrite }: { mayWrite: boolean }) {
+  const t = useTranslations("authentication");
+  const notify = useNotify();
+  const settings = useSignInSettings();
+  const change = useSetTrustedProxies();
+  const [typed, setTyped] = useState<string | null>(null);
+
+  if (settings.isError) {
+    return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
+  }
+  if (!settings.data) return <LoadingState className="p-4" />;
+  const kept = settings.data.trusted_proxies;
+  const text = typed ?? kept.join("\n");
+  const lines = text
+    .split(/\r?\n/)
+    .map((line) => line.trim())
+    .filter(Boolean);
+  // The server says which line is wrong by its place among those sent.
+  const wrong = refusalsOf(change.error, ["trusted_proxies"]);
+  const at = /^trusted_proxies\.(\d+)$/.exec(
+    isApiError(change.error) ? (change.error.details[0]?.field ?? "") : "",
+  );
+  const refusal = at ? t("proxyRefused", { line: lines[Number(at[1])] ?? "" }) : undefined;
+
+  function submit(event: FormEvent) {
+    event.preventDefault();
+    change.mutate(lines, {
+      onSuccess: (saved) => {
+        notify(t("proxiesSaved", { count: saved.trusted_proxies.length }));
+        setTyped(null);
+      },
+    });
+  }
+
+  return (
+    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
+      <TextAreaField
+        label={t("trustedProxies")}
+        hint={t("trustedProxiesHint")}
+        rows={4}
+        spellCheck={false}
+        className="font-mono text-sm"
+        disabled={!mayWrite}
+        value={text}
+        error={refusal}
+        onChange={(event) => setTyped(event.target.value)}
+      />
+      {change.isError && !refusal && wrong.elsewhere ? <ErrorState error={change.error} /> : null}
+      {mayWrite ? (
+        <div>
+          <Button type="submit" variant="primary" busy={change.isPending}>
+            {t("saveProxies")}
+          </Button>
+        </div>
+      ) : null}
+    </form>
+  );
+}
+
 /** Where people sign in from, in order, and the role every signed-in user has (SEC-15, SEC-16). */
 export function AuthenticationScreen() {
   const t = useTranslations("authentication");
@@ -329,6 +396,11 @@ export function AuthenticationScreen() {
         <p className="mb-4 text-fg-muted">{t("defaultRoleIntro")}</p>
         <DefaultRole mayWrite={mayWrite} />
       </Panel>
+      <Panel className="p-6">
+        <h2 className={H2}>{t("trustedProxiesTitle")}</h2>
+        <p className="mb-4 text-fg-muted">{t("trustedProxiesIntro")}</p>
+        <TrustedProxies mayWrite={mayWrite} />
+      </Panel>
     </div>
   );
 }
```

Change `frontend/messages/en.json`:

```diff
@@ -696,7 +696,14 @@
     "save": "Save",
     "defaultRoleSet": "Every signed-in user has the role {role}.",
     "defaultRoleCleared": "There is no default role.",
-    "newSource": "New source"
+    "newSource": "New source",
+    "trustedProxiesTitle": "Trusted proxies",
+    "trustedProxiesIntro": "The proxies in front of the gateway: their X-Forwarded-For is believed, past them the client's own address is found, and a trusted header is taken from them only. Without one, every request's address is the one the gateway saw.",
+    "trustedProxies": "Addresses and networks",
+    "trustedProxiesHint": "One a line: 10.0.0.5, or 10.0.0.0/8.",
+    "proxyRefused": "{line} is not an address, nor a network as 10.0.0.0/8.",
+    "proxiesSaved": "{count, plural, =0 {No proxy is trusted.} one {One proxy is trusted.} other {# proxies are trusted.}}",
+    "saveProxies": "Save trusted proxies"
   },
   "source": {
     "newTitle": "New sign-in source",
@@ -705,7 +712,6 @@
     "intro": "Where people sign in, and what their groups give them.",
     "path": "Path",
     "authentication": "Authentication",
-    "providerTitle": "Provider",
     "claimsTitle": "Claims",
     "claimsIntro": "The claims of the ID token that say who someone is. The provider's own names are given unless you change them.",
     "fields": {
@@ -752,10 +758,11 @@
       "oidc": "OIDC",
       "oidcHint": "Keycloak, Entra ID, Okta, Google: people sign in there, in the browser.",
       "ldap": "LDAP",
-      "ldapHint": "OpenLDAP, Active Directory: people sign in here with their directory's password."
+      "ldapHint": "OpenLDAP, Active Directory: people sign in here with their directory's password.",
+      "header": "Trusted header",
+      "headerHint": "A proxy in front signs people in itself, and says who they are in a header: taken from a trusted proxy only."
     },
     "ldap": {
-      "title": "Directory",
       "url": "Address",
       "starttls": "StartTLS",
       "bindDn": "Bind DN",
@@ -786,6 +793,20 @@
         "noGroups": "A user has the default role and what you give them.",
         "groupFilter": "'{dn}' or '{username}': (member='{dn}'), or (memberUid='{username}')."
       }
+    },
+    "titles": {
+      "oidc": "Provider",
+      "ldap": "Directory",
+      "header": "Trusted header"
+    },
+    "header": {
+      "userHeader": "User name header",
+      "groupsHeader": "Groups header",
+      "userHeaderNeeded": "The header that names the user is needed.",
+      "hints": {
+        "userHeader": "X-Forwarded-User unless you say otherwise.",
+        "groupsHeader": "Optional: the groups, separated by commas."
+      }
     }
   },
   "certificates": {
```

Change `docs/web-ui.md`:

```diff
@@ -71,9 +71,11 @@ repositories, blob stores and the installation's own settings.
     built-in `admin` signs in here then. The default role, which every signed-in
     user has, is chosen from the roles. A source's name leads to its page, where its
     settings are changed and the redirect address to register at the provider is
-    shown, with a copy button; New source makes one, OIDC or LDAP, off until it is
-    turned on.
+    shown, with a copy button; New source makes one, OIDC, LDAP or a trusted
+    header, off until it is turned on.
     A group's roles are rows: a group, and the role its members are given.
+    Trusted proxies lists the proxies in front of the gateway, an address or a
+    network a line; a line the server refuses is said by itself.
   - **Certificates** lists what the server trusts when it connects out over TLS,
     besides the usual public authorities, with each one's fingerprint and expiry.
     Fetch asks a server what it presents, its own certificate first; a certificate
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/screens/source.test.tsx src/screens/authentication.test.tsx && pnpm lint && pnpm typecheck`
Expected: 30 passed; `All matched files use Prettier code style!`; the types check.

- [ ] **Step 5: Commit**

```bash
git add frontend docs/web-ui.md
git commit -m "feat(ui): the trusted proxies, a line each; a trusted header source's form"
```

---

### Task 4: The header through the built stack, the guide, and what the plan settled

**Files:**
- Modify: `docs/administration.md`, `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`
- Test: `backend/tests/test_trusted_header.py`

**Interfaces:**
- Consumes: everything above, as it is; `tests.containers` (`HTTP_PORT`, `call`) and the fixtures `stack`, `administrator`.
- Produces: the proof through the gateway and uvicorn as they run, the guide's sections "Trusted header" and "Trusted proxies", and the spec's "Settled while building plan 15e".

This task's test proves what Tasks 1 to 3 built through the real gateway, so it passes once written. Running it is the step.

- [ ] **Step 1: Write the container test**

Create `backend/tests/test_trusted_header.py`:

```python
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
```

- [ ] **Step 2: Run it against the built stack**

Run (in `backend/`): `uv run pytest -q -m docker tests/test_trusted_header.py` (it builds the stack's images)
Expected: 1 passed (the stack is built first: a minute or two).

- [ ] **Step 3: Write the guide and the spec's rows**

Change `docs/administration.md`:

```diff
@@ -149,6 +149,59 @@ under Authentication, New source, LDAP, or at `POST /api/v1/auth-sources` with
 - A directory that does not answer within ten seconds is said by name:
   `503 source_unavailable`.
 
+#### Trusted header
+
+A proxy in front of MegooArti that signs people in itself (an SSO gateway: oauth2-proxy,
+Authelia, a load balancer's own sign-in) says who each request is from in a header.
+Make the source under Authentication, New source, Trusted header, or at
+`POST /api/v1/auth-sources` with `"kind": "header"`, and trust the proxy under
+Trusted proxies (below): the header is taken from a trusted proxy only.
+
+| Setting | What it is |
+| --- | --- |
+| `user_header` | The header that names who is signed in: `X-Forwarded-User` unless you say otherwise. A header HTTP gives a meaning of its own (`Authorization`, `Cookie`, `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`) is refused |
+| `groups_header` | The header that says their groups, separated by commas, or none: then nobody is given roles by a group |
+
+- **Each request is signed in by itself.** No session is kept: the header names who
+  it is from, the first request with a name nobody has makes the user, and every
+  request brings their groups' roles up to date.
+- **From anywhere else, it is refused.** A request with the header that does not come
+  through a trusted proxy is refused with `401`, and `trusted_header_refused` is
+  logged with the address it came from. So is a header that names nobody (empty,
+  longer than 256 characters, or with control characters).
+- **The proxy must set the header itself**, and drop whatever a client sent in it:
+  otherwise anyone it lets through names whoever they want.
+- **Changes come from the server's own pages only.** A browser sends a proxy's
+  sign-in with every request, wherever the page that makes it is. So a change
+  (`POST`, `PUT`, `PATCH`, `DELETE`) signed in by the header is taken only
+  with `Sec-Fetch-Site: same-origin`, or an `Origin` of the server's own address;
+  anything else is refused with `403 cross_site_request`.
+- **A user of a header source** has no password here, and gives package clients an API
+  token, which they make under Account.
+- **Test** says which headers the source reads.
+
+### Trusted proxies
+
+The gateway adds the address it sees to `X-Forwarded-For`. A proxy in front of the
+gateway (a load balancer, an SSO gateway) is listed under Authentication, Trusted
+proxies, or at `PUT /api/v1/settings/trusted-proxies` with
+`{"trusted_proxies": ["10.0.0.5", "10.1.0.0/16"]}`: addresses, or networks.
+
+- **What it changes.** For a request through a trusted proxy, the client is the
+  address the proxy says, `X-Forwarded-For` read from the right past every trusted
+  proxy; `X-Forwarded-Proto` says whether it came over HTTPS. That is the address
+  sessions and the log show, and the scheme of addresses the server writes (an OIDC
+  source's redirect address, without a base URL). A trusted header source's header
+  is taken through a trusted proxy only.
+- **Changed at once**, for every request, without a restart.
+- **What a client writes in `X-Forwarded-For` is not believed**: the addresses read are
+  those past the gateway and the proxies you trust, from the right; the first that is
+  not trusted is the client.
+- **Trust only your own proxies.** Whoever can reach the gateway from a trusted
+  address can say any client address, and send a trusted header source's header.
+- The gateway itself is trusted by the backend through `MEGOOARTI_FORWARDED_ALLOW_IPS`
+  (see [Configuration](configuration.md)), and never from this list.
+
 ### Trusted certificates
 
 MegooArti trusts the usual public authorities when it connects out over TLS: to a
```

Change `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`:

```diff
@@ -180,6 +180,20 @@ Settled here, by the designer:
 - A setting `trusted_proxies`: addresses and networks (CIDR). From them only, `X-Forwarded-For`'s last address not of a trusted proxy is the client's address, for throttling, sessions and the audit log. The gateway is trusted by default where Compose runs it.
 - The header source: the header of the user name (`X-Forwarded-User`), and of groups (optional, separated by commas), honoured only from a trusted proxy. A request with the header is that user's (created or refreshed as 4.2), as a session's: its changes need the same-origin check (CSRF's refusal of cross-site requests), as a cookie's do. A request with the header from any other address is refused (`401`).
 
+### Settled while building plan 15e
+
+| # | What | Why |
+| --- | --- | --- |
+| H1 | Who a request comes from is `megooarti.proxies.ProxiesMiddleware`'s to say, and uvicorn's proxy headers are off: `X-Forwarded-For` is read from the right. The backend's peer is believed as the deployment's (`MEGOOARTI_FORWARDED_ALLOW_IPS`, the gateway, `*` under Compose) or as a trusted proxy, every address before it as a trusted proxy only; the first not believed is the client. A hop that is not an address makes the client `unknown`. The request's `client` is that address; `state.proxied` says whether a proxy the administrator trusts passed it on. | Section 8: uvicorn trusts one list given at start; an administrator's changes while it runs. |
+| H2 | The gateway adds the address it sees to `X-Forwarded-For` (`$proxy_add_x_forwarded_for`), where it wrote its own in its place: what a client wrote is left of it, and believed only past proxies the administrator trusts. | Section 8, 14: a proxy in front of the gateway can be heard; a client cannot speak for itself. |
+| H3 | `X-Forwarded-Proto` is taken when the peer is believed, so the scheme of the addresses the server writes (an OIDC redirect without a base URL) is the client's. | As uvicorn did with its proxy headers. |
+| H4 | `trusted_proxies` is a setting of addresses and networks, at most 100, each kept as its network (`10.0.0.5` as `10.0.0.5/32`), once: `PUT /api/v1/settings/trusted-proxies` with `admin:security:write`, and shown in `GET /api/v1/settings/sign-in`. One that is neither is refused at its place (`trusted_proxies.<n>`). It is read at start and changed at once with the setting, as 15c's certificates (C8: one process). | Section 8. |
+| H5 | A header source's settings: `user_header` (`X-Forwarded-User` unless said) and `groups_header` (none unless said), a header's name each (an HTTP token, at most 64 characters), not `Authorization`, `Cookie`, `Host`, `X-Forwarded-For` or `X-Forwarded-Proto`, and not the same. It has no secret and takes no password; Test says what it reads. | Section 8. |
+| H6 | The header is read before `Authorization`, for every enabled header source in order: present without a trusted proxy, it is `401` and `trusted_header_refused` is logged; a name that is empty, longer than 256 characters or with control characters is `401`. The name is the user's identity at the source and their user name; at most 200 groups are read, separated by commas. A request with it is the user's, as `header`, an interactive principal, provisioned (4.2) at each request; a disabled user is `401`. | Section 8, 4.2. |
+| H7 | A change (`POST`, `PUT`, `PATCH`, `DELETE`) by a header's principal must say it comes from the server's own pages: `Sec-Fetch-Site` `same-origin` or `none`, or without it an `Origin` of the server's host or base URL; anything else, or neither, is `403 cross_site_request`. | Section 8: there is no CSRF token without a session, and a browser sends the proxy's sign-in to every page's request. |
+| H8 | Authentication has a Trusted proxies panel, a line an address or a network, a refused line said by itself; a source's kind is OIDC, LDAP or Trusted header, whose form is the two headers. | Section 4.3, 15d's L9. |
+| H9 | The container test sends the header through the gateway: refused, even with an `X-Forwarded-For` a client wrote, until every address is trusted; then the user is made with their group's role. | Section 12. |
+
 ## 9. The audit log (plan 15f)
 
 - `audit_records`: id, at, actor (user name, or none), how they signed in (`session`, `password`, `token`, `oauth`, `header`, `anonymous`, `system`), address, event (`user.created`, `repository.updated`, `sign_in.failed`, …), target's kind and name, changes (JSON: each changed field's before and after; a secret is `[redacted]`), request ID. Indexed by time, actor, event and target.
```

- [ ] **Step 4: Run every test**

Run (in `backend/`): `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; then (in `frontend/`): `pnpm vitest run`
Expected: Ruff: `453 files already formatted`, `All checks passed!`; pytest: 4288 passed, 2 skipped, 117 deselected (the `docker` tests); Vitest: 920 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tests docs
git commit -m "test: a trusted header through the built stack, refused until its proxy is trusted; docs: the trusted header and trusted proxies, and what plan 15e settled"
```
