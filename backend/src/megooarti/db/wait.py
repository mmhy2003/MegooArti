"""Block until the database accepts connections. Used by the container entrypoint."""

import asyncio
import sys
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.config import ConfigurationError, get_settings


async def _attempt(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def wait_for_database(
    url: str, timeout_seconds: float, interval_seconds: float = 1.0
) -> None:
    """Return once a query succeeds; raise TimeoutError if none does in time."""
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
