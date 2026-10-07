import time

import pytest
from sqlalchemy.engine import make_url

from megooarti.config import ConfigurationError
from megooarti.db import wait
from megooarti.db.wait import wait_for_database

NOWHERE = "postgresql+asyncpg://megooarti:megooarti@127.0.0.1:1/megooarti"


async def test_returns_once_the_database_accepts_connections(database_url):
    await wait_for_database(database_url, timeout_seconds=10)


async def test_gives_up_after_the_timeout():
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="not reachable after 1.5s"):
        await wait_for_database(NOWHERE, timeout_seconds=1.5, interval_seconds=0.2)

    assert time.monotonic() - started < 10


async def test_keeps_trying_until_the_database_appears(monkeypatch):
    attempts = []

    async def flaky(engine) -> None:
        attempts.append(engine)
        if len(attempts) < 3:
            raise ConnectionRefusedError("not yet")

    monkeypatch.setattr(wait, "_attempt", flaky)

    await wait_for_database(NOWHERE, timeout_seconds=10, interval_seconds=0.01)

    assert len(attempts) == 3


def test_command_exits_non_zero_with_a_readable_message(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", NOWHERE)
    monkeypatch.setenv("MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS", "0.5")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        wait.main()

    assert "megooarti: database not reachable after 0.5s" in str(stopped.value)


def test_command_reports_missing_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("MEGOOARTI_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        wait.main()

    assert "MEGOOARTI_DATABASE_URL" in str(stopped.value)


def with_changes(url: str, **changes: str) -> str:
    return make_url(url).set(**changes).render_as_string(hide_password=False)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"password": "wrong"}, "rejected the credentials"),
        ({"database": "no_such_database"}, "does not exist"),
        ({"query": {"bogus_option": "1"}}, "option the driver does not accept"),
    ],
)
async def test_fails_at_once_when_waiting_cannot_help(database_url, changes, message):
    started = time.monotonic()

    with pytest.raises(ConfigurationError, match=message) as caught:
        await wait_for_database(with_changes(database_url, **changes), timeout_seconds=30)

    assert time.monotonic() - started < 10
    assert "MEGOOARTI_DATABASE_URL" in str(caught.value)
    assert "wrong" not in str(caught.value)
