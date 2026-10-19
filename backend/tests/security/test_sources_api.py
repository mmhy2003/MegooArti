"""The sign-in sources' API (spec 4.3): kept, shown without their secrets, ordered,
tested and deleted; and the list the sign-in screen shows before anyone signs in."""

import uuid

import pytest
from sqlalchemy import select

from megooarti.security import roles
from megooarti.security.models import AuthSource
from tests.accounts import PASSWORD, basic, error_code
from tests.security.directory import SECRET, person

SOURCES = "/api/v1/auth-sources"
LOGIN = "/api/v1/auth/login"


def directory(name: str = "corp", **more) -> dict:
    return {
        "kind": "directory",
        "name": name,
        "settings": {"people": {"ann": person("ann pw", "staff")}, "secret": SECRET},
        **more,
    }


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def test_sources_need_the_security_permissions(client, make_user, sessionmaker, kinds):
    await make_role(sessionmaker, "security-reader", "admin:security:read")
    await make_user("rita", roles=["security-reader"])
    as_rita = basic("rita", PASSWORD)

    nobody = await client.get(SOURCES)
    reads = await client.get(SOURCES, headers=as_rita)
    writes = await client.post(SOURCES, json=directory(), headers=as_rita)

    assert (nobody.status_code, reads.status_code, writes.status_code) == (401, 200, 403)


async def test_a_source_is_kept_off_and_last_with_its_secret_sealed_and_never_shown(
    admin_client, sessionmaker, kinds
):
    await make_role(sessionmaker, "staff", "repository:*:*:read")
    first = await admin_client.post(SOURCES, json=directory("first"))
    made = await admin_client.post(
        SOURCES,
        json=directory("second", group_mapping=[{"group": "staff", "roles": ["staff"]}]),
    )
    async with sessionmaker() as db:
        kept = await db.scalar(select(AuthSource).where(AuthSource.name == "second"))

    assert (first.status_code, made.status_code) == (201, 201)
    body = made.json()
    assert (body["kind"], body["enabled"], body["position"], body["users"]) == (
        "directory",
        False,
        1,
        0,
    )
    assert body["secrets"] == ["secret"]
    assert "secret" not in body["settings"]
    assert SECRET not in made.text
    assert kept.settings["secret"] != SECRET  # sealed
    assert body["group_mapping"] == [{"group": "staff", "roles": ["staff"]}]


async def test_a_change_without_the_secret_keeps_it(admin_client, kinds):
    made = (await admin_client.post(SOURCES, json=directory())).json()

    changed = await admin_client.put(
        f"{SOURCES}/{made['id']}",
        json={"name": "corp", "enabled": True, "settings": made["settings"], "group_mapping": []},
    )
    # The directory answers only with the secret it was given: it was kept, and unsealed.
    signed_in = await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})

    assert changed.json()["secrets"] == ["secret"]
    assert changed.json()["enabled"] is True
    assert signed_in.json() == {"ok": True, "message": "The directory answered.", "user": None}


@pytest.mark.parametrize(
    ("sent", "field"),
    [
        ({"kind": "smoke-signals"}, "kind"),
        ({"name": "local"}, "name"),
        ({"name": "Local"}, "name"),
        ({"name": " leading space"}, "body.name"),
        ({"name": "x" * 65}, "body.name"),
        ({"settings": {"people": "everyone"}}, "settings.people"),
        ({"group_mapping": [{"group": "staff", "roles": ["no-such-role"]}]}, "group_mapping"),
        ({"group_mapping": [{"group": "", "roles": []}]}, "body.group_mapping.0.group"),
    ],
)
async def test_what_is_wrong_with_a_source_is_said_where_it_is(admin_client, kinds, sent, field):
    refused = await admin_client.post(SOURCES, json={**directory(), **sent})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert refused.json()["error"]["details"][0]["field"] == field


async def test_two_sources_are_not_called_alike(admin_client, kinds):
    await admin_client.post(SOURCES, json=directory("Corp"))

    again = await admin_client.post(SOURCES, json=directory("corp"))

    assert (again.status_code, error_code(again)) == (409, "conflict")


async def test_the_sources_are_put_in_the_order_given_and_asked_in_it(
    admin_client, other_client, kinds
):
    ids = []
    for name, password in (("first", "first pw"), ("second", "second pw")):
        sent = directory(name, enabled=True)
        sent["settings"]["people"] = {"bo": person(password)}
        ids.append((await admin_client.post(SOURCES, json=sent)).json()["id"])

    ordered = await admin_client.put(f"{SOURCES}/order", json={"ids": ids[::-1]})
    listed = await admin_client.get(SOURCES)
    signed_in = await other_client.post(LOGIN, json={"username": "bo", "password": "second pw"})

    assert [item["name"] for item in ordered.json()["items"]] == ["second", "first"]
    assert [(item["name"], item["position"]) for item in listed.json()["items"]] == [
        ("second", 0),
        ("first", 1),
    ]
    assert signed_in.status_code == 200


