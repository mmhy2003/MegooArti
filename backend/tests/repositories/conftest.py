from collections.abc import AsyncIterator

import pytest

from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Repository
from megooarti.security.authentication import Principal
from megooarti.security.models import User


def someone(*patterns: str, method: str = "token", username: str = "dana") -> Principal:
    """A principal holding exactly these patterns, without touching the database."""
    user = User(username=username, display_name=username.title(), must_change_password=False)
    return Principal(user, method, frozenset(patterns))


async def body(data: bytes, size: int = 700) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


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
