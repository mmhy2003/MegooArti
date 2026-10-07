# Identity and Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users, roles, permission patterns, UI sessions, personal API tokens, anonymous access, a first-start administrator and the REST API that manages them, so that any route can declare the permission it needs in one line.

**Architecture:** A `megooarti.security` package of plain async service functions that take an `AsyncSession`, thin FastAPI routers on top, and one `authentication` module that turns a request into a `Principal` (session cookie, HTTP Basic, bearer token or anonymous). Roles hold permission patterns directly; UI sessions are server-side rows behind an opaque cookie. Services never commit; routers and the authentication dependency do.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, Alembic, argon2-cffi, pydantic 2, pytest + pytest-asyncio + httpx.

**Spec:** [docs/superpowers/specs/2026-10-07-identity-access-design.md](../specs/2026-10-07-identity-access-design.md). Business requirements: [docs/BRD.md](../../BRD.md) SEC-1..10, SEC-19, SYS-1, API-3, API-5, NFR-6, NFR-9.

## Global Constraints

- Everything in the plan 1 Global Constraints still applies: Alembic only, one migration head, working `downgrade()`, `MEGOOARTI_`-prefixed settings listed in `README.md`, JSON logs, routes under `/api/v1`, the standard error envelope, LF line endings, 100-character lines, ruff clean.
- **Services never commit.** A service takes an `AsyncSession`, changes state, and calls `flush()` at most. Routers commit at the end of a successful change. The authentication code commits before raising when something must outlive the failed request (a failed sign-in count).
- **No ORM relationships.** Link tables (`role_permissions`, `role_members`, `user_roles`) are read with column selects and written with Core `insert()` / `delete()` statements, never as loaded entities.
- **No server-side column defaults on columns the code reads back.** Timestamps and IDs use Python-side defaults, so nothing is lazily refreshed after a flush.
- Timestamps come from `megooarti.clock.utcnow()` and are timezone-aware UTC. Services that depend on time take `now` as an argument.
- Passwords and token values never appear in logs or error messages, except the single `initial_admin_password` line.
- Every sign-in failure returns `401`, code `unauthorized`, message `Invalid credentials.` whatever the cause.
- A test must never start an application whose `app.state.sessionmaker` commits for real to the shared test database. Use the `app` fixture, or set `app.state.sessionmaker = sessionmaker` on an application you build yourself. (Applications pointed at the empty or unreachable databases are fine.)
- Markdown tables use spaced separator rows (`| --- | --- |`).

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker compose` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A username typed in a different case or with surrounding spaces.** Sign-in should succeed; usernames are case-insensitive (Task 9).
2. **A malformed `Authorization` header** (not base64, no colon, unknown scheme). The response should be a `401` in the standard envelope, never a `500` (Task 9).
3. **A session cookie whose session no longer exists** (signed out elsewhere, expired, user disabled). The request should be treated as signed out, and `GET /auth/session` should answer `authenticated: false` (Task 9).
4. **A token whose owner was disabled, or that has expired.** It should stop working at once (Task 9).
5. **The data directory cannot be written at first start.** The application should still start and still log the initial password (Task 13).

---

### Task 1: Request sessions, test isolation and shared API pieces

**Files:**
- Create: `backend/src/megooarti/clock.py`
- Create: `backend/src/megooarti/db/session.py`
- Create: `backend/src/megooarti/pagination.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/megooarti/config.py`
- Modify: `backend/src/megooarti/errors.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `backend/tests/clients.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_config.py`
- Modify: `backend/tests/test_errors.py`
- Test: `backend/tests/test_isolation.py`
- Test: `backend/tests/test_pagination.py`

**Interfaces:**
- Consumes: `create_app`, `Settings`, `ApiError`, `client_for`, fixture `database_url` (plan 1).
- Produces:
  - `megooarti.clock.utcnow() -> datetime` (aware, UTC)
  - `megooarti.db.session.create_sessionmaker(engine) -> async_sessionmaker[AsyncSession]`
  - `megooarti.db.session.get_session` — FastAPI dependency yielding an `AsyncSession` from `request.app.state.sessionmaker`. It does not commit.
  - `app.state.sessionmaker`
  - `Settings.data_dir: Path`, `session_idle_seconds: int`, `session_absolute_seconds: int`, `session_cookie_secure: bool`, `login_max_failures: int`, `login_failure_window_seconds: int`
  - `ApiError(status_code, code, message, details=None, headers=None)`
  - `megooarti.pagination.PageParams` (dependency with `.limit`, `.offset`), `Page[T]` (response model), `page(items, total, params) -> dict` (the response body; declare `response_model=Page[...]` on the route)
  - Test fixtures: `db_connection`, `sessionmaker`, `db` (an `AsyncSession`), and `app` now bound to the test transaction. `settings.data_dir` is a temporary directory.
  - `client_for` now uses base URL `https://test`, so `Secure` cookies are sent back.
  - **Test rule:** after arranging data with the `db` fixture, call `await db.commit()` before calling the application. Never call `db.rollback()` after the application has written.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_isolation.py`:

```python
import pytest
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.system.models import SystemSetting


async def count_settings(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(SystemSetting))


@pytest.mark.parametrize("round_number", [1, 2])
async def test_rows_written_in_one_test_are_gone_in_the_next(db, round_number):
    assert await count_settings(db) == 0

    db.add(SystemSetting(key="probe", value={"round": round_number}))
    await db.commit()

    assert await count_settings(db) == 1


async def test_the_application_sees_rows_the_test_committed(app, client, db):
    @app.get("/_test/probe")
    async def probe(session: AsyncSession = Depends(get_session)) -> dict:
        row = await session.get(SystemSetting, "probe")
        return {"value": None if row is None else row.value}

    db.add(SystemSetting(key="probe", value={"seen": True}))
    await db.commit()

    response = await client.get("/_test/probe")

    assert response.json() == {"value": {"seen": True}}
```

`backend/tests/test_pagination.py`:

```python
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from megooarti.pagination import Page, PageParams, page

NUMBERS = list(range(1, 301))


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/numbers", response_model=Page[int])
    async def numbers(params: PageParams = Depends()) -> dict:
        chosen = NUMBERS[params.offset : params.offset + params.limit]
        return page(chosen, len(NUMBERS), params)

    return app


async def get_numbers(query: str = ""):
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="https://test") as client:
        return await client.get(f"/numbers{query}")


async def test_default_page_is_the_first_fifty():
    body = (await get_numbers()).json()
    assert body["items"] == NUMBERS[:50]
    assert (body["total"], body["limit"], body["offset"]) == (300, 50, 0)


async def test_limit_and_offset_select_a_window():
    body = (await get_numbers("?limit=3&offset=10")).json()
    assert body == {"items": [11, 12, 13], "total": 300, "limit": 3, "offset": 10}


@pytest.mark.parametrize("query", ["?limit=0", "?limit=201", "?offset=-1"])
async def test_out_of_range_values_are_rejected(query):
    assert (await get_numbers(query)).status_code == 422
```

Append to `backend/tests/test_config.py`:

```python


def test_identity_defaults():
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert str(settings.data_dir).replace("\\", "/") == "/var/lib/megooarti"
    assert settings.session_idle_seconds == 3600
    assert settings.session_absolute_seconds == 43200
    assert settings.session_cookie_secure is True
    assert settings.login_max_failures == 5
    assert settings.login_failure_window_seconds == 900


