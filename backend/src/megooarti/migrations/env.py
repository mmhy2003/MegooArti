"""Alembic environment: run migrations online, one process at a time."""

import asyncio
import logging
import os

from alembic import context
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import megooarti.models  # noqa: F401  (registers every model on Base.metadata)
from megooarti.config import get_settings
from megooarti.db.base import Base
from megooarti.db.schema import MIGRATION_LOCK_KEY
from megooarti.log import configure_logging

target_metadata = Base.metadata


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    database_url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        locking_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
        async with locking_engine.connect() as lock_connection:
            await lock_connection.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_KEY})"))
            try:
                async with engine.connect() as connection:
                    await connection.run_sync(_run_migrations)
            finally:
                await lock_connection.execute(
                    text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_KEY})")
                )
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; migrate a live database.")

if not logging.getLogger().handlers:  # the alembic CLI; tests and the app configure their own
    configure_logging(
        os.environ.get("MEGOOARTI_LOG_LEVEL", "INFO"),
        os.environ.get("MEGOOARTI_LOG_FORMAT", "console").lower(),
    )

asyncio.run(_run_online())
