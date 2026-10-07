import pytest

from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic, error_code

STORES = "/api/v1/blob-stores"


async def test_reading_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(STORES)).status_code == 401
    assert (await client.get(STORES, headers=basic("dana", PASSWORD))).status_code == 403


async def test_the_default_store_is_listed_with_its_usage(admin_client):
    body = (await admin_client.get(STORES)).json()

    assert body["total"] == 1
    (store,) = body["items"]
    assert (store["name"], store["type"], store["path"]) == ("default", "file", "default")
    assert (store["blob_count"], store["total_bytes"]) == (0, 0)
    assert store["available_bytes"] > 0


async def test_create_and_get(admin_client):
    created = await admin_client.post(STORES, json={"name": "archive"})

    assert created.status_code == 201
    assert (created.json()["name"], created.json()["path"]) == ("archive", "archive")
    fetched = (await admin_client.get(f"{STORES}/archive")).json()
    # Free disk space moves between two requests, so compare everything else.
    assert {**fetched, "available_bytes": None} == {**created.json(), "available_bytes": None}
    assert (await admin_client.get(f"{STORES}/ghost")).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"name": "has space"},
        {"name": ""},
        {"name": "s3-store", "type": "s3"},
        {"name": "escape", "path": "../outside"},
    ],
)
async def test_invalid_stores_are_rejected(admin_client, body):
    response = await admin_client.post(STORES, json=body)
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_duplicate_name_is_a_conflict(admin_client):
    response = await admin_client.post(STORES, json={"name": "default"})
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_delete(admin_client):
    await admin_client.post(STORES, json={"name": "archive"})

    assert (await admin_client.delete(f"{STORES}/archive")).status_code == 204
    assert (await admin_client.get(f"{STORES}/archive")).status_code == 404
    assert (await admin_client.delete(f"{STORES}/archive")).status_code == 404


async def test_a_store_in_use_cannot_be_deleted(admin_client, db, default_store):
    db.add(
        Repository(
            name="files",
            name_key="files",
            format="raw",
            type="hosted",
            blob_store_id=default_store.id,
        )
    )
    await db.commit()

    response = await admin_client.delete(f"{STORES}/default")

    assert (response.status_code, error_code(response)) == (409, "in_use")
