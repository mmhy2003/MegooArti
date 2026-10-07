"""Helpers for the Alembic-managed schema."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# Arbitrary constant ("MEGOO" in ASCII). Every MegooArti process uses the same key,
# so only one of them migrates a given database at a time.
MIGRATION_LOCK_KEY = 0x4D45474F4F


def alembic_config(database_url: str | None = None) -> Config:
    """Alembic configuration; `database_url` overrides MEGOOARTI_DATABASE_URL."""
    config = Config(str(ALEMBIC_INI))
    if database_url is not None:
        config.attributes["database_url"] = database_url
    return config


def head_revision() -> str:
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one migration head, found {len(heads)}: {heads}")
    return heads[0]


async def current_revision(connection: AsyncConnection) -> str | None:
    """The revision recorded in the database, or None if it was never migrated."""
    has_table = await connection.scalar(text("SELECT to_regclass('alembic_version') IS NOT NULL"))
    if not has_table:
        return None
    return await connection.scalar(text("SELECT version_num FROM alembic_version"))
