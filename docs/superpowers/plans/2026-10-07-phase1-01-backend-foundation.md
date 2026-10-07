# Backend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI backend that starts from `docker compose up`, migrates its PostgreSQL schema with Alembic before the app runs, and exposes health endpoints, structured logs and one error format — the base every later MegooArti plan builds on.

**Architecture:** One Python package, `megooarti`, under `backend/src`. An app factory (`create_app`) wires a pure-ASGI request-ID middleware, error handlers and routers. Alembic migrations live inside the package and are the only thing that changes the schema; the image's entrypoint waits for the database, runs `alembic upgrade head` under a PostgreSQL advisory lock, then `exec`s the app.

**Tech Stack:** Python 3.13, uv, FastAPI, uvicorn, pydantic-settings, SQLAlchemy 2 (async) with asyncpg, Alembic, structlog, pytest + pytest-asyncio + httpx, ruff, Docker Compose, PostgreSQL 17.

**Spec:** [docs/BRD.md](../../BRD.md). This plan implements TC-1, TC-3, TC-4 (backend and database only), MIG-1 to MIG-11, SYS-2 (database checks), API-2, API-5 (error format), NFR-8, NFR-10, NFR-13, NFR-14, NFR-15 and NFR-17.

## Phase 1 plan series

BRD Phase 1 covers several independent subsystems, so it is split into one plan per subsystem. Each produces working, testable software. This document is plan 1. The BRD does not define data models or protocols in detail, so plans 2 onward each need a short technical design before their plan is written.

| # | Plan | Main BRD requirements |
| --- | --- | --- |
| 1 | **Backend foundation (this plan)** | MIG-1..11, SYS-2, API-2, API-5, NFR-8/10/13/14/15/17 |
| 2 | Identity and access: users, roles, privileges, sessions, API tokens, settings store | SEC-1..10, SEC-19, SYS-1, API-3, NFR-6, NFR-9 |
| 3 | Storage and repository core, format interface, Raw format | BLB-1/2/4/6/7, REP-1..13, CMP-1, FMT-8, FMT-23, NFR-2/3/5/7/11 |
| 4 | Maven format | FMT-1 |
| 5 | npm format | FMT-2 |
| 6 | PyPI format | FMT-3 |
| 7 | Docker format | FMT-4, FMT-5, FMT-7, TSK-5 |
| 8 | Browse, search, upload and delete API | CMP-2..9, API-4, SYS-4 |
| 9 | Frontend foundation: Next.js shell, design tokens, cyberpunk theme, sign-in | UI-1..15 |
| 10 | Frontend features: browse, search, upload, administration screens | UI-1, UI-2, UI-5 |
| 11 | Release readiness: client compatibility suite, backup guide, full Compose stack, docs | NFR-1, NFR-12, NFR-18, TC-4 |

## Global Constraints

- Python `>=3.13`. Dependencies are managed with uv; `backend/uv.lock` is committed.
- PostgreSQL is the only database (TC-3). The only driver is asyncpg.
- The schema is changed only by Alembic migrations (MIG-1). Never call `Base.metadata.create_all` outside a test helper — and this plan has no such helper.
- Every migration has a working `downgrade()` (MIG-10). The history has exactly one head (MIG-9) and is never rewritten after a release (MIG-11).
- Every deployment setting is an environment variable prefixed `MEGOOARTI_` and is listed in `README.md` (NFR-15).
- Logs are JSON on standard output and carry `request_id` during a request (NFR-14).
- Every API route is under `/api/v1`. Every error response has the shape `{"error": {"code", "message", "details", "request_id"}}` (API-5).
- The container runs as a non-root user (NFR-10).
- Shell scripts, Dockerfiles, Python and YAML are stored with LF line endings. The development machine is Windows; a CRLF entrypoint script will not start in the container.
- Python lines are at most 100 characters. `uv run ruff check .` and `uv run ruff format --check .` must pass before each commit.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker compose` commands in the repository root.

## Review Focus

Failure modes the BRD implies but does not spell out, most likely first. Each has a test in the task named.

1. **The entrypoint script is saved with CRLF line endings on Windows.** The container should still start. Guard: `.gitattributes` plus `test_entrypoint_has_unix_line_endings` (Task 7).
2. **The database URL is pasted as `postgres://…` or `postgresql://…`, is missing, or is not PostgreSQL.** The first two forms should work; the others should fail at start with a message naming `MEGOOARTI_DATABASE_URL` and never echoing the password (Task 1).
3. **The database is not reachable when the container starts.** The entrypoint should wait up to the timeout, then exit non-zero without starting the app (Task 7).
4. **Several containers start at the same moment.** One runs the migration; the others wait and then find nothing to do (Task 4).
5. **The schema is older than the code** (migrations disabled, or a failed deploy). Readiness should report 503 with `schema: out_of_date`, not 200 followed by failing requests (Task 5).

---

### Task 1: Project skeleton and configuration

**Files:**
- Create: `.gitattributes`
- Create: `.gitignore`
- Create: `backend/pyproject.toml`
- Create: `backend/.env.example`
- Create: `backend/src/megooarti/__init__.py`
- Create: `backend/src/megooarti/config.py`
- Create: `backend/tests/__init__.py` (empty)
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `megooarti.__version__: str`
  - `megooarti.config.Settings` with fields `database_url: str` (always normalised to `postgresql+asyncpg://…`), `log_level: Literal["DEBUG","INFO","WARNING","ERROR","CRITICAL"]`, `host: str`, `port: int`, `forwarded_allow_ips: str`, `shutdown_grace_seconds: int`, `db_wait_timeout_seconds: float`
  - `megooarti.config.ConfigurationError(RuntimeError)`
  - `megooarti.config.load_settings() -> Settings` (raises `ConfigurationError`)
  - `megooarti.config.get_settings() -> Settings` (cached; `get_settings.cache_clear()` resets it)
  - In tests, build settings with `Settings(_env_file=None, database_url=...)` so a developer's `.env` file is ignored.

- [ ] **Step 1: Create the repository housekeeping files**

`.gitattributes`:

```gitattributes
* text=auto
*.sh text eol=lf
*.py text eol=lf
*.mako text eol=lf
*.ini text eol=lf
*.toml text eol=lf
*.yml text eol=lf
*.md text eol=lf
Dockerfile text eol=lf
```

`.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
.env
requirements.txt
node_modules/
.next/
```

- [ ] **Step 2: Create the Python project**

`backend/pyproject.toml`:

```toml
[project]
name = "megooarti"
version = "0.1.0"
description = "MegooArti repository and artifact manager (backend)"
requires-python = ">=3.13"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/megooarti"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = ["docker: builds and runs the container image; needs a Docker daemon"]
addopts = "-m 'not docker'"

[tool.ruff]
line-length = 100
target-version = "py313"
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.ruff.lint.isort]
known-first-party = ["megooarti", "tests"]
```

`backend/src/megooarti/__init__.py`:

```python
"""MegooArti: a repository and artifact proxy and manager."""

__version__ = "0.1.0"
```

`backend/.env.example`:

```dotenv
# Copy to .env for local development. Docker Compose sets these itself.
MEGOOARTI_DATABASE_URL=postgresql://megooarti:megooarti@localhost:5432/megooarti
MEGOOARTI_LOG_LEVEL=INFO
```

Create `backend/tests/__init__.py` as an empty file.

- [ ] **Step 3: Install dependencies**

Run in `backend/`:

```bash
uv add pydantic-settings
uv add --dev pytest pytest-asyncio httpx ruff
```

