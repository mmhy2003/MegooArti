import pytest

from megooarti.security import roles as role_service
from megooarti.security import users
from tests.accounts import PASSWORD, basic, error_code, sign_in

ROLES = "/api/v1/roles"
READERS = {
    "name": "readers",
    "description": "May read everything",
    "permissions": ["repository:*:*:read", "repository:*:*:browse"],
    "roles": [],
}


async def test_listing_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(ROLES)).status_code == 401
    assert (await client.get(ROLES, headers=basic("dana", PASSWORD))).status_code == 403


async def test_create_get_and_list(admin_client):
    created = await admin_client.post(ROLES, json=READERS)

    assert created.status_code == 201
    expected = {
        **READERS,
        "builtin": False,
        "permissions": ["repository:*:*:browse", "repository:*:*:read"],
    }
    assert created.json() == expected
    assert (await admin_client.get(f"{ROLES}/readers")).json() == expected
    listed = (await admin_client.get(ROLES)).json()
    assert listed["total"] == 3
    assert [item["name"] for item in listed["items"]] == ["admin", "anonymous", "readers"]


@pytest.mark.parametrize(
    "override",
    [
        {"name": "has space"},
        {"name": ""},
        {"name": "."},
        {"name": ".."},
        {"permissions": ["not a pattern"]},
        {"description": "x" * 256},
        {"roles": ["ghost"]},
    ],
)
async def test_invalid_roles_are_rejected(admin_client, override):
    response = await admin_client.post(ROLES, json={**READERS, **override})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_duplicate_name_is_a_conflict(admin_client):
    await admin_client.post(ROLES, json=READERS)
    response = await admin_client.post(ROLES, json=READERS)
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_put_replaces_the_content(admin_client):
    await admin_client.post(ROLES, json=READERS)
    await admin_client.post(ROLES, json={**READERS, "name": "team", "roles": ["readers"]})
    update = {"description": "Changed", "permissions": ["admin:users:read"], "roles": []}

    response = await admin_client.put(f"{ROLES}/team", json=update)

    assert response.json() == {"name": "team", "builtin": False, **update}
    assert (await admin_client.put(f"{ROLES}/ghost", json=update)).status_code == 404


async def test_a_cycle_is_a_conflict(admin_client):
    await admin_client.post(ROLES, json={**READERS, "name": "inner"})
    await admin_client.post(ROLES, json={**READERS, "name": "outer", "roles": ["inner"]})

    response = await admin_client.put(
        f"{ROLES}/inner", json={"description": "", "permissions": [], "roles": ["outer"]}
    )

    assert (response.status_code, error_code(response)) == (409, "role_cycle")


async def test_built_in_roles_are_protected(admin_client):
    empty = {"description": "", "permissions": [], "roles": []}

    changed = await admin_client.put(f"{ROLES}/admin", json=empty)
    deleted = await admin_client.delete(f"{ROLES}/anonymous")

    assert (changed.status_code, error_code(changed)) == (409, "builtin_protected")
    assert (deleted.status_code, error_code(deleted)) == (409, "builtin_protected")


async def test_delete_a_role(admin_client):
    await admin_client.post(ROLES, json=READERS)

    assert (await admin_client.delete(f"{ROLES}/readers")).status_code == 204
    assert (await admin_client.get(f"{ROLES}/readers")).status_code == 404
    assert (await admin_client.delete(f"{ROLES}/readers")).status_code == 404


async def test_the_role_that_gives_the_last_administrator_access_cannot_go(client, make_user, db):
    await role_service.create_role(db, "super", "", ["*"], [])
    builtin_admin = await users.get_user_by_username(db, "admin")
    await users.update_user(db, builtin_admin, {"status": "disabled"})
    await db.commit()
    await make_user("sue", roles=["super"])
    await sign_in(client, "sue")
    empty = {"description": "", "permissions": [], "roles": []}

    deleted = await client.delete(f"{ROLES}/super")
    emptied = await client.put(f"{ROLES}/super", json=empty)

    assert (deleted.status_code, error_code(deleted)) == (409, "last_administrator")
    assert (emptied.status_code, error_code(emptied)) == (409, "last_administrator")
    assert (await client.get(f"{ROLES}/super")).json()["permissions"] == ["*"]


async def test_a_permission_granted_through_a_role_takes_effect(
    admin_client, other_client, make_user
):
    dana = await make_user("dana")
    headers = basic("dana", PASSWORD)
    assert (await other_client.get(ROLES, headers=headers)).status_code == 403

    await admin_client.post(
        ROLES, json={**READERS, "name": "role-viewers", "permissions": ["admin:roles:read"]}
    )
    await admin_client.patch(f"/api/v1/users/{dana.id}", json={"roles": ["role-viewers"]})

    assert (await other_client.get(ROLES, headers=headers)).status_code == 200
    refused = await other_client.post(ROLES, json=READERS, headers=headers)
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_a_role_that_is_called_dots_already_is_still_listed(admin_client, db):
    # Made before the rule, or by another way than this API (H3).
    await role_service.create_role(db, "..", "", [], [])
    await db.commit()

    listed = (await admin_client.get(ROLES)).json()["items"]

    assert ".." in [item["name"] for item in listed]
    # And a name that only has dots in it is a name.
    assert (await admin_client.post(ROLES, json={**READERS, "name": "..."})).status_code == 201
