"""Helpers for the Alembic-managed schema."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

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