Expected: `backend/.venv/` and `backend/uv.lock` are created and `pyproject.toml` gains a `dependencies` entry and a `[dependency-groups]` table.

- [ ] **Step 4: Write the failing tests**

`backend/tests/conftest.py`:

```python
import pytest

from megooarti.config import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

`backend/tests/test_config.py`:

```python
import pytest
from pydantic import ValidationError

from megooarti.config import ConfigurationError, Settings, get_settings, load_settings

VALID_URL = "postgresql://megooarti:s3cret@db:5432/megooarti"


@pytest.mark.parametrize(
    "given",
    [
        "postgres://u:p@db:5432/m",
        "postgresql://u:p@db:5432/m",
        "postgresql+asyncpg://u:p@db:5432/m",
    ],
)
def test_database_url_is_normalised_to_the_asyncpg_driver(given):
    settings = Settings(_env_file=None, database_url=given)
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/m"


@pytest.mark.parametrize("given", ["mysql://u:hunter2@db/m", "not a url", ""])
def test_non_postgres_url_is_rejected_without_echoing_it(given):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, database_url=given)
    assert "database_url" in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_defaults():
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert settings.log_level == "INFO"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.forwarded_allow_ips == "127.0.0.1"
    assert settings.shutdown_grace_seconds == 30
    assert settings.db_wait_timeout_seconds == 60


def test_values_come_from_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("MEGOOARTI_PORT", "9000")
    monkeypatch.setenv("MEGOOARTI_LOG_LEVEL", "debug")
    settings = Settings(_env_file=None)
    assert settings.port == 9000
    assert settings.log_level == "DEBUG"


def test_unknown_log_level_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=VALID_URL, log_level="chatty")


def test_load_settings_names_the_missing_environment_variable(monkeypatch, tmp_path):
    monkeypatch.delenv("MEGOOARTI_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # a directory with no .env file
    with pytest.raises(ConfigurationError, match="MEGOOARTI_DATABASE_URL"):
        load_settings()


def test_load_settings_never_echoes_a_rejected_url(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "mysql://u:hunter2@db/m")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError) as caught:
        load_settings()
    assert "MEGOOARTI_DATABASE_URL" in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_get_settings_is_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.chdir(tmp_path)
    assert get_settings() is get_settings()
```

- [ ] **Step 5: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_config.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'megooarti.config'`.

- [ ] **Step 6: Implement the configuration module**

`backend/src/megooarti/config.py`:

```python
"""Deployment configuration, read from MEGOOARTI_* environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "MEGOOARTI_"
_POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+asyncpg"}


class ConfigurationError(RuntimeError):
    """The environment does not describe a valid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,  # the database URL contains a password
    )

    database_url: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"
    shutdown_grace_seconds: int = 30
    db_wait_timeout_seconds: float = 60

    @field_validator("database_url")
    @classmethod
    def _use_the_asyncpg_driver(cls, value: str) -> str:
        scheme, separator, rest = value.partition("://")
        if not separator or scheme not in _POSTGRES_SCHEMES:
            raise ValueError(
                "must be a PostgreSQL URL such as postgresql://user:password@host:5432/dbname"
            )
        return f"postgresql+asyncpg://{rest}"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_case_the_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


def load_settings() -> Settings:
    """Read settings from the environment, reporting problems by variable name."""
    try:
        return Settings()
    except ValidationError as error:
        problems = "; ".join(
            f"{ENV_PREFIX}{'_'.join(str(part) for part in item['loc']).upper()}: {item['msg']}"
            for item in error.errors()
        )
        raise ConfigurationError(f"invalid configuration: {problems}") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_config.py -v`
Expected: 12 passed.

- [ ] **Step 8: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: ruff reports no remaining errors; 12 passed.

Run in the repository root:

```bash
git add .gitattributes .gitignore backend
git commit -m "feat(backend): add project skeleton and environment configuration"
```

---

### Task 2: Structured logging and request IDs

**Files:**
- Create: `backend/src/megooarti/log.py`
- Create: `backend/src/megooarti/request_id.py`
- Test: `backend/tests/test_log.py`
- Test: `backend/tests/test_request_id.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `megooarti.log.configure_logging(level: str = "INFO") -> None` — routes structlog and standard-library logging to JSON lines on standard output.
  - `megooarti.request_id.HEADER = "X-Request-ID"`
  - `megooarti.request_id.RequestIdMiddleware(app)` — pure ASGI middleware. For each HTTP request it sets `request.state.request_id: str`, binds `request_id` into structlog's context variables for the duration of the request, and sets the `X-Request-ID` response header.
  - Module loggers are created with `structlog.get_logger(__name__)`.

- [ ] **Step 1: Install dependencies**

Run in `backend/`: `uv add structlog fastapi`

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_log.py`:

```python
import json
import logging

import pytest
import structlog

from megooarti.log import configure_logging


@pytest.fixture
def isolated_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()


def read_lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_structlog_events_are_json_lines_with_bound_context(isolated_logging, capsys):
    configure_logging("INFO")
    structlog.contextvars.bind_contextvars(request_id="abc123")

    structlog.get_logger("megooarti.test").info("artifact_stored", size=42)

    (line,) = read_lines(capsys)
    assert line["event"] == "artifact_stored"
    assert line["size"] == 42
    assert line["level"] == "info"
    assert line["logger"] == "megooarti.test"
    assert line["request_id"] == "abc123"
    assert "timestamp" in line


def test_standard_library_logs_use_the_same_format(isolated_logging, capsys):
    configure_logging("INFO")
    structlog.contextvars.bind_contextvars(request_id="abc123")

    logging.getLogger("thirdparty").warning("plain %s", "message")

    (line,) = read_lines(capsys)
    assert line["event"] == "plain message"
    assert line["level"] == "warning"
    assert line["logger"] == "thirdparty"
    assert line["request_id"] == "abc123"


def test_exceptions_are_rendered_inside_the_json_line(isolated_logging, capsys):
    configure_logging("INFO")

    try:
        1 / 0  # noqa: B018
    except ZeroDivisionError:
        logging.getLogger("thirdparty").exception("calculation failed")

    (line,) = read_lines(capsys)
    assert line["event"] == "calculation failed"
    assert "ZeroDivisionError" in line["exception"]


def test_level_filters_lower_severity(isolated_logging, capsys):
    configure_logging("WARNING")

    structlog.get_logger("megooarti.test").info("ignored")
    structlog.get_logger("megooarti.test").warning("kept")

    assert [line["event"] for line in read_lines(capsys)] == ["kept"]
```

`backend/tests/test_request_id.py`:

```python
import re

import pytest
import structlog
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response

from megooarti.request_id import RequestIdMiddleware

GENERATED = re.compile(r"[0-9a-f]{32}")


def build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def echo(request: Request) -> dict[str, str | None]:
        return {
            "state": request.state.request_id,
            "log_context": structlog.contextvars.get_contextvars().get("request_id"),
        }

    return app


async def get_echo(headers: dict[str, str] | None = None) -> Response:
    transport = ASGITransport(app=build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/echo", headers=headers)


async def test_generates_an_id_and_exposes_it_to_handlers_logs_and_the_client():
    response = await get_echo()
    request_id = response.headers["X-Request-ID"]
    assert GENERATED.fullmatch(request_id)
    assert response.json() == {"state": request_id, "log_context": request_id}


async def test_keeps_a_well_formed_id_sent_by_the_client():
    response = await get_echo({"X-Request-ID": "build-1234.a_b"})
    assert response.headers["X-Request-ID"] == "build-1234.a_b"
    assert response.json()["state"] == "build-1234.a_b"


@pytest.mark.parametrize("hostile", ["has space", "x" * 65, '{"forged":true}', "semi;colon"])
async def test_replaces_a_malformed_id_sent_by_the_client(hostile):
    response = await get_echo({"X-Request-ID": hostile})
    assert GENERATED.fullmatch(response.headers["X-Request-ID"])


async def test_log_context_is_cleared_after_the_request():
    await get_echo()
    assert "request_id" not in structlog.contextvars.get_contextvars()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_log.py tests/test_request_id.py -v`
