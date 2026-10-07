from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from megooarti.config import Settings, get_settings
from megooarti.main import create_app
from tests.clients import client_for

DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"


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
