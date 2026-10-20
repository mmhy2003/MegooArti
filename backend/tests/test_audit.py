"""The audit log (spec 9): records written in the change's transaction, with who, how and
from where; read a page at a time, filtered, exported; kept the days an administrator
sets; and never changed through the API."""

import csv
import io
import json
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute

from megooarti.clock import utcnow
from megooarti.security import roles
from megooarti.system import audit, audit_api
from megooarti.system.models import AuditRecord
from tests.accounts import PASSWORD, basic, error_code
from tests.audit import last, records

AUDIT = "/api/v1/audit"
RETENTION = f"{AUDIT}/retention"


async def make_role(sessionmaker, name: str, *patterns: str) -> None:
    async with sessionmaker() as db:
        await roles.create_role(db, name, "", list(patterns), [])
        await db.commit()


async def write(sessionmaker, *entries: tuple[str, str, int]) -> None:
    """Records as the system writes them: (event, target's name, hours ago)."""
    now = utcnow()
    async with sessionmaker() as db:
        for event, name, hours in entries:
            entry = audit.record(db, event, ("user", name), {"status": {"before": 1, "after": 2}})
            entry.at = now - timedelta(hours=hours)
            entry.actor = "root" if name != "kim" else "kim"
        await db.commit()


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    """An administrator's credentials, sent with each request: a password signs nobody in
    for good, so no sign-in is recorded beside the records a test writes."""
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def test_a_change_is_recorded_with_who_made_it_how_and_from_where(admin_client, sessionmaker):
    changed = await admin_client.put(
        RETENTION, json={"audit_retention_days": 90}, headers={"X-Request-ID": "change-1"}
    )

    said = await last(sessionmaker, "setting.changed")
    assert changed.status_code == 200
    assert (said.actor, said.method, said.address, said.request_id) == (
        "root",
        "session",
        "127.0.0.1",
        "change-1",
    )
    assert (said.target_kind, said.target_name) == ("setting", "audit_retention_days")
    assert said.changes == {"audit_retention_days": {"before": 365, "after": 90}}


async def test_outside_a_request_the_system_made_it(sessionmaker):
    async with sessionmaker() as db:
        audit.record(db, "user.updated", ("user", "kim"))
        await db.commit()

    said = await last(sessionmaker, "user.updated")
    assert (said.actor, said.method, said.address, said.request_id) == (None, "system", None, None)


async def test_a_record_is_kept_with_its_change_or_not_at_all(sessionmaker):
    async with sessionmaker() as db:
        audit.record(db, "user.deleted", ("user", "kim"))
        await db.rollback()

    assert await records(sessionmaker, "user.deleted") == []


def test_what_changed_is_said_a_field_at_a_time_and_secrets_never():
    before = {"id": 1, "name": "kim", "email": "a@x", "roles": ["dev"], "created_at": "then"}
    after = {"id": 1, "name": "kim", "email": "b@x", "roles": ["dev", "ops"], "created_at": "now"}

    assert audit.diff(before, after, secrets=["bind_password"]) == {
        "email": {"before": "a@x", "after": "b@x"},
        "roles": {"before": ["dev"], "after": ["dev", "ops"]},
        "bind_password": {"before": "[redacted]", "after": "[redacted]"},
    }
    assert audit.diff(None, {"name": "kim"}) == {"name": {"before": None, "after": "kim"}}


async def test_a_secret_is_redacted_wherever_it_is_in_what_changed(sessionmaker):
    sent = {
        "proxy": {
            "before": None,
            "after": {"remote": {"auth": {"username": "ci", "password": "hunter2"}}},
        },
        "must_change_password": {"before": True, "after": False},
    }
    async with sessionmaker() as db:
        audit.record(db, "repository.updated", ("repository", "maven-central"), sent)
        await db.commit()

    said = await last(sessionmaker, "repository.updated")
    assert said.changes["proxy"]["after"]["remote"]["auth"] == {
        "username": "ci",
        "password": "[redacted]",
    }
    assert said.changes["must_change_password"] == {"before": True, "after": False}


async def test_the_records_are_listed_newest_first_and_filtered(client, root, sessionmaker):
    await write(
        sessionmaker,
        ("user.created", "kim", 30),
        ("user.updated", "kim", 20),
        ("role.created", "developers", 10),
        ("user.deleted", "lee", 1),
    )
    now = utcnow()

    every = (await client.get(AUDIT, headers=root, params={"limit": 3})).json()
    of_users = (await client.get(AUDIT, headers=root, params={"event": "user"})).json()
    created = (await client.get(AUDIT, headers=root, params={"event": "user.created"})).json()
    about_kim = (await client.get(AUDIT, headers=root, params={"target": "kim"})).json()
    by_kim = (await client.get(AUDIT, headers=root, params={"actor": "Kim"})).json()
    lately = (
        await client.get(
            AUDIT, headers=root, params={"since": (now - timedelta(hours=15)).isoformat()}
        )
    ).json()
    before = (
        await client.get(
            AUDIT, headers=root, params={"until": (now - timedelta(hours=15)).isoformat()}
        )
    ).json()

    def events(listed: dict) -> list[str]:
        return [entry["event"] for entry in listed["items"]]

    assert every["total"] == 4
    assert events(every) == ["user.deleted", "role.created", "user.updated"]
    assert events(of_users) == ["user.deleted", "user.updated", "user.created"]
    assert events(created) == ["user.created"]
    assert events(about_kim) == events(by_kim) == ["user.updated", "user.created"]
    assert events(lately) == ["user.deleted", "role.created"]
    assert events(before) == ["user.updated", "user.created"]
    assert every["items"][0]["changes"] == {"status": {"before": 1, "after": 2}}


