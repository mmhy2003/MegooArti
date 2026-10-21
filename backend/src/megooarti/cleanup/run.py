"""Running a repository's cleanup policies (spec 5): each component they select removed as
a delete through the API would remove it, with nobody calling (5.3), checked again first
against the policies as they are then (E6)."""

import asyncio
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

import structlog
from fastapi import FastAPI
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from megooarti.cleanup import selection
from megooarti.cleanup.criteria import Criteria
from megooarti.cleanup.models import CleanupPolicy, CleanupRun, RepositoryCleanupPolicy
from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Asset, Repository
from megooarti.repositories.removal import delete_file
from megooarti.storage.models import Blob
from megooarti.system import audit

log = structlog.get_logger(__name__)


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


# --- When ------------------------------------------------------------------------------

# How often the daily run asks which repositories are due (E5).
CHECK_SECONDS = 3600
# How many runs started now one server runs at once, beside the daily one: each holds two
# of the database's connections for as long as it lasts.
MOST_AT_ONCE = 2


async def due(db: AsyncSession, now: datetime, interval_seconds: int) -> list[uuid.UUID]:
    """The hosted and proxy repositories with a policy attached whose last run did not
    finish within the interval: never run, run long ago, or cut short (R10). One under
    way elsewhere is among them, and is passed over by its claim."""
    since = now - timedelta(seconds=interval_seconds)
    attached = select(RepositoryCleanupPolicy.repository_id).where(
        RepositoryCleanupPolicy.repository_id == Repository.id
    )
    return list(
        await db.scalars(
            select(Repository.id)
            .outerjoin(CleanupRun, CleanupRun.repository_id == Repository.id)
            .where(
                Repository.type.in_(("hosted", "proxy")),
                attached.exists(),
                or_(
                    CleanupRun.repository_id.is_(None),
                    CleanupRun.finished_at.is_(None),
                    CleanupRun.finished_at < since,
                ),
            )
            .order_by(Repository.name_key)
        )
    )


async def daily(app: FastAPI) -> int:
    """Clean each repository that is due, one after another, passing over one another
    container is cleaning. How many were cleaned."""
    settings = app.state.settings
    async with app.state.sessionmaker() as db:
        found = await due(db, utcnow(), settings.cleanup_interval_seconds)
    cleaned = 0
    for repository_id in found:
        connection = await claim(app.state.engine, repository_id)
        if connection is None:
            continue
        try:
            # The list is old by now: a run here or elsewhere may have cleaned it since.
            async with app.state.sessionmaker() as db:
                still = await _still_due(
                    db, repository_id, utcnow(), settings.cleanup_interval_seconds
                )
            if still:
                await clean(app.state.sessionmaker, settings, repository_id)
                cleaned += 1
        finally:
            await release(connection, repository_id)
    return cleaned


async def _still_due(
    db: AsyncSession, repository_id: uuid.UUID, now: datetime, interval_seconds: int
) -> bool:
    """Whether a repository's last run, read now, did not finish within the interval."""
    kept = await db.get(CleanupRun, repository_id, populate_existing=True)
    return (
        kept is None
        or kept.finished_at is None
        or kept.finished_at < now - timedelta(seconds=interval_seconds)
    )


async def start_now(
    app: FastAPI, repository: Repository, by: str
) -> Literal["started", "running", "busy"]:
    """Start a run of a repository in the server: `running` if one of it is under way,
    `busy` if this server runs as many as it runs at once. It keeps the caller's context:
    its record names who asked (R7)."""
    if len(app.state.cleanups) >= MOST_AT_ONCE:
        return "busy"
    connection = await claim(app.state.engine, repository.id)
    if connection is None:
        return "running"

    async def running() -> None:
        try:
            await clean(app.state.sessionmaker, app.state.settings, repository.id, by=by)
        except Exception:
            log.error("cleanup_failed", repository=repository.name, exc_info=True)
        finally:
            await release(connection, repository.id)

    task = asyncio.create_task(running())
    app.state.cleanups.add(task)
    task.add_done_callback(app.state.cleanups.discard)
    return "started"


