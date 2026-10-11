import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from megooarti import secrets_box
from megooarti.config import Settings
from megooarti.secrets_box import Sealed, SecretUnreadable, seal, unseal

SECRET = "the remote's password ✓"


def settings_in(directory, **overrides) -> Settings:
    return Settings(
        _env_file=None, database_url="postgresql://u:p@db/m", data_dir=directory, **overrides
    )


@pytest.fixture(autouse=True)
def _no_cached_keys():
    secrets_box.forget_keys()
    yield
    secrets_box.forget_keys()


def test_a_sealed_secret_can_be_unsealed(tmp_path):
    settings = settings_in(tmp_path)

    sealed = seal(settings, SECRET)

    assert isinstance(sealed, Sealed)
    assert unseal(settings, sealed) == SECRET


def test_sealed_text_is_marked_differs_each_time_and_hides_the_secret(tmp_path):
    settings = settings_in(tmp_path)

    first, second = seal(settings, SECRET), seal(settings, SECRET)

    assert first.startswith("enc:v1:")
    assert first != second
    assert "password" not in first


def test_a_key_is_generated_once_and_reused_after_a_restart(tmp_path):
    settings = settings_in(tmp_path)
    sealed = seal(settings, SECRET)
    key = (tmp_path / "secret.key").read_bytes()

    secrets_box.forget_keys()  # as after a restart

    assert unseal(settings, sealed) == SECRET
    assert (tmp_path / "secret.key").read_bytes() == key


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_generated_key_is_readable_by_its_owner_only(tmp_path):
    seal(settings_in(tmp_path), SECRET)
    assert (tmp_path / "secret.key").stat().st_mode & 0o777 == 0o600


def test_a_configured_key_is_used_instead_and_no_file_is_written(tmp_path):
    here = settings_in(tmp_path / "one", secret_key="a long random value")
    there = settings_in(tmp_path / "two", secret_key="a long random value")

    sealed = seal(here, SECRET)

    assert unseal(there, sealed) == SECRET
    assert not (tmp_path / "one" / "secret.key").exists()


def test_a_different_key_cannot_unseal(tmp_path):
    sealed = seal(settings_in(tmp_path, secret_key="the first key"), SECRET)

    with pytest.raises(SecretUnreadable):
        unseal(settings_in(tmp_path, secret_key="another key"), sealed)


@pytest.mark.parametrize("stored", ["", "plain text", "enc:v1:", "enc:v1:not-a-token"])
def test_text_that_was_never_sealed_is_unreadable(tmp_path, stored):
    with pytest.raises(SecretUnreadable):
        unseal(settings_in(tmp_path), stored)


def test_a_damaged_key_file_is_reported_at_once(tmp_path):
    (tmp_path / "secret.key").write_bytes(b"")
    started = time.monotonic()

    with pytest.raises(SecretUnreadable, match="secret.key"):
        seal(settings_in(tmp_path), SECRET)

    assert time.monotonic() - started < 2


def test_no_temporary_key_file_is_left_behind(tmp_path):
    seal(settings_in(tmp_path), SECRET)

    assert [path.name for path in tmp_path.iterdir()] == ["secret.key"]


def test_text_sealed_with_the_time_is_read_only_for_so_long(tmp_path):
    settings = settings_in(tmp_path)
    now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)

    sealed = secrets_box.seal_at(settings, SECRET, now)

    assert SECRET not in sealed
    assert secrets_box.unseal_within(settings, sealed, 300, now) == SECRET
    assert secrets_box.unseal_within(settings, sealed, 300, now + timedelta(seconds=300)) == SECRET
    assert secrets_box.unseal_within(settings, sealed, 300, now + timedelta(seconds=301)) is None
    assert secrets_box.unseal_within(settings, sealed, 300, now - timedelta(hours=1)) is None


def test_what_was_not_sealed_here_is_not_read(tmp_path):
    settings = settings_in(tmp_path)
    now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    sealed = secrets_box.seal_at(settings, SECRET, now)
    elsewhere = secrets_box.seal_at(settings_in(tmp_path, secret_key="another key"), SECRET, now)

    for candidate in (sealed[:-3] + "abc", elsewhere, "", "not sealed", "ünïcode"):
        assert secrets_box.unseal_within(settings, candidate, 300, now) is None
