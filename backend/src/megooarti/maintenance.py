"""Background work the application does on a schedule.

Phase 2 replaces this with scheduled tasks an administrator can manage. Until then a
job runs on a fixed interval, in one container at a time.
"""

import asyncio
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger(__name__)

Job = Callable[[], Awaitable[None]]


async def run_exclusively(engine: AsyncEngine, lock_key: int, job: Job) -> bool:
    """Run `job` unless another container is already running it. False if skipped."""
    # A session-level lock lives on this connection, so it is held on a dedicated one
    # in autocommit mode for as long as the job runs.
    async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as connection:
        acquired = await connection.scalar(text(f"SELECT pg_try_advisory_lock({lock_key})"))
        if not acquired:
            return False
        try:
            await job()
        finally:
            await connection.execute(text(f"SELECT pg_advisory_unlock({lock_key})"))
        return True


async def run_periodically(name: str, interval_seconds: float, job: Job) -> None:
    """Run `job` every `interval_seconds`, forever. A failure is logged, not fatal."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await job()
        except Exception:
            log.error("maintenance_failed", job=name, exc_info=True)
