import uuid

import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code, sign_in

USERS = "/api/v1/users"
SESSION = "/api/v1/auth/session"
ELI = {
    "username": "Eli",
    "display_name": "Eli Stone",
    "email": "eli@example.org",
    "password": "a perfectly fine password",
    "roles": ["anonymous"],
}


async def id_of(client, username: str) -> str:
    listed = (await client.get(USERS, params={"limit": 200})).json()
    return next(item["id"] for item in listed["items"] if item["username"] == username)


async def test_listing_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(USERS)).status_code == 401
    refused = await client.get(USERS, headers=basic("dana", PASSWORD))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_list_is_paged(admin_client):
    body = (await admin_client.get(USERS, params={"limit": 2})).json()

    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 0)
    assert [item["username"] for item in body["items"]] == ["admin", "anonymous"]


async def test_create_a_user_who_must_change_their_password(admin_client, other_client):
    response = await admin_client.post(USERS, json=ELI)

    assert response.status_code == 201
    body = response.json()
    assert (body["username"], body["display_name"], body["email"]) == (
        "eli",
        "Eli Stone",
        "eli@example.org",
    )
    assert (body["status"], body["builtin"], body["roles"]) == ("active", False, ["anonymous"])
    assert body["must_change_password"] is True
    assert "password" not in body
    signed_in = await sign_in(other_client, "eli", ELI["password"])
    assert signed_in["must_change_password"] is True


@pytest.mark.parametrize(
    "override",
    [
        {"username": "has space"},
        {"username": ""},
        {"display_name": ""},
        {"email": "not-an-email"},
        {"password": "short"},
        {"roles": ["ghost"]},
    ],
)
async def test_invalid_users_are_rejected(admin_client, override):
    response = await admin_client.post(USERS, json={**ELI, **override})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_duplicate_username_is_a_conflict(admin_client):
    await admin_client.post(USERS, json=ELI)
    response = await admin_client.post(USERS, json={**ELI, "username": "ELI"})
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_get_one_user(admin_client):
    root_id = await id_of(admin_client, "root")

    found = await admin_client.get(f"{USERS}/{root_id}")
    missing = await admin_client.get(f"{USERS}/{uuid.uuid4()}")
    malformed = await admin_client.get(f"{USERS}/not-a-uuid")

    assert found.json()["roles"] == ["admin"]
    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert malformed.status_code == 422


async def test_patch_changes_only_what_is_sent(admin_client, make_user):
    dana = await make_user("dana", roles=["anonymous"])

    response = await admin_client.patch(f"{USERS}/{dana.id}", json={"display_name": "D. Smith"})
    assert response.json()["display_name"] == "D. Smith"
    assert response.json()["roles"] == ["anonymous"]

    response = await admin_client.patch(
        f"{USERS}/{dana.id}", json={"roles": ["admin"], "email": "d@example.org"}
    )
    assert (response.json()["roles"], response.json()["email"]) == (["admin"], "d@example.org")

    response = await admin_client.patch(f"{USERS}/{dana.id}", json={"email": None})
    assert response.json()["email"] is None


async def test_disabling_a_user_signs_them_out_and_keeps_them_out(
    admin_client, other_client, make_user
):
    dana = await make_user("dana")
    await sign_in(other_client, "dana")

    response = await admin_client.patch(f"{USERS}/{dana.id}", json={"status": "disabled"})

    assert response.json()["status"] == "disabled"
    assert (await other_client.get(SESSION)).json()["authenticated"] is False
    login = {"username": "dana", "password": PASSWORD}
    assert (await other_client.post("/api/v1/auth/login", json=login)).status_code == 401


async def test_you_cannot_disable_or_delete_yourself(admin_client):
    root_id = await id_of(admin_client, "root")

    disabled = await admin_client.patch(f"{USERS}/{root_id}", json={"status": "disabled"})
    deleted = await admin_client.delete(f"{USERS}/{root_id}")

    assert (disabled.status_code, error_code(disabled)) == (409, "self_protected")
    assert (deleted.status_code, error_code(deleted)) == (409, "self_protected")


async def test_the_last_administrator_cannot_be_demoted(admin_client):
    root_id = await id_of(admin_client, "root")

    response = await admin_client.patch(f"{USERS}/{root_id}", json={"roles": []})

    assert (response.status_code, error_code(response)) == (409, "last_administrator")
    assert (await admin_client.get(f"{USERS}/{root_id}")).json()["roles"] == ["admin"]


async def test_delete_a_user(admin_client, make_user):
    dana = await make_user("dana")

    assert (await admin_client.delete(f"{USERS}/{dana.id}")).status_code == 204
    assert (await admin_client.get(f"{USERS}/{dana.id}")).status_code == 404


async def test_built_in_users_cannot_be_deleted(admin_client):
    admin_id = await id_of(admin_client, "admin")

    response = await admin_client.delete(f"{USERS}/{admin_id}")

    assert (response.status_code, error_code(response)) == (409, "builtin_protected")


async def test_reset_a_password(admin_client, other_client, make_user):
    dana = await make_user("dana")
    await sign_in(other_client, "dana")

    response = await admin_client.put(
        f"{USERS}/{dana.id}/password", json={"password": "a temporary password"}
    )

    assert response.status_code == 204
    assert (await other_client.get(SESSION)).json()["authenticated"] is False
    old = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    assert old.status_code == 401
    assert (await sign_in(other_client, "dana", "a temporary password"))[
        "must_change_password"
    ] is True


async def test_the_anonymous_user_cannot_be_given_a_password(admin_client):
    anonymous_id = await id_of(admin_client, "anonymous")

    response = await admin_client.put(
        f"{USERS}/{anonymous_id}/password", json={"password": "a temporary password"}
    )

    assert (response.status_code, error_code(response)) == (409, "builtin_protected")


async def test_list_and_revoke_another_users_tokens(admin_client, make_user, make_token):
    dana = await make_user("dana")
    await make_token(dana, "ci")
    url = f"{USERS}/{dana.id}/tokens"

    listed = (await admin_client.get(url)).json()

    assert (listed["total"], listed["items"][0]["name"]) == (1, "ci")
    assert "token" not in listed["items"][0]
    token_id = listed["items"][0]["id"]
    assert (await admin_client.delete(f"{url}/{token_id}")).status_code == 204
    assert (await admin_client.get(url)).json()["total"] == 0
    assert (await admin_client.get(f"{USERS}/{uuid.uuid4()}/tokens")).status_code == 404


async def test_managing_users_does_not_include_managing_their_tokens(client, make_user, db):
    await roles.create_role(db, "user-admins", "", ["admin:users:*"], [])
    await db.commit()
    ula = await make_user("ula", roles=["user-admins"])
    headers = basic("ula", PASSWORD)

    allowed = await client.get(USERS, headers=headers)
    refused = await client.get(f"{USERS}/{ula.id}/tokens", headers=headers)

    assert allowed.status_code == 200
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