Expected: collection errors, `No module named 'megooarti.log'` and `No module named 'megooarti.request_id'`.

- [ ] **Step 4: Implement logging**

`backend/src/megooarti/log.py`:

```python
"""JSON logging on standard output for structlog and the standard library."""

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
```

- [ ] **Step 5: Implement the request-ID middleware**

This is a pure ASGI middleware, not `BaseHTTPMiddleware`: later plans stream multi-gigabyte request and response bodies, which `BaseHTTPMiddleware` handles poorly.

`backend/src/megooarti/request_id.py`:

```python
"""Give every HTTP request an ID that appears in logs, handlers and the response."""

import re
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Request-ID"
_WELL_FORMED = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = Headers(scope=scope).get(HEADER, "")
        request_id = supplied if _WELL_FORMED.fullmatch(supplied) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            await self.app(scope, receive, send_with_header)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_log.py tests/test_request_id.py -v`
Expected: 11 passed.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: no ruff errors; 23 passed.

Run in the repository root:

```bash
git add backend
git commit -m "feat(backend): add JSON logging and request ID middleware"
```

---

### Task 3: Application factory, error format and liveness

**Files:**
- Create: `backend/src/megooarti/errors.py`
- Create: `backend/src/megooarti/main.py`
- Create: `backend/src/megooarti/system/__init__.py` (empty)
- Create: `backend/src/megooarti/system/status.py`
- Create: `backend/tests/clients.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_app.py`
- Test: `backend/tests/test_errors.py`

**Interfaces:**
- Consumes: `Settings`, `get_settings` (Task 1); `RequestIdMiddleware`, `HEADER` (Task 2).
- Produces:
  - `megooarti.main.create_app(settings: Settings | None = None) -> FastAPI`. Sets `app.state.settings`. OpenAPI is served at `/api/v1/openapi.json`, interactive docs at `/api/docs`.
  - `megooarti.errors.ApiError(status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None)` — raise it from any handler to return an error in the standard shape.
  - `megooarti.errors.register_error_handlers(app: FastAPI) -> None`
  - `megooarti.system.status.router` — `GET /status/live`; mounted by `create_app` under `/api/v1`.
  - `tests.clients.client_for(app)` — async context manager yielding an in-process `httpx.AsyncClient`.
  - pytest fixtures `settings`, `app`, `client`.

- [ ] **Step 1: Write the test support code**

`backend/tests/clients.py`:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client that calls `app` in-process.

    Unhandled exceptions come back as 500 responses, as they would over a real socket.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

Replace `backend/tests/conftest.py` with:

```python
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from megooarti.config import Settings, get_settings
from megooarti.main import create_app
from tests.clients import client_for

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"
)


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, database_url=DEFAULT_TEST_DATABASE_URL)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app) as http:
        yield http
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_app.py`:

```python
async def test_liveness(client):
    response = await client.get("/api/v1/status/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


async def test_openapi_document_is_served(client):
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "MegooArti"
    assert "/api/v1/status/live" in document["paths"]


async def test_interactive_documentation_is_served(client):
    response = await client.get("/api/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_settings_are_available_on_the_app(app, settings):
    assert app.state.settings is settings
```

`backend/tests/test_errors.py`:

```python
import pytest
from fastapi import APIRouter, FastAPI

from megooarti.errors import ApiError


@pytest.fixture
def app(app: FastAPI) -> FastAPI:
    router = APIRouter(prefix="/_test")

    @router.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    @router.get("/conflict")
    async def conflict() -> None:
        raise ApiError(409, "conflict", "A repository with this name already exists.")

    @router.get("/items/{number}")
    async def item(number: int) -> dict[str, int]:
        return {"number": number}

    app.include_router(router)
    return app


def assert_error(response, status_code: int, code: str) -> dict:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert error["request_id"] == response.headers["X-Request-ID"]
    return error


async def test_unknown_route(client):
    assert_error(await client.get("/api/v1/nope"), 404, "not_found")


async def test_wrong_method(client):
    assert_error(await client.post("/api/v1/status/live"), 405, "method_not_allowed")


async def test_api_error(client):
    error = assert_error(await client.get("/_test/conflict"), 409, "conflict")
    assert error["message"] == "A repository with this name already exists."
    assert error["details"] == []


async def test_validation_error_lists_the_offending_field(client):
    error = assert_error(await client.get("/_test/items/abc"), 422, "validation_error")
    assert [detail["field"] for detail in error["details"]] == ["path.number"]
    assert error["details"][0]["message"]


async def test_unhandled_exception_reveals_nothing_internal(client):
    response = await client.get("/_test/boom")
    error = assert_error(response, 500, "internal_error")
    assert error["message"] == "An unexpected error occurred."
    assert "secret detail" not in response.text
    assert "RuntimeError" not in response.text
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_app.py tests/test_errors.py -v`
Expected: every test errors during collection of `conftest.py` with `No module named 'megooarti.main'`.

- [ ] **Step 4: Implement the error format**

The catch-all handler for `Exception` is run by Starlette's outermost middleware, outside `RequestIdMiddleware`. That is why `error_response` sets the `X-Request-ID` header itself and why the log call passes `request_id` explicitly.

`backend/src/megooarti/errors.py`:

```python
"""One JSON shape for every error the API returns."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from megooarti.request_id import HEADER as REQUEST_ID_HEADER

log = structlog.get_logger(__name__)

_CODES_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
}


class ApiError(Exception):
    """Raise from a handler to return an error response in the standard shape."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
            "request_id": request_id,
        }
    }
    response = JSONResponse(body, status_code=status_code, headers=headers)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return error_response(
            request, error.status_code, error.code, error.message, error.details
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _CODES_BY_STATUS.get(error.status_code, "http_error")
        return error_response(
            request, error.status_code, code, str(error.detail), headers=error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        return error_response(
            request, 422, "validation_error", "The request is not valid.", details
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        log.error(
            "unhandled_exception",
            request_id=getattr(request.state, "request_id", None),
            method=request.method,
            path=request.url.path,
            exc_info=error,
        )
        return error_response(request, 500, "internal_error", "An unexpected error occurred.")
```

- [ ] **Step 5: Implement the status router and the app factory**

Create `backend/src/megooarti/system/__init__.py` as an empty file.

`backend/src/megooarti/system/status.py`:

```python
"""Unauthenticated health endpoints for load balancers and orchestrators."""

from fastapi import APIRouter

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is running and can answer HTTP requests."""
    return {"status": "ok"}
```

`backend/src/megooarti/main.py`:

```python
"""Application factory."""

from fastapi import FastAPI

from megooarti import __version__
from megooarti.config import Settings, get_settings
from megooarti.errors import register_error_handlers
from megooarti.request_id import RequestIdMiddleware
from megooarti.system.status import router as status_router

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MegooArti",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    return app
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_app.py tests/test_errors.py -v`
Expected: 9 passed.

- [ ] **Step 7: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: no ruff errors; 32 passed.

Run in the repository root:

