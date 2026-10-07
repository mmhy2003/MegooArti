import pytest
from sqlalchemy import delete

from megooarti.main import create_app
from megooarti.security import users
from megooarti.security.models import UserSession
from tests.accounts import PASSWORD, error_code, sign_in
from tests.clients import client_for

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
SESSION = "/api/v1/auth/session"
SIGNED_OUT = {
    "authenticated": False,
    "method": None,
    "user": None,
    "permissions": [],
    "must_change_password": False,
    "csrf_token": None,
}


async def attempt(client, username, password):
    return await client.post(LOGIN, json={"username": username, "password": password})


async def test_sign_in_describes_the_session_and_sets_a_protected_cookie(client, make_user):
    await make_user("dana", roles=["admin"])

    response = await attempt(client, "dana", PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert (body["authenticated"], body["method"]) == (True, "session")
    assert (body["user"]["username"], body["user"]["display_name"]) == ("dana", "Dana")
    assert body["permissions"] == ["*"]
    assert body["must_change_password"] is False
    assert len(body["csrf_token"]) == 43
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("megooarti_session=")
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute in cookie
    assert PASSWORD not in response.text


async def test_cookie_is_not_marked_secure_for_plain_http(settings, sessionmaker, make_user):
    await make_user("dana")
    app = create_app(settings.model_copy(update={"session_cookie_secure": False}))
    app.state.sessionmaker = sessionmaker

    async with client_for(app) as http:
        response = await attempt(http, "dana", PASSWORD)

    assert "Secure" not in response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("username", "password"),
    [("dana", "the wrong password"), ("nobody", PASSWORD), ("dan", PASSWORD), ("anonymous", "x")],
)
async def test_every_failure_looks_the_same(client, make_user, db, username, password):
    await make_user("dana")
    await make_user("dan")
    dan = await users.get_user_by_username(db, "dan")
    await users.update_user(db, dan, {"status": "disabled"})
    await db.commit()

    response = await attempt(client, username, password)

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid credentials."
    assert error_code(response) == "unauthorized"
    assert "set-cookie" not in response.headers


async def test_username_case_and_surrounding_spaces_do_not_matter(client, make_user):
    await make_user("dana")
    assert (await attempt(client, "  DaNa ", PASSWORD)).status_code == 200


async def test_passwords_may_contain_any_characters(client, make_user):
    await make_user("uma", password="pässwörd-ünïcode-✓")
    assert (await attempt(client, "uma", "pässwörd-ünïcode-✓")).status_code == 200


async def test_sign_in_records_the_time(client, make_user, db):
    await make_user("dana")
    await sign_in(client, "dana")
    assert (await users.get_user_by_username(db, "dana")).last_login_at is not None


async def test_session_endpoint_without_credentials_reports_signed_out(client):
    response = await client.get(SESSION)
    assert response.status_code == 200
    assert response.json() == SIGNED_OUT


async def test_session_endpoint_after_sign_in(client, make_user):
    await make_user("dana")
    signed_in = await sign_in(client, "dana")

    body = (await client.get(SESSION)).json()

    assert body == signed_in
    assert body["permissions"] == []


async def test_sign_out_ends_the_session(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await client.post(LOGOUT)

    assert response.status_code == 204
    assert 'megooarti_session=""' in response.headers["set-cookie"]
    assert (await client.get(SESSION)).json() == SIGNED_OUT


async def test_sign_out_needs_the_csrf_token(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await client.post(LOGOUT, headers={"X-CSRF-Token": "wrong"})

    assert (response.status_code, error_code(response)) == (403, "csrf_failed")
    assert (await client.get(SESSION)).json()["authenticated"] is True


async def test_sign_out_without_a_session_is_harmless(client):
    assert (await client.post(LOGOUT)).status_code == 204


async def test_a_cookie_for_a_session_that_no_longer_exists_means_signed_out(client, make_user, db):
    await make_user("dana")
    await sign_in(client, "dana")
    await db.execute(delete(UserSession))
    await db.commit()

    response = await client.get(SESSION)

    assert response.status_code == 200
    assert response.json() == SIGNED_OUT


async def test_repeated_failures_are_refused_even_with_the_right_password(client, make_user):
    await make_user("dana")
    for _ in range(5):
        assert (await attempt(client, "dana", "the wrong password")).status_code == 401

    response = await attempt(client, "dana", PASSWORD)

    assert (response.status_code, error_code(response)) == (429, "too_many_attempts")
    assert 0 < int(response.headers["Retry-After"]) <= 900


async def test_a_success_clears_the_failure_count(client, make_user):
    await make_user("dana")
    for _ in range(2):
        for _ in range(4):
            await attempt(client, "dana", "the wrong password")
        assert (await attempt(client, "dana", PASSWORD)).status_code == 200


async def test_failures_for_many_usernames_from_one_address_are_refused(client, make_user):
    await make_user("dana")
    for number in range(5):
        await attempt(client, f"guess{number}", "the wrong password")

    assert (await attempt(client, "dana", PASSWORD)).status_code == 429


async def test_a_nul_character_in_the_username_is_an_ordinary_failure(client, make_user):
    await make_user("dana")

    response = await attempt(client, "da\x00na", PASSWORD)

    assert (response.status_code, error_code(response)) == (401, "unauthorized")
