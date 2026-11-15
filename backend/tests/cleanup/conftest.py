"""What the tests of cleanup share: files stored as a client stores them, then made as old
as a test needs."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from megooarti.cleanup.models import CleanupPolicy, RepositoryCleanupPolicy
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


async def age_everything(db, repository: Repository, *, written: float) -> None:
    """Make every file of a repository, and every component, written that many days ago."""
    await db.execute(
        update(Asset)
        .where(Asset.repository_id == repository.id)
        .values(updated_at=days_ago(written), last_downloaded_at=None)
    )
    await db.execute(
        update(Component)
        .where(Component.repository_id == repository.id)
        .values(created_at=days_ago(written))
    )
    await db.commit()


async def attach(db, repository: Repository, name: str = "old", **criteria) -> CleanupPolicy:
    """A policy of the repository's format attached to it: by default, not updated in 30
    days."""
    policy = CleanupPolicy(
        name=name,
        name_key=name.lower(),
        format=repository.format,
        **(criteria or {"updated_days": 30}),
    )
    db.add(policy)
    await db.flush()
    db.add(RepositoryCleanupPolicy(repository_id=repository.id, policy_id=policy.id))
    await db.commit()
    return policy


async def component_id(db, repository: Repository, name: str, version: str):
    found = await db.scalar(
        select(Component.id).where(
            Component.repository_id == repository.id,
            Component.name == name,
            Component.version == version,
        )
    )
    assert found is not None, (name, version)
    return found


async def paths_of(db, repository: Repository) -> list[str]:
    return sorted(await db.scalars(select(Asset.path).where(Asset.repository_id == repository.id)))
