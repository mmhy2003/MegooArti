"""Signing in at an OIDC provider (spec 5): sent there with a state, a nonce and PKCE,
back with a code, which is traded for an ID token that is checked before anybody is
made or signed in; and every way it can go wrong, said on the sign-in screen."""

import time
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from megooarti.security import roles
from megooarti.security.models import User
from tests.accounts import basic, bearer
from tests.security.provider import CLIENT_ID, ISSUER, Key, query_of

SESSION = "/api/v1/auth/session"
DEVELOPERS = [{"group": "developers", "roles": ["developers"]}]


def oidc_path(source, step: str) -> str:
    return f"/api/v1/auth/oidc/{source.id}/{step}"


async def sign_in(client, provider, source, login: str, *, next: str = "/search", **back):
    """The whole sign-in as a browser goes through it: start, the provider, the callback."""
    started = await client.get(oidc_path(source, "start"), params={"next": next})
    assert started.status_code == 302, started.text
    address = started.headers["location"]
    code = provider.authorize(address, login)
    answer = {"code": code, "state": query_of(address)["state"], **back}
    return await client.get(oidc_path(source, "callback"), params=answer)


def landed(response) -> tuple[str, dict[str, str]]:
    """Where the browser was sent back to, and what it was told there."""
    assert response.status_code == 302, response.text
    place = response.headers["location"]
    return urlsplit(place).path, {
        name: values[0] for name, values in parse_qs(urlsplit(place).query).items()
    }


async def stored(sessionmaker, username: str) -> User | None:
    async with sessionmaker() as db:
        return await db.scalar(select(User).where(User.username == username))


async def test_start_sends_the_browser_to_the_provider_with_a_state_a_nonce_and_pkce(
    client, provider, add_oidc_source
):
    source = await add_oidc_source()

    started = await client.get(oidc_path(source, "start"), params={"next": "/search"})
    asked = query_of(started.headers["location"])
    cookie = started.headers["set-cookie"]

    assert started.status_code == 302
    assert started.headers["location"].startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    assert asked["client_id"] == CLIENT_ID
    assert asked["redirect_uri"] == f"https://test/api/v1/auth/oidc/{source.id}/callback"
    assert asked["scope"] == "openid profile email"
    assert (asked["response_type"], asked["code_challenge_method"]) == ("code", "S256")
    assert len(asked["state"]) >= 43 and len(asked["nonce"]) >= 43
    assert asked["state"] not in cookie and asked["nonce"] not in cookie  # sealed
    for said in (
        "megooarti_oidc=",
        "HttpOnly",
        "Max-Age=600",
        "Path=/api/v1/auth/oidc/",
        "SameSite=lax",
    ):
        assert said in cookie


async def test_the_first_sign_in_makes_the_user_starts_a_session_and_goes_on(
    client, provider, add_oidc_source, sessionmaker
):
    async with sessionmaker() as db:
        await roles.create_role(db, "developers", "", ["repository:*:*:read"], [])
        await db.commit()
    source = await add_oidc_source(mapping=DEVELOPERS)
    provider.person("kim", name="Kim Lee", email="kim@corp.example", groups=["developers", "staff"])

    back = await sign_in(client, provider, source, "kim")
    session = (await client.get(SESSION)).json()
    kim = await stored(sessionmaker, "kim")

    assert landed(back) == ("/login", {"next": "/search", "signed_in": "1"})
    assert "megooarti_session=" in back.headers.get("set-cookie", "")
    assert session["user"]["username"] == "kim" and session["method"] == "session"
    assert "repository:*:*:read" in session["permissions"]
    assert (kim.source_id, kim.external_id) == (source.id, "subject-of-kim")
    assert (kim.display_name, kim.email, kim.password_hash) == ("Kim Lee", "kim@corp.example", None)


