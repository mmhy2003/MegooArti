"""A format that signs its client in: the one request taken without credentials."""

import json

import pytest
from sqlalchemy import select
from starlette.responses import JSONResponse, Response

from megooarti.repositories import formats
from megooarti.repositories.formats import Format
from megooarti.security.models import ApiToken
from tests.accounts import PASSWORD, basic, bearer, error_code

LOGIN = "/repository/files/-/login"
FILE = "/repository/files/a.txt"


class SigningIn(Format):
    """Raw files, plus a sign-in and a sign-out address."""

    name = "raw"

    def takes_body_credentials(self, method, path):
        return method == "PUT" and path == "-/login"

    async def handle_hosted(self, context, request, path):
        if path == "-/login":
            sent = json.loads(await context.receive(request.stream(), limit=1000))
            token = await context.issue_token(
                request, sent["name"], sent["password"], label="test login"
            )
            return JSONResponse({"token": token, "principal": context.principal is not None})
        if path == "-/logout":
            await context.revoke_token(request.headers["X-Token"])
            return Response(status_code=204)
        return await super().handle_hosted(context, request, path)


@pytest.fixture
async def dana(files, make_user, monkeypatch):
    monkeypatch.setitem(formats._registry, "raw", SigningIn())
    return await make_user("dana", roles=["admin"])


async def sign_in(client, name: str = "dana", password: str = PASSWORD):
    return await client.put(LOGIN, json={"name": name, "password": password})


async def test_the_named_request_is_taken_without_credentials(client, dana):
    response = await sign_in(client)

    assert response.status_code == 200
    assert response.json()["principal"] is False
    token = response.json()["token"]
    assert (await client.put(FILE, content=b"hello", headers=bearer(token))).status_code == 201
    assert (await client.get(FILE, headers=bearer(token))).content == b"hello"


async def test_every_other_write_still_needs_credentials(client, dana):
    attempts = [
        await client.put(FILE, content=b"hello"),
        await client.post(LOGIN, json={"name": "dana", "password": PASSWORD}),
        await client.delete(LOGIN),
        await client.put("/repository/files/-/logout"),
    ]

    assert [response.status_code for response in attempts] == [401, 401, 401, 401]


async def test_a_format_that_names_no_request_takes_none(client, files, make_user):
    await make_user("dana", roles=["admin"])

    response = await sign_in(client)

    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_the_token_is_a_personal_api_token_named_for_the_client(client, dana, db):
    await sign_in(client)

    token = await db.scalar(select(ApiToken))

    assert token.user_id == dana.id
    assert token.name.startswith("test login 20")
    assert (token.expires_at, token.scopes) == (None, None)


async def test_wrong_credentials_get_no_token(client, dana, db):
    wrong = await sign_in(client, password="not the password")
    unknown = await sign_in(client, name="nobody")

    assert (wrong.status_code, error_code(wrong)) == (401, "unauthorized")
    assert unknown.status_code == 401
    assert await db.scalar(select(ApiToken)) is None


async def test_failed_attempts_are_limited_as_for_any_sign_in(client, dana, app):
    allowed = app.state.settings.login_max_failures

    statuses = [(await sign_in(client, password="guess")).status_code for _ in range(allowed + 1)]
    with_the_right_password = await sign_in(client)

    assert statuses == [401] * allowed + [429]
    assert (with_the_right_password.status_code, error_code(with_the_right_password)) == (
        429,
        "too_many_attempts",
    )


async def test_an_api_token_given_as_the_secret_is_returned_as_it_is(client, dana, make_token, db):
    token = await make_token(dana)

    response = await sign_in(client, password=token)
    for_someone_else = await sign_in(client, name="root", password=token)

    assert response.json()["token"] == token
    assert for_someone_else.status_code == 401
    assert len(list(await db.scalars(select(ApiToken.id)))) == 1


async def test_a_pending_password_change_blocks_the_token(
    client, files, make_user, monkeypatch, db
):
    monkeypatch.setitem(formats._registry, "raw", SigningIn())
    await make_user("newcomer", roles=["admin"], must_change_password=True)

    response = await sign_in(client, name="newcomer")

    assert (response.status_code, error_code(response)) == (403, "password_change_required")
    assert await db.scalar(select(ApiToken)) is None


async def test_a_caller_revokes_only_their_own_token(client, dana, make_user):
    await make_user("eli", roles=["admin"])
    danas = (await sign_in(client)).json()["token"]
    elis = (await sign_in(client, name="eli")).json()["token"]
    logout = "/repository/files/-/logout"

    not_theirs = await client.put(logout, headers={**bearer(elis), "X-Token": danas})
    unknown = await client.put(logout, headers={**bearer(elis), "X-Token": "mga_nothing"})
    own = await client.put(logout, headers={**bearer(danas), "X-Token": danas})

    assert (not_theirs.status_code, error_code(not_theirs)) == (404, "not_found")
    assert unknown.status_code == 404
    assert own.status_code == 204
    assert (await client.get(FILE, headers=bearer(danas))).status_code == 401
    assert (await client.get(FILE, headers=bearer(elis))).status_code == 404


async def test_basic_credentials_are_checked_the_same_way_as_before(client, dana, make_token):
    token = await make_token(dana)

    with_password = await client.get(FILE, headers=basic("dana", PASSWORD))
    with_token = await client.get(FILE, headers=basic("dana", token))
    with_another_name = await client.get(FILE, headers=basic("root", token))
    wrong = await client.get(FILE, headers=basic("dana", "wrong"))

    assert (with_password.status_code, with_token.status_code) == (404, 404)
    assert (with_another_name.status_code, wrong.status_code) == (401, 401)


@pytest.mark.parametrize(
    "stale", [bearer("mga_revoked-long-ago"), basic("dana", "an old password"), bearer("junk")]
)
async def test_a_stale_credential_in_a_header_does_not_stop_a_sign_in(client, dana, stale):
    # A client whose saved token was revoked sends it with every request, this one too.
    response = await client.put(LOGIN, json={"name": "dana", "password": PASSWORD}, headers=stale)

    assert response.status_code == 200, response.text
    assert response.json()["principal"] is False


async def test_a_stale_credential_still_stops_everything_else(client, dana):
    stale = bearer("mga_revoked-long-ago")

    attempts = [
        await client.put(FILE, content=b"hello", headers=stale),
        await client.get(FILE, headers=stale),
        await client.put("/repository/files/-/logout", headers=stale),
        await client.post(LOGIN, json={"name": "dana", "password": PASSWORD}, headers=stale),
        await client.put("/repository/nowhere/-/login", json={}, headers=stale),
    ]

    assert [response.status_code for response in attempts] == [401] * 5
    assert all(
        response.headers["WWW-Authenticate"] == 'Basic realm="MegooArti"' for response in attempts
    )
