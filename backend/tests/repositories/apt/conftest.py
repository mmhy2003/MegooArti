"""APT repositories made for a test, and what uploads to them."""

import pytest

from megooarti.repositories import derived, service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/apt-hosted"
REMOTE = "http://remote.test/debian"


async def create(
    db,
    name: str = "apt-hosted",
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    format_config: dict | None = None,
) -> Repository:
    """An APT repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="apt",
        type=type,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        format_config=format_config or {},
    )
    await db.commit()
    return repository


@pytest.fixture(autouse=True)
def nothing_kept():
    """Every test writes its indexes anew: what one wrote is not served to the next."""
    derived.forget()
    yield
    derived.forget()


@pytest.fixture
async def hosted(db) -> Repository:
    return await create(db)


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def upload(
    client, headers, package: bytes, *, repository: str = "apt-hosted", method: str = "PUT"
):
    """A package sent as `curl --upload-file` sends it."""
    return await client.request(
        method, f"/repository/{repository}/", content=package, headers=headers
    )
