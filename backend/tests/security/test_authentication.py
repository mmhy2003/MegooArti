import base64
from datetime import timedelta

import pytest
import structlog
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import select, update

from megooarti.clock import utcnow
from megooarti.security import users
from megooarti.security.authentication import Principal, require, require_interactive
from megooarti.security.models import ApiToken, LoginFailure, UserSession
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in

READ = "/_test/users-read"
WRITE = "/_test/users-write"
MAVEN = "/_test/maven-read"
INTERACTIVE = "/_test/interactive"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    def who(principal: Principal) -> dict:
        return {"user": principal.user.username, "method": principal.method}

    @router.get("/users-read")
    async def users_read(principal: Principal = Depends(require("admin:users:read"))) -> dict:
        return who(principal)

    @router.post("/users-write")
    async def users_write(principal: Principal = Depends(require("admin:users:write"))) -> dict:
        return who(principal)

    @router.get("/maven-read")
    async def maven_read(
        principal: Principal = Depends(require("repository:maven:releases:read")),
    ) -> dict:
        return who(principal)

    @router.post("/interactive")
    async def interactive(principal: Principal = Depends(require_interactive())) -> dict:
        return who(principal)

    app.include_router(router)
    return app


async def enable_anonymous_access(db) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()


async def disable_user(db, username: str) -> None:
    user = await users.get_user_by_username(db, username)
    await users.update_user(db, user, {"status": "disabled"})
    await db.commit()


async def test_no_credentials_is_unauthorized_with_a_challenge(client):
    response = await client.get(READ)

    assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="MegooArti"'


async def test_basic_with_a_password(client, make_user):
    await make_user("root", roles=["admin"])

    response = await client.get(READ, headers=basic("root", PASSWORD))

    assert response.json() == {"user": "root", "method": "password"}


