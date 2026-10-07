import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.maintenance import run_exclusively, run_periodically

LOCK_KEY = 0x7E57_0001


@pytest.fixture
async def engine(database_url):
    engine = create_async_engine(database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


async def test_the_job_runs_when_nobody_else_holds_the_lock(engine):
    runs = []

    async def job() -> None:
        runs.append("ran")

    assert await run_exclusively(engine, LOCK_KEY, job) is True
    assert await run_exclusively(engine, LOCK_KEY, job) is True
    assert runs == ["ran", "ran"]


async def test_the_job_is_skipped_while_another_connection_holds_the_lock(engine):
    runs = []

    async def job() -> None:
        runs.append("ran")

    async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as other:
        await other.execute(text(f"SELECT pg_advisory_lock({LOCK_KEY})"))
        skipped = await run_exclusively(engine, LOCK_KEY, job)
        await other.execute(text(f"SELECT pg_advisory_unlock({LOCK_KEY})"))

    assert skipped is False
    assert runs == []


async def test_the_lock_is_released_when_the_job_fails(engine):
    async def failing() -> None:
        raise RuntimeError("the job broke")

    async def fine() -> None:
        return None

    with pytest.raises(RuntimeError):
        await run_exclusively(engine, LOCK_KEY, failing)

    assert await run_exclusively(engine, LOCK_KEY, fine) is True


async def test_a_periodic_job_keeps_running_after_a_failure():
    runs = []

    async def job() -> None:
        runs.append(len(runs))
        if len(runs) == 1:
            raise RuntimeError("the first run broke")

    task = asyncio.create_task(run_periodically("test", 0.01, job))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(runs) >= 3
