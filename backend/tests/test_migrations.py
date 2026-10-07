"""Migration tests. All synchronous: Alembic's env.py starts its own event loop."""

import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.db.schema import MIGRATION_LOCK_KEY, alembic_config, head_revision
from tests.databases import fetch_all

USER_TABLES = (
    "SELECT tablename FROM pg_tables "
    "WHERE schemaname = 'public' AND tablename <> 'alembic_version' ORDER BY tablename"
)


def applied_revision(url: str) -> list[tuple]:
    return fetch_all(url, "SELECT version_num FROM alembic_version")


def test_history_has_exactly_one_head():
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert len(heads) == 1
    assert head_revision() == heads[0]


def test_upgrade_from_an_empty_database_reaches_head(empty_database):
    command.upgrade(alembic_config(empty_database), "head")

    assert applied_revision(empty_database) == [(head_revision(),)]
    assert ("system_settings",) in fetch_all(empty_database, USER_TABLES)


def test_upgrade_is_a_no_op_when_already_at_head(empty_database):
    command.upgrade(alembic_config(empty_database), "head")
    command.upgrade(alembic_config(empty_database), "head")

    assert applied_revision(empty_database) == [(head_revision(),)]


def test_downgrade_to_base_removes_every_table(empty_database):
    command.upgrade(alembic_config(empty_database), "head")
    command.downgrade(alembic_config(empty_database), "base")

    assert fetch_all(empty_database, USER_TABLES) == []


def test_models_and_migrations_describe_the_same_schema(empty_database):
    config = alembic_config(empty_database)
    command.upgrade(config, "head")

    command.check(config)  # raises CommandError if autogenerate would emit operations


def test_migration_waits_while_another_process_holds_the_lock(empty_database):
    async def scenario() -> None:
        engine = create_async_engine(
            empty_database, poolclass=NullPool, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as holder:
                await holder.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_KEY})"))
                migration = asyncio.create_task(
                    asyncio.to_thread(command.upgrade, alembic_config(empty_database), "head")
                )

                finished, _ = await asyncio.wait({migration}, timeout=2)
                assert not finished, "the migration ran without waiting for the lock"

                await holder.execute(text(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_KEY})"))
                await asyncio.wait_for(migration, timeout=30)
        finally:
            await engine.dispose()

    asyncio.run(scenario())

    assert applied_revision(empty_database) == [(head_revision(),)]
