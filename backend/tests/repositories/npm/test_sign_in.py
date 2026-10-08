from sqlalchemy import select

from megooarti.security.models import ApiToken
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code
from tests.repositories.npm.conftest import URL

LOGIN = f"{URL}/-/user/org.couchdb.user:dana"
WHOAMI = f"{URL}/-/whoami"


def credentials(name: str = "dana", password: str = PASSWORD) -> dict:
    """What `npm login` sends."""
    return {"_id": f"org.couchdb.user:{name}", "name": name, "password": password, "type": "user"}


async def sign_in(client, name: str = "dana", password: str = PASSWORD) -> str:
    response = await client.put(
        f"{URL}/-/user/org.couchdb.user:{name}", json=credentials(name, password)
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


async def test_signing_in_gives_a_token_that_works(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    response = await client.put(LOGIN, json=credentials())

    body = response.json()
    assert response.status_code == 201
    assert (body["ok"], body["id"]) == (True, "org.couchdb.user:dana")
    assert body["token"].startswith("mga_")
    who = await client.get(WHOAMI, headers=bearer(body["token"]))
    assert (who.status_code, who.json()) == (200, {"username": "dana"})


async def test_the_token_is_one_of_the_users_tokens(client, registry, make_user, db):
    await make_user("dana", roles=["admin"])

    await sign_in(client)

    names = list(await db.scalars(select(ApiToken.name)))
    assert len(names) == 1
    assert names[0].startswith("npm login ")


async def test_an_api_token_can_be_given_as_the_password(
    client, registry, make_user, make_token, db
):
    dana = await make_user("dana", roles=["admin"])
    token = await make_token(dana)

    returned = await sign_in(client, password=token)

    assert returned == token
    assert len(list(await db.scalars(select(ApiToken.id)))) == 1  # no second token was made


async def test_wrong_credentials_are_refused(client, registry, make_user, db):
    await make_user("dana", roles=["admin"])

    wrong = await client.put(LOGIN, json=credentials(password="not the password"))
    unknown = await client.put(f"{URL}/-/user/org.couchdb.user:nobody", json=credentials("nobody"))

    assert (wrong.status_code, error_code(wrong)) == (401, "unauthorized")
    assert (unknown.status_code, error_code(unknown)) == (401, "unauthorized")
    assert list(await db.scalars(select(ApiToken.id))) == []


async def test_repeated_failures_are_throttled_like_any_sign_in(client, registry, make_user, app):
    await make_user("dana", roles=["admin"])
    allowed = app.state.settings.login_max_failures

    statuses = []
    for _ in range(allowed + 1):
        response = await client.put(LOGIN, json=credentials(password="guess"))
        statuses.append(response.status_code)
    even_the_right_one = await client.put(LOGIN, json=credentials())

    assert statuses == [401] * allowed + [429]
    assert (even_the_right_one.status_code, error_code(even_the_right_one)) == (
        429,
        "too_many_attempts",
    )


async def test_a_user_who_must_change_their_password_gets_no_token(client, registry, make_user, db):
    await make_user("dana", roles=["admin"], must_change_password=True)

    response = await client.put(LOGIN, json=credentials())

    assert (response.status_code, error_code(response)) == (403, "password_change_required")
    assert list(await db.scalars(select(ApiToken.id))) == []


async def test_a_sign_in_must_be_what_npm_sends(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    another_name = await client.put(LOGIN, json=credentials("root"))
    no_password = await client.put(LOGIN, json={"name": "dana"})
    not_json = await client.put(LOGIN, content=b"name=dana&password=x")
    not_an_object = await client.put(LOGIN, json=["dana", PASSWORD])
    too_large = await client.put(LOGIN, json={**credentials(), "padding": "x" * 20_000})

    for response in (another_name, no_password, not_json, not_an_object):
        assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert (too_large.status_code, error_code(too_large)) == (413, "payload_too_large")


async def test_signing_in_is_the_only_request_taken_without_credentials(
    client, registry, make_user
):
    await make_user("dana", roles=["admin"])
    token = await sign_in(client)

    attempts = [
        await client.put(f"{URL}/left-pad", json={"name": "left-pad"}),
        await client.put(f"{URL}/-/package/left-pad/dist-tags/beta", json="1.0.0"),
        await client.delete(f"{URL}/-/user/token/{token}"),
        await client.delete(LOGIN),
        await client.post(LOGIN, json=credentials()),
        await client.post(f"{URL}/-/v1/login", json={}),
        await client.get(LOGIN),
        await client.get(WHOAMI),
    ]

    assert [response.status_code for response in attempts] == [401] * len(attempts)
    assert (await client.get(WHOAMI, headers=bearer(token))).status_code == 200


async def test_a_sign_in_from_another_site_is_refused(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    response = await client.put(LOGIN, json=credentials(), headers={"Sec-Fetch-Site": "cross-site"})

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")


async def test_signing_out_revokes_the_token(client, registry, make_user):
    await make_user("dana", roles=["admin"])
    token = await sign_in(client)

    response = await client.delete(f"{URL}/-/user/token/{token}", headers=bearer(token))

    assert (response.status_code, response.json()) == (200, {"ok": True})
    assert (await client.get(WHOAMI, headers=bearer(token))).status_code == 401


async def test_nobody_can_revoke_another_users_token(client, registry, make_user):
    await make_user("dana", roles=["admin"])
    await make_user("eli", roles=["admin"])
    danas = await sign_in(client, "dana")
    elis = await sign_in(client, "eli")

    response = await client.delete(f"{URL}/-/user/token/{danas}", headers=bearer(elis))
    unknown = await client.delete(f"{URL}/-/user/token/mga_nothing", headers=bearer(elis))

    assert (response.status_code, error_code(response)) == (404, "not_found")
    assert unknown.status_code == 404
    assert (await client.get(WHOAMI, headers=bearer(danas))).status_code == 200


async def test_whoami_needs_a_person_and_ping_does_not(client, registry, root, db):
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    anonymous_who = await client.get(WHOAMI)
    by_password = await client.get(WHOAMI, headers=root)
    ping = await client.get(f"{URL}/-/ping", headers=root)
    written = await client.put(f"{URL}/-/ping", headers=root)

    assert anonymous_who.status_code == 401
    assert by_password.json() == {"username": "root"}
    assert (ping.status_code, ping.json()) == (200, {})
    assert ping.headers["X-Content-Type-Options"] == "nosniff"
    assert (written.status_code, error_code(written)) == (405, "method_not_allowed")


async def test_web_login_is_absent_so_that_npm_falls_back(client, registry, root):
    response = await client.post(f"{URL}/-/v1/login", json={}, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_basic_credentials_still_work_everywhere(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    assert (await client.get(WHOAMI, headers=basic("dana", PASSWORD))).json() == {
        "username": "dana"
    }


async def test_a_revoked_token_in_npmrc_does_not_stop_npm_login(client, registry, make_user):
    await make_user("dana", roles=["admin"])
    old = await sign_in(client)
    await client.delete(f"{URL}/-/user/token/{old}", headers=bearer(old))

    # npm sends the token it has saved with every request, including the next sign-in.
    response = await client.put(LOGIN, json=credentials(), headers=bearer(old))

    assert response.status_code == 201, response.text
    assert response.json()["token"] != old


async def test_a_secret_that_cannot_be_text_is_refused_not_an_error(client, registry, make_user):
    await make_user("dana", roles=["admin"])
    half_a_pair = b'{"name": "dana", "password": "\\ud800"}'

    response = await client.put(LOGIN, content=half_a_pair)

    assert (response.status_code, error_code(response)) == (400, "invalid_package")
