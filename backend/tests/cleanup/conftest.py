"""What the tests of cleanup share: files stored as a client stores them, then made as old
as a test needs."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from megooarti.clock import utcnow
from megooarti.repositories.models import Asset, Component, Repository
from tests.accounts import PASSWORD, basic


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def put(client, headers, path: str, repository: str = "files") -> None:
    response = await client.put(
        f"/repository/{repository}/{path}", content=path.encode(), headers=headers
    )
    assert response.status_code == 201, response.text


def days_ago(days: float) -> datetime:
    return utcnow() - timedelta(days=days)


async def age(
    db,
    path: str,
    *,
    written: float | None = None,
    downloaded: float | None = None,
    made: float | None = None,
    repository: str | None = None,
) -> None:
    """Make a stored file, and its component, as old as asked, in days."""
    query = select(Asset).where(Asset.path == path)
    if repository is not None:
        query = query.join(Repository, Repository.id == Asset.repository_id).where(
            Repository.name == repository
        )
    asset = await db.scalar(query)
    assert asset is not None, path
    values = {}
    if written is not None:
        values["updated_at"] = days_ago(written)
    if downloaded is not None:
        values["last_downloaded_at"] = days_ago(downloaded)
    if values:
        await db.execute(update(Asset).where(Asset.id == asset.id).values(**values))
    if made is not None and asset.component_id is not None:
        await db.execute(
            update(Component)
            .where(Component.id == asset.component_id)
            .values(created_at=days_ago(made))
        )
    await db.commit()
