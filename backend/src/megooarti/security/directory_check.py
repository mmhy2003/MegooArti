"""The hourly check of LDAP sources' users (spec 7, D4): each one is looked up by their DN,
and one the directory no longer has is disabled, their sessions ended and their tokens
refused with them. A directory that cannot be asked disables nobody."""

import asyncio
from typing import Any

import structlog
from sqlalchemy import select

from megooarti.secrets_box import SecretUnreadable
from megooarti.security import ldap, sources
from megooarti.security.models import User
from megooarti.security.sessions import delete_user_sessions

log = structlog.get_logger(__name__)

CHECK_SECONDS = 3600
# Arbitrary constant, distinct from the other advisory lock keys.
LOCK_KEY = 0x4D45474F52


async def run(app: Any) -> int:
    """Check every enabled LDAP source's active users; how many were disabled."""
    reach = sources.outbound(app)
    async with app.state.sessionmaker() as db:
        checked = [
            source.id
            for source in await sources.in_order(db)
            if source.enabled and source.kind == ldap.KIND
        ]
    disabled = 0
    for source_id in checked:
        disabled += await _check(app, reach, source_id)
    return disabled


async def _check(app: Any, reach: sources.Outbound, source_id: Any) -> int:
    async with app.state.sessionmaker() as db:
        source = await sources.get_source(db, source_id)
        if source is None or not source.enabled:
            return 0  # deleted or turned off since
        users = list(
            await db.scalars(
                select(User).where(User.source_id == source.id, User.status == "active")
            )
        )
        if not users:
            return 0
        try:
            settings = sources.opened_settings(
                app.state.settings, sources.KINDS[ldap.KIND], source.settings
            )
            gone = set(
                await asyncio.to_thread(
                    ldap.missing,
                    settings,
                    ldap.context_for(reach.trusted),
                    [user.external_id for user in users],
                )
            )
        except (sources.SourceUnavailable, SecretUnreadable) as error:
            log.warning("directory_check_skipped", source=source.name, error=str(error))
            return 0
        for user in users:
            if user.external_id in gone:
                user.status = "disabled"
                await delete_user_sessions(db, user.id)
                log.info("directory_user_gone", username=user.username, source=source.name)
        await db.commit()
        return sum(user.external_id in gone for user in users)
