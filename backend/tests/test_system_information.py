import platform
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from megooarti import __version__
from megooarti.db.schema import head_revision
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

INFORMATION = "/api/v1/system/information"


async def test_reading_needs_the_permission_to_read_settings(client, make_user, db):
    await make_user("dana")
    await roles.create_role(db, "settings-readers", "", ["admin:settings:read"], [])
    await db.commit()
    await make_user("rae", roles=["settings-readers"])

    assert (await client.get(INFORMATION)).status_code == 401
    refused = await client.get(INFORMATION, headers=basic("dana", PASSWORD))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert (await client.get(INFORMATION, headers=basic("rae", PASSWORD))).status_code == 200


async def test_it_says_which_version_runs_and_on_what(admin_client):
    before = datetime.now(UTC)

    information = (await admin_client.get(INFORMATION)).json()

    assert information["version"] == __version__
    assert information["runtime"]["python"] == platform.python_version()
    assert information["runtime"]["platform"] == platform.platform()
    started = datetime.fromisoformat(information["runtime"]["started_at"])
    # The application of this test was made a moment ago, and not after it was asked.
    assert before - timedelta(minutes=10) < started <= datetime.now(UTC)
    assert re.match(r"PostgreSQL \d+", information["database"]["version"])
    assert set(information) == {"version", "schema", "runtime", "database"}


async def test_it_says_that_the_schema_is_the_one_this_version_expects(admin_client):
    schema = (await admin_client.get(INFORMATION)).json()["schema"]

    assert schema == {"revision": head_revision(), "expected": head_revision(), "current": True}


async def test_it_says_so_when_the_schema_is_another_one(admin_client, db):
    # As after an upgrade whose migrations were not run, or a downgrade of the image.
    await db.execute(text("UPDATE alembic_version SET version_num = 'an-older-one'"))
    await db.commit()
    try:
        schema = (await admin_client.get(INFORMATION)).json()["schema"]
    finally:
        await db.execute(
            text("UPDATE alembic_version SET version_num = :head"), {"head": head_revision()}
        )
        await db.commit()

    assert schema == {"revision": "an-older-one", "expected": head_revision(), "current": False}


async def test_it_says_so_when_the_database_was_never_migrated(admin_client, db):
    # No table of revisions at all, as before the first migration was run.
    await db.execute(text("ALTER TABLE alembic_version RENAME TO alembic_version_away"))
    await db.commit()
    try:
        schema = (await admin_client.get(INFORMATION)).json()["schema"]
    finally:
        await db.execute(text("ALTER TABLE alembic_version_away RENAME TO alembic_version"))
        await db.commit()

    assert schema == {"revision": None, "expected": head_revision(), "current": False}


async def test_it_gives_away_nothing_of_the_configuration(admin_client, app):
    response = await admin_client.get(INFORMATION)
    said = response.text
    information = response.json()

    assert response.status_code == 200
    # What it says is all it says: a field added to it is added here, on purpose.
    assert set(information["schema"]) == {"revision", "expected", "current"}
    assert set(information["runtime"]) == {"python", "platform", "started_at"}
    assert set(information["database"]) == {"version"}
    # Not the address of the database, which has its password in it, nor a path.
    assert app.state.settings.database_url not in said
    assert "megooarti:megooarti" not in said
    assert str(app.state.settings.data_dir) not in said
