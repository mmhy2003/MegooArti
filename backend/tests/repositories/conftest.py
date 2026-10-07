from collections.abc import AsyncIterator

import pytest

from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Repository
from megooarti.security.authentication import Principal
from megooarti.security.models import User
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore


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
def context_for(db, settings):
    async def make(repository: Repository, principal: Principal | None) -> RepositoryContext:
        store = await db.get(BlobStore, repository.blob_store_id)
        return RepositoryContext(
            db=db,
            settings=settings,
            repository=repository,
            principal=principal,
            format=get_format(repository.format),
            backend=backend_for(settings, store),
        )

    return make
