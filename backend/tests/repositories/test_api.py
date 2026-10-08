import pytest
from sqlalchemy import select

from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic, error_code

REPOSITORIES = "/api/v1/repositories"
FILES = {"name": "files", "format": "raw", "type": "hosted"}
EXPECTED = {
    "name": "files",
    "format": "raw",
    "type": "hosted",
    "online": True,
    "blob_store": "default",
    "url_path": "/repository/files/",
    "hosted": {"deployment_policy": "allow_redeploy"},
    "format_config": {},
    "proxy": None,
    "group": None,
    "status": None,
}


async def test_reading_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(REPOSITORIES)).status_code == 401
    assert (await client.get(REPOSITORIES, headers=basic("dana", PASSWORD))).status_code == 403


async def test_create_get_and_list(admin_client):
    created = await admin_client.post(REPOSITORIES, json=FILES)

    assert created.status_code == 201
    assert created.json() == EXPECTED
    assert (await admin_client.get(f"{REPOSITORIES}/files")).json() == EXPECTED
    assert (await admin_client.get(REPOSITORIES)).json()["items"] == [EXPECTED]
    assert (await admin_client.get(f"{REPOSITORIES}/ghost")).status_code == 404


async def test_create_with_explicit_settings(admin_client):
    await admin_client.post("/api/v1/blob-stores", json={"name": "archive"})
    request = {
        **FILES,
        "online": False,
        "blob_store": "archive",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }

    body = (await admin_client.post(REPOSITORIES, json=request)).json()

    assert (body["online"], body["blob_store"]) == (False, "archive")
    assert body["hosted"] == {"deployment_policy": "disable_redeploy"}


