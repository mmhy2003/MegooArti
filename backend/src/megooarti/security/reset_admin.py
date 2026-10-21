"""`python -m megooarti.security.reset_admin`: let the built-in administrator in again.

For whoever runs the installation and can no longer sign in as `admin`: it gets a new
random password, to be changed at the next sign-in, as at the first start. It is made
active if it was disabled, its sessions end, and every sign-in block is lifted.
"""

import asyncio
import secrets
import sys

from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from megooarti.config import ConfigurationError, Settings, get_settings
from megooarti.db.schema import current_revision, head_revision
from megooarti.db.session import create_sessionmaker
from megooarti.errors import ApiError
from megooarti.security import users
from megooarti.security.bootstrap import SchemaNotReady, password_file, write_private
from megooarti.security.models import LoginFailure, User
from megooarti.system import audit


async def reset_admin(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, head: str
) -> str:
    """Give `admin` a new password and return it. Raises SchemaNotReady before migrations."""
    async with sessionmaker() as db:
        if await current_revision(await db.connection()) != head:
            raise SchemaNotReady("the schema is not at head")
        admin = await db.scalar(
            select(User).where(User.username == "admin", User.builtin.is_(True)).with_for_update()
        )
        if admin is None:
            raise SchemaNotReady("there is no built-in administrator")

        password = secrets.token_urlsafe(18)
        status = admin.status
        admin.status = "active"
        await users.set_password(db, admin, password, must_change_password=True)
        # A block on the address it is reset from would keep it out as long as one on
        # the name: both go, and with them any other.
        await db.execute(delete(LoginFailure))
        audit.record(
            db,
            "user.password_changed",
            ("user", admin.username),
            audit.diff({"status": status}, {"status": "active"}, secrets=["password"]),
        )
        await db.commit()

    try:
        # Where the README says to read it, as after the first start.
        write_private(password_file(settings), password)
    except OSError:
        pass  # it is printed all the same
    return password


async def _run(settings: Settings) -> str:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        return await reset_admin(create_sessionmaker(engine), settings, head_revision())
    finally:
        await engine.dispose()


def main() -> None:
    try:
        settings = get_settings()
        password = asyncio.run(_run(settings))
    except ConfigurationError as error:
        sys.exit(f"megooarti: {error}")
    except SchemaNotReady as error:
        sys.exit(f"megooarti: {error}: start the backend once, which migrates the database")
    except ApiError as error:
        sys.exit(f"megooarti: {error.message}")
    except (OSError, DBAPIError) as error:
        sys.exit(f"megooarti: the database could not be reached ({type(error).__name__})")

    print(f"The password of admin is now: {password}")
    print("Sign in with it and choose another. Its sessions have ended, and no one is")
    print("blocked from signing in any more.")


if __name__ == "__main__":
    main()