async def test_basic_with_a_token_in_the_password_field(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    await make_user("dana", roles=["admin"])
    token = await make_token(root)

    assert (await client.get(READ, headers=basic("ROOT", token))).json() == {
        "user": "root",
        "method": "token",
    }
    assert (await client.get(READ, headers=basic("dana", token))).status_code == 401


async def test_bearer_token(client, make_user, make_token, db):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    response = await client.get(READ, headers=bearer(token))

    assert response.json() == {"user": "root", "method": "token"}
    assert await db.scalar(select(ApiToken.last_used_at)) is not None


@pytest.mark.parametrize("token", ["mga_" + "x" * 43, "not-a-megooarti-token"])
async def test_an_unknown_bearer_token_is_unauthorized(client, token):
    response = await client.get(READ, headers=bearer(token))
    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_token_scopes_narrow_what_the_owner_may_do(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root, scopes=["admin:users:read"])

    assert (await client.get(READ, headers=bearer(token))).status_code == 200
    refused = await client.post(WRITE, headers=bearer(token))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_token_scopes_never_widen_what_the_owner_may_do(client, make_user, make_token):
    dana = await make_user("dana")
    token = await make_token(dana, scopes=["*"])

    assert (await client.get(READ, headers=bearer(token))).status_code == 403


async def test_an_identified_user_without_the_permission_is_forbidden(client, make_user):
    await make_user("dana")

    response = await client.get(READ, headers=basic("dana", PASSWORD))

    assert (response.status_code, error_code(response)) == (403, "forbidden")


@pytest.mark.parametrize(
    "header",
    [
        "Basic !!!not-base64!!!",
        "Basic " + base64.b64encode(b"no-colon-here").decode(),
        "Basic " + base64.b64encode(b"\xff\xfe:\xff").decode(),
        "Basic",
        "Bearer",
        "Digest username=root",
        "nonsense",
    ],
)
async def test_a_malformed_authorization_header_is_unauthorized(client, header):
    response = await client.get(READ, headers={"Authorization": header})
    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_a_token_stops_working_when_its_owner_is_disabled(client, make_user, make_token, db):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    await disable_user(db, "root")

    assert (await client.get(READ, headers=bearer(token))).status_code == 401
    assert (await client.get(READ, headers=basic("root", PASSWORD))).status_code == 401


async def test_an_expired_token_is_unauthorized(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root, expires_at=utcnow() - timedelta(seconds=1))

    assert (await client.get(READ, headers=bearer(token))).status_code == 401


async def test_a_cookie_request_that_changes_state_needs_the_csrf_token(admin_client):
    refused = await admin_client.post(WRITE, headers={"X-CSRF-Token": "wrong"})
    allowed = await admin_client.post(WRITE)

    assert (refused.status_code, error_code(refused)) == (403, "csrf_failed")
    assert allowed.json() == {"user": "root", "method": "session"}


async def test_header_authenticated_requests_need_no_csrf_token(client, make_user):
    await make_user("root", roles=["admin"])
    assert (await client.post(WRITE, headers=basic("root", PASSWORD))).status_code == 200


async def test_a_pending_password_change_blocks_everything_but_tokens(
    client, other_client, make_user, make_token
):
    root = await make_user("root", roles=["admin"], must_change_password=True)
    token = await make_token(root)
    await sign_in(client, "root")

    by_session = await client.get(READ)
    by_password = await other_client.get(READ, headers=basic("root", PASSWORD))
    by_token = await other_client.get(READ, headers=bearer(token))

    assert (by_session.status_code, error_code(by_session)) == (403, "password_change_required")
    assert error_code(by_password) == "password_change_required"
    assert by_token.status_code == 200


async def test_anonymous_access_is_off_by_default(client):
    assert (await client.get(MAVEN)).status_code == 401


async def test_anonymous_access_acts_as_the_anonymous_user(client, db):
    await enable_anonymous_access(db)

    allowed = await client.get(MAVEN)
    refused = await client.get(READ)

    assert allowed.json() == {"user": "anonymous", "method": "anonymous"}
    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


async def test_interactive_routes_refuse_tokens_and_anonymous_requests(
    admin_client, other_client, make_user, make_token, db
):
    dana = await make_user("dana")
    token = await make_token(dana)
    await enable_anonymous_access(db)

    by_token = await other_client.post(INTERACTIVE, headers=bearer(token))
    by_nobody = await other_client.post(INTERACTIVE)
    by_session = await admin_client.post(INTERACTIVE)
    by_password = await other_client.post(INTERACTIVE, headers=basic("dana", PASSWORD))

    assert (by_token.status_code, error_code(by_token)) == (403, "interactive_auth_required")
    assert by_nobody.status_code == 401
    assert by_session.json()["method"] == "session"
    assert by_password.json()["method"] == "password"


async def test_an_authorization_header_takes_priority_over_the_cookie(admin_client):
    response = await admin_client.get(READ, headers=bearer("mga_" + "x" * 43))
    assert response.status_code == 401


async def test_an_idle_session_expires(admin_client, db):
    await db.execute(update(UserSession).values(last_seen_at=utcnow() - timedelta(hours=2)))
    await db.commit()

    assert (await admin_client.get(READ)).status_code == 401


async def test_a_session_ends_when_its_user_is_disabled(admin_client, db):
    await disable_user(db, "root")
    assert (await admin_client.get(READ)).status_code == 401


async def test_a_valid_token_works_even_when_its_address_is_blocked(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    for number in range(5):
        await client.get(READ, headers=bearer("mga_" + str(number) * 43))

    blocked = await client.get(READ, headers=bearer("mga_" + "x" * 43))
    by_token = await client.get(READ, headers=bearer(token))
    by_basic_token = await client.get(READ, headers=basic("root", token))
    by_password = await client.get(READ, headers=basic("root", PASSWORD))

    assert blocked.status_code == 429
    assert by_token.status_code == 200
    assert by_basic_token.status_code == 200
    assert by_password.status_code == 429  # passwords stay limited by address


async def test_anonymous_requests_never_get_administrative_access(client, db):
    anonymous = await users.get_user_by_username(db, "anonymous")
    await users.set_roles(db, anonymous, ["admin"])
    await enable_anonymous_access(db)

    allowed = await client.get(MAVEN)
    refused = await client.get(READ)

    assert allowed.json() == {"user": "anonymous", "method": "anonymous"}
    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


async def test_a_nul_character_in_basic_credentials_is_unauthorized(client):
    header = "Basic " + base64.b64encode(b"da\x00na:secret").decode()

    response = await client.get(READ, headers={"Authorization": header})

    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_a_token_put_where_the_name_belongs_is_not_logged_or_remembered(
    client, make_user, make_token, db
):
    # `https://<token>@host/` in an index address sends the token as the user name.
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    with structlog.testing.capture_logs() as logs:
        by_basic = await client.get(READ, headers=basic(token, ""))
        by_login = await client.post(
            "/api/v1/auth/login", json={"username": token, "password": "anything at all"}
        )

    assert (by_basic.status_code, by_login.status_code) == (401, 401)
    assert token.lower() not in repr(logs).lower()
    remembered = list(await db.scalars(select(LoginFailure.subject)))
    assert remembered and not [subject for subject in remembered if "mga_" in subject.lower()]


async def test_basic_with_the_token_user_name_is_the_tokens_owner(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    await make_user("dana", roles=["admin"])
    token = await make_token(root)

    # No name at all is as `__token__`, as dotnet-symbol sends a token.
    for name in ("__token__", "__TOKEN__", " __token__ ", ""):
        response = await client.get(READ, headers=basic(name, token))
        assert response.json() == {"user": "root", "method": "token"}


async def test_the_token_user_name_takes_nothing_but_a_token(client, make_user, make_token, db):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    with_password = await client.get(READ, headers=basic("__token__", PASSWORD))
    nameless = await client.get(READ, headers=basic("", PASSWORD))
    with_unknown = await client.get(READ, headers=basic("__token__", "mga_" + "x" * 43))
    await disable_user(db, "root")
    with_a_disabled_owner = await client.get(READ, headers=basic("__token__", token))

    for response in (with_password, nameless, with_unknown, with_a_disabled_owner):
        assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_guesses_under_the_token_user_name_are_limited_by_address(
    client, make_user, make_token
):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    for number in range(5):
        await client.get(READ, headers=basic("__token__", f"guess number {number}"))

    blocked = await client.get(READ, headers=basic("__token__", "one more guess"))
    by_token = await client.get(READ, headers=basic("__token__", token))

    assert blocked.status_code == 429
    assert by_token.status_code == 200  # a valid token is accepted even from a blocked address
