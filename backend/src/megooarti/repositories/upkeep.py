"""What repositories need done from time to time, whoever uses them.

Run by the periodic maintenance job. Each format tends its own repositories; uploads
that were begun and then left are removed here, for every format.
"""

from datetime import datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.config import Settings
from megooarti.repositories import uploads
from megooarti.repositories.content import build_context
from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Repository

log = structlog.get_logger(__name__)

# An upload nothing was appended to for this long is given up on.
UPLOAD_MAX_AGE_SECONDS = 86400


async def run(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> None:
    """Let every format tend its repositories, then remove uploads that were left.

    One repository's failure is logged and does not stop the others.
    """
    async with sessionmaker() as db:
        identifiers = list(await db.scalars(select(Repository.id).order_by(Repository.name_key)))
    for identifier in identifiers:
        async with sessionmaker() as db:
            repository = await db.get(Repository, identifier)
            handler = None if repository is None else get_format(repository.format)
            if handler is None:
                continue  # deleted since, or of a format this version does not have
            try:
                # Nobody is calling, so there is no principal.
                context = await build_context(db, settings, repository, None)
                await handler.maintain(context, now)
                await db.commit()
            except Exception:
                log.error("upkeep_failed", repository=repository.name, exc_info=True)
    removed = await uploads.sweep(
        sessionmaker, settings, now=now, max_age_seconds=UPLOAD_MAX_AGE_SECONDS
    )
    log.info("upkeep_finished", repositories=len(identifiers), uploads_removed=removed)