```bash
git add backend
git commit -m "feat(backend): add app factory, standard error format and liveness endpoint"
```

---

### Task 4: Database schema management with Alembic

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/src/megooarti/alembic.ini`
- Create: `backend/src/megooarti/db/__init__.py` (empty)
- Create: `backend/src/megooarti/db/base.py`
- Create: `backend/src/megooarti/db/schema.py`
- Create: `backend/src/megooarti/models.py`
- Create: `backend/src/megooarti/system/models.py`
- Create: `backend/src/megooarti/migrations/env.py`
- Create: `backend/src/megooarti/migrations/script.py.mako`
- Create: `backend/src/megooarti/migrations/versions/0001_create_system_settings.py`
- Create: `backend/tests/databases.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `get_settings` (Task 1), `configure_logging` (Task 2).
- Produces:
  - `megooarti.db.base.Base` — the declarative base; every model inherits from it.
  - `megooarti.models` — importing it registers every model on `Base.metadata`. Each new model module must be imported there.
  - `megooarti.system.models.SystemSetting` — table `system_settings(key varchar(128) PK, value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())`.
  - `megooarti.db.schema.MIGRATION_LOCK_KEY: int`
  - `megooarti.db.schema.alembic_config(database_url: str | None = None) -> alembic.config.Config` — with no argument, migrations use `MEGOOARTI_DATABASE_URL`.
  - `megooarti.db.schema.head_revision() -> str`
  - `tests.databases.run_sql(url, *statements)`, `fetch_all(url, statement) -> list[tuple]`, `ensure_database(url)`, `reset_schema(url)`. These call `asyncio.run`, so call them only from synchronous tests and synchronous fixtures.
  - pytest fixtures `database_url` (session; a migrated database), `empty_database` (function; a second database with an empty `public` schema).

- [ ] **Step 1: Add the development database**

`docker-compose.yml` (repository root):

```yaml
name: megooarti

services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: megooarti
      POSTGRES_PASSWORD: megooarti
      POSTGRES_DB: megooarti
    ports:
      - "${MEGOOARTI_DB_PORT:-5432}:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U megooarti -d megooarti"]
      interval: 2s
      timeout: 3s
      retries: 30

volumes:
  db-data:
```

Run in the repository root: `docker compose up --detach --wait db`
Expected: the `db` service is reported `Healthy`.

If port 5432 is already in use, set `MEGOOARTI_DB_PORT` to a free port before starting, and set `MEGOOARTI_TEST_DATABASE_URL=postgresql://megooarti:megooarti@localhost:<port>/megooarti_test` when running tests.

- [ ] **Step 2: Install dependencies**

Run in `backend/`: `uv add "sqlalchemy[asyncio]" asyncpg alembic`

- [ ] **Step 3: Write the test support code**

`backend/tests/databases.py`:

```python
"""Database helpers for tests.

Every function here calls asyncio.run, so use them only from synchronous tests and
synchronous fixtures, never from inside a running event loop.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def run_sql(url: str, *statements: str) -> None:
    """Run statements in autocommit mode on a short-lived connection."""

    async def run() -> None:
        engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                for statement in statements:
                    await connection.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def fetch_all(url: str, statement: str) -> list[tuple]:
    async def run() -> list[tuple]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text(statement))
                return [tuple(row) for row in result]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def ensure_database(url: str) -> None:
    """Create the database named in `url` if it does not exist."""
    target = make_url(url)
    maintenance = target.set(database="postgres").render_as_string(hide_password=False)
    found = fetch_all(
        maintenance, f"SELECT 1 FROM pg_database WHERE datname = '{target.database}'"
    )
    if not found:
        run_sql(maintenance, f'CREATE DATABASE "{target.database}"')


def reset_schema(url: str) -> None:
    """Remove every table, including alembic_version."""
    run_sql(url, "DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
```

Replace `backend/tests/conftest.py` with:

```python
import os
from collections.abc import AsyncIterator

import pytest
from alembic import command
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.engine import make_url

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
def settings() -> Settings:
    return Settings(_env_file=None, database_url=DEFAULT_TEST_DATABASE_URL)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app) as http:
        yield http
```

- [ ] **Step 4: Write the failing tests**

`backend/tests/test_migrations.py`:

```python
"""Migration tests. All synchronous: Alembic's env.py starts its own event loop."""

import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.db.schema import MIGRATION_LOCK_KEY, alembic_config, head_revision
from tests.databases import fetch_all

USER_TABLES = (
    "SELECT tablename FROM pg_tables "
    "WHERE schemaname = 'public' AND tablename <> 'alembic_version' ORDER BY tablename"
)


def applied_revision(url: str) -> list[tuple]:
    return fetch_all(url, "SELECT version_num FROM alembic_version")


def test_history_has_exactly_one_head():
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1
    assert head_revision() == heads[0]


def test_upgrade_from_an_empty_database_reaches_head(empty_database):
    command.upgrade(alembic_config(empty_database), "head")

    assert applied_revision(empty_database) == [(head_revision(),)]
    assert ("system_settings",) in fetch_all(empty_database, USER_TABLES)


def test_upgrade_is_a_no_op_when_already_at_head(empty_database):
    command.upgrade(alembic_config(empty_database), "head")
    command.upgrade(alembic_config(empty_database), "head")

    assert applied_revision(empty_database) == [(head_revision(),)]


def test_downgrade_to_base_removes_every_table(empty_database):
    command.upgrade(alembic_config(empty_database), "head")
    command.downgrade(alembic_config(empty_database), "base")

    assert fetch_all(empty_database, USER_TABLES) == []


def test_models_and_migrations_describe_the_same_schema(empty_database):
    config = alembic_config(empty_database)
    command.upgrade(config, "head")

    command.check(config)  # raises CommandError if autogenerate would emit operations


def test_migration_waits_while_another_process_holds_the_lock(empty_database):
    async def scenario() -> None:
        engine = create_async_engine(
            empty_database, poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as holder:
                await holder.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_KEY})"))
                migration = asyncio.create_task(
                    asyncio.to_thread(command.upgrade, alembic_config(empty_database), "head")
                )

                finished, _ = await asyncio.wait({migration}, timeout=2)
                assert not finished, "the migration ran without waiting for the lock"

                await holder.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_KEY})"))
                await asyncio.wait_for(migration, timeout=30)
        finally:
            await engine.dispose()

    asyncio.run(scenario())

    assert applied_revision(empty_database) == [(head_revision(),)]
```

- [ ] **Step 5: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_migrations.py -v`
Expected: collection error in `conftest.py`, `No module named 'megooarti.db'`.

- [ ] **Step 6: Implement the declarative base and the first model**

Create `backend/src/megooarti/db/__init__.py` as an empty file.

`backend/src/megooarti/db/base.py`:

```python
"""Declarative base shared by every model."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit names let migrations drop and alter constraints reliably.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

`backend/src/megooarti/system/models.py`:

```python
"""Instance-wide settings that administrators change at runtime."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

`backend/src/megooarti/models.py`:

```python
"""Import every model module here so that Base.metadata is complete.

Alembic's autogenerate and the model/migration drift test both rely on this module.
"""

from megooarti.system import models as _system_models  # noqa: F401
```

- [ ] **Step 7: Implement the Alembic configuration helpers**

The Alembic configuration file lives inside the package so it is found the same way in development, in tests and in the container.

`backend/src/megooarti/alembic.ini`:

```ini
[alembic]
script_location = %(here)s/migrations
file_template = %%(rev)s_%%(slug)s
```

`backend/src/megooarti/db/schema.py`:

