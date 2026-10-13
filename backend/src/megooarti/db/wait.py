"""Block until the database accepts connections. Used by the container entrypoint."""

import asyncio
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.config import ConfigurationError, get_settings

_REJECTED = (
    "the database rejected the user name or the password. The password is "
    "MEGOOARTI_DATABASE_PASSWORD if that is set (under Docker Compose, from "
    "MEGOOARTI_DB_PASSWORD), and otherwise the one in MEGOOARTI_DATABASE_URL. A database "
    "keeps the one it was first made with, whatever is set afterwards"
)
_PERMANENT_SQLSTATES = {
    "28000": _REJECTED,
    "28P01": _REJECTED,
    "3D000": "the database named in MEGOOARTI_DATABASE_URL does not exist",
}


def _permanent_problem(error: Exception) -> str | None:
    """A message if retrying cannot fix `error`, otherwise None."""
    if isinstance(error, TypeError | ArgumentError):
        return "MEGOOARTI_DATABASE_URL has an option the driver does not accept"
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    return _PERMANENT_SQLSTATES.get(sqlstate)


async def _attempt(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def wait_for_database(
    url: str, timeout_seconds: float, interval_seconds: float = 1.0
) -> None:
    """Return once a query succeeds.

    Raises TimeoutError if none does in time, and ConfigurationError straight away for
    a failure that waiting cannot fix.
    """
    engine = create_async_engine(url, poolclass=NullPool)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            try:
                async with asyncio.timeout(max(remaining, 0.1)):
                    await _attempt(engine)
                return
            except Exception as error:  # refused, DNS failure, starting up, timed out
                problem = _permanent_problem(error)
                if problem:
                    raise ConfigurationError(problem) from error
                if time.monotonic() + interval_seconds >= deadline:
                    raise TimeoutError(
                        f"database not reachable after {timeout_seconds:g}s "
                        f"(last error: {type(error).__name__})"
                    ) from error
                await asyncio.sleep(interval_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    try:
        settings = get_settings()
        asyncio.run(wait_for_database(settings.database_url, settings.db_wait_timeout_seconds))
    except (ConfigurationError, TimeoutError) as error:
        sys.exit(f"megooarti: {error}")


if __name__ == "__main__":
    main()
