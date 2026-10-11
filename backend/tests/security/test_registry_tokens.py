import uuid
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti import secrets_box
from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.security import registry_tokens, roles, users
from megooarti.security.authentication import (
    Credentials,
    Principal,
    authorize,
    issue_registry_token,
    registry_credentials,
)
from megooarti.security.models import ApiToken, LoginFailure
from megooarti.security.registry_tokens import Claims
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code

READ = "/_test/maven-read"
ADMIN = "/_test/users-read"
SIGN_IN = "/_test/registry-token"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    # Routes as the registry API has them: they take a registry token.
    async def who(credentials: Credentials, permission: str) -> dict:
        principal: Principal = authorize(await credentials.principal(), permission)
        return {"user": principal.user.username, "method": principal.method}

    @router.get("/maven-read")
    async def maven_read(credentials: Credentials = Depends(registry_credentials)) -> dict:
        return await who(credentials, "repository:maven:releases:read")

    @router.get("/users-read")
    async def users_read(credentials: Credentials = Depends(registry_credentials)) -> dict:
        return await who(credentials, "admin:users:read")

    @router.get("/registry-token")
    async def registry_token(
        request: Request,
        credentials: Credentials = Depends(registry_credentials),
        db: AsyncSession = Depends(get_session),
    ) -> dict:
        signed_in = "Authorization" in request.headers
        principal = await credentials.principal() if signed_in else None
        return {"token": await issue_registry_token(request, db, principal)}

    app.include_router(router)
    return app


async def sign_in(client, headers: dict | None = None) -> str:
    response = await client.get(SIGN_IN, headers=headers or {})
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def let_anyone_read(db, *permissions: str) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    anonymous = await users.get_user_by_username(db, "anonymous")
    if permissions:
        await roles.create_role(db, "public", "", list(permissions), [])
        await users.set_roles(db, anonymous, ["public"])
    await db.commit()


def test_a_token_states_who_signed_in(settings):
    now = utcnow()
    claims = Claims(uuid.uuid4(), "token", uuid.uuid4())

    value = registry_tokens.issue(settings, claims, now)

    assert value.startswith("mgr_")
    assert registry_tokens.read(settings, value, now) == claims
    assert registry_tokens.read(settings, value, now + timedelta(seconds=299)) == claims
    nobody = registry_tokens.issue(settings, Claims(None, "anonymous"), now)
    assert registry_tokens.read(settings, nobody, now) == Claims(None, "anonymous")


def test_a_token_is_read_only_within_its_lifetime(settings):
    now = utcnow()
    value = registry_tokens.issue(settings, Claims(uuid.uuid4(), "password"), now)

    assert registry_tokens.read(settings, value, now + timedelta(seconds=301)) is None
    assert registry_tokens.read(settings, value, now - timedelta(hours=1)) is None  # not yet made


def test_what_is_not_a_registry_token_is_not_read(settings):
    now = utcnow()
    value = registry_tokens.issue(settings, Claims(uuid.uuid4(), "password"), now)
    altered = value[:-6] + ("AAAAAA" if not value.endswith("AAAAAA") else "BBBBBB")
    # Something else sealed with the same key, such as a remote's password.
    other = "mgr_" + secrets_box.seal_at(settings, "s3cret", now)
    wrong_purpose = "mgr_" + secrets_box.seal_at(
        settings, '{"for": "something", "user": null, "method": "anonymous", "token": null}', now
    )
    odd = "mgr_" + secrets_box.seal_at(
        settings, '{"for": "registry", "user": 7, "method": "password", "token": null}', now
    )

    for candidate in (altered, other, wrong_purpose, odd, "mgr_", "mgr_not-sealed", value[4:], ""):
        assert registry_tokens.read(settings, candidate, now) is None, candidate


async def test_signing_in_with_a_password_gives_a_token_that_works(client, make_user):
    await make_user("root", roles=["admin"])

    token = await sign_in(client, basic("root", PASSWORD))
    response = await client.get(ADMIN, headers=bearer(token))

    assert response.json() == {"user": "root", "method": "password"}


