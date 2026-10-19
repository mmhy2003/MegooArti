# MCP: OAuth Sign-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An MCP client that signs in with OAuth (claude.ai's connectors, the official client) finds MegooArti's sign-in from `/mcp`'s `401`, registers itself, sends the person to a consent page where they choose what it may do and for how long, and is given tokens that work at `/mcp` only; the person sees and revokes it under Account, Connected apps.

**Architecture:** MegooArti is both OAuth's authorization server and the protected resource. `security/oauth.py` keeps clients, approvals (grants) and hashed codes and tokens (three tables, migration `0009`); `security/api/oauth.py` serves the discovery documents (`/.well-known/…`), registration, authorize and token (`/oauth/…`), and the consent page's calls (`/api/v1/oauth/…`). An authorization request is sealed into the consent page's address, not stored. `agent_principal` takes an OAuth access token at `/mcp` beside an API token, and no other route does. The web UI gains the consent page (`/connect`) and Connected apps; the gateway passes `/.well-known/` and `/oauth/` to the backend.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy and Alembic, the MCP Python SDK 2.3.0 (its client's `OAuthClientProvider` in the tests); Next.js, React, TanStack Query, Vitest; Playwright and Docker Compose for the stack's tests.

**Spec:** [docs/superpowers/specs/2026-10-18-mcp-design.md](../specs/2026-10-18-mcp-design.md): section 7, E6, 9.2, 9.3, and the row of plan 14c in section 12; the product owner's ruling recorded as N10 (unchanged here).

## Decisions this plan settles

Task 5 writes these into the spec, as "Settled while building plan 14c".

| # | Decision | Reason |
| --- | --- | --- |
| O1 | An authorization request is checked at `/oauth/authorize`, then sealed (as a registry token is, `secrets_box.seal_at`, for 10 minutes) into the address of the consent page, `/connect?request=…`; nothing is stored until the person answers. A client or redirect address that is not known is answered with an error there, never redirected to; any other fault goes back to the client's redirect address with its `state`. | The consent page may wait for a sign-in; a request that is never answered leaves nothing behind (RFC 6749 4.1.2.1). |
| O2 | The consent page is the web UI's `/connect`, which only a person signed in sees (a visitor is sent to sign in, and back with the request); it reads `GET /api/v1/oauth/consent`, and answers with `POST /api/v1/oauth/consent` or `POST /api/v1/oauth/refusal`, which give the address the browser is sent to. They need a session, as making a token does. | 7.3. `/oauth/` itself is the backend's, through the gateway. |
| O3 | A code is an `OAuthToken` of kind `code` (60 seconds, used once, with its PKCE challenge and redirect address); a code or a refresh token used a second time deletes the approval and every token of it. Expired codes, tokens and approvals, and clients no approval names 30 days after they registered, are removed by the compaction job. | 7.4, 7.2: one table of hashes for every kind, and the job that already tends the server. |
| O4 | An access token signs in at `/mcp` only: `agent_principal` takes `mga_` and `mgo_`; every other route reads `mgo_` as no token of its (`401`). The principal of an OAuth token is the user's, narrowed by the approval's scopes, with `grant_id`; `whoami` says `kind: oauth` and the client's name. | E6. |
| O5 | `/mcp`'s `401` names `resource_metadata` in `WWW-Authenticate`, from the base URL or, without one, the request's own address; the discovery documents and the OAuth endpoints answer `503 temporarily_unavailable`, saying to set the base URL, where there is none. | 7.1: a client is told where to look even before an administrator has set it up. |
| O6 | Registration answers `token_endpoint_auth_method: none` whatever was asked (every client is public), and takes a redirect address that is `https`, or `http` to `127.0.0.1`, `localhost` or `[::1]`, without a fragment or credentials; at most ten. `client_name` is cut at 200 characters. | 7.2; the official client asks for `client_secret_post`, and goes on with what it is answered (RFC 7591 3.2.1). |
| O7 | Connected apps: `GET` and `DELETE /api/v1/me/connected-apps`, and `/api/v1/users/{id}/connected-apps` with `admin:tokens:read` and `write`; the web UI's Account, Connected apps, and a section of a user's page. `user_details` gives `connected_apps`, and `revoke_token` takes `connected_app` (an id) in place of `token` (in place of 14b's N8). | 7.6, 6.2. |
| O8 | The tests: every step in `tests/mcp/test_oauth.py`; the official client's OAuth provider in-process (`test_oauth_client.py`) and through the gateway of the built stack (`test_mcp_oauth_client.py`), the person's consent answered by the API as the consent page answers it; the consent page and Connected apps in the browser test. | 9.2, 9.3. The browser test's redirect address is the UI's own (`http://localhost`), so that no request leaves the site. |

## Global Constraints

- **Every code and token is random, given once, and kept as its SHA-256** (7.4): `mgc_` codes (60 seconds), `mgo_` access tokens (an hour, at most until the approval ends), `mgf_` refresh tokens (used once).
- **An OAuth access token works at `/mcp` only** (E6).
- **PKCE with S256, an exact redirect address, and `resource` naming `<base>/mcp` are required** (7.3).
- **A code or a refresh token used twice revokes the approval** (7.4).
- **The consent page is answered only by a person signed in, with a session**: a token cannot approve (D4 of the identity-access spec).
- **OAuth names the server by its base URL**, and refuses, saying so, where there is none (7.1).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Every test of the stack is marked `docker`.**

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

What could hurt a person using this most, and which test of this plan pins it.

1. **A stolen code or refresh token, replayed:** the approval is revoked, and every token of it stops working. Task 1: `test_a_code_is_traded_once_for_tokens_that_sign_in_to_mcp`, `test_a_refresh_token_is_used_once_and_used_twice_revokes_the_approval`.
2. **A client sending the browser to an address it did not register (an open redirect):** answered with an error at `/oauth/authorize`, never redirected. Task 1: `test_authorize_answers_a_stranger_itself_and_sends_other_faults_back`.
3. **The consent page reached by someone not signed in, or answered with a token:** sent to sign in and back with the request; a token is refused. Tasks 1 and 3: `test_the_consent_page_is_told_who_asks_and_only_a_person_signed_in_may_answer`, and the rules' test of `/connect`.
4. **An OAuth access token used on the REST API or a package client:** `401` (E6). Task 1: `test_an_oauth_token_works_at_mcp_only`.
5. **A server without a base URL:** the discovery documents say to set it, rather than naming a wrong address. Task 1: `test_without_a_base_url_oauth_says_to_set_one`.

---

### Task 1: OAuth: discovery, registration, consent, tokens, and sign-in at `/mcp`

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0009_add_oauth.py`, `backend/src/megooarti/security/oauth.py`, `backend/src/megooarti/security/api/oauth.py`
- Modify: `backend/src/megooarti/security/models.py`, `backend/src/megooarti/security/authentication.py`, `backend/src/megooarti/main.py`, `backend/src/megooarti/mcp/system.py`, `backend/src/megooarti/mcp/tools.py`, `frontend/openapi.json` (written by a command)
- Test: `backend/tests/mcp/oauth_steps.py`, `backend/tests/mcp/test_oauth.py`, `backend/tests/mcp/test_oauth_client.py`; modify `backend/tests/mcp/conftest.py`, `backend/tests/test_route_guards.py`

**Interfaces:**
- Consumes: `secrets_box.seal_at`, `unseal_within`; `keys.hash_secret`; `authentication._authenticate_token`, `_checked`, `_no_match`, `build_principal`, `unauthorized`, `require_interactive`, `client_ip`; `settings_store.get_setting`; `users.get_user`; 14a's `agent` fixture and `tools`.
- Produces:
  - Models `OAuthClient`, `OAuthGrant`, `OAuthToken`.
  - `security.oauth`: `ACCESS_PREFIX`, `REFRESH_PREFIX`, `CODE_PREFIX`, `ACCESS`, `LASTS`, `REGISTRATIONS_PER_HOUR`, `OAuthError(error, description, status)`, `register(db, name, redirect_uris, address, now)`, `get_client(db, client_id)`, `Request`, `seal_request`, `open_request`, `redirect_with`, `approve(db, user, request, access, lasts, now) -> str`, `refuse(request) -> str`, `exchange_code(...)`, `refresh(...)`, `find_access(db, value, now) -> OAuthGrant | None`, `Approval`, `approvals(db, user_id, now)`, `revoke(db, user_id, grant_id)`, `forget(db, now)`, `describe(client)`.
  - `security.api.oauth`: routers `well_known`, `endpoints`, `consent`; `issuer(db)`.
  - `Principal.grant_id`; `agent_principal` taking `mgo_`; `whoami`'s `kind: "oauth"`.
  - For tests: `oauth_steps` (`BASE`, `REDIRECT`, `pkce`, `register`, `sealed_request`, `approved_code`, `tokens`, `query_of`), and the fixtures `based` and `browser`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/mcp/oauth_steps.py`:

```python
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
```

Change `backend/tests/mcp/conftest.py`:

```diff
@@ -8,10 +8,14 @@ from typing import Any
 import httpx2
 import pytest
 from fastapi import FastAPI
+from httpx import ASGITransport, AsyncClient
 from mcp import Client
 from mcp.client.streamable_http import streamable_http_client
 from mcp.types import CallToolResult
 
+from megooarti.system.settings_store import set_setting
+from tests.accounts import sign_in
+from tests.mcp.oauth_steps import BASE
 from tests.repositories.conftest import fake_remote  # noqa: F401  (a fixture of these tests too)
 
 
@@ -42,3 +46,19 @@ def refusal(result: CallToolResult) -> str:
     """What a tool that refused said."""
     assert result.is_error, result.structured_content
     return "\n".join(getattr(part, "text", "") for part in result.content)
+
+
+@pytest.fixture
+async def based(db):
+    """The server's base URL, which OAuth names itself by."""
+    await set_setting(db, "base_url", BASE)
+    await db.commit()
+
+
+@pytest.fixture
+async def browser(app, based, make_user):
+    """A person signed in to the web UI, in a browser of their own."""
+    await make_user("dev", roles=["admin"])
+    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as http:
+        await sign_in(http, "dev")
+        yield http
```

Create `backend/tests/mcp/test_oauth.py`:

```python
"""OAuth sign-in to /mcp (MCP spec 7, 9.2): what a client discovers, registers, is sent
to approve, and trades its code and refresh tokens for; an access token that works at
/mcp only; an approval revoked where a code or a refresh token is used twice."""

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from megooarti.clock import utcnow
from megooarti.security import oauth, users
from megooarti.security.models import OAuthClient, OAuthGrant, OAuthToken
from tests.mcp.oauth_steps import (
    BASE,
    LIST_TOOLS,
    MCP,
    REDIRECT,
    approved_code,
    authorization,
    pkce,
    query_of,
    register,
    sealed_request,
    tokens,
)


async def mcp(client: AsyncClient, token: str):
    return await client.post(
        "/mcp", json=LIST_TOOLS, headers=MCP | {"Authorization": f"Bearer {token}"}
    )


async def test_a_client_finds_who_signs_it_in_to_mcp(client, based):
    resource = await client.get("/.well-known/oauth-protected-resource/mcp")
    root = await client.get("/.well-known/oauth-protected-resource")
    server = await client.get("/.well-known/oauth-authorization-server")
    refused = await client.post("/mcp", json=LIST_TOOLS, headers=MCP)

    assert (
        resource.json()
        == root.json()
        == {
            "resource": f"{BASE}/mcp",
            "authorization_servers": [BASE],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [],
        }
    )
    described = server.json()
    assert described["issuer"] == BASE
    assert described["authorization_endpoint"] == f"{BASE}/oauth/authorize"
    assert described["token_endpoint"] == f"{BASE}/oauth/token"
    assert described["registration_endpoint"] == f"{BASE}/oauth/register"
    assert described["code_challenge_methods_supported"] == ["S256"]
    assert described["token_endpoint_auth_methods_supported"] == ["none"]
    assert refused.status_code == 401
    assert refused.headers["WWW-Authenticate"] == (
        f'Bearer realm="MegooArti", '
        f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"'
    )


async def test_without_a_base_url_oauth_says_to_set_one(client):
    answer = await client.get("/.well-known/oauth-authorization-server")

    assert answer.status_code == 503
    assert answer.json()["error"] == "temporarily_unavailable"
    assert "base URL" in answer.json()["error_description"]


async def test_a_client_registers_itself_with_where_it_is_sent_back_to(client, based):
    made = await client.post(
        "/oauth/register",
        json={"client_name": "Claude Code", "redirect_uris": [REDIRECT, "https://claude.ai/cb"]},
    )
    remote = await client.post(
        "/oauth/register", json={"client_name": "x", "redirect_uris": ["http://example.org/cb"]}
    )
    fragment = await client.post(
        "/oauth/register", json={"redirect_uris": ["https://example.org/cb#here"]}
    )
    huge = await client.post("/oauth/register", content=b'{"client_name": "' + b"x" * 17000 + b'"}')

    assert made.status_code == 201
    said = made.json()
    assert (said["client_name"], said["redirect_uris"]) == (
        "Claude Code",
        [REDIRECT, "https://claude.ai/cb"],
    )
    assert said["token_endpoint_auth_method"] == "none"
    assert said["grant_types"] == ["authorization_code", "refresh_token"]
    assert (remote.status_code, remote.json()["error"]) == (400, "invalid_redirect_uri")
    assert (fragment.status_code, fragment.json()["error"]) == (400, "invalid_redirect_uri")
    assert huge.status_code == 413


async def test_registrations_from_one_address_are_limited_an_hour(client, based):
    for _ in range(oauth.REGISTRATIONS_PER_HOUR):
        await register(client)

    refused = await client.post("/oauth/register", json={"redirect_uris": [REDIRECT]})

    assert (refused.status_code, refused.json()["error"]) == (429, "too_many_registrations")


async def test_authorize_answers_a_stranger_itself_and_sends_other_faults_back(client, based):
    client_id = await register(client)
    _, challenge = pkce()

    unknown = await client.get("/oauth/authorize", params=authorization("nobody", challenge))
    elsewhere = await client.get(
        "/oauth/authorize",
        params=authorization(client_id, challenge, redirect_uri="http://127.0.0.1:1/x"),
    )
    plain = await client.get(
        "/oauth/authorize",
        params=authorization(client_id, challenge, code_challenge_method="plain"),
    )
    other = await client.get(
        "/oauth/authorize",
        params=authorization(client_id, challenge, resource="https://other.example/mcp"),
    )

    assert (unknown.status_code, unknown.json()["error"]) == (400, "invalid_client")
    assert (elsewhere.status_code, elsewhere.json()["error"]) == (400, "invalid_request")
    for answer, error in ((plain, "invalid_request"), (other, "invalid_target")):
        assert answer.status_code == 302
        back = query_of(answer.headers["Location"])
        assert answer.headers["Location"].startswith(REDIRECT)
        assert (back["error"], back["state"]) == (error, "the-clients-state")


async def test_the_consent_page_is_told_who_asks_and_only_a_person_signed_in_may_answer(
    client, browser, make_token, sessionmaker
):
    client_id = await register(client)
    _, challenge = pkce()
    sealed = await sealed_request(client, client_id, challenge)
    async with sessionmaker() as db:
        dev = await users.get_user_by_username(db, "dev")
    token = await make_token(dev, "agent")

    shown = await browser.get("/api/v1/oauth/consent", params={"request": sealed})
    stranger = await client.get("/api/v1/oauth/consent", params={"request": sealed})
    by_token = await client.get(
        "/api/v1/oauth/consent",
        params={"request": sealed},
        headers={"Authorization": f"Bearer {token}"},
    )
    garbled = await browser.get("/api/v1/oauth/consent", params={"request": sealed[:-4] + "AAAA"})
    refused = await browser.post("/api/v1/oauth/refusal", json={"request": sealed})

    assert shown.json() == {"client": "Claude", "redirect_host": "127.0.0.1"}
    assert stranger.status_code == 401
    assert by_token.status_code == 403
    assert (garbled.status_code, garbled.json()["error"]["code"]) == (410, "request_expired")
    back = query_of(refused.json()["redirect"])
    assert back == {"error": "access_denied", "state": "the-clients-state"}


async def test_a_code_is_traded_once_for_tokens_that_sign_in_to_mcp(client, browser):
    client_id, code = await approved_code(client, browser)

    issued = await tokens(client, client_id, code)
    signed_in = await mcp(client, issued["access_token"])
    again = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code.split(" ")[0],
            "redirect_uri": REDIRECT,
            "code_verifier": code.split(" ")[1],
        },
    )
    after = await mcp(client, issued["access_token"])

    assert issued["token_type"] == "Bearer"
    assert issued["expires_in"] == 3600
    assert issued["access_token"].startswith("mgo_")
    assert issued["refresh_token"].startswith("mgf_")
    assert signed_in.status_code == 200
    assert (again.status_code, again.json()["error"]) == (400, "invalid_grant")
    assert after.status_code == 401  # a code used twice revokes its approval


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code_verifier", "not-the-verifier"),
        ("redirect_uri", "http://127.0.0.1:1/x"),
        ("client_id", "other"),
    ],
)
async def test_a_code_is_refused_with_what_it_was_not_given_with(client, browser, field, value):
    client_id, code = await approved_code(client, browser)
    form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code.split(" ")[0],
        "redirect_uri": REDIRECT,
        "code_verifier": code.split(" ")[1],
    }

    answer = await client.post("/oauth/token", data=form | {field: value})

    assert (answer.status_code, answer.json()["error"]) == (400, "invalid_grant")


async def test_an_expired_code_is_refused(client, browser, sessionmaker):
    client_id, code = await approved_code(client, browser)
    async with sessionmaker() as db:
        await db.execute(
            update(OAuthToken)
            .where(OAuthToken.kind == "code")
            .values(expires_at=utcnow() - timedelta(seconds=1))
        )
        await db.commit()

    answer = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code.split(" ")[0],
            "redirect_uri": REDIRECT,
            "code_verifier": code.split(" ")[1],
        },
    )

    assert answer.json()["error_description"] == "The code has expired."


async def test_a_refresh_token_is_used_once_and_used_twice_revokes_the_approval(client, browser):
    client_id, code = await approved_code(client, browser)
    first = await tokens(client, client_id, code)
    form = {"grant_type": "refresh_token", "client_id": client_id}

    second = await client.post(
        "/oauth/token", data=form | {"refresh_token": first["refresh_token"]}
    )
    replayed = await client.post(
        "/oauth/token", data=form | {"refresh_token": first["refresh_token"]}
    )
    newest = await mcp(client, second.json()["access_token"])

    assert second.status_code == 200
    assert second.json()["refresh_token"] != first["refresh_token"]
    assert (replayed.status_code, replayed.json()["error"]) == (400, "invalid_grant")
    assert newest.status_code == 401  # the approval is gone, and its tokens with it


async def test_an_oauth_token_works_at_mcp_only(client, browser):
    client_id, code = await approved_code(client, browser)
    access = (await tokens(client, client_id, code))["access_token"]
    bearer = {"Authorization": f"Bearer {access}"}

    api = await client.get("/api/v1/me/tokens", headers=bearer)
    search = await client.get("/api/v1/search", headers=bearer)
    content = await client.get("/repository/anything/file", headers=bearer)

    assert (api.status_code, search.status_code, content.status_code) == (401, 401, 401)


async def test_what_was_approved_is_what_the_agent_may_do(client, browser, agent):
    read_id, read_code = await approved_code(client, browser, access="read")
    all_id, all_code = await approved_code(client, browser, access="all", lasts="1d")
    reading = (await tokens(client, read_id, read_code))["access_token"]
    everything = (await tokens(client, all_id, all_code))["access_token"]

    async with agent(reading) as session:
        theirs = {tool.name for tool in (await session.list_tools()).tools}
        who = (await session.call_tool("whoami", {})).structured_content
    async with agent(everything) as session:
        ours = {tool.name for tool in (await session.list_tools()).tools}
        whose = (await session.call_tool("whoami", {})).structured_content

    assert "create_repository" not in theirs and "search_packages" in theirs
    assert "create_repository" in ours
    assert who["token"]["kind"] == "oauth"
    assert who["token"]["name"] == "Claude"
    assert who["token"]["scopes"] == oauth.ACCESS["read"]
    assert whose["token"]["scopes"] is None
    assert whose["token"]["expires_at"] is not None  # a day


async def test_an_approval_that_expired_or_a_user_disabled_signs_in_no_more(
    client, browser, sessionmaker
):
    client_id, code = await approved_code(client, browser)
    access = (await tokens(client, client_id, code))["access_token"]
    async with sessionmaker() as db:
        await db.execute(update(OAuthGrant).values(expires_at=utcnow() - timedelta(seconds=1)))
        await db.commit()
    expired = await mcp(client, access)
    client_id, code = await approved_code(client, browser)
    other = (await tokens(client, client_id, code))["access_token"]
    async with sessionmaker() as db:
        dev = await users.get_user_by_username(db, "dev")
        await users.update_user(db, dev, {"status": "disabled"})
        await db.commit()

    disabled = await mcp(client, other)

    assert (expired.status_code, disabled.status_code) == (401, 401)


async def test_what_ended_is_forgotten_and_a_client_no_one_approved_after_a_month(
    client, browser, sessionmaker
):
    client_id, _ = await approved_code(client, browser)
    lonely = await register(client, name="Never approved")
    async with sessionmaker() as db:
        await db.execute(update(OAuthClient).values(registered_at=utcnow() - timedelta(days=31)))
        await db.commit()
        await oauth.forget(db, utcnow())
        await db.commit()
        kept = set(map(str, await db.scalars(select(OAuthClient.id))))

    assert client_id in kept
    assert lonely not in kept
```

Create `backend/tests/mcp/test_oauth_client.py`:

```python
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
```

Change `backend/tests/test_route_guards.py`:

```diff
@@ -16,6 +16,15 @@ OPEN = {
     "/api/v1/status/live",  # health checks, required to be unauthenticated (SYS-2)
     "/api/v1/status/ready",
     "/api/v1/auth/login",  # this is where credentials are presented
+    # OAuth (MCP spec 7): what a client discovers is public (RFC 9728, RFC 8414); any
+    # client may register (RFC 7591); authorize sends a person to the consent page, where
+    # they sign in; token takes a code or a refresh token, which are the credentials.
+    "/.well-known/oauth-protected-resource",
+    "/.well-known/oauth-protected-resource/mcp",
+    "/.well-known/oauth-authorization-server",
+    "/oauth/register",
+    "/oauth/authorize",
+    "/oauth/token",
 }
 # The API description, its viewer and the files the viewer loads. They describe the
 # API's shape, not its data, and are left open by design.
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/mcp/test_oauth.py tests/mcp/test_oauth_client.py tests/test_route_guards.py`
Expected: 1 error during collection: `ImportError: cannot import name 'oauth' from 'megooarti.security'`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/models.py`:

```diff
@@ -107,6 +107,55 @@ class ApiToken(Base):
     last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
 
 
+class OAuthClient(Base):
+    """A client that registered itself for OAuth (RFC 7591): an agent's host."""
+
+    __tablename__ = "oauth_clients"
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    name: Mapped[str] = mapped_column(String(200))
+    redirect_uris: Mapped[list[Any]] = mapped_column(JSONB)
+    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
+    registered_from: Mapped[str] = mapped_column(String(64))
+
+
+class OAuthGrant(Base):
+    """An approval: what a user let a client do as them, and until when."""
+
+    __tablename__ = "oauth_grants"
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    user_id: Mapped[uuid.UUID] = mapped_column(
+        ForeignKey("users.id", ondelete="CASCADE"), index=True
+    )
+    client_id: Mapped[uuid.UUID] = mapped_column(
+        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
+    )
+    # Patterns that narrow the user's permissions, as an API token's scopes do; null: none.
+    scopes: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True))
+    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
+    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+
+
+class OAuthToken(Base):
+    """A code, an access token or a refresh token of a grant, kept as its hash."""
+
+    __tablename__ = "oauth_tokens"
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    grant_id: Mapped[uuid.UUID] = mapped_column(
+        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
+    )
+    kind: Mapped[str] = mapped_column(String(16))  # "code", "access" or "refresh"
+    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
+    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
+    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
+    # A code's: what the token request must show again (RFC 7636, RFC 6749 4.1.3).
+    code_challenge: Mapped[str | None] = mapped_column(String(128))
+    redirect_uri: Mapped[str | None] = mapped_column(String(2048))
+
+
 class LoginFailure(Base):
     __tablename__ = "login_failures"
 
