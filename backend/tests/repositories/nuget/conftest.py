"""NuGet repositories made for a test, and what is pushed to them."""

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from megooarti.security import roles
from tests.accounts import PASSWORD, basic

URL = "/repository/nuget-hosted"
BASE = "https://test/repository/nuget-hosted/"


async def create(
    db, name: str = "nuget-hosted", *, hosted: dict | None = None, format_config: dict | None = None
) -> Repository:
    """A hosted NuGet repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="nuget",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config=format_config or {},
    )
    await db.commit()
    return repository


@pytest.fixture
async def hosted(db) -> Repository:
    return await create(db)


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


@pytest.fixture
async def pusher(db, make_user) -> dict[str, str]:
    """Someone who may read and add to NuGet repositories, and nothing more."""
    await roles.create_role(
        db, "pushers", "", ["repository:nuget:*:read", "repository:nuget:*:add"], []
    )
    await db.commit()
    await make_user("pusher", roles=["pushers"])
    return basic("pusher", PASSWORD)


async def push(
    client,
    headers: dict[str, str],
    package: bytes,
    *,
    repository: str = "nuget-hosted",
    symbols: bool = False,
):
    """A package as `dotnet nuget push` sends it: one file of a multipart form."""
    where = "api/v2/symbolpackage" if symbols else "api/v2/package"
    return await client.put(
        f"/repository/{repository}/{where}",
        files={"package": ("package.nupkg", package, "application/octet-stream")},
        headers=headers,
    )
