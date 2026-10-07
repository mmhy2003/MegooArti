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
def settings() -> Settings:
    return Settings(_env_file=None, database_url=DEFAULT_TEST_DATABASE_URL)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with client_for(app) as http:
        yield http
