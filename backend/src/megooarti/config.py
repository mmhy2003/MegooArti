"""Deployment configuration, read from MEGOOARTI_* environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ENV_PREFIX = "MEGOOARTI_"
_POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+asyncpg"}


class ConfigurationError(RuntimeError):
    """The environment does not describe a valid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,  # the database URL contains a password
    )

    database_url: str
    # The password of that address, when it is kept apart from it. An address gives
    # a meaning to some characters (@ / # ? %); apart, a password may hold any.
    database_password: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000
    forwarded_allow_ips: str = "127.0.0.1"
    shutdown_grace_seconds: int = 30
    db_wait_timeout_seconds: float = 60
    data_dir: Path = Path("/var/lib/megooarti")
    session_idle_seconds: int = 3600
    session_absolute_seconds: int = 43200
    session_cookie_secure: bool = True
    login_max_failures: int = 5
    login_failure_window_seconds: int = 900
    compaction_interval_seconds: int = 3600
    blob_grace_seconds: int = 86400
    secret_key: str | None = None
    npm_max_publish_bytes: int = 100 * 1024 * 1024

    @field_validator("database_url")
    @classmethod
    def _use_the_asyncpg_driver(cls, value: str) -> str:
        scheme, separator, rest = value.strip().partition("://")
        if not separator or scheme not in _POSTGRES_SCHEMES:
            raise ValueError(
                "must be a PostgreSQL URL such as postgresql://user:password@host:5432/dbname"
            )
        location, has_query, query = rest.partition("?")
        if has_query:
            # Managed PostgreSQL services hand out libpq URLs; asyncpg calls sslmode "ssl".
            options = [
                ("ssl" if name == "sslmode" else name, option)
                for name, option in parse_qsl(query, keep_blank_values=True)
            ]
            rest = f"{location}?{urlencode(options)}"
        return f"postgresql+asyncpg://{rest}"

    @model_validator(mode="after")
    def _put_the_password_into_the_address(self) -> "Settings":
        if self.database_password:
            address = make_url(self.database_url).set(password=self.database_password)
            self.database_url = address.render_as_string(hide_password=False)
        return self

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_case_the_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


def load_settings() -> Settings:
    """Read settings from the environment, reporting problems by variable name."""
    try:
        return Settings()
    except ValidationError as error:
        problems = "; ".join(
            f"{ENV_PREFIX}{'_'.join(str(part) for part in item['loc']).upper()}: {item['msg']}"
            for item in error.errors()
        )
        raise ConfigurationError(f"invalid configuration: {problems}") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
