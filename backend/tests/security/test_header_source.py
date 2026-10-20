"""A trusted header source (spec 8, SEC-17): a proxy in front says who a request is in a
header; taken from a trusted proxy only, refused from anywhere else, and its changes
accepted from the server's own pages only."""

import pytest
from sqlalchemy import select

from megooarti.security import roles
from megooarti.security.models import User
from tests.accounts import PASSWORD, basic, error_code

SOURCES = "/api/v1/auth-sources"
SESSION = "/api/v1/auth/session"
PROXY = "10.0.0.5"
# As the gateway passes a request on from the SSO proxy: the client, then the proxy.
THROUGH_PROXY = {"X-Forwarded-For": f"198.51.100.9, {PROXY}"}
DEVELOPERS = [{"group": "developers", "roles": ["developers"]}]


def as_(name: str, groups: str | None = None, **more: str) -> dict[str, str]:
    said = {**THROUGH_PROXY, "X-Forwarded-User": name, **more}
    if groups is not None:
        said["X-Forwarded-Groups"] = groups
    return said


@pytest.fixture
async def header_source(admin_client, sessionmaker):
    """A header source, on, with groups, and the SSO proxy trusted."""
    async with sessionmaker() as db:
        await roles.create_role(db, "developers", "", ["repository:*:*:read"], [])
        await db.commit()
    made = await admin_client.post(
        SOURCES,
        json={
            "kind": "header",
            "name": "Corp SSO proxy",
            "enabled": True,
            "settings": {"groups_header": "X-Forwarded-Groups"},
            "group_mapping": DEVELOPERS,
        },
    )
    assert made.status_code == 201, made.text
    trusted = await admin_client.put(
        "/api/v1/settings/trusted-proxies", json={"trusted_proxies": [PROXY]}
    )
    assert trusted.status_code == 200
    return made.json()


async def test_a_header_source_is_kept_with_its_defaults_and_its_test_says_what_it_takes(
    admin_client,
):
    made = await admin_client.post(
        SOURCES, json={"kind": "header", "name": "Proxy", "settings": {}}
    )
    tested = await admin_client.post(f"{SOURCES}/{made.json()['id']}/test", json={})

    assert made.json()["settings"] == {"user_header": "X-Forwarded-User", "groups_header": None}
    assert tested.json()["ok"] is True
    assert "X-Forwarded-User names who is signed in" in tested.json()["message"]
    assert "Taken only from a trusted proxy." in tested.json()["message"]


@pytest.mark.parametrize(
    ("sent", "field"),
    [
        ({"user_header": "X Forwarded User"}, "settings.user_header"),
        ({"user_header": "Authorization"}, "settings.user_header"),
        ({"user_header": "x-forwarded-for"}, "settings.user_header"),
        ({"groups_header": "X-Forwarded-User"}, "settings.groups_header"),
        ({"groups_header": "Cookie"}, "settings.groups_header"),
    ],
)
async def test_what_is_wrong_with_a_header_source_is_said_where_it_is(admin_client, sent, field):
    refused = await admin_client.post(
        SOURCES, json={"kind": "header", "name": "Proxy", "settings": sent}
    )

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_the_header_from_a_trusted_proxy_signs_the_person_in_with_their_groups(
    other_client, header_source, sessionmaker
):
    said = await other_client.get(SESSION, headers=as_("Kim.Lee", "developers, staff"))
    async with sessionmaker() as db:
        kim = await db.scalar(select(User).where(User.username == "kim.lee"))

    assert said.status_code == 200, said.text
    assert (said.json()["method"], said.json()["user"]["username"]) == ("header", "kim.lee")
    assert "repository:*:*:read" in said.json()["permissions"]
    assert (str(kim.source_id), kim.external_id, kim.password_hash) == (
        header_source["id"],
        "kim.lee",
        None,
    )


async def test_each_request_brings_the_groups_up_to_date(other_client, header_source):
    await other_client.get(SESSION, headers=as_("kim", "developers"))

    left = await other_client.get(SESSION, headers=as_("kim", ""))

    assert "repository:*:*:read" not in left.json()["permissions"]


@pytest.mark.parametrize(
    "chain",
    [
        {},  # straight to the gateway
        {"X-Forwarded-For": f"{PROXY}, 203.0.113.7"},  # the proxy's address, written by a client
        {"X-Forwarded-For": "198.51.100.9, 10.0.0.6"},  # another proxy, not trusted
    ],
    ids=["direct", "spoofed", "untrusted"],
)
async def test_the_header_from_anywhere_else_is_refused(other_client, header_source, chain):
    refused = await other_client.get(SESSION, headers={**chain, "X-Forwarded-User": "admin"})

    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


@pytest.mark.parametrize("twice", ["X-Forwarded-User", "X-Forwarded-Groups"])
async def test_a_header_sent_twice_is_refused(other_client, header_source, twice):
    # A proxy that adds its header to the client's, rather than setting it, sends both.
    said = [*as_("kim", "developers").items(), (twice, "admin")]

    refused = await other_client.get(SESSION, headers=said)

    assert refused.status_code == 401


async def test_the_same_name_in_another_case_is_the_same_user(
    other_client, header_source, sessionmaker
):
    first = await other_client.get(SESSION, headers=as_("Kim.Lee"))
    again = await other_client.get(SESSION, headers=as_("kim.lee"))
    async with sessionmaker() as db:
        made = (await db.scalars(select(User).where(User.source_id == header_source["id"]))).all()

    assert first.json()["user"]["id"] == again.json()["user"]["id"]
    assert [user.username for user in made] == ["kim.lee"]


async def test_without_a_header_source_on_the_header_is_nobodys(admin_client, other_client):
    said = await other_client.get(SESSION, headers=as_("admin"))

    assert said.status_code == 200
    assert said.json()["authenticated"] is False


async def test_a_header_that_names_nobody_is_refused(other_client, header_source):
    refused = await other_client.get(SESSION, headers=as_("   "))

    assert refused.status_code == 401


async def test_a_change_is_taken_from_the_servers_own_pages_only(other_client, header_source):
    token = {"name": "ci"}

    bare = await other_client.post("/api/v1/me/tokens", json=token, headers=as_("kim"))
    cross = await other_client.post(
        "/api/v1/me/tokens", json=token, headers=as_("kim", **{"Sec-Fetch-Site": "same-site"})
    )
    elsewhere = await other_client.post(
        "/api/v1/me/tokens", json=token, headers=as_("kim", Origin="https://evil.example")
    )
    own = await other_client.post(
        "/api/v1/me/tokens", json=token, headers=as_("kim", **{"Sec-Fetch-Site": "same-origin"})
    )
    own_origin = await other_client.post(
        "/api/v1/me/tokens", json={"name": "ci2"}, headers=as_("kim", Origin="https://test")
    )

    for refused in (bare, cross, elsewhere):
        assert (refused.status_code, error_code(refused)) == (403, "cross_site_request")
    assert (own.status_code, own_origin.status_code) == (201, 201)


async def test_a_user_of_the_header_has_no_password_and_is_refused_once_disabled(
    admin_client, other_client, header_source, sessionmaker
):
    await other_client.get(SESSION, headers=as_("kim"))
    async with sessionmaker() as db:
        kim = await db.scalar(select(User).where(User.username == "kim"))
    by_password = await other_client.get(SESSION, headers=basic("kim", PASSWORD))
    await admin_client.patch(f"/api/v1/users/{kim.id}", json={"status": "disabled"})

    disabled = await other_client.get(SESSION, headers=as_("kim"))

    assert by_password.status_code == 401
    assert disabled.status_code == 401