async def test_signing_in_with_an_api_token_keeps_its_limits(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    narrow = await make_token(root, scopes=["repository:maven"])

    token = await sign_in(client, basic("__token__", narrow))
    allowed = await client.get(READ, headers=bearer(token))
    beyond = await client.get(ADMIN, headers=bearer(token))

    assert allowed.json() == {"user": "root", "method": "token"}
    assert (beyond.status_code, error_code(beyond)) == (403, "forbidden")


async def test_wrong_credentials_get_no_token_and_are_counted(client, make_user, db):
    await make_user("root", roles=["admin"])

    response = await client.get(SIGN_IN, headers=basic("root", "not the password"))

    assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'
    assert await db.scalar(select(LoginFailure.count).where(LoginFailure.subject == "user:root"))


async def test_a_token_stops_working_when_its_user_is_disabled(client, make_user, db):
    await make_user("root", roles=["admin"])
    token = await sign_in(client, basic("root", PASSWORD))
    user = await users.get_user_by_username(db, "root")
    await users.update_user(db, user, {"status": "disabled"})
    await db.commit()

    response = await client.get(ADMIN, headers=bearer(token))

    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_a_token_stops_working_when_the_api_token_behind_it_is_revoked(
    client, make_user, make_token, db
):
    root = await make_user("root", roles=["admin"])
    token = await sign_in(client, basic("root", await make_token(root)))
    before = await client.get(ADMIN, headers=bearer(token))
    await db.execute(delete(ApiToken))
    await db.commit()

    after = await client.get(ADMIN, headers=bearer(token))

    assert (before.status_code, after.status_code) == (200, 401)


async def test_a_token_follows_its_users_roles_as_they_are_now(client, make_user, db):
    await make_user("dana")
    token = await sign_in(client, basic("dana", PASSWORD))
    before = await client.get(ADMIN, headers=bearer(token))
    user = await users.get_user_by_username(db, "dana")
    await users.set_roles(db, user, ["admin"])
    await db.commit()

    after = await client.get(ADMIN, headers=bearer(token))

    assert (before.status_code, after.status_code) == (403, 200)


async def test_an_expired_or_altered_token_is_refused_without_being_counted(
    client, make_user, settings, db
):
    root = await make_user("root", roles=["admin"])
    old = registry_tokens.issue(
        settings, Claims(root.id, "password"), utcnow() - timedelta(seconds=301)
    )
    good = await sign_in(client, basic("root", PASSWORD))

    for value in (old, good[:-4] + "AAAA", "mgr_anything"):
        response = await client.get(ADMIN, headers=bearer(value))
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert list(await db.scalars(select(LoginFailure.subject))) == []


async def test_a_token_that_states_something_impossible_is_refused(client, make_user, settings):
    root = await make_user("root", roles=["admin"])
    now = utcnow()
    impossible = [
        Claims(uuid.uuid4(), "password"),  # nobody has this ID
        Claims(root.id, "token"),  # by a token, but which?
        Claims(root.id, "token", uuid.uuid4()),  # a token that does not exist
        Claims(root.id, "anonymous"),
    ]

    for claims in impossible:
        value = registry_tokens.issue(settings, claims, now)
        response = await client.get(ADMIN, headers=bearer(value))
        assert response.status_code == 401, claims


async def test_without_credentials_there_is_no_token_unless_anyone_may_read(client, db):
    refused = await client.get(SIGN_IN)
    await let_anyone_read(db, "repository:maven:releases:read")

    token = await sign_in(client)
    reading = await client.get(READ, headers=bearer(token))
    administering = await client.get(ADMIN, headers=bearer(token))

    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")
    assert reading.json() == {"user": "anonymous", "method": "anonymous"}
    assert administering.status_code == 401  # nobody administers anonymously


async def test_a_token_for_nobody_stops_working_when_anonymous_access_is_switched_off(client, db):
    await let_anyone_read(db, "repository:maven:releases:read")
    token = await sign_in(client)
    await set_setting(db, "anonymous_access", {"enabled": False})
    await db.commit()

    response = await client.get(READ, headers=bearer(token))

    assert response.status_code == 401


async def test_a_registry_token_is_taken_by_the_registry_api_and_nothing_else(
    client, make_user, db
):
    # It was obtained with a password, and lasts five minutes. If the rest of the API
    # took it, whoever held one could make an API token that lasts for ever.
    await make_user("root", roles=["admin"])
    token = await sign_in(client, basic("root", PASSWORD))
    with_token = bearer(token)

    attempts = [
        await client.post("/api/v1/me/tokens", json={"name": "kept"}, headers=with_token),
        await client.get("/api/v1/me/tokens", headers=with_token),
        await client.get("/api/v1/users", headers=with_token),
        await client.get("/api/v1/auth/session", headers=with_token),
        await client.get("/repository/files/a.txt", headers=with_token),
        await client.put("/repository/files/a.txt", content=b"x", headers=with_token),
    ]

    for response in attempts:
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert await db.scalar(select(ApiToken.id)) is None
    assert list(await db.scalars(select(LoginFailure))) == []  # nor is it a failed sign-in
    assert (await client.get(ADMIN, headers=with_token)).json()["user"] == "root"


async def test_a_registry_token_cannot_be_exchanged_for_another(client, make_user, db):
    # Whoever held one could otherwise keep it alive for ever, past a change of password.
    await make_user("root", roles=["admin"])
    held = await sign_in(client, basic("root", PASSWORD))
    await let_anyone_read(db)
    nobodys = await sign_in(client)

    for value in (held, nobodys):
        response = await client.get(SIGN_IN, headers=bearer(value))
        assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert (await client.get(ADMIN, headers=bearer(held))).json()["user"] == "root"
