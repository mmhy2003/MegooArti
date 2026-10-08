import pytest
from pydantic import ValidationError

from megooarti.config import ConfigurationError, Settings, get_settings, load_settings

VALID_URL = "postgresql://megooarti:s3cret@db:5432/megooarti"


@pytest.mark.parametrize(
    "given",
    [
        "postgres://u:p@db:5432/m",
        "postgresql://u:p@db:5432/m",
        "postgresql+asyncpg://u:p@db:5432/m",
    ],
)
def test_database_url_is_normalised_to_the_asyncpg_driver(given):
    settings = Settings(_env_file=None, database_url=given)
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/m"


@pytest.mark.parametrize("given", ["mysql://u:hunter2@db/m", "not a url", ""])
def test_non_postgres_url_is_rejected_without_echoing_it(given):
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, database_url=given)
    assert "database_url" in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_defaults():
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert settings.log_level == "INFO"
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.forwarded_allow_ips == "127.0.0.1"
    assert settings.shutdown_grace_seconds == 30
    assert settings.db_wait_timeout_seconds == 60


def test_values_come_from_prefixed_environment_variables(monkeypatch):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("MEGOOARTI_PORT", "9000")
    monkeypatch.setenv("MEGOOARTI_LOG_LEVEL", "debug")
    settings = Settings(_env_file=None)
    assert settings.port == 9000
    assert settings.log_level == "DEBUG"


def test_unknown_log_level_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=VALID_URL, log_level="chatty")


def test_load_settings_names_the_missing_environment_variable(monkeypatch, tmp_path):
    monkeypatch.delenv("MEGOOARTI_DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # a directory with no .env file
    with pytest.raises(ConfigurationError, match="MEGOOARTI_DATABASE_URL"):
        load_settings()


def test_load_settings_never_echoes_a_rejected_url(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "mysql://u:hunter2@db/m")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError) as caught:
        load_settings()
    assert "MEGOOARTI_DATABASE_URL" in str(caught.value)
    assert "hunter2" not in str(caught.value)


def test_get_settings_is_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.chdir(tmp_path)
    assert get_settings() is get_settings()


def test_libpq_sslmode_is_translated_for_the_asyncpg_driver():
    given = "postgresql://u:p@db:5432/m?sslmode=require&application_name=megooarti"
    settings = Settings(_env_file=None, database_url=given)
    assert settings.database_url == (
        "postgresql+asyncpg://u:p@db:5432/m?ssl=require&application_name=megooarti"
    )


def test_whitespace_around_the_database_url_is_ignored():
    settings = Settings(_env_file=None, database_url="  postgresql://u:p@db:5432/m\n")
    assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/m"


def test_identity_defaults():
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert str(settings.data_dir).replace("\\", "/") == "/var/lib/megooarti"
    assert settings.session_idle_seconds == 3600
    assert settings.session_absolute_seconds == 43200
    assert settings.session_cookie_secure is True
    assert settings.login_max_failures == 5
    assert settings.login_failure_window_seconds == 900


def test_identity_settings_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("MEGOOARTI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEGOOARTI_SESSION_COOKIE_SECURE", "false")
    monkeypatch.setenv("MEGOOARTI_LOGIN_MAX_FAILURES", "9")
    settings = Settings(_env_file=None)
    assert settings.data_dir == tmp_path
    assert settings.session_cookie_secure is False
    assert settings.login_max_failures == 9


def test_storage_defaults():
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert settings.compaction_interval_seconds == 3600
    assert settings.blob_grace_seconds == 86400


def test_secret_key_is_unset_by_default_and_read_from_the_environment(monkeypatch):
    assert Settings(_env_file=None, database_url=VALID_URL).secret_key is None

    monkeypatch.setenv("MEGOOARTI_SECRET_KEY", "a long random value")

    assert Settings(_env_file=None, database_url=VALID_URL).secret_key == "a long random value"


def test_the_npm_publish_limit(monkeypatch):
    assert Settings(_env_file=None, database_url=VALID_URL).npm_max_publish_bytes == 104857600

    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("MEGOOARTI_NPM_MAX_PUBLISH_BYTES", "2048")

    assert Settings(_env_file=None).npm_max_publish_bytes == 2048
