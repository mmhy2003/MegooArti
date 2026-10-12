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
        {"name": "."},
        {"name": ".."},
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
        {
            "remote_url": "https://remote.example",
            "remote_auth": {"type": "bearer", "secret": "tökën"},
        },
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


@pytest.mark.parametrize("name", ["...", ".a", "a.", "a..b", "-"])
async def test_a_name_with_dots_in_it_is_a_name(admin_client, name):
    # Only . and .. themselves are folders to a browser and a proxy.
    assert (await admin_client.post(REPOSITORIES, json={**FILES, "name": name})).status_code == 201


@pytest.mark.parametrize(
    ("wanted", "policy"),
    [
        # A Maven repository takes releases unless it says otherwise, and a release is
        # deployed once.
        ({"format": "maven"}, "disable_redeploy"),
        ({"format": "maven", "format_config": {"version_policy": "release"}}, "disable_redeploy"),
        ({"format": "maven", "hosted": {}}, "disable_redeploy"),
        ({"format": "maven", "hosted": {"deployment_policy": None}}, "disable_redeploy"),
        # A snapshot is replaced by its nature, and a mixed repository takes snapshots.
        ({"format": "maven", "format_config": {"version_policy": "snapshot"}}, "allow_redeploy"),
        ({"format": "maven", "format_config": {"version_policy": "mixed"}}, "allow_redeploy"),
        ({"format": "raw"}, "allow_redeploy"),
        ({"format": "npm"}, "allow_redeploy"),
        ({"format": "pypi", "hosted": {}}, "allow_redeploy"),
        # What is said is kept, whatever the format would have chosen.
        ({"format": "maven", "hosted": {"deployment_policy": "allow_redeploy"}}, "allow_redeploy"),
        ({"format": "maven", "hosted": {"deployment_policy": "read_only"}}, "read_only"),
        (
            {"format": "raw", "hosted": {"deployment_policy": "disable_redeploy"}},
            "disable_redeploy",
        ),
    ],
)
async def test_a_hosted_repository_given_no_policy_gets_its_formats_own(
    admin_client, wanted, policy
):
    created = await admin_client.post(
        REPOSITORIES, json={"name": "made", "type": "hosted", **wanted}
    )

    assert created.status_code == 201, created.text
    assert created.json()["hosted"] == {"deployment_policy": policy}
    assert (await admin_client.get(f"{REPOSITORIES}/made")).json()["hosted"] == {
        "deployment_policy": policy
    }


async def test_replacing_a_repository_without_a_policy_gives_it_its_formats_own(admin_client):
    for name, format in (("releases", "maven"), ("files", "raw")):
        wanted = {"name": name, "format": format, "type": "hosted"}
        await admin_client.post(
            REPOSITORIES, json={**wanted, "hosted": {"deployment_policy": "read_only"}}
        )

    releases = await admin_client.put(f"{REPOSITORIES}/releases", json={"online": True})
    files = await admin_client.put(f"{REPOSITORIES}/files", json={"online": True})
    kept = await admin_client.put(
        f"{REPOSITORIES}/releases",
        json={"online": True, "hosted": {"deployment_policy": "allow_redeploy"}},
    )

    assert releases.json()["hosted"] == {"deployment_policy": "disable_redeploy"}
    assert files.json()["hosted"] == {"deployment_policy": "allow_redeploy"}
    assert kept.json()["hosted"] == {"deployment_policy": "allow_redeploy"}


async def test_a_proxy_and_a_group_have_no_deployment_policy(admin_client):
    proxy = {"name": "central", "format": "maven", "type": "proxy"}
    made = await admin_client.post(
        REPOSITORIES, json={**proxy, "proxy": {"remote_url": "https://repo.example.org/maven2"}}
    )
    group = await admin_client.post(
        REPOSITORIES,
        json={"name": "all", "format": "maven", "type": "group", "group": {"members": []}},
    )

    assert (made.status_code, made.json()["hosted"]) == (201, None)
    assert (group.status_code, group.json()["hosted"]) == (201, None)
