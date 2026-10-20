# External Identity: The Audit Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every change of configuration or security, and every sign-in, is recorded with who made it, how they signed in, their address, what changed and the request's ID. The record is kept in the change's own transaction and never edited. An administrator reads, filters and exports the records, and sets how many days they are kept.

**Architecture:**
- **Recording.** `system/audit.py` holds `record(db, event, target, changes)`, which adds a row of `audit_records` to the caller's session; the row is kept when the caller's change commits.
- **The request's context.** `ContextMiddleware` keeps each request's ID and its client's address. Authentication adds who the caller is with `identified(principal)`.
- **What changed.** `diff(before, after, secrets=...)` says what changed, a field at a time, and never a secret's value.
- **Where records are written.** Tasks 2 to 4 add a `record` call beside each existing `log.info` of a change, and to sign-in.
- **Reading and keeping.** `system/audit_api.py` lists, exports and sets how long records are kept; an hourly job removes older ones.
- **The screen.** The web UI gets Administration, Audit log.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy and Alembic (PostgreSQL JSONB), structlog; Next.js, React, TanStack Query, Vitest.

**Spec:** [docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md](../specs/2026-10-19-identity-audit-selectors-design.md): section 9, with D3, E7, 11, 12, 14 and the row of plan 15f in 13; the "Settled" tables of 15a to 15e.

## Decisions this plan settles

Task 5 writes these into the spec, as "Settled while building plan 15f".