@pytest.mark.parametrize("which", ["missing", "twice", "stranger"])
async def test_an_order_names_every_source_once(admin_client, kinds, which):
    one = (await admin_client.post(SOURCES, json=directory("one"))).json()["id"]
    two = (await admin_client.post(SOURCES, json=directory("two"))).json()["id"]
    ids = {"missing": [one], "twice": [one, two, one], "stranger": [one, str(uuid.uuid4())]}

    refused = await admin_client.put(f"{SOURCES}/order", json={"ids": ids[which]})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")


async def test_a_test_says_who_the_source_says_someone_is_and_what_they_would_be_given(
    admin_client, sessionmaker, kinds
):
    await make_role(sessionmaker, "staff", "repository:*:*:read")
    made = (
        await admin_client.post(
            SOURCES, json=directory(group_mapping=[{"group": "STAFF", "roles": ["staff"]}])
        )
    ).json()

    tried = await admin_client.post(
        f"{SOURCES}/{made['id']}/test", json={"username": "ann", "password": "ann pw"}
    )
    wrong = await admin_client.post(
        f"{SOURCES}/{made['id']}/test", json={"username": "ann", "password": "no"}
    )
    users = (await admin_client.get("/api/v1/users", params={"limit": 200})).json()

    assert tried.json() == {
        "ok": True,
        "message": "ann signed in.",
        "user": {
            "external_id": "uid=ann,ou=people",
            "username": "ann",
            "display_name": "Ann",
            "email": None,
            "groups": ["staff"],
            "roles": ["staff"],
        },
    }
    assert (wrong.json()["ok"], wrong.json()["user"]) == (False, None)
    assert "ann" not in [user["username"] for user in users["items"]]  # nobody was made


async def test_a_source_that_does_not_answer_says_so_when_tested(admin_client, kinds):
    sent = directory()
    sent["settings"]["down"] = True
    made = (await admin_client.post(SOURCES, json=sent)).json()

    tried = await admin_client.post(f"{SOURCES}/{made['id']}/test", json={})

    assert tried.json() == {"ok": False, "message": "the directory did not answer", "user": None}


async def test_deleting_a_source_disables_and_keeps_its_users(admin_client, other_client, kinds):
    made = (await admin_client.post(SOURCES, json=directory(enabled=True))).json()
    await other_client.post(LOGIN, json={"username": "ann", "password": "ann pw"})
    counted = (await admin_client.get(f"{SOURCES}/{made['id']}")).json()["users"]

    deleted = await admin_client.delete(f"{SOURCES}/{made['id']}")
    session = (await other_client.get("/api/v1/auth/session")).json()
    users = (await admin_client.get("/api/v1/users", params={"limit": 200})).json()["items"]
    ann = next(user for user in users if user["username"] == "ann")
    gone = await admin_client.get(f"{SOURCES}/{made['id']}")

    assert (counted, deleted.status_code, gone.status_code) == (1, 204, 404)
    assert session["authenticated"] is False
    assert (ann["status"], ann["source"], ann["external_id"]) == (
        "disabled",
        None,
        "uid=ann,ou=people",
    )


async def test_a_user_shows_the_source_they_sign_in_through(admin_client, other_client, kinds):
    await admin_client.post(SOURCES, json=directory("Corp", enabled=True))
    await other_client.post(LOGIN, json={"username": "ann", "password": "ann pw"})

    users = (await admin_client.get("/api/v1/users", params={"limit": 200})).json()["items"]
    by_name = {user["username"]: user for user in users}

    assert (by_name["ann"]["source"], by_name["ann"]["external_id"]) == (
        "Corp",
        "uid=ann,ou=people",
    )
    assert (by_name["root"]["source"], by_name["root"]["external_id"]) == (None, None)


async def test_the_sign_in_screen_is_told_the_enabled_sources_signed_in_to_in_the_browser(
    client, add_source
):
    await add_source("Corp SSO", kind="portal", issuer="https://sso.example")
    await add_source("Old SSO", kind="portal", enabled=False)
    await add_source("Corp LDAP")

    listed = await client.get("/api/v1/auth/sources")

    assert listed.status_code == 200
    assert [(item["name"], item["kind"]) for item in listed.json()["items"]] == [
        ("Corp SSO", "portal")
    ]
    assert set(listed.json()["items"][0]) == {"id", "name", "kind"}
