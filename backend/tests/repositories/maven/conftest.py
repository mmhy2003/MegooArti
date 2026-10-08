import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic


async def create(db, name: str, *, hosted: dict | None = None, **format_config) -> Repository:
    """A hosted Maven repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="maven",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config=format_config,
    )
    await db.commit()
    return repository


@pytest.fixture
async def releases(db) -> Repository:
    return await create(db, "releases")


@pytest.fixture
async def snapshots(db) -> Repository:
    return await create(db, "snapshots", version_policy="snapshot")


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
