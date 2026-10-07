import pytest
from fastapi import APIRouter, Depends, FastAPI

from megooarti.errors import ApiError
from megooarti.security import roles, users
from megooarti.security.authentication import Principal, authorize, client_principal, require
from megooarti.security.models import User
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code

MAVEN = "/_test/maven-read"
USERS = "/_test/users-read"
CLIENT = "/_test/client/maven-read"
MAVEN_READ = "repository:maven:releases:read"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    @router.get("/maven-read")
    async def maven_read(principal: Principal = Depends(require(MAVEN_READ))) -> dict:
        return {"user": principal.user.username}

    @router.get("/users-read")
    async def users_read(principal: Principal = Depends(require("admin:users:read"))) -> dict:
        return {"user": principal.user.username}

    @router.get("/client/maven-read")
    async def client_read(principal: Principal | None = Depends(client_principal)) -> dict:
        return {"user": authorize(principal, MAVEN_READ, scheme="Basic").user.username}

    app.include_router(router)
    return app


async def enable_anonymous_access(db) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()


def person(**fields) -> Principal:
    user = User(username="pat", display_name="Pat", must_change_password=False)
    fields.setdefault("method", "password")
    fields.setdefault("patterns", frozenset())
    return Principal(user=user, **fields)


async def test_a_signed_in_user_may_do_what_anyone_may_do(client, make_user, db):
    await make_user("dana")
    headers = basic("dana", PASSWORD)
    assert (await client.get(MAVEN, headers=headers)).status_code == 403

    await enable_anonymous_access(db)

    assert (await client.get(MAVEN, headers=headers)).json() == {"user": "dana"}


async def test_token_scopes_do_not_narrow_public_access(client, make_user, make_token, db):
    dana = await make_user("dana")
    token = await make_token(dana, scopes=["admin:users:read"])
    await enable_anonymous_access(db)

    assert (await client.get(MAVEN, headers=bearer(token))).status_code == 200


async def test_public_access_never_includes_administration(client, make_user, db):
    await roles.create_role(db, "generous", "", ["admin:users:read", "repository"], [])
    anonymous = await users.get_user_by_username(db, "anonymous")
    await users.set_roles(db, anonymous, ["generous"])
    await enable_anonymous_access(db)
    await make_user("dana")

    by_dana = await client.get(USERS, headers=basic("dana", PASSWORD))
    by_nobody = await client.get(USERS)

    assert (by_dana.status_code, error_code(by_dana)) == (403, "forbidden")
    assert by_nobody.status_code == 401


def test_allows_applies_patterns_scopes_and_public_access():
    owner = person(patterns=frozenset({"*"}))
    scoped = person(patterns=frozenset({"*"}), scopes=frozenset({"admin:users:read"}))
    reader = person(public=frozenset({"repository:*:*:read"}))

    assert owner.allows("admin:users:write")
    assert scoped.allows("admin:users:read")
    assert not scoped.allows("admin:users:write")
    assert reader.allows(MAVEN_READ)
    assert not reader.allows("repository:maven:releases:add")
    assert not reader.allows("admin:users:read")


@pytest.mark.parametrize(
    "permission",
    ["repository:maven:a*b:read", "repository:maven::read", "repository:maven:*:read", ""],
)
def test_a_malformed_permission_is_refused_even_with_full_access(permission):
    assert not person(patterns=frozenset({"*"}), public=frozenset({"*"})).allows(permission)


def test_authorize_returns_the_principal_when_allowed():
    owner = person(patterns=frozenset({"*"}))
    assert authorize(owner, "admin:users:read") is owner


@pytest.mark.parametrize(
    ("principal", "status", "code"),
    [
        (None, 401, "unauthorized"),
        (person(), 403, "forbidden"),
        (person(method="anonymous"), 401, "unauthorized"),
    ],
)
def test_authorize_refusals(principal, status, code):
    with pytest.raises(ApiError) as caught:
        authorize(principal, "admin:users:read")
    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_authorize_refuses_everything_while_a_password_change_is_pending():
    pending = person(patterns=frozenset({"*"}))
    pending.user.must_change_password = True

    with pytest.raises(ApiError) as caught:
        authorize(pending, "admin:users:read")

    assert caught.value.code == "password_change_required"


@pytest.mark.parametrize("headers", [{}, basic("nobody", "wrong password")])
async def test_client_routes_challenge_with_basic(client, headers):
    response = await client.get(CLIENT, headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"'


async def test_api_routes_still_challenge_with_bearer(client):
    response = await client.get(USERS, headers=basic("nobody", "wrong password"))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="MegooArti"'