| # | Decision | Reason |
| --- | --- | --- |
| A1 | A record is a row of `audit_records` (id, at, actor, method, address, event, target_kind, target_name, changes as JSONB, request_id), indexed by time, actor, event, and target's kind and name. `system/audit.py`'s `record(db, event, target, changes)` adds it to the caller's session, kept by its commit (E7). | Section 9. |
| A2 | Who, how and from where come from the request: `audit.ContextMiddleware`, inside the request's ID and the proxies (15e), keeps the ID and the client's address; `audit.identified(principal)`, called where a principal is made (`_identify`, the MCP endpoint's, a session started), the user's name and how they signed in; `audit.acting(name, method)` where there is no principal (a package client signing in by password). Nobody identified: no actor, no method. Outside a request: `system`. | Section 9: the caller and the request from the request's context. |
| A3 | `method` is the principal's (`session`, `password`, `token`, `header`, `anonymous`), `oauth` for a token an application was given by a person's approval, `system` for the server's own work (the hourly directory check). | Section 9's list. |
| A4 | Events are `<kind>.<what happened>`: `user.created`, `user.updated`, `user.deleted`, `user.password_changed`, `role.*`, `token.created`, `token.revoked`, `connected_app.approved`, `connected_app.revoked`, `oauth_client.registered`, `source.*`, `setting.changed`, `certificate.trusted`, `certificate.removed`, `repository.*` with `cache_invalidated` and `index_rebuilt`, `signing_key.imported`, `signing_key.generated`, `blob_store.*`, `sign_in.succeeded`, `sign_in.failed`, `sign_in.throttled`, `sign_in.refused`, `session.signed_out`. A token is named `<user>/<token>`, an approval `<user>/<client>`. What a repository holds (uploads, deletes) is not configuration, and not recorded. | Section 9: the routes that log a change today, and sign-in. |
| A5 | `changes` is `audit.diff(before, after, secrets=...)`: each field that differs, as the API shows it, `{before, after}`; ids and times left out, and what is not configuration (a source's user count, a repository's remote status, a certificate's PEM). A secret given anew is said by its name, `[redacted]`; a field named as a secret is (`password`, `bind_password`, `client_secret`, `secret`, `private_key`, `passphrase`, `token`), wherever it is. | Section 9: a secret is `[redacted]`. |
| A6 | A setting is recorded by `audit.set_setting`, only when its value changes; the order of the sources is the setting `source_order`. | Section 9: `setting_changed`. |
| A7 | Sign-in: `sign_in.succeeded` when a session starts (a password, a provider), with its source; `sign_in.failed` at each failed check of a password, a token or a provider's answer, kept by a commit before the error is answered; `sign_in.throttled`; `sign_in.refused` for a trusted header from elsewhere; `session.signed_out`. A package client's password accepted at each request is not a sign-in, and not recorded; a client signing in for a token (`npm login`) is `token.created`. A first sign-in is `user.created`, and roles a source's groups give or take back are `user.updated` (`roles_from_groups`). | Section 9: succeeded, failed, throttled, by every source; D4's refresh. |
| A8 | `GET /api/v1/audit` filters by `since`, `until` (a time without its zone is UTC's), `actor`, `event` (an event, or a kind: `user`), `target` and `target_kind`; newest first. `GET /api/v1/audit/export?format=jsonl|csv` streams what the filters give, in a session of its own, 500 at a time; a CSV cell starting with `=`, `+`, `-`, `@`, a tab or a return is written after a `'`. | Section 9; a name typed at sign-in must not run in a spreadsheet. |
| A9 | `audit_retention_days` (365; 1 to 36500) is read and set at `/api/v1/audit/retention`: reading with `admin:audit:read`, setting with `admin:audit:write`, which no settings permission gives. The hourly job `audit_prune`, one container at a time, removes older records. No route changes or deletes a record. | D3; whoever may change settings must not be able to shorten the record of it. |
| A10 | The screen is Administration, Audit log, last: its filters in its address (a kind of event, who, about what, the days, in UTC, the last one included), its records a page at a time, each opening to what changed; the export of what the filters give; the days kept. The role editor's areas gain `security`, `certificates` and `audit`. | Section 9; 15a and 15c's areas were missing from the editor's lists. |

## Global Constraints

- **An audit record is written in the transaction of the change it records** (E7): no change without its record, and no record of a change that was rolled back.
- **A secret is `[redacted]`** (section 9); **no record is edited or deleted through the UI or the API** (D3).
- **Kept a number of days an administrator sets (365 unless set; at least 1), exported as JSON Lines or CSV** (D3).
- **`GET /api/v1/audit` (paged, filtered by time, actor, event and target; newest first) and `GET /api/v1/audit/export?format=jsonl|csv`, with `admin:audit:read`** (section 9). **Every new list is paged** (API-5).
- **Sign-in is recorded: succeeded, failed, throttled; by every source** (section 9). **MCP tools are recorded through the routes they call** (section 9).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database; `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

These are the failures that would hurt a person using this most, each with the test in this plan that pins it.

1. **A secret written into the log.** A source's client secret, a remote's password or a password set would sit in a table that more people read than the secret's owner. Each is said by its name as `[redacted]`. Pinned by Task 1's `test_a_secret_is_redacted_wherever_it_is_in_what_changed`, Task 2's `test_a_sources_secret_is_said_by_its_name_and_never_its_value`, and Task 4's `test_a_repository_made_changed_and_deleted_is_recorded_without_its_secret`.
2. **A failed sign-in lost with its failed request.** The 401 rolls nothing back that was kept: the record is committed before the error is answered. Pinned by Task 3's `test_a_wrong_password_is_recorded_though_the_request_fails`.
3. **A name typed at sign-in (`=HYPERLINK(...)`) that runs when the CSV export is opened in a spreadsheet.** It is written as text. Pinned by Task 1's `test_a_cell_a_spreadsheet_would_run_is_written_as_text`.
4. **A change that was refused, still recorded as made.** No record without the change. Pinned by Task 1's `test_a_record_is_kept_with_its_change_or_not_at_all` and Task 2's `test_a_change_that_is_refused_leaves_no_record`.
5. **Whoever may change settings shortening the log to hide what they did.** The days kept need `admin:audit:write`, and their change is a record of its own. Pinned by Task 1's `test_the_audit_needs_its_permissions` and `test_a_change_is_recorded_with_who_made_it_how_and_from_where`.

---

### Task 1: The audit log: records, their context, reading, export and how long they are kept

**Files:**
- Create: `backend/src/megooarti/system/audit.py`, `backend/src/megooarti/system/audit_api.py`, `backend/src/megooarti/migrations/versions/0012_add_audit_records.py`
- Modify: `backend/src/megooarti/system/models.py`, `backend/src/megooarti/system/settings_store.py`, `backend/src/megooarti/security/authentication.py`, `backend/src/megooarti/main.py`, `docs/administration.md` (the permission's row), `frontend/openapi.json` (written by the snapshot test with `MEGOOARTI_UPDATE_OPENAPI=1`)
- Test: `backend/tests/audit.py` (what the log holds, for the tests of every task), `backend/tests/test_audit.py`; modify `backend/tests/test_settings_store.py`

**Interfaces:**
- Consumes: 15e's `ProxiesMiddleware` (the client's address) and `RequestIdMiddleware`; `Principal` (`is_anonymous`, `grant_id`, `method`, `user`); `settings_store`; `maintenance.run_periodically`, `run_exclusively`; `pagination`.
- Produces:
  - Recording:
    - `audit.record(db, event: str, target: tuple[str, str] | None = None, changes: Mapping | None = None) -> AuditRecord` (synchronous: it adds the row to the caller's session).
    - `audit.diff(before, after, *, secrets: Iterable[str] = ()) -> dict`, and `audit.REDACTED`.
    - `audit.set_setting(db, key, value)`, which keeps a setting and records the change.
  - The request's context: `audit.identified(principal)`, `audit.acting(actor, method)` and `audit.ContextMiddleware`.
  - Keeping: `audit.prune(db, now) -> int`, `audit.prune_now(app)`, `audit.PRUNE_SECONDS`, `audit.LOCK_KEY`.
  - The model `AuditRecord`; the setting `audit_retention_days`; the permissions `admin:audit:read` and `admin:audit:write`.
  - Routes: `GET /api/v1/audit`, `GET /api/v1/audit/export`, `GET` and `PUT /api/v1/audit/retention`.
  - For tests: `tests.audit.records(sessionmaker, event=None)` and `tests.audit.last(sessionmaker, event)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/audit.py`:

```python
"""What the audit log holds, for the tests of the changes that write it (spec 12)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.system.models import AuditRecord


async def records(
    sessionmaker: async_sessionmaker[AsyncSession], event: str | None = None
) -> list[AuditRecord]:
    """The records, oldest first: of one event, or all of them."""
    query = select(AuditRecord).order_by(AuditRecord.at, AuditRecord.id)
    if event is not None:
        query = query.where(AuditRecord.event == event)
    async with sessionmaker() as db:
        return list(await db.scalars(query))


async def last(sessionmaker: async_sessionmaker[AsyncSession], event: str) -> AuditRecord:
    """The newest record of an event; fails the test if there is none."""
    found = await records(sessionmaker, event)
    assert found, f"no {event} record"
    return found[-1]
```

Create `backend/tests/test_audit.py`:

```python
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
```

Change `backend/tests/test_settings_store.py`:

```diff
@@ -9,12 +9,14 @@ async def test_defaults_apply_when_nothing_is_stored(db):
     assert await get_setting(db, "default_role") is None
     assert await get_setting(db, "local_sign_in") == {"enabled": True}
     assert await get_setting(db, "trusted_proxies") == []
+    assert await get_setting(db, "audit_retention_days") == 365
     assert set(DEFAULTS) == {
         "base_url",
         "anonymous_access",
         "default_role",
         "local_sign_in",
         "trusted_proxies",
+        "audit_retention_days",
     }
 
 
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/test_audit.py tests/test_settings_store.py`
Expected: The tests do not load: `ImportError: cannot import name 'audit' from 'megooarti.system'`.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/system/models.py`:

```diff
@@ -4,7 +4,7 @@ import uuid
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import DateTime, String, Text, func
+from sqlalchemy import DateTime, Index, String, Text, func
 from sqlalchemy.dialects.postgresql import JSONB
 from sqlalchemy.orm import Mapped, mapped_column
 
@@ -37,3 +37,25 @@ class TrustedCertificate(Base):
     pem: Mapped[str] = mapped_column(Text)
     added_by: Mapped[str] = mapped_column(String(64))  # the name, which outlives the user
     added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
+
+
+class AuditRecord(Base):
+    """A change of configuration or security, or a sign-in, as it happened (spec 9). Never
+    changed; removed when older than the days kept."""
+
+    __tablename__ = "audit_records"
+    __table_args__ = (Index("ix_audit_records_target", "target_kind", "target_name"),)
+
+    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
+    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
+    # Who, by their name, which outlives the user; none when nobody was signed in.
+    actor: Mapped[str | None] = mapped_column(String(128), index=True)
+    # How they signed in: session, password, token, oauth, header, anonymous, or system.
+    method: Mapped[str | None] = mapped_column(String(16))
+    address: Mapped[str | None] = mapped_column(String(45))
+    event: Mapped[str] = mapped_column(String(64), index=True)
+    target_kind: Mapped[str | None] = mapped_column(String(32))
+    target_name: Mapped[str | None] = mapped_column(String(255))
+    # Each changed field's before and after; a secret's are "[redacted]".
+    changes: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
+    request_id: Mapped[str | None] = mapped_column(String(64))
```

Create `backend/src/megooarti/migrations/versions/0012_add_audit_records.py`:

```python
"""add the audit log's records

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("address", sa.String(length=45), nullable=True),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_records")),
    )
    op.create_index(op.f("ix_audit_records_at"), "audit_records", ["at"])
    op.create_index(op.f("ix_audit_records_actor"), "audit_records", ["actor"])
    op.create_index(op.f("ix_audit_records_event"), "audit_records", ["event"])
    op.create_index("ix_audit_records_target", "audit_records", ["target_kind", "target_name"])


def downgrade() -> None:
    op.drop_table("audit_records")
```

Change `backend/src/megooarti/system/settings_store.py`:

```diff
@@ -16,6 +16,8 @@ DEFAULTS: dict[str, Any] = {
     # The proxies in front of the gateway whose X-Forwarded-For is believed, and whose
     # trusted header signs people in (spec 8): addresses and networks (CIDR).
     "trusted_proxies": [],
+    # How many days the audit log keeps a record (D3): at least one.
+    "audit_retention_days": 365,
 }
 
 
```

Create `backend/src/megooarti/system/audit.py`:

```python
"""The audit log (spec 9): who changed what, when, from where, and how they signed in.

A record is written by `record`, in the transaction of the change it records (E7): the
change and its record are kept together, or neither is. Who made it, how they signed in,
their address and the request's ID come from the request being served (`Context`, set by
`ContextMiddleware` and completed by `identified`); outside a request, it is the system's.
No record is ever changed; the hourly job removes those older than the days kept (D3).
"""

import uuid
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from megooarti.clock import utcnow
from megooarti.system import settings_store
from megooarti.system.models import AuditRecord
from megooarti.system.settings_store import get_setting

if TYPE_CHECKING:
    from megooarti.security.authentication import Principal

log = structlog.get_logger(__name__)

REDACTED = "[redacted]"
SYSTEM = "system"
PRUNE_SECONDS = 3600
# Arbitrary constant, distinct from the other advisory lock keys.
LOCK_KEY = 0x4D45474F53
# What a record never holds, wherever it is in what changed: secrets, by their names.
_SECRET_NAMES = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "bind_password",
        "secret",
        "client_secret",
        "private_key",
        "passphrase",
        "token",
    }
)
# What changes with every save, or is the record's own: not what anyone changed.
_UNTOLD = frozenset({"id", "created_at", "updated_at", "last_login_at", "last_used_at"})


@dataclass
class Context:
    """The request a record is written for. Who made it is known once they are identified."""

    request_id: str | None
    address: str | None
    actor: str | None = None
    method: str | None = None


_context: ContextVar[Context | None] = ContextVar("megooarti_audit", default=None)


class ContextMiddleware:
    """Each HTTP request's context, for the records written while it is served. Placed
    inside the middleware that sets the request's ID and its client's address."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        token = _context.set(
            Context(
                request_id=scope.get("state", {}).get("request_id"),
                address=client[0] if client else None,
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _context.reset(token)


def acting(actor: str | None, method: str | None) -> None:
    """Who the request being served is from, for its records, and how they signed in."""
    said = _context.get()
    if said is not None:
        said.actor, said.method = actor, method


def identified(principal: "Principal | None") -> None:
    """Who a principal is, for the records: the user's name (none when anonymous), and
    how they signed in (`oauth` for an application's token a person approved)."""
    if principal is None:
        return
    acting(
        None if principal.is_anonymous else principal.user.username,
        "oauth" if principal.grant_id is not None else principal.method,
    )


def _plain(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    plain = jsonable_encoder(value)
    return plain if isinstance(plain, dict) else {"value": plain}


def _hidden(value: Any) -> Any:
    """A secret's value, redacted: a change of one keeps its shape, each side redacted."""
    if isinstance(value, Mapping) and set(value) == {"before", "after"}:
        return {side: None if value[side] is None else REDACTED for side in ("before", "after")}
    return None if value is None else REDACTED


def _redacted(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _hidden(item) if key in _SECRET_NAMES else _redacted(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    return value


def diff(before: Any, after: Any, *, secrets: Iterable[str] = ()) -> dict[str, Any]:
    """What changed, a field at a time: `{field: {"before": ..., "after": ...}}`. Either
    side may be None (made, or deleted), a mapping, a model or a dataclass. A secret given
    anew is said by its name, its values redacted: they are never known to the record."""
    old, new = _plain(before), _plain(after)
    changed = {
        name: {"before": old.get(name), "after": new.get(name)}
        for name in sorted((old.keys() | new.keys()) - _UNTOLD)
        if old.get(name) != new.get(name)
    }
    for name in secrets:
        changed[name] = {"before": REDACTED, "after": REDACTED}
    return changed


def record(
    db: AsyncSession,
    event: str,
    target: tuple[str, str] | None = None,
    changes: Mapping[str, Any] | None = None,
) -> AuditRecord:
    """Write a record in the caller's transaction: kept when it commits, with the change.

    `event` is `<kind>.<what happened>` (`user.created`, `sign_in.failed`); `target` is
    what it happened to, by its kind and its name."""
    said = _context.get()
    entry = AuditRecord(
        id=uuid.uuid4(),
        at=utcnow(),
        actor=None if said is None else said.actor,
        method=SYSTEM if said is None else said.method,
        address=None if said is None else said.address,
        event=event,
        target_kind=None if target is None else target[0],
        target_name=None if target is None else target[1][:255],
        changes=_redacted(jsonable_encoder(dict(changes))) if changes else None,
        request_id=None if said is None else said.request_id,
    )
    db.add(entry)
    return entry


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Keep a setting's value, with a record of the change when it is one."""
    before = await get_setting(db, key)
    await settings_store.set_setting(db, key, value)
    after = await get_setting(db, key)
    if after != before:
        record(db, "setting.changed", ("setting", key), diff({key: before}, {key: after}))


async def prune(db: AsyncSession, now: datetime) -> int:
    """Remove the records older than the days kept; how many were removed."""
    days = await get_setting(db, "audit_retention_days")
    removed = await db.execute(
        delete(AuditRecord).where(AuditRecord.at < now - timedelta(days=days))
    )
    return removed.rowcount or 0


async def prune_now(app: Any) -> None:
    """The hourly job: run by one container at a time (`LOCK_KEY`)."""
    async with app.state.sessionmaker() as db:
        removed = await prune(db, utcnow())
        await db.commit()
    if removed:
        log.info("audit_pruned", removed=removed)
```

Create `backend/src/megooarti/system/audit_api.py`:

```python
"""The audit log's records, read a page at a time and exported (spec 9). No route changes
or deletes a record: only how many days they are kept is changed here."""

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.pagination import Page, PageParams, page
from megooarti.security.authentication import Principal, require
from megooarti.system import audit
from megooarti.system.models import AuditRecord
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

_COLUMNS = (
    "at",
    "actor",
    "method",
    "address",
    "event",
    "target_kind",
    "target_name",
    "changes",
    "request_id",
    "id",
)
# A spreadsheet takes a cell that starts so for a formula: a name someone typed is not one.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


class AuditRecordOut(BaseModel):
    id: uuid.UUID
    at: datetime
    actor: str | None
    method: str | None
    address: str | None
    event: str
    target_kind: str | None
    target_name: str | None
    changes: dict[str, Any] | None
    request_id: str | None


class Retention(BaseModel):
    audit_retention_days: int = Field(ge=1, le=36500)


def _utc(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


class Filters:
    """Which records: from and until a time, by whom, of which event (`user.created`, or
    every event of a kind, `user`), and about what (its name, and its kind)."""

    def __init__(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        actor: Annotated[str | None, Query(max_length=128)] = None,
        event: Annotated[str | None, Query(max_length=64)] = None,
        target: Annotated[str | None, Query(max_length=255)] = None,
        target_kind: Annotated[str | None, Query(max_length=32)] = None,
    ) -> None:
        # A time without its zone is UTC's, as a date alone is that day's start there.
        self.since, self.until = _utc(since), _utc(until)
        self.actor, self.event = actor, event
        self.target, self.target_kind = target, target_kind

    def where(self) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if self.since is not None:
            found.append(AuditRecord.at >= self.since)
        if self.until is not None:
            found.append(AuditRecord.at < self.until)
        if self.actor:
            found.append(AuditRecord.actor == self.actor.strip().lower())
        if self.event:
            event = self.event.strip()
            found.append(or_(AuditRecord.event == event, AuditRecord.event.startswith(f"{event}.")))
        if self.target:
            found.append(AuditRecord.target_name == self.target.strip())
        if self.target_kind:
            found.append(AuditRecord.target_kind == self.target_kind.strip())
        return found

    def select(self) -> Select[tuple[AuditRecord]]:
        return (
            select(AuditRecord)
            .where(*self.where())
            .order_by(AuditRecord.at.desc(), AuditRecord.id.desc())
        )


def _out(entry: AuditRecord) -> AuditRecordOut:
    return AuditRecordOut.model_validate(entry, from_attributes=True)


@router.get("", response_model=Page[AuditRecordOut])
async def list_records(
    filters: Filters = Depends(),
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:audit:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The records, newest first, a page at a time."""
    total = await db.scalar(select(func.count()).select_from(AuditRecord).where(*filters.where()))
    found = await db.scalars(filters.select().limit(params.limit).offset(params.offset))
    return page([_out(entry) for entry in found], total or 0, params)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)
    return f"'{text}" if text.startswith(_FORMULA) else text


def _line(entry: AuditRecordOut, format: str) -> str:
    plain = entry.model_dump(mode="json")
    if format == "jsonl":
        return json.dumps(plain, sort_keys=True) + "\n"
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow([_cell(plain[name]) for name in _COLUMNS])
    return out.getvalue()


@router.get("/export")
async def export_records(
    request: Request,
    format: Literal["jsonl", "csv"] = "jsonl",
    filters: Filters = Depends(),
    _: Principal = Depends(require("admin:audit:read")),
) -> StreamingResponse:
    """Every record the filters give, newest first, as JSON Lines or CSV: streamed, a
    record a line, however many there are."""

    async def lines() -> AsyncIterator[str]:
        if format == "csv":
            yield ",".join(_COLUMNS) + "\n"
        # Its own session: the request's is closed before the body is sent.
        async with request.app.state.sessionmaker() as db:
            found = await db.stream_scalars(filters.select().execution_options(yield_per=500))
            async for entry in found:
                yield _line(_out(entry), format)

    named = f"audit-{utcnow():%Y%m%d-%H%M%S}.{format}"
    return StreamingResponse(
        lines(),
        media_type="text/csv" if format == "csv" else "application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{named}"'},
    )


@router.get("/retention", response_model=Retention)
async def read_retention(
    _: Principal = Depends(require("admin:audit:read")),
    db: AsyncSession = Depends(get_session),
) -> Retention:
    return Retention(audit_retention_days=await get_setting(db, "audit_retention_days"))


@router.put("/retention", response_model=Retention)
async def set_retention(
    body: Retention,
    principal: Principal = Depends(require("admin:audit:write")),
    db: AsyncSession = Depends(get_session),
) -> Retention:
    """How many days a record is kept: the hourly job removes older ones."""
    await audit.set_setting(db, "audit_retention_days", body.audit_retention_days)
    await db.commit()
    log.info(
        "setting_changed",
        setting="audit_retention_days",
        days=body.audit_retention_days,
        by=principal.user.username,
    )
    return body
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -30,6 +30,7 @@ from megooarti.security.keys import TOKEN_PREFIX
 from megooarti.security.models import ApiToken, User, UserSession
 from megooarti.security.passwords import hash_password, needs_rehash, verify_password
 from megooarti.security.permissions import any_grants, is_valid_permission
+from megooarti.system import audit
 from megooarti.system.settings_store import get_setting
 
 log = structlog.get_logger(__name__)
@@ -501,6 +502,7 @@ async def _identify(
             raise
         raise unauthorized(error.message, scheme=scheme) from None
     await db.commit()  # last-seen times, cleared failure counts, upgraded password hashes
+    audit.identified(principal)
     if principal is not None and principal.method == "header" and request.method in _UNSAFE_METHODS:
         # No CSRF token without a session: a change must come from this server's own pages.
         await _require_same_origin(request, db)
@@ -617,6 +619,7 @@ async def agent_principal(request: Request, db: AsyncSession = Depends(get_sessi
             }
         raise
     await db.commit()  # when the token, or the approval, was last used
+    audit.identified(principal)
     return principal
 
 
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -49,7 +49,8 @@ from megooarti.security.api import users as users_api
 from megooarti.security.bootstrap import ensure_initial_admin_password
 from megooarti.storage import blobs
 from megooarti.storage.api import router as blob_stores_router
-from megooarti.system import certificates
+from megooarti.system import audit, certificates
+from megooarti.system.audit_api import router as audit_router
 from megooarti.system.certificates_api import router as certificates_router
 from megooarti.system.information_api import router as information_router
 from megooarti.system.settings_api import router as settings_router
@@ -129,6 +130,18 @@ async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
             )
         )
     )
+    # The audit log's records older than the days kept are removed (spec 9, D3).
+    background.append(
+        asyncio.create_task(
+            run_periodically(
+                "audit_prune",
+                audit.PRUNE_SECONDS,
+                lambda: run_exclusively(
+                    app.state.engine, audit.LOCK_KEY, lambda: audit.prune_now(app)
+                ),
+            )
+        )
+    )
     if settings.compaction_interval_seconds > 0:
         background.append(
             asyncio.create_task(
@@ -191,6 +204,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(settings_router, prefix=API_PREFIX)
     app.include_router(information_router, prefix=API_PREFIX)
     app.include_router(certificates_router, prefix=API_PREFIX)
+    app.include_router(audit_router, prefix=API_PREFIX)
     app.include_router(blob_stores_router, prefix=API_PREFIX)
     app.include_router(repositories_router, prefix=API_PREFIX)
     app.include_router(content_api_router, prefix=API_PREFIX)
@@ -208,6 +222,9 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     # first, so its 500 response passes through every other middleware, and keep
     # RequestIdMiddleware last, so everything else runs with a request ID.
     app.add_middleware(UnhandledErrorMiddleware)
+    # Each request's context for the audit log's records: its ID and its client's address,
+    # so it runs inside the two below.
+    app.add_middleware(audit.ContextMiddleware)
     # Who a request comes from, before anything reads it.
     app.add_middleware(
         ProxiesMiddleware,
```

Change `docs/administration.md`:

```diff
@@ -251,6 +251,7 @@ area's name alone gives both.
 | `admin:settings` | The base URL and anonymous access; to read, also what is running (`/api/v1/system/information`) |
 | `admin:security` | How people sign in: the sign-in sources and their order, the default role, and whether MegooArti's own users sign in |
 | `admin:certificates` | The certificates outbound TLS trusts besides the usual authorities; to write, also fetching what a host presents |
+| `admin:audit` | The audit log: to read, its records and their export; to write, how many days they are kept |
 
 What a repository holds is not given by these, but by `repository:` permissions:
 see [Repositories](repositories.md). Whoever may change roles, or the roles a user
```

Change `frontend/openapi.json`:

```diff
@@ -160,6 +160,116 @@
         "title": "AssetView",
         "type": "object"
       },
+      "AuditRecordOut": {
+        "properties": {
+          "actor": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Actor"
+          },
+          "address": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Address"
+          },
+          "at": {
+            "format": "date-time",
+            "title": "At",
+            "type": "string"
+          },
+          "changes": {
+            "anyOf": [
+              {
+                "additionalProperties": true,
+                "type": "object"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Changes"
+          },
+          "event": {
+            "title": "Event",
+            "type": "string"
+          },
+          "id": {
+            "format": "uuid",
+            "title": "Id",
+            "type": "string"
+          },
+          "method": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Method"
+          },
+          "request_id": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Request Id"
+          },
+          "target_kind": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Target Kind"
+          },
+          "target_name": {
+            "anyOf": [
+              {
+                "type": "string"
+              },
+              {
+                "type": "null"
+              }
+            ],
+            "title": "Target Name"
+          }
+        },
+        "required": [
+          "id",
+          "at",
+          "actor",
+          "method",
+          "address",
+          "event",
+          "target_kind",
+          "target_name",
+          "changes",
+          "request_id"
+        ],
+        "title": "AuditRecordOut",
+        "type": "object"
+      },
       "BaseUrl": {
         "properties": {
           "base_url": {
@@ -1056,6 +1166,37 @@
         "title": "Order",
         "type": "object"
       },
+      "Page_AuditRecordOut_": {
+        "properties": {
+          "items": {
+            "items": {
+              "$ref": "#/components/schemas/AuditRecordOut"
+            },
+            "title": "Items",
+            "type": "array"
+          },
+          "limit": {
+            "title": "Limit",
+            "type": "integer"
+          },
+          "offset": {
+            "title": "Offset",
+            "type": "integer"
+          },
+          "total": {
+            "title": "Total",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "items",
+          "total",
+          "limit",
+          "offset"
+        ],
+        "title": "Page[AuditRecordOut]",
+        "type": "object"
+      },
       "Page_BlobStoreOut_": {
         "properties": {
           "items": {
@@ -2066,6 +2207,21 @@
         "title": "Result",
         "type": "object"
       },
+      "Retention": {
+        "properties": {
+          "audit_retention_days": {
+            "maximum": 36500.0,
+            "minimum": 1.0,
+            "title": "Audit Retention Days",
+            "type": "integer"
+          }
+        },
+        "required": [
+          "audit_retention_days"
+        ],
+        "title": "Retention",
+        "type": "object"
+      },
       "RoleContent": {
         "properties": {
           "description": {
@@ -3223,6 +3379,384 @@
   },
   "openapi": "3.1.0",
   "paths": {
+    "/api/v1/audit": {
+      "get": {
+        "description": "The records, newest first, a page at a time.",
+        "operationId": "list_records_api_v1_audit_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "since",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "format": "date-time",
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Since"
+            }
+          },
+          {
+            "in": "query",
+            "name": "until",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "format": "date-time",
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Until"
+            }
+          },
+          {
+            "in": "query",
+            "name": "actor",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 128,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Actor"
+            }
+          },
+          {
+            "in": "query",
+            "name": "event",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 64,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Event"
+            }
+          },
+          {
+            "in": "query",
+            "name": "target",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 255,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Target"
+            }
+          },
+          {
+            "in": "query",
+            "name": "target_kind",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 32,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Target Kind"
+            }
+          },
+          {
+            "in": "query",
+            "name": "limit",
+            "required": false,
+            "schema": {
+              "default": 50,
+              "maximum": 200,
+              "minimum": 1,
+              "title": "Limit",
+              "type": "integer"
+            }
+          },
+          {
+            "in": "query",
+            "name": "offset",
+            "required": false,
+            "schema": {
+              "default": 0,
+              "minimum": 0,
+              "title": "Offset",
+              "type": "integer"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Page_AuditRecordOut_"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "List Records",
+        "tags": [
+          "audit"
+        ]
+      }
+    },
+    "/api/v1/audit/export": {
+      "get": {
+        "description": "Every record the filters give, newest first, as JSON Lines or CSV: streamed, a\nrecord a line, however many there are.",
+        "operationId": "export_records_api_v1_audit_export_get",
+        "parameters": [
+          {
+            "in": "query",
+            "name": "format",
+            "required": false,
+            "schema": {
+              "default": "jsonl",
+              "enum": [
+                "jsonl",
+                "csv"
+              ],
+              "title": "Format",
+              "type": "string"
+            }
+          },
+          {
+            "in": "query",
+            "name": "since",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "format": "date-time",
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Since"
+            }
+          },
+          {
+            "in": "query",
+            "name": "until",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "format": "date-time",
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Until"
+            }
+          },
+          {
+            "in": "query",
+            "name": "actor",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 128,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Actor"
+            }
+          },
+          {
+            "in": "query",
+            "name": "event",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 64,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Event"
+            }
+          },
+          {
+            "in": "query",
+            "name": "target",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 255,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Target"
+            }
+          },
+          {
+            "in": "query",
+            "name": "target_kind",
+            "required": false,
+            "schema": {
+              "anyOf": [
+                {
+                  "maxLength": 32,
+                  "type": "string"
+                },
+                {
+                  "type": "null"
+                }
+              ],
+              "title": "Target Kind"
+            }
+          }
+        ],
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {}
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Export Records",
+        "tags": [
+          "audit"
+        ]
+      }
+    },
+    "/api/v1/audit/retention": {
+      "get": {
+        "operationId": "read_retention_api_v1_audit_retention_get",
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Retention"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Read Retention",
+        "tags": [
+          "audit"
+        ]
+      },
+      "put": {
+        "description": "How many days a record is kept: the hourly job removes older ones.",
+        "operationId": "set_retention_api_v1_audit_retention_put",
+        "requestBody": {
+          "content": {
+            "application/json": {
+              "schema": {
+                "$ref": "#/components/schemas/Retention"
+              }
+            }
+          },
+          "required": true
+        },
+        "responses": {
+          "200": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/Retention"
+                }
+              }
+            },
+            "description": "Successful Response"
+          },
+          "default": {
+            "content": {
+              "application/json": {
+                "schema": {
+                  "$ref": "#/components/schemas/ErrorResponse"
+                }
+              }
+            },
+            "description": "Any error."
+          }
+        },
+        "summary": "Set Retention",
+        "tags": [
+          "audit"
+        ]
+      }
+    },
     "/api/v1/auth-sources": {
       "get": {
         "description": "The sources, in the order they are asked, after MegooArti's own users.",
```

Then (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest -q tests/test_openapi_snapshot.py`, which writes `frontend/openapi.json` as above.

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/test_audit.py tests/test_settings_store.py tests/test_migrations.py tests/test_db_script.py tests/test_route_guards.py tests/test_app.py tests/test_openapi_snapshot.py tests/test_documents.py tests/security tests/mcp`
Expected: 752 passed.

- [ ] **Step 5: Commit**

```bash
git add backend docs frontend/openapi.json
git commit -m "feat(audit): records of changes in the change's own transaction, with who, how and from where; read, filtered and exported; kept the days an administrator sets"
```

---

### Task 2: The security routes write their records

**Files:**
- Modify:
  - `backend/src/megooarti/security/api/users.py`, `backend/src/megooarti/security/api/me.py`, `backend/src/megooarti/security/api/roles.py`, `backend/src/megooarti/security/api/sources.py`, `backend/src/megooarti/security/api/oauth.py`
  - `backend/src/megooarti/security/tokens.py` and `backend/src/megooarti/security/oauth.py` (revoking says what it revoked)
  - `backend/src/megooarti/security/sources.py` (a first sign-in, and the roles groups give)
  - `backend/src/megooarti/security/client_login.py`, `backend/src/megooarti/security/directory_check.py`
  - `backend/src/megooarti/system/settings_api.py`, `backend/src/megooarti/system/certificates_api.py`
- Test: `backend/tests/security/test_audit_records.py`, `backend/tests/mcp/test_audit_records.py`; modify `backend/tests/repositories/test_client_login.py`

**Interfaces:**
- Consumes: Task 1's `audit.record`, `audit.diff`, `audit.set_setting`, `audit.acting`, `tests.audit`.
- Produces:
  - `tokens.revoke_token(...) -> str` (the token's name) and `oauth.revoke(...) -> str` (the client's name).
  - The events `user.*`, `role.*`, `token.*`, `connected_app.*`, `oauth_client.registered`, `source.*`, `setting.changed`, `certificate.*`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_audit_records.py`:

```python
"""What the security routes write to the audit log (spec 9): every change of users,
roles, tokens, sources, settings and certificates, by whom, with what changed, and never
a secret; and what the server changes itself, as the system."""

from sqlalchemy import select

from megooarti.security import directory_check, roles
from megooarti.security.models import User
from tests.accounts import PASSWORD, basic, sign_in
from tests.audit import last, records
from tests.tls import authority

USERS = "/api/v1/users"
ROLES = "/api/v1/roles"
SOURCES = "/api/v1/auth-sources"
SETTINGS = "/api/v1/settings"


async def user_id(sessionmaker, username: str) -> str:
    async with sessionmaker() as db:
        return str(await db.scalar(select(User.id).where(User.username == username)))


async def test_a_user_made_changed_and_deleted_is_recorded_with_what_changed(
    admin_client, sessionmaker
):
    made = await admin_client.post(
        USERS,
        json={"username": "kim", "display_name": "Kim", "password": PASSWORD, "roles": []},
    )
    kim = made.json()["id"]
    await admin_client.patch(f"{USERS}/{kim}", json={"email": "kim@corp.example"})
    await admin_client.put(f"{USERS}/{kim}/password", json={"password": "another one entirely"})
    await admin_client.delete(f"{USERS}/{kim}")

    created = await last(sessionmaker, "user.created")
    updated = await last(sessionmaker, "user.updated")
    password = await last(sessionmaker, "user.password_changed")
    deleted = await last(sessionmaker, "user.deleted")
    assert (created.actor, created.method, created.target_name) == ("root", "session", "kim")
    assert created.changes["display_name"] == {"before": None, "after": "Kim"}
    assert "id" not in created.changes and "password" not in created.changes
    assert updated.changes == {"email": {"before": None, "after": "kim@corp.example"}}
    assert password.changes == {"password": {"before": "[redacted]", "after": "[redacted]"}}
    assert deleted.changes["username"] == {"before": "kim", "after": None}


async def test_a_change_that_is_refused_leaves_no_record(admin_client, sessionmaker):
    root = await user_id(sessionmaker, "root")

    refused = await admin_client.patch(f"{USERS}/{root}", json={"status": "disabled"})

    assert refused.status_code == 409
    assert await records(sessionmaker, "user.updated") == []


async def test_ones_own_password_and_tokens_are_recorded(client, make_user, sessionmaker):
    await make_user("kim")
    await sign_in(client, "kim")

    await client.put(
        "/api/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "another one entirely"},
    )
    token = (
        await client.post(
            "/api/v1/me/tokens", json={"name": "ci", "scopes": ["repository:*:*:read"]}
        )
    ).json()
    await client.delete(f"/api/v1/me/tokens/{token['id']}")

    password = await last(sessionmaker, "user.password_changed")
    created = await last(sessionmaker, "token.created")
    revoked = await last(sessionmaker, "token.revoked")
    assert (password.actor, password.target_name) == ("kim", "kim")
    assert (created.target_kind, created.target_name) == ("token", "kim/ci")
    assert created.changes == {"scopes": {"before": None, "after": ["repository:*:*:read"]}}
    assert (revoked.actor, revoked.target_name) == ("kim", "kim/ci")
    assert token["token"] not in str(created.changes)


async def test_an_administrator_revoking_someones_token_is_recorded(
    admin_client, make_user, make_token, sessionmaker
):
    kim = await make_user("kim")
    await make_token(kim, "deploy")
    listed = await admin_client.get(f"{USERS}/{kim.id}/tokens")

    await admin_client.delete(f"{USERS}/{kim.id}/tokens/{listed.json()['items'][0]['id']}")

    revoked = await last(sessionmaker, "token.revoked")
    assert (revoked.actor, revoked.target_name) == ("root", "kim/deploy")


async def test_a_role_made_changed_and_deleted_is_recorded(admin_client, sessionmaker):
    role = {"name": "developers", "description": "", "permissions": [], "roles": []}
    await admin_client.post(ROLES, json=role)
    await admin_client.put(
        f"{ROLES}/developers",
        json={"description": "Devs", "permissions": ["repository:*:*:read"], "roles": []},
    )
    await admin_client.delete(f"{ROLES}/developers")

    updated = await last(sessionmaker, "role.updated")
    assert (await last(sessionmaker, "role.created")).target_name == "developers"
    assert updated.changes == {
        "description": {"before": "", "after": "Devs"},
        "permissions": {"before": [], "after": ["repository:*:*:read"]},
    }
    assert (await last(sessionmaker, "role.deleted")).target_name == "developers"


async def test_a_sources_secret_is_said_by_its_name_and_never_its_value(admin_client, sessionmaker):
    source = {
        "kind": "oidc",
        "name": "Corp SSO",
        "settings": {
            "issuer": "https://sso.corp.example",
            "client_id": "megooarti",
            "client_secret": "s3cr3t-value",
        },
    }
    made = (await admin_client.post(SOURCES, json=source)).json()
    await admin_client.put(
        f"{SOURCES}/{made['id']}",
        json={
            "name": "Corp SSO",
            "enabled": True,
            "settings": {**source["settings"], "client_secret": "an0ther-value"},
        },
    )
    await admin_client.delete(f"{SOURCES}/{made['id']}")

    created = await last(sessionmaker, "source.created")
    updated = await last(sessionmaker, "source.updated")
    every = str([entry.changes for entry in await records(sessionmaker)])
    assert created.changes["client_secret"] == {"before": "[redacted]", "after": "[redacted]"}
    assert created.changes["kind"] == {"before": None, "after": "oidc"}
    assert updated.changes["enabled"] == {"before": False, "after": True}
    assert updated.changes["client_secret"] == {"before": "[redacted]", "after": "[redacted]"}
    assert (await last(sessionmaker, "source.deleted")).target_name == "Corp SSO"
    assert "s3cr3t-value" not in every and "an0ther-value" not in every


async def test_the_sources_order_is_recorded_as_a_setting(admin_client, sessionmaker):
    ids = []
    for name in ("First", "Second"):
        made = await admin_client.post(
            SOURCES, json={"kind": "header", "name": name, "settings": {}}
        )
        ids.append(made.json()["id"])

    await admin_client.put(f"{SOURCES}/order", json={"ids": list(reversed(ids))})

    ordered = await last(sessionmaker, "setting.changed")
    assert ordered.target_name == "source_order"
    assert ordered.changes == {
        "source_order": {"before": ["First", "Second"], "after": ["Second", "First"]}
    }


async def test_every_setting_changed_is_recorded_and_one_left_as_it_was_is_not(
    admin_client, sessionmaker
):
    await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": "https://repo.example"})
    await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": True})
    await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": True})
    await admin_client.put(f"{SETTINGS}/default-role", json={"default_role": "admin"})
    await admin_client.put(f"{SETTINGS}/trusted-proxies", json={"trusted_proxies": ["10.0.0.5"]})

    changed = {
        entry.target_name: entry.changes for entry in await records(sessionmaker, "setting.changed")
    }
    assert len(await records(sessionmaker, "setting.changed")) == 4
    assert changed["base_url"] == {"base_url": {"before": None, "after": "https://repo.example"}}
    assert changed["anonymous_access"] == {
        "anonymous_access": {"before": {"enabled": False}, "after": {"enabled": True}}
    }
    assert changed["default_role"] == {"default_role": {"before": None, "after": "admin"}}
    assert changed["trusted_proxies"] == {
        "trusted_proxies": {"before": [], "after": ["10.0.0.5/32"]}
    }


async def test_a_certificate_trusted_and_removed_is_recorded_by_its_fingerprint(
    admin_client, sessionmaker
):
    ca = authority("Corp Root CA")
    added = (await admin_client.post("/api/v1/certificates", json={"pem": ca.pem})).json()
    await admin_client.delete(f"/api/v1/certificates/{added['id']}")

    trusted = await last(sessionmaker, "certificate.trusted")
    removed = await last(sessionmaker, "certificate.removed")
    assert trusted.target_name == added["subject"]
    assert trusted.changes["fingerprint"] == {"before": None, "after": added["fingerprint"]}
    assert "pem" not in trusted.changes
    assert removed.changes["fingerprint"] == {"before": added["fingerprint"], "after": None}


async def test_a_request_signed_in_by_password_is_recorded_so(client, make_user, sessionmaker):
    await make_user("ada", roles=["admin"])

    await client.post(
        ROLES,
        json={"name": "ops", "description": "", "permissions": [], "roles": []},
        headers=basic("ada", PASSWORD),
    )

    made = await last(sessionmaker, "role.created")
    assert (made.actor, made.method) == ("ada", "password")


async def test_a_user_the_directory_no_longer_has_is_disabled_by_the_system(
    app, client, directory, add_ldap_source, sessionmaker
):
    kim = directory.person("kim", "kim's password")
    directory.person("lou", "lou's password")
    await add_ldap_source()
    await sign_in(client, "kim", "kim's password")
    await sign_in(client, "lou", "lou's password")

    directory.remove(kim)
    await directory_check.run(app)

    disabled = await last(sessionmaker, "user.updated")
    assert (disabled.actor, disabled.method, disabled.target_name) == (None, "system", "kim")
    assert disabled.changes["status"] == {"before": "active", "after": "disabled"}


async def test_a_first_sign_in_and_the_roles_groups_give_are_recorded(
    admin_client, other_client, sessionmaker
):
    async with sessionmaker() as db:
        await roles.create_role(db, "developers", "", ["repository:*:*:read"], [])
        await db.commit()
    await admin_client.post(
        SOURCES,
        json={
            "kind": "header",
            "name": "Corp SSO proxy",
            "enabled": True,
            "settings": {"groups_header": "X-Forwarded-Groups"},
            "group_mapping": [{"group": "developers", "roles": ["developers"]}],
        },
    )
    await admin_client.put(f"{SETTINGS}/trusted-proxies", json={"trusted_proxies": ["10.0.0.5"]})
    proxied = {"X-Forwarded-For": "198.51.100.9, 10.0.0.5", "X-Forwarded-User": "kim"}

    await other_client.get(
        "/api/v1/auth/session", headers={**proxied, "X-Forwarded-Groups": "developers"}
    )
    await other_client.get(
        "/api/v1/auth/session", headers={**proxied, "X-Forwarded-Groups": "developers"}
    )
    await other_client.get("/api/v1/auth/session", headers={**proxied, "X-Forwarded-Groups": ""})

    made = await last(sessionmaker, "user.created")
    mapped = [entry.changes for entry in await records(sessionmaker, "user.updated")]
    assert (made.target_name, made.address) == ("kim", "198.51.100.9")
    assert made.changes == {"source": {"before": None, "after": "Corp SSO proxy"}}
    assert mapped == [
        {"roles_from_groups": {"before": [], "after": ["developers"]}},
        {"roles_from_groups": {"before": ["developers"], "after": []}},
    ]
```

Create `backend/tests/mcp/test_audit_records.py`:

```python
"""MCP's changes in the audit log (spec 9): recorded by the routes the tools call, as the
token's user, and as `oauth` for an application a person approved; and OAuth's own
changes: a client registered, an approval given and revoked."""

from tests.audit import last
from tests.mcp.conftest import structured
from tests.mcp.oauth_steps import approved_code, tokens

ROLE = {"name": "ops", "description": "", "permissions": [], "roles": []}


async def test_a_tools_change_is_recorded_as_its_tokens_user(
    agent, make_user, make_token, sessionmaker
):
    token = await make_token(await make_user("root", roles=["admin"]))

    async with agent(token) as client:
        structured(await client.call_tool("create_role", ROLE))

    made = await last(sessionmaker, "role.created")
    assert (made.actor, made.method, made.target_name) == ("root", "token", "ops")


async def test_an_approved_applications_change_is_recorded_as_oauth(
    agent, client, browser, sessionmaker
):
    client_id, code = await approved_code(client, browser, access="all")
    access = (await tokens(client, client_id, code))["access_token"]

    async with agent(access) as mcp:
        structured(await mcp.call_tool("create_role", ROLE))

    made = await last(sessionmaker, "role.created")
    assert (made.actor, made.method) == ("dev", "oauth")


async def test_a_client_registered_and_an_approval_given_and_revoked_are_recorded(
    client, browser, sessionmaker
):
    client_id, code = await approved_code(client, browser)
    (app,) = (await browser.get("/api/v1/me/connected-apps")).json()["items"]
    await browser.delete(f"/api/v1/me/connected-apps/{app['id']}")

    registered = await last(sessionmaker, "oauth_client.registered")
    approved = await last(sessionmaker, "connected_app.approved")
    revoked = await last(sessionmaker, "connected_app.revoked")
    assert (registered.actor, registered.target_name) == (None, "Claude")
    assert registered.changes == {
        "redirect_uris": {"before": None, "after": ["http://127.0.0.1:33418/callback"]}
    }
    assert (approved.actor, approved.target_name) == ("dev", "dev/Claude")
    assert approved.changes == {
        "access": {"before": None, "after": "read"},
        "lasts": {"before": None, "after": "30d"},
    }
    assert (revoked.actor, revoked.target_name) == ("dev", "dev/Claude")
```

Change `backend/tests/repositories/test_client_login.py`:

```diff
@@ -10,6 +10,7 @@ from megooarti.repositories import formats
 from megooarti.repositories.formats import Format
 from megooarti.security.models import ApiToken
 from tests.accounts import PASSWORD, basic, bearer, error_code
+from tests.audit import last
 
 LOGIN = "/repository/files/-/login"
 FILE = "/repository/files/a.txt"
@@ -200,3 +201,18 @@ async def test_a_stale_header_credential_is_not_counted_as_a_failed_attempt(clie
     # Two failures, not four: only the body is a sign-in attempt.
     assert mistyped == [401, 401]
     assert then_right.status_code == 200, then_right.text
+
+
+async def test_a_client_signing_in_and_out_is_recorded_as_its_token(client, dana, sessionmaker):
+    token = (await sign_in(client)).json()["token"]
+    await client.put("/repository/files/-/logout", headers={**bearer(token), "X-Token": token})
+
+    made = await last(sessionmaker, "token.created")
+    revoked = await last(sessionmaker, "token.revoked")
+    assert (made.actor, made.method) == ("dana", "password")
+    assert made.target_name.startswith("dana/test login ")
+    assert (revoked.actor, revoked.method, revoked.target_name) == (
+        "dana",
+        "token",
+        made.target_name,
+    )
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_audit_records.py tests/mcp/test_audit_records.py tests/repositories/test_client_login.py`
Expected: 15 failed, 16 passed: no record is written (`AssertionError: no role.created record`, `no user.created record`, ...); the client sign-in's other tests pass.

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/tokens.py`:

```diff
@@ -81,7 +81,8 @@ async def list_tokens(
     return list(rows), total or 0
 
 
-async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
+async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> str:
+    """Revoke one of a user's tokens; its name. Raises 404."""
     token = await db.scalar(
         select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
     )
@@ -89,3 +90,4 @@ async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID
         raise ApiError(404, "not_found", "No such token.")
     await db.delete(token)
     await db.flush()
+    return token.name
```

Change `backend/src/megooarti/security/oauth.py`:

```diff
@@ -377,15 +377,18 @@ async def approvals(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> list
     ]
 
 
-async def revoke(db: AsyncSession, user_id: uuid.UUID, grant_id: uuid.UUID) -> None:
-    """Revoke one of a user's approvals, and its tokens with it. Raises 404."""
+async def revoke(db: AsyncSession, user_id: uuid.UUID, grant_id: uuid.UUID) -> str:
+    """Revoke one of a user's approvals, and its tokens with it; the client's name. Raises
+    404."""
     grant = await db.scalar(
         select(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.user_id == user_id)
     )
     if grant is None:
         raise ApiError(404, "not_found", "No such connected app.")
+    client = await db.get(OAuthClient, grant.client_id)
     await db.delete(grant)
     await db.flush()
+    return "" if client is None else client.name
 
 
 async def forget(db: AsyncSession, now: datetime) -> None:
```

Change `backend/src/megooarti/security/sources.py`:

```diff
@@ -26,6 +26,7 @@ from megooarti.secrets_box import seal, unseal
 from megooarti.security.models import AuthSource, Role, User, UserRole, UserSession
 from megooarti.security.sessions import delete_user_sessions
 from megooarti.security.users import TOKEN_USERNAME, looks_like_token, normalise_username
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -321,6 +322,20 @@ async def _map_roles(
     wanted = set(await db.scalars(select(Role.id).where(Role.name.in_(names)))) if names else set()
     held = await _held_roles(db, user)
     gone = [role_id for role_id, by in held.items() if by == "source" and role_id not in wanted]
+    if gone or wanted - held.keys():
+        given = {role_id for role_id, by in held.items() if by == "source"}
+        named = dict(
+            (await db.execute(select(Role.id, Role.name).where(Role.id.in_(given | wanted)))).all()
+        )
+        audit.record(
+            db,
+            "user.updated",
+            ("user", user.username),
+            audit.diff(
+                {"roles_from_groups": sorted(named[role_id] for role_id in given)},
+                {"roles_from_groups": sorted(named[role_id] for role_id in wanted)},
+            ),
+        )
     if gone:
         await db.execute(
             delete(UserRole).where(UserRole.user_id == user.id, UserRole.role_id.in_(gone))
@@ -361,6 +376,9 @@ async def _first(db: AsyncSession, source: AuthSource, identity: Identity) -> Us
         if found is None:
             raise  # not theirs: another name taken at the same moment
         return found
+    audit.record(
+        db, "user.created", ("user", made.username), audit.diff(None, {"source": source.name})
+    )
     log.info("user_provisioned", username=made.username, source=source.name)
     return made
 
```

Change `backend/src/megooarti/security/client_login.py`:

```diff
@@ -15,6 +15,7 @@ from megooarti.clock import utcnow
 from megooarti.errors import ApiError
 from megooarti.security import tokens
 from megooarti.security.authentication import Principal, authenticate_secret
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -38,6 +39,8 @@ async def issue_token(
         )
     name = f"{label} {utcnow():%Y-%m-%d %H:%M:%S} {secrets.token_hex(3)}"
     _, value = await tokens.create_token(db, user.id, name=name, expires_at=None, scopes=None)
+    audit.acting(user.username, "password")
+    audit.record(db, "token.created", ("token", f"{user.username}/{name}"))
     log.info("client_signed_in", username=user.username, token_name=name)
     return value
 
@@ -49,4 +52,5 @@ async def revoke_own_token(db: AsyncSession, principal: Principal, value: str) -
         raise ApiError(404, "not_found", "No such token.")
     await db.delete(token)
     await db.flush()
+    audit.record(db, "token.revoked", ("token", f"{principal.user.username}/{token.name}"))
     log.info("client_signed_out", username=principal.user.username, token_name=token.name)
```

Change `backend/src/megooarti/security/directory_check.py`:

```diff
@@ -12,6 +12,7 @@ from sqlalchemy import select
 from megooarti.security import ldap, sources
 from megooarti.security.models import User
 from megooarti.security.sessions import delete_user_sessions
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -79,6 +80,12 @@ async def _check(app: Any, reach: sources.Outbound, source_id: Any) -> int:
         for user in found:
             user.status = "disabled"
             await delete_user_sessions(db, user.id)
+            audit.record(
+                db,
+                "user.updated",
+                ("user", user.username),
+                audit.diff({"status": "active"}, {"status": "disabled", "source": name}),
+            )
             log.info("directory_user_gone", username=user.username, source=name)
         await db.commit()
     return len(found)
```

Change `backend/src/megooarti/security/api/users.py`:

```diff
@@ -20,6 +20,7 @@ from megooarti.security.bootstrap import discard_initial_password
 from megooarti.security.guards import ensure_administrator_remains
 from megooarti.security.models import User
 from megooarti.security.users import UserView
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -100,6 +101,7 @@ async def create_user(
         must_change_password=body.must_change_password,
     )
     view = await users.describe(db, user)
+    audit.record(db, "user.created", ("user", user.username), audit.diff(None, view))
     await db.commit()
     log.info("user_created", username=user.username, by=principal.user.username)
     return view
@@ -130,9 +132,11 @@ async def update_user(
     }
     if user.id == principal.user.id and changes.get("status") == "disabled":
         raise ApiError(409, "self_protected", "You cannot disable your own account.")
+    before = await users.describe(db, user)
     await users.update_user(db, user, changes)
     await ensure_administrator_remains(db)
     view = await users.describe(db, user)
+    audit.record(db, "user.updated", ("user", user.username), audit.diff(before, view))
     await db.commit()
     log.info("user_updated", username=user.username, by=principal.user.username)
     return view
@@ -147,8 +151,10 @@ async def delete_user(
     user = await _load(db, user_id)
     if user.id == principal.user.id:
         raise ApiError(409, "self_protected", "You cannot delete your own account.")
+    before = await users.describe(db, user)
     await users.delete_user(db, user)
     await ensure_administrator_remains(db)
+    audit.record(db, "user.deleted", ("user", before.username), audit.diff(before, None))
     await db.commit()
     log.info("user_deleted", username=user.username, by=principal.user.username)
 
@@ -176,6 +182,12 @@ async def reset_password(
     await users.set_password(
         db, user, body.password, must_change_password=body.must_change_password
     )
+    audit.record(
+        db,
+        "user.password_changed",
+        ("user", user.username),
+        audit.diff(None, None, secrets=["password"]),
+    )
     await db.commit()
     discard_initial_password(request.app.state.settings, user)
     log.info("password_changed", username=user.username, by=principal.user.username)
@@ -214,7 +226,8 @@ async def revoke_user_connected_app(
     db: AsyncSession = Depends(get_session),
 ) -> None:
     user = await _load(db, user_id)
-    await oauth.revoke(db, user.id, app_id)
+    client = await oauth.revoke(db, user.id, app_id)
+    audit.record(db, "connected_app.revoked", ("connected_app", f"{user.username}/{client}"))
     await db.commit()
     log.info("connected_app_revoked", username=user.username, by=principal.user.username)
 
@@ -227,6 +240,7 @@ async def revoke_user_token(
     db: AsyncSession = Depends(get_session),
 ) -> None:
     user = await _load(db, user_id)
-    await tokens.revoke_token(db, user.id, token_id)
+    name = await tokens.revoke_token(db, user.id, token_id)
+    audit.record(db, "token.revoked", ("token", f"{user.username}/{name}"))
     await db.commit()
     log.info("token_revoked", username=user.username, by=principal.user.username)
```

Change `backend/src/megooarti/security/api/me.py`:

```diff
@@ -19,6 +19,7 @@ from megooarti.security.authentication import (
     require_interactive,
 )
 from megooarti.security.bootstrap import discard_initial_password
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -61,6 +62,12 @@ async def change_password(
     await users.set_password(
         db, user, body.new_password, must_change_password=False, keep_session_id=keep
     )
+    audit.record(
+        db,
+        "user.password_changed",
+        ("user", user.username),
+        audit.diff(None, None, secrets=["password"]),
+    )
     await db.commit()
     discard_initial_password(request.app.state.settings, user)
     log.info("password_changed", username=user.username, by=user.username)
@@ -97,6 +104,12 @@ async def create_token(
         last_used_at=token.last_used_at,
         token=value,
     )
+    audit.record(
+        db,
+        "token.created",
+        ("token", f"{principal.user.username}/{token.name}"),
+        audit.diff(None, {"scopes": token.scopes, "expires_at": token.expires_at}),
+    )
     await db.commit()
     log.info("token_created", username=principal.user.username, token=token.name)
     return created
@@ -108,7 +121,8 @@ async def revoke_token(
     principal: Principal = Depends(require_interactive()),
     db: AsyncSession = Depends(get_session),
 ) -> None:
-    await tokens.revoke_token(db, principal.user.id, token_id)
+    name = await tokens.revoke_token(db, principal.user.id, token_id)
+    audit.record(db, "token.revoked", ("token", f"{principal.user.username}/{name}"))
     await db.commit()
     log.info("token_revoked", username=principal.user.username, by=principal.user.username)
 
@@ -131,6 +145,9 @@ async def revoke_connected_app(
     db: AsyncSession = Depends(get_session),
 ) -> None:
     """Revoke an approval: the application's tokens stop working at once."""
-    await oauth.revoke(db, principal.user.id, app_id)
+    client = await oauth.revoke(db, principal.user.id, app_id)
+    audit.record(
+        db, "connected_app.revoked", ("connected_app", f"{principal.user.username}/{client}")
+    )
     await db.commit()
     log.info("connected_app_revoked", username=principal.user.username)
```

Change `backend/src/megooarti/security/api/roles.py`:

```diff
@@ -15,6 +15,7 @@ from megooarti.security.authentication import Principal, require
 from megooarti.security.guards import ensure_administrator_remains
 from megooarti.security.models import Role
 from megooarti.security.roles import RoleView
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -64,6 +65,7 @@ async def create_role(
 ) -> RoleView:
     role = await roles.create_role(db, body.name, body.description, body.permissions, body.roles)
     view = await roles.describe(db, role)
+    audit.record(db, "role.created", ("role", role.name), audit.diff(None, view))
     await db.commit()
     log.info("role_created", role=role.name, by=principal.user.username)
     return view
@@ -86,9 +88,11 @@ async def update_role(
     db: AsyncSession = Depends(get_session),
 ) -> RoleView:
     role = await _load(db, name)
+    before = await roles.describe(db, role)
     await roles.update_role(db, role, body.description, body.permissions, body.roles)
     await ensure_administrator_remains(db)
     view = await roles.describe(db, role)
+    audit.record(db, "role.updated", ("role", role.name), audit.diff(before, view))
     await db.commit()
     log.info("role_updated", role=role.name, by=principal.user.username)
     return view
@@ -101,7 +105,9 @@ async def delete_role(
     db: AsyncSession = Depends(get_session),
 ) -> None:
     role = await _load(db, name)
+    before = await roles.describe(db, role)
     await roles.delete_role(db, role)
     await ensure_administrator_remains(db)
+    audit.record(db, "role.deleted", ("role", name), audit.diff(before, None))
     await db.commit()
     log.info("role_deleted", role=name, by=principal.user.username)
```

Change `backend/src/megooarti/security/api/sources.py`:

```diff
@@ -17,6 +17,7 @@ from megooarti.pagination import Page, PageParams, page
 from megooarti.security import sources
 from megooarti.security.authentication import Principal, require
 from megooarti.security.models import AuthSource
+from megooarti.system import audit
 from megooarti.system.settings_store import get_setting
 
 log = structlog.get_logger(__name__)
@@ -141,6 +142,16 @@ async def _check_name(db: AsyncSession, name: str, own: uuid.UUID | None) -> Non
         raise ApiError(409, "conflict", f"A sign-in source named {name} already exists.")
 
 
+def _told(out: SourceOut) -> dict[str, Any]:
+    """A source as its records tell it: not how many users it has, nor its address."""
+    return out.model_dump(exclude={"users", "redirect_uri"})
+
+
+def _given(body: SourceIn, kind: sources.Kind) -> list[str]:
+    """The secrets given anew, by their names: their values are not recorded."""
+    return [name for name in kind.secrets if body.settings.get(name)]
+
+
 async def _apply(
     db: AsyncSession, request: Request, source: AuthSource, body: SourceIn, kind: sources.Kind
 ) -> None:
@@ -180,6 +191,12 @@ async def create_source(
     db.add(source)
     await db.flush()
     result = await _out(db, request, source)
+    audit.record(
+        db,
+        "source.created",
+        ("source", source.name),
+        audit.diff(None, _told(result), secrets=_given(body, kind)),
+    )
     await db.commit()
     log.info("auth_source_created", source=source.name, by=principal.user.username)
     return result
@@ -193,9 +210,18 @@ async def order_sources(
     db: AsyncSession = Depends(get_session),
 ) -> dict:
     """Put the sources in the order they are to be asked: every one of them, once."""
+    before = [source.name for source in await sources.in_order(db)]
     await sources.reorder(db, body.ids)
     every = await sources.in_order(db)
     items = [await _out(db, request, source) for source in every]
+    after = [source.name for source in every]
+    if after != before:
+        audit.record(
+            db,
+            "setting.changed",
+            ("setting", "source_order"),
+            audit.diff({"source_order": before}, {"source_order": after}),
+        )
     await db.commit()
     log.info("auth_sources_ordered", by=principal.user.username)
     return page(items, len(items), PageParams(limit=200, offset=0))
@@ -222,11 +248,19 @@ async def update_source(
     """Change a source; its kind stays. Turned off, its users are refused until it is on."""
     source = await _load(db, source_id)
     was_on = source.enabled
-    await _apply(db, request, source, body, _kind(source.kind))
+    before = _told(await _out(db, request, source))
+    kind = _kind(source.kind)
+    await _apply(db, request, source, body, kind)
     if was_on and not source.enabled:
         await sources.sign_out_users(db, source)
     await db.flush()
     result = await _out(db, request, source)
+    audit.record(
+        db,
+        "source.updated",
+        ("source", source.name),
+        audit.diff(before, _told(result), secrets=_given(body, kind)),
+    )
     await db.commit()
     log.info("auth_source_updated", source=source.name, by=principal.user.username)
     return result
@@ -235,12 +269,15 @@ async def update_source(
 @router.delete("/{source_id}", status_code=204)
 async def delete_source(
     source_id: uuid.UUID,
+    request: Request,
     principal: Principal = Depends(require("admin:security:write")),
     db: AsyncSession = Depends(get_session),
 ) -> None:
     """Delete a source. Its users are disabled, and kept with what they own."""
     source = await _load(db, source_id)
+    before = _told(await _out(db, request, source))
     await sources.delete_source(db, source)
+    audit.record(db, "source.deleted", ("source", source.name), audit.diff(before, None))
     await db.commit()
     log.info("auth_source_deleted", source=source.name, by=principal.user.username)
 
```

Change `backend/src/megooarti/security/api/oauth.py`:

```diff
@@ -16,6 +16,7 @@ from megooarti.db.session import get_session
 from megooarti.errors import ApiError
 from megooarti.security import oauth
 from megooarti.security.authentication import Principal, client_ip, require_interactive
+from megooarti.system import audit
 from megooarti.system.settings_store import get_setting
 
 log = structlog.get_logger(__name__)
@@ -116,6 +117,12 @@ async def register(request: Request, db: AsyncSession = Depends(get_session)) ->
     except oauth.OAuthError as error:
         return _answer(error)
     described = oauth.describe(client)
+    audit.record(
+        db,
+        "oauth_client.registered",
+        ("oauth_client", client.name),
+        audit.diff(None, {"redirect_uris": said.redirect_uris}),
+    )
     await db.commit()
     log.info("oauth_client_registered", client=described["client_id"], name=client.name)
     return JSONResponse(described, status_code=201, headers=_NO_STORE)
@@ -268,6 +275,13 @@ async def approve(
     """The person approves: a code for the client, back at its redirect address."""
     found = await _asked(request, db, body.request)
     address = await oauth.approve(db, principal.user, found, body.access, body.lasts, utcnow())
+    client = await oauth.get_client(db, found.client_id)
+    audit.record(
+        db,
+        "connected_app.approved",
+        ("connected_app", f"{principal.user.username}/{'' if client is None else client.name}"),
+        audit.diff(None, {"access": body.access, "lasts": body.lasts}),
+    )
     await db.commit()
     log.info("oauth_approved", client=found.client_id, by=principal.user.username)
     return Redirect(redirect=address)
```

Change `backend/src/megooarti/system/settings_api.py`:

```diff
@@ -14,7 +14,8 @@ from megooarti.security import users
 from megooarti.security.authentication import Principal, require
 from megooarti.security.guards import ensure_administrator_remains
 from megooarti.security.roles import get_role
-from megooarti.system.settings_store import get_setting, set_setting
+from megooarti.system import audit
+from megooarti.system.settings_store import get_setting
 
 log = structlog.get_logger(__name__)
 
@@ -101,7 +102,7 @@ async def set_base_url(
     principal: Principal = Depends(require("admin:settings:write")),
     db: AsyncSession = Depends(get_session),
 ) -> SettingsOut:
-    await set_setting(db, "base_url", body.base_url)
+    await audit.set_setting(db, "base_url", body.base_url)
     result = await _current(db)
     await db.commit()
     log.info("setting_changed", setting="base_url", by=principal.user.username)
@@ -114,7 +115,7 @@ async def set_anonymous_access(
     principal: Principal = Depends(require("admin:settings:write")),
     db: AsyncSession = Depends(get_session),
 ) -> SettingsOut:
-    await set_setting(db, "anonymous_access", {"enabled": body.enabled})
+    await audit.set_setting(db, "anonymous_access", {"enabled": body.enabled})
     result = await _current(db)
     await db.commit()
     log.info(
@@ -144,7 +145,7 @@ async def set_default_role(
     if body.default_role is not None and await get_role(db, body.default_role) is None:
         details = [{"field": "default_role", "message": f"Unknown role: {body.default_role}"}]
         raise ApiError(422, "validation_error", "The request is not valid.", details)
-    await set_setting(db, "default_role", body.default_role)
+    await audit.set_setting(db, "default_role", body.default_role)
     result = await _sign_in(db)
     await db.commit()
     log.info(
@@ -164,7 +165,7 @@ async def set_local_sign_in(
 ) -> SignInSettings:
     """Whether MegooArti's own users sign in. Off, the built-in `admin` still does (E1),
     and must then hold full access: else nobody who signs in would."""
-    await set_setting(db, "local_sign_in", {"enabled": body.enabled})
+    await audit.set_setting(db, "local_sign_in", {"enabled": body.enabled})
     await ensure_administrator_remains(db)
     if not body.enabled:
         await users.sign_out_our_own(db)  # signed out for good, as a disabled user is
@@ -199,7 +200,7 @@ async def set_trusted_proxies(
             raise ApiError(422, "validation_error", "The request is not valid.", details) from None
         if network not in kept:
             kept.append(network)
-    await set_setting(db, "trusted_proxies", kept or None)
+    await audit.set_setting(db, "trusted_proxies", kept or None)
     result = await _sign_in(db)
     await db.commit()
     request.app.state.trusted_proxies = networks(kept)  # at once, for the next request
```

Change `backend/src/megooarti/system/certificates_api.py`:

```diff
@@ -14,7 +14,7 @@ from megooarti.errors import ApiError
 from megooarti.pagination import Page, PageParams, page
 from megooarti.repositories import remote
 from megooarti.security.authentication import Principal, require
-from megooarti.system import certificates
+from megooarti.system import audit, certificates
 from megooarti.system.models import TrustedCertificate
 
 log = structlog.get_logger(__name__)
@@ -56,6 +56,22 @@ class Fetched(BaseModel):
     chain: list[CertificateView]
 
 
+def _told(added: TrustedCertificate | None, removed: TrustedCertificate | None) -> dict:
+    """A certificate as its records tell it: by its fingerprint, not its PEM."""
+
+    def told(held: TrustedCertificate | None) -> dict | None:
+        if held is None:
+            return None
+        return {
+            "subject": held.subject,
+            "issuer": held.issuer,
+            "fingerprint": held.fingerprint,
+            "not_after": held.not_after,
+        }
+
+    return audit.diff(told(removed), told(added))
+
+
 async def _kept_and_trusted(request: Request, db: AsyncSession) -> None:
     """Keep the change, and have the outbound connections trust the certificates as they
     are kept with it (spec 6). Called holding the trust lock: two changes at once would
@@ -86,6 +102,7 @@ async def add_certificate(
     described = certificates.read_one(body.pem)
     async with request.app.state.trust_lock:
         added = await certificates.add(db, described, principal.user.username)
+        audit.record(db, "certificate.trusted", ("certificate", added.subject), _told(added, None))
         await _kept_and_trusted(request, db)
     log.info(
         "certificate_trusted",
@@ -124,5 +141,6 @@ async def delete_certificate(
             raise ApiError(404, "not_found", "No such certificate.")
         await db.delete(held)
         await db.flush()
+        audit.record(db, "certificate.removed", ("certificate", held.subject), _told(None, held))
         await _kept_and_trusted(request, db)
     log.info("certificate_removed", subject=held.subject, by=principal.user.username)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security tests/mcp tests/repositories/test_client_login.py tests/test_settings_api.py tests/test_certificates_api.py tests/test_proxies.py tests/test_audit.py`
Expected: 652 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(audit): users, roles, tokens, connected apps, sources, settings and certificates recorded with what changed, never a secret; what the server changes itself, as the system"
```

---

### Task 3: Sign-in in the audit log

**Files:**
- Modify: `backend/src/megooarti/security/authentication.py`, `backend/src/megooarti/security/api/auth.py`, `backend/src/megooarti/security/api/oidc.py`
- Test: `backend/tests/security/test_audit_sign_in.py`

**Interfaces:**
- Consumes: Task 1's `audit.record`, `audit.diff`, `audit.identified`; the OIDC tests' `sign_in`, `landed` and `oidc_path`; the fixtures `provider`, `add_oidc_source`, `directory`, `add_ldap_source`.
- Produces: the events `sign_in.succeeded`, `sign_in.failed`, `sign_in.throttled`, `sign_in.refused`, `session.signed_out`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/test_audit_sign_in.py`:

```python
"""Sign-in in the audit log (spec 9): every one that succeeds, fails, is throttled or is
refused, by every source, kept though the request that failed is answered with an error;
and every sign-out."""

from tests.accounts import PASSWORD, basic, bearer, sign_in
from tests.audit import last, records
from tests.security.test_oidc_sign_in import landed, oidc_path
from tests.security.test_oidc_sign_in import sign_in as oidc_sign_in

SESSION = "/api/v1/auth/session"
LOGIN = "/api/v1/auth/login"


async def test_a_sign_in_and_a_sign_out_are_recorded(client, make_user, sessionmaker):
    await make_user("kim")

    await sign_in(client, "kim")
    await client.post("/api/v1/auth/logout")

    signed_in = await last(sessionmaker, "sign_in.succeeded")
    signed_out = await last(sessionmaker, "session.signed_out")
    assert (signed_in.actor, signed_in.method, signed_in.target_name) == ("kim", "session", "kim")
    assert signed_in.address == "127.0.0.1"
    assert signed_in.changes is None  # one of MegooArti's own: no source
    assert (signed_out.actor, signed_out.target_name) == ("kim", "kim")


async def test_a_wrong_password_is_recorded_though_the_request_fails(
    client, make_user, sessionmaker
):
    await make_user("kim")

    refused = await client.post(LOGIN, json={"username": "kim", "password": "wrong"})
    by_basic = await client.get(SESSION, headers=basic("Kim", "wrong"))

    failed = await records(sessionmaker, "sign_in.failed")
    assert (refused.status_code, by_basic.status_code) == (401, 401)
    assert [(entry.actor, entry.target_name) for entry in failed] == [
        (None, "kim"),
        (None, "kim"),
    ]


async def test_a_token_that_is_none_is_recorded_without_a_name(client, sessionmaker):
    await client.get(SESSION, headers=bearer("mga_" + "x" * 40))

    failed = await last(sessionmaker, "sign_in.failed")
    assert (failed.target_kind, failed.target_name) == (None, None)


async def test_a_throttled_sign_in_is_recorded(client, make_user, sessionmaker):
    await make_user("kim")
    for _ in range(5):
        await client.post(LOGIN, json={"username": "kim", "password": "wrong"})

    throttled = await client.post(LOGIN, json={"username": "kim", "password": PASSWORD})

    assert throttled.status_code == 429
    assert (await last(sessionmaker, "sign_in.throttled")).target_name == "kim"


async def test_a_directorys_sign_in_says_its_source_and_a_wrong_password_there_too(
    client, other_client, directory, add_ldap_source, sessionmaker
):
    directory.person("kim", "kim's password")
    await add_ldap_source()

    await sign_in(client, "kim", "kim's password")
    await other_client.get(SESSION, headers=basic("kim", "not kim's"))

    signed_in = await last(sessionmaker, "sign_in.succeeded")
    assert signed_in.changes == {"source": {"before": None, "after": "Corp LDAP"}}
    assert (await last(sessionmaker, "sign_in.failed")).target_name == "kim"


async def test_a_providers_sign_in_is_recorded_and_one_that_failed_says_why(
    client, provider, add_oidc_source, sessionmaker
):
    source = await add_oidc_source()
    provider.person("kim")

    landed(await oidc_sign_in(client, provider, source, "kim"))
    started = await client.get(oidc_path(source, "start"), params={"next": "/search"})
    code = provider.authorize(started.headers["location"], "kim")
    await client.get(oidc_path(source, "callback"), params={"code": code, "state": "forged"})

    signed_in = await last(sessionmaker, "sign_in.succeeded")
    failed = await last(sessionmaker, "sign_in.failed")
    assert (signed_in.actor, signed_in.target_name) == ("kim", "kim")
    assert signed_in.changes == {"source": {"before": None, "after": "Corp SSO"}}
    assert failed.target_name == "Corp SSO"
    assert failed.changes["why"] == {"before": None, "after": "failed"}


async def test_a_trusted_header_from_elsewhere_is_recorded_as_refused(
    admin_client, other_client, sessionmaker
):
    await admin_client.post(
        "/api/v1/auth-sources",
        json={"kind": "header", "name": "Corp SSO proxy", "enabled": True, "settings": {}},
    )

    refused = await other_client.get(SESSION, headers={"X-Forwarded-User": "admin"})

    said = await last(sessionmaker, "sign_in.refused")
    assert refused.status_code == 401
    assert (said.target_kind, said.target_name) == ("source", "Corp SSO proxy")
    assert said.changes == {"why": {"before": None, "after": "not through a trusted proxy"}}
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/security/test_audit_sign_in.py`
Expected: 7 failed: no sign-in is recorded (`AssertionError: no sign_in.succeeded record`, `no sign_in.throttled record`, `no sign_in.refused record`).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -148,6 +148,8 @@ async def _checked[T](
         window_seconds=settings.login_failure_window_seconds,
     )
     if standing.blocked_for:
+        audit.record(db, "sign_in.throttled", None if username is None else ("user", username))
+        await db.commit()  # the record must outlive this refused request
         log.warning("login_throttled", username=username, ip=client_ip(request))
         raise ApiError(
             429,
@@ -161,7 +163,8 @@ async def _checked[T](
         await throttle.record_failure(
             db, subjects, now=now, window_seconds=settings.login_failure_window_seconds
         )
-        await db.commit()  # the count must outlive this failed request
+        audit.record(db, "sign_in.failed", None if username is None else ("user", username))
+        await db.commit()  # the count, and the record, must outlive this failed request
         log.info("login_failed", username=username, ip=client_ip(request))
         raise unauthorized(INVALID_CREDENTIALS)
     if standing.has_failures:
@@ -360,6 +363,13 @@ async def _from_trusted_header(request: Request, db: AsyncSession) -> Principal
         if source.settings["user_header"] not in request.headers:
             continue
         if not getattr(request.state, "proxied", False):
+            audit.record(
+                db,
+                "sign_in.refused",
+                ("source", source.name),
+                audit.diff(None, {"why": "not through a trusted proxy"}),
+            )
+            await db.commit()  # the record must outlive this refused request
             log.warning("trusted_header_refused", source=source.name, ip=client_ip(request))
             raise unauthorized(
                 f"{source.settings['user_header']} is taken from a trusted proxy only."
```

Change `backend/src/megooarti/security/api/auth.py`:

```diff
@@ -10,7 +10,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 from megooarti.clock import utcnow
 from megooarti.db.session import get_session
 from megooarti.pagination import Page, PageParams, page
-from megooarti.security import sessions, sources
+from megooarti.security import sessions, sources, users
 from megooarti.security.authentication import (
     SESSION_COOKIE,
     Principal,
@@ -21,6 +21,7 @@ from megooarti.security.authentication import (
     refuse_cross_site,
 )
 from megooarti.security.models import User
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -98,6 +99,11 @@ async def start_session(
         lifetime_seconds=settings.session_absolute_seconds,
     )
     principal = await build_principal(db, user, "session", session=record)
+    audit.identified(principal)
+    source = logged.get("source") or (await users.describe(db, user)).source
+    audit.record(
+        db, "sign_in.succeeded", ("user", user.username), audit.diff(None, {"source": source})
+    )
     await db.commit()
     response.set_cookie(
         SESSION_COOKIE,
@@ -130,6 +136,7 @@ async def logout(
 ) -> None:
     if principal is not None and principal.session is not None:
         await sessions.delete_session(db, principal.session)
+        audit.record(db, "session.signed_out", ("user", principal.user.username))
         await db.commit()
         log.info("logout", username=principal.user.username)
     response.delete_cookie(SESSION_COOKIE, path="/")
```

Change `backend/src/megooarti/security/api/oidc.py`:

```diff
@@ -24,6 +24,7 @@ from megooarti.security import oidc, sources, users
 from megooarti.security.api.auth import start_session
 from megooarti.security.api.sources import redirect_uri
 from megooarti.security.models import AuthSource
+from megooarti.system import audit
 from megooarti.system.settings_store import get_setting
 
 log = structlog.get_logger(__name__)
@@ -149,6 +150,14 @@ async def callback(
     async def failed(why: str, said: str) -> RedirectResponse:
         log.warning("oidc_sign_in_failed", source_id=str(source_id), why=why, said=said[:300])
         await db.rollback()  # nothing is made of a sign-in that did not happen
+        named = await _source(db, source_id)
+        audit.record(
+            db,
+            "sign_in.failed",
+            ("source", str(source_id) if named is None else named.name),
+            audit.diff(None, {"why": why, "said": said[:300]}),
+        )
+        await db.commit()
         response = await _sign_in_screen(db, error=why, next=next)
         response.delete_cookie(COOKIE, path=COOKIE_PATH)
         return response
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/security tests/mcp tests/test_proxies.py tests/test_audit.py tests/repositories/test_client_login.py`
Expected: 636 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(audit): every sign-in, failed, throttled or refused, by every source, kept though its request fails; every sign-out"
```

---

### Task 4: Repositories and blob stores write their records

**Files:**
- Modify: `backend/src/megooarti/repositories/api.py`, `backend/src/megooarti/storage/api.py`
- Test: `backend/tests/repositories/test_audit_records.py`

**Interfaces:**
- Consumes: Task 1's `audit.record`, `audit.diff`, `tests.audit.last`.
- Produces: the events `repository.created`, `repository.updated`, `repository.deleted`, `repository.cache_invalidated`, `repository.index_rebuilt`, `signing_key.imported`, `signing_key.generated`, `blob_store.created`, `blob_store.deleted`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/repositories/test_audit_records.py`:

```python
"""What the repositories' and blob stores' administration writes to the audit log (spec 9):
each repository made, changed and deleted, with what changed and never its remote's
secret; its cache, index and signing key; and each blob store."""

from tests.audit import last

REPOSITORIES = "/api/v1/repositories"
MIRROR = {
    "name": "mirror",
    "format": "raw",
    "type": "proxy",
    "proxy": {
        "remote_url": "https://remote.example/files",
        "remote_auth": {"type": "basic", "username": "robot", "secret": "hunter2-the-remote"},
    },
}


async def test_a_repository_made_changed_and_deleted_is_recorded_without_its_secret(
    admin_client, sessionmaker
):
    await admin_client.post(REPOSITORIES, json=MIRROR)
    await admin_client.put(f"{REPOSITORIES}/mirror", json={**MIRROR, "online": False})
    await admin_client.post(f"{REPOSITORIES}/mirror/invalidate-cache")
    await admin_client.delete(f"{REPOSITORIES}/mirror")

    created = await last(sessionmaker, "repository.created")
    updated = await last(sessionmaker, "repository.updated")
    deleted = await last(sessionmaker, "repository.deleted")
    assert (created.actor, created.target_kind, created.target_name) == (
        "root",
        "repository",
        "mirror",
    )
    assert created.changes["format"] == {"before": None, "after": "raw"}
    assert created.changes["proxy.remote_auth.secret"] == {
        "before": "[redacted]",
        "after": "[redacted]",
    }
    assert "status" not in created.changes
    assert updated.changes["online"] == {"before": True, "after": False}
    assert "hunter2-the-remote" not in str([created.changes, updated.changes])
    assert (await last(sessionmaker, "repository.cache_invalidated")).target_name == "mirror"
    assert deleted.changes["name"] == {"before": "mirror", "after": None}


async def test_a_signing_key_made_is_recorded_by_its_fingerprint(admin_client, sessionmaker):
    await admin_client.post(
        REPOSITORIES, json={"name": "apt-hosted", "format": "apt", "type": "hosted"}
    )

    shown = await admin_client.post(f"{REPOSITORIES}/apt-hosted/signing-key/generate", json={})

    generated = await last(sessionmaker, "signing_key.generated")
    assert generated.target_name == "apt-hosted"
    assert generated.changes["fingerprint"] == {
        "before": None,
        "after": shown.json()["fingerprint"],
    }


async def test_an_index_rebuilt_is_recorded_with_what_was_done(admin_client, sessionmaker):
    await admin_client.post(REPOSITORIES, json={"name": "files", "format": "raw", "type": "hosted"})

    await admin_client.post(f"{REPOSITORIES}/files/rebuild-index")

    rebuilt = await last(sessionmaker, "repository.index_rebuilt")
    assert rebuilt.target_name == "files"
    assert set(rebuilt.changes) == {"files", "moved", "components", "removed"}


async def test_a_blob_store_made_and_deleted_is_recorded(admin_client, sessionmaker):
    await admin_client.post("/api/v1/blob-stores", json={"name": "archive"})
    await admin_client.delete("/api/v1/blob-stores/archive")

    created = await last(sessionmaker, "blob_store.created")
    assert created.changes == {
        "path": {"before": None, "after": "archive"},
        "type": {"before": None, "after": "file"},
    }
    assert (await last(sessionmaker, "blob_store.deleted")).target_name == "archive"
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_audit_records.py`
Expected: 4 failed: no record is written (`AssertionError: no repository.created record`, `no signing_key.generated record`, `no repository.index_rebuilt record`, `no blob_store.created record`).

- [ ] **Step 3: Write the code**

Change `backend/src/megooarti/repositories/api.py`:

```diff
@@ -1,5 +1,6 @@
 """Administration of repositories."""
 
+from dataclasses import asdict
 from datetime import datetime
 from typing import Any, Literal
 
@@ -20,6 +21,7 @@ from megooarti.repositories.models import Repository, SigningKey
 from megooarti.repositories.service import RepositoryView
 from megooarti.secrets_box import seal
 from megooarti.security.authentication import Principal, require
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -132,6 +134,16 @@ def _plain(model: BaseModel | None) -> dict[str, Any] | None:
     return None if model is None else model.model_dump()
 
 
+def _told(view: RepositoryView) -> dict[str, Any]:
+    """A repository as its records tell it: its settings, not how its remote is doing."""
+    return {name: value for name, value in asdict(view).items() if name != "status"}
+
+
+def _given(proxy: ProxyIn | None) -> list[str]:
+    """The remote's secret, by its name, when one is given anew: its value is not recorded."""
+    return ["proxy.remote_auth.secret"] if proxy and proxy.remote_auth.secret else []
+
+
 def _proxy(settings: Settings, proxy: ProxyIn | None) -> dict[str, Any] | None:
     """The proxy settings as the service takes them, with the secret sealed."""
     if proxy is None:
@@ -191,6 +203,12 @@ async def create_repository(
         format_config=body.format_config,
     )
     view = await service.describe(db, repository)
+    audit.record(
+        db,
+        "repository.created",
+        ("repository", repository.name),
+        audit.diff(None, _told(view), secrets=_given(body.proxy)),
+    )
     await db.commit()
     log.info("repository_created", repository=repository.name, by=principal.user.username)
     return view
@@ -230,6 +248,12 @@ async def update_repository(
         format_config=body.format_config,
     )
     view = await service.describe(db, repository)
+    audit.record(
+        db,
+        "repository.updated",
+        ("repository", repository.name),
+        audit.diff(_told(current), _told(view), secrets=_given(body.proxy)),
+    )
     await db.commit()
     log.info("repository_updated", repository=repository.name, by=principal.user.username)
     return view
@@ -242,7 +266,9 @@ async def delete_repository(
     db: AsyncSession = Depends(get_session),
 ) -> None:
     repository = await _load(db, name)
+    before = await service.describe(db, repository)
     await service.delete_repository(db, repository, utcnow())
+    audit.record(db, "repository.deleted", ("repository", name), audit.diff(_told(before), None))
     await db.commit()
     log.info("repository_deleted", repository=name, by=principal.user.username)
 
@@ -255,6 +281,7 @@ async def invalidate_cache(
 ) -> None:
     repository = await _load(db, name)
     await service.invalidate_cache(db, repository)
+    audit.record(db, "repository.cache_invalidated", ("repository", name))
     await db.commit()
     log.info("repository_cache_invalidated", repository=name, by=principal.user.username)
 
@@ -294,6 +321,8 @@ async def rebuild_index(
             await db.commit()
             done.components, done.removed = done.components + seen, done.removed + removed
             first = False
+    audit.record(db, "repository.index_rebuilt", ("repository", name), audit.diff(None, done))
+    await db.commit()
     log.info(
         "repository_index_rebuilt",
         repository=name,
@@ -365,6 +394,12 @@ async def import_signing_key(
         details = [{"field": "body.private_key", "message": str(error)}]
         raise ApiError(422, "validation_error", "The request is not valid.", details) from None
     shown = _shown(request.app.state.settings, key)
+    audit.record(
+        db,
+        "signing_key.imported",
+        ("repository", name),
+        audit.diff(None, {"fingerprint": shown.fingerprint}, secrets=["private_key"]),
+    )
     await db.commit()
     log.info(
         "signing_key_imported",
@@ -391,6 +426,12 @@ async def generate_signing_key(
         details = [{"field": "body.algorithm", "message": str(error)}]
         raise ApiError(422, "validation_error", "The request is not valid.", details) from None
     shown = _shown(request.app.state.settings, key)
+    audit.record(
+        db,
+        "signing_key.generated",
+        ("repository", name),
+        audit.diff(None, {"algorithm": shown.algorithm, "fingerprint": shown.fingerprint}),
+    )
     await db.commit()
     log.info(
         "signing_key_generated",
```

Change `backend/src/megooarti/storage/api.py`:

```diff
@@ -13,6 +13,7 @@ from megooarti.security.authentication import Principal, require
 from megooarti.storage import blob_stores
 from megooarti.storage.blob_stores import BlobStoreView
 from megooarti.storage.models import BlobStore
+from megooarti.system import audit
 
 log = structlog.get_logger(__name__)
 
@@ -65,6 +66,12 @@ async def create_blob_store(
         db, settings, name=body.name, type=body.type, path=body.path
     )
     view = await blob_stores.describe(db, settings, store)
+    audit.record(
+        db,
+        "blob_store.created",
+        ("blob_store", store.name),
+        audit.diff(None, {"type": store.type, "path": view.path}),
+    )
     await db.commit()
     log.info("blob_store_created", blob_store=store.name, by=principal.user.username)
     return view
@@ -88,5 +95,6 @@ async def delete_blob_store(
 ) -> None:
     store = await _load(db, name)
     await blob_stores.delete_blob_store(db, store)
+    audit.record(db, "blob_store.deleted", ("blob_store", name))
     await db.commit()
     log.info("blob_store_deleted", blob_store=name, by=principal.user.username)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest -q tests/repositories/test_audit_records.py tests/repositories/test_api.py tests/repositories/test_rebuild_index.py tests/repositories/apt tests/storage`
Expected: 356 passed.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "feat(audit): repositories, their caches, indexes and signing keys, and blob stores recorded, never a remote's secret"
```

---

### Task 5: The Audit log screen, the guide, and what the plan settled

**Files:**
- Create: `frontend/src/screens/audit.tsx`, `frontend/src/app/(shell)/admin/audit/page.tsx`
- Modify:
  - `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api` from Task 1's `openapi.json`), `frontend/src/lib/api/types.ts`
  - `frontend/src/lib/paths.ts`, `frontend/src/lib/administration.ts`, `frontend/src/lib/navigation.ts`, `frontend/src/lib/patterns.ts`, `frontend/messages/en.json`
  - `docs/web-ui.md`, `docs/administration.md` (the audit log's section), `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`
- Test: `frontend/src/screens/audit.test.tsx`; modify `frontend/src/components/shell.test.tsx`, `frontend/src/lib/navigation.test.ts`, `frontend/src/components/security.test.tsx`, `frontend/src/screens/security.test.tsx`, `frontend/src/lib/account.test.ts` (their example of an area the editor does not know is now one it knows)

**Interfaces:**
- Consumes: Task 1's routes and `AuditRecordOut` and `Retention` (through `schema.d.ts`). From the web UI: `Pager`, `Time`, `Table`, `SelectField`, `TextField`, `refusalsOf`, `allows`, `useSession`, `pageOf` and `withQuery`.
- Produces:
  - `AUDIT`, `auditHref(filters, page)`, `AuditFilters`, `useAuditRecords(page, filters)`, `auditExportHref(format, filters)`, `useAuditRetention()`, `useSetAuditRetention()`, `AuditScreen`.
  - The navigation item `audit`; the role editor's areas `security`, `certificates` and `audit`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/audit.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { AuditScreen } from "./audit";

const page = (items: unknown[], total = items.length) => ({
  items,
  total,
  limit: 50,
  offset: 0,
});
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });

const UPDATED = {
  id: "r2",
  at: "2026-10-20T09:30:00Z",
  actor: "root",
  method: "session",
  address: "198.51.100.9",
  event: "user.updated",
  target_kind: "user",
  target_name: "kim",
  changes: {
    email: { before: null, after: "kim@corp.example" },
    roles: { before: ["dev"], after: ["dev", "ops"] },
  },
  request_id: "abc",
};
const FAILED = {
  id: "r1",
  at: "2026-10-20T09:00:00Z",
  actor: null,
  method: null,
  address: "203.0.113.7",
  event: "sign_in.failed",
  target_kind: "user",
  target_name: "kim",
  changes: null,
  request_id: "def",
};

function auditScreen(more: Routes = {}, session = ADMIN, address = "/admin/audit") {
  const api = mockApi({
    "GET /audit": { json: page([UPDATED, FAILED]) },
    "GET /audit/retention": { json: { audit_retention_days: 365 } },
    ...more,
  });
  navigation.at(address);
  return { ...renderUi(<AuditScreen />, { session }), ...api };
}

describe("the audit log (spec 9)", () => {
  test("lists who did what, about what and from where, each opening to what changed", async () => {
    const user = userEvent.setup();
    auditScreen();

    const table = await screen.findByRole("table", { name: "Audit log" });
    const rows = within(table).getAllByRole("row").slice(1);
    const cells = (row: Element | undefined) =>
      within(row as HTMLElement)
        .getAllByRole("cell")
        .slice(1, 5)
        .map((cell) => cell.textContent);
    expect(cells(rows[0])).toEqual(["rootby session", "user.updated", "userkim", "198.51.100.9"]);
    expect(cells(rows[1])).toEqual([
      "Nobody signed in",
      "sign_in.failed",
      "userkim",
      "203.0.113.7",
    ]);

    await user.click(within(rows[0] as HTMLElement).getByText("2 fields"));
    expect(within(rows[0] as HTMLElement).getByText("roles:")).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText('["dev"] → ["dev","ops"]')).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText("— → kim@corp.example")).toBeVisible();
    await expectAccessible();
  });

  test("asks for the records the address names, and pages through them", async () => {
    const { calls } = auditScreen(
      { "GET /audit": { json: { ...page([UPDATED], 120), offset: 50 } } },
      ADMIN,
      "/admin/audit?event=user&actor=root&since=2026-10-01&until=2026-10-19&page=2",
    );

    await screen.findByRole("table", { name: "Audit log" });
    const listing = of(calls, "GET").find((call) => call.path.startsWith("/audit?"));
    const asked = new URLSearchParams(listing?.path.split("?")[1]);
    expect(Object.fromEntries(asked)).toEqual({
      limit: "50",
      offset: "50",
      event: "user",
      actor: "root",
      since: "2026-10-01T00:00:00.000Z",
      until: "2026-10-20T00:00:00.000Z",
    });
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/admin/audit?event=user&actor=root&since=2026-10-01&until=2026-10-19&page=3",
    );
  });

  test("filters by what is typed, from the first page", async () => {
    const user = userEvent.setup();
    auditScreen();

    await screen.findByRole("table", { name: "Audit log" });
    await user.selectOptions(screen.getByLabelText("Event"), "sign_in");
    await user.type(screen.getByLabelText("About"), "kim");
    await user.click(screen.getByRole("button", { name: "Filter" }));

    expect(navigation.router.push).toHaveBeenCalledWith("/admin/audit?event=sign_in&target=kim");
  });

  test("exports what the filters give, as JSON Lines or CSV", async () => {
    auditScreen({}, ADMIN, "/admin/audit?event=user&until=2026-10-19");

    await screen.findByRole("table", { name: "Audit log" });

    expect(screen.getByRole("link", { name: "Export as JSON Lines" })).toHaveAttribute(
      "href",
      "/api/v1/audit/export?format=jsonl&event=user&until=2026-10-20T00%3A00%3A00.000Z",
    );
    expect(screen.getByRole("link", { name: "Export as CSV" })).toHaveAttribute(
      "href",
      "/api/v1/audit/export?format=csv&event=user&until=2026-10-20T00%3A00%3A00.000Z",
    );
  });

  test("says so when there is no record", async () => {
    auditScreen({ "GET /audit": { json: page([]) } });

    expect(await screen.findByText("No records.")).toBeVisible();
  });

  test("keeps records the days an administrator sets, and says what it refuses", async () => {
    const user = userEvent.setup();
    const { calls } = auditScreen({
      "PUT /audit/retention": (call) => ({ json: call.body }),
    });

    const days = await screen.findByLabelText("Days kept");
    await user.clear(days);
    await user.type(days, "0");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(days).toHaveAccessibleDescription(/from 1 to 36500/);
    expect(of(calls, "PUT")).toHaveLength(0);

    await user.clear(days);
    await user.type(days, "90");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("Records are kept 90 days."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ audit_retention_days: 90 });
  });

  test("shows the days kept, and not their change, to whoever may only read", async () => {
    auditScreen({}, holding("admin:audit:read"));

    expect(await screen.findByLabelText("Days kept")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  test("says why when the records cannot be read, with the request to look up", async () => {
    auditScreen({ "GET /audit": failure(503, "unavailable", "The database is not reachable.") });

    expect(await screen.findByText(/req-123/)).toBeVisible();
  });
});
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -82,6 +82,7 @@ describe("the shell", () => {
       ["Manage repositories", "/admin/repositories"],
       ["Blob stores", "/admin/blob-stores"],
       ["System", "/admin/system"],
+      ["Audit log", "/admin/audit"],
     ]);
     // One user's page is among the users.
     expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([
@@ -93,6 +94,7 @@ describe("the shell", () => {
       null,
       null,
       null,
+      null,
     ]);
   });
 
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -87,11 +87,16 @@ describe("the navigation as it is", () => {
       ["manageRepositories", "/admin/repositories"],
       ["blobStores", "/admin/blob-stores"],
       ["system", "/admin/system"],
+      ["audit", "/admin/audit"],
     ]);
     // How people sign in is security's, not a setting's (spec 4.3).
     expect(administration({ ...ADMIN, permissions: ["admin:security:read"] })).toEqual([
       ["authentication", "/admin/authentication"],
     ]);
+    // The audit log is an area of its own (spec 9).
+    expect(administration({ ...ADMIN, permissions: ["admin:audit:read"] })).toEqual([
+      ["audit", "/admin/audit"],
+    ]);
     // What outbound TLS trusts is an area of its own (spec 6).
     expect(administration({ ...ADMIN, permissions: ["admin:certificates:read"] })).toEqual([
       ["certificates", "/admin/certificates"],
```

Change `frontend/src/components/security.test.tsx`:

```diff
@@ -129,12 +129,12 @@ describe("permissions as rows (A2)", () => {
 
   test("what the lists cannot say is typed, and stays as it was typed (A3)", async () => {
     const user = userEvent.setup();
-    renderUi(<Rows initial={["repository:maven", "admin:audit:read"]} />);
+    renderUi(<Rows initial={["repository:maven", "admin:jobs:read"]} />);
 
     expect(within(row(1)).getByLabelText("About")).toHaveValue("typed");
     expect(within(row(1)).getByLabelText("Pattern")).toHaveValue("repository:maven");
     expect(row(1)).toHaveTextContent("Whatever this pattern matches.");
-    expect(patterns()).toEqual(["repository:maven", "admin:audit:read"]);
+    expect(patterns()).toEqual(["repository:maven", "admin:jobs:read"]);
 
     // Typing a pattern that a row could say does not turn the field into lists under
     // the hands that are typing it.
```

Change `frontend/src/screens/security.test.tsx`:

```diff
@@ -53,7 +53,7 @@ const ROLES = [
   }),
   role("deployers", {
     description: "May deploy releases",
-    permissions: ["repository:maven:releases:add", "admin:audit:read"],
+    permissions: ["repository:maven:releases:add", "admin:jobs:read"],
     roles: ["anonymous"],
   }),
 ];
@@ -851,7 +851,7 @@ describe("a role", () => {
     // A permission this UI has no lists for is there as it was typed.
     expect(
       within(screen.getByRole("group", { name: "Permission 2" })).getByLabelText("Pattern"),
-    ).toHaveValue("admin:audit:read");
+    ).toHaveValue("admin:jobs:read");
     // A role does not contain itself, so it is not offered itself.
     expect(await screen.findByRole("checkbox", { name: "anonymous" })).toBeChecked();
     expect(screen.queryByRole("checkbox", { name: "deployers" })).toBeNull();
@@ -862,7 +862,7 @@ describe("a role", () => {
     await waitFor(() => expect(notices()).toHaveTextContent("Saved the role deployers."));
     expect(of(calls, "PUT")[0]?.body).toEqual({
       description: "May deploy releases",
-      permissions: ["repository:maven:releases:add", "admin:audit:read"],
+      permissions: ["repository:maven:releases:add", "admin:jobs:read"],
       roles: ["anonymous"],
     });
     await waitFor(() => expect(calls.some((call) => call.path === "/auth/session")).toBe(true));
@@ -1014,7 +1014,7 @@ describe("anonymous access (A9)", () => {
     expect(screen.getByText("Browse in every repository.")).toBeVisible();
     expect(screen.getByText("Read in every repository.")).toBeVisible();
     // Not what a visitor is never allowed, whatever the roles say.
-    expect(screen.queryByText("admin:audit:read")).toBeNull();
+    expect(screen.queryByText("admin:jobs:read")).toBeNull();
     await expectAccessible();
   });
 
```

Change `frontend/src/lib/account.test.ts`:

```diff
@@ -70,7 +70,7 @@ describe("a permission pattern", () => {
     "admin",
     "admin:users",
     "repository:maven:releases:publish", // an action this UI does not know
-    "admin:audit:read", // an area this UI does not know
+    "admin:jobs:read", // an area this UI does not know
     "admin:users:read:more",
     "*:users:read",
     "metrics:read",
```

- [ ] **Step 2: Run them to verify they fail**

Run (in `frontend/`): `pnpm vitest run src/screens/audit.test.tsx src/components/shell.test.tsx src/lib/navigation.test.ts src/components/security.test.tsx src/screens/security.test.tsx src/lib/account.test.ts`
Expected: `audit.test.tsx` does not load (there is no `./audit` yet); 2 failed, 169 passed: the navigation has no Audit log.

- [ ] **Step 3: Write the code, the guide and the spec's rows**

Change `frontend/src/lib/api/schema.d.ts`:

```diff
@@ -4,6 +4,68 @@
  */
 
 export interface paths {
+    "/api/v1/audit": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * List Records
+         * @description The records, newest first, a page at a time.
+         */
+        get: operations["list_records_api_v1_audit_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/audit/export": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /**
+         * Export Records
+         * @description Every record the filters give, newest first, as JSON Lines or CSV: streamed, a
+         *     record a line, however many there are.
+         */
+        get: operations["export_records_api_v1_audit_export_get"];
+        put?: never;
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
+    "/api/v1/audit/retention": {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        /** Read Retention */
+        get: operations["read_retention_api_v1_audit_retention_get"];
+        /**
+         * Set Retention
+         * @description How many days a record is kept: the hourly job removes older ones.
+         */
+        put: operations["set_retention_api_v1_audit_retention_put"];
+        post?: never;
+        delete?: never;
+        options?: never;
+        head?: never;
+        patch?: never;
+        trace?: never;
+    };
     "/api/v1/auth-sources": {
         parameters: {
             query?: never;
@@ -1170,6 +1232,37 @@ export interface components {
             /** Size */
             size: number;
         };
+        /** AuditRecordOut */
+        AuditRecordOut: {
+            /** Actor */
+            actor: string | null;
+            /** Address */
+            address: string | null;
+            /**
+             * At
+             * Format: date-time
+             */
+            at: string;
+            /** Changes */
+            changes: {
+                [key: string]: unknown;
+            } | null;
+            /** Event */
+            event: string;
+            /**
+             * Id
+             * Format: uuid
+             */
+            id: string;
+            /** Method */
+            method: string | null;
+            /** Request Id */
+            request_id: string | null;
+            /** Target Kind */
+            target_kind: string | null;
+            /** Target Name */
+            target_name: string | null;
+        };
         /** BaseUrl */
         BaseUrl: {
             /** Base Url */
@@ -1531,6 +1624,17 @@ export interface components {
             /** Ids */
             ids: string[];
         };
+        /** Page[AuditRecordOut] */
+        Page_AuditRecordOut_: {
+            /** Items */
+            items: components["schemas"]["AuditRecordOut"][];
+            /** Limit */
+            limit: number;
+            /** Offset */
+            offset: number;
+            /** Total */
+            total: number;
+        };
         /** Page[BlobStoreOut] */
         Page_BlobStoreOut_: {
             /** Items */
@@ -1910,6 +2014,11 @@ export interface components {
             /** Version */
             version: string;
         };
+        /** Retention */
+        Retention: {
+            /** Audit Retention Days */
+            audit_retention_days: number;
+        };
         /** RoleContent */
         RoleContent: {
             /**
@@ -2341,6 +2450,143 @@ export interface components {
 }
 export type $defs = Record<string, never>;
 export interface operations {
+    list_records_api_v1_audit_get: {
+        parameters: {
+            query?: {
+                since?: string | null;
+                until?: string | null;
+                actor?: string | null;
+                event?: string | null;
+                target?: string | null;
+                target_kind?: string | null;
+                limit?: number;
+                offset?: number;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Page_AuditRecordOut_"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    export_records_api_v1_audit_export_get: {
+        parameters: {
+            query?: {
+                format?: "jsonl" | "csv";
+                since?: string | null;
+                until?: string | null;
+                actor?: string | null;
+                event?: string | null;
+                target?: string | null;
+                target_kind?: string | null;
+            };
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": unknown;
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    read_retention_api_v1_audit_retention_get: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody?: never;
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Retention"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
+    set_retention_api_v1_audit_retention_put: {
+        parameters: {
+            query?: never;
+            header?: never;
+            path?: never;
+            cookie?: never;
+        };
+        requestBody: {
+            content: {
+                "application/json": components["schemas"]["Retention"];
+            };
+        };
+        responses: {
+            /** @description Successful Response */
+            200: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["Retention"];
+                };
+            };
+            /** @description Any error. */
+            default: {
+                headers: {
+                    [name: string]: unknown;
+                };
+                content: {
+                    "application/json": components["schemas"]["ErrorResponse"];
+                };
+            };
+        };
+    };
     list_sources_api_v1_auth_sources_get: {
         parameters: {
             query?: {
```

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -61,6 +61,10 @@ export type Redirect = Schemas["Redirect"];
 /** A format the server has: its types, and the public repository a new proxy is given. */
 export type FormatOut = Schemas["FormatOut"];
 export type BlobStoreCreate = Schemas["BlobStoreCreate"];
+/** A change of configuration or security, or a sign-in, as the audit log keeps it (spec 9). */
+export type AuditRecordOut = Schemas["AuditRecordOut"];
+/** How many days the audit log keeps a record. */
+export type Retention = Schemas["Retention"];
 /** A certificate outbound TLS trusts besides the usual authorities (spec 6). */
 export type CertificateOut = Schemas["CertificateOut"];
 /** A certificate as a person checks it: what a host presented, before it is trusted. */
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -32,6 +32,7 @@ export const NEW_REPOSITORY = "/admin/repositories/~new" as Route;
 export const BLOB_STORES = "/admin/blob-stores" as Route;
 export const CERTIFICATES = "/admin/certificates" as Route;
 export const SYSTEM = "/admin/system" as Route;
+export const AUDIT = "/admin/audit" as Route;
 
 const segments = (path: string) => path.split("/").filter((segment) => segment !== "");
 const encoded = (path: string) => segments(path).map(encodeURIComponent).join("/");
@@ -71,6 +72,11 @@ export function searchHref(wanted: Record<string, string | undefined>): Route {
 }
 
 /** A page of a list that has numbered pages. The first has no number in its address. */
+/** The audit log, with the filters asked, at a page. */
+export function auditHref(filters: Record<string, string | undefined>, page: number): Route {
+  return withQuery(AUDIT, { ...filters, page: page > 1 ? String(page) : undefined });
+}
+
 export function pageHref(list: Route, page: number): Route {
   return withQuery(list, { page: page > 1 ? String(page) : undefined });
 }
```

Change `frontend/src/lib/administration.ts`:

```diff
@@ -6,8 +6,9 @@
  */
 import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
 
-import { api } from "@/lib/api/client";
+import { API_PREFIX, api } from "@/lib/api/client";
 import type {
+  AuditRecordOut,
   BlobStoreCreate,
   BlobStoreOut,
   CertificateOut,
@@ -19,6 +20,7 @@ import type {
   RepositoryCreate,
   RepositoryOut,
   RepositoryUpdate,
+  Retention,
   SettingsOut,
   SigningKeyGenerate,
   SigningKeyImport,
@@ -245,6 +247,68 @@ export function useDeleteCertificate() {
   });
 }
 
+// --- The audit log (spec 9) -------------------------------------------------------------------
+
+const AUDIT = "audit";
+const DAY = 24 * 60 * 60 * 1000;
+
+/** What a person filters the records by, as the screen's address holds it: days, not times. */
+export type AuditFilters = Partial<
+  Record<"event" | "actor" | "target" | "since" | "until", string>
+>;
+
+/** The filters as the API takes them: a day from its start, until the end of the last one, in UTC. */
+function auditQuery(filters: AuditFilters): Record<string, string | undefined> {
+  const day = (text: string | undefined, after: number) => {
+    const start = text && /^\d{4}-\d{2}-\d{2}$/.test(text) ? Date.parse(`${text}T00:00:00Z`) : NaN;
+    return Number.isNaN(start) ? undefined : new Date(start + after).toISOString();
+  };
+  return {
+    event: filters.event || undefined,
+    actor: filters.actor || undefined,
+    target: filters.target || undefined,
+    since: day(filters.since, 0),
+    until: day(filters.until, DAY),
+  };
+}
+
+export function useAuditRecords(page: number, filters: AuditFilters) {
+  const query = auditQuery(filters);
+  return useQuery({
+    queryKey: [AUDIT, "records", page, query],
+    queryFn: () => api.get<Page<AuditRecordOut>>("/audit", { query: { ...paged(page), ...query } }),
+  });
+}
+
+/** Where the records the filters give are downloaded, every one of them. */
+export function auditExportHref(format: "jsonl" | "csv", filters: AuditFilters): string {
+  const search = new URLSearchParams({ format });
+  for (const [name, value] of Object.entries(auditQuery(filters))) {
+    if (value) search.set(name, value);
+  }
+  return `${API_PREFIX}/audit/export?${search.toString()}`;
+}
+
+export function useAuditRetention() {
+  return useQuery({
+    queryKey: [AUDIT, "retention"],
+    queryFn: () => api.get<Retention>("/audit/retention"),
+  });
+}
+
+export function useSetAuditRetention() {
+  const client = useQueryClient();
+  return useMutation({
+    mutationFn: (days: number) =>
+      api.put<Retention>("/audit/retention", { audit_retention_days: days }),
+    onSuccess: (kept) => {
+      client.setQueryData([AUDIT, "retention"], kept);
+      // The change is a record of its own.
+      return client.invalidateQueries({ queryKey: [AUDIT, "records"] });
+    },
+  });
+}
+
 // --- The installation -----------------------------------------------------------------------
 
 export function useInformation() {
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -7,6 +7,7 @@ import {
   Boxes,
   HardDrive,
   KeyRound,
+  ScrollText,
   Search,
   Server,
   ShieldCheck,
@@ -21,6 +22,7 @@ import type { Route } from "next";
 import type { SessionInfo } from "@/lib/api/types";
 import {
   ANONYMOUS_ACCESS,
+  AUDIT,
   AUTHENTICATION,
   BLOB_STORES,
   CERTIFICATES,
@@ -43,7 +45,8 @@ export type ItemKey =
   | "certificates"
   | "manageRepositories"
   | "blobStores"
-  | "system";
+  | "system"
+  | "audit";
 
 export type NavItem = {
   /** Its name is the message `nav.items.<key>`. */
@@ -119,6 +122,7 @@ export const NAVIGATION: readonly NavArea[] = [
         permission: "admin:blobstores:read",
       },
       { key: "system", href: SYSTEM, icon: Server, permission: "admin:settings:read" },
+      { key: "audit", href: AUDIT, icon: ScrollText, permission: "admin:audit:read" },
     ],
   },
 ];
```

Change `frontend/src/lib/patterns.ts`:

```diff
@@ -18,6 +18,9 @@ export const ADMIN_AREAS = [
   "settings",
   "blobstores",
   "repositories",
+  "security",
+  "certificates",
+  "audit",
 ] as const;
 export const ADMIN_ACTIONS = ["read", "write"] as const;
 /** What a token that may only read is limited to. */
```

Create `frontend/src/screens/audit.tsx`:

```tsx
"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Pager, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { SelectField } from "@/components/ui/inputs";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import {
  AT_ONCE,
  auditExportHref,
  useAuditRecords,
  useAuditRetention,
  useSetAuditRetention,
  type AuditFilters,
} from "@/lib/administration";
import type { AuditRecordOut } from "@/lib/api/types";
import { auditHref, pageOf } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
/** The kinds of event a person filters by: what each record's event starts with. */
const KINDS = [
  "sign_in",
  "session",
  "user",
  "role",
  "token",
  "connected_app",
  "oauth_client",
  "source",
  "setting",
  "certificate",
  "repository",
  "signing_key",
  "blob_store",
] as const;
const FILTERS = ["event", "actor", "target", "since", "until"] as const;

function filtersOf(search: { get(name: string): string | null }): AuditFilters {
  return Object.fromEntries(
    FILTERS.map((name) => [name, search.get(name) ?? ""]).filter(([, value]) => value !== ""),
  ) as AuditFilters;
}

/** A value as a record holds it, in a line: a name as it is, anything else as JSON. */
function shown(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** What one record changed: each field, before and after. */
function Changes({ entry }: { entry: AuditRecordOut }) {
  const t = useTranslations("audit");
  const changed = Object.entries(entry.changes ?? {}) as [
    string,
    { before?: unknown; after?: unknown },
  ][];
  if (changed.length === 0) return <span className="text-fg-subtle">{t("nothing")}</span>;
  return (
    <details>
      <summary className="cursor-pointer text-neon-cyan">
        {t("changed", { count: changed.length })}
      </summary>
      <dl className="mt-2 flex flex-col gap-1 font-mono text-xs">
        {changed.map(([field, { before, after }]) => (
          <div key={field} className="break-all">
            <dt className="inline text-fg-muted">{t("field", { field })}</dt>
            <dd className="inline">
              {t("fromTo", { before: shown(before), after: shown(after) })}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

/** Which records: of a kind of event, by whom, about what, and when. */
function Filters({ asked }: { asked: AuditFilters }) {
  const t = useTranslations("audit");
  const router = useRouter();
  const [typed, setTyped] = useState<AuditFilters>(asked);

  function submit(event: FormEvent) {
    event.preventDefault();
    router.push(auditHref(typed, 1));
  }

  const field = (name: (typeof FILTERS)[number]) => ({
    value: typed[name] ?? "",
    onChange: (event: { target: { value: string } }) =>
      setTyped({ ...typed, [name]: event.target.value }),
  });

  return (
    <form
      onSubmit={submit}
      className="grid gap-4 sm:grid-cols-3 lg:grid-cols-6 lg:items-end"
      role="search"
      aria-label={t("filters")}
      noValidate
    >
      <SelectField
        label={t("fields.event")}
        choices={[
          { value: "", label: t("everyEvent") },
          ...KINDS.map((kind) => ({ value: kind, label: t(`kinds.${kind}`) })),
        ]}
        {...field("event")}
      />
      <TextField label={t("fields.actor")} spellCheck={false} {...field("actor")} />
      <TextField label={t("fields.target")} spellCheck={false} {...field("target")} />
      <TextField label={t("fields.since")} type="date" {...field("since")} />
      <TextField label={t("fields.until")} type="date" {...field("until")} />
      <div>
        <Button type="submit" variant="primary">
          {t("apply")}
        </Button>
      </div>
    </form>
  );
}

/** How many days records are kept: changed by whoever may, shown to whoever may read them. */
function Retention({ mayWrite }: { mayWrite: boolean }) {
  const t = useTranslations("audit");
  const notify = useNotify();
  const kept = useAuditRetention();
  const change = useSetAuditRetention();
  const [typed, setTyped] = useState<string | null>(null);
  const refused = refusalsOf(change.error, ["audit_retention_days"]);

  if (kept.isError) return <ErrorState error={kept.error} onRetry={() => void kept.refetch()} />;
  if (!kept.data) return <LoadingState className="p-4" />;
  const text = typed ?? String(kept.data.audit_retention_days);
  const days = Number(text);
  const wrong = /^[0-9]{1,5}$/.test(text) && days >= 1 && days <= 36500 ? undefined : t("daysRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (wrong) return;
    change.mutate(days, {
      onSuccess: (saved) => {
        notify(t("retentionSaved", { count: saved.audit_retention_days }));
        setTyped(null);
      },
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-end gap-4" noValidate>
      <TextField
        label={t("fields.days")}
        hint={t("hints.days")}
        className="w-48"
        inputMode="numeric"
        disabled={!mayWrite}
        value={text}
        error={wrong ?? refused.at.audit_retention_days}
        onChange={(event) => setTyped(event.target.value)}
      />
      {mayWrite ? (
        <Button type="submit" busy={change.isPending}>
          {t("saveRetention")}
        </Button>
      ) : null}
      {change.isError && refused.elsewhere ? <ErrorState error={change.error} /> : null}
    </form>
  );
}

/** The audit log (spec 9): who changed what, and every sign-in, newest first. */
export function AuditScreen() {
  const t = useTranslations("audit");
  const session = useSession();
  const search = useSearchParams();
  const page = pageOf(search);
  const asked = filtersOf(search);
  const listed = useAuditRecords(page, asked);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:audit:write");
  const pages = listed.data === undefined ? undefined : Math.ceil(listed.data.total / AT_ONCE);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="p-6">
        {/* Keyed by what was asked: a link to other filters starts the form anew. */}
        <Filters key={search.toString()} asked={asked} />
        <div className="mt-4 flex flex-wrap gap-3">
          {(["jsonl", "csv"] as const).map((format) => (
            <Button key={format} asChild size="sm">
              <a href={auditExportHref(format, asked)} download>
                <Download aria-hidden="true" className="size-4" />
                {t(`export.${format}`)}
              </a>
            </Button>
          ))}
        </div>
      </Panel>
      <Panel>
        {listed.isError ? (
          <ErrorState error={listed.error} onRetry={() => void listed.refetch()} className="m-4" />
        ) : !listed.data ? (
          <LoadingState />
        ) : listed.data.items.length === 0 ? (
          <p className="p-6 text-fg-muted">{t("none")}</p>
        ) : (
          <>
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.at")}</Th>
                  <Th>{t("columns.actor")}</Th>
                  <Th>{t("columns.event")}</Th>
                  <Th>{t("columns.target")}</Th>
                  <Th>{t("columns.address")}</Th>
                  <Th>{t("columns.changes")}</Th>
                </tr>
              </thead>
              <tbody>
                {listed.data.items.map((entry) => (
                  <tr key={entry.id} className="align-top hover:bg-raised">
                    <Td className="whitespace-nowrap">
                      <Time value={entry.at} />
                    </Td>
                    <Td>
                      <span className="block">{entry.actor ?? t("nobody")}</span>
                      {entry.method ? (
                        <span className="text-xs text-fg-subtle">
                          {t("method", { method: entry.method })}
                        </span>
                      ) : null}
                    </Td>
                    <Td className="font-mono text-xs">{entry.event}</Td>
                    <Td className="break-all">
                      {entry.target_name === null ? (
                        "—"
                      ) : (
                        <>
                          <span className="block text-xs text-fg-subtle">{entry.target_kind}</span>
                          {entry.target_name}
                        </>
                      )}
                    </Td>
                    <Td className="font-mono text-xs">{entry.address ?? "—"}</Td>
                    <Td className="min-w-48">
                      <Changes entry={entry} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pager page={page} pages={pages ?? 1} hrefFor={(target) => auditHref(asked, target)} />
          </>
        )}
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("retentionTitle")}</h2>
        <p className="mb-4 text-fg-muted">{t("retentionIntro")}</p>
        <Retention mayWrite={mayWrite} />
      </Panel>
    </div>
  );
}
```

Create `frontend/src/app/(shell)/admin/audit/page.tsx`:

```tsx
import type { Metadata } from "next";

import { AuditScreen } from "@/screens/audit";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.audit.title };

export default function Page() {
  return <AuditScreen />;
}
```

Change `frontend/messages/en.json`:

```diff
@@ -25,7 +25,8 @@
       "certificates": "Certificates",
       "manageRepositories": "Manage repositories",
       "blobStores": "Blob stores",
-      "system": "System"
+      "system": "System",
+      "audit": "Audit log"
     }
   },
   "theme": {
@@ -392,7 +393,10 @@
       "tokens": "API tokens",
       "settings": "Settings",
       "blobstores": "Blob stores",
-      "repositories": "Repositories"
+      "repositories": "Repositories",
+      "security": "Sign-in",
+      "certificates": "Certificates",
+      "audit": "Audit log"
     },
     "add": "Add a permission",
     "remove": "Remove permission {number}",
@@ -425,7 +429,10 @@
         "tokens": "everybody's API tokens",
         "settings": "the settings",
         "blobstores": "the blob stores",
-        "repositories": "the repositories"
+        "repositories": "the repositories",
+        "security": "how people sign in",
+        "certificates": "the trusted certificates",
+        "audit": "the audit log"
       },
       "other": "Whatever this pattern matches."
     }
@@ -1190,5 +1197,62 @@
     },
     "allow": "Allow",
     "refuse": "Refuse"
+  },
+  "audit": {
+    "title": "Audit log",
+    "intro": "Who changed what, and when: users, roles, tokens, sign-in sources, settings, certificates, repositories and blob stores; and every sign-in. Nothing here can be changed or deleted.",
+    "filters": "Filter the records",
+    "fields": {
+      "event": "Event",
+      "actor": "Who",
+      "target": "About",
+      "since": "From (UTC)",
+      "until": "Until (UTC, that day too)",
+      "days": "Days kept"
+    },
+    "hints": {
+      "days": "Older records are removed every hour. At least 1."
+    },
+    "everyEvent": "Every event",
+    "kinds": {
+      "sign_in": "Sign-in",
+      "session": "Sign-out",
+      "user": "Users",
+      "role": "Roles",
+      "token": "API tokens",
+      "connected_app": "Connected apps",
+      "oauth_client": "OAuth clients",
+      "source": "Sign-in sources",
+      "setting": "Settings",
+      "certificate": "Certificates",
+      "repository": "Repositories",
+      "signing_key": "Signing keys",
+      "blob_store": "Blob stores"
+    },
+    "apply": "Filter",
+    "export": {
+      "jsonl": "Export as JSON Lines",
+      "csv": "Export as CSV"
+    },
+    "none": "No records.",
+    "columns": {
+      "at": "When",
+      "actor": "Who",
+      "event": "Event",
+      "target": "About",
+      "address": "From",
+      "changes": "What changed"
+    },
+    "nothing": "—",
+    "field": "{field}: ",
+    "fromTo": "{before} → {after}",
+    "nobody": "Nobody signed in",
+    "method": "by {method}",
+    "changed": "{count, plural, one {# field} other {# fields}}",
+    "retentionTitle": "How long records are kept",
+    "retentionIntro": "A record older than this is removed. Exports keep them as long as you do.",
+    "daysRule": "A number of days from 1 to 36500.",
+    "saveRetention": "Save",
+    "retentionSaved": "{count, plural, one {Records are kept # day.} other {Records are kept # days.}}"
   }
 }
```

Change `docs/web-ui.md`:

```diff
@@ -81,6 +81,11 @@ repositories, blob stores and the installation's own settings.
     Fetch asks a server what it presents, its own certificate first; a certificate
     is trusted after a question that shows its whole fingerprint, to check with
     whoever runs the server. One can also be pasted in PEM, and removed.
+  - **Audit log** lists who changed what and every sign-in, newest first: when, who
+    and how they signed in, the event, what it was about and the address it came
+    from; each opens to what changed, before and after. Filter by a kind of event,
+    who, what it was about, and the days; export what the filters give as JSON Lines
+    or CSV. Whoever may change it sets how many days records are kept.
   - **Manage repositories** lists every repository as it is set up. A new one is made
     on one page: choose the format and the type, and the page shows what that
     combination has. A hosted repository has a deployment policy; a proxy has its
```

Change `docs/administration.md`:

```diff
@@ -235,6 +235,43 @@ Certificates, or at `/api/v1/certificates`, and is trusted by all of them at onc
 The full API is described at `/api/docs`. The page is served with its own script and
 stylesheet, and asks nothing of another host.
 
+### Audit log
+
+Every change of configuration or security, and every sign-in, is recorded: under
+Administration, Audit log, or at `GET /api/v1/audit`, with `admin:audit:read`.
+
+- **What is recorded.** Users made, changed, deleted, and their passwords set
+  (`user.created`, `user.updated`, `user.deleted`, `user.password_changed`); roles;
+  API tokens made and revoked; applications approved and revoked, and OAuth clients
+  registered; sign-in sources; every setting (`setting.changed`, the order of the
+  sources among them); trusted certificates; repositories, their caches, indexes and
+  signing keys; blob stores. And sign-in: `sign_in.succeeded` (the web UI, a provider,
+  a directory), `sign_in.failed` (whatever was presented: a password, a token, a
+  provider's answer), `sign_in.throttled`, `sign_in.refused` (a trusted header from
+  elsewhere), and `session.signed_out`. A package client's password at each request is
+  not a sign-in: only its failures are recorded.
+- **What a record says.** When; who (their user name, or nobody); how they signed in
+  (`session`, `password`, `token`, `oauth` for an application a person approved,
+  `header`, `anonymous`, or `system` for what the server does itself, as the hourly
+  check of a directory); their address; the event; what it was about, by its kind and
+  its name; what changed, each field before and after; and the request's ID, which the
+  logs carry too. A secret (a password, a client secret, a remote's secret, a private
+  key) is said by its name, as `[redacted]`: its value is never recorded.
+- **With the change, or not at all.** A record is kept in the change's own transaction:
+  a change that is refused or fails leaves none.
+- **Nothing edits or deletes a record.** No route changes one; the hourly job removes
+  those older than the days kept: 365, unless set at `PUT /api/v1/audit/retention`
+  (`{"audit_retention_days": 90}`, at least 1) with `admin:audit:write`. The change is
+  a record of its own.
+- **Filters.** `since` and `until` (times; a date alone is that day's start, in UTC);
+  `actor`; `event`, an event (`user.created`) or a kind of event (`user`); `target`, a
+  name, and `target_kind`. Newest first, a page at a time (`limit`, `offset`).
+- **Export.** `GET /api/v1/audit/export?format=jsonl` (JSON Lines) or `format=csv`, with
+  the same filters: every record they give, streamed. A CSV cell that a spreadsheet
+  would take for a formula (it starts with `=`, `+`, `-` or `@`) is written with a `'`
+  before it. Export what you must keep longer than the days kept.
+- **MCP.** A tool's change is recorded by the route it calls, as the token's user.
+
 ### What an administrator may be given
 
 The built-in `admin` role holds `*`, which is everything. A role of your own can hold
```

Change `docs/superpowers/specs/2026-10-19-identity-audit-selectors-design.md`:

```diff
@@ -202,6 +202,21 @@ Settled here, by the designer:
 - A setting `audit_retention_days` (365 unless set; at least 1): the hourly job removes older records.
 - The screen (Administration, Audit log): the records, filtered, a page at a time, each opening to its changes; the export.
 
+### Settled while building plan 15f
+
+| # | What | Why |
+| --- | --- | --- |
+| A1 | A record is a row of `audit_records` (id, at, actor, method, address, event, target_kind, target_name, changes as JSONB, request_id), indexed by time, actor, event, and target's kind and name. `system/audit.py`'s `record(db, event, target, changes)` adds it to the caller's session, kept by its commit (E7). | Section 9. |
+| A2 | Who, how and from where come from the request: `audit.ContextMiddleware`, inside the request's ID and the proxies (15e), keeps the ID and the client's address; `audit.identified(principal)`, called where a principal is made (`_identify`, the MCP endpoint's, a session started), the user's name and how they signed in; `audit.acting(name, method)` where there is no principal (a package client signing in by password). Nobody identified: no actor, no method. Outside a request: `system`. | Section 9: the caller and the request from the request's context. |
+| A3 | `method` is the principal's (`session`, `password`, `token`, `header`, `anonymous`), `oauth` for a token an application was given by a person's approval, `system` for the server's own work (the hourly directory check). | Section 9's list. |
+| A4 | Events are `<kind>.<what happened>`: `user.created`, `user.updated`, `user.deleted`, `user.password_changed`, `role.*`, `token.created`, `token.revoked`, `connected_app.approved`, `connected_app.revoked`, `oauth_client.registered`, `source.*`, `setting.changed`, `certificate.trusted`, `certificate.removed`, `repository.*` with `cache_invalidated` and `index_rebuilt`, `signing_key.imported`, `signing_key.generated`, `blob_store.*`, `sign_in.succeeded`, `sign_in.failed`, `sign_in.throttled`, `sign_in.refused`, `session.signed_out`. A token is named `<user>/<token>`, an approval `<user>/<client>`. What a repository holds (uploads, deletes) is not configuration, and not recorded. | Section 9: the routes that log a change today, and sign-in. |
+| A5 | `changes` is `audit.diff(before, after, secrets=...)`: each field that differs, as the API shows it, `{before, after}`; ids and times left out, and what is not configuration (a source's user count, a repository's remote status, a certificate's PEM). A secret given anew is said by its name, `[redacted]`; a field named as a secret is (`password`, `bind_password`, `client_secret`, `secret`, `private_key`, `passphrase`, `token`), wherever it is. | Section 9: a secret is `[redacted]`. |
+| A6 | A setting is recorded by `audit.set_setting`, only when its value changes; the order of the sources is the setting `source_order`. | Section 9: `setting_changed`. |
+| A7 | Sign-in: `sign_in.succeeded` when a session starts (a password, a provider), with its source; `sign_in.failed` at each failed check of a password, a token or a provider's answer, kept by a commit before the error is answered; `sign_in.throttled`; `sign_in.refused` for a trusted header from elsewhere; `session.signed_out`. A package client's password accepted at each request is not a sign-in, and not recorded; a client signing in for a token (`npm login`) is `token.created`. A first sign-in is `user.created`, and roles a source's groups give or take back are `user.updated` (`roles_from_groups`). | Section 9: succeeded, failed, throttled, by every source; D4's refresh. |
+| A8 | `GET /api/v1/audit` filters by `since`, `until` (a time without its zone is UTC's), `actor`, `event` (an event, or a kind: `user`), `target` and `target_kind`; newest first. `GET /api/v1/audit/export?format=jsonl|csv` streams what the filters give, in a session of its own, 500 at a time; a CSV cell starting with `=`, `+`, `-`, `@`, a tab or a return is written after a `'`. | Section 9; a name typed at sign-in must not run in a spreadsheet. |
+| A9 | `audit_retention_days` (365; 1 to 36500) is read and set at `/api/v1/audit/retention`: reading with `admin:audit:read`, setting with `admin:audit:write`, which no settings permission gives. The hourly job `audit_prune`, one container at a time, removes older records. No route changes or deletes a record. | D3; whoever may change settings must not be able to shorten the record of it. |
+| A10 | The screen is Administration, Audit log, last: its filters in its address (a kind of event, who, about what, the days, in UTC, the last one included), its records a page at a time, each opening to what changed; the export of what the filters give; the days kept. The role editor's areas gain `security`, `certificates` and `audit`. | Section 9; 15a and 15c's areas were missing from the editor's lists. |
+
 ## 10. Content selectors (plans 15g, 15h)
 
 - `content_selectors`: name, description, expression.
```

- [ ] **Step 4: Run the tests to verify they pass, and every test**

Run (in `frontend/`): `pnpm vitest run src/screens/audit.test.tsx src/components/shell.test.tsx src/lib/navigation.test.ts src/components/security.test.tsx src/screens/security.test.tsx src/lib/account.test.ts && pnpm lint && pnpm typecheck`
Expected: 179 passed; `All matched files use Prettier code style!`; the types check.

Then (in `backend/`): `uv run pytest -q tests/test_documents.py`
Expected: 147 passed.

Then every test: (in `backend/`) `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`; (in `frontend/`) `pnpm vitest run`
Expected: Ruff: `462 files already formatted`, `All checks passed!`; pytest: 4336 passed, 2 skipped, 117 deselected (the `docker` tests); Vitest: 928 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend docs
git commit -m "feat(ui): the Audit log: who changed what and every sign-in, filtered, opened to what changed, exported; the days kept; docs: the audit log, and what plan 15f settled"
```
