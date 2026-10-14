"""YUM repositories made for a test, and what uploads to them."""

import pytest

from megooarti.repositories import derived, service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/yum-hosted"
REMOTE = "http://remote.test/fedora/44/Everything/x86_64/os"


async def create(
    db,
    name: str = "yum-hosted",
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    format_config: dict | None = None,
) -> Repository:
    """A YUM repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="yum",
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
    """Every test writes its metadata anew: what one wrote is not served to the next."""
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


async def upload(client, headers, path: str, package: bytes, *, repository: str = "yum-hosted"):
    """A package sent as `curl --upload-file` sends it to its path."""
    return await client.put(f"/repository/{repository}/{path}", content=package, headers=headers)
