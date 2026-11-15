"""Cleanup policies' API (spec 4.5): kept with their own permissions, refused at their
fields, their format fixed once made, recorded in the audit log."""

import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.audit import last

POLICIES = "/api/v1/cleanup-policies"
STALE = {
    "name": "stale-snapshots",
    "format": "maven",
    "updated_days": 14,
    "release_type": "prerelease",
}
CONTENT = {key: value for key, value in STALE.items() if key != "name"}


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def test_a_policy_is_made_read_listed_changed_and_deleted(admin_client):
    made = await admin_client.post(POLICIES, json=STALE)
    read = await admin_client.get(f"{POLICIES}/stale-snapshots")
    listed = await admin_client.get(POLICIES)
    changed = await admin_client.put(
        f"{POLICIES}/stale-snapshots",
        json={"format": "maven", "updated_days": 30, "release_type": "prerelease"},
    )
    deleted = await admin_client.delete(f"{POLICIES}/stale-snapshots")
    gone = await admin_client.get(f"{POLICIES}/stale-snapshots")

    assert made.status_code == 201, made.text
    body = made.json()
    assert {key: body[key] for key in ("name", "format", "updated_days", "release_type")} == STALE
    assert (body["downloaded_days"], body["asset_pattern"], body["description"]) == (None, None, "")
    assert body["repositories"] == []
    assert read.json()["name"] == "stale-snapshots"
    assert listed.json()["total"] == 1
    assert [item["name"] for item in listed.json()["items"]] == ["stale-snapshots"]
    assert changed.status_code == 200, changed.text
    assert changed.json()["updated_days"] == 30
    assert deleted.status_code == 204
    assert (gone.status_code, error_code(gone)) == (404, "not_found")


async def test_each_change_is_recorded(admin_client, sessionmaker):
    await admin_client.post(POLICIES, json=STALE)
    await admin_client.put(f"{POLICIES}/stale-snapshots", json={**CONTENT, "updated_days": 30})
    await admin_client.delete(f"{POLICIES}/stale-snapshots")

    created = await last(sessionmaker, "cleanup_policy.created")
    updated = await last(sessionmaker, "cleanup_policy.updated")
    deleted = await last(sessionmaker, "cleanup_policy.deleted")
    assert (created.target_kind, created.target_name) == ("cleanup_policy", "stale-snapshots")
    assert created.changes["updated_days"] == {"before": None, "after": 14}
    assert updated.changes == {"updated_days": {"before": 14, "after": 30}}
    assert deleted.changes["format"] == {"before": "maven", "after": None}


async def test_a_name_is_taken_whatever_its_case(admin_client):
    await admin_client.post(POLICIES, json=STALE)

    taken = await admin_client.post(POLICIES, json={**STALE, "name": "STALE-snapshots"})

    assert (taken.status_code, error_code(taken)) == (409, "conflict")


async def test_the_format_does_not_change(admin_client):
    await admin_client.post(POLICIES, json=STALE)

    moved = await admin_client.put(
        f"{POLICIES}/stale-snapshots", json={"format": "npm", "updated_days": 14}
    )
    kept = await admin_client.put(f"{POLICIES}/stale-snapshots", json=CONTENT)

    assert (moved.status_code, error_code(moved)) == (409, "immutable")
    assert kept.status_code == 200, kept.text


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"updated_days": None, "release_type": None}, "criteria"),
        ({"format": "raw"}, "release_type"),
        ({"asset_pattern": "(a+)+"}, "asset_pattern"),
        ({"format": "nothing", "release_type": None}, "format"),
        ({"downloaded_days": 0}, "downloaded_days"),
    ],
)
async def test_what_cannot_be_a_policy_is_refused_at_its_field(admin_client, changes, field):
    refused = await admin_client.post(POLICIES, json={**STALE, **changes})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")
    assert [detail["field"] for detail in refused.json()["error"]["details"]] == [field]


async def test_reading_needs_cleanup_read_and_changing_cleanup_write(
    admin_client, other_client, make_user, sessionmaker
):
    await admin_client.post(POLICIES, json=STALE)
    await make_role(sessionmaker, "cleanup-readers", "admin:cleanup:read")
    await make_user("rita", roles=["cleanup-readers"])
    await make_user("sam")
    rita, sam = basic("rita", PASSWORD), basic("sam", PASSWORD)
    one = f"{POLICIES}/stale-snapshots"

    client = other_client  # with no session of root's
    made = await client.post(POLICIES, json={**STALE, "name": "x"}, headers=rita)

    assert (await client.get(POLICIES, headers=rita)).status_code == 200
    assert (await client.get(one, headers=rita)).status_code == 200
    assert made.status_code == 403
    assert (await client.put(one, json=CONTENT, headers=rita)).status_code == 403
    assert (await client.delete(one, headers=rita)).status_code == 403
    assert (await client.get(POLICIES, headers=sam)).status_code == 403
