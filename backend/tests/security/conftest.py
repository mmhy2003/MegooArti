from datetime import UTC, datetime
from typing import Any

import pytest

from megooarti.security import oidc, sources
from megooarti.security.models import AuthSource, User
from tests.security.directory import SECRET, Directory, Portal
from tests.security.provider import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def dana(db) -> User:
    user = User(username="dana", display_name="Dana")
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
def kinds(monkeypatch) -> dict[str, sources.Kind]:
    """The kinds of source of the tests, in place of whatever the server has."""
    registered = {kind.name: kind for kind in (Directory(), Portal())}
    monkeypatch.setattr(sources, "KINDS", registered)
    return registered


@pytest.fixture
def add_source(sessionmaker, settings, kinds):
    """Keep a source of a test kind, enabled and asked after those before it."""

    async def add(
        name: str,
        people: dict[str, Any] | None = None,
        *,
        kind: str = "directory",
        mapping: list[dict[str, Any]] | None = None,
        enabled: bool = True,
        **more: Any,
    ) -> AuthSource:
        sent = {"people": people or {}, "secret": SECRET, **more} if kind == "directory" else more
        async with sessionmaker() as db:
            source = AuthSource(
                kind=kind,
                name=name,
                enabled=enabled,
                position=await sources.next_position(db),
                settings=sources.kept_settings(settings, kinds[kind], sent, None),
                group_mapping=mapping or [],
            )
            db.add(source)
            await db.commit()
            return source

    return add


@pytest.fixture
def change_source(sessionmaker, settings, kinds):
    """Change what a test source says or how it is set, as a directory changes."""

    async def change(source: AuthSource, **changes: Any) -> None:
        async with sessionmaker() as db:
            stored = await db.get(AuthSource, source.id)
            for name in ("enabled", "position", "group_mapping"):
                if name in changes:
                    setattr(stored, name, changes.pop(name))
            if changes:
                kind = kinds[stored.kind]
                sent = {**stored.settings, **changes}
                sent.pop("secret", None)  # the stored one is kept
                stored.settings = sources.kept_settings(settings, kind, sent, stored.settings)
            await db.commit()

    return change


@pytest.fixture
def provider(app):
    """An OIDC provider of the test's own, in place of the outbound client's internet."""
    oidc.forget()
    fake = FakeProvider()
    app.state.http = fake.client()
    yield fake
    oidc.forget()


@pytest.fixture
def add_oidc_source(sessionmaker, settings):
    """Keep an OIDC source of the fake provider, enabled and asked after those before it."""

    async def add(
        name: str = "Corp SSO",
        *,
        enabled: bool = True,
        mapping: list[dict[str, Any]] | None = None,
        **more: Any,
    ) -> AuthSource:
        sent = {"issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, **more}
        async with sessionmaker() as db:
            source = AuthSource(
                kind="oidc",
                name=name,
                enabled=enabled,
                position=await sources.next_position(db),
                settings=sources.kept_settings(settings, sources.KINDS["oidc"], sent, None),
                group_mapping=mapping or [],
            )
            db.add(source)
            await db.commit()
            return source

    return add