def test_identity_settings_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("MEGOOARTI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEGOOARTI_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("MEGOOARTI_LOGIN_MAX_FAILURES", "9")
    settings = Settings(_env_file=None)
    assert settings.data_dir == tmp_path
    assert settings.session_cookie_secure is False
    assert settings.login_max_failures == 9
```

In `backend/tests/test_errors.py`, add this route inside the `app` fixture, after the `conflict` route:

```python
    @router.get("/throttled")
    async def throttled() -> None:
        raise ApiError(429, "too_many_attempts", "Slow down.", headers={"Retry-After": "7"})
```

and append this test to the same file:

```python


async def test_api_error_can_carry_response_headers(client):
    response = await client.get("/_test/throttled")
    assert_error(response, 429, "too_many_attempts")
    assert response.headers["Retry-After"] == "7"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_isolation.py tests/test_pagination.py tests/test_config.py tests/test_errors.py -q`
Expected: collection errors for `megooarti.db.session` and `megooarti.pagination`; `test_identity_defaults` and `test_identity_settings_come_from_the_environment` fail with `AttributeError`; `test_api_error_can_carry_response_headers` fails with `TypeError: ... unexpected keyword argument 'headers'`.

- [ ] **Step 3: Add the settings, the clock and the session dependency**

FastAPI declares dependencies as `Depends(...)` in argument defaults, which ruff's B008 rule rejects. In `backend/pyproject.toml`, add this line to the `[tool.ruff.lint]` table, below `select`:

```toml
ignore = ["B008"]  # FastAPI's Depends(...) in argument defaults is intended
```

In `backend/src/megooarti/config.py`, add `from pathlib import Path` to the imports and add these fields to `Settings`, after `db_wait_timeout_seconds`:

```python
    data_dir: Path = Path("/var/lib/megooarti")
    session_idle_seconds: int = 3600
    session_absolute_seconds: int = 43200
    session_cookie_secure: bool = True
    login_max_failures: int = 5
    login_failure_window_seconds: int = 900
```

`backend/src/megooarti/clock.py`:

```python
"""The one place the application reads the current time."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
```

`backend/src/megooarti/db/session.py`:

```python
"""Database sessions for request handlers."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False keeps loaded objects usable after a commit, which async code
    # needs because it cannot lazily reload them.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session for one request. It does not commit: the code that changes data does.

    Anything not committed is rolled back when the session closes.
    """
    async with request.app.state.sessionmaker() as session:
        yield session
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.db.session import create_sessionmaker` and add this line directly after `app.state.engine = ...`:

```python
    app.state.sessionmaker = create_sessionmaker(app.state.engine)
```

- [ ] **Step 4: Let `ApiError` carry headers**

In `backend/src/megooarti/errors.py`, replace the `ApiError` class with:

```python
class ApiError(Exception):
    """Raise from a handler to return an error response in the standard shape."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers
```

and replace the body of `handle_api_error` with:

```python
        return error_response(
            request, error.status_code, error.code, error.message, error.details, error.headers
        )
```

- [ ] **Step 5: Add pagination**

`backend/src/megooarti/pagination.py`:

```python
"""The paging convention every list endpoint uses."""

from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel


class PageParams:
    """Use as `params: PageParams = Depends()`."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def page(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    """The body of a list response. Declare `response_model=Page[...]` on the route."""
    return {"items": items, "total": total, "limit": params.limit, "offset": params.offset}
```

- [ ] **Step 6: Run each test inside a transaction that is rolled back**

In `backend/tests/clients.py`, change the base URL so that `Secure` cookies are returned to the application:

```python
        async with AsyncClient(transport=transport, base_url="https://test") as client:
```

Replace `backend/tests/conftest.py` with:

```python
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from megooarti.config import Settings, get_settings
from megooarti.db.schema import alembic_config
from megooarti.main import create_app
from tests.clients import client_for
from tests.databases import ensure_database, reset_schema

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"
)


def _configured_test_database_url() -> str:
    raw = os.environ.get("MEGOOARTI_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    return Settings(_env_file=None, database_url=raw).database_url


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def database_url() -> str:
    """A database migrated to head, shared by the whole test session."""
    url = _configured_test_database_url()
    ensure_database(url)
    reset_schema(url)
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def _migration_database_url() -> str:
    base = make_url(_configured_test_database_url())
    url = base.set(database=f"{base.database}_migrations")
    rendered = url.render_as_string(hide_password=False)
    ensure_database(rendered)
    return rendered


@pytest.fixture
def empty_database(_migration_database_url: str) -> str:
    """A separate database with no tables, for tests that run migrations themselves."""
    reset_schema(_migration_database_url)
    return _migration_database_url


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(_env_file=None, database_url=database_url, data_dir=tmp_path / "data")


@pytest.fixture
async def db_connection(database_url: str) -> AsyncIterator[AsyncConnection]:
    """One connection whose transaction is rolled back when the test ends."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                yield connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def sessionmaker(db_connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Sessions on the test connection. Their commits are savepoints, undone with the test."""
    return async_sessionmaker(
        bind=db_connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def db(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """A session for arranging and checking data. Commit before calling the application."""
    async with sessionmaker() as session:
        yield session


@pytest.fixture
def app(settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]) -> FastAPI:
    app = create_app(settings)
    app.state.sessionmaker = sessionmaker
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app) as http:
        yield http
```

- [ ] **Step 7: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_isolation.py tests/test_pagination.py tests/test_config.py tests/test_errors.py -q`
Expected: no failures; `test_isolation.py` reports 3 passed and `test_pagination.py` 5 passed.

- [ ] **Step 8: Lint, run the suite and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Expected: no ruff errors; no test failures.

Run in the repository root:

```bash
git add backend
git commit -m "feat(backend): add request sessions, test isolation, pagination and error headers"
```

---

### Task 2: Permission patterns

**Files:**
- Create: `backend/src/megooarti/security/__init__.py` (empty)
- Create: `backend/src/megooarti/security/permissions.py`
- Test: `backend/tests/security/__init__.py` (empty)
- Test: `backend/tests/security/test_permissions.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `megooarti.security.permissions`:
  - `is_valid_pattern(pattern: str) -> bool` — segments may be `*`
  - `is_valid_permission(permission: str) -> bool` — no `*`
  - `grants(pattern: str, permission: str) -> bool`
  - `any_grants(patterns: Iterable[str], permission: str) -> bool`
  - `FULL_ACCESS = "*"`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/security/__init__.py` as an empty file.

`backend/tests/security/test_permissions.py`:

```python
import pytest

from megooarti.security.permissions import (
    FULL_ACCESS,
    any_grants,
    grants,
    is_valid_pattern,
    is_valid_permission,
)


@pytest.mark.parametrize(
    ("pattern", "permission", "expected"),
    [
        ("*", "admin:users:write", True),
        ("admin:users:*", "admin:users:write", True),
        ("admin:users:read", "admin:users:write", False),
        ("admin:users:write", "admin:users:write", True),
        ("repository:*:*:read", "repository:maven:releases:read", True),
        ("repository:*:*:read", "repository:maven:releases:delete", False),
        ("repository:maven", "repository:maven:releases:delete", True),
        ("repository:maven", "repository:npm:internal:read", False),
        ("admin", "admin:settings:write", True),
        ("repository:maven:releases:read:extra", "repository:maven:releases:read", False),
        ("admin:Users:read", "admin:users:read", False),
        ("*:users:read", "admin:users:read", True),
    ],
)
def test_grants(pattern, permission, expected):
    assert grants(pattern, permission) is expected


def test_any_grants_is_true_when_one_pattern_matches():
    assert any_grants(["admin:roles:read", "admin:users:*"], "admin:users:write")


def test_any_grants_is_false_for_no_patterns():
    assert not any_grants([], "admin:users:read")


def test_full_access_is_the_single_wildcard():
    assert FULL_ACCESS == "*"
    assert grants(FULL_ACCESS, "anything:at:all")


@pytest.mark.parametrize("pattern", ["*", "admin:users:*", "repository:maven:my.repo-1_x:read"])
def test_valid_patterns(pattern):
    assert is_valid_pattern(pattern)


@pytest.mark.parametrize("pattern", ["", "admin::read", "admin:us ers", "admin:users:", "a:b*", "é"])
def test_invalid_patterns(pattern):
    assert not is_valid_pattern(pattern)


def test_a_permission_may_not_contain_a_wildcard():
    assert is_valid_permission("admin:users:read")
    assert not is_valid_permission("admin:*:read")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_permissions.py -q`
Expected: collection error, `No module named 'megooarti.security'`.

- [ ] **Step 3: Implement**

Create `backend/src/megooarti/security/__init__.py` as an empty file.

`backend/src/megooarti/security/permissions.py`:

```python
"""Permission patterns.

A route requires a permission such as `admin:users:write`. A role grants patterns such
as `admin:users:*`. A pattern grants a permission when each of its segments is `*` or
equals the permission's segment at the same position; a pattern shorter than the
permission grants everything beneath it, and a longer one grants nothing.
"""

import re
from collections.abc import Iterable

FULL_ACCESS = "*"
_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")


def is_valid_pattern(pattern: str) -> bool:
    return all(part == "*" or _SEGMENT.fullmatch(part) for part in pattern.split(":"))


def is_valid_permission(permission: str) -> bool:
    return all(_SEGMENT.fullmatch(part) for part in permission.split(":"))


def grants(pattern: str, permission: str) -> bool:
    granted = pattern.split(":")
    required = permission.split(":")
    if len(granted) > len(required):
        return False
    return all(have in ("*", need) for have, need in zip(granted, required, strict=False))


def any_grants(patterns: Iterable[str], permission: str) -> bool:
    return any(grants(pattern, permission) for pattern in patterns)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_permissions.py -q`
Expected: 25 passed.

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
git commit -m "feat(security): add permission pattern matching"
```

---

### Task 3: Security tables and built-in rows

**Files:**
- Create: `backend/src/megooarti/security/models.py`
- Create: `backend/src/megooarti/migrations/versions/0002_add_security_tables.py`
- Modify: `backend/src/megooarti/models.py`
- Test: `backend/tests/security/test_models.py`

**Interfaces:**
- Consumes: `Base` (plan 1), `utcnow` (Task 1).
- Produces, in `megooarti.security.models`:
  - `User(id, username, display_name, email, password_hash, status, must_change_password, builtin, created_at, updated_at, last_login_at)` — table `users`
  - `Role(id, name, description, builtin)` — table `roles`
  - `RolePermission(role_id, pattern)`, `RoleMember(role_id, member_role_id)`, `UserRole(user_id, role_id)` — link tables; use only through Core statements and column selects
  - `UserSession(id, token_hash, csrf_token, user_id, created_at, last_seen_at, expires_at, ip, user_agent)` — table `sessions`
  - `ApiToken(id, user_id, name, token_hash, display_prefix, scopes, expires_at, created_at, last_used_at)` — table `api_tokens`
  - `LoginFailure(subject, window_started_at, count)` — table `login_failures`
  - Rows present after migration: roles `admin` (pattern `*`) and `anonymous` (patterns `repository:*:*:browse`, `repository:*:*:read`); users `admin` and `anonymous`, both `builtin`, neither with a password.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_models.py`:

```python
from sqlalchemy import select

from megooarti.security.models import Role, RolePermission, User, UserRole


async def test_built_in_roles_exist_with_their_patterns(db):
    rows = await db.execute(
        select(Role.name, RolePermission.pattern)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .where(Role.builtin.is_(True))
        .order_by(Role.name, RolePermission.pattern)
    )
    assert [tuple(row) for row in rows] == [
        ("admin", "*"),
        ("anonymous", "repository:*:*:browse"),
        ("anonymous", "repository:*:*:read"),
    ]


async def test_built_in_users_exist_without_passwords(db):
    rows = await db.execute(
        select(User.username, Role.name, User.password_hash, User.must_change_password)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.builtin.is_(True))
        .order_by(User.username)
    )
    assert [tuple(row) for row in rows] == [
        ("admin", "admin", None, True),
        ("anonymous", "anonymous", None, False),
    ]


async def test_a_new_user_gets_an_id_and_timestamps_without_a_reload(db):
    user = User(username="dana", display_name="Dana")
    db.add(user)
    await db.flush()

    assert user.id is not None
    assert user.status == "active"
    assert user.created_at is not None
    assert user.created_at.tzinfo is not None
    assert user.updated_at == user.created_at or user.updated_at > user.created_at
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_models.py -q`
Expected: collection error, `No module named 'megooarti.security.models'`.

- [ ] **Step 3: Write the models**

`backend/src/megooarti/security/models.py`:

```python
"""Tables for users, roles, sessions, API tokens and failed sign-ins.

There are no ORM relationships. Services query the link tables explicitly, so every
database round trip is visible in async code and nothing is loaded lazily.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(254))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")
    must_change_password: Mapped[bool] = mapped_column(default=False)
    builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    builtin: Mapped[bool] = mapped_column(default=False)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    pattern: Mapped[str] = mapped_column(String(255), primary_key=True)


class RoleMember(Base):
    """`role_id` contains `member_role_id`."""

    __tablename__ = "role_members"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    member_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str] = mapped_column(String(45))
    user_agent: Mapped[str] = mapped_column(String(255))


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    display_prefix: Mapped[str] = mapped_column(String(8))
    scopes: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginFailure(Base):
    __tablename__ = "login_failures"

    subject: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column()
```

In `backend/src/megooarti/models.py`, add below the existing import:

```python
from megooarti.security import models as _security_models  # noqa: F401
```

- [ ] **Step 4: Write the migration**

`backend/src/megooarti/migrations/versions/0002_add_security_tables.py`:

```python
"""add security tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("name", name=op.f("uq_roles_name")),
    )
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "pattern", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "role_members",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("member_role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_members_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_role_id"],
            ["roles.id"],
            name=op.f("fk_role_members_member_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "member_role_id", name=op.f("pk_role_members")),
    )
    user_roles = op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_user_roles_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("display_prefix", sa.String(length=8), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_api_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_api_tokens_user_id")),
    )
    op.create_table(
        "login_failures",
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("subject", name=op.f("pk_login_failures")),
    )

    now = datetime.now(UTC)
    admin_role, anonymous_role, admin_user, anonymous_user = (uuid.uuid4() for _ in range(4))
    op.bulk_insert(
        roles,
        [
            {
                "id": admin_role,
                "name": "admin",
                "description": "Full access to everything.",
                "builtin": True,
            },
            {
                "id": anonymous_role,
                "name": "anonymous",
                "description": "What requests without credentials may do.",
                "builtin": True,
            },
        ],
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_id": admin_role, "pattern": "*"},
            {"role_id": anonymous_role, "pattern": "repository:*:*:browse"},
            {"role_id": anonymous_role, "pattern": "repository:*:*:read"},
        ],
    )
    op.bulk_insert(
        users,
        [
            {
                "id": admin_user,
                "username": "admin",
                "display_name": "Administrator",
                "email": None,
                "password_hash": None,
                "status": "active",
                "must_change_password": True,
                "builtin": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            },
            {
                "id": anonymous_user,
                "username": "anonymous",
                "display_name": "Anonymous",
                "email": None,
                "password_hash": None,
                "status": "active",
                "must_change_password": False,
                "builtin": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            },
        ],
    )
    op.bulk_insert(
        user_roles,
        [
            {"user_id": admin_user, "role_id": admin_role},
            {"user_id": anonymous_user, "role_id": anonymous_role},
        ],
    )


def downgrade() -> None:
    op.drop_table("login_failures")
    op.drop_table("api_tokens")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_table("role_members")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("users")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_models.py tests/test_migrations.py tests/test_db_script.py -q`
Expected: no failures. `test_models_and_migrations_describe_the_same_schema` passing proves the hand-written migration matches the models; if it fails, its message lists the differences to correct in the migration.

`tests/test_db_script.py::test_next_revision_number_for_the_real_history` now expects `0003`, which it computes itself.

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
git commit -m "feat(security): add users, roles, sessions and token tables with built-in rows"
```

---

### Task 4: Passwords and secrets

**Files:**
- Create: `backend/src/megooarti/security/passwords.py`
- Create: `backend/src/megooarti/security/keys.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/security/test_passwords.py`
- Test: `backend/tests/security/test_keys.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `megooarti.security.passwords`: `hash_password(password) -> str`, `verify_password(password_hash: str | None, password: str) -> bool` (always does one hash computation, even for `None`), `needs_rehash(password_hash) -> bool`, `password_problem(password, username) -> str | None`, `MIN_LENGTH = 8`, `MAX_LENGTH = 256`. These are CPU-bound; call the first two through `asyncio.to_thread`.
  - `megooarti.security.keys`: `TOKEN_PREFIX = "mga_"`, `new_secret() -> str` (43 URL-safe characters), `new_api_token() -> str` (47 characters, starts with `mga_`), `hash_secret(value) -> str` (64 hex characters).
  - An autouse test fixture that makes password hashing cheap.

- [ ] **Step 1: Install the dependency**

Run in `backend/`: `uv add argon2-cffi`

- [ ] **Step 2: Write the failing tests**

`backend/tests/security/test_passwords.py`:

```python
import pytest
from argon2 import PasswordHasher

from megooarti.security import passwords
from megooarti.security.passwords import (
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)


def test_a_hash_verifies_its_own_password_only():
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "correct horse batterx")


def test_two_hashes_of_one_password_differ():
    assert hash_password("same password") != hash_password("same password")


def test_a_missing_hash_never_verifies():
    assert not verify_password(None, "anything")


def test_a_corrupt_hash_never_verifies():
    assert not verify_password("not-a-hash", "anything")


def test_non_ascii_passwords_work():
    hashed = hash_password("pässwörd-ünïcode-✓")
    assert verify_password(hashed, "pässwörd-ünïcode-✓")


def test_a_hash_made_with_other_parameters_needs_a_rehash(monkeypatch):
    old = hash_password("correct horse battery")
    assert not needs_rehash(old)

    stronger = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    monkeypatch.setattr(passwords, "_hasher", stronger)

    assert needs_rehash(old)
    assert verify_password(old, "correct horse battery")


@pytest.mark.parametrize(
    ("password", "username", "fragment"),
    [
        ("short", "dana", "at least 8"),
        ("x" * 257, "dana", "at most 256"),
        ("DanaSmith", "danasmith", "username"),
    ],
)
def test_password_rules(password, username, fragment):
    assert fragment in password_problem(password, username)


def test_an_acceptable_password_has_no_problem():
    assert password_problem("correct horse battery", "dana") is None
```

`backend/tests/security/test_keys.py`:

```python
import re

from megooarti.security.keys import TOKEN_PREFIX, hash_secret, new_api_token, new_secret


def test_secrets_are_long_random_and_url_safe():
    first, second = new_secret(), new_secret()
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)


def test_api_tokens_carry_the_prefix():
    token = new_api_token()
    assert token.startswith(TOKEN_PREFIX)
    assert len(token) == 47


def test_hash_is_stable_hex_and_differs_by_input():
    assert hash_secret("abc") == hash_secret("abc")
    assert hash_secret("abc") != hash_secret("abd")
    assert re.fullmatch(r"[0-9a-f]{64}", hash_secret("abc"))
```

Add to `backend/tests/conftest.py`, with the imports `from argon2 import PasswordHasher` and `from megooarti.security import passwords` at the top:

```python
@pytest.fixture(autouse=True)
def _cheap_password_hashing(monkeypatch):
    """Argon2 at production cost would add seconds to the suite."""
    cheap = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(passwords, "_hasher", cheap)
    monkeypatch.setattr(passwords, "_dummy_hash", None)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_passwords.py tests/security/test_keys.py -q`
Expected: collection error in `conftest.py`, `cannot import name 'passwords' from 'megooarti.security'`.

- [ ] **Step 4: Implement**

`backend/src/megooarti/security/passwords.py`:

```python
"""Password hashing (Argon2id) and password rules.

hash_password and verify_password are CPU-bound: call them with asyncio.to_thread.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 8
MAX_LENGTH = 256

_hasher = PasswordHasher()
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Check a password. A missing hash costs the same time as a wrong password,
    so response time does not reveal whether an account exists."""
    global _dummy_hash
    if password_hash is None:
        if _dummy_hash is None:
            _dummy_hash = _hasher.hash("megooarti-no-such-account")
        candidate = _dummy_hash
    else:
        candidate = password_hash
    try:
        matched = _hasher.verify(candidate, password)
    except (VerificationError, InvalidHashError):
        return False
    return matched and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problem(password: str, username: str) -> str | None:
    """Why this password is not acceptable, or None if it is."""
    if len(password) < MIN_LENGTH:
        return f"The password must be at least {MIN_LENGTH} characters long."
    if len(password) > MAX_LENGTH:
        return f"The password must be at most {MAX_LENGTH} characters long."
    if password.lower() == username.lower():
        return "The password must not be the same as the username."
    return None
```

`backend/src/megooarti/security/keys.py`:

```python
"""Random secrets for sessions and API tokens, and the hash they are stored as.

These secrets carry 256 bits of randomness, so a fast hash is the right choice;
slow hashing is for passwords, which people choose.
"""

import hashlib
import secrets

TOKEN_PREFIX = "mga_"


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def new_api_token() -> str:
    return TOKEN_PREFIX + new_secret()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_passwords.py tests/security/test_keys.py -q`
Expected: 13 passed.

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
git commit -m "feat(security): add Argon2id password hashing and secret generation"
```

---

### Task 5: Roles and the keep-an-administrator check

**Files:**
- Create: `backend/src/megooarti/security/roles.py`
- Create: `backend/src/megooarti/security/guards.py`
- Test: `backend/tests/security/test_roles.py`
- Test: `backend/tests/security/test_guards.py`

**Interfaces:**
- Consumes: models (Task 3), `ApiError` (Task 1).
- Produces, in `megooarti.security.roles`:
  - `RoleView(name, description, builtin, permissions: list[str], roles: list[str])` (frozen dataclass)
  - `get_role(db, name) -> Role | None`
  - `roles_named(db, names) -> list[Role]` — raises `ApiError(422, "validation_error")` for an unknown name
  - `reachable_role_ids(db, role_ids) -> set[UUID]`
  - `effective_patterns(db, role_ids) -> frozenset[str]`
  - `describe(db, role) -> RoleView`
  - `list_roles(db, limit, offset) -> tuple[list[RoleView], int]`
  - `create_role(db, name, description, permissions, member_names) -> Role` — `409 conflict` on a duplicate name
  - `update_role(db, role, description, permissions, member_names) -> None` — `409 builtin_protected` for the `admin` role, `409 role_cycle`
  - `delete_role(db, role) -> None` — `409 builtin_protected` for built-in roles
- Produces, in `megooarti.security.guards`:
  - `ensure_administrator_remains(db) -> None` — raises `ApiError(409, "last_administrator")` unless an active user with a password holds `*` through its roles. Routers call it after any change to users or roles, before committing.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_roles.py`:

```python
import pytest

from megooarti.errors import ApiError
from megooarti.security import roles


async def code_of(awaitable) -> str:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value.code


async def test_create_and_describe(db):
    role = await roles.create_role(
        db, "developers", "People who publish", ["repository:*:*:read", "admin:users:read"], []
    )

    view = await roles.describe(db, role)

    assert view == roles.RoleView(
        name="developers",
        description="People who publish",
        builtin=False,
        permissions=["admin:users:read", "repository:*:*:read"],
        roles=[],
    )


async def test_a_duplicate_name_is_a_conflict(db):
    await roles.create_role(db, "developers", "", [], [])
    assert await code_of(roles.create_role(db, "developers", "", [], [])) == "conflict"


async def test_an_unknown_member_role_is_a_validation_error(db):
    assert await code_of(roles.create_role(db, "team", "", [], ["ghost"])) == "validation_error"


async def test_effective_patterns_follow_contained_roles(db):
    readers = await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    writers = await roles.create_role(db, "writers", "", ["repository:*:*:add"], ["readers"])
    leads = await roles.create_role(db, "leads", "", ["admin:users:read"], ["writers"])

    assert await roles.effective_patterns(db, [readers.id]) == {"repository:*:*:read"}
    assert await roles.effective_patterns(db, [leads.id]) == {
        "admin:users:read",
        "repository:*:*:add",
        "repository:*:*:read",
    }
    assert await roles.effective_patterns(db, []) == frozenset()
    assert (await roles.describe(db, writers)).roles == ["readers"]


async def test_a_role_cannot_contain_itself(db):
    role = await roles.create_role(db, "loop", "", [], [])
    assert await code_of(roles.update_role(db, role, "", [], ["loop"])) == "role_cycle"


async def test_an_indirect_cycle_is_rejected(db):
    inner = await roles.create_role(db, "inner", "", [], [])
    await roles.create_role(db, "middle", "", [], ["inner"])
    await roles.create_role(db, "outer", "", [], ["middle"])

    assert await code_of(roles.update_role(db, inner, "", [], ["outer"])) == "role_cycle"


async def test_update_replaces_description_patterns_and_members(db):
    await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    await roles.create_role(db, "auditors", "", ["admin:users:read"], [])
    role = await roles.create_role(db, "team", "old", ["admin:roles:read", "a:b"], ["readers"])

    await roles.update_role(db, role, "new", ["a:b", "c:d"], ["auditors"])

    view = await roles.describe(db, role)
    assert (view.description, view.permissions, view.roles) == ("new", ["a:b", "c:d"], ["auditors"])


async def test_the_admin_role_cannot_be_changed(db):
    admin = await roles.get_role(db, "admin")
    assert await code_of(roles.update_role(db, admin, "", [], [])) == "builtin_protected"


async def test_the_anonymous_role_can_be_changed_but_not_deleted(db):
    anonymous = await roles.get_role(db, "anonymous")

    await roles.update_role(db, anonymous, "Nothing", [], [])

    assert (await roles.describe(db, anonymous)).permissions == []
    assert await code_of(roles.delete_role(db, anonymous)) == "builtin_protected"


async def test_deleting_a_role_removes_it_from_roles_that_contained_it(db):
    readers = await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    team = await roles.create_role(db, "team", "", [], ["readers"])

    await roles.delete_role(db, readers)

    assert await roles.get_role(db, "readers") is None
    assert (await roles.describe(db, team)).roles == []


async def test_list_is_paged_in_name_order(db):
    for name in ("zeta", "beta"):
        await roles.create_role(db, name, "", [], [])

    first, total = await roles.list_roles(db, limit=3, offset=0)
    rest, _ = await roles.list_roles(db, limit=3, offset=3)

    assert total == 4
    assert [view.name for view in first] == ["admin", "anonymous", "beta"]
    assert [view.name for view in rest] == ["zeta"]
```

`backend/tests/security/test_guards.py`:

```python
import pytest
from sqlalchemy import insert

from megooarti.errors import ApiError
from megooarti.security import roles
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import User, UserRole


async def add_user(db, username: str, role_name: str, **fields) -> User:
    user = User(username=username, display_name=username, password_hash="hash", **fields)
    db.add(user)
    await db.flush()
    role = await roles.get_role(db, role_name)
    await db.execute(insert(UserRole).values(user_id=user.id, role_id=role.id))
    return user


async def refused(db) -> bool:
    try:
        await ensure_administrator_remains(db)
    except ApiError as error:
        assert error.code == "last_administrator"
        assert error.status_code == 409
        return True
    return False


async def test_refused_when_no_administrator_has_a_password(db):
    # Straight after migration the built-in admin has no password yet.
    assert await refused(db)


async def test_passes_with_an_active_administrator_who_has_a_password(db):
    await add_user(db, "root", "admin")
    assert not await refused(db)


async def test_a_disabled_administrator_does_not_count(db):
    await add_user(db, "root", "admin", status="disabled")
    assert await refused(db)


async def test_full_access_through_a_contained_role_counts(db):
    await roles.create_role(db, "operators", "", [], ["admin"])
    await add_user(db, "olga", "operators")
    assert not await refused(db)


@pytest.mark.parametrize("patterns", [["admin"], ["admin:*"], ["*:*"]])
async def test_only_the_single_wildcard_counts_as_full_access(db, patterns):
    await roles.create_role(db, "nearly", "", patterns, [])
    await add_user(db, "nora", "nearly")
    assert await refused(db)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_roles.py tests/security/test_guards.py -q`
Expected: collection errors, `cannot import name 'roles'` and `No module named 'megooarti.security.guards'`.

- [ ] **Step 3: Implement roles**

`backend/src/megooarti/security/roles.py`:

```python
"""Roles: named sets of permission patterns, which may contain other roles."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.models import Role, RoleMember, RolePermission


@dataclass(frozen=True)
class RoleView:
    name: str
    description: str
    builtin: bool
    permissions: list[str]
    roles: list[str]


async def get_role(db: AsyncSession, name: str) -> Role | None:
    return await db.scalar(select(Role).where(Role.name == name))


async def roles_named(db: AsyncSession, names: Iterable[str]) -> list[Role]:
    """The roles with these names. An unknown name is a validation error."""
    wanted = sorted(set(names))
    if not wanted:
        return []
    found = list(await db.scalars(select(Role).where(Role.name.in_(wanted))))
    missing = sorted(set(wanted) - {role.name for role in found})
    if missing:
        details = [{"field": "roles", "message": f"Unknown role: {name}"} for name in missing]
        raise ApiError(422, "validation_error", "The request is not valid.", details)
    return found


async def reachable_role_ids(db: AsyncSession, role_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The given roles plus every role they contain, directly or indirectly."""
    start = list(role_ids)
    if not start:
        return set()
    reachable = select(Role.id).where(Role.id.in_(start)).cte("reachable", recursive=True)
    # UNION (not UNION ALL) removes duplicates, which also stops at a cycle.
    reachable = reachable.union(
        select(RoleMember.member_role_id).join(reachable, RoleMember.role_id == reachable.c.id)
    )
    return set(await db.scalars(select(reachable.c.id)))


async def effective_patterns(db: AsyncSession, role_ids: Iterable[uuid.UUID]) -> frozenset[str]:
    ids = await reachable_role_ids(db, role_ids)
    if not ids:
        return frozenset()
    patterns = await db.scalars(
        select(RolePermission.pattern).where(RolePermission.role_id.in_(ids))
    )
    return frozenset(patterns)


async def describe(db: AsyncSession, role: Role) -> RoleView:
    permissions = await db.scalars(
        select(RolePermission.pattern)
        .where(RolePermission.role_id == role.id)
        .order_by(RolePermission.pattern)
    )
    members = await db.scalars(
        select(Role.name)
        .join(RoleMember, RoleMember.member_role_id == Role.id)
        .where(RoleMember.role_id == role.id)
        .order_by(Role.name)
    )
    return RoleView(role.name, role.description, role.builtin, list(permissions), list(members))


async def list_roles(db: AsyncSession, limit: int, offset: int) -> tuple[list[RoleView], int]:
    total = await db.scalar(select(func.count()).select_from(Role))
    page = list(await db.scalars(select(Role).order_by(Role.name).limit(limit).offset(offset)))
    return [await describe(db, role) for role in page], total or 0


async def _replace_content(
    db: AsyncSession, role: Role, permissions: Iterable[str], member_names: Iterable[str]
) -> None:
    members = await roles_named(db, member_names)
    member_ids = {member.id for member in members}
    if role.id in await reachable_role_ids(db, member_ids):
        raise ApiError(
            409, "role_cycle", "A role cannot contain itself, directly or indirectly."
        )
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    await db.execute(delete(RoleMember).where(RoleMember.role_id == role.id))
    patterns = sorted(set(permissions))
    if patterns:
        await db.execute(
            insert(RolePermission),
            [{"role_id": role.id, "pattern": pattern} for pattern in patterns],
        )
    if member_ids:
        await db.execute(
            insert(RoleMember),
            [{"role_id": role.id, "member_role_id": member_id} for member_id in member_ids],
        )


async def create_role(
    db: AsyncSession,
    name: str,
    description: str,
    permissions: Iterable[str],
    member_names: Iterable[str],
) -> Role:
    if await get_role(db, name) is not None:
        raise ApiError(409, "conflict", f"A role named {name} already exists.")
    role = Role(name=name, description=description, builtin=False)
    db.add(role)
    await db.flush()
    await _replace_content(db, role, permissions, member_names)
    return role


async def update_role(
    db: AsyncSession,
    role: Role,
    description: str,
    permissions: Iterable[str],
    member_names: Iterable[str],
) -> None:
    if role.builtin and role.name == "admin":
        raise ApiError(409, "builtin_protected", "The admin role cannot be changed.")
    role.description = description
    await db.flush()
    await _replace_content(db, role, permissions, member_names)


async def delete_role(db: AsyncSession, role: Role) -> None:
    if role.builtin:
        raise ApiError(409, "builtin_protected", "Built-in roles cannot be deleted.")
    await db.delete(role)
    await db.flush()
```

- [ ] **Step 4: Implement the guard**

`backend/src/megooarti/security/guards.py`:

```python
"""Checks that protect the installation from locking itself out."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.models import RoleMember, RolePermission, User, UserRole
from megooarti.security.permissions import FULL_ACCESS


async def ensure_administrator_remains(db: AsyncSession) -> None:
    """Refuse the pending change if nobody who can sign in would have full access.

    Call after changing users or roles and before committing.
    """
    # Roles that grant full access: those holding "*" and every role that contains one.
    granting = (
        select(RolePermission.role_id.label("id"))
        .where(RolePermission.pattern == FULL_ACCESS)
        .cte("granting", recursive=True)
    )
    granting = granting.union(
        select(RoleMember.role_id).join(granting, RoleMember.member_role_id == granting.c.id)
    )
    administrator = await db.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.status == "active",
            User.password_hash.is_not(None),
            UserRole.role_id.in_(select(granting.c.id)),
        )
        .limit(1)
    )
    if administrator is None:
        raise ApiError(
            409,
            "last_administrator",
            "This change would leave no active user with full access.",
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_roles.py tests/security/test_guards.py -q`
Expected: 18 passed.

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
git commit -m "feat(security): add roles with nesting and the keep-an-administrator check"
```

---

### Task 6: Sessions, API tokens and failed-sign-in counters

**Files:**
- Create: `backend/src/megooarti/security/sessions.py`
- Create: `backend/src/megooarti/security/tokens.py`
- Create: `backend/src/megooarti/security/throttle.py`
- Create: `backend/tests/security/conftest.py`
- Test: `backend/tests/security/test_sessions.py`
- Test: `backend/tests/security/test_tokens.py`
- Test: `backend/tests/security/test_throttle.py`

**Interfaces:**
- Consumes: models (Task 3), `keys` (Task 4), `ApiError`.
- Produces, in `megooarti.security.sessions`:
  - `create_session(db, user_id, *, ip, user_agent, now, lifetime_seconds) -> tuple[UserSession, str]` — the string is the cookie value; also deletes expired sessions
  - `find_session(db, value, *, now, idle_seconds) -> UserSession | None`
  - `touch(record, now) -> None` — moves `last_seen_at` at most once a minute
  - `delete_session(db, record) -> None`
  - `delete_user_sessions(db, user_id, keep_session_id=None) -> None`
- Produces, in `megooarti.security.tokens`:
  - `create_token(db, user_id, *, name, expires_at, scopes) -> tuple[ApiToken, str]` — `409 conflict` on a duplicate name for that user
  - `find_token(db, value, now) -> ApiToken | None` — `None` if unknown, expired, or not starting with `mga_`
  - `touch(token, now) -> None`
  - `list_tokens(db, user_id, limit, offset) -> tuple[list[ApiToken], int]`
  - `revoke_token(db, user_id, token_id) -> None` — `404 not_found` if that user has no such token
- Produces, in `megooarti.security.throttle`:
  - `subjects(username: str | None, ip: str) -> list[str]`
  - `Standing(blocked_for: int, has_failures: bool)`
  - `standing(db, subjects, *, now, max_failures, window_seconds) -> Standing`
  - `record_failure(db, subjects, *, now, window_seconds) -> None`
  - `clear(db, subjects) -> None`
- Test fixture `dana` (in `tests/security/conftest.py`): a flushed `User` with no password.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/conftest.py`:

```python
from datetime import UTC, datetime

import pytest

from megooarti.security.models import User

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def dana(db) -> User:
    user = User(username="dana", display_name="Dana")
    db.add(user)
    await db.flush()
    return user
```

`backend/tests/security/test_sessions.py`:

```python
from datetime import timedelta

from sqlalchemy import func, select

from megooarti.security import sessions
from megooarti.security.models import UserSession
from tests.security.conftest import NOW

HOUR = 3600


async def start(db, user, now=NOW, lifetime_seconds=12 * HOUR):
    return await sessions.create_session(
        db, user.id, ip="10.0.0.1", user_agent="pytest", now=now, lifetime_seconds=lifetime_seconds
    )


async def count(db) -> int:
    return await db.scalar(select(func.count()).select_from(UserSession))


async def test_a_session_is_found_by_its_value_but_stores_only_a_hash(db, dana):
    record, value = await start(db, dana)

    found = await sessions.find_session(db, value, now=NOW, idle_seconds=HOUR)

    assert found.id == record.id
    assert record.token_hash != value
    assert value not in (record.token_hash, record.csrf_token)
    assert len(record.csrf_token) == 43
    assert await sessions.find_session(db, "wrong", now=NOW, idle_seconds=HOUR) is None


async def test_a_session_ends_after_the_idle_limit(db, dana):
    _, value = await start(db, dana)

    just_inside = NOW + timedelta(seconds=HOUR)
    just_outside = NOW + timedelta(seconds=HOUR + 1)

    assert await sessions.find_session(db, value, now=just_inside, idle_seconds=HOUR)
    assert await sessions.find_session(db, value, now=just_outside, idle_seconds=HOUR) is None


async def test_a_session_ends_at_the_absolute_limit_even_if_active(db, dana):
    record, value = await start(db, dana, lifetime_seconds=2 * HOUR)
    record.last_seen_at = NOW + timedelta(seconds=2 * HOUR - 1)
    await db.flush()

    at_limit = NOW + timedelta(seconds=2 * HOUR)

    assert await sessions.find_session(db, value, now=at_limit, idle_seconds=HOUR) is None


async def test_touch_moves_last_seen_at_most_once_a_minute(db, dana):
    record, _ = await start(db, dana)

    sessions.touch(record, NOW + timedelta(seconds=59))
    assert record.last_seen_at == NOW

    sessions.touch(record, NOW + timedelta(seconds=60))
    assert record.last_seen_at == NOW + timedelta(seconds=60)


async def test_creating_a_session_removes_expired_ones(db, dana):
    await start(db, dana, lifetime_seconds=HOUR)
    assert await count(db) == 1

    await start(db, dana, now=NOW + timedelta(seconds=HOUR + 1))

    assert await count(db) == 1


async def test_delete_user_sessions_can_keep_one(db, dana):
    keep, _ = await start(db, dana)
    await start(db, dana)

    await sessions.delete_user_sessions(db, dana.id, keep_session_id=keep.id)
    assert await db.scalar(select(UserSession.id)) == keep.id

    await sessions.delete_user_sessions(db, dana.id)
    assert await count(db) == 0
```

`backend/tests/security/test_tokens.py`:

```python
import uuid
from datetime import timedelta

import pytest

from megooarti.errors import ApiError
from megooarti.security import tokens
from megooarti.security.models import User
from tests.security.conftest import NOW


async def make(db, user, name="ci", **fields):
    fields.setdefault("expires_at", None)
    fields.setdefault("scopes", None)
    return await tokens.create_token(db, user.id, name=name, **fields)


async def test_a_token_is_found_by_its_value_but_stores_only_a_hash(db, dana):
    token, value = await make(db, dana)

    assert value.startswith("mga_")
    assert token.display_prefix == value[:8]
    assert token.token_hash != value
    assert token.created_at is not None
    assert (await tokens.find_token(db, value, NOW)).id == token.id
    assert await tokens.find_token(db, "mga_" + "x" * 43, NOW) is None
    assert await tokens.find_token(db, "no-prefix", NOW) is None


async def test_an_expired_token_is_not_found(db, dana):
    _, value = await make(db, dana, expires_at=NOW + timedelta(days=1))

    assert await tokens.find_token(db, value, NOW)
    assert await tokens.find_token(db, value, NOW + timedelta(days=1)) is None


async def test_scopes_are_stored_as_given(db, dana):
    scoped, _ = await make(db, dana, name="scoped", scopes=["repository:*:*:read"])
    unscoped, _ = await make(db, dana, name="unscoped")

    assert scoped.scopes == ["repository:*:*:read"]
    assert unscoped.scopes is None


async def test_token_names_are_unique_per_user_only(db, dana):
    other = User(username="eli", display_name="Eli")
    db.add(other)
    await db.flush()
    await make(db, dana, name="ci")

    await make(db, other, name="ci")
    with pytest.raises(ApiError) as caught:
        await make(db, dana, name="ci")

    assert caught.value.code == "conflict"


async def test_list_is_newest_first_and_paged(db, dana):
    for name in ("one", "two", "three"):
        token, _ = await make(db, dana, name=name)
        token.created_at = NOW + timedelta(minutes=len(name))
    await db.flush()

    first, total = await tokens.list_tokens(db, dana.id, limit=2, offset=0)

    assert total == 3
    assert [token.name for token in first] == ["three", "one"]


async def test_revoke_removes_the_token(db, dana):
    token, value = await make(db, dana)

    await tokens.revoke_token(db, dana.id, token.id)

    assert await tokens.find_token(db, value, NOW) is None


@pytest.mark.parametrize("wrong", ["owner", "token"])
async def test_revoking_a_token_the_user_does_not_have_is_not_found(db, dana, wrong):
    token, _ = await make(db, dana)
    owner_id = uuid.uuid4() if wrong == "owner" else dana.id
    token_id = uuid.uuid4() if wrong == "token" else token.id

    with pytest.raises(ApiError) as caught:
        await tokens.revoke_token(db, owner_id, token_id)

    assert (caught.value.status_code, caught.value.code) == (404, "not_found")


async def test_touch_moves_last_used_at_most_once_a_minute(db, dana):
    token, _ = await make(db, dana)

    tokens.touch(token, NOW)
    tokens.touch(token, NOW + timedelta(seconds=59))
    assert token.last_used_at == NOW

    tokens.touch(token, NOW + timedelta(seconds=60))
    assert token.last_used_at == NOW + timedelta(seconds=60)
```

`backend/tests/security/test_throttle.py`:

```python
from datetime import timedelta

from megooarti.security import throttle
from tests.security.conftest import NOW

LIMITS = {"max_failures": 3, "window_seconds": 900}
BOTH = ["user:dana", "ip:10.0.0.1"]


async def fail(db, subjects, times, now=NOW):
    for _ in range(times):
        await throttle.record_failure(db, subjects, now=now, window_seconds=900)


def test_subjects():
    assert throttle.subjects("dana", "10.0.0.1") == BOTH
    assert throttle.subjects(None, "10.0.0.1") == ["ip:10.0.0.1"]
    assert throttle.subjects("x" * 200, "10.0.0.1")[0] == "user:" + "x" * 64


async def test_nothing_recorded_means_not_blocked(db):
    assert await throttle.standing(db, BOTH, now=NOW, **LIMITS) == throttle.Standing(0, False)


async def test_blocked_once_the_limit_is_reached_until_the_window_ends(db):
    await fail(db, BOTH, 2)
    assert (await throttle.standing(db, BOTH, now=NOW, **LIMITS)).blocked_for == 0

    await fail(db, BOTH, 1, now=NOW + timedelta(seconds=100))
    later = NOW + timedelta(seconds=300)

    assert await throttle.standing(db, BOTH, now=later, **LIMITS) == throttle.Standing(600, True)
    at_end = NOW + timedelta(seconds=900)
    assert (await throttle.standing(db, BOTH, now=at_end, **LIMITS)).blocked_for == 0


async def test_one_blocked_subject_is_enough(db):
    await fail(db, ["ip:10.0.0.1"], 3)

    assert (await throttle.standing(db, BOTH, now=NOW, **LIMITS)).blocked_for == 900
    assert (await throttle.standing(db, ["user:dana"], now=NOW, **LIMITS)).blocked_for == 0


async def test_a_failure_after_the_window_starts_a_new_count(db):
    await fail(db, BOTH, 3)
    after = NOW + timedelta(seconds=901)

    await fail(db, BOTH, 1, now=after)

    assert await throttle.standing(db, BOTH, now=after, **LIMITS) == throttle.Standing(0, True)


async def test_clear_forgets_the_given_subjects_only(db):
    await fail(db, BOTH, 3)

    await throttle.clear(db, ["user:dana"])

    assert (await throttle.standing(db, ["user:dana"], now=NOW, **LIMITS)).has_failures is False
    assert (await throttle.standing(db, ["ip:10.0.0.1"], now=NOW, **LIMITS)).blocked_for == 900


async def test_recording_a_failure_discards_other_expired_windows(db):
    await fail(db, ["ip:10.9.9.9"], 1)
    after = NOW + timedelta(seconds=901)

    await fail(db, ["user:dana"], 1, now=after)

    assert not (await throttle.standing(db, ["ip:10.9.9.9"], now=after, **LIMITS)).has_failures
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_sessions.py tests/security/test_tokens.py tests/security/test_throttle.py -q`
Expected: three collection errors, `cannot import name 'sessions'`, `'tokens'` and `'throttle'` from `megooarti.security`.

- [ ] **Step 3: Implement sessions**

`backend/src/megooarti/security/sessions.py`:

```python
"""Server-side sessions for the web UI."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.security.keys import hash_secret, new_secret
from megooarti.security.models import UserSession

_TOUCH_INTERVAL = timedelta(seconds=60)


async def create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    ip: str,
    user_agent: str | None,
    now: datetime,
    lifetime_seconds: int,
) -> tuple[UserSession, str]:
    """Start a session. Returns the record and the cookie value, which is not stored."""
    await db.execute(delete(UserSession).where(UserSession.expires_at <= now))
    value = new_secret()
    record = UserSession(
        token_hash=hash_secret(value),
        csrf_token=new_secret(),
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=lifetime_seconds),
        ip=ip[:45],
        user_agent=(user_agent or "")[:255],
    )
    db.add(record)
    await db.flush()
    return record, value


async def find_session(
    db: AsyncSession, value: str, *, now: datetime, idle_seconds: int
) -> UserSession | None:
    record = await db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_secret(value))
    )
    if record is None or record.expires_at <= now:
        return None
    if record.last_seen_at + timedelta(seconds=idle_seconds) < now:
        return None
    return record


def touch(record: UserSession, now: datetime) -> None:
    """Note activity, writing at most once a minute per session."""
    if now - record.last_seen_at >= _TOUCH_INTERVAL:
        record.last_seen_at = now


async def delete_session(db: AsyncSession, record: UserSession) -> None:
    await db.delete(record)
    await db.flush()


async def delete_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, keep_session_id: uuid.UUID | None = None
) -> None:
    statement = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_session_id is not None:
        statement = statement.where(UserSession.id != keep_session_id)
    await db.execute(statement)
```

- [ ] **Step 4: Implement API tokens**

`backend/src/megooarti/security/tokens.py`:

```python
"""Personal API tokens."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.keys import TOKEN_PREFIX, hash_secret, new_api_token
from megooarti.security.models import ApiToken

_TOUCH_INTERVAL = timedelta(seconds=60)


async def create_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    expires_at: datetime | None,
    scopes: list[str] | None,
) -> tuple[ApiToken, str]:
    """Create a token. Returns the record and the secret value, which is not stored."""
    duplicate = await db.scalar(
        select(ApiToken.id).where(ApiToken.user_id == user_id, ApiToken.name == name)
    )
    if duplicate is not None:
        raise ApiError(409, "conflict", f"A token named {name} already exists.")
    value = new_api_token()
    token = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=hash_secret(value),
        display_prefix=value[:8],
        scopes=scopes,
        expires_at=expires_at,
    )
    db.add(token)
    await db.flush()
    return token, value


async def find_token(db: AsyncSession, value: str, now: datetime) -> ApiToken | None:
    if not value.startswith(TOKEN_PREFIX):
        return None
    token = await db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_secret(value)))
    if token is None:
        return None
    if token.expires_at is not None and token.expires_at <= now:
        return None
    return token


def touch(token: ApiToken, now: datetime) -> None:
    """Note use, writing at most once a minute per token."""
    if token.last_used_at is None or now - token.last_used_at >= _TOUCH_INTERVAL:
        token.last_used_at = now


async def list_tokens(
    db: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[ApiToken], int]:
    owned = ApiToken.user_id == user_id
    total = await db.scalar(select(func.count()).select_from(ApiToken).where(owned))
    rows = await db.scalars(
        select(ApiToken)
        .where(owned)
        .order_by(ApiToken.created_at.desc(), ApiToken.name)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    token = await db.scalar(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
    )
    if token is None:
        raise ApiError(404, "not_found", "No such token.")
    await db.delete(token)
    await db.flush()
```

- [ ] **Step 5: Implement the failed-sign-in counters**

`backend/src/megooarti/security/throttle.py`:

```python
"""Counters of failed sign-ins, kept in the database so every container shares them.

A subject is `user:<username>` or `ip:<address>`. Each subject has one fixed window that
starts at its first failure.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.security.models import LoginFailure


@dataclass(frozen=True)
class Standing:
    blocked_for: int  # seconds until another attempt is allowed; 0 when not blocked
    has_failures: bool


def subjects(username: str | None, ip: str) -> list[str]:
    found = [f"ip:{ip}"]
    if username:
        found.insert(0, f"user:{username[:64]}")
    return found


async def standing(
    db: AsyncSession,
    subjects: list[str],
    *,
    now: datetime,
    max_failures: int,
    window_seconds: int,
) -> Standing:
    window = timedelta(seconds=window_seconds)
    rows = (
        await db.execute(
            select(LoginFailure.window_started_at, LoginFailure.count).where(
                LoginFailure.subject.in_(subjects)
            )
        )
    ).all()
    waits = [
        (started + window - now).total_seconds()
        for started, count in rows
        if count >= max_failures and started + window > now
    ]
    return Standing(blocked_for=math.ceil(max(waits)) if waits else 0, has_failures=bool(rows))


async def record_failure(
    db: AsyncSession, subjects: list[str], *, now: datetime, window_seconds: int
) -> None:
    # Expired windows are deleted first, so a row that is then incremented is always
    # inside its window and a plain increment is correct.
    cutoff = now - timedelta(seconds=window_seconds)
    await db.execute(delete(LoginFailure).where(LoginFailure.window_started_at <= cutoff))
    for subject in subjects:
        statement = insert(LoginFailure).values(subject=subject, window_started_at=now, count=1)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[LoginFailure.subject],
                set_={"count": LoginFailure.count + 1},
            )
        )


async def clear(db: AsyncSession, subjects: list[str]) -> None:
    await db.execute(delete(LoginFailure).where(LoginFailure.subject.in_(subjects)))

```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_sessions.py tests/security/test_tokens.py tests/security/test_throttle.py -q`
Expected: 22 passed.

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
git commit -m "feat(security): add UI sessions, API tokens and failed sign-in counters"
```

---

### Task 7: Users

**Files:**
- Create: `backend/src/megooarti/security/users.py`
- Create: `backend/tests/accounts.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/security/test_users.py`

**Interfaces:**
- Consumes: models, `passwords` (Task 4), `roles` (Task 5), `sessions.delete_user_sessions` (Task 6).
- Produces, in `megooarti.security.users`:
  - `UserView(id, username, display_name, email, status, must_change_password, builtin, roles: list[str], created_at, last_login_at)` (frozen dataclass)
  - `normalise_username(username) -> str` — stripped and lower-cased
  - `get_user(db, user_id) -> User | None`, `get_user_by_username(db, username) -> User | None`
  - `user_patterns(db, user) -> frozenset[str]`
  - `describe(db, user) -> UserView`, `list_users(db, limit, offset) -> tuple[list[UserView], int]`
  - `create_user(db, *, username, display_name, email, password, role_names, must_change_password) -> User` — `409 conflict`, `422 validation_error`
  - `update_user(db, user, changes: dict) -> None` — keys `display_name`, `email`, `status`, `roles`; disabling deletes the user's sessions
  - `set_roles(db, user, role_names) -> None`
  - `set_password(db, user, password, *, must_change_password, keep_session_id=None) -> None` — deletes the user's other sessions; `409 builtin_protected` for `anonymous`
  - `delete_user(db, user) -> None` — `409 builtin_protected`
- Produces for tests: `tests.accounts.PASSWORD`; fixture `make_user(username, *, roles=(), password=PASSWORD, must_change_password=False) -> User`, which commits.

- [ ] **Step 1: Write the failing tests**

`backend/tests/accounts.py`:

```python
"""Helpers for tests that need people who can sign in."""

PASSWORD = "correct horse battery"
```

Add to `backend/tests/conftest.py`, with the imports `from collections.abc import Sequence`, `from megooarti.security import users`, `from megooarti.security.models import User` and `from tests.accounts import PASSWORD`:

```python
@pytest.fixture
def make_user(sessionmaker: async_sessionmaker[AsyncSession]):
    """Create and commit a user who can sign in with tests.accounts.PASSWORD."""

    async def make(
        username: str,
        *,
        roles: Sequence[str] = (),
        password: str = PASSWORD,
        must_change_password: bool = False,
    ) -> User:
        async with sessionmaker() as session:
            user = await users.create_user(
                session,
                username=username,
                display_name=username.title(),
                email=None,
                password=password,
                role_names=list(roles),
                must_change_password=must_change_password,
            )
            await session.commit()
            return user

    return make
```

`backend/tests/security/test_users.py`:

```python
import pytest
from sqlalchemy import func, select

from megooarti.errors import ApiError
from megooarti.security import roles, sessions, tokens, users
from megooarti.security.models import ApiToken, UserSession
from megooarti.security.passwords import verify_password
from tests.accounts import PASSWORD
from tests.security.conftest import NOW


async def create(db, username="Dana", **fields):
    fields.setdefault("display_name", "Dana Smith")
    fields.setdefault("email", None)
    fields.setdefault("password", PASSWORD)
    fields.setdefault("role_names", [])
    fields.setdefault("must_change_password", False)
    return await users.create_user(db, username=username, **fields)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def session_count(db, user) -> int:
    return await db.scalar(
        select(func.count()).select_from(UserSession).where(UserSession.user_id == user.id)
    )


async def start_session(db, user):
    record, _ = await sessions.create_session(
        db, user.id, ip="10.0.0.1", user_agent="pytest", now=NOW, lifetime_seconds=3600
    )
    return record


async def test_create_stores_a_lower_case_username_and_a_password_hash(db):
    user = await create(db, "  Dana ", email="dana@example.org", role_names=["anonymous"])

    assert user.username == "dana"
    assert user.password_hash != PASSWORD
    assert verify_password(user.password_hash, PASSWORD)
    view = await users.describe(db, user)
    assert (view.username, view.email, view.status, view.roles) == (
        "dana",
        "dana@example.org",
        "active",
        ["anonymous"],
    )
    assert (view.builtin, view.must_change_password, view.last_login_at) == (False, False, None)


async def test_usernames_are_unique_whatever_the_case(db):
    await create(db, "dana")
    assert (await error_of(create(db, "DANA"))).code == "conflict"


async def test_lookup_by_username_ignores_case_and_spaces(db):
    user = await create(db, "dana")
    assert (await users.get_user_by_username(db, " DaNa ")).id == user.id
    assert await users.get_user_by_username(db, "nobody") is None


@pytest.mark.parametrize("password", ["short", "dana"])
async def test_an_unacceptable_password_is_a_validation_error(db, password):
    error = await error_of(create(db, "dana", password=password))
    assert (error.status_code, error.code) == (422, "validation_error")
    assert error.details[0]["field"] == "password"


async def test_an_unknown_role_is_a_validation_error(db):
    assert (await error_of(create(db, role_names=["ghost"]))).code == "validation_error"


async def test_patterns_come_from_the_users_roles(db):
    await roles.create_role(db, "readers", "", ["repository:*:*:read"], [])
    await roles.create_role(db, "team", "", ["admin:users:read"], ["readers"])
    user = await create(db, role_names=["team"])

    assert await users.user_patterns(db, user) == {"admin:users:read", "repository:*:*:read"}


async def test_update_changes_only_the_given_fields(db):
    user = await create(db, email="dana@example.org", role_names=["anonymous"])

    await users.update_user(db, user, {"display_name": "D. Smith", "email": None})

    view = await users.describe(db, user)
    assert (view.display_name, view.email, view.roles) == ("D. Smith", None, ["anonymous"])


async def test_update_can_replace_roles(db):
    await roles.create_role(db, "readers", "", [], [])
    user = await create(db, role_names=["anonymous"])

    await users.update_user(db, user, {"roles": ["readers"]})

    assert (await users.describe(db, user)).roles == ["readers"]


async def test_disabling_a_user_ends_their_sessions(db):
    user = await create(db)
    await start_session(db, user)

    await users.update_user(db, user, {"status": "disabled"})

    assert user.status == "disabled"
    assert await session_count(db, user) == 0


async def test_set_password_replaces_the_hash_and_ends_other_sessions(db):
    user = await create(db, must_change_password=True)
    keep = await start_session(db, user)
    await start_session(db, user)

    await users.set_password(
        db, user, "another good password", must_change_password=False, keep_session_id=keep.id
    )

    assert verify_password(user.password_hash, "another good password")
    assert user.must_change_password is False
    assert await db.scalar(select(UserSession.id).where(UserSession.user_id == user.id)) == keep.id


async def test_set_password_applies_the_password_rules(db):
    user = await create(db)
    error = await error_of(users.set_password(db, user, "short", must_change_password=False))
    assert error.code == "validation_error"


async def test_the_anonymous_user_cannot_have_a_password(db):
    anonymous = await users.get_user_by_username(db, "anonymous")
    error = await error_of(users.set_password(db, anonymous, PASSWORD, must_change_password=False))
    assert error.code == "builtin_protected"


async def test_built_in_users_cannot_be_deleted(db):
    admin = await users.get_user_by_username(db, "admin")
    assert (await error_of(users.delete_user(db, admin))).code == "builtin_protected"


async def test_deleting_a_user_removes_their_sessions_and_tokens(db):
    user = await create(db)
    await start_session(db, user)
    await tokens.create_token(db, user.id, name="ci", expires_at=None, scopes=None)

    await users.delete_user(db, user)

    assert await users.get_user_by_username(db, "dana") is None
    assert await db.scalar(select(func.count()).select_from(UserSession)) == 0
    assert await db.scalar(select(func.count()).select_from(ApiToken)) == 0


async def test_list_is_paged_in_username_order(db):
    for name in ("zoe", "bob"):
        await create(db, name)

    first, total = await users.list_users(db, limit=3, offset=0)

    assert total == 4
    assert [view.username for view in first] == ["admin", "anonymous", "bob"]


async def test_make_user_fixture_creates_someone_who_can_sign_in(make_user, db):
    created = await make_user("dana", roles=["admin"])

    user = await users.get_user(db, created.id)

    assert verify_password(user.password_hash, PASSWORD)
    assert (await users.describe(db, user)).roles == ["admin"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_users.py -q`
Expected: collection error in `conftest.py`, `cannot import name 'users' from 'megooarti.security'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/security/users.py`:

```python
"""Users: creation, changes, passwords and their effective permissions."""

import asyncio
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.models import Role, User, UserRole
from megooarti.security.passwords import hash_password, password_problem
from megooarti.security.roles import effective_patterns, roles_named
from megooarti.security.sessions import delete_user_sessions


@dataclass(frozen=True)
class UserView:
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    status: str
    must_change_password: bool
    builtin: bool
    roles: list[str]
    created_at: datetime
    last_login_at: datetime | None


def normalise_username(username: str) -> str:
    return username.strip().lower()


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == normalise_username(username)))


async def user_patterns(db: AsyncSession, user: User) -> frozenset[str]:
    role_ids = await db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id))
    return await effective_patterns(db, list(role_ids))


async def describe(db: AsyncSession, user: User) -> UserView:
    names = await db.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
        .order_by(Role.name)
    )
    return UserView(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        status=user.status,
        must_change_password=user.must_change_password,
        builtin=user.builtin,
        roles=list(names),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def list_users(db: AsyncSession, limit: int, offset: int) -> tuple[list[UserView], int]:
    total = await db.scalar(select(func.count()).select_from(User))
    page = list(
        await db.scalars(select(User).order_by(User.username).limit(limit).offset(offset))
    )
    return [await describe(db, user) for user in page], total or 0


def _check_password(password: str, username: str) -> None:
    problem = password_problem(password, username)
    if problem:
        details = [{"field": "password", "message": problem}]
        raise ApiError(422, "validation_error", "The request is not valid.", details)


async def set_roles(db: AsyncSession, user: User, role_names: Iterable[str]) -> None:
    chosen = await roles_named(db, role_names)
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    if chosen:
        await db.execute(
            insert(UserRole), [{"user_id": user.id, "role_id": role.id} for role in chosen]
        )


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    display_name: str,
    email: str | None,
    password: str,
    role_names: Iterable[str],
    must_change_password: bool,
) -> User:
    username = normalise_username(username)
    if await get_user_by_username(db, username) is not None:
        raise ApiError(409, "conflict", f"A user named {username} already exists.")
    _check_password(password, username)
    user = User(
        username=username,
        display_name=display_name,
        email=email,
        password_hash=await asyncio.to_thread(hash_password, password),
        status="active",
        must_change_password=must_change_password,
        builtin=False,
    )
    db.add(user)
    await db.flush()
    await set_roles(db, user, role_names)
    return user


async def update_user(db: AsyncSession, user: User, changes: dict[str, Any]) -> None:
    """Apply any of display_name, email, status and roles."""
    for field in ("display_name", "email", "status"):
        if field in changes:
            setattr(user, field, changes[field])
    await db.flush()
    if "roles" in changes:
        await set_roles(db, user, changes["roles"])
    if user.status != "active":
        await delete_user_sessions(db, user.id)


async def set_password(
    db: AsyncSession,
    user: User,
    password: str,
    *,
    must_change_password: bool,
    keep_session_id: uuid.UUID | None = None,
) -> None:
    if user.builtin and user.username == "anonymous":
        raise ApiError(409, "builtin_protected", "The anonymous user cannot have a password.")
    _check_password(password, user.username)
    user.password_hash = await asyncio.to_thread(hash_password, password)
    user.must_change_password = must_change_password
    await db.flush()
    await delete_user_sessions(db, user.id, keep_session_id)


async def delete_user(db: AsyncSession, user: User) -> None:
    if user.builtin:
        raise ApiError(409, "builtin_protected", "Built-in users cannot be deleted.")
    await db.delete(user)
    await db.flush()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_users.py -q`
Expected: 17 passed.

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
git commit -m "feat(security): add user management service"
```

---

### Task 8: Settings store

**Files:**
- Create: `backend/src/megooarti/system/settings_store.py`
- Test: `backend/tests/test_settings_store.py`

**Interfaces:**
- Consumes: `SystemSetting` (plan 1).
- Produces, in `megooarti.system.settings_store`:
  - `DEFAULTS: dict[str, Any]` — `{"base_url": None, "anonymous_access": {"enabled": False}}`
  - `get_setting(db, key) -> Any` — the stored value, or the default; `KeyError` for an unknown key
  - `set_setting(db, key, value) -> None` — `None` removes the stored value, restoring the default

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_settings_store.py`:

```python
import pytest

from megooarti.system.settings_store import DEFAULTS, get_setting, set_setting


async def test_defaults_apply_when_nothing_is_stored(db):
    assert await get_setting(db, "base_url") is None
    assert await get_setting(db, "anonymous_access") == {"enabled": False}
    assert set(DEFAULTS) == {"base_url", "anonymous_access"}


async def test_a_stored_value_replaces_the_default(db):
    await set_setting(db, "base_url", "https://repo.example.org")
    await set_setting(db, "anonymous_access", {"enabled": True})

    assert await get_setting(db, "base_url") == "https://repo.example.org"
    assert await get_setting(db, "anonymous_access") == {"enabled": True}


async def test_a_value_can_be_overwritten(db):
    await set_setting(db, "base_url", "https://one.example.org")
    await set_setting(db, "base_url", "https://two.example.org")

    assert await get_setting(db, "base_url") == "https://two.example.org"


async def test_none_restores_the_default(db):
    await set_setting(db, "base_url", "https://repo.example.org")
    await set_setting(db, "base_url", None)
    await set_setting(db, "base_url", None)

    assert await get_setting(db, "base_url") is None


async def test_unknown_keys_are_a_programming_error(db):
    with pytest.raises(KeyError):
        await get_setting(db, "no_such_setting")
    with pytest.raises(KeyError):
        await set_setting(db, "no_such_setting", 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_settings_store.py -q`
Expected: collection error, `No module named 'megooarti.system.settings_store'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/system/settings_store.py`:

```python
"""Instance settings that administrators change at runtime."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.system.models import SystemSetting

DEFAULTS: dict[str, Any] = {
    "base_url": None,
    "anonymous_access": {"enabled": False},
}


async def get_setting(db: AsyncSession, key: str) -> Any:
    default = DEFAULTS[key]
    row = await db.get(SystemSetting, key)
    return default if row is None else row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Store a value. None removes the stored value, so the default applies again."""
    if key not in DEFAULTS:  # a programming error, not bad input
        raise KeyError(key)
    row = await db.get(SystemSetting, key)
    if value is None:
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    await db.flush()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_settings_store.py -q`
Expected: 5 passed.

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
git commit -m "feat(system): add settings store"
```

---

### Task 9: Authentication and the sign-in API

**Files:**
- Create: `backend/src/megooarti/security/authentication.py`
- Create: `backend/src/megooarti/security/api/__init__.py` (empty)
- Create: `backend/src/megooarti/security/api/auth.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `backend/tests/accounts.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/security/test_auth_api.py`
- Test: `backend/tests/security/test_authentication.py`

**Interfaces:**
- Consumes: `users`, `sessions`, `tokens`, `throttle`, `passwords`, `keys.TOKEN_PREFIX`, `permissions.any_grants`, `settings_store.get_setting`, `get_session`, `utcnow`, `ApiError`.
- Produces, in `megooarti.security.authentication`:
  - `Principal(user: User, method: "session" | "password" | "token" | "anonymous", patterns: frozenset[str], scopes: frozenset[str] | None, session: UserSession | None)` with `.is_anonymous`, `.is_interactive`, `.allows(permission) -> bool`
  - `SESSION_COOKIE = "megooarti_session"`, `CSRF_HEADER = "X-CSRF-Token"`
  - `unauthorized(message=...) -> ApiError`, `client_ip(request) -> str`
  - `build_principal(db, user, method, *, token=None, session=None) -> Principal`
  - `authenticate_password(db, request, username, password) -> User` — raises `401` or `429`
  - `resolve_principal(request, db) -> Principal | None`
  - Dependencies: `current_principal` (→ `Principal | None`, enforces CSRF), `require(permission)` (→ `Principal`), `require_interactive(*, allow_pending_password_change=False)` (→ `Principal`)
- Produces routes under `/api/v1/auth`: `POST /login`, `POST /logout`, `GET /session`; response model `SessionInfo` and function `session_info(principal)` in `megooarti.security.api.auth`.
- Produces for tests: `tests.accounts.sign_in(client, username, password=PASSWORD) -> dict` (also stores the CSRF token on the client), `basic(username, secret)`, `bearer(token)`, `error_code(response)`; fixtures `make_token(user, name="ci", *, scopes=None, expires_at=None) -> str`, `admin_client` (signed in as `root`, role `admin`), `other_client` (no cookies, same application).

- [ ] **Step 1: Write the test helpers**

Replace `backend/tests/accounts.py` with:

```python
"""Helpers for tests that need people who can sign in."""

import base64

from httpx import AsyncClient, Response

PASSWORD = "correct horse battery"


async def sign_in(client: AsyncClient, username: str, password: str = PASSWORD) -> dict:
    """Sign in through the API. The client keeps the cookie and sends the CSRF token."""
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    client.headers["X-CSRF-Token"] = body["csrf_token"]
    return body


def basic(username: str, secret: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def error_code(response: Response) -> str:
    return response.json()["error"]["code"]
```

Add to `backend/tests/conftest.py`, with the imports `from datetime import datetime`, `from httpx import ASGITransport`, `from megooarti.security import tokens` and `from tests.accounts import sign_in`:

```python
@pytest.fixture
def make_token(sessionmaker: async_sessionmaker[AsyncSession]):
    """Create and commit an API token; returns its secret value."""

    async def make(
        user: User,
        name: str = "ci",
        *,
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        async with sessionmaker() as session:
            _, value = await tokens.create_token(
                session, user.id, name=name, expires_at=expires_at, scopes=scopes
            )
            await session.commit()
            return value

    return make


@pytest.fixture
async def admin_client(client: AsyncClient, make_user) -> AsyncClient:
    """The client, signed in as `root`, who has the admin role."""
    await make_user("root", roles=["admin"])
    await sign_in(client, "root")
    return client


@pytest.fixture
async def other_client(app: FastAPI, client: AsyncClient) -> AsyncIterator[AsyncClient]:
    """A second client with no cookies, talking to the same running application."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as http:
        yield http
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/security/test_auth_api.py`:

```python
import pytest
from sqlalchemy import delete

from megooarti.main import create_app
from megooarti.security import users
from megooarti.security.models import UserSession
from tests.accounts import PASSWORD, error_code, sign_in
from tests.clients import client_for

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
SESSION = "/api/v1/auth/session"
SIGNED_OUT = {
    "authenticated": False,
    "method": None,
    "user": None,
    "permissions": [],
    "must_change_password": False,
    "csrf_token": None,
}


async def attempt(client, username, password):
    return await client.post(LOGIN, json={"username": username, "password": password})


async def test_sign_in_describes_the_session_and_sets_a_protected_cookie(client, make_user):
    await make_user("dana", roles=["admin"])

    response = await attempt(client, "dana", PASSWORD)

    assert response.status_code == 200
    body = response.json()
    assert (body["authenticated"], body["method"]) == (True, "session")
    assert (body["user"]["username"], body["user"]["display_name"]) == ("dana", "Dana")
    assert body["permissions"] == ["*"]
    assert body["must_change_password"] is False
    assert len(body["csrf_token"]) == 43
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("megooarti_session=")
    for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert attribute in cookie
    assert PASSWORD not in response.text


async def test_cookie_is_not_marked_secure_for_plain_http(settings, sessionmaker, make_user):
    await make_user("dana")
    app = create_app(settings.model_copy(update={"session_cookie_secure": False}))
    app.state.sessionmaker = sessionmaker

    async with client_for(app) as http:
        response = await attempt(http, "dana", PASSWORD)

    assert "Secure" not in response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("username", "password"),
    [("dana", "the wrong password"), ("nobody", PASSWORD), ("dan", PASSWORD), ("anonymous", "x")],
)
async def test_every_failure_looks_the_same(client, make_user, db, username, password):
    await make_user("dana")
    await make_user("dan")
    dan = await users.get_user_by_username(db, "dan")
    await users.update_user(db, dan, {"status": "disabled"})
    await db.commit()

    response = await attempt(client, username, password)

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid credentials."
    assert error_code(response) == "unauthorized"
    assert "set-cookie" not in response.headers


async def test_username_case_and_surrounding_spaces_do_not_matter(client, make_user):
    await make_user("dana")
    assert (await attempt(client, "  DaNa ", PASSWORD)).status_code == 200


async def test_passwords_may_contain_any_characters(client, make_user):
    await make_user("uma", password="pässwörd-ünïcode-✓")
    assert (await attempt(client, "uma", "pässwörd-ünïcode-✓")).status_code == 200


async def test_sign_in_records_the_time(client, make_user, db):
    await make_user("dana")
    await sign_in(client, "dana")
    assert (await users.get_user_by_username(db, "dana")).last_login_at is not None


async def test_session_endpoint_without_credentials_reports_signed_out(client):
    response = await client.get(SESSION)
    assert response.status_code == 200
    assert response.json() == SIGNED_OUT


async def test_session_endpoint_after_sign_in(client, make_user):
    await make_user("dana")
    signed_in = await sign_in(client, "dana")

    body = (await client.get(SESSION)).json()

    assert body == signed_in
    assert body["permissions"] == []


async def test_sign_out_ends_the_session(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await client.post(LOGOUT)

    assert response.status_code == 204
    assert 'megooarti_session=""' in response.headers["set-cookie"]
    assert (await client.get(SESSION)).json() == SIGNED_OUT


async def test_sign_out_needs_the_csrf_token(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await client.post(LOGOUT, headers={"X-CSRF-Token": "wrong"})

    assert (response.status_code, error_code(response)) == (403, "csrf_failed")
    assert (await client.get(SESSION)).json()["authenticated"] is True


async def test_sign_out_without_a_session_is_harmless(client):
    assert (await client.post(LOGOUT)).status_code == 204


async def test_a_cookie_for_a_session_that_no_longer_exists_means_signed_out(
    client, make_user, db
):
    await make_user("dana")
    await sign_in(client, "dana")
    await db.execute(delete(UserSession))
    await db.commit()

    response = await client.get(SESSION)

    assert response.status_code == 200
    assert response.json() == SIGNED_OUT


async def test_repeated_failures_are_refused_even_with_the_right_password(client, make_user):
    await make_user("dana")
    for _ in range(5):
        assert (await attempt(client, "dana", "the wrong password")).status_code == 401

    response = await attempt(client, "dana", PASSWORD)

    assert (response.status_code, error_code(response)) == (429, "too_many_attempts")
    assert 0 < int(response.headers["Retry-After"]) <= 900


async def test_a_success_clears_the_failure_count(client, make_user):
    await make_user("dana")
    for _ in range(2):
        for _ in range(4):
            await attempt(client, "dana", "the wrong password")
        assert (await attempt(client, "dana", PASSWORD)).status_code == 200


async def test_failures_for_many_usernames_from_one_address_are_refused(client, make_user):
    await make_user("dana")
    for number in range(5):
        await attempt(client, f"guess{number}", "the wrong password")

    assert (await attempt(client, "dana", PASSWORD)).status_code == 429
```

`backend/tests/security/test_authentication.py`:

```python
import base64
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import select, update

from megooarti.clock import utcnow
from megooarti.security import users
from megooarti.security.authentication import Principal, require, require_interactive
from megooarti.security.models import ApiToken, UserSession
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in

READ = "/_test/users-read"
WRITE = "/_test/users-write"
MAVEN = "/_test/maven-read"
INTERACTIVE = "/_test/interactive"


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    def who(principal: Principal) -> dict:
        return {"user": principal.user.username, "method": principal.method}

    @router.get("/users-read")
    async def users_read(principal: Principal = Depends(require("admin:users:read"))) -> dict:
        return who(principal)

    @router.post("/users-write")
    async def users_write(principal: Principal = Depends(require("admin:users:write"))) -> dict:
        return who(principal)

    @router.get("/maven-read")
    async def maven_read(
        principal: Principal = Depends(require("repository:maven:releases:read")),
    ) -> dict:
        return who(principal)

    @router.post("/interactive")
    async def interactive(principal: Principal = Depends(require_interactive())) -> dict:
        return who(principal)

    app.include_router(router)
    return app


async def enable_anonymous_access(db) -> None:
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()


async def disable_user(db, username: str) -> None:
    user = await users.get_user_by_username(db, username)
    await users.update_user(db, user, {"status": "disabled"})
    await db.commit()


async def test_no_credentials_is_unauthorized_with_a_challenge(client):
    response = await client.get(READ)

    assert (response.status_code, error_code(response)) == (401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="MegooArti"'


async def test_basic_with_a_password(client, make_user):
    await make_user("root", roles=["admin"])

    response = await client.get(READ, headers=basic("root", PASSWORD))

    assert response.json() == {"user": "root", "method": "password"}


async def test_basic_with_a_token_in_the_password_field(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    await make_user("dana", roles=["admin"])
    token = await make_token(root)

    assert (await client.get(READ, headers=basic("ROOT", token))).json() == {
        "user": "root",
        "method": "token",
    }
    assert (await client.get(READ, headers=basic("dana", token))).status_code == 401


async def test_bearer_token(client, make_user, make_token, db):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)

    response = await client.get(READ, headers=bearer(token))

    assert response.json() == {"user": "root", "method": "token"}
    assert await db.scalar(select(ApiToken.last_used_at)) is not None


@pytest.mark.parametrize("token", ["mga_" + "x" * 43, "not-a-megooarti-token"])
async def test_an_unknown_bearer_token_is_unauthorized(client, token):
    response = await client.get(READ, headers=bearer(token))
    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_token_scopes_narrow_what_the_owner_may_do(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root, scopes=["admin:users:read"])

    assert (await client.get(READ, headers=bearer(token))).status_code == 200
    refused = await client.post(WRITE, headers=bearer(token))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_token_scopes_never_widen_what_the_owner_may_do(client, make_user, make_token):
    dana = await make_user("dana")
    token = await make_token(dana, scopes=["*"])

    assert (await client.get(READ, headers=bearer(token))).status_code == 403


async def test_an_identified_user_without_the_permission_is_forbidden(client, make_user):
    await make_user("dana")

    response = await client.get(READ, headers=basic("dana", PASSWORD))

    assert (response.status_code, error_code(response)) == (403, "forbidden")


@pytest.mark.parametrize(
    "header",
    [
        "Basic !!!not-base64!!!",
        "Basic " + base64.b64encode(b"no-colon-here").decode(),
        "Basic " + base64.b64encode(b"\xff\xfe:\xff").decode(),
        "Basic",
        "Bearer",
        "Digest username=root",
        "nonsense",
    ],
)
async def test_a_malformed_authorization_header_is_unauthorized(client, header):
    response = await client.get(READ, headers={"Authorization": header})
    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_a_token_stops_working_when_its_owner_is_disabled(client, make_user, make_token, db):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root)
    await disable_user(db, "root")

    assert (await client.get(READ, headers=bearer(token))).status_code == 401
    assert (await client.get(READ, headers=basic("root", PASSWORD))).status_code == 401


async def test_an_expired_token_is_unauthorized(client, make_user, make_token):
    root = await make_user("root", roles=["admin"])
    token = await make_token(root, expires_at=utcnow() - timedelta(seconds=1))

    assert (await client.get(READ, headers=bearer(token))).status_code == 401


async def test_a_cookie_request_that_changes_state_needs_the_csrf_token(admin_client):
    refused = await admin_client.post(WRITE, headers={"X-CSRF-Token": "wrong"})
    allowed = await admin_client.post(WRITE)

    assert (refused.status_code, error_code(refused)) == (403, "csrf_failed")
    assert allowed.json() == {"user": "root", "method": "session"}


async def test_header_authenticated_requests_need_no_csrf_token(client, make_user):
    await make_user("root", roles=["admin"])
    assert (await client.post(WRITE, headers=basic("root", PASSWORD))).status_code == 200


async def test_a_pending_password_change_blocks_everything_but_tokens(
    client, other_client, make_user, make_token
):
    root = await make_user("root", roles=["admin"], must_change_password=True)
    token = await make_token(root)
    await sign_in(client, "root")

    by_session = await client.get(READ)
    by_password = await other_client.get(READ, headers=basic("root", PASSWORD))
    by_token = await other_client.get(READ, headers=bearer(token))

    assert (by_session.status_code, error_code(by_session)) == (403, "password_change_required")
    assert error_code(by_password) == "password_change_required"
    assert by_token.status_code == 200


async def test_anonymous_access_is_off_by_default(client):
    assert (await client.get(MAVEN)).status_code == 401


async def test_anonymous_access_acts_as_the_anonymous_user(client, db):
    await enable_anonymous_access(db)

    allowed = await client.get(MAVEN)
    refused = await client.get(READ)

    assert allowed.json() == {"user": "anonymous", "method": "anonymous"}
    assert (refused.status_code, error_code(refused)) == (401, "unauthorized")


async def test_interactive_routes_refuse_tokens_and_anonymous_requests(
    admin_client, other_client, make_user, make_token, db
):
    dana = await make_user("dana")
    token = await make_token(dana)
    await enable_anonymous_access(db)

    by_token = await other_client.post(INTERACTIVE, headers=bearer(token))
    by_nobody = await other_client.post(INTERACTIVE)
    by_session = await admin_client.post(INTERACTIVE)
    by_password = await other_client.post(INTERACTIVE, headers=basic("dana", PASSWORD))

    assert (by_token.status_code, error_code(by_token)) == (403, "interactive_auth_required")
    assert by_nobody.status_code == 401
    assert by_session.json()["method"] == "session"
    assert by_password.json()["method"] == "password"


async def test_an_authorization_header_takes_priority_over_the_cookie(admin_client):
    response = await admin_client.get(READ, headers=bearer("mga_" + "x" * 43))
    assert response.status_code == 401


async def test_an_idle_session_expires(admin_client, db):
    await db.execute(update(UserSession).values(last_seen_at=utcnow() - timedelta(hours=2)))
    await db.commit()

    assert (await admin_client.get(READ)).status_code == 401


async def test_a_session_ends_when_its_user_is_disabled(admin_client, db):
    await disable_user(db, "root")
    assert (await admin_client.get(READ)).status_code == 401
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_auth_api.py tests/security/test_authentication.py -q`
Expected: `test_authentication.py` fails to collect with `No module named 'megooarti.security.authentication'`; every test in `test_auth_api.py` fails with `404` or a missing key.

- [ ] **Step 4: Implement authentication**

`backend/src/megooarti/security/authentication.py`:

```python
"""Who is making this request, and are they allowed to do this?"""

import asyncio
import base64
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.security import sessions, throttle, tokens, users
from megooarti.security.keys import TOKEN_PREFIX
from megooarti.security.models import ApiToken, User, UserSession
from megooarti.security.passwords import hash_password, needs_rehash, verify_password
from megooarti.security.permissions import any_grants
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

SESSION_COOKIE = "megooarti_session"
CSRF_HEADER = "X-CSRF-Token"
INVALID_CREDENTIALS = "Invalid credentials."
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CHALLENGE = {"WWW-Authenticate": 'Bearer realm="MegooArti"'}

Method = Literal["session", "password", "token", "anonymous"]


@dataclass(frozen=True)
class Principal:
    """The identity a request acts as."""

    user: User
    method: Method
    patterns: frozenset[str]
    scopes: frozenset[str] | None = None
    session: UserSession | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.method == "anonymous"

    @property
    def is_interactive(self) -> bool:
        """Signed in as a person (cookie or password), not with an API token."""
        return self.method in ("session", "password")

    def allows(self, permission: str) -> bool:
        if not any_grants(self.patterns, permission):
            return False
        return self.scopes is None or any_grants(self.scopes, permission)


def unauthorized(message: str = "Authentication is required.") -> ApiError:
    return ApiError(401, "unauthorized", message, headers=_CHALLENGE)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def build_principal(
    db: AsyncSession,
    user: User,
    method: Method,
    *,
    token: ApiToken | None = None,
    session: UserSession | None = None,
) -> Principal:
    scopes = None if token is None or token.scopes is None else frozenset(token.scopes)
    return Principal(user, method, await users.user_patterns(db, user), scopes, session)


async def _checked[T](
    db: AsyncSession,
    request: Request,
    username: str | None,
    attempt: Callable[[], Awaitable[T | None]],
) -> T:
    """Run one credential check under the failed-sign-in limits."""
    settings = request.app.state.settings
    now = utcnow()
    subjects = throttle.subjects(username, client_ip(request))
    standing = await throttle.standing(
        db,
        subjects,
        now=now,
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_failure_window_seconds,
    )
    if standing.blocked_for:
        log.warning("login_throttled", username=username, ip=client_ip(request))
        raise ApiError(
            429,
            "too_many_attempts",
            "Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(standing.blocked_for)},
        )

    result = await attempt()
    if result is None:
        await throttle.record_failure(
            db, subjects, now=now, window_seconds=settings.login_failure_window_seconds
        )
        await db.commit()  # the count must outlive this failed request
        log.info("login_failed", username=username, ip=client_ip(request))
        raise unauthorized(INVALID_CREDENTIALS)
    if standing.has_failures:
        await throttle.clear(db, subjects)
    return result


async def authenticate_password(
    db: AsyncSession, request: Request, username: str, password: str
) -> User:
    """The active user with this username and password, or a 401 / 429 error."""
    username = users.normalise_username(username)

    async def attempt() -> User | None:
        user = await users.get_user_by_username(db, username)
        stored = None if user is None else user.password_hash
        matched = await asyncio.to_thread(verify_password, stored, password)
        if user is None or not matched or user.status != "active":
            return None
        if needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(hash_password, password)
        return user

    return await _checked(db, request, username, attempt)


async def _authenticate_token(
    db: AsyncSession, request: Request, value: str, username: str | None = None
) -> tuple[User, ApiToken]:
    async def attempt() -> tuple[User, ApiToken] | None:
        now = utcnow()
        token = await tokens.find_token(db, value, now)
        if token is None:
            return None
        user = await users.get_user(db, token.user_id)
        if user is None or user.status != "active":
            return None
        if username is not None and user.username != users.normalise_username(username):
            return None
        tokens.touch(token, now)
        return user, token

    # Token attempts are limited by address only, so a locked-out username does not
    # stop that user's automation.
    return await _checked(db, request, None, attempt)


def _decode_basic(credentials: str) -> tuple[str, str]:
    try:
        decoded = base64.b64decode(credentials.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise unauthorized("The Authorization header is malformed.") from None
    username, separator, secret = decoded.partition(":")
    if not separator:
        raise unauthorized("The Authorization header is malformed.")
    return username, secret


async def _from_header(db: AsyncSession, request: Request, header: str) -> Principal:
    scheme, _, credentials = header.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer":
        user, token = await _authenticate_token(db, request, credentials.strip())
        return await build_principal(db, user, "token", token=token)
    if scheme == "basic":
        username, secret = _decode_basic(credentials)
        if secret.startswith(TOKEN_PREFIX):
            user, token = await _authenticate_token(db, request, secret, username)
            return await build_principal(db, user, "token", token=token)
        user = await authenticate_password(db, request, username, secret)
        return await build_principal(db, user, "password")
    raise unauthorized("The Authorization scheme is not supported.")


async def resolve_principal(request: Request, db: AsyncSession) -> Principal | None:
    """The principal for this request, or None when there are no credentials.

    Invalid credentials in an Authorization header are an error, never a fall-through
    to the cookie or to anonymous access.
    """
    header = request.headers.get("Authorization")
    if header:
        return await _from_header(db, request, header)

    settings = request.app.state.settings
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        now = utcnow()
        record = await sessions.find_session(
            db, cookie, now=now, idle_seconds=settings.session_idle_seconds
        )
        if record is not None:
            user = await users.get_user(db, record.user_id)
            if user is not None and user.status == "active":
                sessions.touch(record, now)
                return await build_principal(db, user, "session", session=record)

    if (await get_setting(db, "anonymous_access"))["enabled"]:
        anonymous = await users.get_user_by_username(db, "anonymous")
        if anonymous is not None and anonymous.status == "active":
            return await build_principal(db, anonymous, "anonymous")
    return None


async def current_principal(
    request: Request, db: AsyncSession = Depends(get_session)
) -> Principal | None:
    """Dependency: who is calling, if anyone. Enforces CSRF for cookie requests."""
    principal = await resolve_principal(request, db)
    await db.commit()  # last-seen times, cleared failure counts, upgraded password hashes
    if (
        principal is not None
        and principal.session is not None
        and request.method in _UNSAFE_METHODS
    ):
        sent = request.headers.get(CSRF_HEADER, "")
        expected = principal.session.csrf_token
        if not secrets.compare_digest(sent.encode(), expected.encode()):
            raise ApiError(403, "csrf_failed", "The CSRF token is missing or wrong.")
    return principal


def _refuse_pending_password_change(principal: Principal) -> None:
    if principal.is_interactive and principal.user.must_change_password:
        raise ApiError(
            403, "password_change_required", "Change your password before doing anything else."
        )


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must hold `permission`."""

    async def dependency(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        if principal is None:
            raise unauthorized()
        _refuse_pending_password_change(principal)
        if not principal.allows(permission):
            if principal.is_anonymous:
                raise unauthorized()
            raise ApiError(403, "forbidden", "You do not have permission to do this.")
        return principal

    return dependency


def require_interactive(
    *, allow_pending_password_change: bool = False
) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: the caller must be signed in as a person, not with a token."""

    async def dependency(
        principal: Principal | None = Depends(current_principal),
    ) -> Principal:
        if principal is None or principal.is_anonymous:
            raise unauthorized()
        if not principal.is_interactive:
            raise ApiError(
                403,
                "interactive_auth_required",
                "Sign in with your password to do this; an API token is not enough.",
            )
        if not allow_pending_password_change:
            _refuse_pending_password_change(principal)
        return principal

    return dependency
```

- [ ] **Step 5: Implement the sign-in routes**

Create `backend/src/megooarti/security/api/__init__.py` as an empty file.

`backend/src/megooarti/security/api/auth.py`:

```python
"""Sign in, sign out, and "who am I?"."""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.security import sessions
from megooarti.security.authentication import (
    SESSION_COOKIE,
    Principal,
    authenticate_password,
    build_principal,
    client_ip,
    current_principal,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None


class SessionInfo(BaseModel):
    authenticated: bool
    method: str | None
    user: UserSummary | None
    permissions: list[str]
    must_change_password: bool
    csrf_token: str | None


def session_info(principal: Principal | None) -> SessionInfo:
    if principal is None:
        return SessionInfo(
            authenticated=False,
            method=None,
            user=None,
            permissions=[],
            must_change_password=False,
            csrf_token=None,
        )
    identified = not principal.is_anonymous
    user = principal.user
    summary = UserSummary(
        id=user.id, username=user.username, display_name=user.display_name, email=user.email
    )
    return SessionInfo(
        authenticated=identified,
        method=principal.method,
        user=summary if identified else None,
        permissions=sorted(principal.patterns),
        must_change_password=principal.is_interactive and user.must_change_password,
        csrf_token=None if principal.session is None else principal.session.csrf_token,
    )


@router.post("/login", response_model=SessionInfo)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> SessionInfo:
    settings = request.app.state.settings
    user = await authenticate_password(db, request, body.username, body.password)
    now = utcnow()
    user.last_login_at = now
    record, value = await sessions.create_session(
        db,
        user.id,
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        now=now,
        lifetime_seconds=settings.session_absolute_seconds,
    )
    principal = await build_principal(db, user, "session", session=record)
    await db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        value,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    log.info("login_succeeded", username=user.username, ip=client_ip(request))
    return session_info(principal)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    principal: Principal | None = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    if principal is not None and principal.session is not None:
        await sessions.delete_session(db, principal.session)
        await db.commit()
        log.info("logout", username=principal.user.username)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/session", response_model=SessionInfo)
async def session(principal: Principal | None = Depends(current_principal)) -> SessionInfo:
    """Describe the caller. Answers 200 when nobody is signed in, so a UI can start here."""
    return session_info(principal)
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.security.api import auth as auth_api` and add after the line that includes `status_router`:

```python
    app.include_router(auth_api.router, prefix=API_PREFIX)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_auth_api.py tests/security/test_authentication.py -q`
Expected: 45 passed.

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
git commit -m "feat(security): authenticate by session, password, token or anonymously"
```

---

### Task 10: Self-service API — own password and own tokens

**Files:**
- Create: `backend/src/megooarti/security/api/schemas.py`
- Create: `backend/src/megooarti/security/api/me.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/security/test_me_api.py`

**Interfaces:**
- Consumes: `require_interactive`, `authenticate_password`, `users.set_password`, `tokens`, `PageParams`, `Page`, `page`.
- Produces:
  - `megooarti.security.api.schemas`: `Pattern` (a validated permission-pattern string type), `TokenInfo`, `TokenCreated`
  - Routes under `/api/v1/me`: `PUT /password`, `GET /tokens`, `POST /tokens`, `DELETE /tokens/{token_id}`

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_me_api.py`:

```python
import pytest

from tests.accounts import PASSWORD, basic, bearer, error_code, sign_in

ME = "/api/v1/me"
SESSION = "/api/v1/auth/session"
NEW_PASSWORD = "an entirely new password"


async def change(client, current=PASSWORD, new=NEW_PASSWORD, **kwargs):
    body = {"current_password": current, "new_password": new}
    return await client.put(f"{ME}/password", json=body, **kwargs)


async def test_changing_the_password_keeps_this_session_and_ends_the_others(
    client, other_client, make_user
):
    await make_user("dana")
    await sign_in(client, "dana")
    await sign_in(other_client, "dana")

    response = await change(client)

    assert response.status_code == 204
    assert (await client.get(SESSION)).json()["authenticated"] is True
    assert (await other_client.get(SESSION)).json()["authenticated"] is False
    old = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    new = await other_client.get(SESSION, headers=basic("dana", NEW_PASSWORD))
    assert old.status_code == 401
    assert new.json()["method"] == "password"


async def test_the_current_password_must_be_right(client, other_client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await change(client, current="not my password")

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "body.current_password"
    still_works = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    assert still_works.status_code == 200


async def test_the_new_password_must_be_acceptable(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await change(client, new="short")

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == "password"


async def test_a_forced_change_can_be_completed(client, make_user):
    await make_user("dana", must_change_password=True)
    assert (await sign_in(client, "dana"))["must_change_password"] is True

    assert (await change(client)).status_code == 204

    assert (await client.get(SESSION)).json()["must_change_password"] is False
    assert (await client.get(f"{ME}/tokens")).status_code == 200


async def test_a_token_cannot_change_the_password(client, make_user, make_token):
    dana = await make_user("dana")
    token = await make_token(dana)

    response = await change(client, headers=bearer(token))

    assert (response.status_code, error_code(response)) == (403, "interactive_auth_required")


async def test_changing_the_password_needs_someone_signed_in(client):
    assert (await change(client)).status_code == 401


async def test_create_list_use_and_revoke_a_token(client, other_client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")

    created = await client.post(f"{ME}/tokens", json={"name": "ci"})

    assert created.status_code == 201
    body = created.json()
    token = body["token"]
    assert token.startswith("mga_")
    assert (body["name"], body["display_prefix"], body["scopes"]) == ("ci", token[:8], None)

    listed = (await client.get(f"{ME}/tokens")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == body["id"]
    assert "token" not in listed["items"][0]

    who = (await other_client.get(SESSION, headers=bearer(token))).json()
    assert (who["method"], who["user"]["username"]) == ("token", "dana")

    assert (await client.delete(f"{ME}/tokens/{body['id']}")).status_code == 204
    assert (await other_client.get(SESSION, headers=bearer(token))).status_code == 401
    assert (await client.delete(f"{ME}/tokens/{body['id']}")).status_code == 404


async def test_a_token_can_have_scopes_and_an_expiry(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")
    request = {
        "name": "read-only",
        "scopes": ["repository:*:*:read"],
        "expires_at": "2099-01-01T00:00:00Z",
    }

    body = (await client.post(f"{ME}/tokens", json=request)).json()

    assert body["scopes"] == ["repository:*:*:read"]
    assert body["expires_at"].startswith("2099-01-01T00:00:00")


async def test_token_names_must_be_unique(client, make_user):
    await make_user("dana")
    await sign_in(client, "dana")
    await client.post(f"{ME}/tokens", json={"name": "ci"})

    response = await client.post(f"{ME}/tokens", json={"name": "ci"})

    assert (response.status_code, error_code(response)) == (409, "conflict")


@pytest.mark.parametrize(
    "request_body",
    [
        {"name": ""},
        {"name": "x" * 101},
        {"name": "ci", "scopes": ["not a pattern"]},
        {"name": "ci", "expires_at": "2020-01-01T00:00:00Z"},
        {"name": "ci", "expires_at": "2099-01-01T00:00:00"},
    ],
)
async def test_invalid_token_requests_are_rejected(client, make_user, request_body):
    await make_user("dana")
    await sign_in(client, "dana")

    response = await client.post(f"{ME}/tokens", json=request_body)

    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_token_cannot_create_or_list_tokens(client, make_user, make_token):
    dana = await make_user("dana")
    token = await make_token(dana)

    created = await client.post(f"{ME}/tokens", json={"name": "more"}, headers=bearer(token))
    listed = await client.get(f"{ME}/tokens", headers=bearer(token))

    assert error_code(created) == "interactive_auth_required"
    assert error_code(listed) == "interactive_auth_required"


async def test_one_user_cannot_revoke_another_users_token(client, other_client, make_user):
    await make_user("dana")
    await make_user("eli")
    await sign_in(client, "dana")
    await sign_in(other_client, "eli")
    token_id = (await client.post(f"{ME}/tokens", json={"name": "ci"})).json()["id"]

    response = await other_client.delete(f"{ME}/tokens/{token_id}")

    assert response.status_code == 404
    assert (await client.get(f"{ME}/tokens")).json()["total"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_me_api.py -q`
Expected: every test fails with `404` responses.

- [ ] **Step 3: Implement the shared schemas**

`backend/src/megooarti/security/api/schemas.py`:

```python
"""Request and response shapes shared by the security routers."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel

from megooarti.security.permissions import is_valid_pattern


def _valid_pattern(value: str) -> str:
    if len(value) > 255 or not is_valid_pattern(value):
        raise ValueError("is not a valid permission pattern")
    return value


Pattern = Annotated[str, AfterValidator(_valid_pattern)]


class TokenInfo(BaseModel):
    id: uuid.UUID
    name: str
    display_prefix: str
    scopes: list[str] | None
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


class TokenCreated(TokenInfo):
    token: str
```

- [ ] **Step 4: Implement the routes**

`backend/src/megooarti/security/api/me.py`:

```python
"""What a signed-in person may do to their own account."""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import tokens, users
from megooarti.security.api.schemas import Pattern, TokenCreated, TokenInfo
from megooarti.security.authentication import (
    Principal,
    authenticate_password,
    require_interactive,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/me", tags=["account"])


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: AwareDatetime | None = None
    scopes: list[Pattern] | None = None


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


@router.put("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    request: Request,
    principal: Principal = Depends(require_interactive(allow_pending_password_change=True)),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = principal.user
    try:
        await authenticate_password(db, request, user.username, body.current_password)
    except ApiError as error:
        if error.status_code != 401:
            raise
        raise _invalid("body.current_password", "The current password is not correct.") from None
    keep = None if principal.session is None else principal.session.id
    await users.set_password(
        db, user, body.new_password, must_change_password=False, keep_session_id=keep
    )
    await db.commit()
    log.info("password_changed", username=user.username, by=user.username)


@router.get("/tokens", response_model=Page[TokenInfo])
async def list_tokens(
    params: PageParams = Depends(),
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await tokens.list_tokens(db, principal.user.id, params.limit, params.offset)
    return page(items, total, params)


@router.post("/tokens", response_model=TokenCreated, status_code=201)
async def create_token(
    body: TokenCreate,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> TokenCreated:
    if body.expires_at is not None and body.expires_at <= utcnow():
        raise _invalid("body.expires_at", "The expiry must be in the future.")
    token, value = await tokens.create_token(
        db, principal.user.id, name=body.name, expires_at=body.expires_at, scopes=body.scopes
    )
    created = TokenCreated(
        id=token.id,
        name=token.name,
        display_prefix=token.display_prefix,
        scopes=token.scopes,
        expires_at=token.expires_at,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        token=value,
    )
    await db.commit()
    log.info("token_created", username=principal.user.username, token=token.name)
    return created


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> None:
    await tokens.revoke_token(db, principal.user.id, token_id)
    await db.commit()
    log.info("token_revoked", username=principal.user.username, by=principal.user.username)
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.security.api import me as me_api` and include the router after the auth router:

```python
    app.include_router(me_api.router, prefix=API_PREFIX)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_me_api.py -q`
Expected: 16 passed.

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
git commit -m "feat(security): let people change their password and manage their API tokens"
```

---

### Task 11: Administration API — users, roles and other people's tokens

**Files:**
- Create: `backend/src/megooarti/security/api/users.py`
- Create: `backend/src/megooarti/security/api/roles.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/security/test_users_api.py`
- Test: `backend/tests/security/test_roles_api.py`

**Interfaces:**
- Consumes: `require`, `users`, `roles`, `tokens`, `ensure_administrator_remains`, `Pattern`, `TokenInfo`, `PageParams`, `Page`, `page`.
- Produces routes under `/api/v1`:
  - `GET /users`, `POST /users`, `GET /users/{user_id}`, `PATCH /users/{user_id}`, `DELETE /users/{user_id}`, `PUT /users/{user_id}/password`, `GET /users/{user_id}/tokens`, `DELETE /users/{user_id}/tokens/{token_id}`
  - `GET /roles`, `POST /roles`, `GET /roles/{name}`, `PUT /roles/{name}`, `DELETE /roles/{name}`

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_users_api.py`:

```python
import uuid

import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code, sign_in

USERS = "/api/v1/users"
SESSION = "/api/v1/auth/session"
ELI = {
    "username": "Eli",
    "display_name": "Eli Stone",
    "email": "eli@example.org",
    "password": "a perfectly fine password",
    "roles": ["anonymous"],
}


async def id_of(client, username: str) -> str:
    listed = (await client.get(USERS, params={"limit": 200})).json()
    return next(item["id"] for item in listed["items"] if item["username"] == username)


async def test_listing_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(USERS)).status_code == 401
    refused = await client.get(USERS, headers=basic("dana", PASSWORD))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_list_is_paged(admin_client):
    body = (await admin_client.get(USERS, params={"limit": 2})).json()

    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 0)
    assert [item["username"] for item in body["items"]] == ["admin", "anonymous"]


async def test_create_a_user_who_must_change_their_password(admin_client, other_client):
    response = await admin_client.post(USERS, json=ELI)

    assert response.status_code == 201
    body = response.json()
    assert (body["username"], body["display_name"], body["email"]) == (
        "eli",
        "Eli Stone",
        "eli@example.org",
    )
    assert (body["status"], body["builtin"], body["roles"]) == ("active", False, ["anonymous"])
    assert body["must_change_password"] is True
    assert "password" not in body
    signed_in = await sign_in(other_client, "eli", ELI["password"])
    assert signed_in["must_change_password"] is True


@pytest.mark.parametrize(
    "override",
    [
        {"username": "has space"},
        {"username": ""},
        {"display_name": ""},
        {"email": "not-an-email"},
        {"password": "short"},
        {"roles": ["ghost"]},
    ],
)
async def test_invalid_users_are_rejected(admin_client, override):
    response = await admin_client.post(USERS, json={**ELI, **override})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_duplicate_username_is_a_conflict(admin_client):
    await admin_client.post(USERS, json=ELI)
    response = await admin_client.post(USERS, json={**ELI, "username": "ELI"})
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_get_one_user(admin_client):
    root_id = await id_of(admin_client, "root")

    found = await admin_client.get(f"{USERS}/{root_id}")
    missing = await admin_client.get(f"{USERS}/{uuid.uuid4()}")
    malformed = await admin_client.get(f"{USERS}/not-a-uuid")

    assert found.json()["roles"] == ["admin"]
    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert malformed.status_code == 422


async def test_patch_changes_only_what_is_sent(admin_client, make_user):
    dana = await make_user("dana", roles=["anonymous"])

    response = await admin_client.patch(f"{USERS}/{dana.id}", json={"display_name": "D. Smith"})
    assert response.json()["display_name"] == "D. Smith"
    assert response.json()["roles"] == ["anonymous"]

    response = await admin_client.patch(
        f"{USERS}/{dana.id}", json={"roles": ["admin"], "email": "d@example.org"}
    )
    assert (response.json()["roles"], response.json()["email"]) == (["admin"], "d@example.org")

    response = await admin_client.patch(f"{USERS}/{dana.id}", json={"email": None})
    assert response.json()["email"] is None


async def test_disabling_a_user_signs_them_out_and_keeps_them_out(
    admin_client, other_client, make_user
):
    dana = await make_user("dana")
    await sign_in(other_client, "dana")

    response = await admin_client.patch(f"{USERS}/{dana.id}", json={"status": "disabled"})

    assert response.json()["status"] == "disabled"
    assert (await other_client.get(SESSION)).json()["authenticated"] is False
    login = {"username": "dana", "password": PASSWORD}
    assert (await other_client.post("/api/v1/auth/login", json=login)).status_code == 401


async def test_you_cannot_disable_or_delete_yourself(admin_client):
    root_id = await id_of(admin_client, "root")

    disabled = await admin_client.patch(f"{USERS}/{root_id}", json={"status": "disabled"})
    deleted = await admin_client.delete(f"{USERS}/{root_id}")

    assert (disabled.status_code, error_code(disabled)) == (409, "self_protected")
    assert (deleted.status_code, error_code(deleted)) == (409, "self_protected")


async def test_the_last_administrator_cannot_be_demoted(admin_client):
    root_id = await id_of(admin_client, "root")

    response = await admin_client.patch(f"{USERS}/{root_id}", json={"roles": []})

    assert (response.status_code, error_code(response)) == (409, "last_administrator")
    assert (await admin_client.get(f"{USERS}/{root_id}")).json()["roles"] == ["admin"]


async def test_delete_a_user(admin_client, make_user):
    dana = await make_user("dana")

    assert (await admin_client.delete(f"{USERS}/{dana.id}")).status_code == 204
    assert (await admin_client.get(f"{USERS}/{dana.id}")).status_code == 404


async def test_built_in_users_cannot_be_deleted(admin_client):
    admin_id = await id_of(admin_client, "admin")

    response = await admin_client.delete(f"{USERS}/{admin_id}")

    assert (response.status_code, error_code(response)) == (409, "builtin_protected")


async def test_reset_a_password(admin_client, other_client, make_user):
    dana = await make_user("dana")
    await sign_in(other_client, "dana")

    response = await admin_client.put(
        f"{USERS}/{dana.id}/password", json={"password": "a temporary password"}
    )

    assert response.status_code == 204
    assert (await other_client.get(SESSION)).json()["authenticated"] is False
    old = await other_client.get(SESSION, headers=basic("dana", PASSWORD))
    assert old.status_code == 401
    assert (await sign_in(other_client, "dana", "a temporary password"))[
        "must_change_password"
    ] is True


async def test_the_anonymous_user_cannot_be_given_a_password(admin_client):
    anonymous_id = await id_of(admin_client, "anonymous")

    response = await admin_client.put(
        f"{USERS}/{anonymous_id}/password", json={"password": "a temporary password"}
    )

    assert (response.status_code, error_code(response)) == (409, "builtin_protected")


async def test_list_and_revoke_another_users_tokens(admin_client, make_user, make_token):
    dana = await make_user("dana")
    await make_token(dana, "ci")
    url = f"{USERS}/{dana.id}/tokens"

    listed = (await admin_client.get(url)).json()

    assert (listed["total"], listed["items"][0]["name"]) == (1, "ci")
    assert "token" not in listed["items"][0]
    token_id = listed["items"][0]["id"]
    assert (await admin_client.delete(f"{url}/{token_id}")).status_code == 204
    assert (await admin_client.get(url)).json()["total"] == 0
    assert (await admin_client.get(f"{USERS}/{uuid.uuid4()}/tokens")).status_code == 404


async def test_managing_users_does_not_include_managing_their_tokens(client, make_user, db):
    await roles.create_role(db, "user-admins", "", ["admin:users:*"], [])
    await db.commit()
    ula = await make_user("ula", roles=["user-admins"])
    headers = basic("ula", PASSWORD)

    allowed = await client.get(USERS, headers=headers)
    refused = await client.get(f"{USERS}/{ula.id}/tokens", headers=headers)

    assert allowed.status_code == 200
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
```

`backend/tests/security/test_roles_api.py`:

```python
import pytest

from megooarti.security import roles as role_service
from tests.accounts import PASSWORD, basic, error_code, sign_in

ROLES = "/api/v1/roles"
READERS = {
    "name": "readers",
    "description": "May read everything",
    "permissions": ["repository:*:*:read", "repository:*:*:browse"],
    "roles": [],
}


async def test_listing_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(ROLES)).status_code == 401
    assert (await client.get(ROLES, headers=basic("dana", PASSWORD))).status_code == 403


async def test_create_get_and_list(admin_client):
    created = await admin_client.post(ROLES, json=READERS)

    assert created.status_code == 201
    expected = {
        **READERS,
        "builtin": False,
        "permissions": ["repository:*:*:browse", "repository:*:*:read"],
    }
    assert created.json() == expected
    assert (await admin_client.get(f"{ROLES}/readers")).json() == expected
    listed = (await admin_client.get(ROLES)).json()
    assert listed["total"] == 3
    assert [item["name"] for item in listed["items"]] == ["admin", "anonymous", "readers"]


@pytest.mark.parametrize(
    "override",
    [
        {"name": "has space"},
        {"name": ""},
        {"permissions": ["not a pattern"]},
        {"description": "x" * 256},
        {"roles": ["ghost"]},
    ],
)
async def test_invalid_roles_are_rejected(admin_client, override):
    response = await admin_client.post(ROLES, json={**READERS, **override})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_a_duplicate_name_is_a_conflict(admin_client):
    await admin_client.post(ROLES, json=READERS)
    response = await admin_client.post(ROLES, json=READERS)
    assert (response.status_code, error_code(response)) == (409, "conflict")


async def test_put_replaces_the_content(admin_client):
    await admin_client.post(ROLES, json=READERS)
    await admin_client.post(ROLES, json={**READERS, "name": "team", "roles": ["readers"]})
    update = {"description": "Changed", "permissions": ["admin:users:read"], "roles": []}

    response = await admin_client.put(f"{ROLES}/team", json=update)

    assert response.json() == {"name": "team", "builtin": False, **update}
    assert (await admin_client.put(f"{ROLES}/ghost", json=update)).status_code == 404


async def test_a_cycle_is_a_conflict(admin_client):
    await admin_client.post(ROLES, json={**READERS, "name": "inner"})
    await admin_client.post(ROLES, json={**READERS, "name": "outer", "roles": ["inner"]})

    response = await admin_client.put(
        f"{ROLES}/inner", json={"description": "", "permissions": [], "roles": ["outer"]}
    )

    assert (response.status_code, error_code(response)) == (409, "role_cycle")


async def test_built_in_roles_are_protected(admin_client):
    empty = {"description": "", "permissions": [], "roles": []}

    changed = await admin_client.put(f"{ROLES}/admin", json=empty)
    deleted = await admin_client.delete(f"{ROLES}/anonymous")

    assert (changed.status_code, error_code(changed)) == (409, "builtin_protected")
    assert (deleted.status_code, error_code(deleted)) == (409, "builtin_protected")


async def test_delete_a_role(admin_client):
    await admin_client.post(ROLES, json=READERS)

    assert (await admin_client.delete(f"{ROLES}/readers")).status_code == 204
    assert (await admin_client.get(f"{ROLES}/readers")).status_code == 404
    assert (await admin_client.delete(f"{ROLES}/readers")).status_code == 404


async def test_the_role_that_gives_the_last_administrator_access_cannot_go(
    client, make_user, db
):
    await role_service.create_role(db, "super", "", ["*"], [])
    await db.commit()
    await make_user("sue", roles=["super"])
    await sign_in(client, "sue")
    empty = {"description": "", "permissions": [], "roles": []}

    deleted = await client.delete(f"{ROLES}/super")
    emptied = await client.put(f"{ROLES}/super", json=empty)

    assert (deleted.status_code, error_code(deleted)) == (409, "last_administrator")
    assert (emptied.status_code, error_code(emptied)) == (409, "last_administrator")
    assert (await client.get(f"{ROLES}/super")).json()["permissions"] == ["*"]


async def test_a_permission_granted_through_a_role_takes_effect(
    admin_client, other_client, make_user
):
    dana = await make_user("dana")
    headers = basic("dana", PASSWORD)
    assert (await other_client.get(ROLES, headers=headers)).status_code == 403

    await admin_client.post(
        ROLES, json={**READERS, "name": "role-viewers", "permissions": ["admin:roles:read"]}
    )
    await admin_client.patch(f"/api/v1/users/{dana.id}", json={"roles": ["role-viewers"]})

    assert (await other_client.get(ROLES, headers=headers)).status_code == 200
    refused = await other_client.post(ROLES, json=READERS, headers=headers)
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_users_api.py tests/security/test_roles_api.py -q`
Expected: every test fails with `404` responses or a `StopIteration` from `id_of`.

- [ ] **Step 3: Implement the users routes**

`backend/src/megooarti/security/api/users.py`:

```python
"""Administration of users, and of other people's API tokens."""

import uuid
from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import tokens, users
from megooarti.security.api.schemas import TokenInfo
from megooarti.security.authentication import Principal, require
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import User
from megooarti.security.users import UserView

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

_USERNAME = r"^[A-Za-z0-9._@-]{1,64}$"
_EMAIL = r"^[^@\s]+@[^@\s]+$"


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    status: str
    must_change_password: bool
    builtin: bool
    roles: list[str]
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(pattern=_USERNAME)
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)
    password: str = Field(max_length=1024)
    roles: list[str] = []
    must_change_password: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)
    status: Literal["active", "disabled"] | None = None
    roles: list[str] | None = None


class PasswordReset(BaseModel):
    password: str = Field(max_length=1024)
    must_change_password: bool = True


async def _load(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await users.get_user(db, user_id)
    if user is None:
        raise ApiError(404, "not_found", "No such user.")
    return user


@router.get("", response_model=Page[UserOut])
async def list_users(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:users:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await users.list_users(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> UserView:
    user = await users.create_user(
        db,
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        password=body.password,
        role_names=body.roles,
        must_change_password=body.must_change_password,
    )
    view = await users.describe(db, user)
    await db.commit()
    log.info("user_created", username=user.username, by=principal.user.username)
    return view


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    _: Principal = Depends(require("admin:users:read")),
    db: AsyncSession = Depends(get_session),
) -> UserView:
    return await users.describe(db, await _load(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> UserView:
    user = await _load(db, user_id)
    # A field sent as null means "no change", except email, where null clears it.
    changes = {
        name: value
        for name, value in body.model_dump(exclude_unset=True).items()
        if value is not None or name == "email"
    }
    if user.id == principal.user.id and changes.get("status") == "disabled":
        raise ApiError(409, "self_protected", "You cannot disable your own account.")
    await users.update_user(db, user, changes)
    await ensure_administrator_remains(db)
    view = await users.describe(db, user)
    await db.commit()
    log.info("user_updated", username=user.username, by=principal.user.username)
    return view


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await _load(db, user_id)
    if user.id == principal.user.id:
        raise ApiError(409, "self_protected", "You cannot delete your own account.")
    await users.delete_user(db, user)
    await ensure_administrator_remains(db)
    await db.commit()
    log.info("user_deleted", username=user.username, by=principal.user.username)


@router.put("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await _load(db, user_id)
    own_session = principal.session if user.id == principal.user.id else None
    await users.set_password(
        db,
        user,
        body.password,
        must_change_password=body.must_change_password,
        keep_session_id=None if own_session is None else own_session.id,
    )
    await db.commit()
    log.info("password_changed", username=user.username, by=principal.user.username)


@router.get("/{user_id}/tokens", response_model=Page[TokenInfo])
async def list_user_tokens(
    user_id: uuid.UUID,
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:tokens:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    user = await _load(db, user_id)
    items, total = await tokens.list_tokens(db, user.id, params.limit, params.offset)
    return page(items, total, params)


@router.delete("/{user_id}/tokens/{token_id}", status_code=204)
async def revoke_user_token(
    user_id: uuid.UUID,
    token_id: uuid.UUID,
    principal: Principal = Depends(require("admin:tokens:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await _load(db, user_id)
    await tokens.revoke_token(db, user.id, token_id)
    await db.commit()
    log.info("token_revoked", username=user.username, by=principal.user.username)
```

- [ ] **Step 4: Implement the roles routes**

`backend/src/megooarti/security/api/roles.py`:

```python
"""Administration of roles."""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import roles
from megooarti.security.api.schemas import Pattern
from megooarti.security.authentication import Principal, require
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import Role
from megooarti.security.roles import RoleView

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/roles", tags=["roles"])


class RoleOut(BaseModel):
    name: str
    description: str
    builtin: bool
    permissions: list[str]
    roles: list[str]


class RoleContent(BaseModel):
    description: str = Field(default="", max_length=255)
    permissions: list[Pattern] = []
    roles: list[str] = []


class RoleCreate(RoleContent):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")


async def _load(db: AsyncSession, name: str) -> Role:
    role = await roles.get_role(db, name)
    if role is None:
        raise ApiError(404, "not_found", "No such role.")
    return role


@router.get("", response_model=Page[RoleOut])
async def list_roles(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:roles:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await roles.list_roles(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreate,
    principal: Principal = Depends(require("admin:roles:write")),
    db: AsyncSession = Depends(get_session),
) -> RoleView:
    role = await roles.create_role(db, body.name, body.description, body.permissions, body.roles)
    view = await roles.describe(db, role)
    await db.commit()
    log.info("role_created", role=role.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=RoleOut)
async def get_role(
    name: str,
    _: Principal = Depends(require("admin:roles:read")),
    db: AsyncSession = Depends(get_session),
) -> RoleView:
    return await roles.describe(db, await _load(db, name))


@router.put("/{name}", response_model=RoleOut)
async def update_role(
    name: str,
    body: RoleContent,
    principal: Principal = Depends(require("admin:roles:write")),
    db: AsyncSession = Depends(get_session),
) -> RoleView:
    role = await _load(db, name)
    await roles.update_role(db, role, body.description, body.permissions, body.roles)
    await ensure_administrator_remains(db)
    view = await roles.describe(db, role)
    await db.commit()
    log.info("role_updated", role=role.name, by=principal.user.username)
    return view


@router.delete("/{name}", status_code=204)
async def delete_role(
    name: str,
    principal: Principal = Depends(require("admin:roles:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    role = await _load(db, name)
    await roles.delete_role(db, role)
    await ensure_administrator_remains(db)
    await db.commit()
    log.info("role_deleted", role=name, by=principal.user.username)
```

In `backend/src/megooarti/main.py`, add the imports `from megooarti.security.api import roles as roles_api` and `from megooarti.security.api import users as users_api`, and include the routers after the `me` router:

```python
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(roles_api.router, prefix=API_PREFIX)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_users_api.py tests/security/test_roles_api.py -q`
Expected: 35 passed.

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
git commit -m "feat(security): add administration API for users, roles and tokens"
```

---

### Task 12: Settings API

**Files:**
- Create: `backend/src/megooarti/system/settings_api.py`
- Modify: `backend/src/megooarti/main.py`
- Test: `backend/tests/test_settings_api.py`

**Interfaces:**
- Consumes: `require`, `get_setting`, `set_setting`.
- Produces routes under `/api/v1/settings`: `GET ""`, `PUT /base-url`, `PUT /anonymous-access`. Each returns `{"base_url": str | null, "anonymous_access": {"enabled": bool}}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_settings_api.py`:

```python
import pytest

from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

SETTINGS = "/api/v1/settings"
SESSION = "/api/v1/auth/session"
DEFAULTS = {"base_url": None, "anonymous_access": {"enabled": False}}


async def test_reading_needs_the_permission(client, make_user):
    await make_user("dana")

    assert (await client.get(SETTINGS)).status_code == 401
    assert (await client.get(SETTINGS, headers=basic("dana", PASSWORD))).status_code == 403


async def test_defaults(admin_client):
    assert (await admin_client.get(SETTINGS)).json() == DEFAULTS


async def test_base_url_is_stored_without_a_trailing_slash_and_can_be_cleared(admin_client):
    stored = await admin_client.put(
        f"{SETTINGS}/base-url", json={"base_url": " https://repo.example.org/megooarti/ "}
    )

    assert stored.status_code == 200
    assert stored.json()["base_url"] == "https://repo.example.org/megooarti"
    assert (await admin_client.get(SETTINGS)).json()["base_url"] == stored.json()["base_url"]

    cleared = await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": None})
    assert cleared.json() == DEFAULTS


@pytest.mark.parametrize(
    "value", ["ftp://repo.example.org", "repo.example.org", "https://", "https://x.example/?a=1"]
)
async def test_an_invalid_base_url_is_rejected(admin_client, value):
    response = await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": value})
    assert (response.status_code, error_code(response)) == (422, "validation_error")


async def test_turning_on_anonymous_access_takes_effect_at_once(admin_client, other_client):
    assert (await other_client.get(SESSION)).json()["method"] is None

    response = await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": True})

    assert response.json()["anonymous_access"] == {"enabled": True}
    seen = (await other_client.get(SESSION)).json()
    assert (seen["authenticated"], seen["method"], seen["user"]) == (False, "anonymous", None)
    assert seen["permissions"] == ["repository:*:*:browse", "repository:*:*:read"]

    await admin_client.put(f"{SETTINGS}/anonymous-access", json={"enabled": False})
    assert (await other_client.get(SESSION)).json()["method"] is None


async def test_reading_settings_does_not_allow_changing_them(client, make_user, db):
    await roles.create_role(db, "settings-readers", "", ["admin:settings:read"], [])
    await db.commit()
    await make_user("rae", roles=["settings-readers"])
    headers = basic("rae", PASSWORD)

    read = await client.get(SETTINGS, headers=headers)
    write = await client.put(
        f"{SETTINGS}/anonymous-access", json={"enabled": True}, headers=headers
    )

    assert read.status_code == 200
    assert (write.status_code, error_code(write)) == (403, "forbidden")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_settings_api.py -q`
Expected: every test fails with `404` responses.

- [ ] **Step 3: Implement**

`backend/src/megooarti/system/settings_api.py`:

```python
"""Instance settings an administrator can change."""

from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.security.authentication import Principal, require
from megooarti.system.settings_store import get_setting, set_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class AnonymousAccess(BaseModel):
    enabled: bool


class SettingsOut(BaseModel):
    base_url: str | None
    anonymous_access: AnonymousAccess


class BaseUrl(BaseModel):
    base_url: str | None

    @field_validator("base_url")
    @classmethod
    def _http_url_without_trailing_slash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an http or https URL")
        if parts.query or parts.fragment:
            raise ValueError("must not contain a query or a fragment")
        return value.rstrip("/")


async def _current(db: AsyncSession) -> SettingsOut:
    return SettingsOut(
        base_url=await get_setting(db, "base_url"),
        anonymous_access=AnonymousAccess(**await get_setting(db, "anonymous_access")),
    )


@router.get("", response_model=SettingsOut)
async def read_settings(
    _: Principal = Depends(require("admin:settings:read")),
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    return await _current(db)


@router.put("/base-url", response_model=SettingsOut)
async def set_base_url(
    body: BaseUrl,
    principal: Principal = Depends(require("admin:settings:write")),
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    await set_setting(db, "base_url", body.base_url)
    result = await _current(db)
    await db.commit()
    log.info("setting_changed", setting="base_url", by=principal.user.username)
    return result


@router.put("/anonymous-access", response_model=SettingsOut)
async def set_anonymous_access(
    body: AnonymousAccess,
    principal: Principal = Depends(require("admin:settings:write")),
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    await set_setting(db, "anonymous_access", {"enabled": body.enabled})
    result = await _current(db)
    await db.commit()
    log.info(
        "setting_changed",
        setting="anonymous_access",
        enabled=body.enabled,
        by=principal.user.username,
    )
    return result
```

In `backend/src/megooarti/main.py`, add the import `from megooarti.system.settings_api import router as settings_router` and include it after the roles router:

```python
    app.include_router(settings_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_settings_api.py -q`
Expected: 9 passed.

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
git commit -m "feat(system): add settings API for base URL and anonymous access"
```

---

### Task 13: First start, container and documentation

**Files:**
- Create: `backend/src/megooarti/security/bootstrap.py`
- Modify: `backend/src/megooarti/main.py` (replace the whole file)
- Modify: `backend/src/megooarti/security/api/me.py`
- Modify: `backend/src/megooarti/security/api/users.py`
- Modify: `backend/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `backend/.env.example`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `backend/tests/test_container.py`
- Test: `backend/tests/security/test_bootstrap.py`

**Interfaces:**
- Consumes: `current_revision`, `hash_password`, `Settings.data_dir`, `app.state.sessionmaker`, `app.state.head_revision`.
- Produces, in `megooarti.security.bootstrap`:
  - `password_file(settings) -> Path` — `<data_dir>/admin.password`
  - `ensure_initial_admin_password(sessionmaker, settings, head_revision) -> None`
  - `discard_initial_password(settings, user) -> None` — deletes the file when `user` is the built-in `admin`
- The application runs `ensure_initial_admin_password` at start-up and retries in the background if the database was not reachable.

- [ ] **Step 1: Write the failing tests**

`backend/tests/security/test_bootstrap.py`:

```python
import structlog

from megooarti.config import Settings
from megooarti.main import create_app
from megooarti.security.bootstrap import password_file
from tests.accounts import sign_in
from tests.clients import client_for

NEW_PASSWORD = "a brand new password"


def generated_password(settings: Settings) -> str:
    return password_file(settings).read_text(encoding="utf-8").strip()


async def test_first_start_gives_the_administrator_a_password_to_change(client, settings):
    password = generated_password(settings)

    signed_in = await sign_in(client, "admin", password)

    assert len(password) >= 20
    assert signed_in["must_change_password"] is True
    assert signed_in["permissions"] == ["*"]


async def test_a_second_start_changes_nothing(app, settings):
    async with client_for(app):
        first = generated_password(settings)

    async with client_for(app) as client:
        assert generated_password(settings) == first
        await sign_in(client, "admin", first)


async def test_changing_the_password_removes_the_file(client, settings):
    password = generated_password(settings)
    await sign_in(client, "admin", password)

    response = await client.put(
        "/api/v1/me/password",
        json={"current_password": password, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 204
    assert not password_file(settings).exists()


async def test_start_up_survives_a_data_directory_it_cannot_write(
    settings, sessionmaker, tmp_path
):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is expected", encoding="utf-8")
    app = create_app(settings.model_copy(update={"data_dir": blocker / "data"}))
    app.state.sessionmaker = sessionmaker

    with structlog.testing.capture_logs() as logs:
        async with client_for(app) as client:
            (entry,) = [log for log in logs if log["event"] == "initial_admin_password"]
            assert entry["file"] is None
            await sign_in(client, "admin", entry["password"])


async def test_start_up_skips_the_step_while_the_schema_is_behind(empty_database, tmp_path):
    settings = Settings(_env_file=None, database_url=empty_database, data_dir=tmp_path)

    async with client_for(create_app(settings)) as client:
        assert (await client.get("/api/v1/status/live")).status_code == 200

    assert not password_file(settings).exists()
```

Add to `backend/tests/test_container.py`, with `import urllib.error` at the top:

```python
DATA_FILE = "/var/lib/megooarti/admin.password"


def call(method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    """A JSON request to the published backend port: (status, headers, body)."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1{path}",
        method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, response.headers, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, error.headers, json.loads(error.read() or b"null")


@pytest.mark.docker
def test_the_first_start_administrator_can_sign_in_and_change_the_password(stack):
    password = compose("exec", "-T", "backend", "cat", DATA_FILE).stdout.strip()
    assert password

    status, headers, session = call(
        "POST", "/auth/login", {"username": "admin", "password": password}
    )
    assert status == 200
    assert session["must_change_password"] is True
    credentials = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }

    status, _, _ = call(
        "PUT",
        "/me/password",
        {"current_password": password, "new_password": "a brand new password"},
        credentials,
    )
    assert status == 204

    status, _, listed = call("GET", "/users", headers=credentials)
    assert status == 200
    assert {user["username"] for user in listed["items"]} == {"admin", "anonymous"}
    still_there = compose("exec", "-T", "backend", "test", "-e", DATA_FILE, check=False)
    assert still_there.returncode != 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/security/test_bootstrap.py -q`
Expected: collection error, `No module named 'megooarti.security.bootstrap'`.

- [ ] **Step 3: Implement the first-start step**

`backend/src/megooarti/security/bootstrap.py`:

```python
"""First start: give the built-in administrator a random password."""

import asyncio
import os
import secrets
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.config import Settings
from megooarti.db.schema import current_revision
from megooarti.security.models import User
from megooarti.security.passwords import hash_password

log = structlog.get_logger(__name__)

_FILE_NAME = "admin.password"


def password_file(settings: Settings) -> Path:
    return settings.data_dir / _FILE_NAME


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content + "\n")


async def ensure_initial_admin_password(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, head_revision: str
) -> None:
    """Set a random password for `admin` if it has none. Safe to call on every start."""
    async with sessionmaker() as db:
        if await current_revision(await db.connection()) != head_revision:
            log.warning("initial_admin_password_skipped", reason="the schema is not at head")
            return
        # The row lock makes several containers starting together take turns here.
        admin = await db.scalar(
            select(User)
            .where(User.username == "admin", User.builtin.is_(True))
            .with_for_update()
        )
        if admin is None or admin.password_hash is not None:
            return

        password = secrets.token_urlsafe(18)
        admin.password_hash = await asyncio.to_thread(hash_password, password)
        admin.must_change_password = True
        path = password_file(settings)
        written: str | None = str(path)
        try:
            _write_private(path, password)
        except OSError as error:
            written = None
            log.warning(
                "initial_admin_password_file_not_written",
                file=str(path),
                error=type(error).__name__,
            )
        await db.commit()
        # SEC-2 requires the password in the start-up log. It must be changed at first
        # sign-in, after which this line is useless to a reader.
        log.warning("initial_admin_password", username="admin", password=password, file=written)


def discard_initial_password(settings: Settings, user: User) -> None:
    """Remove the first-start password file once the administrator has a new password."""
    if not (user.builtin and user.username == "admin"):
        return
    try:
        password_file(settings).unlink(missing_ok=True)
    except OSError as error:
        log.warning("initial_admin_password_file_not_removed", error=type(error).__name__)
```

- [ ] **Step 4: Run it at start-up and discard the file on a password change**

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
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.errors import ERROR_RESPONSES, UnhandledErrorMiddleware, register_error_handlers
from megooarti.request_id import RequestIdMiddleware
from megooarti.security.api import auth as auth_api
from megooarti.security.api import me as me_api
from megooarti.security.api import roles as roles_api
from megooarti.security.api import users as users_api
from megooarti.security.bootstrap import ensure_initial_admin_password
from megooarti.system.settings_api import router as settings_router
from megooarti.system.status import router as status_router

log = structlog.get_logger(__name__)

API_PREFIX = "/api/v1"
_FIRST_START_RETRY_SECONDS = 5


async def _first_start(app: FastAPI) -> None:
    # Read app.state at call time: tests replace the sessionmaker after create_app.
    await ensure_initial_admin_password(
        app.state.sessionmaker, app.state.settings, app.state.head_revision
    )


async def _first_start_when_possible(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(_FIRST_START_RETRY_SECONDS)
        try:
            await _first_start(app)
            return
        except Exception as error:  # the database is still not reachable
            log.warning("initial_admin_password_deferred", error=type(error).__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    retry: asyncio.Task[None] | None = None
    try:
        await _first_start(app)
    except Exception as error:  # usually: the database is not reachable yet
        log.warning("initial_admin_password_deferred", error=type(error).__name__)
        retry = asyncio.create_task(_first_start_when_possible(app))
    yield
    if retry is not None:
        retry.cancel()
        with suppress(asyncio.CancelledError):
            await retry
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
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    app.include_router(auth_api.router, prefix=API_PREFIX)
    app.include_router(me_api.router, prefix=API_PREFIX)
    app.include_router(users_api.router, prefix=API_PREFIX)
    app.include_router(roles_api.router, prefix=API_PREFIX)
    app.include_router(settings_router, prefix=API_PREFIX)

    # Middleware added later wraps middleware added earlier. Keep UnhandledErrorMiddleware
    # first, so its 500 response passes through every other middleware, and keep
    # RequestIdMiddleware last, so everything else runs with a request ID.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
```

In `backend/src/megooarti/security/api/me.py`, add the import `from megooarti.security.bootstrap import discard_initial_password` and, in `change_password`, add this line directly after `await db.commit()`:

```python
    discard_initial_password(request.app.state.settings, user)
```

In `backend/src/megooarti/security/api/users.py`, add the imports `from fastapi import Request` (extend the existing `fastapi` import) and `from megooarti.security.bootstrap import discard_initial_password`, add the parameter `request: Request,` to `reset_password` directly after `body: PasswordReset,`, and add this line directly after its `await db.commit()`:

```python
    discard_initial_password(request.app.state.settings, user)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/security/test_bootstrap.py -q`
Expected: 5 passed.

Run in `backend/`: `uv run pytest -q`
Expected: no failures. The two readiness tests that use an unreachable database now also exercise the deferred first-start path.

- [ ] **Step 6: Give the container a data directory**

In `backend/Dockerfile`, replace the last `RUN` instruction with:

```dockerfile
RUN uv sync --frozen --no-dev \
    && chmod 0755 docker-entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home megooarti \
    && mkdir -p /var/lib/megooarti \
    && chown megooarti /var/lib/megooarti

VOLUME /var/lib/megooarti
```

In `docker-compose.yml`, add to the `backend` service, after its `ports:` block:

```yaml
    volumes:
      - backend-data:/var/lib/megooarti
```

and add `backend-data:` under the top-level `volumes:` key, next to `db-data:`.

Append to `backend/.env.example`:

```dotenv
MEGOOARTI_DATA_DIR=./data
```

Append to `.gitignore`:

```gitignore
backend/data/
```

- [ ] **Step 7: Run the container tests**

Run in `backend/`: `uv run pytest -m docker -q`
Expected: 6 passed.

- [ ] **Step 8: Document it**

In `README.md`, add these rows to the table in the **Configuration** section, after the `MEGOOARTI_SHUTDOWN_GRACE_SECONDS` row:

```markdown
| `MEGOOARTI_DATA_DIR` | `/var/lib/megooarti` | Directory for files MegooArti writes. Mount a volume here |
| `MEGOOARTI_SESSION_IDLE_SECONDS` | `3600` | A UI session ends after this long without a request |
| `MEGOOARTI_SESSION_ABSOLUTE_SECONDS` | `43200` | A UI session ends this long after sign-in, whatever the activity |
| `MEGOOARTI_SESSION_COOKIE_SECURE` | `true` | Set `false` only when serving plain HTTP on a host other than `localhost` |
| `MEGOOARTI_LOGIN_MAX_FAILURES` | `5` | Failed sign-ins allowed per username and per client address in one window |
| `MEGOOARTI_LOGIN_FAILURE_WINDOW_SECONDS` | `900` | Length of that window |
```

and add this section before **Health endpoints**:

````markdown
## First sign-in

On first start MegooArti creates the `admin` account with a random password, writes it
to `admin.password` in the data directory, and logs it once:

```bash
docker compose exec backend cat /var/lib/megooarti/admin.password
```

Sign in with it; you must then choose a new password, after which the file is deleted.

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<the generated password>"}' \
  http://localhost:8000/api/v1/auth/login
```

The response contains a `csrf_token`. Requests that use the session cookie and change
anything must send it in an `X-CSRF-Token` header.

## Access control

- **Roles** hold permission patterns such as `admin:users:*` or
  `repository:maven:releases:read`. `*` matches one segment, and a pattern shorter than
  the permission grants everything beneath it, so `repository:maven` covers every Maven
  repository. Roles can contain other roles.
- **Personal API tokens** (`mga_…`) are created under `/api/v1/me/tokens` while signed
  in with a password. Use one as a bearer token, or as the password in HTTP Basic. A
  token can be limited to a list of patterns and can expire.
- **Anonymous access** is off by default. When turned on under `/api/v1/settings`,
  requests without credentials act as the built-in `anonymous` user; change what they
  may do by editing that user's roles.
- Five failed sign-ins for one username, or from one address, within 15 minutes block
  further attempts until the window ends.

The full API is described at `/api/docs`.
````

- [ ] **Step 9: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest -q
```

Expected: no ruff errors; no test failures.

Run in the repository root:

```bash
git add .gitignore README.md docker-compose.yml backend
git commit -m "feat(security): create the administrator password on first start"
```
