import asyncio

import structlog
from alembic import command

from megooarti.config import Settings
from megooarti.db.schema import alembic_config
from megooarti.main import create_app
from megooarti.security.bootstrap import password_file
from tests.accounts import sign_in
from tests.clients import client_for

NEW_PASSWORD = "a brand new password"


def generated_password(settings: Settings) -> str:
    return password_file(settings).read_text(encoding="utf-8").strip()


async def test_first_start_gives_the_administrator_a_password_to_change(client, settings):
    password = generated_password(settings)

    signed_in = await sign_in(client, "admin", password)

    assert len(password) >= 20
    assert signed_in["must_change_password"] is True
    assert signed_in["permissions"] == ["*"]


async def test_a_second_start_changes_nothing(app, settings):
    async with client_for(app):
        first = generated_password(settings)

    async with client_for(app) as client:
        assert generated_password(settings) == first
        await sign_in(client, "admin", first)


async def test_changing_the_password_removes_the_file(client, settings):
    password = generated_password(settings)
    await sign_in(client, "admin", password)

    response = await client.put(
        "/api/v1/me/password",
        json={"current_password": password, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 204
    assert not password_file(settings).exists()


async def test_start_up_survives_a_data_directory_it_cannot_write(settings, sessionmaker, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a directory is expected", encoding="utf-8")
    app = create_app(settings.model_copy(update={"data_dir": blocker / "data"}))
    app.state.sessionmaker = sessionmaker

    with structlog.testing.capture_logs() as logs:
        async with client_for(app) as client:
            (entry,) = [log for log in logs if log["event"] == "initial_admin_password"]
            assert entry["file"] is None
            await sign_in(client, "admin", entry["password"])


async def test_start_up_skips_the_step_while_the_schema_is_behind(empty_database, tmp_path):
    settings = Settings(_env_file=None, database_url=empty_database, data_dir=tmp_path)

    async with client_for(create_app(settings)) as client:
        assert (await client.get("/api/v1/status/live")).status_code == 200

    assert not password_file(settings).exists()


async def test_first_start_happens_once_a_late_migration_finishes(
    empty_database, tmp_path, monkeypatch
):
    monkeypatch.setattr("megooarti.main._FIRST_START_RETRY_SECONDS", 0.05)
    settings = Settings(_env_file=None, database_url=empty_database, data_dir=tmp_path)

    async with client_for(create_app(settings)):
        assert not password_file(settings).exists()
        await asyncio.to_thread(command.upgrade, alembic_config(empty_database), "head")
        for _ in range(100):
            if password_file(settings).exists():
                break
            await asyncio.sleep(0.05)

        assert password_file(settings).exists()