```python
"""Helpers for the Alembic-managed schema."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# Arbitrary constant ("MEGOO" in ASCII). Every MegooArti process uses the same key,
# so only one of them migrates a given database at a time.
MIGRATION_LOCK_KEY = 0x4D45474F4F


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic configuration; `database_url` overrides MEGOOARTI_DATABASE_URL."""
    config = Config(str(ALEMBIC_INI))
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def head_revision() -> str:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one migration head, found {len(heads)}: {heads}")
    return heads[0]
```

- [ ] **Step 8: Implement the migration environment**

The lock is taken on its own autocommit connection and held while a second connection runs the migrations in a transaction. A process that had to wait for the lock reads the current revision only after it gets the lock, so it sees the first process's work and does nothing.

`backend/src/megooarti/migrations/env.py`:

```python
"""Alembic environment: run migrations online, one process at a time."""

import asyncio
import logging
import os

from alembic import context
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import megooarti.models  # noqa: F401  (registers every model on Base.metadata)
from megooarti.config import get_settings
from megooarti.db.base import Base
from megooarti.db.schema import MIGRATION_LOCK_KEY
from megooarti.log import configure_logging

target_metadata = Base.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    database_url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        locking_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
        async with locking_engine.connect() as lock_connection:
            await lock_connection.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_KEY})"))
            try:
                async with engine.connect() as connection:
                    await connection.run_sync(_run_migrations)
            finally:
                await lock_connection.execute(
                    text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_KEY})")
                )
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; migrate a live database.")

if not logging.getLogger().handlers:  # the alembic CLI; tests and the app configure their own
    configure_logging(os.environ.get("MEGOOARTI_LOG_LEVEL", "INFO"))

asyncio.run(_run_online())
```

`backend/src/megooarti/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 9: Write the first migration**

`backend/src/megooarti/migrations/versions/0001_create_system_settings.py`:

```python
"""create system_settings

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_settings")),
    )


def downgrade() -> None:
    op.drop_table("system_settings")
```

- [ ] **Step 10: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_migrations.py -v`
Expected: 6 passed. The lock test takes a little over 2 seconds.

- [ ] **Step 11: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: no ruff errors; 38 passed.

Run in the repository root:

```bash
git add docker-compose.yml backend
git commit -m "feat(backend): manage the schema with Alembic under an advisory lock"
```

---

### Task 5: Readiness endpoint

**Files:**
- Modify: `backend/src/megooarti/db/schema.py`
- Modify: `backend/src/megooarti/system/status.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `backend/tests/clients.py`
- Modify: `backend/tests/conftest.py` (the `settings` fixture only)
- Test: `backend/tests/test_readiness.py`

**Interfaces:**
- Consumes: `create_app`, `client_for`, `head_revision`, fixtures `database_url` and `empty_database`.
- Produces:
  - `megooarti.db.schema.current_revision(connection: AsyncConnection) -> str | None` — the revision recorded in the database, or `None` if it has never been migrated.
  - `app.state.engine: sqlalchemy.ext.asyncio.AsyncEngine` — the application's connection pool, disposed at shutdown. Later plans build sessions on it.
  - `app.state.head_revision: str`
  - `GET /api/v1/status/ready` → `200 {"status": "ok", "checks": {"database": "ok", "schema": "ok"}}` or `503 {"status": "unavailable", "checks": {...}}` where `database` is `ok` or `unreachable` and `schema` is `ok`, `out_of_date` or `unknown`.
  - `client_for(app)` now disposes `app.state.engine` on exit.
  - The `settings` fixture now points at the migrated `database_url`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_readiness.py`:

```python
from megooarti.config import Settings
from megooarti.main import create_app
from tests.clients import client_for

READY = "/api/v1/status/ready"


async def test_ready_when_the_database_is_reachable_and_migrated(client):
    response = await client.get(READY)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "schema": "ok"}}


async def test_not_ready_when_the_schema_is_behind_the_code(empty_database):
    app = create_app(Settings(_env_file=None, database_url=empty_database))

    async with client_for(app) as client:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "ok", "schema": "out_of_date"},
    }


async def test_not_ready_when_the_database_is_unreachable():
    nowhere = "postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/megooarti"
    app = create_app(Settings(_env_file=None, database_url=nowhere))

    async with client_for(app) as client:
        response = await client.get(READY)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "unreachable", "schema": "unknown"},
    }


async def test_liveness_does_not_depend_on_the_database():
    nowhere = "postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/megooarti"
    app = create_app(Settings(_env_file=None, database_url=nowhere))

    async with client_for(app) as client:
        response = await client.get("/api/v1/status/live")

    assert response.status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_readiness.py -v`
Expected: the three readiness tests fail with `404`; the liveness test passes.

- [ ] **Step 3: Add `current_revision`**

In `backend/src/megooarti/db/schema.py`, replace the imports at the top of the file with:

```python
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
```

and add at the end of the file:

```python
async def current_revision(connection: AsyncConnection) -> str | None:
    """The revision recorded in the database, or None if it was never migrated."""
    has_table = await connection.scalar(
        text("SELECT to_regclass('alembic_version') IS NOT NULL")
    )
    if not has_table:
        return None
    return await connection.scalar(text("SELECT version_num FROM alembic_version"))
```

- [ ] **Step 4: Add the readiness endpoint**

Replace `backend/src/megooarti/system/status.py` with:

```python
"""Unauthenticated health endpoints for load balancers and orchestrators."""

import asyncio

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from megooarti.db.schema import current_revision

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/status", tags=["status"])

READINESS_TIMEOUT_SECONDS = 5


@router.get("/live")
async def live() -> dict[str, str]:
    """The process is running and can answer HTTP requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """The process can reach its database and the schema matches this version."""
    checks = {"database": "ok", "schema": "ok"}
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with request.app.state.engine.connect() as connection:
                revision = await current_revision(connection)
    except Exception as error:  # any driver, network or timeout failure means "not ready"
        log.warning("readiness_database_unreachable", error=type(error).__name__)
        checks = {"database": "unreachable", "schema": "unknown"}
    else:
        expected = request.app.state.head_revision
        if revision != expected:
            log.warning("readiness_schema_out_of_date", found=revision, expected=expected)
            checks["schema"] = "out_of_date"

    healthy = all(result == "ok" for result in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "unavailable", "checks": checks},
        status_code=200 if healthy else 503,
    )
