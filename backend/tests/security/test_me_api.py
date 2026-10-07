import pytest

from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in

ME = "/api/v1/me"
SESSION = "/api/v1/auth/session"
NEW_PASSWORD = "an entirely new password"


async def change(client, current=PASSWORD, new=NEW_PASSWORD, **kwargs):
    body = {"current_password": current, "new_password": new}
    return await client.put(f"{ME}/password", json=body, **kwargs)


async def test_changing_the_password_keeps_this_session_and_ends_the_others(
    client, other_client, make_user
):
    await make_user("dana")
    await sign_in(client, "dana")
    await sign_in(other_client, "dana")

    response = await change(client)

    assert response.status_code == 204
    assert (await client.get(SESSION)).json()["authenticated"] is True
    assert (await other_client.get(SESSION)).json()["authenticated"] is False
    old = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    new = await other_client.get(SESSION, headers=basic("dana", NEW_PASSWORD))
    assert old.status_code == 401
    assert new.json()["method"] == "password"


async def test_the_current_password_must_be_right(client, other_client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await change(client, current="not my password")

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "body.current_password"
    still_works = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    assert still_works.status_code == 200


async def test_the_new_password_must_be_acceptable(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await change(client, new="short")

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "password"


async def test_a_forced_change_can_be_completed(client, make_user):
    await make_user("dana", must_change_password=True)
    assert (await sign_in(client, "dana"))["must_change_password"] is True

    assert (await change(client)).status_code == 204

    assert (await client.get(SESSION)).json()["must_change_password"] is False
    assert (await client.get(f"{ME}/tokens")).status_code == 200


async def test_a_token_cannot_change_the_password(client, make_user, make_token):
    dana = await make_user("dana")
    token = await make_token(dana)

    response = await change(client, headers=bearer(token))

    assert (response.status_code, error_code(response)) == (403, "interactive_auth_required")


async def test_changing_the_password_needs_someone_signed_in(client):
    assert (await change(client)).status_code == 401


async def test_create_list_use_and_revoke_a_token(client, other_client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    created = await client.post(f"{ME}/tokens", json={"name": "ci"})

    assert created.status_code == 201
    body = created.json()
    token = body["token"]
    assert token.startswith("mga_")
    assert (body["name"], body["display_prefix"], body["scopes"]) == ("ci", token[:8], None)

    listed = (await client.get(f"{ME}/tokens")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == body["id"]
    assert "token" not in listed["items"][0]

    who = (await other_client.get(SESSION, headers=bearer(token))).json()
    assert (who["method"], who["user"]["username"]) == ("token", "dana")

    assert (await client.delete(f"{ME}/tokens/{body['id']}")).status_code == 204
    assert (await other_client.get(SESSION, headers=bearer(token))).status_code == 401
    assert (await client.delete(f"{ME}/tokens/{body['id']}")).status_code == 404


async def test_a_token_can_have_scopes_and_an_expiry(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")
    request = {
        "name": "read-only",
        "scopes": ["repository:*:*:read"],
        "expires_at": "2099-01-01T00:00:00Z",
    }

    body = (await client.post(f"{ME}/tokens", json=request)).json()

    assert body["scopes"] == ["repository:*:*:read"]
    assert body["expires_at"].startswith("2099-01-01T00:00:00")


async def test_token_names_must_be_unique(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")
    await client.post(f"{ME}/tokens", json={"name": "ci"})

    response = await client.post(f"{ME}/tokens", json={"name": "ci"})

    assert (response.status_code, error_code(response)) == (409, "conflict")


@pytest.mark.parametrize(
    "request_body",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"name": "ci", "scopes": ["not a pattern"]},
        {"name": "ci", "expires_at": "2020-01-01T00:00:00Z"},
        {"name": "ci", "expires_at": "2099-01-01T00:00:00"},
    ],
)
async def test_invalid_token_requests_are_rejected(client, make_user, request_body):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await client.post(f"{ME}/tokens", json=request_body)

    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_token_cannot_create_or_list_tokens(client, make_user, make_token):
    dana = await make_user("dana")
    token = await make_token(dana)

    created = await client.post(f"{ME}/tokens", json={"name": "more"}, headers=bearer(token))
    listed = await client.get(f"{ME}/tokens", headers=bearer(token))

    assert error_code(created) == "interactive_auth_required"
    assert error_code(listed) == "interactive_auth_required"


async def test_one_user_cannot_revoke_another_users_token(client, other_client, make_user):
    await make_user("dana")
    await make_user("eli")
    await sign_in(client, "dana")
    await sign_in(other_client, "eli")
    token_id = (await client.post(f"{ME}/tokens", json={"name": "ci"})).json()["id"]

    response = await other_client.delete(f"{ME}/tokens/{token_id}")

    assert response.status_code == 404
    assert (await client.get(f"{ME}/tokens")).json()["total"] == 1