async def test_each_sign_in_brings_the_user_up_to_date(
    client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source()
    provider.person("kim", name="Kim Lee")
    await sign_in(client, provider, source, "kim")

    provider.person("kim", name="Kim Park", preferred_username="kim.park")
    await sign_in(client, provider, source, "kim")

    assert await stored(sessionmaker, "kim") is None
    assert (await stored(sessionmaker, "kim.park")).display_name == "Kim Park"


async def test_the_provider_is_asked_for_its_metadata_and_keys_once_an_hour(
    client, provider, add_oidc_source
):
    source = await add_oidc_source()
    provider.person("kim")

    await sign_in(client, provider, source, "kim")
    await sign_in(client, provider, source, "kim")

    assert provider.asked.count("/realms/corp/.well-known/openid-configuration") == 1
    assert provider.asked.count("/realms/corp/protocol/openid-connect/certs") == 1


async def test_a_key_the_provider_rolled_over_to_is_fetched(client, provider, add_oidc_source):
    source = await add_oidc_source()
    provider.person("kim")
    await sign_in(client, provider, source, "kim")

    provider.rotate()
    again = await sign_in(client, provider, source, "kim")

    assert landed(again)[1].get("signed_in") == "1"


async def test_a_refusal_at_the_provider_is_said_and_makes_nobody(
    client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source()
    provider.person("kim")

    refused = await sign_in(client, provider, source, "kim", error="access_denied")

    assert landed(refused) == ("/login", {"error": "denied", "next": "/search"})
    assert await stored(sessionmaker, "kim") is None
    assert (await client.get(SESSION)).json()["authenticated"] is False


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"aud": "another-client"}, "audience"),
        ({"iss": "https://elsewhere.example"}, "issuer"),
        ({"nonce": "of-another-sign-in"}, "nonce"),
        ({"exp": int(time.time()) - 400}, "expired"),
        ({"sub": None}, "no subject"),
        ({"aud": ["megooarti", "another-client"]}, "azp"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
async def test_an_id_token_that_does_not_check_makes_nobody(
    client, provider, add_oidc_source, sessionmaker, change, why
):
    source = await add_oidc_source()
    provider.person("kim")
    provider.claims_changed = change

    failed = await sign_in(client, provider, source, "kim")

    assert landed(failed)[1]["error"] == "failed", why
    assert await stored(sessionmaker, "kim") is None


async def test_an_id_token_signed_by_another_key_makes_nobody(
    client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source()
    provider.person("kim")
    provider.signer = Key("key-1")  # the provider's name for its key, and not its key

    failed = await sign_in(client, provider, source, "kim")

    assert landed(failed)[1]["error"] == "failed"
    assert await stored(sessionmaker, "kim") is None


async def test_an_id_token_late_by_less_than_five_minutes_is_taken(
    client, provider, add_oidc_source
):
    source = await add_oidc_source()
    provider.person("kim")
    provider.claims_changed = {"exp": int(time.time()) - 200}

    back = await sign_in(client, provider, source, "kim")

    assert landed(back)[1].get("signed_in") == "1"


async def test_a_code_the_token_endpoint_refuses_is_said(client, provider, add_oidc_source):
    source = await add_oidc_source()
    provider.person("kim")
    provider.token_error = "invalid_grant"

    failed = await sign_in(client, provider, source, "kim")

    assert landed(failed)[1]["error"] == "failed"


async def test_a_callback_of_another_sign_in_or_none_is_refused(
    client, other_client, provider, add_oidc_source
):
    source = await add_oidc_source()
    provider.person("kim")
    started = await client.get(oidc_path(source, "start"), params={"next": "/search"})
    code = provider.authorize(started.headers["location"], "kim")

    wrong_state = await client.get(
        oidc_path(source, "callback"), params={"code": code, "state": "x"}
    )
    no_cookie = await other_client.get(
        oidc_path(source, "callback"),
        params={"code": code, "state": query_of(started.headers["location"])["state"]},
    )

    assert landed(wrong_state)[1]["error"] == "failed"
    assert landed(no_cookie)[1] == {"error": "expired"}


async def test_an_answer_naming_another_provider_is_refused(client, provider, add_oidc_source):
    source = await add_oidc_source()
    provider.person("kim")

    mixed_up = await sign_in(client, provider, source, "kim", iss="https://elsewhere.example")

    assert landed(mixed_up)[1]["error"] == "failed"


async def test_a_source_that_requires_a_verified_email_refuses_one_that_is_not(
    client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source(require_verified_email=True)
    provider.person("kim", email="kim@corp.example", email_verified=False)
    provider.person("lou", email="lou@corp.example", email_verified=True)

    kim = await sign_in(client, provider, source, "kim")
    lou = await sign_in(client, provider, source, "lou")

    assert landed(kim)[1]["error"] == "refused"
    assert await stored(sessionmaker, "kim") is None
    assert landed(lou)[1].get("signed_in") == "1"


async def test_a_source_that_is_off_or_a_provider_that_is_down_is_said_at_once(
    client, provider, add_oidc_source
):
    off = await add_oidc_source("Old SSO", enabled=False)
    down = await add_oidc_source("Corp SSO")
    provider.down = True

    at_off = await client.get(oidc_path(off, "start"), params={"next": "/search"})
    at_down = await client.get(oidc_path(down, "start"), params={"next": "/search"})

    assert landed(at_off) == ("/login", {"error": "unavailable", "next": "/search"})
    assert landed(at_down) == ("/login", {"error": "unavailable", "next": "/search"})


async def test_a_user_an_administrator_disabled_is_refused(
    admin_client, other_client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source()
    provider.person("kim")
    await sign_in(other_client, provider, source, "kim")
    kim = await stored(sessionmaker, "kim")
    await admin_client.patch(f"/api/v1/users/{kim.id}", json={"status": "disabled"})
    other_client.cookies.clear()

    again = await sign_in(other_client, provider, source, "kim")

    assert landed(again)[1]["error"] == "refused"
    assert (await other_client.get(SESSION)).json()["authenticated"] is False


async def test_where_to_go_next_is_given_only_to_the_sign_in_screen(
    client, provider, add_oidc_source
):
    source = await add_oidc_source()
    provider.person("kim")

    back = await sign_in(client, provider, source, "kim", next="https://evil.example/")

    # The sign-in screen goes there only if it is an address of its own: it is not.
    assert landed(back) == ("/login", {"next": "https://evil.example/", "signed_in": "1"})


async def test_a_user_of_a_provider_has_no_password_here_and_makes_api_tokens(
    client, other_client, provider, add_oidc_source
):
    source = await add_oidc_source()
    provider.person("kim")
    await sign_in(client, provider, source, "kim")
    client.headers["X-CSRF-Token"] = (await client.get(SESSION)).json()["csrf_token"]

    made = await client.post("/api/v1/me/tokens", json={"name": "ci"})
    by_token = await other_client.get(SESSION, headers=bearer(made.json()["token"]))
    by_password = await other_client.get(SESSION, headers=basic("kim", "anything"))

    assert made.status_code == 201
    assert by_token.json()["user"]["username"] == "kim"
    assert by_password.status_code == 401