```

- [ ] **Step 5: Give the app an engine**

Replace `backend/src/megooarti/main.py` with:

```python
"""Application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from megooarti import __version__
from megooarti.config import Settings, get_settings
from megooarti.db.schema import head_revision
from megooarti.errors import register_error_handlers
from megooarti.request_id import RequestIdMiddleware
from megooarti.system.status import router as status_router

API_PREFIX = "/api/v1"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
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
    )
    app.state.settings = settings
    # Creating the engine opens no connection; the pool connects on first use.
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.head_revision = head_revision()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(status_router, prefix=API_PREFIX)
    return app
```

- [ ] **Step 6: Update the test support code**

Replace `backend/tests/clients.py` with:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client that calls `app` in-process, closing its database pool afterwards.

    Unhandled exceptions come back as 500 responses, as they would over a real socket.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        await app.state.engine.dispose()
```

In `backend/tests/conftest.py`, replace the `settings` fixture with:

```python
@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(_env_file=None, database_url=database_url)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_readiness.py -v`
Expected: 4 passed.

- [ ] **Step 8: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: no ruff errors; 42 passed.

Run in the repository root:

```bash
git add backend
git commit -m "feat(backend): add readiness endpoint that checks database and schema revision"
```

---

### Task 6: Migration helper script

**Files:**
- Create: `backend/scripts/db.py`
- Test: `backend/tests/test_db_script.py`

**Interfaces:**
- Consumes: `alembic_config`, `head_revision` (Task 4); fixture `empty_database`; `tests.databases.fetch_all`.
- Produces: the developer command `uv run python scripts/db.py <action>` with actions `new "<message>"`, `upgrade [revision]` (default `head`), `downgrade [revision]` (default `-1`), `current`, `history`, `check`. Revisions it creates are numbered `0002`, `0003`, … and saved as `<number>_<slug>.py`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_db_script.py`:

```python
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from alembic.script import ScriptDirectory

from megooarti.db.schema import alembic_config, head_revision
from tests.databases import fetch_all

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_DIR / "scripts" / "db.py"
USER_TABLES = (
    "SELECT tablename FROM pg_tables "
    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
)


def load_script():
    spec = importlib.util.spec_from_file_location("megooarti_db_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=BACKEND_DIR,
        env={**os.environ, "MEGOOARTI_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def fake_history(*revisions: str) -> SimpleNamespace:
    return SimpleNamespace(
        walk_revisions=lambda: [SimpleNamespace(revision=revision) for revision in revisions]
    )


def test_first_revision_number():
    assert load_script().next_revision_id(fake_history()) == "0001"


def test_next_revision_number_follows_the_highest_and_ignores_non_numeric_ids():
    history = fake_history("0001", "0007", "a1b2c3")
    assert load_script().next_revision_id(history) == "0008"


def test_next_revision_number_for_the_real_history():
    history = ScriptDirectory.from_config(alembic_config())
    expected = f"{int(head_revision()) + 1:04d}"
    assert load_script().next_revision_id(history) == expected


def test_upgrade_then_current_reports_head(empty_database):
    upgraded = run_script(empty_database, "upgrade")
    assert upgraded.returncode == 0, upgraded.stderr

    current = run_script(empty_database, "current")
    assert current.returncode == 0, current.stderr
    assert f"{head_revision()} (head)" in current.stdout


def test_check_passes_at_head(empty_database):
    run_script(empty_database, "upgrade")

    checked = run_script(empty_database, "check")
    assert checked.returncode == 0, checked.stderr


def test_downgrade_to_base_removes_every_table(empty_database):
    run_script(empty_database, "upgrade")

    downgraded = run_script(empty_database, "downgrade", "base")
    assert downgraded.returncode == 0, downgraded.stderr
    assert fetch_all(empty_database, USER_TABLES) == []


def test_history_lists_the_first_revision(empty_database):
    history = run_script(empty_database, "history")
    assert history.returncode == 0, history.stderr
    assert "0001" in history.stdout


def test_unknown_action_is_a_usage_error(empty_database):
    result = run_script(empty_database, "explode")
    assert result.returncode == 2
    assert "usage:" in result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_db_script.py -v`
Expected: every test fails; the first three with `FileNotFoundError` for `scripts/db.py`, the rest with a non-zero return code.

- [ ] **Step 3: Implement the script**

`backend/scripts/db.py`:

```python
"""Database migration helper for developers.

Run from the backend/ directory, with MEGOOARTI_DATABASE_URL set or a .env file present:

    uv run python scripts/db.py new "add users table"   create the next revision from the models
    uv run python scripts/db.py upgrade [revision]      apply migrations (default: head)
    uv run python scripts/db.py downgrade [revision]    revert migrations (default: -1, one step)
    uv run python scripts/db.py current                 show the revision the database is at
    uv run python scripts/db.py history                 list every revision
    uv run python scripts/db.py check                   fail if models and migrations differ