```

Create `backend/src/megooarti/migrations/versions/0009_add_oauth.py`:

```python
"""add OAuth's clients, approvals and tokens, for AI agents' sign-in to /mcp

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_from", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_grants_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_grants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_grants")),
    )
    op.create_index(op.f("ix_oauth_grants_client_id"), "oauth_grants", ["client_id"])
    op.create_index(op.f("ix_oauth_grants_user_id"), "oauth_grants", ["user_id"])
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_challenge", sa.String(length=128), nullable=True),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("fk_oauth_tokens_grant_id_oauth_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_tokens_token_hash")),
    )
    op.create_index(op.f("ix_oauth_tokens_grant_id"), "oauth_tokens", ["grant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_tokens_grant_id"), table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_index(op.f("ix_oauth_grants_user_id"), table_name="oauth_grants")
    op.drop_index(op.f("ix_oauth_grants_client_id"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")
```

Create `backend/src/megooarti/security/oauth.py`:

```python
"""OAuth 2.1 for AI agents' sign-in to /mcp (MCP spec 7): clients that register
themselves, a user's approval of one, and the codes and tokens that follow from it.

Every code and token is random, given once, and kept as its hash, as API tokens are.
An approval's request is sealed into the address of the consent page, not stored.
"""

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti import secrets_box
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.security.keys import hash_secret
from megooarti.security.models import OAuthClient, OAuthGrant, OAuthToken, User

ACCESS_PREFIX = "mgo_"
REFRESH_PREFIX = "mgf_"
CODE_PREFIX = "mgc_"
ACCESS_SECONDS = 3600
CODE_SECONDS = 60
# How long the consent page may take: a person reads it, perhaps signs in first.
REQUEST_SECONDS = 600
REGISTRATIONS_PER_HOUR = 20
# A client that no approval names is forgotten this long after it registered.
UNAPPROVED_DAYS = 30
# A refresh token of an approval that does not expire still has to have an end.
_FOREVER = timedelta(days=3650)
_REQUEST = "oauth-request"

# What the consent page offers (spec 7.3): what an agent may do, and for how long.
ACCESS = {
    "read": ["repository:*:*:browse", "repository:*:*:read", "admin:*:read"],
    "all": None,
}
LASTS = {
    "1d": timedelta(days=1),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "forever": None,
}
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}


class OAuthError(Exception):
    """An answer of OAuth's own shape (RFC 6749 5.2, RFC 7591 3.2.2)."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error, self.description, self.status = error, description, status


