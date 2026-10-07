"""Tests of the test support code that every later test relies on."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from tests.clients import client_for
from tests.databases import reset_schema


async def test_client_for_runs_the_application_lifespan():
    events = []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        events.append("startup")
        yield
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)

    async with client_for(app):
        assert events == ["startup"]

    assert events == ["startup", "shutdown"]


@pytest.mark.parametrize("name", ["megooarti", "production", "megooarti_test_backup"])
def test_reset_schema_refuses_a_database_not_named_for_tests(name):
    url = f"postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/{name}"

    with pytest.raises(ValueError, match="_test"):
        reset_schema(url)
