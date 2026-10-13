import os
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from argon2 import PasswordHasher
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
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
from megooarti.repositories import remote, service
from megooarti.repositories.models import Repository
from megooarti.security import passwords, tokens, users
from megooarti.security.models import User
from tests.accounts import PASSWORD, sign_in
from tests.clients import client_for
from tests.containers import DATA_FILE, call, compose
from tests.databases import ensure_database, reset_schema
from tests.failures import keep_broken_setup, keep_stack_logs, say_where

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"


# For the tests of the tests' own support code.
pytest_plugins = ["pytester"]


_kept: list[Path] = []
_logs: list[Path] = []


def _stack_logs() -> str:
    said = compose("logs", "--no-color", "--tail", "4000", "backend", "gateway", check=False)
    return said.stdout


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Keep what a failed setup said, whatever becomes of the run's own output.

    And of a test of the running stack that failed, what the stack said.
    """
    path = keep_broken_setup(report)
    if path is not None:
        _kept.append(path)
    logs = keep_stack_logs(report, _stack_logs)
    if logs is not None:
        _logs.append(logs)


def pytest_terminal_summary(terminalreporter) -> None:
    say_where(terminalreporter.write_line, _kept)
    say_where(terminalreporter.write_line, _logs, "log of the stack", "logs of the stack")


def _configured_test_database_url() -> str:
    raw = os.environ.get("MEGOOARTI_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    return Settings(_env_file=None, database_url=raw).database_url


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_waiting_for_remotes(monkeypatch):
    """A remote that refuses a connection is asked again after a wait: in tests, at once."""
    monkeypatch.setattr(remote, "CONNECT_WAITS", (0.0, 0.0))


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


@pytest.fixture(autouse=True)
def _cheap_password_hashing(monkeypatch):
    """Argon2 at production cost would add seconds to the suite."""
    cheap = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    monkeypatch.setattr(passwords, "_hasher", cheap)
    monkeypatch.setattr(passwords, "_dummy_hash", None)


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


@pytest.fixture
async def files(db) -> Repository:
    repository = await service.create_repository(
        db,
        name="files",
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=None,
        format_config={},
    )
    await db.commit()
    return repository


@pytest.fixture(scope="module")
def stack():
    """The built image and its database, started afresh for each module of container tests."""
    compose("down", "--volumes", check=False)
    compose("build")
    compose("up", "--detach", "--wait", "--wait-timeout", "180")
    yield
    compose("down", "--volumes", check=False)


@pytest.fixture(scope="module")
def administrator(stack) -> dict[str, str]:
    """Sign in as the first-start administrator and change the password, once per module.

    Returns the headers that authenticate later requests as that session.
    """
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
    return credentials
