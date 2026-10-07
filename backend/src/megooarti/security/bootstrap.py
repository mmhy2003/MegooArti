"""First start: give the built-in administrator a random password."""

import asyncio
import os
import secrets
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from megooarti.config import Settings
from megooarti.db.schema import current_revision
from megooarti.security.models import User
from megooarti.security.passwords import hash_password

log = structlog.get_logger(__name__)

_FILE_NAME = "admin.password"


class SchemaNotReady(RuntimeError):
    """The database has not been migrated to this version yet."""


def password_file(settings: Settings) -> Path:
    return settings.data_dir / _FILE_NAME


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content + "\n")


async def ensure_initial_admin_password(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, head_revision: str
) -> None:
    """Set a random password for `admin` if it has none. Safe to call on every start.

    Raises SchemaNotReady while migrations have not been applied; the caller retries.
    """
    async with sessionmaker() as db:
        if await current_revision(await db.connection()) != head_revision:
            raise SchemaNotReady("the schema is not at head")
        # The row lock makes several containers starting together take turns here.
        admin = await db.scalar(
            select(User).where(User.username == "admin", User.builtin.is_(True)).with_for_update()
        )
        if admin is None or admin.password_hash is not None:
            return

        password = secrets.token_urlsafe(18)
        admin.password_hash = await asyncio.to_thread(hash_password, password)
        admin.must_change_password = True
        path = password_file(settings)
        written: str | None = str(path)
        try:
            _write_private(path, password)
        except OSError as error:
            written = None
            log.warning(
                "initial_admin_password_file_not_written",
                file=str(path),
                error=type(error).__name__,
            )
        await db.commit()
        # SEC-2 requires the password in the start-up log. It must be changed at first
        # sign-in, after which this line is useless to a reader.
        log.warning("initial_admin_password", username="admin", password=password, file=written)


def discard_initial_password(settings: Settings, user: User) -> None:
    """Remove the first-start password file once the administrator has a new password."""
    if not (user.builtin and user.username == "admin"):
        return
    try:
        password_file(settings).unlink(missing_ok=True)
    except OSError as error:
        log.warning("initial_admin_password_file_not_removed", error=type(error).__name__)
