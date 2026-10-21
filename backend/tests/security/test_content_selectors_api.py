"""Content selectors' API (spec 10): kept with their own permissions, refused at their
expression saying where, previewed against paths, recorded in the audit log, and kept
while a role names them."""

import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.audit import last

SELECTORS = "/api/v1/content-selectors"
ACME = {"name": "acme", "description": "Acme's", "expression": 'path =^ "/com/acme/"'}


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def test_a_selector_is_made_listed_changed_and_deleted_with_its_records(
    admin_client, sessionmaker
):
    made = await admin_client.post(SELECTORS, json=ACME)
    listed = await admin_client.get(SELECTORS)
    changed = await admin_client.put(
        f"{SELECTORS}/acme", json={"description": "Acme's", "expression": 'path =^ "/com/"'}
    )
    read = await admin_client.get(f"{SELECTORS}/acme")
    deleted = await admin_client.delete(f"{SELECTORS}/acme")
    gone = await admin_client.get(f"{SELECTORS}/acme")

    assert made.status_code == 201
    assert (made.json()["name"], made.json()["expression"]) == ("acme", 'path =^ "/com/acme/"')
    assert [found["name"] for found in listed.json()["items"]] == ["acme"]
    assert changed.status_code == 200
    assert read.json()["expression"] == 'path =^ "/com/"'
    assert (deleted.status_code, gone.status_code) == (204, 404)
    assert (await last(sessionmaker, "selector.created")).target_name == "acme"
    assert (await last(sessionmaker, "selector.updated")).changes == {
        "expression": {"before": 'path =^ "/com/acme/"', "after": 'path =^ "/com/"'}
    }
    assert (await last(sessionmaker, "selector.deleted")).target_name == "acme"


@pytest.mark.parametrize(
    ("expression", "said"),
    [
        ('path = "/com/"', "Unexpected '=' (at character 6)"),
        (
            'path =~ "(unclosed"',
            "Not a pattern: missing ), unterminated subpattern (at character 9)",
        ),
        ('name == "x"', "Expected format, path or ( (at character 1)"),
    ],
)
async def test_an_expression_that_does_not_parse_is_refused_saying_where(
    admin_client, expression, said
):
    refused = await admin_client.post(SELECTORS, json={**ACME, "expression": expression})
    changed = await admin_client.post(SELECTORS, json=ACME)
    refused_change = await admin_client.put(
        f"{SELECTORS}/acme", json={"description": "", "expression": expression}
    )

    assert changed.status_code == 201
    for answer in (refused, refused_change):
        assert (answer.status_code, error_code(answer)) == (422, "validation_error")
        assert answer.json()["error"]["details"] == [{"field": "expression", "message": said}]


@pytest.mark.parametrize("name", ["with space", "a:b", "..", "x" * 65])
async def test_a_name_a_permission_could_not_hold_is_refused(admin_client, name):
    refused = await admin_client.post(SELECTORS, json={**ACME, "name": name})

    assert refused.status_code == 422


async def test_a_name_taken_is_a_conflict(admin_client):
    await admin_client.post(SELECTORS, json=ACME)

    again = await admin_client.post(SELECTORS, json=ACME)

    assert (again.status_code, error_code(again)) == (409, "conflict")


async def test_a_preview_says_which_paths_match(admin_client):
    said = await admin_client.post(
        f"{SELECTORS}/preview",
        json={
            "expression": 'format == "maven" and path =^ "/com/acme/"',
            "format": "maven",
            "paths": ["/com/acme/app/1.0/app-1.0.jar", "com/acme/lib.pom", "/org/x.jar"],
        },
    )

    assert said.json() == {
        "paths": [
            {"path": "/com/acme/app/1.0/app-1.0.jar", "matches": True},
            {"path": "/com/acme/lib.pom", "matches": True},
            {"path": "/org/x.jar", "matches": False},
        ]
    }


async def test_a_role_names_only_a_selector_there_is_and_keeps_it(admin_client):
    await admin_client.post(SELECTORS, json=ACME)
    unknown = await admin_client.post(
        "/api/v1/roles",
        json={
            "name": "acme-readers",
            "permissions": ["selector:nobody:maven:*:read"],
            "roles": [],
        },
    )
    every = await admin_client.post(
        "/api/v1/roles",
        json={"name": "every-selector", "permissions": ["selector:*:maven:*:read"], "roles": []},
    )
    named = await admin_client.post(
        "/api/v1/roles",
        json={"name": "acme-readers", "permissions": ["selector:acme:maven:*:read"], "roles": []},
    )

    kept = await admin_client.delete(f"{SELECTORS}/acme")

    assert (unknown.status_code, error_code(unknown)) == (422, "validation_error")
    assert unknown.json()["error"]["details"] == [
        {"field": "permissions", "message": "Unknown content selector: nobody"}
    ]
    assert (every.status_code, named.status_code) == (201, 201)
    assert (kept.status_code, error_code(kept)) == (409, "in_use")
    assert "acme-readers" in kept.json()["error"]["message"]
    assert "every-selector" not in kept.json()["error"]["message"]


async def test_selectors_need_their_permissions(client, make_user, sessionmaker):
    await make_role(sessionmaker, "selector-readers", "admin:selectors:read")
    await make_user("rita", roles=["selector-readers"])
    await make_user("sam")
    rita = basic("rita", PASSWORD)

    nobody = await client.get(SELECTORS)
    sam = await client.get(SELECTORS, headers=basic("sam", PASSWORD))
    reads = await client.get(SELECTORS, headers=rita)
    previews = await client.post(
        f"{SELECTORS}/preview", json={"expression": 'path =^ "/"', "paths": []}, headers=rita
    )
    makes = await client.post(SELECTORS, json=ACME, headers=rita)

    assert (nobody.status_code, sam.status_code) == (401, 403)
    assert (reads.status_code, previews.status_code, makes.status_code) == (200, 200, 403)


async def test_a_preview_takes_paths_no_longer_than_a_path_is(admin_client):
    refused = await admin_client.post(
        f"{SELECTORS}/preview",
        json={"expression": 'path =^ "/"', "paths": ["/" + "a" * 1024]},
    )

    assert refused.status_code == 422
