import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

REMOTE = "http://remote.test/maven2"


async def create(
    db,
    name: str,
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
    **format_config,
) -> Repository:
    """A Maven repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="maven",
        type=type,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        group=group,
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
async def central(db) -> Repository:
    """A proxy of the fake remote, taking releases in the strict layout."""
    return await create(db, "central", type="proxy", proxy={"remote_url": REMOTE})


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
