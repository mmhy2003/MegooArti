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
