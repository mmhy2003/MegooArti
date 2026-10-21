"""Running a repository's cleanup policies (spec 5): each component they select removed as
a delete through the API would remove it, with nobody calling (5.3), checked again first
against the policies as they are then (E6)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.cleanup import selection
from megooarti.cleanup.criteria import Criteria
from megooarti.cleanup.models import CleanupPolicy, RepositoryCleanupPolicy
from megooarti.config import Settings
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Asset, Repository
from megooarti.repositories.removal import delete_file
from megooarti.storage.models import Blob


async def unattended_context(
    db: AsyncSession, settings: Settings, repository: Repository
) -> RepositoryContext:
    """A context that deletes as the format does, asking no one (R1): the run's alone."""
    return await build_context(db, settings, repository, None, unattended=True)


async def policies_of(db: AsyncSession, repository: Repository) -> list[tuple[str, Criteria]]:
    """The policies attached to a repository now, by name, in name order."""
    found = await db.scalars(
        select(CleanupPolicy)
        .join(RepositoryCleanupPolicy, RepositoryCleanupPolicy.policy_id == CleanupPolicy.id)
        .where(RepositoryCleanupPolicy.repository_id == repository.id)
        .order_by(CleanupPolicy.name_key)
        .execution_options(populate_existing=True)
    )
    return [(policy.name, policy.criteria) for policy in found]


async def _companions(context: RepositoryContext, path: str) -> list[str]:
    """A proxy's files of no component that go with a file it removes (R3): its path, then
    `.` and more (`x.jar.sha1`, `x.whl.metadata`)."""
    escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return list(
        await context.db.scalars(
            select(Asset.path).where(
                Asset.repository_id == context.repository.id,
                Asset.component_id.is_(None),
                Asset.path.like(f"{escaped}.%", escape="\\"),
            )
        )
    )


async def remove(context: RepositoryContext, component_id: uuid.UUID, now: datetime) -> str | None:
    """Remove a component if a policy attached to its repository selects it now: the name
    of the first that does, or None (it is gone, or none selects it). Does not commit."""
    held = await selection.held(context, component_id)
    if held is None:
        return None
    chosen = next(
        (
            name
            for name, criteria in await policies_of(context.db, context.repository)
            if criteria.selects(held, now, context.format)
        ),
        None,
    )
    if chosen is None:
        return None
    files = [
        (path, sha256)
        for path, sha256 in await context.db.execute(
            select(Asset.path, Blob.sha256)
            .join(Blob, Blob.id == Asset.blob_id)
            .where(Asset.component_id == component_id)
            .order_by(Asset.path)
        )
    ]
    for path, _ in files:
        await delete_file(context, path)  # False for one an earlier one took with it
        if context.repository.type == "proxy":
            for companion in await _companions(context, path):
                await context.delete(companion)
    await context.format.cleaned_up(context, files)
    return chosen
