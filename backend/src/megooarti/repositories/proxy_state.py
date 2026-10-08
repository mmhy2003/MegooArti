"""What a proxy repository has learned about its remote.

Two things, both kept in the database so that every container shares them: how the
remote has been failing (and so whether it is blocked), and which paths it said it
does not have.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.models import NegativeCacheEntry, ProxyState, Repository

_FIRST_BLOCK_SECONDS = 60
_LONGEST_BLOCK_SECONDS = 3600


def block_seconds(failures: int) -> int:
    """How long to leave the remote alone after this many consecutive failures."""
    doubled = _FIRST_BLOCK_SECONDS * 2 ** min(failures - 1, 16)
    return min(doubled, _LONGEST_BLOCK_SECONDS)


async def blocked(db: AsyncSession, repository: Repository, now: datetime) -> bool:
    settings = repository.config["proxy"]
    if settings["blocked"]:
        return True
    if not settings["auto_block"]:
        return False  # turning automatic blocking off also lifts a block already in place
    until = await db.scalar(
        select(ProxyState.blocked_until).where(ProxyState.repository_id == repository.id)
    )
    return until is not None and until > now


async def record_failure(
    db: AsyncSession, repository: Repository, now: datetime, reason: str, *, blockable: bool
) -> None:
    # Make sure the row exists, then lock it, so concurrent failures count once each.
    await db.execute(
        insert(ProxyState).values(repository_id=repository.id, failures=0).on_conflict_do_nothing()
    )
    state = await db.scalar(
        select(ProxyState)
        .where(ProxyState.repository_id == repository.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    state.last_error = reason[:255]
    state.last_checked_at = now
    # A failure counts only if the remote was not already blocked. Requests that were in
    # flight when it went down all fail together, and that is one outage, not several.
    already_blocked = state.blocked_until is not None and state.blocked_until > now
    if blockable and repository.config["proxy"]["auto_block"] and not already_blocked:
        state.failures += 1
        state.blocked_until = now + timedelta(seconds=block_seconds(state.failures))
    await db.flush()


async def record_success(db: AsyncSession, repository: Repository, now: datetime) -> None:
    await db.execute(
        update(ProxyState)
        .where(ProxyState.repository_id == repository.id)
        .values(failures=0, blocked_until=None, last_error=None, last_checked_at=now)
    )


def _negative_cache(repository: Repository) -> dict:
    return repository.config["proxy"]["negative_cache"]


async def remember_missing(
    db: AsyncSession, repository: Repository, path: str, now: datetime
) -> None:
    """Note that the remote does not have this path, for the configured time."""
    settings = _negative_cache(repository)
    if not settings["enabled"]:
        return
    # Tidy this repository's expired entries. Scoped to one repository so that the
    # delete uses the primary key and never scans the whole table on a miss.
    await db.execute(
        delete(NegativeCacheEntry).where(
            NegativeCacheEntry.repository_id == repository.id,
            NegativeCacheEntry.expires_at <= now,
        )
    )
    expires = now + timedelta(minutes=settings["ttl_minutes"])
    remember = insert(NegativeCacheEntry).values(
        repository_id=repository.id, path=path, expires_at=expires
    )
    await db.execute(
        remember.on_conflict_do_update(
            index_elements=[NegativeCacheEntry.repository_id, NegativeCacheEntry.path],
            set_={"expires_at": expires},
        )
    )


async def known_missing(db: AsyncSession, repository: Repository, path: str, now: datetime) -> bool:
    if not _negative_cache(repository)["enabled"]:
        return False
    expires = await db.scalar(
        select(NegativeCacheEntry.expires_at).where(
            NegativeCacheEntry.repository_id == repository.id, NegativeCacheEntry.path == path
        )
    )
    return expires is not None and expires > now
