import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

SETTINGS = "/api/v1/settings"
SESSION = "/api/v1/auth/session"
DEFAULTS = {"base_url": None, "anonymous_access": {"enabled": False}}


async def test_reading_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(SETTINGS)).status_code == 401
    assert (await client.get(SETTINGS, headers=basic("dana", PASSWORD))).status_code == 403


async def test_defaults(admin_client):
    assert (await admin_client.get(SETTINGS)).json() == DEFAULTS


async def test_base_url_is_stored_without_a_trailing_slash_and_can_be_cleared(admin_client):
    stored = await admin_client.put(
        f"{SETTINGS}/base-url", json={"base_url": " https://repo.example.org/megooarti/ "}
    )

    assert stored.status_code == 200
    assert stored.json()["base_url"] == "https://repo.example.org/megooarti"
    assert (await admin_client.get(SETTINGS)).json()["base_url"] == stored.json()["base_url"]

    cleared = await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": None})
    assert cleared.json() == DEFAULTS


@pytest.mark.parametrize(
    "value",
    [
        "ftp://repo.example.org",
        "repo.example.org",
        "https://",
        "https://x.example/?a=1",
        # Every address the server gives out would carry them (H4).
        "https://robot:secret@repo.example.org",
        "https://robot@repo.example.org",
        "https://@repo.example.org",
    ],
)
async def test_an_invalid_base_url_is_rejected(admin_client, value):
    response = await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": value})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_turning_on_anonymous_access_takes_effect_at_once(admin_client, other_client):
    assert (await other_client.get(SESSION)).json()["method"] is None

    response = await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": True})

    assert response.json()["anonymous_access"] == {"enabled": True}
    seen = (await other_client.get(SESSION)).json()
    assert (seen["authenticated"], seen["method"], seen["user"]) == (False, "anonymous", None)
    assert seen["permissions"] == ["repository:*:*:browse", "repository:*:*:read"]

    await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": False})
    assert (await other_client.get(SESSION)).json()["method"] is None


async def test_reading_settings_does_not_allow_changing_them(client, make_user, db):
    await roles.create_role(db, "settings-readers", "", ["admin:settings:read"], [])
    await db.commit()
    await make_user("rae", roles=["settings-readers"])
    headers = basic("rae", PASSWORD)

    read = await client.get(SETTINGS, headers=headers)
    write = await client.put(
        f"{SETTINGS}/anonymous-access", json={"enabled": True}, headers=headers
    )

    assert read.status_code == 200
    assert (write.status_code, error_code(write)) == (403, "forbidden")


async def test_a_base_url_may_have_a_port_and_a_path(admin_client):
    response = await admin_client.put(
        f"{SETTINGS}/base-url", json={"base_url": "http://repo.example.org:8081/megooarti"}
    )

    assert response.status_code == 200
    assert response.json()["base_url"] == "http://repo.example.org:8081/megooarti"
