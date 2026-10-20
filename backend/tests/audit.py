"""What the audit log holds, for the tests of the changes that write it (spec 12)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.system.models import AuditRecord


async def records(
    sessionmaker: async_sessionmaker[AsyncSession], event: str | None = None
) -> list[AuditRecord]:
    """The records, oldest first: of one event, or all of them."""
    query = select(AuditRecord).order_by(AuditRecord.at, AuditRecord.id)
    if event is not None:
        query = query.where(AuditRecord.event == event)
    async with sessionmaker() as db:
        return list(await db.scalars(query))


async def last(sessionmaker: async_sessionmaker[AsyncSession], event: str) -> AuditRecord:
    """The newest record of an event; fails the test if there is none."""
    found = await records(sessionmaker, event)
    assert found, f"no {event} record"
    return found[-1]
