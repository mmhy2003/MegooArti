# Proxy and Group Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proxy repositories that fetch from a remote on a miss, cache what they fetch, keep serving it when the remote is down and remember what the remote lacks; and group repositories that present several repositories behind one URL.

**Architecture:** A proxy engine and a group engine sit beside the hosted handler behind one dispatcher. The proxy engine downloads a missing file completely through the storage facade's `stage`, records it with a new unchecked `cache` operation, then serves it like any stored asset. Remote credentials are sealed with a key from the environment or the data directory. Blocking state and the negative cache live in the database so every container shares them.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, Alembic, httpx (outbound), cryptography (Fernet), pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-10-07-storage-repositories-design.md](../specs/2026-10-07-storage-repositories-design.md), sections 5.1, 6, 8, 8.1, 9 and 10. Business requirements: [docs/BRD.md](../../BRD.md) REP-5 to REP-13, FMT-8 (proxy, group), NFR-7.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | The storage facade gains `cache(path, staged, ...)`, which records content with no permission or policy check and `created_by = "proxy"`. It refuses to run on anything but a proxy repository. | A reader with only `read` triggers proxy caching. The check that matters, `read` on the proxy or on the group in front of it, has already happened. |
| P2 | The repository service accepts a remote secret only as `secrets_box.Sealed`, never a plain string. The API seals it. | The "encrypted at rest" rule is enforced by a type, not by every caller remembering. |
| P3 | A remote `404` for a file that is already cached keeps the cached copy and marks it verified. | An artifact manager does not lose a file because its upstream dropped it. |
| P4 | Only transport failures, `5xx` and `429` count toward automatic blocking. Other unexpected statuses (`401`, `403`, …) fail the request with `502` but do not block. | A misconfigured credential should surface as an error on each request, not hide behind a block. |
| P5 | A group whose members all fail or lack the path answers `404`. | Matches Nexus, and a group's contract is "the first member that has it". |
| P6 | A request that changes state and carries `Sec-Fetch-Site: cross-site` is refused. | Browsers cache HTTP Basic credentials after the `/repository` challenge; package clients never send this header. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only, one migration head, working `downgrade()`; settings prefixed `MEGOOARTI_` and listed in `README.md`; the standard error envelope; services never commit; no ORM relationships; Python-side defaults on columns the code reads back; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; file and hash work off the event loop; only the security package reads `Principal.patterns`; every route authenticates unless on the open list; content responses always carry the download-only headers; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **Formats and engines do not commit their changes; the route does.** The exceptions are the commits that release a connection before a body moves, and the proxy engine's commits that must outlive a failed request (a recorded failure, a negative-cache entry).
- **Remote secrets are never returned, logged or stored unsealed.** The API reports only whether one is set.
- **Outbound requests** go through the one `httpx.AsyncClient` on `app.state.http`, use only `http` and `https`, and send `Accept-Encoding: identity` so that what is stored is what the remote holds.
- A test must never start an application whose `app.state.sessionmaker` commits for real to the shared test database, and must never contact a real network host: tests replace `app.state.http` with a client wired to an in-process fake remote.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker compose` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **The remote sends fewer bytes than it declared, or drops the connection mid-file.** Nothing should be cached, and the client should get an error or the previous cached copy, never a truncated file (Tasks 5 and 7).
2. **The remote redirects to another host.** The stored credentials must not follow (Task 5).
3. **Many clients ask for the same uncached file at once.** The remote should be asked once (Task 7).
4. **The remote is down and the file is cached but stale.** The cached copy is served, and the remote is not hammered while it is blocked (Task 7).
5. **A group contains a repository the caller could not read directly.** The group's permission decides; and a caller without permission on the group gets nothing, even if they could read a member (Task 8).

---

### Task 1: Sealing secrets

**Files:**
- Create: `backend/src/megooarti/secrets_box.py`
- Modify: `backend/src/megooarti/config.py`
- Modify: `backend/tests/test_config.py`
- Test: `backend/tests/test_secrets_box.py`

**Interfaces:**
- Consumes: `Settings.data_dir`.
- Produces:
  - `Settings.secret_key: str | None = None` (`MEGOOARTI_SECRET_KEY`)
  - `megooarti.secrets_box.Sealed` — a `str` subclass marking ciphertext
  - `seal(settings, plaintext: str) -> Sealed` — the result starts with `enc:v1:`
  - `unseal(settings, stored: str) -> str` — raises `SecretUnreadable`
  - `SecretUnreadable(Exception)`
  - `forget_keys() -> None` — drops cached keys; for tests
  - With no `secret_key`, a key is generated into `<data_dir>/secret.key` on first use and reused afterwards.

- [ ] **Step 1: Install the dependency**

Run in `backend/`: `uv add cryptography`

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_secrets_box.py`:

```python
import os

import pytest

from megooarti import secrets_box
from megooarti.config import Settings
from megooarti.secrets_box import Sealed, SecretUnreadable, seal, unseal

SECRET = "the remote's password ✓"


def settings_in(directory, **overrides) -> Settings:
    return Settings(
        _env_file=None, database_url="postgresql://u:p@db/m", data_dir=directory, **overrides
    )


@pytest.fixture(autouse=True)
def _no_cached_keys():
    secrets_box.forget_keys()
    yield
    secrets_box.forget_keys()


def test_a_sealed_secret_can_be_unsealed(tmp_path):
    settings = settings_in(tmp_path)

    sealed = seal(settings, SECRET)

    assert isinstance(sealed, Sealed)
    assert unseal(settings, sealed) == SECRET


def test_sealed_text_is_marked_differs_each_time_and_hides_the_secret(tmp_path):
    settings = settings_in(tmp_path)

    first, second = seal(settings, SECRET), seal(settings, SECRET)

    assert first.startswith("enc:v1:")
    assert first != second
    assert "password" not in first


def test_a_key_is_generated_once_and_reused_after_a_restart(tmp_path):
    settings = settings_in(tmp_path)
    sealed = seal(settings, SECRET)
    key = (tmp_path / "secret.key").read_bytes()

    secrets_box.forget_keys()  # as after a restart

    assert unseal(settings, sealed) == SECRET
    assert (tmp_path / "secret.key").read_bytes() == key


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_generated_key_is_readable_by_its_owner_only(tmp_path):
    seal(settings_in(tmp_path), SECRET)
    assert (tmp_path / "secret.key").stat().st_mode & 0o777 == 0o600


def test_a_configured_key_is_used_instead_and_no_file_is_written(tmp_path):
    here = settings_in(tmp_path / "one", secret_key="a long random value")
    there = settings_in(tmp_path / "two", secret_key="a long random value")

    sealed = seal(here, SECRET)

    assert unseal(there, sealed) == SECRET
    assert not (tmp_path / "one" / "secret.key").exists()


def test_a_different_key_cannot_unseal(tmp_path):
    sealed = seal(settings_in(tmp_path, secret_key="the first key"), SECRET)

    with pytest.raises(SecretUnreadable):
        unseal(settings_in(tmp_path, secret_key="another key"), sealed)


@pytest.mark.parametrize("stored", ["", "plain text", "enc:v1:", "enc:v1:not-a-token"])
def test_text_that_was_never_sealed_is_unreadable(tmp_path, stored):
    with pytest.raises(SecretUnreadable):
        unseal(settings_in(tmp_path), stored)
```

Append to `backend/tests/test_config.py`:

```python


def test_secret_key_is_unset_by_default_and_read_from_the_environment(monkeypatch):
    assert Settings(_env_file=None, database_url=VALID_URL).secret_key is None

    monkeypatch.setenv("MEGOOARTI_SECRET_KEY", "a long random value")

    assert Settings(_env_file=None, database_url=VALID_URL).secret_key == "a long random value"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_secrets_box.py tests/test_config.py -q`
Expected: `test_secrets_box.py` fails to collect with `cannot import name 'secrets_box'`; the new config test fails with `AttributeError`.

- [ ] **Step 4: Implement**

In `backend/src/megooarti/config.py`, add to `Settings` after `blob_grace_seconds`:

```python
    secret_key: str | None = None
```

`backend/src/megooarti/secrets_box.py`:

```python
"""Sealing of secrets MegooArti must be able to read back, such as remote passwords.

The key is MEGOOARTI_SECRET_KEY when set. Otherwise one is generated into the data
directory on first use. Losing the key makes sealed secrets unreadable.
"""

import base64
import hashlib
import os
import time
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from megooarti.config import Settings

_MARK = "enc:v1:"
_KEY_FILE = "secret.key"


class Sealed(str):
    """Text produced by `seal`. Code that stores a secret accepts only this type."""


class SecretUnreadable(Exception):
    """The stored value was not sealed with the current key."""


def _generated_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Another container may be writing it at this moment: wait for the content.
        for _ in range(50):
            key = path.read_bytes().strip()
            if key:
                return key
            time.sleep(0.1)
        raise
    key = Fernet.generate_key()
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(key)
    return key


@lru_cache(maxsize=8)
def _fernet(secret_key: str | None, data_dir: str) -> Fernet:
    if secret_key:
        # Any text is accepted as the key; hashing gives it the length Fernet needs.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))
    return Fernet(_generated_key(Path(data_dir) / _KEY_FILE))


def _box(settings: Settings) -> Fernet:
    return _fernet(settings.secret_key, str(settings.data_dir))


def seal(settings: Settings, plaintext: str) -> Sealed:
    return Sealed(_MARK + _box(settings).encrypt(plaintext.encode()).decode())


def unseal(settings: Settings, stored: str) -> str:
    if not stored.startswith(_MARK):
        raise SecretUnreadable
    try:
        return _box(settings).decrypt(stored.removeprefix(_MARK).encode()).decode()
    except InvalidToken:
        raise SecretUnreadable from None


def forget_keys() -> None:
    """Drop cached keys, so the next use reads them again. For tests."""
    _fernet.cache_clear()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_secrets_box.py tests/test_config.py -q`
Expected: no failures. On Windows `test_secrets_box.py` reports 9 passed and 1 skipped; on Linux, 10 passed.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(security): seal stored secrets with a configured or generated key"
```

---

### Task 2: Tables for groups and proxy state, and the format's proxy hooks

**Files:**
- Modify: `backend/src/megooarti/repositories/models.py`
- Create: `backend/src/megooarti/migrations/versions/0004_add_proxy_and_group_tables.py`
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/tests/repositories/test_formats.py`
- Test: `backend/tests/repositories/test_proxy_models.py`

**Interfaces:**
- Consumes: `Base`, `Repository`.
- Produces, in `megooarti.repositories.models`:
  - `RepositoryMember(group_id, member_id, position)` — table `repository_members`; use only through Core statements and column selects
  - `ProxyState(repository_id, failures, blocked_until, last_error, last_checked_at)` — table `proxy_state`, one row per proxy repository that has had a failure
  - `NegativeCacheEntry(repository_id, path, expires_at)` — table `negative_cache`
- Produces, on `megooarti.repositories.formats.Format`:
  - `remote_url(self, base: str, path: str) -> str` — generic: `base` + `/` + the path, percent-encoded
  - `is_metadata(self, path: str) -> bool` — generic: `False`

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_proxy_models.py`:

```python
from datetime import UTC, datetime

from sqlalchemy import insert, select

