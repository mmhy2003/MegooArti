"""Database helpers for tests.

Every function here calls asyncio.run, so use them only from synchronous tests and
synchronous fixtures, never from inside a running event loop.
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def run_sql(url: str, *statements: str) -> None:
    """Run statements in autocommit mode on a short-lived connection."""

    async def run() -> None:
        engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as connection:
                for statement in statements:
                    await connection.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(run())


def fetch_all(url: str, statement: str) -> list[tuple]:
    async def run() -> list[tuple]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text(statement))
                return [tuple(row) for row in result]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def ensure_database(url: str) -> None:
    """Create the database named in `url` if it does not exist."""
    target = make_url(url)
    maintenance = target.set(database="postgres").render_as_string(hide_password=False)
    found = fetch_all(maintenance, f"SELECT 1 FROM pg_database WHERE datname = '{target.database}'")
    if not found:
        run_sql(maintenance, f'CREATE DATABASE "{target.database}"')


def reset_schema(url: str) -> None:
    """Remove every table, including alembic_version. Only for databases named for tests."""
    name = make_url(url).database or ""
    if not name.endswith(("_test", "_test_migrations")):
        raise ValueError(
            f"refusing to reset database {name!r}: the name must end in _test or _test_migrations"
        )
    run_sql(url, "DROP SCHEMA public CASCADE", "CREATE SCHEMA public")


async def connected(engine, tries: int = 3):
    """A connection of `engine`, asked for again where a try is dropped before it is made.

    On Windows, a connection to a port that Docker publishes ends now and then in an
    OSError (WinError 121, "The semaphore timeout period has expired") in place of a
    connection: once in many runs of the suite. What the database answers, a refusal
    included, is no OSError, and is not asked for again.
    """
    for last in [False] * (tries - 1) + [True]:
        try:
            return await engine.connect()
        except OSError:
            if last:
                raise
    raise AssertionError("the last try answers or raises")
