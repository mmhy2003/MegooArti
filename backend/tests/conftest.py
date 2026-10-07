import os
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest
from alembic import command
from argon2 import PasswordHasher
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
from megooarti.security import passwords, users
from megooarti.security.models import User
from tests.accounts import PASSWORD
from tests.clients import client_for
from tests.databases import ensure_database, reset_schema

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"


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