from megooarti.repositories.models import (
    NegativeCacheEntry,
    ProxyState,
    Repository,
    RepositoryMember,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def repository(db, name: str, type: str) -> Repository:
    row = Repository(name=name, name_key=name, format="raw", type=type)
    db.add(row)
    await db.flush()
    return row


async def test_a_group_keeps_its_members_in_order(db):
    group = await repository(db, "all", "group")
    first = await repository(db, "first", "hosted")
    second = await repository(db, "second", "hosted")
    await db.execute(
        insert(RepositoryMember),
        [
            {"group_id": group.id, "member_id": second.id, "position": 1},
            {"group_id": group.id, "member_id": first.id, "position": 0},
        ],
    )

    ordered = await db.scalars(
        select(RepositoryMember.member_id)
        .where(RepositoryMember.group_id == group.id)
        .order_by(RepositoryMember.position)
    )

    assert list(ordered) == [first.id, second.id]


async def test_proxy_state_starts_with_no_failures(db):
    proxy = await repository(db, "mirror", "proxy")
    db.add(ProxyState(repository_id=proxy.id))
    await db.flush()

    state = await db.get(ProxyState, proxy.id)

    assert (state.failures, state.blocked_until, state.last_error) == (0, None, None)


async def test_negative_cache_entries_are_per_repository_and_path(db):
    proxy = await repository(db, "mirror", "proxy")
    db.add(NegativeCacheEntry(repository_id=proxy.id, path="missing/a.bin", expires_at=NOW))
    await db.flush()

    found = await db.get(NegativeCacheEntry, (proxy.id, "missing/a.bin"))

    assert found.expires_at == NOW
```

Append to `backend/tests/repositories/test_formats.py`:

```python


@pytest.mark.parametrize(
    ("base", "path", "expected"),
    [
        ("https://remote.example/files", "a/b.bin", "https://remote.example/files/a/b.bin"),
        ("https://remote.example/files/", "a.bin", "https://remote.example/files/a.bin"),
        (
            "https://remote.example",
            "with space/ünï?.bin",
            "https://remote.example/with%20space/%C3%BCn%C3%AF%3F.bin",
        ),
    ],
)
def test_the_generic_remote_url_is_the_base_plus_the_encoded_path(base, path, expected):
    assert get_format("raw").remote_url(base, path) == expected


def test_the_generic_format_has_no_metadata_paths():
    assert get_format("raw").is_metadata("anything/at/all.xml") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_proxy_models.py tests/repositories/test_formats.py -q`
Expected: `test_proxy_models.py` fails to collect with `cannot import name 'NegativeCacheEntry'`; the four new format tests fail with `AttributeError`.

- [ ] **Step 3: Add the models**

In `backend/src/megooarti/repositories/models.py`, add `Integer` to the `sqlalchemy` import and append:

```python
class RepositoryMember(Base):
    """`group_id` presents `member_id`, at `position` in its order."""

    __tablename__ = "repository_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    # A repository cannot be deleted while a group presents it.
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class ProxyState(Base):
    """How a proxy repository's remote has been behaving. Shared by every container."""

    __tablename__ = "proxy_state"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    failures: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NegativeCacheEntry(Base):
    """A path the remote said it does not have, remembered until `expires_at`."""

    __tablename__ = "negative_cache"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Write the migration**

`backend/src/megooarti/migrations/versions/0004_add_proxy_and_group_tables.py`:

```python
"""add proxy and group tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repository_members",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["repositories.id"],
            name=op.f("fk_repository_members_group_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["repositories.id"],
            name=op.f("fk_repository_members_member_id_repositories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("group_id", "member_id", name=op.f("pk_repository_members")),
    )
    op.create_table(
        "proxy_state",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_proxy_state_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repository_id", name=op.f("pk_proxy_state")),
    )
    op.create_table(
        "negative_cache",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_negative_cache_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repository_id", "path", name=op.f("pk_negative_cache")),
    )


def downgrade() -> None:
    op.drop_table("negative_cache")
    op.drop_table("proxy_state")
    op.drop_table("repository_members")
```

- [ ] **Step 5: Add the format hooks**

In `backend/src/megooarti/repositories/formats.py`, add `from urllib.parse import quote` to the imports and add these two methods to `Format`, after `describe_component`:

```python
    def remote_url(self, base: str, path: str) -> str:
        """Where a proxy repository finds a path on its remote."""
        return f"{base.rstrip('/')}/{quote(path, safe='/')}"

    def is_metadata(self, path: str) -> bool:
        """Whether a path is an index that changes as packages are published.

        Metadata is revalidated on `metadata_max_age_minutes`; everything else on
        `content_max_age_minutes`. The generic format has no metadata.
        """
        return False
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_proxy_models.py tests/repositories/test_formats.py tests/test_migrations.py tests/test_db_script.py -q`
Expected: no failures. `test_models_and_migrations_describe_the_same_schema` proves the migration matches the models.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add group member, proxy state and negative cache tables"
```

---

### Task 3: Proxy and group settings in the repository service and API

**Files:**
- Modify: `backend/src/megooarti/repositories/service.py` (replace the whole file)
- Modify: `backend/src/megooarti/repositories/api.py` (replace the whole file)
- Modify: `backend/tests/repositories/test_service.py`
- Modify: `backend/tests/repositories/test_api.py`

**Interfaces:**
- Consumes: models (Task 2); `Sealed`, `seal` (Task 1); everything the two modules already consumed.
- Produces, in `megooarti.repositories.service`:
  - `RepositoryView` gains `proxy`, `group` and `status` (each `dict | None`, default `None`)
  - `create_repository(db, *, name, format, type, online, blob_store, hosted=None, proxy=None, group=None, format_config=None) -> Repository` — all three types. `blob_store` may be `None`, meaning `default`; it is ignored for a group.
  - `update_repository(db, repository, *, online, hosted=None, proxy=None, group=None, format_config=None) -> None`
  - `delete_repository(db, repository, now) -> None` — now `409 in_use` while a group presents it
  - `member_names(db, group) -> list[str]`, `members(db, group) -> list[Repository]` — in order
  - `invalidate_cache(db, repository) -> None` — marks every cached asset stale and empties the negative cache; `409 not_a_proxy` for other types
  - A proxy's stored `config["proxy"]` is `{"remote_url", "content_max_age_minutes", "metadata_max_age_minutes", "negative_cache": {"enabled", "ttl_minutes"}, "remote_auth": {"type", "username", "secret"}, "blocked", "auto_block"}`; for `type` `none`, `remote_auth` is just `{"type": "none"}`.
  - In a view, `proxy["remote_auth"]` is `{"type", "username", "has_secret"}`; `group` is `{"members": [...]}`; `status` is `{"blocked", "auto_blocked_until", "failures", "last_error"}` for a proxy.
  - `proxy["remote_auth"]["secret"]` passed in must be a `Sealed` or absent; a plain `str` raises `TypeError`. When absent on update and the type is unchanged, the stored secret is kept.
- Produces, on the API: `POST` and `PUT` accept `proxy` and `group`; responses carry `proxy`, `group` and `status`. (`POST /repositories/{name}/invalidate-cache` arrives in Task 7.)

- [ ] **Step 1: Update the expectations of the existing API tests**

In `backend/tests/repositories/test_api.py`, replace the `EXPECTED` dictionary with:

```python
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
```

and in the same file change the parametrised case `{"type": "proxy"},` in `test_invalid_repositories_are_rejected` to:

```python
        {"type": "proxy", "proxy": {"remote_url": "ftp://remote.example"}},
```

In `backend/tests/repositories/test_service.py`, change the two parametrised cases `({"type": "proxy"}, "type"),` and `({"type": "group"}, "type"),` in `test_invalid_repositories_are_rejected` to:

```python
        ({"type": "proxy"}, "proxy.remote_url"),
        ({"type": "group", "group": {"members": ["ghost"]}}, "group.members"),
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/repositories/test_service.py`, adding `from megooarti.repositories.models import RepositoryMember` and `from megooarti.secrets_box import Sealed` to its imports:

```python
REMOTE = {"remote_url": "https://remote.example/files/"}
SECRET = Sealed("enc:v1:sealed-by-the-caller")


async def proxy(db, name="mirror", **settings):
    return await create(db, name, type="proxy", proxy={**REMOTE, **settings})


async def group(db, name="all", members=()):
    return await create(db, name, type="group", group={"members": list(members)})


async def test_create_a_proxy_repository_with_defaults(db):
    view = await service.describe(db, await proxy(db))

    assert (view.type, view.blob_store, view.hosted, view.group) == (
        "proxy",
        "default",
        None,
        None,
    )
    assert view.proxy == {
        "remote_url": "https://remote.example/files",
        "content_max_age_minutes": 1440,
        "metadata_max_age_minutes": 1440,
        "negative_cache": {"enabled": True, "ttl_minutes": 1440},
        "remote_auth": {"type": "none", "username": "", "has_secret": False},
        "blocked": False,
        "auto_block": True,
    }
    assert view.status == {
        "blocked": False,
        "auto_blocked_until": None,
        "failures": 0,
        "last_error": None,
    }


@pytest.mark.parametrize(
    ("settings", "field"),
    [
        ({"remote_url": ""}, "proxy.remote_url"),
        ({"remote_url": "ftp://remote.example"}, "proxy.remote_url"),
        ({"remote_url": "https://"}, "proxy.remote_url"),
        ({"remote_url": "https://remote.example/?token=1"}, "proxy.remote_url"),
        ({"content_max_age_minutes": -2}, "proxy.content_max_age_minutes"),
        ({"metadata_max_age_minutes": "soon"}, "proxy.metadata_max_age_minutes"),
        ({"negative_cache": {"ttl_minutes": 0}}, "proxy.negative_cache.ttl_minutes"),
        ({"remote_auth": {"type": "kerberos"}}, "proxy.remote_auth.type"),
        ({"remote_auth": {"type": "basic", "secret": SECRET}}, "proxy.remote_auth.username"),
        ({"remote_auth": {"type": "basic", "username": "u"}}, "proxy.remote_auth.secret"),
        ({"remote_auth": {"type": "bearer"}}, "proxy.remote_auth.secret"),
    ],
)
async def test_invalid_proxy_settings_are_rejected(db, settings, field):
    error = await error_of(proxy(db, **settings))

    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == field


async def test_a_remote_secret_is_stored_sealed_and_never_shown(db):
    auth = {"type": "basic", "username": "robot", "secret": SECRET}
    repository = await proxy(db, remote_auth=auth)

    view = await service.describe(db, repository)

    assert repository.config["proxy"]["remote_auth"]["secret"] == SECRET
    assert view.proxy["remote_auth"] == {"type": "basic", "username": "robot", "has_secret": True}


async def test_a_remote_secret_that_is_not_sealed_is_a_programming_error(db):
    auth = {"type": "bearer", "secret": "a plain string"}

    with pytest.raises(TypeError):
        await proxy(db, remote_auth=auth)


async def test_updating_without_a_secret_keeps_the_stored_one(db):
    repository = await proxy(
        db, remote_auth={"type": "basic", "username": "robot", "secret": SECRET}
    )

    await service.update_repository(
        db,
        repository,
        online=True,
        proxy={**REMOTE, "remote_auth": {"type": "basic", "username": "robot-2"}},
    )

    stored = repository.config["proxy"]["remote_auth"]
    assert (stored["username"], stored["secret"]) == ("robot-2", SECRET)


async def test_changing_the_kind_of_credential_needs_a_new_secret(db):
    repository = await proxy(
        db, remote_auth={"type": "basic", "username": "robot", "secret": SECRET}
    )

    error = await error_of(
        service.update_repository(
            db, repository, online=True, proxy={**REMOTE, "remote_auth": {"type": "bearer"}}
        )
    )

    assert error.details[0]["field"] == "proxy.remote_auth.secret"


async def test_removing_the_credential_forgets_the_secret(db):
    repository = await proxy(db, remote_auth={"type": "bearer", "secret": SECRET})

    await service.update_repository(db, repository, online=True, proxy=REMOTE)

    assert repository.config["proxy"]["remote_auth"] == {"type": "none"}


async def test_create_a_group_with_ordered_members(db):
    await create(db, "releases")
    await proxy(db, "mirror")

    repository = await group(db, members=["mirror", "releases"])
    view = await service.describe(db, repository)

    assert (view.type, view.blob_store, view.hosted, view.proxy) == ("group", None, None, None)
    assert view.group == {"members": ["mirror", "releases"]}
    assert [member.name for member in await service.members(db, repository)] == [
        "mirror",
        "releases",
    ]


async def test_updating_a_group_replaces_its_members_and_order(db):
    for name in ("one", "two", "three"):
        await create(db, name)
    repository = await group(db, members=["one", "two"])

    await service.update_repository(
        db, repository, online=True, group={"members": ["three", "one"]}
    )

    assert await service.member_names(db, repository) == ["three", "one"]


async def test_a_group_may_be_empty(db):
    assert (await service.describe(db, await group(db))).group == {"members": []}


async def test_a_member_must_exist_once_and_share_the_format(db):
    await create(db, "releases")
    other = Repository(name="jars", name_key="jars", format="another-format", type="hosted")
    db.add(other)
    await db.flush()

    unknown = await error_of(group(db, "a", members=["ghost"]))
    twice = await error_of(group(db, "b", members=["releases", "releases"]))
    foreign = await error_of(group(db, "c", members=["jars"]))

    for error in (unknown, twice, foreign):
        assert (error.status_code, error.code) == (422, "validation_error")
        assert error.details[0]["field"] == "group.members"


async def test_a_group_cannot_contain_itself_directly_or_indirectly(db):
    inner = await group(db, "inner")
    await group(db, "outer", members=["inner"])

    direct = await error_of(
        service.update_repository(db, inner, online=True, group={"members": ["inner"]})
    )
    indirect = await error_of(
        service.update_repository(db, inner, online=True, group={"members": ["outer"]})
    )

    assert (direct.status_code, direct.code) == (409, "repository_cycle")
    assert (indirect.status_code, indirect.code) == (409, "repository_cycle")
    assert await service.member_names(db, inner) == []


async def test_a_repository_a_group_presents_cannot_be_deleted(db):
    member = await create(db, "releases")
    presenting = await group(db, members=["releases"])

    error = await error_of(service.delete_repository(db, member, NOW))
    assert (error.status_code, error.code) == (409, "in_use")

    await service.update_repository(db, presenting, online=True, group={"members": []})
    await service.delete_repository(db, member, NOW)

    assert await service.get_repository(db, "releases") is None


async def test_deleting_a_group_leaves_its_members(db):
    await create(db, "releases")
    presenting = await group(db, members=["releases"])

    await service.delete_repository(db, presenting, NOW)

    assert await service.get_repository(db, "releases") is not None
    assert await db.scalar(select(func.count()).select_from(RepositoryMember)) == 0


async def test_invalidating_a_proxy_cache_is_refused_for_other_types(db):
    hosted = await create(db, "releases")

    error = await error_of(service.invalidate_cache(db, hosted))

    assert (error.status_code, error.code) == (409, "not_a_proxy")
```

Append to `backend/tests/repositories/test_api.py`:

```python
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
```

Add these imports to `backend/tests/repositories/test_api.py`:

```python
from sqlalchemy import select

from megooarti.repositories.models import Repository
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_service.py tests/repositories/test_api.py -q`
Expected: the new tests fail (`TypeError: create_repository() got an unexpected keyword argument 'proxy'`, `422` responses, missing keys); so do the existing tests whose expectations Step 1 changed.

- [ ] **Step 4: Replace the service**

Replace `backend/src/megooarti/repositories/service.py` with:

```python
"""Repositories: creating, changing, finding and deleting them."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.formats import format_names, get_format
from megooarti.repositories.models import (
    Asset,
    NegativeCacheEntry,
    ProxyState,
    Repository,
    RepositoryMember,
)
from megooarti.secrets_box import Sealed
from megooarti.storage import blobs
from megooarti.storage.blob_stores import get_blob_store
from megooarti.storage.models import BlobStore

DEPLOYMENT_POLICIES = ("allow_redeploy", "disable_redeploy", "read_only")
REMOTE_AUTH_TYPES = ("none", "basic", "bearer")


@dataclass(frozen=True)
class RepositoryView:
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: dict[str, Any] | None
    format_config: dict[str, Any]
    proxy: dict[str, Any] | None = None
    group: dict[str, Any] | None = None
    status: dict[str, Any] | None = None


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _hosted_settings(hosted: dict[str, Any] | None) -> dict[str, Any]:
    policy = (hosted or {}).get("deployment_policy", "allow_redeploy")
    if policy not in DEPLOYMENT_POLICIES:
        choices = ", ".join(DEPLOYMENT_POLICIES)
        raise _invalid("hosted.deployment_policy", f"Must be one of: {choices}.")
    return {"deployment_policy": policy}


def _whole_number(value: Any, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _invalid(field, f"Must be a whole number, {minimum} or more.")
    return value


def _remote_auth(sent: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
    """The credential to store. A secret that is not sent is kept if the kind is unchanged."""
    sent = sent or {}
    kind = sent.get("type", "none")
    if kind not in REMOTE_AUTH_TYPES:
        choices = ", ".join(REMOTE_AUTH_TYPES)
        raise _invalid("proxy.remote_auth.type", f"Must be one of: {choices}.")
    if kind == "none":
        return {"type": "none"}
    username = (sent.get("username") or "").strip()
    if kind == "basic" and not username:
        raise _invalid("proxy.remote_auth.username", "A username is required.")
    secret = sent.get("secret")
    if secret is None and current is not None and current.get("type") == kind:
        secret = current.get("secret")
    elif secret is not None and not isinstance(secret, Sealed):
        # A caller's bug, not bad input: secrets are sealed before they get here.
        raise TypeError("remote_auth.secret must be sealed with secrets_box.seal")
    if not secret:
        raise _invalid("proxy.remote_auth.secret", "A secret is required.")
    return {"type": kind, "username": username if kind == "basic" else "", "secret": str(secret)}


def _proxy_settings(
    proxy: dict[str, Any] | None, current: dict[str, Any] | None
) -> dict[str, Any]:
    proxy = proxy or {}
    url = str(proxy.get("remote_url") or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.query or parts.fragment:
        raise _invalid(
            "proxy.remote_url", "Must be an http or https URL without a query or fragment."
        )
    negative = proxy.get("negative_cache") or {}
    return {
        "remote_url": url.rstrip("/"),
        "content_max_age_minutes": _whole_number(
            proxy.get("content_max_age_minutes", 1440), "proxy.content_max_age_minutes", -1
        ),
        "metadata_max_age_minutes": _whole_number(
            proxy.get("metadata_max_age_minutes", 1440), "proxy.metadata_max_age_minutes", -1
        ),
        "negative_cache": {
            "enabled": bool(negative.get("enabled", True)),
            "ttl_minutes": _whole_number(
                negative.get("ttl_minutes", 1440), "proxy.negative_cache.ttl_minutes", 1
            ),
        },
        "remote_auth": _remote_auth(
            proxy.get("remote_auth"), (current or {}).get("remote_auth")
        ),
        "blocked": bool(proxy.get("blocked", False)),
        "auto_block": bool(proxy.get("auto_block", True)),
    }


async def get_repository(db: AsyncSession, name: str) -> Repository | None:
    return await db.scalar(select(Repository).where(Repository.name == name))


async def members(db: AsyncSession, group: Repository) -> list[Repository]:
    """A group's members, in the order they are tried."""
    rows = await db.scalars(
        select(Repository)
        .join(RepositoryMember, RepositoryMember.member_id == Repository.id)
        .where(RepositoryMember.group_id == group.id)
        .order_by(RepositoryMember.position)
    )
    return list(rows)


async def member_names(db: AsyncSession, group: Repository) -> list[str]:
    return [member.name for member in await members(db, group)]


async def _reachable(db: AsyncSession, repository_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """These repositories plus everything they present, directly or indirectly."""
    start = list(repository_ids)
    if not start:
        return set()
    reachable = (
        select(Repository.id).where(Repository.id.in_(start)).cte("reachable", recursive=True)
    )
    reachable = reachable.union(
        select(RepositoryMember.member_id).join(
            reachable, RepositoryMember.group_id == reachable.c.id
        )
    )
    return set(await db.scalars(select(reachable.c.id)))


async def _set_members(db: AsyncSession, group: Repository, names: list[str]) -> None:
    if len(set(names)) != len(names):
        raise _invalid("group.members", "A repository is listed more than once.")
    chosen = []
    for name in names:
        member = await get_repository(db, name)
        if member is None:
            raise _invalid("group.members", f"Unknown repository: {name}.")
        if member.format != group.format:
            raise _invalid("group.members", f"{name} is not a {group.format} repository.")
        chosen.append(member)
    if group.id in await _reachable(db, [member.id for member in chosen]):
        raise ApiError(
            409, "repository_cycle", "A group cannot contain itself, directly or indirectly."
        )
    await db.execute(delete(RepositoryMember).where(RepositoryMember.group_id == group.id))
    if chosen:
        await db.execute(
            insert(RepositoryMember),
            [
                {"group_id": group.id, "member_id": member.id, "position": position}
                for position, member in enumerate(chosen)
            ],
        )


def _shown_proxy(proxy: dict[str, Any]) -> dict[str, Any]:
    auth = proxy["remote_auth"]
    shown = {
        "type": auth["type"],
        "username": auth.get("username", ""),
        "has_secret": bool(auth.get("secret")),
    }
    return {**proxy, "remote_auth": shown}


async def describe(db: AsyncSession, repository: Repository) -> RepositoryView:
    store = None
    if repository.blob_store_id is not None:
        store = await db.scalar(
            select(BlobStore.name).where(BlobStore.id == repository.blob_store_id)
        )
    proxy = repository.config.get("proxy")
    status = None
    if proxy is not None:
        state = await db.get(ProxyState, repository.id)
        until = None if state is None else state.blocked_until
        status = {
            "blocked": proxy["blocked"],
            "auto_blocked_until": until if until is not None and until > utcnow() else None,
            "failures": 0 if state is None else state.failures,
            "last_error": None if state is None else state.last_error,
        }
    group = None
    if repository.type == "group":
        group = {"members": await member_names(db, repository)}
    return RepositoryView(
        name=repository.name,
        format=repository.format,
        type=repository.type,
        online=repository.online,
        blob_store=store,
        url_path=f"/repository/{repository.name}/",
        hosted=repository.config.get("hosted"),
        format_config=repository.config.get("format_config", {}),
        proxy=None if proxy is None else _shown_proxy(proxy),
        group=group,
        status=status,
    )


async def list_repositories(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[RepositoryView], int]:
    total = await db.scalar(select(func.count()).select_from(Repository))
    page = list(
        await db.scalars(
            select(Repository).order_by(Repository.name_key).limit(limit).offset(offset)
        )
    )
    return [await describe(db, repository) for repository in page], total or 0


def _type_settings(
    type: str,
    hosted: dict[str, Any] | None,
    proxy: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    if type == "hosted":
        return {"hosted": _hosted_settings(hosted)}
    if type == "proxy":
        return {"proxy": _proxy_settings(proxy, (current or {}).get("proxy"))}
    return {}


async def create_repository(
    db: AsyncSession,
    *,
    name: str,
    format: str,
    type: str,
    online: bool,
    blob_store: str | None,
    hosted: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    format_config: dict[str, Any] | None = None,
) -> Repository:
    handler = get_format(format)
    if handler is None:
        known = ", ".join(format_names())
        raise _invalid("format", f"Unknown format. Known formats: {known}.")
    if type not in handler.types:
        raise _invalid("type", f"{type} repositories are not available for this format.")
    settings = {
        **_type_settings(type, hosted, proxy, None),
        "format_config": handler.validate_config(type, format_config or {}),
    }
    store_id = None
    if type != "group":  # a group stores nothing of its own
        store = await get_blob_store(db, blob_store or "default")
        if store is None:
            raise _invalid("blob_store", f"Unknown blob store: {blob_store}.")
        store_id = store.id
    taken = await db.scalar(select(Repository.id).where(Repository.name_key == name.lower()))
    if taken is not None:
        raise ApiError(409, "conflict", f"A repository named {name} already exists.")
    repository = Repository(
        name=name,
        name_key=name.lower(),
        format=format,
        type=type,
        online=online,
        blob_store_id=store_id,
        config=settings,
    )
    db.add(repository)
    await db.flush()
    if type == "group":
        await _set_members(db, repository, list((group or {}).get("members", [])))
    return repository


async def update_repository(
    db: AsyncSession,
    repository: Repository,
    *,
    online: bool,
    hosted: dict[str, Any] | None = None,
    proxy: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    format_config: dict[str, Any] | None = None,
) -> None:
    """Replace what can change. Name, format, type and blob store never do."""
    handler = get_format(repository.format)
    repository.config = {
        **_type_settings(repository.type, hosted, proxy, repository.config),
        "format_config": handler.validate_config(repository.type, format_config or {}),
    }
    repository.online = online
    await db.flush()
    if repository.type == "group":
        await _set_members(db, repository, list((group or {}).get("members", [])))


async def delete_repository(db: AsyncSession, repository: Repository, now: datetime) -> None:
    """Delete a repository and everything in it. Its blobs become unreferenced."""
    presenting = await db.scalar(
        select(Repository.name)
        .join(RepositoryMember, RepositoryMember.group_id == Repository.id)
        .where(RepositoryMember.member_id == repository.id)
        .limit(1)
    )
    if presenting is not None:
        raise ApiError(409, "in_use", f"The group {presenting} presents this repository.")
    await db.delete(repository)  # the database removes its components and assets
    await db.flush()
    # One set-based statement, however many assets there were.
    await blobs.mark_unreferenced(db, now)


async def invalidate_cache(db: AsyncSession, repository: Repository) -> None:
    """Make a proxy ask its remote again for everything it has cached or ruled out."""
    if repository.type != "proxy":
        raise ApiError(409, "not_a_proxy", "Only a proxy repository has a cache to invalidate.")
    await db.execute(
        update(Asset).where(Asset.repository_id == repository.id).values(last_verified_at=None)
    )
    await db.execute(
        delete(NegativeCacheEntry).where(NegativeCacheEntry.repository_id == repository.id)
    )
```

- [ ] **Step 5: Replace the API**

Replace `backend/src/megooarti/repositories/api.py` with:

```python
"""Administration of repositories."""

from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import service
from megooarti.repositories.models import Repository
from megooarti.repositories.service import RepositoryView
from megooarti.secrets_box import seal
from megooarti.security.authentication import Principal, require

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/repositories", tags=["repositories"])

# The same characters as a permission segment, so a name can never shift a permission.
_NAME = r"^[A-Za-z0-9_.-]{1,64}$"


class HostedSettings(BaseModel):
    deployment_policy: Literal["allow_redeploy", "disable_redeploy", "read_only"] = (
        "allow_redeploy"
    )


class NegativeCache(BaseModel):
    enabled: bool = True
    ttl_minutes: int = Field(default=1440, ge=1)


class RemoteAuthIn(BaseModel):
    type: Literal["none", "basic", "bearer"] = "none"
    username: str = Field(default="", max_length=255)
    # Write-only. Leave it out on an update to keep the stored secret.
    secret: str | None = Field(default=None, min_length=1, max_length=4096)


class ProxyIn(BaseModel):
    remote_url: str = Field(min_length=1, max_length=2048)
    content_max_age_minutes: int = Field(default=1440, ge=-1)
    metadata_max_age_minutes: int = Field(default=1440, ge=-1)
    negative_cache: NegativeCache = NegativeCache()
    remote_auth: RemoteAuthIn = RemoteAuthIn()
    blocked: bool = False
    auto_block: bool = True


class RemoteAuthOut(BaseModel):
    type: str
    username: str
    has_secret: bool


class ProxyOut(BaseModel):
    remote_url: str
    content_max_age_minutes: int
    metadata_max_age_minutes: int
    negative_cache: NegativeCache
    remote_auth: RemoteAuthOut
    blocked: bool
    auto_block: bool


class GroupSettings(BaseModel):
    members: list[str] = []


class ProxyStatus(BaseModel):
    blocked: bool
    auto_blocked_until: datetime | None
    failures: int
    last_error: str | None


class RepositoryOut(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: HostedSettings | None
    format_config: dict[str, Any]
    proxy: ProxyOut | None
    group: GroupSettings | None
    status: ProxyStatus | None


class RepositoryCreate(BaseModel):
    name: str = Field(pattern=_NAME)
    format: str
    type: Literal["hosted", "proxy", "group"]
    online: bool = True
    blob_store: str | None = None
    hosted: HostedSettings | None = None
    proxy: ProxyIn | None = None
    group: GroupSettings | None = None
    format_config: dict[str, Any] = {}


class RepositoryUpdate(BaseModel):
    online: bool = True
    hosted: HostedSettings | None = None
    proxy: ProxyIn | None = None
    group: GroupSettings | None = None
    format_config: dict[str, Any] = {}
    # Accepted so a client can send back what it read, but they cannot change.
    format: str | None = None
    type: str | None = None
    blob_store: str | None = None


def _plain(model: BaseModel | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump()


def _proxy(settings: Settings, proxy: ProxyIn | None) -> dict[str, Any] | None:
    """The proxy settings as the service takes them, with the secret sealed."""
    if proxy is None:
        return None
    values = proxy.model_dump()
    secret = values["remote_auth"]["secret"]
    if secret is not None:
        values["remote_auth"]["secret"] = seal(settings, secret)
    return values


async def _load(db: AsyncSession, name: str) -> Repository:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    return repository


@router.get("", response_model=Page[RepositoryOut])
async def list_repositories(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await service.list_repositories(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=RepositoryOut, status_code=201)
async def create_repository(
    body: RepositoryCreate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await service.create_repository(
        db,
        name=body.name,
        format=body.format,
        type=body.type,
        online=body.online,
        blob_store=body.blob_store,
        hosted=_plain(body.hosted),
        proxy=_proxy(request.app.state.settings, body.proxy),
        group=_plain(body.group),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    await db.commit()
    log.info("repository_created", repository=repository.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=RepositoryOut)
async def get_repository(
    name: str,
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    return await service.describe(db, await _load(db, name))


@router.put("/{name}", response_model=RepositoryOut)
async def update_repository(
    name: str,
    body: RepositoryUpdate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await _load(db, name)
    current = await service.describe(db, repository)
    fixed = {"format": current.format, "type": current.type, "blob_store": current.blob_store}
    for field, value in fixed.items():
        sent = getattr(body, field)
        if sent is not None and sent != value:
            raise ApiError(409, "immutable", f"A repository's {field} cannot be changed.")
    await service.update_repository(
        db,
        repository,
        online=body.online,
        hosted=_plain(body.hosted),
        proxy=_proxy(request.app.state.settings, body.proxy),
        group=_plain(body.group),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    await db.commit()
    log.info("repository_updated", repository=repository.name, by=principal.user.username)
    return view


@router.delete("/{name}", status_code=204)
async def delete_repository(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    await service.delete_repository(db, repository, utcnow())
    await db.commit()
    log.info("repository_deleted", repository=name, by=principal.user.username)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_service.py tests/repositories/test_api.py -q`
Expected: no failures; `test_service.py` reports 38 passed and `test_api.py` 30 passed.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add proxy and group settings to the service and API"
```

---

### Task 4: Caching through the facade, and a dispatcher

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py` (replace the whole file)
- Create: `backend/src/megooarti/repositories/dispatch.py`
- Modify: `backend/src/megooarti/repositories/routes.py` (replace the whole file)
- Modify: `backend/tests/repositories/conftest.py`
- Modify: `backend/tests/repositories/test_content.py`
- Test: `backend/tests/repositories/test_dispatch.py`

**Interfaces:**
- Consumes: everything `content.py` and `routes.py` already consumed; `service.create_repository` with `proxy=` (Task 3).
- Produces:
  - `RepositoryContext.backend` may be `None` (a group stores nothing).
  - `RepositoryContext.cache(path, staged, *, content_type, attributes, now) -> Asset` — records content fetched from a remote: no permission or policy check, `created_by = "proxy"`, `last_verified_at = now`, `attributes` replaced. `updated_at` moves only if the content changed. Raises `RuntimeError`, after discarding the staged content, on a repository that is not a proxy. Never commits.
  - `megooarti.repositories.content.build_context(db, settings, repository, principal) -> RepositoryContext`
  - `megooarti.repositories.dispatch.ENGINES: dict[str, Engine]` — repository type to the coroutine that answers for it; `Engine = Callable[[RepositoryContext, Request, str], Awaitable[Response]]`. This task registers `hosted`.
  - `megooarti.repositories.dispatch.serve(context, request, path) -> Response` — `503 repository_unavailable` for a type with no engine. It does not authenticate, authorise or commit: the route does.
  - Test fixture `mirror`: a committed proxy repository named `mirror` with remote `http://remote.test/files`. The `context_for` fixture now uses `build_context`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/conftest.py`, replace the `context_for` fixture with the following, add the `mirror` fixture, replace the import of `RepositoryContext` with `from megooarti.repositories.content import RepositoryContext, build_context`, and remove the imports that are no longer used (`get_format`, `backend_for`, `BlobStore`):

```python
@pytest.fixture
async def mirror(db) -> Repository:
    repository = await service.create_repository(
        db,
        name="mirror",
        format="raw",
        type="proxy",
        online=True,
        blob_store=None,
        proxy={"remote_url": "http://remote.test/files"},
    )
    await db.commit()
    return repository


@pytest.fixture
def context_for(db, settings):
    async def make(repository: Repository, principal: Principal | None) -> RepositoryContext:
        return await build_context(db, settings, repository, principal)

    return make
```

Append to `backend/tests/repositories/test_content.py`, adding `from datetime import UTC, datetime` to its imports (it already imports `timedelta`):

```python
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=3)


async def cached(context, content: bytes, etag: str, now: datetime):
    return await context.cache(
        "lib/a.bin",
        await context.stage(body(content)),
        content_type="application/x-thing",
        attributes={"remote_etag": etag},
        now=now,
    )


async def test_cache_records_remote_content_without_asking_who_is_reading(mirror, context_for):
    context = await context_for(mirror, None)

    asset = await cached(context, HELLO, '"v1"', NOW)

    assert (asset.created_by, asset.content_type) == ("proxy", "application/x-thing")
    assert (asset.attributes, asset.last_verified_at) == ({"remote_etag": '"v1"'}, NOW)
    assert await read(await context.respond("lib/a.bin", request())) == HELLO


async def test_cache_replaces_a_cached_file_and_releases_the_old_content(
    db, mirror, context_for
):
    context = await context_for(mirror, None)
    first = await cached(context, b"version one", '"v1"', NOW)
    first_id, first_blob, first_updated = first.id, first.blob_id, first.updated_at

    second = await cached(context, b"version two", '"v2"', LATER)

    assert (second.id, second.attributes) == (first_id, {"remote_etag": '"v2"'})
    assert second.blob_id != first_blob
    assert second.last_verified_at == LATER
    assert second.updated_at > first_updated
    old = await db.get(Blob, first_blob, populate_existing=True)
    assert old.unreferenced_since is not None


async def test_caching_the_same_content_again_only_marks_it_verified(mirror, context_for):
    context = await context_for(mirror, None)
    first = await cached(context, HELLO, '"v1"', NOW)
    blob, updated = first.blob_id, first.updated_at

    again = await cached(context, HELLO, '"v1"', LATER)

    assert (again.blob_id, again.updated_at) == (blob, updated)
    assert again.last_verified_at == LATER


async def test_cache_refuses_a_repository_that_is_not_a_proxy(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    staged = await context.stage(body(HELLO))

    with pytest.raises(RuntimeError):
        await context.cache("a.bin", staged, content_type=None, attributes={}, now=NOW)

    assert await count(db, Asset) == 0
    assert temporary_files(context.settings) == []


async def test_a_group_has_no_blob_store(db, context_for):
    everything = await service.create_repository(
        db, name="all", format="raw", type="group", online=True, blob_store=None
    )

    assert (await context_for(everything, None)).backend is None
```

`backend/tests/repositories/test_dispatch.py`:

```python
from megooarti.repositories.dispatch import ENGINES
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic, error_code


def test_hosted_repositories_have_an_engine():
    assert "hosted" in ENGINES


async def test_a_repository_of_a_type_with_no_engine_is_unavailable(client, make_user, db):
    await make_user("root", roles=["admin"])
    db.add(Repository(name="odd", name_key="odd", format="raw", type="mystery"))
    await db.commit()

    response = await client.get("/repository/odd/a.bin", headers=basic("root", PASSWORD))

    assert (response.status_code, error_code(response)) == (503, "repository_unavailable")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_content.py tests/repositories/test_dispatch.py -q`
Expected: collection errors, `cannot import name 'build_context'` and `No module named 'megooarti.repositories.dispatch'`.

- [ ] **Step 3: Replace the facade**

Replace `backend/src/megooarti/repositories/content.py` with:

```python
"""The storage facade formats and engines work through.

It enforces the add, edit and delete permissions and the deployment policy, so a format
cannot bypass them, and it is the only code that ties assets to blobs.
"""

import hashlib
import mimetypes
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import serving
from megooarti.repositories.formats import ComponentKey, Format, get_format
from megooarti.repositories.models import Asset, Component, Repository
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import Principal, authorize
from megooarti.storage import blobs
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore

# First key of the two-key advisory lock; the second is derived from what is locked.
_LOCK_NAMESPACE = 0x4D48
_DOWNLOAD_NOTE_INTERVAL = timedelta(hours=1)
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(;[\x20-\x7e]*)?")
# Recorded as the creator of content a proxy repository fetched for a reader.
PROXY_CREATOR = "proxy"


def _media_type(declared: str | None, path: str) -> str:
    """The declared type if it is a well-formed media type, else a guess from the name."""
    if declared is not None:
        declared = declared.strip()
        if len(declared) <= 255 and _MEDIA_TYPE.fullmatch(declared):
            return declared
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _verify(
    staged: StagedBlob, expected_size: int | None, expected_hashes: dict[str, str] | None
) -> None:
    if expected_size is not None and staged.size != expected_size:
        raise ApiError(
            400,
            "checksum_mismatch",
            f"Received {staged.size} bytes but {expected_size} were declared.",
        )
    for algorithm, expected in (expected_hashes or {}).items():
        if getattr(staged, algorithm) != expected.strip().lower():
            raise ApiError(
                400, "checksum_mismatch", f"The {algorithm} checksum does not match the content."
            )


class RepositoryContext:
    """One request's view of one repository."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        repository: Repository,
        principal: Principal | None,
        format: Format,
        backend: BlobBackend | None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository
        self.principal = principal
        self.format = format
        self.backend = backend  # None for a group, which stores nothing itself

    def permission(self, action: str) -> str:
        return f"repository:{self.repository.format}:{self.repository.name}:{action}"

    async def _lock(self, kind: str, key: str) -> None:
        """Serialise work on one path or component until this transaction ends."""
        digest = hashlib.sha256(f"{self.repository.id}:{kind}:{key}".encode()).digest()
        number = int.from_bytes(digest[:4], "big", signed=True)
        await self.db.execute(text(f"SELECT pg_advisory_xact_lock({_LOCK_NAMESPACE}, {number})"))

    async def get(self, path: str, *, fresh: bool = False) -> Asset | None:
        statement = select(Asset).where(
            Asset.repository_id == self.repository.id, Asset.path == path
        )
        if fresh:  # reread from the database even if this session already loaded it
            statement = statement.execution_options(populate_existing=True)
        return await self.db.scalar(statement)

    def _check_policy(self, *, replacing: bool) -> None:
        policy = self.repository.config.get("hosted", {}).get("deployment_policy")
        if policy == "read_only":
            raise ApiError(403, "repository_read_only", "This repository is read-only.")
        if replacing and policy == "disable_redeploy":
            raise ApiError(
                409, "redeploy_disabled", "This repository does not allow a path to be replaced."
            )

    def _check_may_store(self, existing: Asset | None) -> None:
        action = "add" if existing is None else "edit"
        authorize(self.principal, self.permission(action), scheme="Basic")
        self._check_policy(replacing=existing is not None)

    async def _lock_component(self, key: ComponentKey) -> None:
        await self._lock("component", f"{key.namespace}\x00{key.name}\x00{key.version}")

    async def _component(self, key: ComponentKey) -> Component:
        await self._lock_component(key)
        component = await self.db.scalar(
            select(Component).where(
                Component.repository_id == self.repository.id,
                Component.namespace == key.namespace,
                Component.name == key.name,
                Component.version == key.version,
            )
        )
        if component is None:
            component = Component(
                repository_id=self.repository.id,
                namespace=key.namespace,
                name=key.name,
                version=key.version,
            )
            self.db.add(component)
            await self.db.flush()
        return component

    async def put(
        self,
        path: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        expected_size: int | None = None,
        expected_hashes: dict[str, str] | None = None,
        kind: str = "asset",
    ) -> tuple[Asset, bool]:
        """Store content at a path. Returns the asset and whether it is new.

        The caller commits. Permission and policy are checked before the body is read,
        so a refused upload is refused early, and again before recording, because the
        path may have been written while the body arrived.
        """
        path = normalise_path(path)
        self._check_may_store(await self.get(path))
        await self.db.commit()  # give the connection back while the body arrives
        staged = await self.stage(
            chunks, expected_size=expected_size, expected_hashes=expected_hashes
        )
        return await self.store(path, staged, content_type=content_type, kind=kind)

    async def stage(
        self,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int | None = None,
        expected_hashes: dict[str, str] | None = None,
    ) -> StagedBlob:
        """Receive content into temporary storage and verify it. Uses no database.

        A format that publishes several files in one request stages each of them first,
        then calls `store` for each inside one transaction, so the publish is atomic.
        """
        staged = await self.backend.stage(chunks)
        try:
            _verify(staged, expected_size, expected_hashes)
        except BaseException:
            await self.backend.discard(staged)
            raise
        return staged

    async def _record(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None,
        kind: str,
        checked: bool,
        created_by: str | None = None,
        attributes: dict[str, Any] | None = None,
        verified_at: datetime | None = None,
    ) -> tuple[Asset, bool]:
        """Tie staged content to a path. `checked` applies permission and policy."""
        try:
            path = normalise_path(path)
            await self._lock("path", path)
            existing = await self.get(path, fresh=True)
            if checked:
                self._check_may_store(existing)
            blob = await blobs.record(self.db, self.backend, self.repository.blob_store_id, staged)
        except BaseException:
            await self.backend.discard(staged)
            raise

        now = utcnow()
        media_type = _media_type(content_type, path)
        if existing is None:
            component = await self._component(self.format.describe_component(path))
            asset = Asset(
                repository_id=self.repository.id,
                component_id=component.id,
                path=path,
                blob_id=blob.id,
                content_type=media_type,
                kind=kind,
                attributes=attributes or {},
                created_by=created_by or self.principal.user.username,
                last_verified_at=verified_at,
            )
            self.db.add(asset)
            await self.db.flush()
            return asset, True

        previous = existing.blob_id
        changed = previous != blob.id
        existing.blob_id = blob.id
        existing.content_type = media_type
        existing.last_verified_at = verified_at
        if attributes is not None:
            existing.attributes = attributes
        if checked or changed:
            # An upload always counts as a change. Fetching the same bytes from the
            # remote again does not, so Last-Modified stays put.
            existing.updated_at = now
        await self.db.flush()
        if changed:
            await blobs.dereference(self.db, [previous], now)
        return existing, False

    async def store(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None = None,
        kind: str = "asset",
    ) -> tuple[Asset, bool]:
        """Record staged content at a path, in the caller's transaction.

        Checks permission and policy under the path lock. Never commits: the caller
        does, and a rollback undoes everything recorded here.
        """
        return await self._record(
            path, staged, content_type=content_type, kind=kind, checked=True
        )

    async def cache(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None,
        attributes: dict[str, Any],
        now: datetime,
    ) -> Asset:
        """Record content a proxy repository fetched from its remote.

        No permission or policy check: a reader triggered this, and their `read` on the
        proxy (or on the group in front of it) has already been checked. For that reason
        it works only on a proxy repository.
        """
        if self.repository.type != "proxy":
            await self.backend.discard(staged)
            raise RuntimeError("cache() is only for proxy repositories")
        asset, _ = await self._record(
            path,
            staged,
            content_type=content_type,
            kind="asset",
            checked=False,
            created_by=PROXY_CREATOR,
            attributes=attributes,
            verified_at=now,
        )
        return asset

    async def delete(self, path: str) -> bool:
        """Remove what is at a path. False if there was nothing. The caller commits."""
        path = normalise_path(path)
        authorize(self.principal, self.permission("delete"), scheme="Basic")
        self._check_policy(replacing=False)
        await self._lock("path", path)
        asset = await self.get(path, fresh=True)
        if asset is None:
            return False
        blob_id, component_id = asset.blob_id, asset.component_id
        await self.db.delete(asset)
        await self.db.flush()
        if component_id is not None:
            # The same lock an upload into this component holds, so a sibling that is
            # being added is seen here instead of losing its component under it.
            component = await self.db.get(Component, component_id, populate_existing=True)
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            remaining = await self.db.scalar(
                select(Asset.id).where(Asset.component_id == component_id).limit(1)
            )
            if remaining is None:
                await self.db.execute(delete(Component).where(Component.id == component_id))
        await blobs.dereference(self.db, [blob_id], utcnow())
        return True

    async def respond(self, path: str, request: Request) -> Response:
        """The response to a GET or HEAD for a path. The caller has checked `read`."""
        path = normalise_path(path)
        found = (
            await self.db.execute(
                select(Asset, Blob)
                .join(Blob, Blob.id == Asset.blob_id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if found is None:
            raise ApiError(404, "not_found", "No such file.")
        asset, blob = found
        item = serving.Servable(
            sha256=blob.sha256,
            md5=blob.md5,
            sha1=blob.sha1,
            sha512=blob.sha512,
            size=blob.size,
            content_type=asset.content_type,
            last_modified=asset.updated_at,
            filename=path.rpartition("/")[2],
        )
        plan = serving.plan(request.method, request.headers, item)

        now = utcnow()
        noted = asset.last_downloaded_at
        if plan.byte_range is not None and (
            noted is None or now - noted >= _DOWNLOAD_NOTE_INTERVAL
        ):
            asset.last_downloaded_at = now
        await self.db.commit()  # give the connection back before the body is sent

        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return StreamingResponse(
            self.backend.open(blob.sha256, start, end),
            status_code=plan.status,
            headers=plan.headers,
        )


async def build_context(
    db: AsyncSession, settings: Settings, repository: Repository, principal: Principal | None
) -> RepositoryContext:
    backend = None
    if repository.blob_store_id is not None:
        store = await db.get(BlobStore, repository.blob_store_id)
        backend = backend_for(settings, store)
    return RepositoryContext(
        db=db,
        settings=settings,
        repository=repository,
        principal=principal,
        format=get_format(repository.format),
        backend=backend,
    )
```

- [ ] **Step 4: Add the dispatcher and use it from the route**

`backend/src/megooarti/repositories/dispatch.py`:

```python
"""Send a request for repository content to the engine for the repository's type.

An engine answers for one type of repository. It does not authenticate, authorise
`read`, or commit: the route does those around it.
"""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext

Engine = Callable[[RepositoryContext, Request, str], Awaitable[Response]]


async def _hosted(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_hosted(context, request, path)


ENGINES: dict[str, Engine] = {"hosted": _hosted}


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    engine = ENGINES.get(context.repository.type)
    if engine is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return await engine(context, request, path)
```

Replace `backend/src/megooarti/repositories/routes.py` with:

```python
"""Requests for repository content: /repository/{name}/{path}.

Authentication and the `read` check happen here, before any format or engine code runs.
The storage facade checks `add`, `edit` and `delete` at the moment of each operation.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.repositories import dispatch, service
from megooarti.repositories.content import build_context
from megooarti.security.authentication import (
    Principal,
    authorize,
    client_principal,
    unauthorized,
)

log = structlog.get_logger(__name__)

router = APIRouter()

_METHODS = ["GET", "HEAD", "PUT", "POST", "PATCH", "DELETE"]


@router.api_route("/repository/{name}/{path:path}", methods=_METHODS, include_in_schema=False)
async def repository_content(
    name: str,
    path: str,
    request: Request,
    principal: Principal | None = Depends(client_principal),
    db: AsyncSession = Depends(get_session),
) -> Response:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    context = await build_context(db, request.app.state.settings, repository, principal)

    if request.method in ("GET", "HEAD"):
        authorize(principal, context.permission("read"), scheme="Basic")
    elif principal is None:
        raise unauthorized(scheme="Basic")
    if not repository.online:
        raise ApiError(503, "repository_offline", "This repository is offline.")

    try:
        response = await dispatch.serve(context, request, path)
        # Committing here, not in each format or engine, means none of them can answer
        # "stored" for a change that was never committed.
        await db.commit()
        return response
    except ClientDisconnect:
        # The client went away mid-upload. Nothing was stored; nobody is left to answer.
        log.info("upload_interrupted", repository=name, path=path)
        return Response(status_code=400)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories -q`
Expected: no failures. `test_content.py` gains 5 tests and `test_dispatch.py` reports 2 passed; the hosted Raw tests are unchanged and prove the route still behaves as before.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add unchecked caching to the facade and a type dispatcher"
```

---

### Task 5: Talking to a remote

**Files:**
- Create: `backend/src/megooarti/repositories/remote.py`
- Create: `backend/tests/repositories/fake_remote.py`
- Test: `backend/tests/repositories/test_remote.py`

**Interfaces:**
- Consumes: `unseal`, `SecretUnreadable` (Task 1); `StagedBlob`; `ApiError`; `megooarti.__version__`.
- Produces, in `megooarti.repositories.remote`:
  - `new_client(transport=None) -> httpx.AsyncClient` — follows at most 5 redirects, 10 s to connect and 60 s per read, identifies as `MegooArti/<version>`
  - `authorization(settings, remote_auth: dict) -> str | None` — the `Authorization` header value for a stored credential; raises `SecretUnreadable`
  - `Stage = Callable[[AsyncIterator[bytes], int | None], Awaitable[StagedBlob]]` — receives the body and the size the remote declared (or `None`)
  - Outcomes (frozen dataclasses): `Fetched(staged, content_type, etag, last_modified)`, `NotModified()`, `Missing()`, `Failed(reason: str, blockable: bool)`, `Exists(headers: dict[str, str])`
  - `download(client, url, *, authorization, stage, etag=None, last_modified=None) -> Fetched | NotModified | Missing | Failed`
  - `head(client, url, *, authorization) -> Exists | Missing | Failed`
  - `404` and `410` are `Missing`. Transport errors, `5xx` and `429` are `Failed(blockable=True)`. Any other status is `Failed(blockable=False)`. A body that does not match its declared length is `Failed(blockable=True)` with nothing left staged.
- Produces for tests, in `tests/repositories/fake_remote.py`: `FakeRemote` — an in-process remote with `.files: dict[str, bytes]` (keyed by URL path without the leading slash), `.requests: list[dict]` (each with `method`, `host`, `path`, `headers`), `.status: int | None` (force a status), `.declared_extra: int` (lie about `Content-Length`), `.redirect_to: str | None`, `.down: bool` (raise a connection error), `.delay: float` (seconds to wait before answering), `.paths(method="GET") -> list[str]`, and `.client() -> httpx.AsyncClient`.

- [ ] **Step 1: Write the fake remote**

`backend/tests/repositories/fake_remote.py`:

```python
"""An in-process stand-in for a remote repository. No test touches the network."""

import asyncio
import hashlib
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from megooarti.repositories.remote import new_client

MODIFIED = "Fri, 02 Jan 2026 03:04:05 GMT"


def etag_of(content: bytes) -> str:
    return '"' + hashlib.md5(content).hexdigest() + '"'


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, remote: "FakeRemote") -> None:
        self._remote = remote
        self._inner = httpx.ASGITransport(app=remote.app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._remote.down:
            raise httpx.ConnectError("connection refused", request=request)
        return await self._inner.handle_async_request(request)


class FakeRemote:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.requests: list[dict] = []
        self.status: int | None = None
        self.declared_extra = 0
        self.redirect_to: str | None = None
        self.down = False
        self.delay = 0.0
        self.app = Starlette(routes=[Route("/{path:path}", self._serve, methods=["GET"])])

    def client(self) -> httpx.AsyncClient:
        return new_client(transport=_Transport(self))

    def paths(self, method: str = "GET") -> list[str]:
        return [seen["path"] for seen in self.requests if seen["method"] == method]

    async def _serve(self, request: Request) -> Response:
        self.requests.append(
            {
                "method": request.method,
                "host": request.url.hostname,
                "path": request.url.path,
                "headers": dict(request.headers),
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.status is not None:
            return Response(status_code=self.status)
        if self.redirect_to and request.url.hostname != urlsplit(self.redirect_to).hostname:
            return RedirectResponse(self.redirect_to + request.url.path, status_code=302)
        content = self.files.get(request.url.path.lstrip("/"))
        if content is None:
            return Response(status_code=404)
        etag = etag_of(content)
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304)
        headers = {
            "ETag": etag,
            "Last-Modified": MODIFIED,
            "Content-Type": "application/x-remote",
            "Content-Length": str(len(content) + self.declared_extra),
        }
        return Response(b"" if request.method == "HEAD" else content, headers=headers)
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/repositories/test_remote.py`:

```python
import base64
import hashlib
from collections.abc import AsyncIterator

import pytest

from megooarti import __version__
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import remote
from megooarti.secrets_box import SecretUnreadable, seal
from megooarti.storage.backends import FileBlobBackend, StagedBlob
from tests.repositories.fake_remote import MODIFIED, FakeRemote, etag_of

URL = "http://remote.test/files/a/b.bin"
CONTENT = b"content held by the remote"


@pytest.fixture
def fake() -> FakeRemote:
    remote_ = FakeRemote()
    remote_.files["files/a/b.bin"] = CONTENT
    return remote_


@pytest.fixture
def backend(tmp_path) -> FileBlobBackend:
    return FileBlobBackend(tmp_path / "store")


@pytest.fixture
def stage(backend):
    async def stage_checked(chunks: AsyncIterator[bytes], size: int | None) -> StagedBlob:
        staged = await backend.stage(chunks)
        if size is not None and staged.size != size:
            await backend.discard(staged)
            raise ApiError(400, "checksum_mismatch", "The size does not match.")
        return staged

    return stage_checked


def temporary_files(tmp_path) -> list:
    directory = tmp_path / "store" / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


async def fetch(fake, stage, **options):
    async with fake.client() as client:
        options.setdefault("authorization", None)
        return await remote.download(client, URL, stage=stage, **options)


async def test_download_stages_the_content_and_reports_what_the_remote_said(fake, stage):
    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Fetched)
    assert outcome.staged.sha256 == hashlib.sha256(CONTENT).hexdigest()
    assert (outcome.content_type, outcome.etag, outcome.last_modified) == (
        "application/x-remote",
        etag_of(CONTENT),
        MODIFIED,
    )


async def test_requests_identify_megooarti_and_ask_for_the_bytes_as_stored(fake, stage):
    await fetch(fake, stage)

    (seen,) = fake.requests
    assert seen["headers"]["user-agent"] == f"MegooArti/{__version__}"
    assert seen["headers"]["accept-encoding"] == "identity"
    assert "authorization" not in seen["headers"]


async def test_an_unchanged_file_is_not_downloaded_again(fake, stage, tmp_path):
    outcome = await fetch(fake, stage, etag=etag_of(CONTENT), last_modified=MODIFIED)

    assert outcome == remote.NotModified()
    assert fake.requests[0]["headers"]["if-modified-since"] == MODIFIED
    assert temporary_files(tmp_path) == []


async def test_a_file_the_remote_lacks_is_missing(fake, stage):
    fake.files.clear()
    assert await fetch(fake, stage) == remote.Missing()

    fake.status = 410
    assert await fetch(fake, stage) == remote.Missing()


@pytest.mark.parametrize(
    ("status", "blockable"),
    [(500, True), (503, True), (429, True), (401, False), (403, False), (400, False)],
)
async def test_other_answers_are_failures_and_only_some_count_towards_blocking(
    fake, stage, tmp_path, status, blockable
):
    fake.status = status

    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is blockable
    assert str(status) in outcome.reason
    assert temporary_files(tmp_path) == []


async def test_an_unreachable_remote_is_a_blockable_failure(fake, stage):
    fake.down = True

    outcome = await fetch(fake, stage)

    assert outcome == remote.Failed("ConnectError", blockable=True)


async def test_a_file_shorter_than_declared_is_a_failure_and_leaves_nothing(fake, stage, tmp_path):
    fake.declared_extra = 5

    outcome = await fetch(fake, stage)

    assert isinstance(outcome, remote.Failed)
    assert outcome.blockable is True
    assert temporary_files(tmp_path) == []


async def test_the_credential_is_sent_to_the_remote(fake, stage):
    await fetch(fake, stage, authorization="Bearer the-remote-token")

    assert fake.requests[0]["headers"]["authorization"] == "Bearer the-remote-token"


async def test_the_credential_does_not_follow_a_redirect_to_another_host(fake, stage):
    fake.redirect_to = "http://elsewhere.test"

    outcome = await fetch(fake, stage, authorization="Bearer the-remote-token")

    first, second = fake.requests
    assert isinstance(outcome, remote.Fetched)
    assert (first["host"], second["host"]) == ("remote.test", "elsewhere.test")
    assert "authorization" in first["headers"]
    assert "authorization" not in second["headers"]


async def test_head_reports_existence_without_fetching_the_body(fake):
    async with fake.client() as client:
        exists = await remote.head(client, URL, authorization=None)
        fake.files.clear()
        missing = await remote.head(client, URL, authorization=None)
        fake.status = 500
        failed = await remote.head(client, URL, authorization=None)

    assert isinstance(exists, remote.Exists)
    assert exists.headers["Content-Length"] == str(len(CONTENT))
    assert exists.headers["Content-Type"] == "application/x-remote"
    assert missing == remote.Missing()
    assert isinstance(failed, remote.Failed)
    assert [seen["method"] for seen in fake.requests] == ["HEAD", "HEAD", "HEAD"]


def test_authorization_headers_for_each_kind_of_credential(tmp_path):
    settings = Settings(_env_file=None, database_url="postgresql://u:p@db/m", data_dir=tmp_path)
    sealed = seal(settings, "s3cret")
    expected_basic = "Basic " + base64.b64encode(b"robot:s3cret").decode()

    assert remote.authorization(settings, {"type": "none"}) is None
    assert remote.authorization(settings, {"type": "bearer", "secret": sealed}) == "Bearer s3cret"
    basic = {"type": "basic", "username": "robot", "secret": sealed}
    assert remote.authorization(settings, basic) == expected_basic


def test_a_credential_sealed_with_another_key_is_unreadable(tmp_path):
    here = Settings(_env_file=None, database_url="postgresql://u:p@db/m", data_dir=tmp_path)
    sealed = seal(here.model_copy(update={"secret_key": "another key"}), "s3cret")

    with pytest.raises(SecretUnreadable):
        remote.authorization(here, {"type": "bearer", "secret": sealed})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_remote.py -q`
Expected: collection error, `cannot import name 'new_client' from 'megooarti.repositories.remote'` (or `No module named 'megooarti.repositories.remote'`).

- [ ] **Step 4: Implement**

httpx is already installed as a development dependency. It is now needed at runtime, so move it: run in `backend/` `uv add httpx`.

`backend/src/megooarti/repositories/remote.py`:

```python
"""Talking to a proxy repository's remote.

Every outcome is a value, not an exception, so the proxy engine decides what a failure
means: serve a cached copy, answer 404, or count it towards blocking the remote.
"""

import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from megooarti import __version__
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.secrets_box import unseal
from megooarti.storage.backends import StagedBlob

# Receives the body and the size the remote declared, if any; returns it staged.
Stage = Callable[[AsyncIterator[bytes], int | None], Awaitable[StagedBlob]]

# What a HEAD answer passes on to the client.
_HEAD_HEADERS = ("Content-Length", "Content-Type", "Last-Modified", "ETag")


@dataclass(frozen=True)
class Fetched:
    staged: StagedBlob
    content_type: str | None
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class NotModified:
    pass


@dataclass(frozen=True)
class Missing:
    pass


@dataclass(frozen=True)
class Failed:
    reason: str
    blockable: bool  # counts towards blocking the remote


@dataclass(frozen=True)
class Exists:
    headers: dict[str, str]


def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,  # httpx drops Authorization when the host changes
        max_redirects=5,
        timeout=httpx.Timeout(60.0, connect=10.0),
        headers={"User-Agent": f"MegooArti/{__version__}"},
    )


def authorization(settings: Settings, remote_auth: dict[str, Any]) -> str | None:
    """The Authorization header for a stored credential. Raises SecretUnreadable."""
    kind = remote_auth.get("type", "none")
    if kind == "none":
        return None
    secret = unseal(settings, remote_auth["secret"])
    if kind == "bearer":
        return f"Bearer {secret}"
    pair = f"{remote_auth['username']}:{secret}".encode()
    return f"Basic {base64.b64encode(pair).decode()}"


def _request_headers(
    authorization: str | None, etag: str | None = None, last_modified: str | None = None
) -> dict[str, str]:
    # identity: store the bytes the remote holds, not a transfer encoding of them.
    headers = {"Accept-Encoding": "identity"}
    if authorization:
        headers["Authorization"] = authorization
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


def _unexpected(status: int) -> Failed:
    return Failed(f"the remote answered {status}", blockable=status >= 500 or status == 429)


def _declared_size(response: httpx.Response) -> int | None:
    if "Content-Encoding" in response.headers:
        return None
    value = response.headers.get("Content-Length", "")
    plain = value.isascii() and value.isdigit() and len(value) <= 18
    return int(value) if plain else None


async def download(
    client: httpx.AsyncClient,
    url: str,
    *,
    authorization: str | None,
    stage: Stage,
    etag: str | None = None,
    last_modified: str | None = None,
) -> Fetched | NotModified | Missing | Failed:
    """Fetch a file completely, or learn that it is unchanged, absent or unavailable."""
    headers = _request_headers(authorization, etag, last_modified)
    try:
        async with client.stream("GET", url, headers=headers) as response:
            status = response.status_code
            if status == 304:
                return NotModified()
            if status in (404, 410):
                return Missing()
            if status != 200:
                return _unexpected(status)
            try:
                staged = await stage(response.aiter_raw(), _declared_size(response))
            except ApiError:  # not the number of bytes the remote declared
                return Failed("the remote sent an incomplete file", blockable=True)
            return Fetched(
                staged=staged,
                content_type=response.headers.get("Content-Type"),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)


async def head(
    client: httpx.AsyncClient, url: str, *, authorization: str | None
) -> Exists | Missing | Failed:
    """Ask whether the remote has a file, without fetching it."""
    try:
        response = await client.head(url, headers=_request_headers(authorization))
    except httpx.HTTPError as error:
        return Failed(type(error).__name__, blockable=True)
    if response.status_code in (404, 410):
        return Missing()
    if response.status_code != 200:
        return _unexpected(response.status_code)
    passed_on = {name: response.headers[name] for name in _HEAD_HEADERS if name in response.headers}
    return Exists(headers=passed_on)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_remote.py -q`
Expected: 17 passed.

- [ ] **Step 6: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): add the outbound client for proxy remotes"
```

---

### Task 6: What a proxy remembers about its remote

**Files:**
- Create: `backend/src/megooarti/repositories/proxy_state.py`
- Test: `backend/tests/repositories/test_proxy_state.py`

**Interfaces:**
- Consumes: `ProxyState`, `NegativeCacheEntry` (Task 2); a proxy repository's `config["proxy"]` (Task 3); fixture `mirror` (Task 4).
- Produces, in `megooarti.repositories.proxy_state`:
  - `block_seconds(failures: int) -> int` — 60, doubling per consecutive failure, at most 3600
  - `blocked(db, repository, now) -> bool` — blocked by hand (`config["proxy"]["blocked"]`) or automatically until a time still in the future
  - `record_failure(db, repository, now, reason, *, blockable) -> None` — always records `last_error` and `last_checked_at`; counts the failure and extends the block only if `blockable` and the repository has `auto_block`
  - `record_success(db, repository, now) -> None` — clears failures and the block
  - `remember_missing(db, repository, path, now) -> None` — no-op when the negative cache is off
  - `known_missing(db, repository, path, now) -> bool`
  - None of these commit.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_proxy_state.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from megooarti.repositories import proxy_state, service
from megooarti.repositories.models import ProxyState

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REMOTE = {"remote_url": "http://remote.test/files"}


def after(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


async def fail(db, repository, when=NOW, *, blockable=True, reason="ConnectError"):
    await proxy_state.record_failure(db, repository, when, reason, blockable=blockable)


async def reconfigure(db, repository, **settings):
    await service.update_repository(db, repository, online=True, proxy={**REMOTE, **settings})


@pytest.mark.parametrize(
    ("failures", "seconds"), [(1, 60), (2, 120), (3, 240), (6, 1920), (7, 3600), (40, 3600)]
)
def test_the_block_doubles_from_a_minute_up_to_an_hour(failures, seconds):
    assert proxy_state.block_seconds(failures) == seconds


async def test_a_proxy_starts_unblocked(db, mirror):
    assert await proxy_state.blocked(db, mirror, NOW) is False


async def test_a_failure_blocks_for_a_minute_and_records_what_happened(db, mirror):
    await fail(db, mirror)

    state = await db.get(ProxyState, mirror.id)

    assert (state.failures, state.last_error, state.last_checked_at) == (1, "ConnectError", NOW)
    assert state.blocked_until == after(60)
    assert await proxy_state.blocked(db, mirror, after(59)) is True
    assert await proxy_state.blocked(db, mirror, after(60)) is False


async def test_consecutive_failures_lengthen_the_block(db, mirror):
    await fail(db, mirror)
    await fail(db, mirror, after(60))
    await fail(db, mirror, after(180))

    state = await db.get(ProxyState, mirror.id)

    assert state.failures == 3
    assert state.blocked_until == after(180 + 240)


async def test_a_failure_that_is_not_blockable_is_recorded_without_blocking(db, mirror):
    await fail(db, mirror, blockable=False, reason="the remote answered 401")

    state = await db.get(ProxyState, mirror.id)

    assert (state.failures, state.blocked_until) == (0, None)
    assert state.last_error == "the remote answered 401"
    assert await proxy_state.blocked(db, mirror, NOW) is False


async def test_auto_block_can_be_turned_off(db, mirror):
    await reconfigure(db, mirror, auto_block=False)

    await fail(db, mirror)

    assert await proxy_state.blocked(db, mirror, NOW) is False
    assert (await db.get(ProxyState, mirror.id)).last_error == "ConnectError"


async def test_a_success_clears_the_block(db, mirror):
    await fail(db, mirror)
    await fail(db, mirror, after(60))

    await proxy_state.record_success(db, mirror, after(61))

    state = await db.get(ProxyState, mirror.id, populate_existing=True)
    assert (state.failures, state.blocked_until, state.last_error) == (0, None, None)
    assert await proxy_state.blocked(db, mirror, after(61)) is False


async def test_a_success_with_nothing_recorded_is_harmless(db, mirror):
    await proxy_state.record_success(db, mirror, NOW)

    assert await db.get(ProxyState, mirror.id) is None


async def test_a_proxy_blocked_by_hand_stays_blocked(db, mirror):
    await reconfigure(db, mirror, blocked=True)

    assert await proxy_state.blocked(db, mirror, after(10**6)) is True


async def test_a_long_reason_is_shortened_to_fit(db, mirror):
    await fail(db, mirror, reason="x" * 1000)

    assert len((await db.get(ProxyState, mirror.id)).last_error) == 255


async def test_a_missing_path_is_remembered_until_it_expires(db, mirror):
    await reconfigure(db, mirror, negative_cache={"ttl_minutes": 10})

    await proxy_state.remember_missing(db, mirror, "nothing/here.bin", NOW)

    assert await proxy_state.known_missing(db, mirror, "nothing/here.bin", after(599)) is True
    assert await proxy_state.known_missing(db, mirror, "nothing/here.bin", after(600)) is False
    assert await proxy_state.known_missing(db, mirror, "something/else.bin", NOW) is False


async def test_remembering_again_extends_the_time(db, mirror):
    await reconfigure(db, mirror, negative_cache={"ttl_minutes": 10})
    await proxy_state.remember_missing(db, mirror, "a.bin", NOW)

    await proxy_state.remember_missing(db, mirror, "a.bin", after(300))

    assert await proxy_state.known_missing(db, mirror, "a.bin", after(899)) is True


async def test_nothing_is_remembered_when_the_negative_cache_is_off(db, mirror):
    await reconfigure(db, mirror, negative_cache={"enabled": False})

    await proxy_state.remember_missing(db, mirror, "a.bin", NOW)

    assert await proxy_state.known_missing(db, mirror, "a.bin", NOW) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_proxy_state.py -q`
Expected: collection error, `cannot import name 'proxy_state' from 'megooarti.repositories'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/proxy_state.py`:

```python
"""What a proxy repository has learned about its remote.

Two things, both kept in the database so that every container shares them: how the
remote has been failing (and so whether it is blocked), and which paths it said it
does not have.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.models import NegativeCacheEntry, ProxyState, Repository

_FIRST_BLOCK_SECONDS = 60
_LONGEST_BLOCK_SECONDS = 3600


def block_seconds(failures: int) -> int:
    """How long to leave the remote alone after this many consecutive failures."""
    doubled = _FIRST_BLOCK_SECONDS * 2 ** min(failures - 1, 16)
    return min(doubled, _LONGEST_BLOCK_SECONDS)


async def blocked(db: AsyncSession, repository: Repository, now: datetime) -> bool:
    if repository.config["proxy"]["blocked"]:
        return True
    until = await db.scalar(
        select(ProxyState.blocked_until).where(ProxyState.repository_id == repository.id)
    )
    return until is not None and until > now


async def record_failure(
    db: AsyncSession, repository: Repository, now: datetime, reason: str, *, blockable: bool
) -> None:
    # Make sure the row exists, then lock it, so concurrent failures count once each.
    await db.execute(
        insert(ProxyState).values(repository_id=repository.id, failures=0).on_conflict_do_nothing()
    )
    state = await db.scalar(
        select(ProxyState)
        .where(ProxyState.repository_id == repository.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    state.last_error = reason[:255]
    state.last_checked_at = now
    if blockable and repository.config["proxy"]["auto_block"]:
        state.failures += 1
        state.blocked_until = now + timedelta(seconds=block_seconds(state.failures))
    await db.flush()


async def record_success(db: AsyncSession, repository: Repository, now: datetime) -> None:
    await db.execute(
        update(ProxyState)
        .where(ProxyState.repository_id == repository.id)
        .values(failures=0, blocked_until=None, last_error=None, last_checked_at=now)
    )


def _negative_cache(repository: Repository) -> dict:
    return repository.config["proxy"]["negative_cache"]


async def remember_missing(
    db: AsyncSession, repository: Repository, path: str, now: datetime
) -> None:
    """Note that the remote does not have this path, for the configured time."""
    settings = _negative_cache(repository)
    if not settings["enabled"]:
        return
    await db.execute(delete(NegativeCacheEntry).where(NegativeCacheEntry.expires_at <= now))
    expires = now + timedelta(minutes=settings["ttl_minutes"])
    remember = insert(NegativeCacheEntry).values(
        repository_id=repository.id, path=path, expires_at=expires
    )
    await db.execute(
        remember.on_conflict_do_update(
            index_elements=[NegativeCacheEntry.repository_id, NegativeCacheEntry.path],
            set_={"expires_at": expires},
        )
    )


async def known_missing(
    db: AsyncSession, repository: Repository, path: str, now: datetime
) -> bool:
    if not _negative_cache(repository)["enabled"]:
        return False
    expires = await db.scalar(
        select(NegativeCacheEntry.expires_at).where(
            NegativeCacheEntry.repository_id == repository.id, NegativeCacheEntry.path == path
        )
    )
    return expires is not None and expires > now
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_proxy_state.py -q`
Expected: 18 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): record remote failures, blocking and missing paths"
```

---

### Task 7: The proxy engine

**Files:**
- Create: `backend/src/megooarti/keyed_locks.py`
- Create: `backend/src/megooarti/repositories/proxy.py`
- Modify: `backend/src/megooarti/repositories/dispatch.py`
- Modify: `backend/src/megooarti/repositories/api.py`
- Modify: `backend/src/megooarti/main.py` (replace the whole file)
- Modify: `backend/tests/repositories/conftest.py`
- Modify: `backend/tests/repositories/test_api.py`
- Test: `backend/tests/test_keyed_locks.py`
- Test: `backend/tests/repositories/test_proxy.py`
- Test: `backend/tests/repositories/test_proxy_races.py`

**Interfaces:**
- Consumes: `RepositoryContext.get`, `.stage`, `.cache`, `.respond` (Task 4); `remote.download`, `remote.head`, `remote.authorization`, `remote.new_client` and the outcome types (Task 5); `proxy_state.*` (Task 6); `Format.remote_url`, `Format.is_metadata` (Task 2); `service.invalidate_cache` (Task 3); `dispatch.ENGINES` (Task 4).
- Produces:
  - `megooarti.keyed_locks.KeyedLocks` with `hold(key)` (an async context manager) and `len()`.
  - `megooarti.repositories.proxy.handle_proxy(context, request, path) -> Response`, registered as the `proxy` engine. It reads the outbound client from `request.app.state.http`.
  - `app.state.http: httpx.AsyncClient`, created with the application and closed at shutdown.
  - `POST /api/v1/repositories/{name}/invalidate-cache` → `204`; needs `admin:repositories:write`; `409 not_a_proxy` for other types.
  - A cached asset's `attributes` hold `remote_etag` and `remote_last_modified` when the remote sent them.
  - Test fixture `fake_remote` (in `tests/repositories/conftest.py`): a `FakeRemote` whose client replaces `app.state.http`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_keyed_locks.py`:

```python
import asyncio

from megooarti.keyed_locks import KeyedLocks


async def test_holders_of_one_key_take_turns():
    locks, order = KeyedLocks(), []

    async def work(name: str) -> None:
        async with locks.hold("same"):
            order.append(f"{name} in")
            await asyncio.sleep(0.02)
            order.append(f"{name} out")

    await asyncio.gather(work("a"), work("b"))

    assert order == ["a in", "a out", "b in", "b out"]


async def test_holders_of_different_keys_do_not_wait_for_each_other():
    locks, order = KeyedLocks(), []

    async def work(key: str) -> None:
        async with locks.hold(key):
            order.append(f"{key} in")
            await asyncio.sleep(0.02)
            order.append(f"{key} out")

    await asyncio.gather(work("one"), work("two"))

    assert order[:2] == ["one in", "two in"]


async def test_nothing_is_kept_once_a_key_is_released_even_after_an_error():
    locks = KeyedLocks()

    async with locks.hold("a"):
        assert len(locks) == 1
    try:
        async with locks.hold("b"):
            raise RuntimeError("the work failed")
    except RuntimeError:
        pass

    assert len(locks) == 0
```

Add to `backend/tests/repositories/conftest.py`, with the import `from tests.repositories.fake_remote import FakeRemote`:

```python
@pytest.fixture
async def fake_remote(app) -> FakeRemote:
    """A remote that exists only in this process, wired in place of the real client."""
    await app.state.http.aclose()
    fake = FakeRemote()
    app.state.http = fake.client()
    return fake
```

`backend/tests/repositories/test_proxy.py`:

```python
import base64
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.repositories import proxy
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset, NegativeCacheEntry, ProxyState, Repository
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.fake_remote import etag_of

URL = "/repository/mirror/lib/a.bin"
REMOTE_FILE = "files/lib/a.bin"
REMOTE_PATH = "/files/lib/a.bin"
CONTENT = b"content held by the remote"
REPOSITORIES = "/api/v1/repositories"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


@pytest.fixture
def remote(fake_remote, mirror):
    fake_remote.files[REMOTE_FILE] = CONTENT
    return fake_remote


async def make_stale(db) -> None:
    long_ago = utcnow() - timedelta(days=3)
    await db.execute(update(Asset).values(last_verified_at=long_ago))
    await db.commit()


async def reconfigure(db, mirror, **settings) -> None:
    current = dict(mirror.config)
    current["proxy"] = {**current["proxy"], **settings}
    mirror.config = current
    await db.commit()


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_a_miss_is_fetched_cached_and_served(client, root, remote):
    first = await client.get(URL, headers=root)
    second = await client.get(URL, headers=root)

    assert (first.status_code, first.content) == (200, CONTENT)
    assert second.content == CONTENT
    assert first.headers["ETag"] == f'"{hashlib.sha256(CONTENT).hexdigest()}"'
    assert first.headers["Content-Type"] == "application/x-remote"
    assert first.headers["Content-Disposition"].startswith('attachment; filename="a.bin"')
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert remote.paths() == [REMOTE_PATH]


async def test_the_cached_file_records_where_it_came_from(client, root, remote, db):
    await client.get(URL, headers=root)

    asset = await db.scalar(select(Asset))

    assert (asset.path, asset.created_by) == ("lib/a.bin", "proxy")
    assert asset.attributes["remote_etag"] == etag_of(CONTENT)
    assert asset.last_verified_at is not None


async def test_a_reader_needs_only_read_to_fill_the_cache(client, remote, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:raw:mirror:read"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])

    response = await client.get(URL, headers=basic("rae", PASSWORD))

    assert (response.status_code, response.content) == (200, CONTENT)


async def test_a_path_with_unusual_characters_is_encoded_for_the_remote(client, root, remote):
    remote.files["files/with space/ünï.bin"] = b"odd name"

    response = await client.get("/repository/mirror/with%20space/%C3%BCn%C3%AF.bin", headers=root)

    assert response.content == b"odd name"


async def test_what_the_remote_lacks_is_not_found_and_remembered(client, root, remote, db):
    missing = "/repository/mirror/nothing/here.bin"

    first = await client.get(missing, headers=root)
    second = await client.get(missing, headers=root)

    assert (first.status_code, error_code(first)) == (404, "not_found")
    assert second.status_code == 404
    assert remote.paths() == ["/files/nothing/here.bin"]

    await db.execute(update(NegativeCacheEntry).values(expires_at=utcnow() - timedelta(seconds=1)))
    await db.commit()
    await client.get(missing, headers=root)

    assert len(remote.paths()) == 2


async def test_with_the_negative_cache_off_the_remote_is_asked_every_time(
    client, root, remote, mirror, db
):
    await reconfigure(db, mirror, negative_cache={"enabled": False, "ttl_minutes": 1440})

    for _ in range(2):
        await client.get("/repository/mirror/nothing.bin", headers=root)

    assert len(remote.paths()) == 2


async def test_a_stale_file_is_revalidated_and_kept_when_unchanged(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)

    response = await client.get(URL, headers=root)

    assert response.content == CONTENT
    conditional = remote.requests[1]["headers"]
    assert conditional["if-none-match"] == etag_of(CONTENT)
    verified = await db.scalar(select(Asset.last_verified_at))
    assert utcnow() - verified < timedelta(minutes=1)


async def test_a_stale_file_is_replaced_when_the_remote_changed(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.files[REMOTE_FILE] = b"a newer version"

    response = await client.get(URL, headers=root)

    assert response.content == b"a newer version"
    assert await count(db, Asset) == 1


async def test_a_maximum_age_of_minus_one_never_revalidates(client, root, remote, mirror, db):
    await reconfigure(db, mirror, content_max_age_minutes=-1)
    await client.get(URL, headers=root)
    long_ago = datetime(2020, 1, 1, tzinfo=UTC)
    await db.execute(update(Asset).values(last_verified_at=long_ago))
    await db.commit()

    await client.get(URL, headers=root)

    assert len(remote.paths()) == 1


def test_metadata_paths_use_the_metadata_age():
    class WithIndex(Format):
        def is_metadata(self, path: str) -> bool:
            return path.endswith("index.json")

    ages = {"content_max_age_minutes": -1, "metadata_max_age_minutes": 10}
    verified = datetime(2026, 1, 1, tzinfo=UTC)
    asset = Asset(last_verified_at=verified)
    later = verified + timedelta(minutes=11)

    assert proxy.is_fresh(ages, WithIndex(), asset, "pkg/thing.tgz", later) is True
    assert proxy.is_fresh(ages, WithIndex(), asset, "pkg/index.json", later) is False
    assert proxy.is_fresh(ages, WithIndex(), Asset(), "pkg/thing.tgz", later) is False


async def test_a_cached_file_is_served_while_the_remote_is_down(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.down = True

    first = await client.get(URL, headers=root)
    asked = len(remote.requests)
    second = await client.get(URL, headers=root)

    assert (first.status_code, first.content) == (200, CONTENT)
    assert second.content == CONTENT
    state = await db.scalar(select(ProxyState))
    assert (state.failures, state.last_error) == (1, "ConnectError")
    assert state.blocked_until > utcnow()
    assert len(remote.requests) == asked  # blocked: the remote was left alone


async def test_a_miss_while_the_remote_is_down_is_bad_gateway_then_blocked(
    client, root, remote, db
):
    remote.down = True

    first = await client.get(URL, headers=root)
    remote.down = False
    second = await client.get(URL, headers=root)

    assert (first.status_code, error_code(first)) == (502, "remote_unavailable")
    assert (second.status_code, error_code(second)) == (502, "remote_unavailable")
    assert remote.paths() == []  # the second request never reached the working remote


async def test_the_block_ends_and_a_success_clears_it(client, root, remote, db):
    remote.down = True
    await client.get(URL, headers=root)
    remote.down = False
    await db.execute(update(ProxyState).values(blocked_until=utcnow() - timedelta(seconds=1)))
    await db.commit()

    response = await client.get(URL, headers=root)

    assert response.content == CONTENT
    state = await db.scalar(select(ProxyState).execution_options(populate_existing=True))
    assert (state.failures, state.blocked_until, state.last_error) == (0, None, None)


async def test_a_proxy_blocked_by_hand_serves_its_cache_and_fetches_nothing(
    client, root, remote, mirror, db
):
    await client.get(URL, headers=root)
    await reconfigure(db, mirror, blocked=True)
    await make_stale(db)

    cached = await client.get(URL, headers=root)
    uncached = await client.get("/repository/mirror/other.bin", headers=root)

    assert cached.content == CONTENT
    assert (uncached.status_code, error_code(uncached)) == (502, "remote_unavailable")
    assert len(remote.paths()) == 1


async def test_a_refused_credential_fails_each_request_without_blocking(client, root, remote):
    remote.status = 401

    first = await client.get(URL, headers=root)
    second = await client.get(URL, headers=root)

    assert (first.status_code, error_code(first)) == (502, "remote_unavailable")
    assert "401" in first.json()["error"]["message"]
    assert second.status_code == 502
    assert len(remote.paths()) == 2


async def test_an_incomplete_download_caches_nothing(client, root, remote, db):
    remote.declared_extra = 7

    response = await client.get(URL, headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert await count(db, Asset) == 0


async def test_an_incomplete_refresh_keeps_the_previous_copy(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.files[REMOTE_FILE] = b"a newer version"
    remote.declared_extra = 7

    response = await client.get(URL, headers=root)

    assert (response.status_code, response.content) == (200, CONTENT)


async def test_a_cached_file_survives_the_remote_dropping_it(client, root, remote, db):
    await client.get(URL, headers=root)
    await make_stale(db)
    remote.files.clear()

    response = await client.get(URL, headers=root)
    again = await client.get(URL, headers=root)

    assert (response.status_code, response.content) == (200, CONTENT)
    assert again.content == CONTENT
    assert len(remote.paths()) == 2  # asked once more, then trusted for the maximum age
    assert await count(db, NegativeCacheEntry) == 0


async def test_the_stored_credential_is_sent_to_the_remote(admin_client, fake_remote):
    fake_remote.files["files/lib/a.bin"] = CONTENT
    await admin_client.post(
        REPOSITORIES,
        json={
            "name": "private",
            "format": "raw",
            "type": "proxy",
            "proxy": {
                "remote_url": "http://remote.test/files",
                "remote_auth": {"type": "basic", "username": "robot", "secret": "s3cret"},
            },
        },
    )

    response = await admin_client.get("/repository/private/lib/a.bin")

    assert response.content == CONTENT
    expected = "Basic " + base64.b64encode(b"robot:s3cret").decode()
    assert fake_remote.requests[0]["headers"]["authorization"] == expected


async def test_a_credential_that_cannot_be_unsealed_is_reported_without_asking(
    client, root, remote, mirror, db
):
    broken = {"type": "bearer", "username": "", "secret": "enc:v1:not-sealed-with-this-key"}
    await reconfigure(db, mirror, remote_auth=broken)

    response = await client.get(URL, headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert "credential" in response.json()["error"]["message"]
    assert remote.requests == []


async def test_head_for_an_uncached_file_asks_the_remote_and_caches_nothing(
    client, root, remote, db
):
    head = await client.head(URL, headers=root)
    missing = await client.head("/repository/mirror/nothing.bin", headers=root)

    assert (head.status_code, head.content) == (200, b"")
    assert head.headers["Content-Length"] == str(len(CONTENT))
    assert head.headers["Content-Type"] == "application/x-remote"
    assert missing.status_code == 404
    assert [seen["method"] for seen in remote.requests] == ["HEAD", "HEAD"]
    assert await count(db, Asset) == 0


async def test_head_for_a_cached_file_is_answered_from_the_cache(client, root, remote):
    await client.get(URL, headers=root)

    head = await client.head(URL, headers=root)

    assert head.headers["Content-Length"] == str(len(CONTENT))
    assert head.headers["ETag"] == f'"{hashlib.sha256(CONTENT).hexdigest()}"'
    assert len(remote.requests) == 1


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
async def test_a_proxy_repository_cannot_be_written_to(client, root, remote, method, db):
    response = await client.request(method, URL, content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
    assert await count(db, Asset) == 0


async def test_invalidating_the_cache_makes_the_proxy_ask_again(admin_client, remote, db):
    await admin_client.get(URL)
    await admin_client.get("/repository/mirror/nothing.bin")
    assert len(remote.paths()) == 2

    response = await admin_client.post(f"{REPOSITORIES}/mirror/invalidate-cache")
    await admin_client.get(URL)
    await admin_client.get("/repository/mirror/nothing.bin")

    assert response.status_code == 204
    assert len(remote.paths()) == 4
    assert remote.requests[2]["headers"]["if-none-match"] == etag_of(CONTENT)


async def test_invalidating_needs_a_proxy_and_the_permission(admin_client, other_client, files):
    not_a_proxy = await admin_client.post(f"{REPOSITORIES}/files/invalidate-cache")
    unknown = await admin_client.post(f"{REPOSITORIES}/ghost/invalidate-cache")
    anonymous = await other_client.post(f"{REPOSITORIES}/files/invalidate-cache")

    assert (not_a_proxy.status_code, error_code(not_a_proxy)) == (409, "not_a_proxy")
    assert unknown.status_code == 404
    assert anonymous.status_code == 401


async def test_the_repository_api_shows_the_blocking_state(admin_client, remote, db):
    remote.down = True
    await admin_client.get(URL)

    status = (await admin_client.get(f"{REPOSITORIES}/mirror")).json()["status"]

    assert (status["blocked"], status["failures"], status["last_error"]) == (
        False,
        1,
        "ConnectError",
    )
    assert status["auto_blocked_until"] is not None
    assert await db.scalar(select(Repository.type).where(Repository.name == "mirror")) == "proxy"
```

`backend/tests/repositories/test_proxy_races.py`:

```python
"""Many readers of one uncached file, with real concurrent database sessions."""

import asyncio
from types import SimpleNamespace

from starlette.requests import Request

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Repository
from megooarti.repositories.proxy import handle_proxy
from tests.repositories.fake_remote import FakeRemote
from tests.storage.test_races import Factory, run

CONTENT = b"a large file, slowly served" * 1000


def test_many_readers_of_one_uncached_file_ask_the_remote_once(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        async with factory() as db:
            repository = await service.create_repository(
                db,
                name="mirror",
                format="raw",
                type="proxy",
                online=True,
                blob_store=None,
                proxy={"remote_url": "http://remote.test/files"},
            )
            await db.commit()
        fake = FakeRemote()
        fake.files["files/big.bin"] = CONTENT
        fake.delay = 0.2
        http = fake.client()
        application = SimpleNamespace(state=SimpleNamespace(http=http))

        async def read_once() -> bytes:
            async with factory() as db:
                mirror = await db.get(Repository, repository.id)
                context = await build_context(db, settings, mirror, None)
                request = Request(
                    {"type": "http", "method": "GET", "path": "/", "headers": [], "app": application}
                )
                response = await handle_proxy(context, request, "big.bin")
                return b"".join([chunk async for chunk in response.body_iterator])

        try:
            bodies = await asyncio.gather(*(read_once() for _ in range(6)))
        finally:
            await http.aclose()

        assert bodies == [CONTENT] * 6
        assert fake.paths() == ["/files/big.bin"]

    run(empty_database, tmp_path, scenario)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_keyed_locks.py tests/repositories/test_proxy.py tests/repositories/test_proxy_races.py -q`
Expected: three collection errors: `No module named 'megooarti.keyed_locks'`, `cannot import name 'proxy' from 'megooarti.repositories'`, and `No module named 'megooarti.repositories.proxy'`.

- [ ] **Step 3: Implement the keyed locks**

`backend/src/megooarti/keyed_locks.py`:

```python
"""One lock per key, for work that should happen once per key inside this process."""

import asyncio
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager


class KeyedLocks:
    """Locks created on demand and forgotten when nobody holds or waits for them."""

    def __init__(self) -> None:
        self._entries: dict[Hashable, list] = {}  # key -> [lock, number of users]

    def __len__(self) -> int:
        return len(self._entries)

    @asynccontextmanager
    async def hold(self, key: Hashable) -> AsyncIterator[None]:
        entry = self._entries.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                del self._entries[key]
```

- [ ] **Step 4: Implement the proxy engine**

`backend/src/megooarti/repositories/proxy.py`:

```python
"""Proxy repositories: fetch from the remote on a miss, cache, and keep serving.

A missing file is downloaded completely, verified and recorded, and only then served.
Every exit that the client should remember (a cached file, a remembered miss, a
recorded failure) is committed here, because several of them end in an error response.
"""

from datetime import datetime, timedelta
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.keyed_locks import KeyedLocks
from megooarti.repositories import proxy_state, remote
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset
from megooarti.repositories.paths import normalise_path
from megooarti.secrets_box import SecretUnreadable
from megooarti.storage.backends import StagedBlob

log = structlog.get_logger(__name__)

# Within this process, concurrent requests for one uncached path share one download.
_downloads = KeyedLocks()


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


def _unavailable(reason: str) -> ApiError:
    return ApiError(
        502, "remote_unavailable", f"The remote repository is not available: {reason}."
    )


def is_fresh(
    settings: dict[str, Any], format: Format, asset: Asset, path: str, now: datetime
) -> bool:
    """Whether a cached file may be served without asking the remote."""
    if asset.last_verified_at is None:
        return False
    kind = "metadata" if format.is_metadata(path) else "content"
    minutes = settings[f"{kind}_max_age_minutes"]
    return minutes < 0 or now - asset.last_verified_at < timedelta(minutes=minutes)


def _fresh(context: RepositoryContext, asset: Asset | None, path: str) -> bool:
    if asset is None:
        return False
    settings = context.repository.config["proxy"]
    return is_fresh(settings, context.format, asset, path, utcnow())


def _target(context: RepositoryContext, path: str) -> tuple[str, str | None]:
    """The remote URL for a path and the Authorization header to send with it."""
    settings = context.repository.config["proxy"]
    try:
        credential = remote.authorization(context.settings, settings["remote_auth"])
    except SecretUnreadable:
        raise _unavailable(
            "its stored credential cannot be read with the current key; enter it again"
        ) from None
    return context.format.remote_url(settings["remote_url"], path), credential


async def _fail(context: RepositoryContext, path: str, outcome: object) -> str:
    """Record that the remote did not help. Returns the reason, for the caller to use."""
    if isinstance(outcome, remote.Failed):
        reason, blockable = outcome.reason, outcome.blockable
    else:
        reason, blockable = "it gave an answer that makes no sense here", False
    await proxy_state.record_failure(
        context.db, context.repository, utcnow(), reason, blockable=blockable
    )
    await context.db.commit()
    log.warning("remote_failed", repository=context.repository.name, path=path, reason=reason)
    return reason


async def _refresh(
    context: RepositoryContext, request: Request, path: str, asset: Asset | None
) -> None:
    """Make `path` servable from the cache, or raise 404 or 502.

    Returning without raising means there is a copy to serve: a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.
    """
    db, repository = context.db, context.repository
    now = utcnow()
    if asset is None and await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        if asset is None:
            raise _unavailable("it is blocked")
        return
    url, credential = _target(context, path)
    known = {} if asset is None else asset.attributes
    await db.commit()  # give the connection back for the length of the download

    async def stage(chunks, size: int | None) -> StagedBlob:
        return await context.stage(chunks, expected_size=size)

    outcome = await remote.download(
        request.app.state.http,
        url,
        authorization=credential,
        stage=stage,
        etag=known.get("remote_etag"),
        last_modified=known.get("remote_last_modified"),
    )
    now = utcnow()

    if isinstance(outcome, remote.Fetched):
        origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
        await context.cache(
            path,
            outcome.staged,
            content_type=outcome.content_type,
            attributes={name: value for name, value in origin.items() if value},
            now=now,
        )
        await proxy_state.record_success(db, repository, now)
        await db.commit()
    elif isinstance(outcome, remote.NotModified) and asset is not None:
        asset.last_verified_at = now
        await proxy_state.record_success(db, repository, now)
        await db.commit()
    elif isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if asset is None:
            await proxy_state.remember_missing(db, repository, path, now)
            await db.commit()
            raise _not_found()
        # The remote dropped a file we hold. An artifact manager keeps it.
        asset.last_verified_at = now
        await db.commit()
    else:
        reason = await _fail(context, path, outcome)
        if asset is None:
            raise _unavailable(reason)


async def _head_remote(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer HEAD for a file that is not cached by asking the remote. Caches nothing."""
    db, repository = context.db, context.repository
    now = utcnow()
    if await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        raise _unavailable("it is blocked")
    url, credential = _target(context, path)
    await db.commit()

    outcome = await remote.head(request.app.state.http, url, authorization=credential)
    now = utcnow()
    if isinstance(outcome, remote.Exists):
        await proxy_state.record_success(db, repository, now)
        await db.commit()
        headers = {**outcome.headers, "X-Content-Type-Options": "nosniff"}
        return Response(status_code=200, headers=headers)
    if isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)
        await proxy_state.remember_missing(db, repository, path, now)
        await db.commit()
        raise _not_found()
    raise _unavailable(await _fail(context, path, outcome))


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a proxy repository. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    asset = await context.get(path)
    if _fresh(context, asset, path):
        return await context.respond(path, request)
    if asset is None and request.method == "HEAD":
        return await _head_remote(context, request, path)

    await context.db.commit()  # hold no connection while waiting for another's download
    async with _downloads.hold((context.repository.id, path)):
        asset = await context.get(path, fresh=True)  # the previous holder may have fetched it
        if not _fresh(context, asset, path):
            await _refresh(context, request, path, asset)
    return await context.respond(path, request)
```

- [ ] **Step 5: Register the engine, add the cache-invalidation route, and give the application an outbound client**

In `backend/src/megooarti/repositories/dispatch.py`, add the import `from megooarti.repositories.proxy import handle_proxy` and replace the `ENGINES` line with:

```python
ENGINES: dict[str, Engine] = {"hosted": _hosted, "proxy": handle_proxy}
```

Append to `backend/src/megooarti/repositories/api.py`:

```python


@router.post("/{name}/invalidate-cache", status_code=204)
async def invalidate_cache(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    await service.invalidate_cache(db, repository)
    await db.commit()
    log.info("repository_cache_invalidated", repository=name, by=principal.user.username)
```

Replace `backend/src/megooarti/main.py` with:

```python
"""Application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from megooarti import __version__
from megooarti.clock import utcnow
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.errors import ERROR_RESPONSES, UnhandledErrorMiddleware, register_error_handlers
from megooarti.maintenance import run_exclusively, run_periodically
from megooarti.repositories import raw as _raw_format  # noqa: F401  (registers the format)
from megooarti.repositories import remote
from megooarti.repositories.api import router as repositories_router
from megooarti.repositories.routes import router as content_router
from megooarti.request_id import RequestIdMiddleware
from megooarti.security.api import auth as auth_api
from megooarti.security.api import me as me_api
from megooarti.security.api import roles as roles_api
from megooarti.security.api import users as users_api
from megooarti.security.bootstrap import ensure_initial_admin_password
from megooarti.storage import blobs
from megooarti.storage.api import router as blob_stores_router
from megooarti.system.settings_api import router as settings_router
from megooarti.system.status import router as status_router

log = structlog.get_logger(__name__)

API_PREFIX = "/api/v1"
_FIRST_START_RETRY_SECONDS = 5
# Arbitrary constant, distinct from the other advisory lock keys.
_COMPACTION_LOCK_KEY = 0x4D45474F51


async def _first_start(app: FastAPI) -> None:
    # Read app.state at call time: tests replace the sessionmaker after create_app.
    await ensure_initial_admin_password(
        app.state.sessionmaker, app.state.settings, app.state.head_revision
    )


async def _first_start_when_possible(app: FastAPI, last_error: str) -> None:
    """Keep trying until the database is reachable and migrated."""
    while True:
        await asyncio.sleep(_FIRST_START_RETRY_SECONDS)
        try:
            await _first_start(app)
            return
        except Exception as error:
            if type(error).__name__ != last_error:  # log a change of cause, not every try
                last_error = type(error).__name__
                log.warning("initial_admin_password_deferred", error=last_error)


async def _compact(app: FastAPI) -> None:
    settings = app.state.settings

    async def job() -> None:
        removed = await blobs.compact(
            app.state.sessionmaker,
            settings,
            now=utcnow(),
            grace_seconds=settings.blob_grace_seconds,
        )
        log.info("compaction_finished", removed=removed)

    await run_exclusively(app.state.engine, _COMPACTION_LOCK_KEY, job)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    background: list[asyncio.Task[None]] = []
    try:
        await _first_start(app)
    except Exception as error:  # the database is not reachable or not migrated yet
        cause = type(error).__name__
        log.warning("initial_admin_password_deferred", error=cause)
        background.append(asyncio.create_task(_first_start_when_possible(app, cause)))
    if settings.compaction_interval_seconds > 0:
        background.append(
            asyncio.create_task(
                run_periodically(
                    "compaction", settings.compaction_interval_seconds, lambda: _compact(app)
                )
            )
        )
    yield
    for task in background:
        task.cancel()
    for task in background:
        with suppress(asyncio.CancelledError):
            await task
    await app.state.http.aclose()
    await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MegooArti",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=_lifespan,
        responses=ERROR_RESPONSES,
    )
    app.state.settings = settings
    # Creating the engine opens no connection; the pool connects on first use.
    # hide_parameters keeps bound values (tokens, password hashes) out of error text and logs.
    app.state.engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, hide_parameters=True
    )
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
    app.state.head_revision = head_revision()
    # The one client for requests to proxy remotes. Tests replace it with a fake remote.
    app.state.http = remote.new_client()
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    app.include_router(auth_api.router, prefix=API_PREFIX)
    app.include_router(me_api.router, prefix=API_PREFIX)
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(roles_api.router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)
    app.include_router(blob_stores_router, prefix=API_PREFIX)
    app.include_router(repositories_router, prefix=API_PREFIX)
    app.include_router(content_router)  # /repository/..., outside the JSON API

    # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
    # first, so its 500 response passes through every other middleware, and keep
    # RequestIdMiddleware last, so everything else runs with a request ID.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_keyed_locks.py tests/repositories/test_proxy.py tests/repositories/test_proxy_races.py tests/test_route_guards.py -q`
Expected: no failures; `test_keyed_locks.py` reports 3 passed, `test_proxy.py` 28 passed and `test_proxy_races.py` 1 passed.

Run in `backend/`: `uv run pytest -q`
Expected: no failures.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): serve proxy repositories with caching, revalidation and blocking"
```

---

### Task 8: The group engine

**Files:**
- Create: `backend/src/megooarti/repositories/group.py`
- Modify: `backend/src/megooarti/repositories/dispatch.py`
- Test: `backend/tests/repositories/test_group.py`

**Interfaces:**
- Consumes: `service.members` (Task 3); `build_context` (Task 4); `dispatch.serve`, `Engine` (Task 4); fixture `fake_remote` (Task 7).
- Produces: `megooarti.repositories.group.handle_group(context, request, path, serve) -> Response`, registered as the `group` engine. Members are tried in order with the caller's principal but no permission check; offline members are skipped; a member answering `404`, `502` or `503` means "try the next"; any other error is returned; if none answers, `404`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_group.py`:

```python
import pytest
from sqlalchemy import insert

from megooarti.repositories import service
from megooarti.repositories.models import RepositoryMember
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

FILE = "docs/a.txt"
GROUP = f"/repository/all/{FILE}"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, type: str = "hosted", **settings):
    repository = await service.create_repository(
        db, name=name, format="raw", type=type, online=True, blob_store=None, **settings
    )
    await db.commit()
    return repository


@pytest.fixture
async def everything(db):
    """Hosted `one` and `two`, presented in that order by the group `all`."""
    await create(db, "one")
    await create(db, "two")
    return await create(db, "all", "group", group={"members": ["one", "two"]})


async def put(client, root, repository: str, content: bytes, path: str = FILE) -> None:
    response = await client.put(f"/repository/{repository}/{path}", content=content, headers=root)
    assert response.status_code in (201, 204)


async def reorder(db, group, members: list[str]) -> None:
    await service.update_repository(db, group, online=True, group={"members": members})
    await db.commit()


async def test_the_first_member_that_has_the_path_answers(client, root, everything, db):
    await put(client, root, "one", b"from one")
    await put(client, root, "two", b"from two")

    first = await client.get(GROUP, headers=root)
    await reorder(db, everything, ["two", "one"])
    second = await client.get(GROUP, headers=root)

    assert (first.status_code, first.content) == (200, b"from one")
    assert second.content == b"from two"
    assert first.headers["Content-Disposition"].startswith('attachment; filename="a.txt"')


async def test_a_later_member_answers_when_earlier_ones_lack_the_path(client, root, everything):
    await put(client, root, "two", b"only in two")

    assert (await client.get(GROUP, headers=root)).content == b"only in two"


async def test_not_found_when_no_member_has_the_path(client, root, everything):
    response = await client.get(GROUP, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_an_empty_group_has_nothing(client, root, db):
    await create(db, "all", "group")

    assert (await client.get(GROUP, headers=root)).status_code == 404


async def test_an_offline_member_is_skipped(client, root, everything, db):
    await put(client, root, "one", b"from one")
    await put(client, root, "two", b"from two")
    one = await service.get_repository(db, "one")
    await service.update_repository(db, one, online=False)
    await db.commit()

    assert (await client.get(GROUP, headers=root)).content == b"from two"


async def test_head_and_ranges_work_through_a_group(client, root, everything):
    await put(client, root, "one", b"hello, world")

    head = await client.head(GROUP, headers=root)
    partial = await client.get(GROUP, headers={**root, "Range": "bytes=7-"})

    assert (head.status_code, head.headers["Content-Length"]) == (200, "12")
    assert (partial.status_code, partial.content) == (206, b"world")


async def test_a_range_outside_the_file_is_reported_not_skipped(client, root, everything):
    await put(client, root, "one", b"short")
    await put(client, root, "two", b"a much longer file in the second member")

    response = await client.get(GROUP, headers={**root, "Range": "bytes=20-"})

    assert (response.status_code, error_code(response)) == (416, "range_not_satisfiable")


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
async def test_a_group_cannot_be_written_to(client, root, everything, method):
    response = await client.request(method, GROUP, content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"


async def test_a_proxy_member_fetches_and_caches_through_the_group(
    client, root, mirror, fake_remote, db
):
    fake_remote.files[f"files/{FILE}"] = b"from the remote"
    await create(db, "one")
    await create(db, "all", "group", group={"members": ["one", "mirror"]})

    first = await client.get(GROUP, headers=root)
    second = await client.get(GROUP, headers=root)

    assert (first.content, second.content) == (b"from the remote", b"from the remote")
    assert fake_remote.paths() == [f"/files/{FILE}"]


async def test_a_proxy_member_that_cannot_answer_is_passed_over(
    client, root, mirror, fake_remote, db
):
    fake_remote.down = True
    await create(db, "two")
    await create(db, "all", "group", group={"members": ["mirror", "two"]})
    await put(client, root, "two", b"from two")

    found = await client.get(GROUP, headers=root)
    absent = await client.get("/repository/all/elsewhere.bin", headers=root)

    assert found.content == b"from two"
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_a_group_inside_a_group(client, root, everything, db):
    await create(db, "three")
    await create(db, "outer", "group", group={"members": ["three", "all"]})
    await put(client, root, "two", b"deep inside")

    response = await client.get(f"/repository/outer/{FILE}", headers=root)

    assert response.content == b"deep inside"


async def test_permission_on_the_group_is_what_counts(client, root, everything, make_user, db):
    await roles.create_role(db, "group-readers", "", ["repository:raw:all:read"], [])
    await roles.create_role(db, "member-readers", "", ["repository:raw:one:read"], [])
    await db.commit()
    await make_user("gia", roles=["group-readers"])
    await make_user("max", roles=["member-readers"])
    await put(client, root, "one", b"from one")
    gia, max_ = basic("gia", PASSWORD), basic("max", PASSWORD)

    through_group = await client.get(GROUP, headers=gia)
    member_directly = await client.get(f"/repository/one/{FILE}", headers=gia)
    without_group_permission = await client.get(GROUP, headers=max_)

    assert through_group.content == b"from one"
    assert (member_directly.status_code, error_code(member_directly)) == (403, "forbidden")
    assert (without_group_permission.status_code, error_code(without_group_permission)) == (
        403,
        "forbidden",
    )


async def test_an_offline_group_is_unavailable(client, root, everything, db):
    await service.update_repository(
        db, everything, online=False, group={"members": ["one", "two"]}
    )
    await db.commit()

    response = await client.get(GROUP, headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")


async def test_a_cycle_that_slipped_into_the_data_ends_in_not_found(client, root, db):
    first = await create(db, "all", "group")
    second = await create(db, "loop", "group", group={"members": ["all"]})
    await db.execute(
        insert(RepositoryMember).values(group_id=first.id, member_id=second.id, position=0)
    )
    await db.commit()

    response = await client.get(GROUP, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/repositories/test_group.py -q`
Expected: every test that requests `/repository/all/...` or `/repository/outer/...` fails with `503` and code `repository_unavailable`, because no engine serves groups yet.

- [ ] **Step 3: Implement the group engine and register it**

`backend/src/megooarti/repositories/group.py`:

```python
"""Group repositories: several repositories behind one URL.

Members are tried in order and the first that has the path answers. Permission is
decided on the group, by the route, before this runs: members are not checked again.
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.paths import normalise_path

# What a member may answer to mean "not from me; try the next": it lacks the path,
# its remote is unavailable, or it has no engine in this version.
_TRY_NEXT = frozenset({404, 502, 503})
_SEEN = "megooarti.groups_seen"


async def handle_group(context: RepositoryContext, request: Request, path: str, serve) -> Response:
    """Answer a request to a group. `serve` is the dispatcher, used for each member."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A group repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    # Cycles are refused when a group is saved, but two simultaneous saves could create
    # one. Visiting each group once per request makes that harmless.
    seen = request.scope.setdefault(_SEEN, set())
    if context.repository.id not in seen:
        seen.add(context.repository.id)
        for member in await service.members(context.db, context.repository):
            if not member.online:
                continue
            member_context = await build_context(
                context.db, context.settings, member, context.principal
            )
            try:
                return await serve(member_context, request, path)
            except ApiError as error:
                if error.status_code not in _TRY_NEXT:
                    raise
    raise ApiError(404, "not_found", "No such file.")
```

In `backend/src/megooarti/repositories/dispatch.py`, add the import `from megooarti.repositories.group import handle_group`, and replace everything from the `ENGINES` line to the end of the file with:

```python
async def _group(context: RepositoryContext, request: Request, path: str) -> Response:
    return await handle_group(context, request, path, serve)


ENGINES: dict[str, Engine] = {"hosted": _hosted, "proxy": handle_proxy, "group": _group}


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    engine = ENGINES.get(context.repository.type)
    if engine is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return await engine(context, request, path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/repositories/test_group.py tests/repositories/test_dispatch.py -q`
Expected: no failures; `test_group.py` reports 16 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add backend
git commit -m "feat(repositories): serve group repositories from their members in order"
```

---

### Task 9: Cross-site write refusal, container test and documentation

**Files:**
- Modify: `backend/src/megooarti/security/authentication.py`
- Modify: `backend/tests/test_container.py`
- Modify: `README.md`
- Test: `backend/tests/security/test_cross_site.py`

**Interfaces:**
- Consumes: `_principal_dependency` in `authentication.py`; the `administrator` fixture and `call` helper in `test_container.py`; all the routes from this plan.
- Produces: any request that goes through `current_principal` or `client_principal`, uses `POST`, `PUT`, `PATCH` or `DELETE`, and carries `Sec-Fetch-Site: cross-site` is refused with `403` and code `cross_site_request`, before credentials are examined.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_cross_site.py`:

```python
import pytest

from tests.accounts import PASSWORD, basic, error_code

ROLES = "/api/v1/roles"
ROLE = {"name": "readers", "description": "", "permissions": [], "roles": []}


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def test_a_write_from_another_site_is_refused_even_with_valid_credentials(client, root):
    response = await client.post(ROLES, json=ROLE, headers={**root, "Sec-Fetch-Site": "cross-site"})

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
    assert (await client.get(f"{ROLES}/readers", headers=root)).status_code == 404


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
async def test_writes_from_the_same_site_or_typed_by_the_user_are_accepted(client, root, site):
    response = await client.post(ROLES, json=ROLE, headers={**root, "Sec-Fetch-Site": site})

    assert response.status_code == 201


async def test_clients_that_do_not_send_the_header_are_unaffected(client, root):
    assert (await client.post(ROLES, json=ROLE, headers=root)).status_code == 201


async def test_reads_from_another_site_are_not_refused(client, root):
    response = await client.get(ROLES, headers={**root, "Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 200


async def test_uploads_from_another_site_are_refused(client, root, files):
    response = await client.put(
        "/repository/files/a.bin", content=b"x", headers={**root, "Sec-Fetch-Site": "cross-site"}
    )

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
```

`files` is the hosted repository fixture in `backend/tests/repositories/conftest.py`. Move that one fixture to `backend/tests/conftest.py`, so both test directories can use it, and add `from megooarti.repositories import service` and `from megooarti.repositories.models import Repository` to the imports of `backend/tests/conftest.py`. Leave the same imports in `backend/tests/repositories/conftest.py`: the `mirror` fixture still uses them.

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_cross_site.py -q`
Expected: the two refusal tests fail (`201` instead of `403`); the others pass.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/security/authentication.py`, inside `_principal_dependency`, add these lines as the first statements of the inner `dependency` function, before the `try`:

```python
        # Browsers remember HTTP Basic credentials after the challenge on /repository
        # and would attach them to a form posted from any site. Browsers also say where
        # a request came from; package clients never send this header.
        if (
            request.method in _UNSAFE_METHODS
            and request.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            raise ApiError(
                403,
                "cross_site_request",
                "Requests that change something are not accepted from other sites.",
            )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_cross_site.py -q`
Expected: 7 passed.

Run in `backend/`: `uv run pytest -q`
Expected: no failures.

- [ ] **Step 5: Add the container test**

Append to `backend/tests/test_container.py`:

```python
@pytest.mark.docker
def test_a_group_serves_a_file_through_a_proxy_of_a_hosted_repository(administrator):
    status, _, created = call("POST", "/me/tokens", {"name": "proxy-test"}, administrator)
    assert status == 201
    token = {"Authorization": f"Bearer {created['token']}"}
    origin = {"name": "origin", "format": "raw", "type": "hosted"}
    mirror = {
        "name": "origin-mirror",
        "format": "raw",
        "type": "proxy",
        "proxy": {
            # The container talks to itself: the remote is its own hosted repository.
            "remote_url": "http://127.0.0.1:8000/repository/origin",
            "remote_auth": {"type": "bearer", "secret": created["token"]},
        },
    }
    everything = {
        "name": "everything",
        "format": "raw",
        "type": "group",
        "group": {"members": ["origin-mirror"]},
    }
    for repository in (origin, mirror, everything):
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body
    assert body["group"] == {"members": ["origin-mirror"]}

    content = os.urandom(64 * 1024 + 3)
    base = f"http://127.0.0.1:{HTTP_PORT}/repository"
    upload = urllib.request.Request(
        f"{base}/origin/dist/app.bin", data=content, method="PUT", headers=token
    )
    with urllib.request.urlopen(upload, timeout=60) as response:
        assert response.status == 201

    through_group = urllib.request.Request(f"{base}/everything/dist/app.bin", headers=token)
    with urllib.request.urlopen(through_group, timeout=60) as response:
        assert response.read() == content

    # Remove the original. The proxy keeps serving what it cached.
    remove = urllib.request.Request(f"{base}/origin/dist/app.bin", method="DELETE", headers=token)
    with urllib.request.urlopen(remove, timeout=60) as response:
        assert response.status == 204
    with urllib.request.urlopen(through_group, timeout=60) as response:
        assert response.read() == content

    status, _, shown = call("GET", "/repositories/origin-mirror", headers=administrator)
    assert status == 200
    assert shown["proxy"]["remote_auth"] == {"type": "bearer", "username": "", "has_secret": True}
    assert shown["status"]["failures"] == 0
    key = compose("exec", "-T", "backend", "test", "-s", "/var/lib/megooarti/secret.key", check=False)
    assert key.returncode == 0
```

Run in `backend/`: `uv run pytest -m docker -q`
Expected: 8 passed.

- [ ] **Step 6: Document it**

In `README.md`, add this row to the table in the **Configuration** section, after the `MEGOOARTI_BLOB_GRACE_SECONDS` row:

```markdown
| `MEGOOARTI_SECRET_KEY` | generated | Key that seals stored secrets such as remote passwords. If unset, a key is generated into `secret.key` in the data directory on first use |
```

In the **Repositories** section, replace the text from "So far there is one" up to and including "(files you publish)." with:

```markdown
So far there is one format, `raw` (arbitrary files by path). A repository has one of
three types: `hosted` (files you publish), `proxy` (a cache of a remote repository) or
`group` (several repositories behind one URL).
```

and add these subsections at the end of the **Repositories** section, before **Health endpoints**:

````markdown
### Proxy repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "upstream-files", "format": "raw", "type": "proxy",
  "proxy": {
    "remote_url": "https://files.example.org/releases",
    "remote_auth": {"type": "basic", "username": "robot", "secret": "the-password"}
  }
}' http://localhost:8000/api/v1/repositories
```

- A file that is not cached is downloaded from the remote completely, checked, stored
  and then served. Later requests are served from the cache.
- A cached file is checked against the remote again after `content_max_age_minutes`
  (default 1440; `-1` never). If the remote is down, the cached copy is served.
- A path the remote does not have is remembered for `negative_cache.ttl_minutes`
  (default 1440), so the remote is not asked again for it.
- After a connection failure, a `5xx` or a `429`, the remote is left alone for a minute,
  doubling with each consecutive failure up to an hour. Set `"blocked": true` to stop
  contacting it altogether, or `"auto_block": false` to turn automatic blocking off.
  `GET /api/v1/repositories/<name>` shows the current state under `status`.
- `POST /api/v1/repositories/<name>/invalidate-cache` makes the proxy check everything
  with the remote again.
- The remote secret is sealed before it is stored and is never returned; the API shows
  only `has_secret`. Leave `secret` out when updating to keep the stored one. It is sent
  only to the configured remote, and not to another host the remote redirects to.
- A proxy repository cannot be written to.

**Back up the key.** Secrets are sealed with `MEGOOARTI_SECRET_KEY`, or with the
generated `secret.key` in the data directory. Without that key the stored secrets cannot
be read and must be entered again.

### Group repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "all-files", "format": "raw", "type": "group",
  "group": {"members": ["files", "upstream-files"]}
}' http://localhost:8000/api/v1/repositories
```

- Members are tried in order and the first that has the path answers. Offline members,
  and proxies whose remote is unavailable, are passed over.
- Reading through a group needs `read` on the group only, not on its members.
- A group may contain other groups. It cannot be written to, and a repository cannot be
  deleted while a group presents it.
````

Record this plan's decisions in the spec. In `docs/superpowers/specs/2026-10-07-storage-repositories-design.md`, add this subsection at the end of section 9, before section 10:

```markdown
### 9.1 Refinements settled while planning proxy and group repositories

- **Caching for a reader.** The facade has a `cache` operation that records content with no permission or policy check and the creator `proxy`. It refuses to run on anything but a proxy repository. The check that matters, `read` on the proxy or on the group in front of it, has already happened.
- **Sealed secrets by type.** The repository service accepts a remote secret only as a sealed value; the API seals it. A plain string is a programming error, not bad input.
- **A cached file outlives its remote copy.** If the remote answers `404` for a file that is already cached, the cached copy is kept and marked verified.
- **What counts toward blocking.** Transport failures, `5xx` and `429`. Other unexpected statuses, such as `401` and `403`, fail the request with `502` but do not block, so a wrong credential shows up on every request.
- **A group with no answer.** If every member lacks the path, is offline, or cannot reach its remote, the group answers `404`. A member's other errors, such as `416`, are returned as they are.
- **Cross-site writes.** A request that changes state and carries `Sec-Fetch-Site: cross-site` is refused with `403 cross_site_request`. Browsers remember HTTP Basic credentials after the `/repository` challenge; package clients never send that header.
```

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Run in the repository root:

```bash
git add README.md docs backend
git commit -m "feat(security): refuse cross-site writes; test proxy and group in the container; document them"
```