# --- One repository's run --------------------------------------------------------------

# With a repository's id, the advisory lock of its run (R6): `0x4D43`.
LOCK_CLASS = 0x4D43
_LOCK = f"({LOCK_CLASS}, hashtext(CAST(:repository AS text)))"


async def claim(engine: AsyncEngine, repository_id: uuid.UUID) -> AsyncConnection | None:
    """A connection holding the lock of a repository's run, or None if another holds it,
    here or in another container (E12). Give it back with `release`."""
    connection = await engine.execution_options(isolation_level="AUTOCOMMIT").connect()
    try:
        taken = await connection.scalar(
            text(f"SELECT pg_try_advisory_lock{_LOCK}"), {"repository": str(repository_id)}
        )
    except BaseException:
        await connection.close()
        raise
    if not taken:
        await connection.close()
        return None
    return connection


async def release(connection: AsyncConnection, repository_id: uuid.UUID) -> None:
    try:
        await connection.execute(
            text(f"SELECT pg_advisory_unlock{_LOCK}"), {"repository": str(repository_id)}
        )
    finally:
        await connection.close()


async def _selected_ids(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    repository_id: uuid.UUID,
    now: datetime,
    batch: int,
) -> list[uuid.UUID]:
    """The ids of what the repository's policies select now: the ids alone are held."""
    async with sessionmaker() as db:
        repository = await db.get(Repository, repository_id)
        if repository is None:
            return []
        context = await build_context(db, settings, repository, None)
        policies = [criteria for _, criteria in await policies_of(db, repository)]
        return [held.id async for held in selection.selected(context, policies, now, batch=batch)]


async def clean(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    repository_id: uuid.UUID,
    *,
    by: str | None = None,
    now: Callable[[], datetime] = utcnow,
    batch: int = selection.BATCH,
) -> CleanupRun | None:
    """Run a repository's policies: each component they select removed in a transaction of
    its own. The caller holds the repository's claim. None if there is no such repository.

    A component that cannot be removed is logged and counted, and the run goes on. A run
    that is cancelled stops between two components, and its record says it did not finish.
    """
    began = time.monotonic()
    async with sessionmaker() as db:
        repository = await db.get(Repository, repository_id)
        if repository is None:
            return None
        name = repository.name
        kept = await db.get(CleanupRun, repository_id) or CleanupRun(repository_id=repository_id)
        kept.started_at, kept.finished_at, kept.by = now(), None, by
        kept.removed, kept.failed, kept.error = 0, 0, None
        db.add(kept)
        await db.commit()

    removed = failed = 0
    chose: set[str] = set()
    error = None
    try:
        ids = await _selected_ids(sessionmaker, settings, repository_id, now(), batch)
    except Exception as failure:
        ids, error = [], f"{type(failure).__name__}: {failure}"
        log.error("cleanup_failed", repository=name, exc_info=True)
    for component_id in ids:
        try:
            async with sessionmaker() as db:
                repository = await db.get(Repository, repository_id)
                if repository is None:
                    break  # deleted meanwhile, and everything in it
                context = await unattended_context(db, settings, repository)
                policy = await remove(context, component_id, now())
                await db.commit()
        except Exception:
            failed += 1
            log.error(
                "cleanup_component_failed",
                repository=name,
                component=str(component_id),
                exc_info=True,
            )
            continue
        if policy is not None:
            removed += 1
            chose.add(policy)

    async with sessionmaker() as db:
        kept = await db.get(CleanupRun, repository_id, populate_existing=True)
        if kept is not None:
            kept.removed, kept.failed, kept.error = removed, failed, error
            kept.finished_at = now()
            said = {"removed": removed, "policies": sorted(chose)}
            if failed:
                said["failed"] = failed
            audit.record(db, "repository.cleaned_up", ("repository", name), audit.diff(None, said))
        await db.commit()
    log.info(
        "cleanup_finished",
        repository=name,
        removed=removed,
        failed=failed,
        seconds=round(time.monotonic() - began, 3),
    )
    return kept
