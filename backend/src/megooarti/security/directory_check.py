"""The hourly check of LDAP sources' users (spec 7, D4): each one is looked up by their DN,
and one the directory no longer gives as a user (gone, moved out of the users' base, or
no longer matching the filter) is disabled, their sessions ended and their tokens refused
with them. A directory that cannot be asked, or that seems to have lost everyone at once,
disables nobody."""

from typing import Any

import structlog
from sqlalchemy import select

from megooarti.security import ldap, sources
from megooarti.security.models import User
from megooarti.security.sessions import delete_user_sessions

log = structlog.get_logger(__name__)

CHECK_SECONDS = 3600
# Arbitrary constant, distinct from the other advisory lock keys.
LOCK_KEY = 0x4D45474F52


async def run(app: Any) -> int:
    """Check every enabled LDAP source's active users; how many were disabled. A failure is
    one source's: the others are checked all the same."""
    reach = sources.outbound(app)
    async with app.state.sessionmaker() as db:
        checked = [
            (source.id, source.name)
            for source in await sources.in_order(db)
            if source.enabled and source.kind == ldap.KIND
        ]
    disabled = 0
    for source_id, name in checked:
        try:
            disabled += await _check(app, reach, source_id)
        except Exception as error:  # noqa: BLE001  (logged, and the next source is checked)
            log.warning(
                "directory_check_skipped", source=name, error=f"{type(error).__name__}: {error}"
            )
    return disabled


async def _check(app: Any, reach: sources.Outbound, source_id: Any) -> int:
    # Read what is asked, and let go of the database while the directory answers.
    async with app.state.sessionmaker() as db:
        source = await sources.get_source(db, source_id)
        if source is None or not source.enabled:
            return 0  # deleted or turned off since
        name = source.name
        settings = sources.opened_settings(
            app.state.settings, sources.KINDS[ldap.KIND], source.settings
        )
        users = {
            user_id: dn
            for user_id, dn in await db.execute(
                select(User.id, User.external_id).where(
                    User.source_id == source.id, User.status == "active"
                )
            )
        }
    if not users:
        return 0
    gone = set(
        await ldap.in_thread(
            ldap.missing, settings, ldap.context_for(reach.trusted), list(users.values())
        )
    )
    if len(users) > 1 and len(gone) == len(users):
        log.warning("directory_check_skipped", source=name, error="every user seems gone at once")
        return 0
    leaving = [user_id for user_id, dn in users.items() if dn in gone]
    if not leaving:
        return 0
    async with app.state.sessionmaker() as db:
        found = list(
            await db.scalars(select(User).where(User.id.in_(leaving), User.status == "active"))
        )
        for user in found:
            user.status = "disabled"
            await delete_user_sessions(db, user.id)
            log.info("directory_user_gone", username=user.username, source=name)
        await db.commit()
    return len(found)
