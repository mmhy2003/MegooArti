import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.clock import utcnow
from megooarti.db.schema import head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.security import reset_admin as module
from megooarti.security.bootstrap import SchemaNotReady, password_file
from megooarti.security.models import LoginFailure, User
from megooarti.security.reset_admin import reset_admin
from megooarti.system.audit import SYSTEM
from tests.accounts import sign_in
from tests.audit import last


async def reset(sessionmaker, settings) -> str:
    return await reset_admin(sessionmaker, settings, head_revision())


async def test_the_administrator_signs_in_with_a_new_password_to_change(
    client, sessionmaker, settings
):
    first = password_file(settings).read_text(encoding="utf-8").strip()

    password = await reset(sessionmaker, settings)

    assert password != first
    assert len(password) >= 20
    assert password_file(settings).read_text(encoding="utf-8").strip() == password
    refused = await client.post("/api/v1/auth/login", json={"username": "admin", "password": first})
    assert refused.status_code == 401
    signed_in = await sign_in(client, "admin", password)
    assert signed_in["must_change_password"] is True


async def test_a_disabled_administrator_is_active_again(client, db, sessionmaker, settings):
    admin = await db.scalar(select(User).where(User.username == "admin"))
    admin.status = "disabled"
    await db.commit()

    password = await reset(sessionmaker, settings)

    await sign_in(client, "admin", password)


async def test_sign_in_blocks_are_lifted(client, db, sessionmaker, settings):
    for subject in ("user:admin", "ip:127.0.0.1"):
        db.add(LoginFailure(subject=subject, window_started_at=utcnow(), count=1000))
    await db.commit()

    password = await reset(sessionmaker, settings)

    assert list(await db.scalars(select(LoginFailure.subject))) == []
    await sign_in(client, "admin", password)


async def test_the_administrators_sessions_end(client, sessionmaker, settings):
    first = password_file(settings).read_text(encoding="utf-8").strip()
    await sign_in(client, "admin", first)
    assert (await client.get("/api/v1/me")).status_code == 200

    await reset(sessionmaker, settings)

    assert (await client.get("/api/v1/me")).status_code == 401


async def test_the_reset_is_recorded_as_the_systems(client, sessionmaker, settings):
    await reset(sessionmaker, settings)

    record = await last(sessionmaker, "user.password_changed")
    assert record.target_name == "admin"
    assert record.actor is None
    assert record.method == SYSTEM
    assert "password" in record.changes


async def test_nothing_changes_while_the_schema_is_behind(empty_database, settings):
    engine = create_async_engine(empty_database, poolclass=NullPool)
    try:
        with pytest.raises(SchemaNotReady):
            await reset_admin(create_sessionmaker(engine), settings, head_revision())
    finally:
        await engine.dispose()
    assert not password_file(settings).exists()


def test_the_command_prints_the_new_password(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "postgresql://u:p@db:5432/m")
    monkeypatch.setenv("MEGOOARTI_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    async def reset_admin(sessionmaker, settings, head):
        return "the-new-password"

    monkeypatch.setattr(module, "reset_admin", reset_admin)

    module.main()

    out = capsys.readouterr().out
    assert "the-new-password" in out
    assert "admin" in out


def test_the_command_says_why_it_failed(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "postgresql://u:p@db:5432/m")
    monkeypatch.chdir(tmp_path)

    async def reset_admin(sessionmaker, settings, head):
        raise SchemaNotReady("the schema is not at head")

    monkeypatch.setattr(module, "reset_admin", reset_admin)

    with pytest.raises(SystemExit) as stopped:
        module.main()

    assert "migrat" in str(stopped.value)
