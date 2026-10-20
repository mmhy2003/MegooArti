"""How people sign in besides the sources (spec 4.1): the default role, and MegooArti's own
users' sign-in, which can be turned off for everyone but the built-in `admin` (E1)."""

from megooarti.security import roles, users
from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in

SIGN_IN = "/api/v1/settings/sign-in"
DEFAULT_ROLE = "/api/v1/settings/default-role"
LOCAL = "/api/v1/settings/local-sign-in"
SESSION = "/api/v1/auth/session"
LOGIN = "/api/v1/auth/login"


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def admin_can_sign_in(sessionmaker) -> None:
    """Give the built-in `admin` the password the tests sign in with."""
    async with sessionmaker() as db:
        admin = await users.get_user_by_username(db, "admin")
        await users.set_password(db, admin, PASSWORD, must_change_password=False)
        await db.commit()


async def test_reading_and_changing_need_the_security_permissions(client, make_user, sessionmaker):
    await make_role(sessionmaker, "settings-only", "admin:settings")
    await make_role(sessionmaker, "security-reader", "admin:security:read")
    await make_user("sam", roles=["settings-only"])
    await make_user("rita", roles=["security-reader"])

    nobody = await client.get(SIGN_IN)
    sam = await client.get(SIGN_IN, headers=basic("sam", PASSWORD))
    rita = await client.get(SIGN_IN, headers=basic("rita", PASSWORD))
    rita_writes = await client.put(
        DEFAULT_ROLE, json={"default_role": None}, headers=basic("rita", PASSWORD)
    )

    assert (nobody.status_code, sam.status_code, rita.status_code) == (401, 403, 200)
    assert rita_writes.status_code == 403


async def test_by_default_there_is_no_default_role_and_our_own_users_sign_in(admin_client):
    said = await admin_client.get(SIGN_IN)

    assert said.json() == {
        "default_role": None,
        "local_sign_in": {"enabled": True},
        "trusted_proxies": [],
    }


async def test_the_default_role_is_every_signed_in_users_and_kept_on_none(
    admin_client, other_client, make_user, sessionmaker, make_token
):
    await make_role(sessionmaker, "readers", "repository:*:*:read")
    dana = await make_user("dana")
    token = await make_token(dana)

    set_to = await admin_client.put(DEFAULT_ROLE, json={"default_role": "readers"})
    session = await sign_in(other_client, "dana")
    by_password = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    by_token = await other_client.get(SESSION, headers=bearer(token))
    held = (await admin_client.get(f"/api/v1/users/{dana.id}")).json()["roles"]

    assert set_to.json()["default_role"] == "readers"
    assert "repository:*:*:read" in session["permissions"]
    assert "repository:*:*:read" in by_password.json()["permissions"]
    assert "repository:*:*:read" in by_token.json()["permissions"]
    assert held == []


async def test_the_default_role_is_not_a_visitors(admin_client, other_client, sessionmaker):
    await make_role(sessionmaker, "uploaders", "repository:*:*:add")
    await admin_client.put(DEFAULT_ROLE, json={"default_role": "uploaders"})
    await admin_client.put("/api/v1/settings/anonymous-access", json={"enabled": True})

    visitor = (await other_client.get(SESSION)).json()

    assert visitor["method"] == "anonymous"
    assert "repository:*:*:add" not in visitor["permissions"]


async def test_a_default_role_that_is_not_there_is_refused_and_null_clears_it(
    admin_client, sessionmaker
):
    await make_role(sessionmaker, "readers", "repository:*:*:read")
    await admin_client.put(DEFAULT_ROLE, json={"default_role": "readers"})

    unknown = await admin_client.put(DEFAULT_ROLE, json={"default_role": "nobody-has-it"})
    cleared = await admin_client.put(DEFAULT_ROLE, json={"default_role": None})

    assert (unknown.status_code, error_code(unknown)) == (422, "validation_error")
    assert unknown.json()["error"]["details"][0]["field"] == "default_role"
    assert cleared.json()["default_role"] is None


async def test_deleting_the_default_role_leaves_no_default_role(admin_client, sessionmaker):
    await make_role(sessionmaker, "readers", "repository:*:*:read")
    await admin_client.put(DEFAULT_ROLE, json={"default_role": "readers"})

    deleted = await admin_client.delete("/api/v1/roles/readers")

    assert deleted.status_code == 204
    assert (await admin_client.get(SIGN_IN)).json()["default_role"] is None


async def test_with_our_own_sign_in_off_only_the_built_in_admin_signs_in(
    admin_client, other_client, make_user, make_token, sessionmaker
):
    await admin_can_sign_in(sessionmaker)
    dana = await make_user("dana")
    token = await make_token(dana)

    off = await admin_client.put(LOCAL, json={"enabled": False})
    dana_signs_in = await other_client.post(LOGIN, json={"username": "dana", "password": PASSWORD})
    dana_by_basic = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    dana_by_token = await other_client.get(SESSION, headers=bearer(token))
    admin = await other_client.post(LOGIN, json={"username": "admin", "password": PASSWORD})

    assert off.json()["local_sign_in"] == {"enabled": False}
    assert (dana_signs_in.status_code, error_code(dana_signs_in)) == (401, "unauthorized")
    assert dana_by_basic.status_code == 401
    assert dana_by_token.status_code == 401
    assert admin.status_code == 200


async def test_the_sessions_of_our_own_end_when_our_sign_in_is_turned_off_for_good(
    admin_client, other_client, make_user, sessionmaker
):
    await admin_can_sign_in(sessionmaker)
    await sign_in(admin_client, "admin")  # `root` is one of our own too
    await make_user("dana")
    await sign_in(other_client, "dana")

    await admin_client.put(LOCAL, json={"enabled": False})
    after = (await other_client.get(SESSION)).json()
    await admin_client.put(LOCAL, json={"enabled": True})
    back = (await other_client.get(SESSION)).json()

    assert after["authenticated"] is False
    # Signed out, as a disabled user is: turning it on again brings no session back.
    assert back["authenticated"] is False


async def test_our_own_sign_in_stays_on_while_the_built_in_admin_has_no_full_access(
    admin_client, sessionmaker
):
    async with sessionmaker() as db:
        admin = await users.get_user_by_username(db, "admin")
        await users.set_roles(db, admin, [])
        await db.commit()

    refused = await admin_client.put(LOCAL, json={"enabled": False})

    assert (refused.status_code, error_code(refused)) == (409, "last_administrator")
    assert (await admin_client.get(SIGN_IN)).json()["local_sign_in"] == {"enabled": True}
