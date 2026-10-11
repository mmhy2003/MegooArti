"""Migration tests. All synchronous: Alembic's env.py starts its own event loop."""

import asyncio

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.db.schema import MIGRATION_LOCK_KEY, alembic_config, head_revision
from tests.databases import fetch_all, run_sql

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


PATH_COLLATIONS = (
    "SELECT table_name, collation_name FROM information_schema.columns "
    "WHERE (table_name, column_name) IN (('assets', 'path'), ('asset_references', 'target')) "
    "ORDER BY table_name"
)


def test_paths_are_ordered_by_their_bytes_whatever_the_database_orders_by(empty_database):
    # The folder walk is only right in byte order. A test database may order that way
    # by itself, and the model check does not look at collations: this does.
    config = alembic_config(empty_database)
    command.upgrade(config, "head")
    upgraded = fetch_all(empty_database, PATH_COLLATIONS)
    command.downgrade(config, "0005")
    before = fetch_all(empty_database, PATH_COLLATIONS)

    assert upgraded == [("asset_references", "C"), ("assets", "C")]
    assert before == [("asset_references", None), ("assets", None)]


SEARCH_INDEXES = (
    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
    "AND (indexname LIKE 'ix_components_%_trgm' OR indexname LIKE 'ix_blobs_%') ORDER BY indexname"
)


def test_components_that_exist_are_given_what_they_are_found_by(empty_database):
    config = alembic_config(empty_database)
    command.upgrade(config, "0006")
    repository = "00000000-0000-0000-0000-000000000001"
    run_sql(
        empty_database,
        "INSERT INTO repositories (id, name, name_key, format, type, online, config, "
        f"created_at, updated_at) VALUES ('{repository}', 'old', 'old', 'maven', 'group', true, "
        "'{}', now(), now())",
        "INSERT INTO components (id, repository_id, namespace, name, version, attributes, "
        "created_at, updated_at) VALUES "
        f"(gen_random_uuid(), '{repository}', 'Com.Acme', 'App', '1.0', '{{}}', now(), now()), "
        f"(gen_random_uuid(), '{repository}', '', 'readme.TXT', '', '{{}}', now(), now())",
    )

    command.upgrade(config, "head")

    found = fetch_all(empty_database, "SELECT search FROM components ORDER BY search")
    assert found == [("com.acme app 1.0",), ("readme.txt",)]
    assert fetch_all(empty_database, SEARCH_INDEXES) == [
        ("ix_blobs_md5",),
        ("ix_blobs_sha1",),
        ("ix_blobs_sha256",),
        ("ix_blobs_sha512",),
        ("ix_components_name_trgm",),
        ("ix_components_namespace_trgm",),
        ("ix_components_search_trgm",),
    ]


def test_the_search_column_and_its_indexes_go_on_the_way_back(empty_database):
    config = alembic_config(empty_database)
    command.upgrade(config, "head")

    command.downgrade(config, "0006")

    columns = fetch_all(
        empty_database,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'components' AND column_name = 'search'",
    )
    assert columns == []
    assert fetch_all(empty_database, SEARCH_INDEXES) == []