@pytest.mark.parametrize(
    "override",
    [
        {"name": "has space"},
        {"name": "a:b"},
        {"name": "star*"},
        {"format": "cobol"},
        {"type": "proxy", "proxy": {"remote_url": "ftp://remote.example"}},
        {"type": "nonsense"},
        {"blob_store": "ghost"},
        {"hosted": {"deployment_policy": "sometimes"}},
        {"format_config": {"anything": 1}},
    ],
)
async def test_invalid_repositories_are_rejected(admin_client, override):
    response = await admin_client.post(REPOSITORIES, json={**FILES, **override})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_name_that_differs_only_by_case_is_a_conflict(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    response = await admin_client.post(REPOSITORIES, json={**FILES, "name": "FILES"})
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_put_replaces_what_can_change(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    update = {"online": False, "hosted": {"deployment_policy": "read_only"}}

    response = await admin_client.put(f"{REPOSITORIES}/files", json=update)

    assert response.status_code == 200
    assert response.json() == {**EXPECTED, **update}
    assert (await admin_client.put(f"{REPOSITORIES}/ghost", json=update)).status_code == 404


async def test_put_may_repeat_the_fixed_fields_unchanged(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    same = {"online": True, "format": "raw", "type": "hosted", "blob_store": "default"}

    assert (await admin_client.put(f"{REPOSITORIES}/files", json=same)).status_code == 200


@pytest.mark.parametrize(
    "change", [{"format": "maven"}, {"type": "proxy"}, {"blob_store": "archive"}]
)
async def test_put_cannot_change_format_type_or_blob_store(admin_client, change):
    await admin_client.post(REPOSITORIES, json=FILES)

    response = await admin_client.put(f"{REPOSITORIES}/files", json={"online": True, **change})

    assert (response.status_code, error_code(response)) == (409, "immutable")


async def test_delete(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)

    assert (await admin_client.delete(f"{REPOSITORIES}/files")).status_code == 204
    assert (await admin_client.get(f"{REPOSITORIES}/files")).status_code == 404
    assert (await admin_client.delete(f"{REPOSITORIES}/files")).status_code == 404


MIRROR = {
    "name": "mirror",
    "format": "raw",
    "type": "proxy",
    "proxy": {
        "remote_url": "https://remote.example/files",
        "remote_auth": {"type": "basic", "username": "robot", "secret": "hunter2-the-remote"},
    },
}


async def test_create_a_proxy_without_ever_returning_its_secret(admin_client, db):
    created = await admin_client.post(REPOSITORIES, json=MIRROR)

    assert created.status_code == 201
    body = created.json()
    assert (body["type"], body["blob_store"], body["hosted"], body["group"]) == (
        "proxy",
        "default",
        None,
        None,
    )
    assert body["proxy"]["remote_auth"] == {
        "type": "basic",
        "username": "robot",
        "has_secret": True,
    }
    assert body["status"] == {
        "blocked": False,
        "auto_blocked_until": None,
        "failures": 0,
        "last_error": None,
    }
    fetched = await admin_client.get(f"{REPOSITORIES}/mirror")
    assert "hunter2" not in created.text + fetched.text
    stored = await db.scalar(select(Repository.config).where(Repository.name == "mirror"))
    assert stored["proxy"]["remote_auth"]["secret"].startswith("enc:v1:")


async def test_updating_a_proxy_without_a_secret_keeps_it(admin_client):
    await admin_client.post(REPOSITORIES, json=MIRROR)
    update = {
        "proxy": {
            "remote_url": "https://remote.example/other",
            "content_max_age_minutes": -1,
            "remote_auth": {"type": "basic", "username": "robot"},
        }
    }

    body = (await admin_client.put(f"{REPOSITORIES}/mirror", json=update)).json()

    assert body["proxy"]["remote_url"] == "https://remote.example/other"
    assert body["proxy"]["content_max_age_minutes"] == -1
    assert body["proxy"]["remote_auth"]["has_secret"] is True


@pytest.mark.parametrize(
    "proxy",
    [
        None,
        {},
        {"remote_url": "ftp://remote.example"},
        {"remote_url": "https://remote.example", "content_max_age_minutes": -2},
        {"remote_url": "https://remote.example", "negative_cache": {"ttl_minutes": 0}},
        {"remote_url": "https://remote.example", "remote_auth": {"type": "kerberos"}},
        {"remote_url": "https://remote.example", "remote_auth": {"type": "bearer"}},
    ],
)
async def test_invalid_proxies_are_rejected(admin_client, proxy):
    response = await admin_client.post(REPOSITORIES, json={**MIRROR, "proxy": proxy})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_create_and_reorder_a_group(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    await admin_client.post(REPOSITORIES, json=MIRROR)
    everything = {
        "name": "all",
        "format": "raw",
        "type": "group",
        "group": {"members": ["files", "mirror"]},
    }

    created = await admin_client.post(REPOSITORIES, json=everything)
    reordered = await admin_client.put(
        f"{REPOSITORIES}/all", json={"group": {"members": ["mirror", "files"]}}
    )

    assert created.status_code == 201
    assert (created.json()["blob_store"], created.json()["group"]) == (
        None,
        {"members": ["files", "mirror"]},
    )
    assert reordered.json()["group"] == {"members": ["mirror", "files"]}


async def test_group_mistakes_are_reported(admin_client):
    await admin_client.post(REPOSITORIES, json=FILES)
    everything = {"name": "all", "format": "raw", "type": "group"}
    await admin_client.post(REPOSITORIES, json={**everything, "group": {"members": ["files"]}})

    unknown = await admin_client.post(
        REPOSITORIES, json={**everything, "name": "more", "group": {"members": ["ghost"]}}
    )
    cycle = await admin_client.put(f"{REPOSITORIES}/all", json={"group": {"members": ["all"]}})
    in_use = await admin_client.delete(f"{REPOSITORIES}/files")

    assert (unknown.status_code, error_code(unknown)) == (422, "validation_error")
    assert (cycle.status_code, error_code(cycle)) == (409, "repository_cycle")
    assert (in_use.status_code, error_code(in_use)) == (409, "in_use")