def _new(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def acceptable_redirect(address: str) -> bool:
    """`https`, or `http` to this machine (a desktop client's own listener), without a
    fragment or credentials (RFC 6749 3.1.2, the MCP authorization spec)."""
    try:
        parts = urlsplit(address)
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in _LOOPBACK


# --- Registration ---------------------------------------------------------------------


async def register(
    db: AsyncSession, name: str, redirect_uris: list[str], address: str, now: datetime
) -> OAuthClient:
    """A client, registered by itself (RFC 7591), from `address`."""
    lately = await db.scalar(
        select(func.count())
        .select_from(OAuthClient)
        .where(
            OAuthClient.registered_from == address,
            OAuthClient.registered_at > now - timedelta(hours=1),
        )
    )
    if (lately or 0) >= REGISTRATIONS_PER_HOUR:
        raise OAuthError(
            "too_many_registrations", "Too many clients registered from here; try later.", 429
        )
    if not redirect_uris or len(redirect_uris) > 10:
        raise OAuthError("invalid_redirect_uri", "Give one to ten redirect addresses.")
    for uri in redirect_uris:
        if len(uri) > 2048 or not acceptable_redirect(uri):
            raise OAuthError(
                "invalid_redirect_uri",
                "A redirect address is https, or http to this machine, with no fragment.",
            )
    client = OAuthClient(
        name=(name.strip() or "An application")[:200],
        redirect_uris=redirect_uris,
        registered_at=now,
        registered_from=address[:64],
    )
    db.add(client)
    await db.flush()
    return client


async def get_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    try:
        return await db.get(OAuthClient, uuid.UUID(client_id))
    except ValueError:
        return None


# --- Authorization --------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """What a client asked to be authorized for, carried through the consent page."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    state: str | None


def seal_request(settings: Settings, request: Request, now: datetime) -> str:
    stated = {"for": _REQUEST, **vars(request)}
    return secrets_box.seal_at(settings, json.dumps(stated), now)


def open_request(settings: Settings, sealed: str, now: datetime) -> Request | None:
    """The request a consent page was given, if it is one and not too old."""
    text = secrets_box.unseal_within(settings, sealed, REQUEST_SECONDS, now)
    if text is None:
        return None
    try:
        stated = json.loads(text)
        if stated.pop("for") != _REQUEST:
            return None
        return Request(**stated)
    except (ValueError, KeyError, TypeError):
        return None


def redirect_with(address: str, **values: str | None) -> str:
    """The client's redirect address with these in its query, beside its own."""
    parts = urlsplit(address)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query += [(name, value) for name, value in values.items() if value is not None]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def approve(
    db: AsyncSession, user: User, request: Request, access: str, lasts: str, now: datetime
) -> str:
    """An approval of the request, and where the browser goes with its code."""
    lifetime = LASTS[lasts]
    grant = OAuthGrant(
        user_id=user.id,
        client_id=uuid.UUID(request.client_id),
        scopes=ACCESS[access],
        expires_at=None if lifetime is None else now + lifetime,
        created_at=now,
    )
    db.add(grant)
    await db.flush()
    code = _new(CODE_PREFIX)
    db.add(
        OAuthToken(
            grant_id=grant.id,
            kind="code",
            token_hash=hash_secret(code),
            expires_at=now + timedelta(seconds=CODE_SECONDS),
            code_challenge=request.code_challenge,
            redirect_uri=request.redirect_uri,
        )
    )
    await db.flush()
    return redirect_with(request.redirect_uri, code=code, state=request.state)


def refuse(request: Request) -> str:
    return redirect_with(request.redirect_uri, error="access_denied", state=request.state)


# --- Tokens ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issued:
    access_token: str
    refresh_token: str
    expires_in: int


async def _issue(db: AsyncSession, grant: OAuthGrant, now: datetime) -> Issued:
    access, refresh = _new(ACCESS_PREFIX), _new(REFRESH_PREFIX)
    ends = grant.expires_at or now + _FOREVER
    access_ends = min(now + timedelta(seconds=ACCESS_SECONDS), ends)
    db.add(
        OAuthToken(
            grant_id=grant.id,
            kind="access",
            token_hash=hash_secret(access),
            expires_at=access_ends,
        )
    )
    db.add(
        OAuthToken(
            grant_id=grant.id, kind="refresh", token_hash=hash_secret(refresh), expires_at=ends
        )
    )
    await db.flush()
    return Issued(access, refresh, max(int((access_ends - now).total_seconds()), 0))


async def _held(db: AsyncSession, kind: str, value: str) -> tuple[OAuthToken, OAuthGrant] | None:
    found = await db.scalar(
        select(OAuthToken).where(
            OAuthToken.kind == kind, OAuthToken.token_hash == hash_secret(value)
        )
    )
    if found is None:
        return None
    grant = await db.get(OAuthGrant, found.grant_id)
    return None if grant is None else (found, grant)


def _invalid(description: str) -> OAuthError:
    return OAuthError("invalid_grant", description)


def _challenge_of(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii", errors="replace")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def exchange_code(
    db: AsyncSession,
    client_id: str,
    code: str,
    redirect_uri: str,
    verifier: str,
    now: datetime,
) -> Issued:
    """Tokens for a code (RFC 6749 4.1.3, RFC 7636 4.6). A code used twice revokes the
    approval it was given for (RFC 6749 4.1.2)."""
    held = await _held(db, "code", code)
    if held is None:
        raise _invalid("No such code.")
    token, grant = held
    if token.used_at is not None:
        await db.delete(grant)
        raise _invalid("The code was used already; the approval is revoked.")
    if token.expires_at <= now:
        raise _invalid("The code has expired.")
    if str(grant.client_id) != client_id:
        raise _invalid("The code was given to another client.")
    if token.redirect_uri != redirect_uri:
        raise _invalid("The redirect address is not the one the code was given with.")
    if not secrets.compare_digest(_challenge_of(verifier), token.code_challenge or ""):
        raise _invalid("The code verifier is not the code challenge's.")
    token.used_at = now
    return await _issue(db, grant, now)


async def refresh(db: AsyncSession, client_id: str, value: str, now: datetime) -> Issued:
    """New tokens for a refresh token, which is used once: one used twice was stolen, and
    revokes the approval (OAuth 2.1 4.3.1)."""
    held = await _held(db, "refresh", value)
    if held is None:
        raise _invalid("No such refresh token.")
    token, grant = held
    if token.used_at is not None:
        await db.delete(grant)
        raise _invalid("The refresh token was used already; the approval is revoked.")
    if token.expires_at <= now or (grant.expires_at is not None and grant.expires_at <= now):
        raise _invalid("The approval has expired.")
    if str(grant.client_id) != client_id:
        raise _invalid("The refresh token was given to another client.")
    token.used_at = now
    return await _issue(db, grant, now)


async def find_access(db: AsyncSession, value: str, now: datetime) -> OAuthGrant | None:
    """The approval an access token stands for, while both last."""
    held = await _held(db, "access", value)
    if held is None:
        return None
    token, grant = held
    if token.expires_at <= now or (grant.expires_at is not None and grant.expires_at <= now):
        return None
    if grant.last_used_at is None or now - grant.last_used_at > timedelta(seconds=60):
        grant.last_used_at = now
    return grant


# --- Approvals ------------------------------------------------------------------------


@dataclass(frozen=True)
class Approval:
    id: uuid.UUID
    client: str  # its name, in its own words
    redirect_host: str
    scopes: list[str] | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


async def approvals(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> list[Approval]:
    """A user's approvals that have not expired, the newest first."""
    rows = await db.execute(
        select(OAuthGrant, OAuthClient)
        .join(OAuthClient, OAuthClient.id == OAuthGrant.client_id)
        .where(OAuthGrant.user_id == user_id)
        .where((OAuthGrant.expires_at.is_(None)) | (OAuthGrant.expires_at > now))
        .order_by(OAuthGrant.created_at.desc())
    )
    return [
        Approval(
            id=grant.id,
            client=client.name,
            redirect_host=urlsplit(client.redirect_uris[0]).hostname or "",
            scopes=grant.scopes,
            created_at=grant.created_at,
            last_used_at=grant.last_used_at,
            expires_at=grant.expires_at,
        )
        for grant, client in rows
    ]


async def revoke(db: AsyncSession, user_id: uuid.UUID, grant_id: uuid.UUID) -> None:
    """Revoke one of a user's approvals, and its tokens with it. Raises 404."""
    grant = await db.scalar(
        select(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.user_id == user_id)
    )
    if grant is None:
        raise ApiError(404, "not_found", "No such connected app.")
    await db.delete(grant)
    await db.flush()


async def forget(db: AsyncSession, now: datetime) -> None:
    """Remove what has expired, and clients no approval names a month after they came."""
    await db.execute(delete(OAuthToken).where(OAuthToken.expires_at <= now))
    await db.execute(
        delete(OAuthGrant).where(OAuthGrant.expires_at.is_not(None), OAuthGrant.expires_at <= now)
    )
    named = exists().where(OAuthGrant.client_id == OAuthClient.id)
    await db.execute(
        delete(OAuthClient).where(
            OAuthClient.registered_at <= now - timedelta(days=UNAPPROVED_DAYS), ~named
        )
    )


def describe(client: OAuthClient) -> dict[str, Any]:
    """A client as registration answers it (RFC 7591 3.2.1)."""
    return {
        "client_id": str(client.id),
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "client_id_issued_at": int(client.registered_at.timestamp()),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
```

Create `backend/src/megooarti/security/api/oauth.py`:

```python
"""OAuth's addresses (MCP spec 7): what a client finds (RFC 9728, RFC 8414), registers
at (RFC 7591), sends a person to (authorize), and trades a code at (token); and the
web UI's consent page's calls."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.security import oauth
from megooarti.security.authentication import Principal, client_ip, require_interactive
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

well_known = APIRouter(prefix="/.well-known", include_in_schema=False)
endpoints = APIRouter(prefix="/oauth", include_in_schema=False)
consent = APIRouter(prefix="/oauth", tags=["account"])

_NO_STORE = {"Cache-Control": "no-store"}


async def issuer(db: AsyncSession) -> str:
    """This server as OAuth names it: its base URL, which must be set (spec 7.1)."""
    base = await get_setting(db, "base_url")
    if not base:
        raise oauth.OAuthError(
            "temporarily_unavailable",
            "Sign-in with OAuth needs the server's base URL: an administrator sets it "
            "under System.",
            503,
        )
    return str(base).rstrip("/")


def _answer(error: oauth.OAuthError) -> JSONResponse:
    return JSONResponse(
        {"error": error.error, "error_description": error.description},
        status_code=error.status,
        headers=_NO_STORE,
    )


# --- Discovery ------------------------------------------------------------------------


@well_known.get("/oauth-protected-resource/mcp")
@well_known.get("/oauth-protected-resource")
async def protected_resource(db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """What protects /mcp, and who signs a client in to it (RFC 9728)."""
    try:
        base = await issuer(db)
    except oauth.OAuthError as error:
        return _answer(error)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [],
        }
    )


@well_known.get("/oauth-authorization-server")
async def authorization_server(db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """How a client is signed in here (RFC 8414)."""
    try:
        base = await issuer(db)
    except oauth.OAuthError as error:
        return _answer(error)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [],
        }
    )


# --- Registration ---------------------------------------------------------------------


class Registration(BaseModel):
    client_name: str = Field(default="", max_length=200)
    redirect_uris: list[str] = Field(default=[], max_length=10)


@endpoints.post("/register")
async def register(request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A client registers itself (RFC 7591), as any may: a person still approves it."""
    body = await request.body()
    if len(body) > 16 * 1024:
        return _answer(oauth.OAuthError("invalid_client_metadata", "At most 16 KiB.", 413))
    try:
        said = Registration.model_validate_json(body)
    except ValueError:
        return _answer(oauth.OAuthError("invalid_client_metadata", "The metadata is not valid."))
    try:
        client = await oauth.register(
            db, said.client_name, said.redirect_uris, client_ip(request), utcnow()
        )
    except oauth.OAuthError as error:
        return _answer(error)
    described = oauth.describe(client)
    await db.commit()
    log.info("oauth_client_registered", client=described["client_id"], name=client.name)
    return JSONResponse(described, status_code=201, headers=_NO_STORE)


# --- Authorization --------------------------------------------------------------------


@endpoints.get("/authorize", response_model=None)
async def authorize(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    state: str | None = None,
    resource: str = "",
    db: AsyncSession = Depends(get_session),
) -> JSONResponse | RedirectResponse:
    """Check what a client asks, and send the person to the consent page with it sealed.

    A client or redirect address that is not known is answered here, never redirected
    to (RFC 6749 4.1.2.1); anything else wrong goes back to the client.
    """
    try:
        base = await issuer(db)
    except oauth.OAuthError as error:
        return _answer(error)
    client = await oauth.get_client(db, client_id)
    if client is None:
        return _answer(oauth.OAuthError("invalid_client", "No such client."))
    if redirect_uri not in client.redirect_uris:
        return _answer(
            oauth.OAuthError("invalid_request", "The redirect address is not one it registered.")
        )

    def back(error: str, description: str) -> RedirectResponse:
        address = oauth.redirect_with(
            redirect_uri, error=error, error_description=description, state=state
        )
        return RedirectResponse(address, status_code=302)

    if response_type != "code":
        return back("unsupported_response_type", "Only the code flow is offered.")
    if code_challenge_method != "S256" or not 43 <= len(code_challenge) <= 128:
        return back("invalid_request", "PKCE with S256 is required.")
    if resource.rstrip("/") != f"{base}/mcp":
        return back("invalid_target", f"The resource is {base}/mcp.")
    sealed = oauth.seal_request(
        request.app.state.settings,
        oauth.Request(str(client.id), redirect_uri, code_challenge, state),
        utcnow(),
    )
    return RedirectResponse(f"{base}/connect?request={sealed}", status_code=302)


# --- Tokens ---------------------------------------------------------------------------


@endpoints.post("/token")
async def token(
    grant_type: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    redirect_uri: Annotated[str, Form()] = "",
    code_verifier: Annotated[str, Form()] = "",
    refresh_token: Annotated[str, Form()] = "",
    resource: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Tokens for a code, or for a refresh token (RFC 6749 4.1.3, 6)."""
    now = utcnow()
    try:
        base = await issuer(db)
        if resource and resource.rstrip("/") != f"{base}/mcp":
            raise oauth.OAuthError("invalid_target", f"The resource is {base}/mcp.")
        if grant_type == "authorization_code":
            issued = await oauth.exchange_code(
                db, client_id, code, redirect_uri, code_verifier, now
            )
        elif grant_type == "refresh_token":
            issued = await oauth.refresh(db, client_id, refresh_token, now)
        else:
            raise oauth.OAuthError("unsupported_grant_type", "A code or a refresh token.")
    except oauth.OAuthError as error:
        await db.commit()  # an approval revoked for a code or a token used twice
        return _answer(error)
    await db.commit()
    return JSONResponse(
        {
            "access_token": issued.access_token,
            "token_type": "Bearer",
            "expires_in": issued.expires_in,
            "refresh_token": issued.refresh_token,
        },
        headers=_NO_STORE,
    )


# --- The consent page's calls ---------------------------------------------------------


class Asked(BaseModel):
    client: str  # the client's name, in its own words
    redirect_host: str  # where the browser is sent back to


class Answer(BaseModel):
    request: str = Field(max_length=4096)


class Consent(Answer):
    access: Literal["read", "all"]
    lasts: Literal["1d", "30d", "90d", "forever"]


class Redirect(BaseModel):
    redirect: str  # where the browser goes next: back to the client


async def _asked(request: Request, db: AsyncSession, sealed: str) -> oauth.Request:
    found = oauth.open_request(request.app.state.settings, sealed, utcnow())
    if found is None or await oauth.get_client(db, found.client_id) is None:
        raise ApiError(
            410, "request_expired", "This request has expired. Start again from the application."
        )
    return found


@consent.get("/consent", response_model=Asked)
async def asked(
    request: Request,
    sealed: Annotated[str, Query(alias="request", max_length=4096)],
    _: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> Asked:
    """What a client asks of the signed-in person, for the consent page to show."""
    found = await _asked(request, db, sealed)
    client = await oauth.get_client(db, found.client_id)
    assert client is not None
    host = urlsplit(found.redirect_uri).hostname or ""
    return Asked(client=client.name, redirect_host=host)


@consent.post("/consent", response_model=Redirect)
async def approve(
    body: Consent,
    request: Request,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> Redirect:
    """The person approves: a code for the client, back at its redirect address."""
    found = await _asked(request, db, body.request)
    address = await oauth.approve(db, principal.user, found, body.access, body.lasts, utcnow())
    await db.commit()
    log.info("oauth_approved", client=found.client_id, by=principal.user.username)
    return Redirect(redirect=address)


@consent.post("/refusal", response_model=Redirect)
async def refuse(
    body: Answer,
    request: Request,
    _: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> Redirect:
    """The person refuses: the client is told so (`access_denied`)."""
    return Redirect(redirect=oauth.refuse(await _asked(request, db, body.request)))
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -5,7 +5,7 @@ import base64
 import secrets
 import uuid
 from collections.abc import Awaitable, Callable
-from dataclasses import dataclass
+from dataclasses import dataclass, replace
 from typing import Literal
 from urllib.parse import urlsplit
 
@@ -16,7 +16,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from megooarti.clock import utcnow
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
-from megooarti.security import registry_tokens, sessions, throttle, tokens, users
+from megooarti.security import oauth, registry_tokens, sessions, throttle, tokens, users
 from megooarti.security.keys import TOKEN_PREFIX
 from megooarti.security.models import ApiToken, User, UserSession
 from megooarti.security.passwords import hash_password, needs_rehash, verify_password
@@ -50,6 +50,8 @@ class Principal:
     public: frozenset[str] = frozenset()
     # The API token the caller presented, if any: what a registry token is issued for.
     token_id: uuid.UUID | None = None
+    # The OAuth approval the caller's access token stands for, if it held one (MCP 7).
+    grant_id: uuid.UUID | None = None
 
     @property
     def is_anonymous(self) -> bool:
@@ -492,19 +494,47 @@ async def registry_credentials(
 
 # Who is calling, if anyone. Both enforce CSRF for cookie requests; they differ only in
 # the challenge a 401 carries.
+async def _resource_metadata(request: Request, db: AsyncSession) -> str:
+    base = (await get_setting(db, "base_url") or str(request.base_url)).rstrip("/")
+    return f"{base}/.well-known/oauth-protected-resource/mcp"
+
+
+async def _agent(request: Request, db: AsyncSession, value: str) -> Principal:
+    if value.startswith(TOKEN_PREFIX):
+        user, token = await _authenticate_token(db, request, value)
+        return await build_principal(db, user, "token", token=token)
+    grant = await oauth.find_access(db, value, utcnow())
+    user = None if grant is None else await users.get_user(db, grant.user_id)
+    if grant is None or user is None or user.status != "active":
+        # Counted against the address, as a token that is not one is.
+        return await _checked(db, request, None, _no_match)
+    principal = await build_principal(db, user, "token")
+    scopes = None if grant.scopes is None else frozenset(grant.scopes)
+    return replace(principal, scopes=scopes, grant_id=grant.id)
+
+
 async def agent_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
-    """Dependency of the MCP endpoint: an API token as a bearer token, and nothing else.
+    """Dependency of the MCP endpoint: an API token, or an OAuth access token, as a bearer
+    token, and nothing else.
 
     No cookie, no password and no anonymous access: an agent always acts for someone,
-    who made the token it holds. Raises 401, or 429 after too many failed attempts.
+    who made its token or approved it. Raises 401, naming where a client finds how to
+    sign in (RFC 9728), or 429 after too many failed attempts.
     """
     scheme, _, value = request.headers.get("Authorization", "").partition(" ")
     value = value.strip()
-    if scheme.lower() != "bearer" or not value.startswith(TOKEN_PREFIX):
-        raise unauthorized("Sign in with an API token, as a bearer token.")
-    user, token = await _authenticate_token(db, request, value)
-    principal = await build_principal(db, user, "token", token=token)
-    await db.commit()  # when the token was last used
+    try:
+        if scheme.lower() != "bearer" or not value.startswith((TOKEN_PREFIX, oauth.ACCESS_PREFIX)):
+            raise unauthorized("Sign in with an API token, or with OAuth, as a bearer token.")
+        principal = await _agent(request, db, value)
+    except ApiError as error:
+        if error.status_code == 401:
+            metadata = await _resource_metadata(request, db)
+            error.headers = {
+                "WWW-Authenticate": f'Bearer realm="MegooArti", resource_metadata="{metadata}"'
+            }
+        raise
+    await db.commit()  # when the token, or the approval, was last used
     return principal
 
 
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -34,8 +34,10 @@ from megooarti.repositories.routes import router as content_router
 from megooarti.repositories.search_api import router as search_router
 from megooarti.repositories.yum import format as _yum_format  # noqa: F401  (registers it)
 from megooarti.request_id import RequestIdMiddleware
+from megooarti.security import oauth
 from megooarti.security.api import auth as auth_api
 from megooarti.security.api import me as me_api
+from megooarti.security.api import oauth as oauth_api
 from megooarti.security.api import roles as roles_api
 from megooarti.security.api import users as users_api
 from megooarti.security.bootstrap import ensure_initial_admin_password
@@ -77,6 +79,9 @@ async def _compact(app: FastAPI) -> None:
     settings = app.state.settings
 
     async def job() -> None:
+        async with app.state.sessionmaker() as db:
+            await oauth.forget(db, utcnow())  # OAuth's codes, tokens and approvals that ended
+            await db.commit()
         # First, so that what upkeep removes starts its wait for compaction now.
         await upkeep.run(app.state.sessionmaker, settings, utcnow())
         removed = await blobs.compact(
@@ -159,6 +164,9 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(registry_router)  # /v2/..., the container registry API
     app.state.mcp = McpServer()
     app.include_router(mcp_router)  # /mcp, for AI agents
+    app.include_router(oauth_api.well_known)  # /.well-known/..., how agents sign in
+    app.include_router(oauth_api.endpoints)  # /oauth/..., where they do
+    app.include_router(oauth_api.consent, prefix=API_PREFIX)  # the consent page's
 
     # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
     # first, so its 500 response passes through every other middleware, and keep
```

Change `backend/src/megooarti/mcp/system.py`:

```diff
@@ -9,15 +9,15 @@ from megooarti import __version__
 from megooarti.mcp.tools import caller, database, tool
 from megooarti.pagination import PageParams
 from megooarti.security import users
-from megooarti.security.models import ApiToken
+from megooarti.security.models import ApiToken, OAuthClient, OAuthGrant
 from megooarti.storage import api as blob_stores_api
 from megooarti.system import information_api, status
 
 
 class TokenView(BaseModel):
-    kind: str  # "api_token": made under Account, Tokens
-    name: str
-    prefix: str  # its first characters, as the web UI shows them
+    kind: str  # "api_token", made under Account, Tokens; or "oauth", an approval
+    name: str  # the token's; or the client's, in its own words
+    prefix: str  # an API token's first characters, as the web UI shows them
     scopes: list[str] | None  # what it narrows its owner's permissions to; null: none
     expires_at: datetime | None
 
@@ -40,21 +40,33 @@ async def whoami() -> Whoami:
     async with database() as db:
         view = await users.describe(db, principal.user)
         token = None if principal.token_id is None else await db.get(ApiToken, principal.token_id)
+        grant = None if principal.grant_id is None else await db.get(OAuthGrant, principal.grant_id)
+        client = None if grant is None else await db.get(OAuthClient, grant.client_id)
+    if grant is not None and client is not None:
+        held: TokenView | None = TokenView(
+            kind="oauth",
+            name=client.name,
+            prefix="",
+            scopes=grant.scopes,
+            expires_at=grant.expires_at,
+        )
+    elif token is not None:
+        held = TokenView(
+            kind="api_token",
+            name=token.name,
+            prefix=token.display_prefix,
+            scopes=token.scopes,
+            expires_at=token.expires_at,
+        )
+    else:
+        held = None
     return Whoami(
         username=view.username,
         display_name=view.display_name,
         email=view.email,
         roles=view.roles,
         permissions=sorted(principal.patterns),
-        token=None
-        if token is None
-        else TokenView(
-            kind="api_token",
-            name=token.name,
-            prefix=token.display_prefix,
-            scopes=token.scopes,
-            expires_at=token.expires_at,
-        ),
+        token=held,
     )
 
 
```

Change `backend/src/megooarti/mcp/tools.py`:

```diff
@@ -186,7 +186,7 @@ def tool(
                     "mcp_tool_called",
                     tool=function.__name__,
                     user=principal.user.username,
-                    token=None if principal.token_id is None else str(principal.token_id),
+                    token=str(principal.token_id or principal.grant_id or "") or None,
                     arguments=loggable(arguments),
                     outcome=outcome,
                     duration_ms=round((time.perf_counter() - started) * 1000),
```

Change `frontend/openapi.json`:

```diff
@@ -14,6 +14,38 @@
         "title": "AnonymousAccess",
         "type": "object"
       },
+      "Answer": {
+        "properties": {
+          "request": {
+            "maxLength": 4096,
+            "title": "Request",
+            "type": "string"
+          }
+        },
+        "required": [
+          "request"
+        ],
+        "title": "Answer",
+        "type": "object"
+      },
+      "Asked": {
+        "properties": {
+          "client": {
+            "title": "Client",
+            "type": "string"
+          },
+          "redirect_host": {
+            "title": "Redirect Host",
+            "type": "string"
+          }
+        },
+        "required": [
+          "client",
+          "redirect_host"
+        ],
+        "title": "Asked",
+        "type": "object"
+      },
       "AssetView": {
         "properties": {
           "blob_store": {
@@ -351,6 +383,40 @@
         "title": "ComponentView",
         "type": "object"
       },
+      "Consent": {
+        "properties": {
+          "access": {
+            "enum": [
+              "read",
+              "all"
+            ],
+            "title": "Access",
+            "type": "string"
+          },
+          "lasts": {
+            "enum": [
+              "1d",
+              "30d",
+              "90d",
+              "forever"
+            ],
+            "title": "Lasts",
+            "type": "string"
+          },
+          "request": {
+            "maxLength": 4096,
+            "title": "Request",
+            "type": "string"
+          }
+        },
+        "required": [
+          "request",
+          "access",
+          "lasts"
+        ],
+        "title": "Consent",
+        "type": "object"
+      },
       "Database": {
         "properties": {
           "version": {
@@ -1156,6 +1222,19 @@
         "title": "ProxyStatus",
         "type": "object"
       },
+      "Redirect": {
+        "properties": {
+          "redirect": {
+            "title": "Redirect",
+            "type": "string"
+          }
+        },
+        "required": [
+          "redirect"
+        ],
+        "title": "Redirect",
+        "type": "object"
+      },
       "RemoteAuthIn": {
         "properties": {
           "secret": {
@@ -3438,6 +3517,132 @@
         ]
       }
     },
+    "/api/v1/oauth/consent": {
+      "get": {
+        "description": "What a client asks of the signed-in person, for the consent page to show.",
+        "operationId": "asked_api_v1_oauth_consent_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "request",
+            "required": true,
+            "schema": {
+              "maxLength": 4096,
+              "title": "Request",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Asked"
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
+        "summary": "Asked",
+        "tags": [
+          "account"
+        ]
+      },
+      "post": {
+        "description": "The person approves: a code for the client, back at its redirect address.",
+        "operationId": "approve_api_v1_oauth_consent_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/Consent"
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
+                  "$ref": "#/components/schemas/Redirect"
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
+        "summary": "Approve",
+        "tags": [
+          "account"
+        ]
+      }
+    },
+    "/api/v1/oauth/refusal": {
+      "post": {
+        "description": "The person refuses: the client is told so (`access_denied`).",
+        "operationId": "refuse_api_v1_oauth_refusal_post",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/Answer"
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
+                  "$ref": "#/components/schemas/Redirect"
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
+        "summary": "Refuse",
+        "tags": [
+          "account"
+        ]
+      }
+    },
     "/api/v1/repositories": {
       "get": {
         "operationId": "list_repositories_api_v1_repositories_get",
```

Then write the API's description: (in `backend/`) `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/mcp tests/test_route_guards.py tests/test_openapi_snapshot.py tests/test_migrations.py`
Expected: 124 passed.

- [ ] **Step 5: Commit**

```bash
git add backend frontend/openapi.json
git commit -m "feat(mcp): OAuth sign-in to /mcp: discovery, registration, consent, tokens of an hour, refresh used once"
```

---

### Task 2: Connected apps

**Files:**
- Modify: `backend/src/megooarti/security/api/schemas.py`, `backend/src/megooarti/security/api/me.py`, `backend/src/megooarti/security/api/users.py`, `backend/src/megooarti/mcp/administration.py`, `frontend/openapi.json` (written by a command)
- Test: `backend/tests/mcp/test_connected_apps.py`

**Interfaces:**
- Consumes: Task 1's `oauth.approvals`, `oauth.revoke`, `oauth_steps`, `browser`; 14b's `user_details`, `revoke_token`.
- Produces: `ConnectedApp`; `GET`/`DELETE /api/v1/me/connected-apps[/{app_id}]`; `GET`/`DELETE /api/v1/users/{user_id}/connected-apps[/{app_id}]`; `user_details.connected_apps`; `revoke_token(username, token=None, connected_app=None)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/mcp/test_connected_apps.py`:

```python
"""Connected apps (MCP spec 7.6): the applications a user let sign in as them with OAuth,
listed and revoked by the user, by an administrator, and by an agent that may."""

from tests.accounts import PASSWORD, basic
from tests.mcp.conftest import refusal, structured
from tests.mcp.oauth_steps import LIST_TOOLS, MCP, approved_code, tokens


async def test_a_user_sees_what_they_connected_and_revokes_it(client, browser, make_token):
    client_id, code = await approved_code(client, browser)
    access = (await tokens(client, client_id, code))["access_token"]

    listed = await browser.get("/api/v1/me/connected-apps")
    (app,) = listed.json()["items"]
    revoked = await browser.delete(f"/api/v1/me/connected-apps/{app['id']}")
    again = await browser.delete(f"/api/v1/me/connected-apps/{app['id']}")
    after = await client.post(
        "/mcp", json=LIST_TOOLS, headers=MCP | {"Authorization": f"Bearer {access}"}
    )

    assert (app["client"], app["redirect_host"]) == ("Claude", "127.0.0.1")
    assert app["scopes"] == ["repository:*:*:browse", "repository:*:*:read", "admin:*:read"]
    assert app["expires_at"] is not None and app["last_used_at"] is None
    assert revoked.status_code == 204
    assert again.status_code == 404
    assert after.status_code == 401
    assert (await browser.get("/api/v1/me/connected-apps")).json()["items"] == []


async def test_only_a_person_signed_in_lists_their_connected_apps(
    client, browser, make_user, make_token
):
    token = await make_token(await make_user("other"))

    by_token = await client.get(
        "/api/v1/me/connected-apps", headers={"Authorization": f"Bearer {token}"}
    )

    assert by_token.status_code == 403


async def test_an_administrator_sees_and_revokes_a_users_connected_apps(
    client, browser, make_user, sessionmaker
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    await approved_code(client, browser)
    users = (await client.get("/api/v1/users", headers=root)).json()["items"]
    dev = next(user for user in users if user["username"] == "dev")

    listed = await client.get(f"/api/v1/users/{dev['id']}/connected-apps", headers=root)
    (app,) = listed.json()["items"]
    revoked = await client.delete(
        f"/api/v1/users/{dev['id']}/connected-apps/{app['id']}", headers=root
    )

    assert revoked.status_code == 204
    assert (await client.get(f"/api/v1/users/{dev['id']}/connected-apps", headers=root)).json()[
        "items"
    ] == []


async def test_an_agent_that_may_sees_a_users_connected_apps_and_revokes_one(
    client, browser, agent, make_user, make_token
):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    await approved_code(client, browser)

    async with agent(token) as session:
        details = structured(await session.call_tool("user_details", {"username": "dev"}))
        (app,) = details["connected_apps"]
        revoked = structured(
            await session.call_tool("revoke_token", {"username": "dev", "connected_app": app["id"]})
        )
        neither = await session.call_tool("revoke_token", {"username": "dev"})
        after = structured(await session.call_tool("user_details", {"username": "dev"}))

    assert app["client"] == "Claude"
    assert revoked == {"deleted": app["id"]}
    assert refusal(neither).endswith("- token: Give a token's name, or a connected app's id.")
    assert after["connected_apps"] == []
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/mcp/test_connected_apps.py`
Expected: 4 failed: `/api/v1/me/connected-apps` is `404`, the users' route has no `items` (`KeyError: 'items'`), and `user_details` has no `connected_apps`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/api/schemas.py`:

```diff
@@ -18,6 +18,18 @@ def _valid_pattern(value: str) -> str:
 Pattern = Annotated[str, AfterValidator(_valid_pattern)]
 
 
+class ConnectedApp(BaseModel):
+    """An approval a user gave an application signed in with OAuth (MCP spec 7.6)."""
+
+    id: uuid.UUID
+    client: str  # the application's name, in its own words
+    redirect_host: str  # where it was sent back to
+    scopes: list[str] | None  # what it may do, narrowing the user's permissions; null: all
+    created_at: datetime
+    last_used_at: datetime | None
+    expires_at: datetime | None  # null: until it is revoked
+
+
 class TokenInfo(BaseModel):
     id: uuid.UUID
     name: str
```

Change `backend/src/megooarti/security/api/me.py`:

```diff
@@ -11,8 +11,8 @@ from megooarti.clock import utcnow
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
 from megooarti.pagination import Page, PageParams, page
-from megooarti.security import tokens, users
-from megooarti.security.api.schemas import Pattern, TokenCreated, TokenInfo
+from megooarti.security import oauth, tokens, users
+from megooarti.security.api.schemas import ConnectedApp, Pattern, TokenCreated, TokenInfo
 from megooarti.security.authentication import (
     Principal,
     authenticate_password,
@@ -111,3 +111,26 @@ async def revoke_token(
     await tokens.revoke_token(db, principal.user.id, token_id)
     await db.commit()
     log.info("token_revoked", username=principal.user.username, by=principal.user.username)
+
+
+@router.get("/connected-apps", response_model=Page[ConnectedApp])
+async def list_connected_apps(
+    params: PageParams = Depends(),
+    principal: Principal = Depends(require_interactive()),
+    db: AsyncSession = Depends(get_session),
+) -> dict:
+    """The applications the caller let sign in as them with OAuth, the newest first."""
+    every = await oauth.approvals(db, principal.user.id, utcnow())
+    return page(every[params.offset : params.offset + params.limit], len(every), params)
+
+
+@router.delete("/connected-apps/{app_id}", status_code=204)
+async def revoke_connected_app(
+    app_id: uuid.UUID,
+    principal: Principal = Depends(require_interactive()),
+    db: AsyncSession = Depends(get_session),
+) -> None:
+    """Revoke an approval: the application's tokens stop working at once."""
+    await oauth.revoke(db, principal.user.id, app_id)
+    await db.commit()
+    log.info("connected_app_revoked", username=principal.user.username)
```

Change `backend/src/megooarti/security/api/users.py`:

```diff
@@ -9,11 +9,12 @@ from fastapi import APIRouter, Depends, Request
 from pydantic import BaseModel, Field
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from megooarti.clock import utcnow
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
 from megooarti.pagination import Page, PageParams, page
-from megooarti.security import tokens, users
-from megooarti.security.api.schemas import TokenInfo
+from megooarti.security import oauth, tokens, users
+from megooarti.security.api.schemas import ConnectedApp, TokenInfo
 from megooarti.security.authentication import Principal, require
 from megooarti.security.bootstrap import discard_initial_password
 from megooarti.security.guards import ensure_administrator_remains
@@ -188,6 +189,32 @@ async def list_user_tokens(
     return page(items, total, params)
 
 
+@router.get("/{user_id}/connected-apps", response_model=Page[ConnectedApp])
+async def list_user_connected_apps(
+    user_id: uuid.UUID,
+    params: PageParams = Depends(),
+    _: Principal = Depends(require("admin:tokens:read")),
+    db: AsyncSession = Depends(get_session),
+) -> dict:
+    """The applications a user let sign in as them with OAuth."""
+    user = await _load(db, user_id)
+    every = await oauth.approvals(db, user.id, utcnow())
+    return page(every[params.offset : params.offset + params.limit], len(every), params)
+
+
+@router.delete("/{user_id}/connected-apps/{app_id}", status_code=204)
+async def revoke_user_connected_app(
+    user_id: uuid.UUID,
+    app_id: uuid.UUID,
+    principal: Principal = Depends(require("admin:tokens:write")),
+    db: AsyncSession = Depends(get_session),
+) -> None:
+    user = await _load(db, user_id)
+    await oauth.revoke(db, user.id, app_id)
+    await db.commit()
+    log.info("connected_app_revoked", username=user.username, by=principal.user.username)
+
+
 @router.delete("/{user_id}/tokens/{token_id}", status_code=204)
 async def revoke_user_token(
     user_id: uuid.UUID,
```

Change `backend/src/megooarti/mcp/administration.py`:

```diff
@@ -19,7 +19,7 @@ from megooarti.security import roles, users
 from megooarti.security.api import roles as roles_api
 from megooarti.security.api import users as users_api
 from megooarti.security.api.roles import RoleContent, RoleCreate, RoleOut
-from megooarti.security.api.schemas import TokenInfo
+from megooarti.security.api.schemas import ConnectedApp, TokenInfo
 from megooarti.security.api.users import UserCreate, UserOut, UserUpdate
 from megooarti.security.models import ApiToken
 
@@ -97,6 +97,8 @@ class UserDetails(BaseModel):
     # Their API tokens: names, first characters, scopes, expiry, last use; never a value.
     # Null to those who may not read tokens.
     tokens: list[TokenInfo] | None
+    # The applications they let sign in as them with OAuth; null likewise.
+    connected_apps: list[ConnectedApp] | None
 
 
 @tool(annotations=READ, shown_to=holding("admin:users:read"))
@@ -119,7 +121,15 @@ async def user_details(username: Username) -> UserDetails:
                 ]
                 if not listed["items"] or len(held) >= listed["total"]:
                     break
-    return UserDetails(user=_user(view), tokens=held)
+        apps = None
+        if principal.allows("admin:tokens:read"):
+            listed = await users_api.list_user_connected_apps(
+                user_id, PageParams(limit=200, offset=0), principal, db
+            )
+            apps = [
+                ConnectedApp.model_validate(one, from_attributes=True) for one in listed["items"]
+            ]
+    return UserDetails(user=_user(view), tokens=held, connected_apps=apps)
 
 
 @tool(annotations=WRITE, shown_to=holding("admin:users:write"))
@@ -184,11 +194,28 @@ async def delete_user(username: Username) -> Gone:
 
 
 @tool(annotations=DESTRUCTIVE, shown_to=holding("admin:tokens:write"))
-async def revoke_token(username: Username, token: Annotated[str, Field(max_length=100)]) -> Gone:
-    """Revoke a user's API token, by its name as `user_details` shows it: whatever signed in
-    with it is refused from then on."""
+async def revoke_token(
+    username: Username,
+    token: Annotated[str | None, Field(max_length=100)] = None,
+    connected_app: uuid.UUID | None = None,
+) -> Gone:
+    """Revoke a user's API token, by its name, or an application they connected with
+    OAuth, by its id, as `user_details` shows them: whatever signed in with it is refused
+    from then on."""
+    if (token is None) == (connected_app is None):
+        raise ApiError(
+            422,
+            "validation_error",
+            "The request is not valid.",
+            [{"field": "token", "message": "Give a token's name, or a connected app's id."}],
+        )
     async with database() as db:
         user_id = await _user_id(db, username)
+        if connected_app is not None:
+            await users_api.revoke_user_connected_app(
+                user_id, connected_app, caller().principal, db
+            )
+            return Gone(deleted=str(connected_app))
         found = await db.scalar(
             select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.name == token)
         )
```

Change `frontend/openapi.json`:

```diff
@@ -383,6 +383,78 @@
         "title": "ComponentView",
         "type": "object"
       },
+      "ConnectedApp": {
+        "description": "An approval a user gave an application signed in with OAuth (MCP spec 7.6).",
+        "properties": {
+          "client": {
+            "title": "Client",
+            "type": "string"
+          },
+          "created_at": {
+            "format": "date-time",
+            "title": "Created At",
+            "type": "string"
+          },
+          "expires_at": {
+            "anyOf": [
+              {
+                "format": "date-time",
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Expires At"
+          },
+          "id": {
+            "format": "uuid",
+            "title": "Id",
+            "type": "string"
+          },
+          "last_used_at": {
+            "anyOf": [
+              {
+                "format": "date-time",
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Last Used At"
+          },
+          "redirect_host": {
+            "title": "Redirect Host",
+            "type": "string"
+          },
+          "scopes": {
+            "anyOf": [
+              {
+                "items": {
+                  "type": "string"
+                },
+                "type": "array"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Scopes"
+          }
+        },
+        "required": [
+          "id",
+          "client",
+          "redirect_host",
+          "scopes",
+          "created_at",
+          "last_used_at",
+          "expires_at"
+        ],
+        "title": "ConnectedApp",
+        "type": "object"
+      },
       "Consent": {
         "properties": {
           "access": {
@@ -831,6 +903,37 @@
         "title": "Page[ComponentView]",
         "type": "object"
       },
+      "Page_ConnectedApp_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/ConnectedApp"
+            },
+            "title": "Items",
+            "type": "array"
+          },
+          "limit": {
+            "title": "Limit",
+            "type": "integer"
+          },
+          "offset": {
+            "title": "Offset",
+            "type": "integer"
+          },
+          "total": {
+            "title": "Total",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "items",
+          "total",
+          "limit",
+          "offset"
+        ],
+        "title": "Page[ConnectedApp]",
+        "type": "object"
+      },
       "Page_FormatOut_": {
         "properties": {
           "items": {
@@ -3352,6 +3455,100 @@
         ]
       }
     },
+    "/api/v1/me/connected-apps": {
+      "get": {
+        "description": "The applications the caller let sign in as them with OAuth, the newest first.",
+        "operationId": "list_connected_apps_api_v1_me_connected_apps_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "limit",
+            "required": false,
+            "schema": {
+              "default": 50,
+              "maximum": 200,
+              "minimum": 1,
+              "title": "Limit",
+              "type": "integer"
+            }
+          },
+          {
+            "in": "query",
+            "name": "offset",
+            "required": false,
+            "schema": {
+              "default": 0,
+              "minimum": 0,
+              "title": "Offset",
+              "type": "integer"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_ConnectedApp_"
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
+        "summary": "List Connected Apps",
+        "tags": [
+          "account"
+        ]
+      }
+    },
+    "/api/v1/me/connected-apps/{app_id}": {
+      "delete": {
+        "description": "Revoke an approval: the application's tokens stop working at once.",
+        "operationId": "revoke_connected_app_api_v1_me_connected_apps__app_id__delete",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "app_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "App Id",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "204": {
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
+        "summary": "Revoke Connected App",
+        "tags": [
+          "account"
+        ]
+      }
+    },
     "/api/v1/me/password": {
       "put": {
         "operationId": "change_password_api_v1_me_password_put",
@@ -4924,6 +5121,119 @@
         ]
       }
     },
+    "/api/v1/users/{user_id}/connected-apps": {
+      "get": {
+        "description": "The applications a user let sign in as them with OAuth.",
+        "operationId": "list_user_connected_apps_api_v1_users__user_id__connected_apps_get",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "user_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "User Id",
+              "type": "string"
+            }
+          },
+          {
+            "in": "query",
+            "name": "limit",
+            "required": false,
+            "schema": {
+              "default": 50,
+              "maximum": 200,
+              "minimum": 1,
+              "title": "Limit",
+              "type": "integer"
+            }
+          },
+          {
+            "in": "query",
+            "name": "offset",
+            "required": false,
+            "schema": {
+              "default": 0,
+              "minimum": 0,
+              "title": "Offset",
+              "type": "integer"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_ConnectedApp_"
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
+        "summary": "List User Connected Apps",
+        "tags": [
+          "users"
+        ]
+      }
+    },
+    "/api/v1/users/{user_id}/connected-apps/{app_id}": {
+      "delete": {
+        "operationId": "revoke_user_connected_app_api_v1_users__user_id__connected_apps__app_id__delete",
+        "parameters": [
+          {
+            "in": "path",
+            "name": "user_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "User Id",
+              "type": "string"
+            }
+          },
+          {
+            "in": "path",
+            "name": "app_id",
+            "required": true,
+            "schema": {
+              "format": "uuid",
+              "title": "App Id",
+              "type": "string"
+            }
+          }
+        ],
+        "responses": {
+          "204": {
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
+        "summary": "Revoke User Connected App",
+        "tags": [
+          "users"
+        ]
+      }
+    },
     "/api/v1/users/{user_id}/password": {
       "put": {
         "operationId": "reset_password_api_v1_users__user_id__password_put",
```

Then write the API's description again: (in `backend/`) `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/mcp tests/test_openapi_snapshot.py`
Expected: 114 passed.

- [ ] **Step 5: Commit**

```bash
git add backend frontend/openapi.json
git commit -m "feat: connected apps, listed and revoked by their user, an administrator, and an agent that may"
```

---

### Task 3: The consent page and Connected apps in the web UI

**Files:**
- Create: `frontend/src/lib/leave.ts`, `frontend/src/components/connected-app-list.tsx`, `frontend/src/screens/connect.tsx`, `frontend/src/screens/connected-apps.tsx`, `frontend/src/app/(shell)/connect/page.tsx`, `frontend/src/app/(shell)/account/connected-apps/page.tsx`
- Modify: `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`), `frontend/src/lib/api/types.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/session/rules.ts`, `frontend/src/lib/security.ts`, `frontend/src/components/account-nav.tsx`, `frontend/src/screens/user.tsx`, `frontend/messages/en.json`
- Test: `frontend/src/screens/connect.test.tsx`; modify `frontend/src/components/security.test.tsx`, `frontend/src/lib/session/rules.test.ts`, `frontend/src/screens/security.test.tsx`

**Interfaces:**
- Consumes: Tasks 1 and 2's routes and schemas; the UI's `AccountNav`, `ConfirmDialog`, `Table`, `ChoiceGroup`, `SelectField`, `useNotify`.
- Produces: `CONNECT`, `CONNECTED_APPS`; `leaveFor(address)`; `useMyConnectedApps`, `useRevokeConnectedApp`, `useUserConnectedApps`, `useRevokeUserConnectedApp`, `useConsentRequest`, `useApprove`, `useRefuse`; `ConnectedAppList`; `ConnectScreen`, `ConnectedAppsScreen`; the messages `connect.*`, `connectedApps.*`, `users.apps*`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/components/security.test.tsx`:

```diff
@@ -439,10 +439,16 @@ describe("the pages of an account (A1)", () => {
 
     expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
       ["API tokens", "/account/tokens"],
+      ["Connected apps", "/account/connected-apps"],
       ["Password", "/account/password"],
       ["Preferences", "/account/preferences"],
     ]);
-    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
+    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([
+      "page",
+      null,
+      null,
+      null,
+    ]);
     await expectAccessible();
   });
 
```

Change `frontend/src/lib/session/rules.test.ts`:

```diff
@@ -37,6 +37,19 @@ describe("what a visitor is shown", () => {
     expect(decide(NOBODY, "/login?next=%2Fsearch", "/search")).toEqual(show);
   });
 
+  test("an application's consent page is answered by someone signed in, and is come back to", () => {
+    expect(decide(NOBODY, "/connect?request=sealed")).toEqual(
+      goTo("/login?next=%2Fconnect%3Frequest%3Dsealed"),
+    );
+    expect(decide(VISITOR, "/connect?request=sealed")).toEqual(
+      goTo("/login?next=%2Fconnect%3Frequest%3Dsealed"),
+    );
+    expect(decide(ADMIN, "/connect?request=sealed")).toEqual(show);
+    expect(decide(ADMIN, "/login", "/connect?request=sealed")).toEqual(
+      goTo("/connect?request=sealed"),
+    );
+  });
+
   test("a visitor browses where anonymous access is on, and has no account", () => {
     expect(isAnonymous(VISITOR)).toBe(true);
     expect(isAnonymous(NOBODY)).toBe(false);
```

Change `frontend/src/screens/security.test.tsx`:

```diff
@@ -349,6 +349,19 @@ describe("one user", () => {
   function one(who = ALICE, more: Routes = {}, session = ADMIN) {
     const api = mockApi({
       [`GET /users/${who.id}`]: { json: who },
+      [`GET /users/${who.id}/connected-apps`]: {
+        json: page([
+          {
+            id: "app1",
+            client: "Claude",
+            redirect_host: "claude.ai",
+            scopes: null,
+            created_at: "2026-10-18T08:00:00Z",
+            last_used_at: null,
+            expires_at: null,
+          },
+        ]),
+      },
       [`GET /users/${who.id}/tokens`]: {
         json: page([
           {
@@ -559,6 +572,30 @@ describe("one user", () => {
     expect(screen.queryByRole("button", { name: "Revoke ci build" })).toBeNull();
   });
 
+  test("has the applications they connected listed, and revoked by whoever may", async () => {
+    const user = userEvent.setup();
+    const first = one(ALICE, { "DELETE /users/id-of-alice/connected-apps/app1": { status: 204 } });
+
+    const table = await screen.findByRole("table", { name: "Applications alice connected" });
+    expect(within(table).getByText("Sent back to claude.ai")).toBeVisible();
+    await user.click(screen.getByRole("button", { name: "Revoke Claude" }));
+    await user.click(
+      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Revoke" }),
+    );
+
+    await waitFor(() =>
+      expect(notices()).toHaveTextContent("Revoked Claude, which alice connected."),
+    );
+    expect(of(first.calls, "DELETE")[0]?.path).toBe("/users/id-of-alice/connected-apps/app1");
+    first.unmount();
+
+    one(ALICE, {}, holding("admin:users:read", "admin:tokens:read"));
+    expect(
+      await screen.findByRole("table", { name: "Applications alice connected" }),
+    ).toBeVisible();
+    expect(screen.queryByRole("button", { name: "Revoke Claude" })).toBeNull();
+  });
+
   test("is deleted only by whoever types their name, and is then not asked for again (A8)", async () => {
     const user = userEvent.setup();
     const { calls } = one(ALICE, { "DELETE /users/id-of-alice": { status: 204 } });
```

Create `frontend/src/screens/connect.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { leaveFor } from "@/lib/leave";
import { failure, mockApi, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { ConnectedAppsScreen } from "./connected-apps";
import { ConnectScreen } from "./connect";

vi.mock("@/lib/leave", () => ({ leaveFor: vi.fn() }));

const BACK = "http://127.0.0.1:33418/callback?code=mgc_x&state=s";
const page = (items: unknown[]) => ({ items, total: items.length, limit: 200, offset: 0 });

beforeEach(() => vi.mocked(leaveFor).mockReset());

function consent(more: Routes = {}, address = "/connect?request=sealed") {
  const api = mockApi({
    "GET /oauth/consent": { json: { client: "Claude Code", redirect_host: "127.0.0.1" } },
    "POST /oauth/consent": { json: { redirect: BACK } },
    "POST /oauth/refusal": {
      json: { redirect: "http://127.0.0.1:33418/callback?error=access_denied" },
    },
    ...more,
  });
  navigation.at(address);
  return { ...renderUi(<ConnectScreen />, { session: ADMIN }), ...api };
}

describe("the consent page of an application signing in with OAuth (7.3)", () => {
  test("says who asks, in its own words, and where the browser goes back to", async () => {
    const { calls } = consent();

    expect(await screen.findByText("Claude Code")).toBeVisible();
    expect(screen.getByText(/the name it gave itself/)).toHaveTextContent("127.0.0.1");
    expect(calls[0]?.path).toBe("/oauth/consent?request=sealed");
    expect(screen.getByRole("radio", { name: /Read what I can read/ })).toBeChecked();
    expect(screen.getByLabelText("For how long")).toHaveValue("30d");
    await expectAccessible();
  });

  test("allows what was chosen, for as long as was chosen, and goes back", async () => {
    const user = userEvent.setup();
    const { calls } = consent();
    await screen.findByText("Claude Code");

    await user.click(screen.getByRole("radio", { name: /Everything I can do/ }));
    await user.selectOptions(screen.getByLabelText("For how long"), "1d");
    await user.click(screen.getByRole("button", { name: "Allow" }));

    await waitFor(() => expect(leaveFor).toHaveBeenCalledWith(BACK));
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      request: "sealed",
      access: "all",
      lasts: "1d",
    });
  });

  test("refuses, and the application is told so", async () => {
    const user = userEvent.setup();
    const { calls } = consent();
    await screen.findByText("Claude Code");

    await user.click(screen.getByRole("button", { name: "Refuse" }));

    await waitFor(() =>
      expect(leaveFor).toHaveBeenCalledWith("http://127.0.0.1:33418/callback?error=access_denied"),
    );
    expect(calls.find((call) => call.method === "POST")?.path).toBe("/oauth/refusal");
  });

  test("says when the request has expired, or when nothing was asked", async () => {
    consent({
      "GET /oauth/consent": failure(
        410,
        "request_expired",
        "This request has expired. Start again from the application.",
      ),
    });
    expect(await screen.findByText(/This request has expired/)).toBeVisible();

    consent({}, "/connect");
    expect(
      screen.getByText("Nothing is asked here. Start again from the application."),
    ).toBeVisible();
  });
});

describe("one's connected apps (7.6)", () => {
  test("are listed with what each may do, and revoked", async () => {
    const user = userEvent.setup();
    const { calls } = (() => {
      const api = mockApi({
        "GET /me/connected-apps": {
          json: page([
            {
              id: "app1",
              client: "Claude Code",
              redirect_host: "127.0.0.1",
              scopes: ["repository:*:*:browse", "repository:*:*:read", "admin:*:read"],
              created_at: "2026-10-18T08:00:00Z",
              last_used_at: "2026-10-18T09:00:00Z",
              expires_at: "2026-11-17T08:00:00Z",
            },
          ]),
        },
        "DELETE /me/connected-apps/app1": { status: 204 },
      });
      navigation.at("/account/connected-apps");
      return { ...renderUi(<ConnectedAppsScreen />, { session: ADMIN }), ...api };
    })();

    const table = await screen.findByRole("table", { name: "Your connected apps" });
    expect(table).toHaveTextContent("Read what you may read");
    await expectAccessible();
    await user.click(screen.getByRole("button", { name: "Revoke Claude Code" }));
    await user.click(screen.getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    expect(calls.find((call) => call.method === "DELETE")?.path).toBe("/me/connected-apps/app1");
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/components/security.test.tsx src/lib/session/rules.test.ts src/screens/security.test.tsx src/screens/connect.test.tsx`
Expected: `connect.test.tsx` does not load (`./connect` is not there), and 3 failed: the account's pages have no Connected apps, a user's page lists no applications, and `/connect` is shown to a visitor: 3 failed, 97 passed.

- [ ] **Step 3: Write the code**

First (in `frontend/`): `pnpm gen:api`, which writes `src/lib/api/schema.d.ts` from Task 2's `openapi.json`.

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -265,6 +265,46 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/me/connected-apps": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * List Connected Apps
+         * @description The applications the caller let sign in as them with OAuth, the newest first.
+         */
+        get: operations["list_connected_apps_api_v1_me_connected_apps_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/me/connected-apps/{app_id}": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        post?: never;
+        /**
+         * Revoke Connected App
+         * @description Revoke an approval: the application's tokens stop working at once.
+         */
+        delete: operations["revoke_connected_app_api_v1_me_connected_apps__app_id__delete"];
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/me/password": {
         parameters: {
             query?: never;
@@ -317,6 +357,50 @@ export interface paths {
         patch?: never;
         trace?: never;
     };
+    "/api/v1/oauth/consent": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * Asked
+         * @description What a client asks of the signed-in person, for the consent page to show.
+         */
+        get: operations["asked_api_v1_oauth_consent_get"];
+        put?: never;
+        /**
+         * Approve
+         * @description The person approves: a code for the client, back at its redirect address.
+         */
+        post: operations["approve_api_v1_oauth_consent_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/oauth/refusal": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        /**
+         * Refuse
+         * @description The person refuses: the client is told so (`access_denied`).
+         */
+        post: operations["refuse_api_v1_oauth_refusal_post"];
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/repositories": {
         parameters: {
             query?: never;
@@ -646,6 +730,43 @@ export interface paths {
         patch: operations["update_user_api_v1_users__user_id__patch"];
         trace?: never;
     };
+    "/api/v1/users/{user_id}/connected-apps": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * List User Connected Apps
+         * @description The applications a user let sign in as them with OAuth.
+         */
+        get: operations["list_user_connected_apps_api_v1_users__user_id__connected_apps_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/users/{user_id}/connected-apps/{app_id}": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        get?: never;
+        put?: never;
+        post?: never;
+        /** Revoke User Connected App */
+        delete: operations["revoke_user_connected_app_api_v1_users__user_id__connected_apps__app_id__delete"];
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/users/{user_id}/password": {
         parameters: {
             query?: never;
@@ -706,6 +827,18 @@ export interface components {
             /** Enabled */
             enabled: boolean;
         };
+        /** Answer */
+        Answer: {
+            /** Request */
+            request: string;
+        };
+        /** Asked */
+        Asked: {
+            /** Client */
+            client: string;
+            /** Redirect Host */
+            redirect_host: string;
+        };
         /** AssetView */
         AssetView: {
             /** Blob Store */
@@ -842,6 +975,47 @@ export interface components {
             /** Version */
             version: string;
         };
+        /**
+         * ConnectedApp
+         * @description An approval a user gave an application signed in with OAuth (MCP spec 7.6).
+         */
+        ConnectedApp: {
+            /** Client */
+            client: string;
+            /**
+             * Created At
+             * Format: date-time
+             */
+            created_at: string;
+            /** Expires At */
+            expires_at: string | null;
+            /**
+             * Id
+             * Format: uuid
+             */
+            id: string;
+            /** Last Used At */
+            last_used_at: string | null;
+            /** Redirect Host */
+            redirect_host: string;
+            /** Scopes */
+            scopes: string[] | null;
+        };
+        /** Consent */
+        Consent: {
+            /**
+             * Access
+             * @enum {string}
+             */
+            access: "read" | "all";
+            /**
+             * Lasts
+             * @enum {string}
+             */
+            lasts: "1d" | "30d" | "90d" | "forever";
+            /** Request */
+            request: string;
+        };
         /** Database */
         Database: {
             /** Version */
@@ -991,6 +1165,17 @@ export interface components {
             /** Total */
             total: number;
         };
+        /** Page[ConnectedApp] */
+        Page_ConnectedApp_: {
+            /** Items */
+            items: components["schemas"]["ConnectedApp"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
         /** Page[FormatOut] */
         Page_FormatOut_: {
             /** Items */
@@ -1150,6 +1335,11 @@ export interface components {
             /** Last Error */
             last_error: string | null;
         };
+        /** Redirect */
+        Redirect: {
+            /** Redirect */
+            redirect: string;
+        };
         /** RemoteAuthIn */
         RemoteAuthIn: {
             /** Secret */
@@ -2157,6 +2347,67 @@ export interface operations {
             };
         };
     };
+    list_connected_apps_api_v1_me_connected_apps_get: {
+        parameters: {
+            query?: {
+                limit?: number;
+                offset?: number;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_ConnectedApp_"];
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
+    revoke_connected_app_api_v1_me_connected_apps__app_id__delete: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                app_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            204: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content?: never;
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
     change_password_api_v1_me_password_put: {
         parameters: {
             query?: never;
@@ -2282,6 +2533,103 @@ export interface operations {
             };
         };
     };
+    asked_api_v1_oauth_consent_get: {
+        parameters: {
+            query: {
+                request: string;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Asked"];
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
+    approve_api_v1_oauth_consent_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["Consent"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Redirect"];
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
+    refuse_api_v1_oauth_refusal_post: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["Answer"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Redirect"];
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
     list_repositories_api_v1_repositories_get: {
         parameters: {
             query?: {
@@ -3157,6 +3505,70 @@ export interface operations {
             };
         };
     };
+    list_user_connected_apps_api_v1_users__user_id__connected_apps_get: {
+        parameters: {
+            query?: {
+                limit?: number;
+                offset?: number;
+            };
+            header?: never;
+            path: {
+                user_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_ConnectedApp_"];
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
+    revoke_user_connected_app_api_v1_users__user_id__connected_apps__app_id__delete: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path: {
+                user_id: string;
+                app_id: string;
+            };
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            204: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content?: never;
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
     reset_password_api_v1_users__user_id__password_put: {
         parameters: {
             query?: never;
```

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -41,6 +41,13 @@ export type SigningKeyOut = Schemas["SigningKeyOut"];
 export type SigningKeyGenerate = Schemas["SigningKeyGenerate"];
 export type SigningKeyImport = Schemas["SigningKeyImport"];
 export type BlobStoreOut = Schemas["BlobStoreOut"];
+/** An application a user let sign in as them with OAuth (MCP spec 7.6). */
+export type ConnectedApp = Schemas["ConnectedApp"];
+/** What an application asks, as the consent page shows it. */
+export type Asked = Schemas["Asked"];
+export type Consent = Schemas["Consent"];
+/** Where the browser goes after the consent page: back to the application. */
+export type Redirect = Schemas["Redirect"];
 /** A format the server has: its types, and the public repository a new proxy is given. */
 export type FormatOut = Schemas["FormatOut"];
 export type BlobStoreCreate = Schemas["BlobStoreCreate"];
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -14,6 +14,9 @@ const UPLOAD = "/upload";
 const SEARCH = "/search";
 export const ACCOUNT_TOKENS = "/account/tokens" as Route;
 export const PREFERENCES = "/account/preferences" as Route;
+export const CONNECTED_APPS = "/account/connected-apps" as Route;
+/** The consent page an application signing in with OAuth sends a person to. */
+export const CONNECT = "/connect" as Route;
 export const USERS = "/admin/users" as Route;
 export const NEW_USER = "/admin/users/new" as Route;
 export const ROLES = "/admin/roles" as Route;
```

Change `frontend/src/lib/session/rules.ts`:

```diff
@@ -13,6 +13,8 @@ export const CHANGE_PASSWORD = "/account/password";
 const ACCOUNT_AREA = "/account";
 // But for this: what is kept in the browser is as much a visitor's as anybody's.
 const PREFERENCES = "/account/preferences";
+// Where an application signing in with OAuth sends a person: only they may answer it.
+const CONNECT = "/connect";
 
 export type Decision = { show: true } | { show: false; goTo: string };
 
@@ -91,7 +93,8 @@ export function decide(session: SessionInfo, path: string, next: string | null =
     }
     return { show: true };
   }
-  const inAccount = pathname === ACCOUNT_AREA || pathname.startsWith(`${ACCOUNT_AREA}/`);
+  const inAccount =
+    pathname === ACCOUNT_AREA || pathname.startsWith(`${ACCOUNT_AREA}/`) || pathname === CONNECT;
   if (isAnonymous(session) && (!inAccount || pathname === PREFERENCES)) return { show: true };
   return { show: false, goTo: signInFor(path) };
 }
```

Create `frontend/src/lib/leave.ts`:

```ts
/**
 * Leave this site for another address: an application's, after its consent page. A
 * module of its own, so that a test can see where the browser was sent.
 */
export function leaveFor(address: string): void {
  window.location.assign(address);
}
```

Change `frontend/src/lib/security.ts`:

```diff
@@ -9,8 +9,12 @@ import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tansta
 
 import { api } from "@/lib/api/client";
 import type {
+  Asked,
+  ConnectedApp,
+  Consent,
   Page,
   PasswordReset,
+  Redirect,
   RoleContent,
   RoleCreate,
   RoleOut,
@@ -30,6 +34,7 @@ export const AT_ONCE = 50;
 const EVERY = 200;
 
 const TOKENS = "tokens";
+const APPS = "connected-apps";
 const USERS = "users";
 const ROLES = "roles";
 const SETTINGS = "settings";
@@ -80,6 +85,45 @@ export function useRevokeToken() {
   });
 }
 
+// --- Connected apps (OAuth) -------------------------------------------------------------------
+
+export function useMyConnectedApps() {
+  return useQuery({
+    queryKey: [APPS, "mine"],
+    queryFn: () => api.get<Page<ConnectedApp>>("/me/connected-apps", { query: { limit: EVERY } }),
+  });
+}
+
+export function useRevokeConnectedApp() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (id: string) => api.delete<void>(`/me/connected-apps/${encodeURIComponent(id)}`),
+    onSuccess: () => client.invalidateQueries({ queryKey: [APPS, "mine"] }),
+  });
+}
+
+/** What an application asks of the person signed in: for its consent page. */
+export function useConsentRequest(request: string) {
+  return useQuery({
+    queryKey: ["consent", request],
+    queryFn: () => api.get<Asked>("/oauth/consent", { query: { request } }),
+    enabled: request !== "",
+    retry: false,
+  });
+}
+
+export function useApprove() {
+  return useMutation({
+    mutationFn: (answer: Consent) => api.post<Redirect>("/oauth/consent", answer),
+  });
+}
+
+export function useRefuse() {
+  return useMutation({
+    mutationFn: (request: string) => api.post<Redirect>("/oauth/refusal", { request }),
+  });
+}
+
 // --- Users ----------------------------------------------------------------------------------
 
 export function useUsers(page: number) {
@@ -167,6 +211,24 @@ export function useRevokeUserToken(id: string) {
   });
 }
 
+export function useUserConnectedApps(id: string, enabled: boolean) {
+  return useQuery({
+    queryKey: [APPS, "of", id],
+    queryFn: () =>
+      api.get<Page<ConnectedApp>>(`${user(id)}/connected-apps`, { query: { limit: EVERY } }),
+    enabled,
+  });
+}
+
+export function useRevokeUserConnectedApp(id: string) {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (app: string) =>
+      api.delete<void>(`${user(id)}/connected-apps/${encodeURIComponent(app)}`),
+    onSuccess: () => client.invalidateQueries({ queryKey: [APPS, "of", id] }),
+  });
+}
+
 // --- Roles ----------------------------------------------------------------------------------
 
 export function useRoles(page: number) {
```

Create `frontend/src/components/connected-app-list.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Time } from "@/components/ui/details";
import { ErrorState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import type { ConnectedApp } from "@/lib/api/types";

/**
 * The applications a person let sign in as them with OAuth (MCP spec 7.6): one's own, or
 * a user's as an administrator sees them. An application is known by the name it gave
 * itself, and by where it was sent back to. `onRevoke` returns when it is gone, or throws.
 */
export function ConnectedAppList({
  caption,
  apps,
  onRevoke,
  empty,
}: {
  caption: string;
  apps: ConnectedApp[];
  /** Without it, the applications can be seen and not revoked. */
  onRevoke?: (app: ConnectedApp) => Promise<unknown>;
  empty: string;
}) {
  const t = useTranslations("connectedApps");
  const [asked, setAsked] = useState<ConnectedApp | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const list = useRef<HTMLDivElement>(null);
  // After one is revoked the button that was pressed is gone: the keyboard is put here.
  const revoked = useRef(false);
  useEffect(() => {
    if (asked !== null || !revoked.current) return;
    revoked.current = false;
    list.current?.focus();
  }, [asked]);

  async function revoke(app: ConnectedApp) {
    setBusy(true);
    setFailure(null);
    try {
      await onRevoke?.(app);
      revoked.current = true;
      setAsked(null);
    } catch (error) {
      setAsked(null);
      setFailure(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={list} tabIndex={-1} role="group" aria-label={caption} className="outline-none">
      {apps.length === 0 ? <p className="p-6 text-fg-muted">{empty}</p> : null}
      <Table caption={caption} hidden={apps.length === 0}>
        <thead>
          <tr>
            <Th>{t("columns.app")}</Th>
            <Th>{t("columns.mayDo")}</Th>
            <Th>{t("columns.expires")}</Th>
            <Th>{t("columns.lastUsed")}</Th>
            <Th>{t("columns.connected")}</Th>
            {onRevoke ? <Th className="text-right">{t("columns.actions")}</Th> : null}
          </tr>
        </thead>
        <tbody>
          {apps.map((app) => (
            <tr key={app.id} className="hover:bg-raised">
              <Td>
                <span className="font-medium break-all">{app.client}</span>
                <span className="block text-xs text-fg-muted">
                  {t("sentTo", { host: app.redirect_host })}
                </span>
              </Td>
              <Td>{app.scopes === null ? t("everything") : t("reading")}</Td>
              <Td className="whitespace-nowrap text-fg-muted">
                {app.expires_at === null ? t("never") : <Time value={app.expires_at} />}
              </Td>
              <Td className="whitespace-nowrap text-fg-muted">
                <Time value={app.last_used_at} />
              </Td>
              <Td className="whitespace-nowrap text-fg-muted">
                <Time value={app.created_at} />
              </Td>
              {onRevoke ? (
                <Td className="text-right">
                  <Button
                    size="sm"
                    aria-label={t("revokeNamed", { name: app.client })}
                    onClick={() => setAsked(app)}
                  >
                    {t("revoke")}
                  </Button>
                </Td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
      {failure ? <ErrorState error={failure} className="m-4" /> : null}
      <ConfirmDialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
        title={t("confirmTitle", { name: asked?.client ?? "" })}
        confirmLabel={t("revoke")}
        busy={busy}
        onConfirm={() => {
          if (asked) void revoke(asked);
        }}
      >
        {t("confirmText")}
      </ConfirmDialog>
    </div>
  );
}
```

Change `frontend/src/components/account-nav.tsx`:

```diff
@@ -1,20 +1,25 @@
 "use client";
 
-import { KeyRound, SlidersHorizontal, Ticket, type LucideIcon } from "lucide-react";
+import { KeyRound, Plug, SlidersHorizontal, Ticket, type LucideIcon } from "lucide-react";
 import type { Route } from "next";
 import { useTranslations } from "next-intl";
 import { usePathname } from "next/navigation";
 
 import { AppLink } from "@/components/ui/link";
 import { cn } from "@/lib/cn";
-import { ACCOUNT_TOKENS, PREFERENCES } from "@/lib/paths";
+import { ACCOUNT_TOKENS, CONNECTED_APPS, PREFERENCES } from "@/lib/paths";
 import { CHANGE_PASSWORD } from "@/lib/session/rules";
 import { useSession } from "@/lib/session/session";
 
-type Page = { key: "tokens" | "password" | "preferences"; href: Route; icon: LucideIcon };
+type Page = {
+  key: "tokens" | "apps" | "password" | "preferences";
+  href: Route;
+  icon: LucideIcon;
+};
 
 const PAGES: Page[] = [
   { key: "tokens", href: ACCOUNT_TOKENS, icon: Ticket },
+  { key: "apps", href: CONNECTED_APPS, icon: Plug },
   { key: "password", href: CHANGE_PASSWORD as Route, icon: KeyRound },
   { key: "preferences", href: PREFERENCES, icon: SlidersHorizontal },
 ];
```

Create `frontend/src/screens/connect.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ChoiceGroup, SelectField } from "@/components/ui/inputs";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import type { Consent } from "@/lib/api/types";
import { leaveFor } from "@/lib/leave";
import { useApprove, useConsentRequest, useRefuse } from "@/lib/security";

const ACCESS = ["read", "all"] as const;
const LASTS = ["1d", "30d", "90d", "forever"] as const;

/**
 * The consent page (MCP spec 7.3): an application signing in with OAuth asks to act as
 * the person signed in, and they choose what it may do, and for how long, or refuse.
 * The application's name is its own words, and is shown as such.
 */
export function ConnectScreen() {
  const t = useTranslations("connect");
  const request = useSearchParams().get("request") ?? "";
  const asked = useConsentRequest(request);
  const approve = useApprove();
  const refuse = useRefuse();
  const [access, setAccess] = useState<Consent["access"]>("read");
  const [lasts, setLasts] = useState<Consent["lasts"]>("30d");
  const busy = approve.isPending || refuse.isPending;

  function allow(event: FormEvent) {
    event.preventDefault();
    approve.mutate({ request, access, lasts }, { onSuccess: (sent) => leaveFor(sent.redirect) });
  }

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={t("title")} />
      {request === "" ? (
        <Alert tone="danger">{t("nothingAsked")}</Alert>
      ) : asked.isError ? (
        <ErrorState error={asked.error} />
      ) : !asked.data ? (
        <LoadingState />
      ) : (
        <Panel className="p-6">
          <p className="mb-2 text-fg">
            {t.rich("asks", {
              name: asked.data.client,
              app: (chunks) => <strong className="break-all">{chunks}</strong>,
            })}
          </p>
          <p className="mb-6 text-sm text-fg-muted">
            {t("itsWords", { host: asked.data.redirect_host })}
          </p>
          <form onSubmit={allow} className="flex flex-col gap-5">
            <ChoiceGroup
              legend={t("fields.access")}
              value={access}
              onChange={(value) => setAccess(value as Consent["access"])}
              options={ACCESS.map((value) => ({
                value,
                label: t(`access.${value}`),
                hint: t(`accessHints.${value}`),
              }))}
            />
            <SelectField
              label={t("fields.lasts")}
              value={lasts}
              onChange={(event) => setLasts(event.target.value as Consent["lasts"])}
              choices={LASTS.map((value) => ({ value, label: t(`lasts.${value}`) }))}
            />
            {approve.isError ? <ErrorState error={approve.error} /> : null}
            {refuse.isError ? <ErrorState error={refuse.error} /> : null}
            <div className="flex flex-wrap gap-3">
              <Button type="submit" variant="primary" busy={approve.isPending} disabled={busy}>
                {t("allow")}
              </Button>
              <Button
                type="button"
                variant="secondary"
                busy={refuse.isPending}
                disabled={busy}
                onClick={() =>
                  refuse.mutate(request, { onSuccess: (sent) => leaveFor(sent.redirect) })
                }
              >
                {t("refuse")}
              </Button>
            </div>
          </form>
        </Panel>
      )}
    </div>
  );
}
```

Create `frontend/src/screens/connected-apps.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";

import { AccountNav } from "@/components/account-nav";
import { ConnectedAppList } from "@/components/connected-app-list";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useMyConnectedApps, useRevokeConnectedApp } from "@/lib/security";

/** The applications one let sign in as oneself with OAuth, and revoking them (7.6). */
export function ConnectedAppsScreen() {
  const t = useTranslations("connectedApps");
  const notify = useNotify();
  const apps = useMyConnectedApps();
  const revoke = useRevokeConnectedApp();
  return (
    <div className="mx-auto max-w-5xl">
      <AccountNav />
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel>
        {apps.isError ? (
          <ErrorState error={apps.error} onRetry={() => void apps.refetch()} className="m-4" />
        ) : !apps.data ? (
          <LoadingState />
        ) : (
          <ConnectedAppList
            caption={t("listTitle")}
            apps={apps.data.items}
            empty={t("none")}
            onRevoke={async (app) => {
              await revoke.mutateAsync(app.id);
              notify(t("revoked", { name: app.client }));
            }}
          />
        )}
      </Panel>
    </div>
  );
}
```

Change `frontend/src/screens/user.tsx`:

```diff
@@ -7,6 +7,7 @@ import { usePathname, useRouter } from "next/navigation";
 import { useEffect, useRef, useState, type FormEvent } from "react";
 
 import { NewPasswordField } from "@/components/new-password-field";
+import { ConnectedAppList } from "@/components/connected-app-list";
 import { TokenList } from "@/components/token-list";
 import { Alert } from "@/components/ui/alert";
 import { Breadcrumbs } from "@/components/ui/breadcrumbs";
@@ -30,9 +31,11 @@ import {
   useDeleteUser,
   useEveryRole,
   useResetPassword,
+  useRevokeUserConnectedApp,
   useRevokeUserToken,
   useUpdateUser,
   useUser,
+  useUserConnectedApps,
   useUserTokens,
 } from "@/lib/security";
 import { allows, CHANGE_PASSWORD } from "@/lib/session/rules";
@@ -494,6 +497,37 @@ function Tokens({ user, mayRevoke }: { user: UserOut; mayRevoke: boolean }) {
   );
 }
 
+function ConnectedApps({ user, mayRevoke }: { user: UserOut; mayRevoke: boolean }) {
+  const t = useTranslations("users");
+  const notify = useNotify();
+  const apps = useUserConnectedApps(user.id, true);
+  const revoke = useRevokeUserConnectedApp(user.id);
+  return (
+    <Panel>
+      <h2 className="px-6 pt-6 text-lg font-semibold text-fg uppercase">{t("appsTitle")}</h2>
+      {apps.isError ? (
+        <ErrorState error={apps.error} onRetry={() => void apps.refetch()} className="m-6" />
+      ) : !apps.data ? (
+        <LoadingState />
+      ) : (
+        <ConnectedAppList
+          caption={t("appsOf", { username: user.username })}
+          apps={apps.data.items}
+          empty={t("noApps")}
+          onRevoke={
+            mayRevoke
+              ? async (app) => {
+                  await revoke.mutateAsync(app.id);
+                  notify(t("appRevoked", { name: app.client, username: user.username }));
+                }
+              : undefined
+          }
+        />
+      )}
+    </Panel>
+  );
+}
+
 function Delete({
   user,
   remove,
@@ -594,7 +628,10 @@ export function UserScreen() {
         <Password user={found} />
       )}
       {may("admin:tokens:read") ? (
-        <Tokens user={found} mayRevoke={may("admin:tokens:write")} />
+        <>
+          <Tokens user={found} mayRevoke={may("admin:tokens:write")} />
+          <ConnectedApps user={found} mayRevoke={may("admin:tokens:write")} />
+        </>
       ) : null}
       {mayWrite ? (
         isSelf || found.builtin ? (
```

Create `frontend/src/app/(shell)/connect/page.tsx`:

```tsx
import type { Metadata } from "next";

import { ConnectScreen } from "@/screens/connect";

import messages from "../../../../messages/en.json";

export const metadata: Metadata = { title: messages.connect.title };

export default function Page() {
  return <ConnectScreen />;
}
```

Create `frontend/src/app/(shell)/account/connected-apps/page.tsx`:

```tsx
import type { Metadata } from "next";

import { ConnectedAppsScreen } from "@/screens/connected-apps";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.connectedApps.title };

export default function Page() {
  return <ConnectedAppsScreen />;
}
```

Change `frontend/messages/en.json`:

```diff
@@ -335,6 +335,7 @@
     "label": "Account",
     "pages": {
       "tokens": "API tokens",
+      "apps": "Connected apps",
       "password": "Password",
       "preferences": "Preferences"
     }
@@ -558,7 +559,11 @@
     "builtinDelete": "A built-in user cannot be deleted. It can be disabled.",
     "mayNotCreate": "You may not create users.",
     "selfPassword": "This is your own account: your password is changed under your account, where you are asked for the one you have.",
-    "toOwnPassword": "Change your password"
+    "toOwnPassword": "Change your password",
+    "appsTitle": "Connected apps",
+    "appsOf": "Applications {username} connected",
+    "noApps": "This user has connected no application.",
+    "appRevoked": "Revoked {name}, which {username} connected."
   },
   "roles": {
     "title": "Roles",
@@ -917,5 +922,54 @@
     "imported": "{name} signs with the imported key.",
     "replaceBody": "Its indexes are signed with that key from now on. Every machine that uses {name} must install the new public key, or it refuses what the repository serves.",
     "unreadable": "This key cannot be read with the installation's secret key, so nothing is signed with it: every client is refused the indexes. Generate a new key or import one."
+  },
+  "connectedApps": {
+    "title": "Connected apps",
+    "intro": "Applications you let sign in as you with OAuth, such as an AI agent. Revoke one, and its sign-in stops working at once.",
+    "listTitle": "Your connected apps",
+    "none": "You have connected no application.",
+    "sentTo": "Sent back to {host}",
+    "everything": "Everything you may do",
+    "reading": "Read what you may read",
+    "never": "Until it is revoked",
+    "columns": {
+      "app": "Application",
+      "mayDo": "May do",
+      "expires": "Expires",
+      "lastUsed": "Last used",
+      "connected": "Connected",
+      "actions": "Actions"
+    },
+    "revoke": "Revoke",
+    "revokeNamed": "Revoke {name}",
+    "confirmTitle": "Revoke {name}?",
+    "confirmText": "It is signed out at once, and must be connected again to sign in.",
+    "revoked": "Revoked {name}."
+  },
+  "connect": {
+    "title": "Connect an application",
+    "asks": "<app>{name}</app> asks to use MegooArti as you.",
+    "itsWords": "That is the name it gave itself. When you answer, your browser goes back to it, at {host}.",
+    "nothingAsked": "Nothing is asked here. Start again from the application.",
+    "fields": {
+      "access": "What it may do",
+      "lasts": "For how long"
+    },
+    "access": {
+      "read": "Read what I can read",
+      "all": "Everything I can do"
+    },
+    "accessHints": {
+      "read": "Find and read packages and settings. It changes nothing.",
+      "all": "Whatever you may do, changing and deleting included."
+    },
+    "lasts": {
+      "1d": "A day",
+      "30d": "30 days",
+      "90d": "90 days",
+      "forever": "Until I revoke it"
+    },
+    "allow": "Allow",
+    "refuse": "Refuse"
   }
 }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm vitest run src/components/security.test.tsx src/lib/session/rules.test.ts src/screens/security.test.tsx src/screens/connect.test.tsx && pnpm lint && pnpm typecheck`
Expected: 105 passed; `All matched files use Prettier code style!`; the types check.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(ui): the consent page of an agent signing in with OAuth, and connected apps"
```

---

### Task 4: Through the gateway, in the browser, and with the official client

**Files:**
- Modify: `gateway/nginx.conf`, `docs/installation.md`
- Test: `backend/tests/test_mcp_oauth_client.py`; modify `backend/tests/test_compose.py`, `frontend/e2e/ui.spec.ts`

**Interfaces:**
- Consumes: Tasks 1 to 3, through the built images; `tests.containers.call`, `HTTP_PORT`; the fixtures `stack` and `administrator`; the browser test's `page`, `asAdministrator`, `expectAccessible`.
- Produces: the gateway's `location /.well-known/` and `location /oauth/`, and their rows in the installation guide.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/test_compose.py`:

```diff
@@ -64,7 +64,7 @@ def test_the_backend_takes_the_gateways_word_for_who_is_calling():
     assert "ports" not in services()["backend"]  # which is why it can
 
 
-def test_the_gateway_sends_the_api_the_repositories_the_registry_and_mcp_to_the_backend():
+def test_the_gateway_sends_the_api_the_repositories_the_registry_mcp_and_oauth_to_the_backend():
     routes = dict(re.findall(r"location (\S+) \{\s*proxy_pass (\$\w+);\s*\}", GATEWAY))
 
     assert routes == {
@@ -72,6 +72,8 @@ def test_the_gateway_sends_the_api_the_repositories_the_registry_and_mcp_to_the_
         "/repository/": "$backend",
         "/v2/": "$backend",
         "/mcp": "$backend",
+        "/.well-known/": "$backend",
+        "/oauth/": "$backend",
         "/": "$frontend",
     }
 
@@ -79,8 +81,8 @@ def test_the_gateway_sends_the_api_the_repositories_the_registry_and_mcp_to_the_
 def test_the_gateway_passes_a_path_on_exactly_as_it_was_sent():
     # With anything after the upstream's address nginx decodes the path and writes it
     # again: an npm scope's encoded slash would become a real one.
-    # The API, the repositories, the registry and MCP; then the web UI.
-    assert re.findall(r"proxy_pass ([^;]+);", GATEWAY) == ["$backend"] * 4 + ["$frontend"]
+    # The API, the repositories, the registry, MCP and its OAuth; then the web UI.
+    assert re.findall(r"proxy_pass ([^;]+);", GATEWAY) == ["$backend"] * 6 + ["$frontend"]
     assert "rewrite" not in GATEWAY
 
 
```

Create `backend/tests/test_mcp_oauth_client.py`:

```python
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
```

Change `frontend/e2e/ui.spec.ts`:

```diff
@@ -1,3 +1,4 @@
+import { createHash, randomBytes } from "node:crypto";
 import { readFile } from "node:fs/promises";
 
 import AxeBuilder from "@axe-core/playwright";
@@ -971,6 +972,80 @@ test("the tokens screen meets WCAG 2.1 AA in both modes", async () => {
   });
 });
 
+test("an agent signing in with OAuth is approved on the consent page, connected, and revoked", async ({
+  playwright,
+  baseURL,
+}) => {
+  // OAuth names the server by its base URL: this browser's address of it.
+  const origin = new URL(baseURL ?? "").origin;
+  await asAdministrator("put", "/api/v1/settings/base-url", { base_url: origin });
+  const callback = `${origin}/oauth-test-callback`;
+  const registered = await page.request.post("/oauth/register", {
+    data: { client_name: "Browser test agent", redirect_uris: [callback] },
+  });
+  expect(registered.status()).toBe(201);
+  const clientId = (await registered.json()).client_id as string;
+  const verifier = randomBytes(48).toString("base64url");
+  const challenge = createHash("sha256").update(verifier).digest("base64url");
+  const asked = new URLSearchParams({
+    response_type: "code",
+    client_id: clientId,
+    redirect_uri: callback,
+    code_challenge: challenge,
+    code_challenge_method: "S256",
+    state: "browser-state",
+    resource: `${origin}/mcp`,
+  });
+
+  await page.goto(`/oauth/authorize?${asked.toString()}`);
+  await expect(page).toHaveURL(/\/connect\?request=/);
+  await expect(
+    page.getByRole("heading", { level: 1, name: "Connect an application" }),
+  ).toBeVisible();
+  await expect(page.getByText("Browser test agent")).toBeVisible();
+  await expect(page.getByRole("radio", { name: /Read what I can read/ })).toBeChecked();
+  await expectAccessible();
+  await page.getByRole("button", { name: "Allow" }).click();
+
+  await page.waitForURL(/\/oauth-test-callback\?/);
+  const back = new URL(page.url()).searchParams;
+  expect(back.get("state")).toBe("browser-state");
+  const traded = await page.request.post("/oauth/token", {
+    form: {
+      grant_type: "authorization_code",
+      client_id: clientId,
+      code: back.get("code") ?? "",
+      redirect_uri: callback,
+      code_verifier: verifier,
+    },
+  });
+  expect(traded.status()).toBe(200);
+  const access = (await traded.json()).access_token as string;
+  expect(access).toMatch(/^mgo_/);
+  const agent = await playwright.request.newContext({
+    baseURL,
+    extraHTTPHeaders: {
+      Authorization: `Bearer ${access}`,
+      Accept: "application/json, text/event-stream",
+    },
+  });
+  const listTools = { jsonrpc: "2.0", id: 1, method: "tools/list" };
+  expect((await agent.post("/mcp", { data: listTools })).status()).toBe(200);
+
+  await page.goto("/account/connected-apps");
+  const row = page.getByRole("row", { name: /Browser test agent/ });
+  await expect(row).toContainText("Read what you may read");
+  await expectAccessible();
+  await row.getByRole("button", { name: "Revoke Browser test agent" }).click();
+  await page.getByRole("alertdialog").getByRole("button", { name: "Revoke" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "Revoked Browser test agent.",
+  );
+  expect((await agent.post("/mcp", { data: listTools })).status()).toBe(401);
+  await agent.dispose();
+  await asAdministrator("put", "/api/v1/settings/base-url", { base_url: null });
+});
+
 test("the administration is in the navigation, in a row that nothing lies over", async () => {
   const main = page.getByRole("navigation", { name: "Main" });
   const overlaps = async () => {
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/test_compose.py && uv run pytest -q -m docker tests/test_mcp_oauth_client.py` (the second builds the images and starts the stack: a few minutes)
Expected: `tests/test_compose.py`: 2 failed (the gateway has no `/.well-known/` or `/oauth/`); the official client: `OAuthRegistrationError: Registration failed: 404`, the web UI's page, as the gateway sends `/oauth/register` to it.

- [ ] **Step 3: Pass `/.well-known/` and `/oauth/` to the backend, and say so**

Change `gateway/nginx.conf`:

```diff
@@ -60,6 +60,15 @@ server {
         proxy_pass $backend;
     }
 
+    # How agents sign in to it with OAuth: what they discover, and where they sign in.
+    location /.well-known/ {
+        proxy_pass $backend;
+    }
+
+    location /oauth/ {
+        proxy_pass $backend;
+    }
+
     location / {
         proxy_pass $frontend;
     }
```

Change `docs/installation.md`:

```diff
@@ -128,6 +128,8 @@ One address serves everything, and each request goes to the right service:
 | `/repository/` | backend, port 8000 | Maven, npm, PyPI, APT, YUM, apk and Raw repositories |
 | `/v2/` | backend, port 8000 | The Docker registry |
 | `/mcp` | backend, port 8000 | The MCP server, for AI agents |
+| `/.well-known/` | backend, port 8000 | How AI agents find where to sign in with OAuth |
+| `/oauth/` | backend, port 8000 | Where they register, and trade a code for tokens |
 | everything else | frontend, port 3000 | The web UI |
 
 [gateway/nginx.conf](../gateway/nginx.conf) does that: it is what Compose runs, and
```

- [ ] **Step 4: Run them to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/test_compose.py tests/test_documents.py && uv run pytest -q -m docker tests/test_mcp_oauth_client.py tests/test_ui_client.py`
Expected: 169 passed; then 13 passed (the official client through the gateway, and the browser test with the consent page and Connected apps).

- [ ] **Step 5: Commit**

```bash
git add gateway docs/installation.md backend/tests frontend/e2e
git commit -m "feat(gateway): OAuth's addresses to the backend; test: an agent signs in with OAuth in the browser and with the official client"
```

---

### Task 5: The guide, and what the plan settled

**Files:**
- Modify: `docs/mcp.md`, `docs/administration.md`, `docs/superpowers/specs/2026-10-18-mcp-design.md`

**Interfaces:**
- Consumes: everything above, as it is.
- Produces: the guide's OAuth sign-in and claude.ai's connector; Connected apps among an administrator's `admin:tokens`; the spec's "Settled while building plan 14c".

- [ ] **Step 1: Write the guide and the spec's rows**

Change `docs/mcp.md`:

````diff
@@ -11,9 +11,22 @@ and a token whose scopes are narrower narrows it too.
 
 ## Signing in
 
-Make an API token in the web UI under Account, Tokens (or at `/api/v1/me/tokens`), and
-give it to the agent as a bearer token: `Authorization: Bearer mga_...`. Nothing else
-signs in to `/mcp`: not a password, not the web UI's session, and not anonymous access.
+An agent signs in in one of two ways, and in no other: not with a password, not with
+the web UI's session, and not as an anonymous visitor.
+
+- **With an API token.** Make one in the web UI under Account, Tokens (or at
+  `/api/v1/me/tokens`), and give it to the agent as a bearer token:
+  `Authorization: Bearer mga_...`.
+- **With OAuth.** A client that signs in with OAuth (claude.ai's connectors, and other
+  clients when they are given no token) sends you to MegooArti's consent page. Signed in
+  there, you see the name the client gave itself and where your browser goes back to,
+  and you choose what it may do (read what you can read, or everything you can do) and
+  for how long (a day, 30 or 90 days, or until you revoke it). The client is given an
+  access token for an hour at a time, which it renews; a token that leaks works at
+  `/mcp` only, and a renewal used twice ends the approval. Account, Connected apps lists
+  what you have connected, and revokes it at once; an administrator sees a user's under
+  their user. OAuth needs the server's base URL, set under System: the server is named
+  by it.
 
 Give an agent a token of its own, with the scopes it needs, and an expiry. For an agent
 that only reads, `repository:*:*:browse` and `repository:*:*:read`. The token's
@@ -62,8 +75,8 @@ claude mcp add --transport http megooarti https://artifacts.example.org/mcp \
 }
 ```
 
-A client that only signs in with OAuth, such as claude.ai's connectors, cannot connect
-yet.
+**claude.ai:** add a custom connector with the address `https://artifacts.example.org/mcp`.
+It signs in with OAuth: you are sent to the consent page to approve it.
 
 ## The tools
 
````

Change `docs/administration.md`:

```diff
@@ -51,7 +51,7 @@ area's name alone gives both.
 | --- | --- |
 | `admin:users` | The users: making, changing and deleting them, the roles they hold, and setting another user's password |
 | `admin:roles` | The roles, and the permission patterns they hold |
-| `admin:tokens` | Seeing which API tokens another user has, and revoking one. Nobody sees a token's value but its owner, once, when it is made |
+| `admin:tokens` | Seeing which API tokens another user has, and revoking one; and the applications they connected with OAuth, and revoking one. Nobody sees a token's value but its owner, once, when it is made |
 | `admin:repositories` | Making, changing and deleting repositories, having a proxy check its remote again, rebuilding an index, and the keys repositories sign with |
 | `admin:blobstores` | The blob stores |
 | `admin:settings` | The base URL and anonymous access; to read, also what is running (`/api/v1/system/information`) |
```

Change `docs/superpowers/specs/2026-10-18-mcp-design.md`:

```diff
@@ -253,6 +253,19 @@ Each plan ends with something an agent uses: 14a with a token and the read tools
 | N9 | A password or a secret given to a tool, at any depth of what it is given (`password`, `proxy.remote_auth.secret`), is written `[redacted]` in the call's log; `delete_path` takes a path with a slash at either end, and refuses one that is only slashes; `revoke_token` finds a token by its name however many its user has; the form gives a proxy chosen before `GET /formats` answered its remote when it does; the server's instructions say what the tools that change things are for. | The final review of 14b: 8.4 says no logged argument is a secret, and 14b's tools are the first given any. |
 | N10 | `create_user`, `update_user`, `create_role` and `update_role` refuse to give, by a role or a permission, what the caller may not do itself, by its permissions narrowed by its token's scopes (`forbidden: You may not give what you may not do yourself: …`). The REST API is not changed. | The product owner's ruling on 14b's final review (I1): a token scoped to `admin:users:write` could make an administrator whose password the agent chose, sign in as them, and be unscoped; so "an agent cannot give itself credentials" (section 2) holds. |
 
+### Settled while building plan 14c
+
+| # | What | Why |
+| --- | --- | --- |
+| O1 | An authorization request is checked at `/oauth/authorize`, then sealed (as a registry token is, `secrets_box.seal_at`, for 10 minutes) into the address of the consent page, `/connect?request=…`; nothing is stored until the person answers. A client or redirect address that is not known is answered with an error there, never redirected to; any other fault goes back to the client's redirect address with its `state`. | The consent page may wait for a sign-in; a request that is never answered leaves nothing behind (RFC 6749 4.1.2.1). |
+| O2 | The consent page is the web UI's `/connect`, which only a person signed in sees (a visitor is sent to sign in, and back with the request); it reads `GET /api/v1/oauth/consent`, and answers with `POST /api/v1/oauth/consent` or `POST /api/v1/oauth/refusal`, which give the address the browser is sent to. They need a session, as making a token does. | 7.3. `/oauth/` itself is the backend's, through the gateway. |
+| O3 | A code is an `OAuthToken` of kind `code` (60 seconds, used once, with its PKCE challenge and redirect address); a code or a refresh token used a second time deletes the approval and every token of it. Expired codes, tokens and approvals, and clients no approval names 30 days after they registered, are removed by the compaction job. | 7.4, 7.2: one table of hashes for every kind, and the job that already tends the server. |
+| O4 | An access token signs in at `/mcp` only: `agent_principal` takes `mga_` and `mgo_`; every other route reads `mgo_` as no token of its (`401`). The principal of an OAuth token is the user's, narrowed by the approval's scopes, with `grant_id`; `whoami` says `kind: oauth` and the client's name. | E6. |
+| O5 | `/mcp`'s `401` names `resource_metadata` in `WWW-Authenticate`, from the base URL or, without one, the request's own address; the discovery documents and the OAuth endpoints answer `503 temporarily_unavailable`, saying to set the base URL, where there is none. | 7.1: a client is told where to look even before an administrator has set it up. |
+| O6 | Registration answers `token_endpoint_auth_method: none` whatever was asked (every client is public), and takes a redirect address that is `https`, or `http` to `127.0.0.1`, `localhost` or `[::1]`, without a fragment or credentials; at most ten. `client_name` is cut at 200 characters. | 7.2; the official client asks for `client_secret_post`, and goes on with what it is answered (RFC 7591 3.2.1). |
+| O7 | Connected apps: `GET` and `DELETE /api/v1/me/connected-apps`, and `/api/v1/users/{id}/connected-apps` with `admin:tokens:read` and `write`; the web UI's Account, Connected apps, and a section of a user's page. `user_details` gives `connected_apps`, and `revoke_token` takes `connected_app` (an id) in place of `token` (in place of 14b's N8). | 7.6, 6.2. |
+| O8 | The tests: every step in `tests/mcp/test_oauth.py`; the official client's OAuth provider in-process (`test_oauth_client.py`) and through the gateway of the built stack (`test_mcp_oauth_client.py`), the person's consent answered by the API as the consent page answers it; the consent page and Connected apps in the browser test. | 9.2, 9.3. The browser test's redirect address is the UI's own (`http://localhost`), so that no request leaves the site. |
+
 ## 13. Requirements
 
 | BRD | Where |
```

- [ ] **Step 2: Run every test**

Run (in `backend/`): `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; then (in `frontend/`): `pnpm vitest run`
Expected: `421 files already formatted`, `All checks passed!`, 4068 passed, 2 skipped, 112 deselected; then 869 passed.

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: AI agents sign in with OAuth, and claude.ai connects; what plan 14c settled"
```