"""

import argparse

from alembic import command
from alembic.script import ScriptDirectory

from megooarti.db.schema import alembic_config


def next_revision_id(history: ScriptDirectory) -> str:
    """The next sequential revision number, zero-padded to four digits."""
    numbers = [
        int(script.revision) for script in history.walk_revisions() if script.revision.isdigit()
    ]
    return f"{max(numbers, default=0) + 1:04d}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("new").add_argument("message")
    actions.add_parser("upgrade").add_argument("revision", nargs="?", default="head")
    actions.add_parser("downgrade").add_argument("revision", nargs="?", default="-1")
    actions.add_parser("current")
    actions.add_parser("history")
    actions.add_parser("check")
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    config = alembic_config()

    if arguments.action == "new":
        revision_id = next_revision_id(ScriptDirectory.from_config(config))
        command.revision(
            config, message=arguments.message, autogenerate=True, rev_id=revision_id
        )
    elif arguments.action == "upgrade":
        command.upgrade(config, arguments.revision)
    elif arguments.action == "downgrade":
        command.downgrade(config, arguments.revision)
    elif arguments.action == "current":
        command.current(config)
    elif arguments.action == "history":
        command.history(config)
    elif arguments.action == "check":
        command.check(config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_db_script.py -v`
Expected: 8 passed.

- [ ] **Step 5: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: no ruff errors; 50 passed.

Run in the repository root:

```bash
git add backend
git commit -m "feat(backend): add migration helper script"
```

---

### Task 7: Container image with migrate-then-start entrypoint

**Files:**
- Create: `backend/src/megooarti/db/wait.py`
- Create: `backend/src/megooarti/__main__.py`
- Create: `backend/docker-entrypoint.sh`
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`
- Modify: `docker-compose.yml`
- Test: `backend/tests/test_wait.py`
- Test: `backend/tests/test_launcher.py`
- Test: `backend/tests/test_container.py`

**Interfaces:**
- Consumes: `get_settings`, `ConfigurationError` (Task 1); `configure_logging` (Task 2); `create_app` (Task 5); `megooarti/alembic.ini` (Task 4).
- Produces:
  - `megooarti.db.wait.wait_for_database(url: str, timeout_seconds: float, interval_seconds: float = 1.0) -> None` — raises `TimeoutError`.
  - `python -m megooarti.db.wait` — exits 0 when the database accepts connections, 1 otherwise.
  - `python -m megooarti` — configures logging and serves the app with uvicorn.
  - The `backend` Compose service, published on `${MEGOOARTI_HTTP_PORT:-8000}`.
  - Entrypoint environment variable `MEGOOARTI_RUN_MIGRATIONS` (default `true`; any other value skips waiting and migrating).

- [ ] **Step 1: Install dependencies**

Run in `backend/`: `uv add "uvicorn[standard]"`

- [ ] **Step 2: Write the failing tests for waiting and launching**

`backend/tests/test_wait.py`:

```python
import time

import pytest

from megooarti.db import wait
from megooarti.db.wait import wait_for_database

NOWHERE = "postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/megooarti"


async def test_returns_once_the_database_accepts_connections(database_url):
    await wait_for_database(database_url, timeout_seconds=10)


async def test_gives_up_after_the_timeout():
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="not reachable after 1.5s"):
        await wait_for_database(NOWHERE, timeout_seconds=1.5, interval_seconds=0.2)

    assert time.monotonic() - started < 10


async def test_keeps_trying_until_the_database_appears(monkeypatch):
    attempts = []

    async def flaky(engine) -> None:
        attempts.append(engine)
        if len(attempts) < 3:
            raise ConnectionRefusedError("not yet")

    monkeypatch.setattr(wait, "_attempt", flaky)

    await wait_for_database(NOWHERE, timeout_seconds=10, interval_seconds=0.01)

    assert len(attempts) == 3


def test_command_exits_non_zero_with_a_readable_message(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", NOWHERE)
    monkeypatch.setenv("MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS", "0.5")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        wait.main()

    assert "megooarti: database not reachable after 0.5s" in str(stopped.value)


def test_command_reports_missing_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("MEGOOARTI_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        wait.main()

    assert "MEGOOARTI_DATABASE_URL" in str(stopped.value)
```

`backend/tests/test_launcher.py`:

```python
import pytest

from megooarti import __main__ as launcher


def test_launcher_serves_the_app_factory_with_values_from_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "postgresql://u:p@db:5432/m")
    monkeypatch.setenv("MEGOOARTI_PORT", "9001")
    monkeypatch.setenv("MEGOOARTI_SHUTDOWN_GRACE_SECONDS", "7")
    monkeypatch.setenv("MEGOOARTI_FORWARDED_ALLOW_IPS", "10.0.0.1")
    monkeypatch.setenv("MEGOOARTI_LOG_LEVEL", "warning")
    monkeypatch.chdir(tmp_path)
    calls, levels = [], []
    monkeypatch.setattr(
        launcher.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    monkeypatch.setattr(launcher, "configure_logging", levels.append)

    launcher.main()

    assert levels == ["WARNING"]
    ((args, kwargs),) = calls
    assert args == ("megooarti.main:create_app",)
    assert kwargs == {
        "factory": True,
        "host": "0.0.0.0",
        "port": 9001,
        "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.1",
        "timeout_graceful_shutdown": 7,
        "log_config": None,
    }


def test_launcher_reports_missing_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("MEGOOARTI_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        launcher.main()

    assert "MEGOOARTI_DATABASE_URL" in str(stopped.value)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_wait.py tests/test_launcher.py -v`
Expected: collection errors, `cannot import name 'wait' from 'megooarti.db'` and `cannot import name '__main__' from 'megooarti'`.

- [ ] **Step 4: Implement waiting for the database**

`backend/src/megooarti/db/wait.py`:

```python
"""Block until the database accepts connections. Used by the container entrypoint."""

import asyncio
import sys
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.config import ConfigurationError, get_settings


async def _attempt(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def wait_for_database(
    url: str, timeout_seconds: float, interval_seconds: float = 1.0
) -> None:
    """Return once a query succeeds; raise TimeoutError if none does in time."""
    engine = create_async_engine(url, poolclass=NullPool)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            try:
                async with asyncio.timeout(max(remaining, 0.1)):
                    await _attempt(engine)
                return
            except Exception as error:  # refused, DNS failure, starting up, timed out
                if time.monotonic() + interval_seconds >= deadline:
                    raise TimeoutError(
                        f"database not reachable after {timeout_seconds:g}s "
                        f"(last error: {type(error).__name__})"
                    ) from error
                await asyncio.sleep(interval_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        settings = get_settings()
        asyncio.run(wait_for_database(settings.database_url, settings.db_wait_timeout_seconds))
    except (ConfigurationError, TimeoutError) as error:
        sys.exit(f"megooarti: {error}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Implement the launcher**

`backend/src/megooarti/__main__.py`:

```python
"""`python -m megooarti`: serve the application with settings from the environment."""

import sys

import uvicorn

from megooarti.config import ConfigurationError, get_settings
from megooarti.log import configure_logging


def main() -> None:
    try:
        settings = get_settings()
    except ConfigurationError as error:
        sys.exit(f"megooarti: {error}")

    configure_logging(settings.log_level)
    uvicorn.run(
        "megooarti.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        timeout_graceful_shutdown=settings.shutdown_grace_seconds,
        log_config=None,  # keep the JSON logging configured above
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run in `backend/`: `uv run pytest tests/test_wait.py tests/test_launcher.py -v`
Expected: 7 passed.

- [ ] **Step 7: Write the failing container tests**

`backend/tests/test_container.py`:

```python
"""Tests of the built image. The `docker` ones run only with `pytest -m docker`."""

import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
PROJECT = "megooarti-test"
HTTP_PORT = "18000"
ENVIRONMENT = {**os.environ, "MEGOOARTI_HTTP_PORT": HTTP_PORT, "MEGOOARTI_DB_PORT": "15432"}
UNREACHABLE = "MEGOOARTI_DATABASE_URL=postgresql://megooarti:megooarti@nowhere.invalid:5432/m"


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=REPOSITORY_ROOT,
        env=ENVIRONMENT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def run_in_backend(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Start a throwaway backend container; `arguments` are `docker compose run` arguments."""
    return compose("run", "--rm", "--no-deps", "-T", *arguments, check=False)


@pytest.fixture(scope="module")
def stack():
    compose("down", "--volumes", check=False)
    compose("build", "backend")
    compose("up", "--detach", "--wait", "--wait-timeout", "180")
    yield
    compose("down", "--volumes", check=False)


def test_entrypoint_has_unix_line_endings():
    script = (BACKEND_DIR / "docker-entrypoint.sh").read_bytes()
    assert script.startswith(b"#!/bin/sh\n")
    assert b"\r" not in script


@pytest.mark.docker
def test_stack_starts_ready_with_the_schema_at_head(stack):
    url = f"http://127.0.0.1:{HTTP_PORT}/api/v1/status/ready"
    with urllib.request.urlopen(url, timeout=10) as response:
        body = json.load(response)
    assert body == {"status": "ok", "checks": {"database": "ok", "schema": "ok"}}


@pytest.mark.docker
def test_starting_again_against_a_migrated_database_is_safe(stack):
    result = run_in_backend("backend", "echo", "started")
    assert result.returncode == 0, result.stderr
    assert "started" in result.stdout


@pytest.mark.docker
def test_unreachable_database_stops_the_container_before_the_app_starts(stack):
    result = run_in_backend(
        "-e", UNREACHABLE, "-e", "MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS=3", "backend", "echo", "started"
    )
    assert result.returncode != 0
    assert "started" not in result.stdout
    assert "database not reachable" in result.stdout + result.stderr


@pytest.mark.docker
def test_migrations_can_be_switched_off(stack):
    result = run_in_backend(
        "-e", UNREACHABLE, "-e", "MEGOOARTI_RUN_MIGRATIONS=false", "backend", "echo", "started"
    )
    assert result.returncode == 0, result.stderr
    assert "started" in result.stdout


@pytest.mark.docker
def test_container_does_not_run_as_root(stack):
    result = run_in_backend("--entrypoint", "id", "backend", "-u")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "10001"
```

- [ ] **Step 8: Run the container tests to verify they fail**

Run in `backend/`: `uv run pytest tests/test_container.py -v`
Expected: `test_entrypoint_has_unix_line_endings` fails with `FileNotFoundError`; the other five are deselected.

- [ ] **Step 9: Write the entrypoint**

Save this file with LF line endings. `set -e` makes a failed wait or a failed migration stop the script, so the container exits non-zero and the app never starts. `exec` replaces the shell with the app so it receives shutdown signals directly.

`backend/docker-entrypoint.sh`:

```sh
#!/bin/sh
# Migrate the database, then start the application.
set -eu

if [ "${MEGOOARTI_RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "entrypoint: waiting for the database"
    python -m megooarti.db.wait
    echo "entrypoint: applying database migrations"
    alembic upgrade head
else
    echo "entrypoint: MEGOOARTI_RUN_MIGRATIONS is not 'true'; skipping migrations"
fi

exec "$@"
```

- [ ] **Step 10: Write the image definition**

`backend/.dockerignore`:

```gitignore
.venv/
.env
.pytest_cache/
.ruff_cache/
__pycache__/
tests/
scripts/
```

`backend/Dockerfile`:

```dockerfile
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.7.13 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    ALEMBIC_CONFIG=/app/src/megooarti/alembic.ini

WORKDIR /app

# Dependencies first, so this layer is reused until the lock file changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY docker-entrypoint.sh ./
RUN uv sync --frozen --no-dev \
    && chmod 0755 docker-entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home megooarti

USER megooarti
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "-m", "megooarti"]
```

- [ ] **Step 11: Add the backend to Compose**

Replace `docker-compose.yml` with:

```yaml
name: megooarti

