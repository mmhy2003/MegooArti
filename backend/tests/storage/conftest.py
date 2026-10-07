from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from megooarti.storage.backends import StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import BlobStore


@pytest.fixture
async def default_store(db) -> BlobStore:
    return await db.scalar(select(BlobStore).where(BlobStore.name == "default"))


@pytest.fixture
def backend(settings, default_store):
    return backend_for(settings, default_store)


@pytest.fixture
def stage(backend):
    async def stage_bytes(body: bytes) -> StagedBlob:
        async def chunks() -> AsyncIterator[bytes]:
            yield body

        return await backend.stage(chunks())

    return stage_bytes