async def test_a_day_alone_is_that_days_start_in_utc(client, root, sessionmaker):
    await write(sessionmaker, ("user.created", "kim", 1))
    today = utcnow().date()

    since_today = await client.get(AUDIT, headers=root, params={"since": today.isoformat()})
    until_today = await client.get(AUDIT, headers=root, params={"until": today.isoformat()})

    assert since_today.status_code == until_today.status_code == 200
    assert since_today.json()["total"] + until_today.json()["total"] == 1


async def test_the_records_are_exported_as_json_lines_or_csv(client, root, sessionmaker):
    await write(sessionmaker, ("user.created", "kim", 2), ("user.created", "=HYPERLINK(1)", 1))

    lines = await client.get(f"{AUDIT}/export", headers=root, params={"format": "jsonl"})
    table = await client.get(
        f"{AUDIT}/export", headers=root, params={"format": "csv", "target": "kim"}
    )

    exported = [json.loads(line) for line in lines.text.splitlines()]
    rows = list(csv.DictReader(io.StringIO(table.text)))
    assert lines.headers["content-type"].startswith("application/x-ndjson")
    assert 'filename="audit-' in lines.headers["content-disposition"]
    assert [entry["target_name"] for entry in exported] == ["=HYPERLINK(1)", "kim"]
    assert table.headers["content-type"].startswith("text/csv")
    assert [row["target_name"] for row in rows] == ["kim"]
    assert json.loads(rows[0]["changes"]) == {"status": {"after": 2, "before": 1}}


async def test_a_cell_a_spreadsheet_would_run_is_written_as_text(client, root, sessionmaker):
    await write(sessionmaker, ("sign_in.failed", "=HYPERLINK(1)", 1))

    table = await client.get(f"{AUDIT}/export", headers=root, params={"format": "csv"})

    assert list(csv.DictReader(io.StringIO(table.text)))[0]["target_name"] == "'=HYPERLINK(1)"


async def test_the_audit_needs_its_permissions(client, make_user, sessionmaker):
    await make_role(sessionmaker, "auditor", "admin:audit:read")
    await make_user("ada", roles=["auditor"])
    await make_user("sam")

    nobody = await client.get(AUDIT)
    sam = await client.get(AUDIT, headers=basic("sam", PASSWORD))
    sam_exports = await client.get(f"{AUDIT}/export", headers=basic("sam", PASSWORD))
    ada = await client.get(AUDIT, headers=basic("ada", PASSWORD))
    ada_exports = await client.get(f"{AUDIT}/export", headers=basic("ada", PASSWORD))
    ada_reads = await client.get(RETENTION, headers=basic("ada", PASSWORD))
    ada_sets = await client.put(
        RETENTION, json={"audit_retention_days": 1}, headers=basic("ada", PASSWORD)
    )

    assert (nobody.status_code, sam.status_code, sam_exports.status_code) == (401, 403, 403)
    assert (ada.status_code, ada_exports.status_code, ada_reads.status_code) == (200, 200, 200)
    assert ada_sets.status_code == 403
    assert ada_reads.json() == {"audit_retention_days": 365}


@pytest.mark.parametrize("days", [0, -1, 36501])
async def test_records_are_kept_at_least_a_day(admin_client, days):
    refused = await admin_client.put(RETENTION, json={"audit_retention_days": days})

    assert (refused.status_code, error_code(refused)) == (422, "validation_error")


def test_no_route_changes_or_deletes_a_record():
    audited = [
        (method, route.path)
        for route in audit_api.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    ]

    assert sorted(audited) == [
        ("GET", "/audit"),
        ("GET", "/audit/export"),
        ("GET", "/audit/retention"),
        ("PUT", "/audit/retention"),
    ]


async def test_records_older_than_the_days_kept_are_removed(admin_client, sessionmaker):
    await admin_client.put(RETENTION, json={"audit_retention_days": 30})
    await write(sessionmaker, ("user.created", "old", 24 * 31), ("user.created", "new", 24 * 29))

    async with sessionmaker() as db:
        removed = await audit.prune(db, utcnow())
        await db.commit()

    names = [entry.target_name for entry in await records(sessionmaker, "user.created")]
    assert (removed, names) == (1, ["new"])


async def test_the_hourly_job_removes_them(app, sessionmaker):
    await write(sessionmaker, ("user.created", "old", 24 * 366))

    await audit.prune_now(app)

    assert await records(sessionmaker, "user.created") == []
    assert isinstance(audit.LOCK_KEY, int) and audit.PRUNE_SECONDS == 3600
    assert AuditRecord.__tablename__ == "audit_records"