services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: megooarti
      POSTGRES_PASSWORD: megooarti
      POSTGRES_DB: megooarti
    ports:
      - "${MEGOOARTI_DB_PORT:-5432}:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U megooarti -d megooarti"]
      interval: 2s
      timeout: 3s
      retries: 30

  backend:
    build: ./backend
    environment:
      MEGOOARTI_DATABASE_URL: postgresql://megooarti:megooarti@db:5432/megooarti
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "${MEGOOARTI_HTTP_PORT:-8000}:8000"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/status/ready', timeout=3)"
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 20s

volumes:
  db-data:
```

- [ ] **Step 12: Run the container tests to verify they pass**

Run in `backend/`:

```bash
uv run pytest tests/test_container.py -v
uv run pytest -m docker -v
```

Expected: the first command reports 1 passed, 5 deselected. The second builds the image (a few minutes the first time) and reports 5 passed.

If `test_entrypoint_has_unix_line_endings` fails, the editor saved CRLF. Convert the file to LF and rerun.

- [ ] **Step 13: Lint and commit**

Run in `backend/`:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Expected: no ruff errors; 58 passed, 5 deselected.

Run in the repository root:

```bash
git add docker-compose.yml backend
git commit -m "feat(backend): add container image that migrates before starting the app"
```

---

### Task 8: Continuous integration and documentation

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (replace the whole file)

**Interfaces:**
- Consumes: every command introduced in Tasks 1–7.
- Produces: a CI workflow with jobs `backend` (lint, tests, dependency audit) and `container` (image tests); a README that documents quick start, every environment variable and the migration workflow.

- [ ] **Step 1: Write the workflow**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    services:
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_USER: megooarti
          POSTGRES_PASSWORD: megooarti
          POSTGRES_DB: megooarti
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U megooarti -d megooarti"
          --health-interval 2s
          --health-timeout 3s
          --health-retries 30
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.7.13"
      - name: Install dependencies
        run: uv sync --frozen
      - name: Lint
        run: uv run ruff check .
      - name: Check formatting
        run: uv run ruff format --check .
      - name: Test (includes migration history and empty-database upgrade checks)
        run: uv run pytest -v
      - name: Audit dependencies for known vulnerabilities
        run: |
          uv export --frozen --no-dev --no-emit-project --output-file requirements.txt
          uvx pip-audit --requirement requirements.txt --disable-pip

  container:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.7.13"
      - name: Install dependencies
        run: uv sync --frozen
      - name: Build the image and test the entrypoint
        run: uv run pytest -m docker -v
```

- [ ] **Step 2: Run every CI command locally**

Run in `backend/`, with the `db` service from `docker compose up --detach --wait db` running:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest -v
uv export --frozen --no-dev --no-emit-project --output-file requirements.txt
uvx pip-audit --requirement requirements.txt --disable-pip
uv run pytest -m docker -v
```

Expected: ruff reports no errors; 58 passed, 5 deselected; pip-audit prints `No known vulnerabilities found`; 5 passed for the docker run. If pip-audit reports a vulnerability, upgrade the named package with `uv lock --upgrade-package <name>` and rerun the tests. `requirements.txt` is ignored by git.

- [ ] **Step 3: Write the README**

Replace `README.md` with:

````markdown
# MegooArti

An open-source repository and artifact proxy and manager. See the
[business requirements](docs/BRD.md) for scope and roadmap.

This repository currently contains the backend foundation: a FastAPI service with
health endpoints, structured logging and automatic database migrations. Package
formats, security and the web UI arrive in later milestones.

## Quick start

Requires Docker with Compose.

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
Interactive API documentation is at <http://localhost:8000/api/docs>.

## Configuration

All configuration is by environment variable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_DATABASE_URL` | required | PostgreSQL URL, for example `postgresql://user:password@host:5432/dbname` |
| `MEGOOARTI_RUN_MIGRATIONS` | `true` | When `true`, the container waits for the database and applies migrations before starting. Any other value skips both |
| `MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS` | `60` | How long the container waits for the database before exiting with an error |
| `MEGOOARTI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `MEGOOARTI_HOST` | `0.0.0.0` | Address the HTTP server binds to |
| `MEGOOARTI_PORT` | `8000` | Port the HTTP server listens on |
| `MEGOOARTI_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Comma-separated reverse-proxy addresses whose `X-Forwarded-*` headers are trusted |
| `MEGOOARTI_SHUTDOWN_GRACE_SECONDS` | `30` | How long in-flight requests may finish after a shutdown signal |

Docker Compose also reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
`MEGOOARTI_DB_PORT` (default `5432`) to choose the ports published on the host.

## Health endpoints

| Endpoint | Meaning |
| --- | --- |
| `GET /api/v1/status/live` | The process is running |
| `GET /api/v1/status/ready` | The database is reachable and its schema matches this version; `503` otherwise |

## Database migrations

The schema is managed only by [Alembic](https://alembic.sqlalchemy.org/). Migration
scripts are in `backend/src/megooarti/migrations/versions/`.

**In a deployment**, the container entrypoint waits for the database, runs
`alembic upgrade head`, and then starts the application. If a migration fails, the
container exits with an error and the application does not start. Several containers
may start at once; a database lock ensures only one applies migrations. To run
migrations as a separate deployment step instead, set `MEGOOARTI_RUN_MIGRATIONS=false`
on the application containers and run this once per release:

```bash
docker compose run --rm backend true
```

**In development**, use the helper script from `backend/`:

```bash
uv run python scripts/db.py new "add users table"   # create the next revision from the models
uv run python scripts/db.py upgrade                 # apply all migrations
uv run python scripts/db.py downgrade               # revert the last migration
uv run python scripts/db.py current                 # show the database's revision
uv run python scripts/db.py history                 # list every revision
uv run python scripts/db.py check                   # fail if models and migrations differ
```

Rules for migrations:

- The database must be at head before `new` will create a revision.
- Import every new model module in `backend/src/megooarti/models.py`, or `new` will not see it.
- Review the generated script; autogenerate does not detect every change.
- Every migration needs a working `downgrade()`.
- Never edit a migration that has been released. Add a new one.

## Development

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
docker compose up --detach --wait db
cd backend
cp .env.example .env
uv sync
uv run pytest                 # unit and integration tests; needs the db service
uv run pytest -m docker       # builds the image and tests the entrypoint
uv run ruff check .
uv run ruff format --check .
uv run python -m megooarti    # serve on http://localhost:8000 using .env
```

Tests create and use the databases `megooarti_test` and `megooarti_test_migrations`.
Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server.
````

- [ ] **Step 4: Verify the README quick start**

Run in the repository root:

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
docker compose logs backend
docker compose down
```

Expected: `curl` prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`. The log shows `entrypoint: waiting for the database`, `entrypoint: applying database migrations`, then JSON lines from Alembic and uvicorn.

- [ ] **Step 5: Commit**

Run in the repository root:

```bash
git add .github README.md
git commit -m "ci: add lint, test, audit and container jobs; document setup and migrations"
```
