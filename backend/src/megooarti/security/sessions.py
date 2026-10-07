"""Server-side sessions for the web UI."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.security.keys import hash_secret, new_secret
from megooarti.security.models import UserSession

_TOUCH_INTERVAL = timedelta(seconds=60)


async def create_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    ip: str,
    user_agent: str | None,
    now: datetime,
    lifetime_seconds: int,
) -> tuple[UserSession, str]:
    """Start a session. Returns the record and the cookie value, which is not stored."""
    await db.execute(delete(UserSession).where(UserSession.expires_at <= now))
    value = new_secret()
    record = UserSession(
        token_hash=hash_secret(value),
        csrf_token=new_secret(),
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=lifetime_seconds),
        ip=ip[:45],
        user_agent=(user_agent or "")[:255],
    )
    db.add(record)
    await db.flush()
    return record, value


async def find_session(
    db: AsyncSession, value: str, *, now: datetime, idle_seconds: int
) -> UserSession | None:
    record = await db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_secret(value))
    )
    if record is None or record.expires_at <= now:
        return None
    if record.last_seen_at + timedelta(seconds=idle_seconds) < now:
        return None
    return record


def touch(record: UserSession, now: datetime) -> None:
    """Note activity, writing at most once a minute per session."""
    if now - record.last_seen_at >= _TOUCH_INTERVAL:
        record.last_seen_at = now


async def delete_session(db: AsyncSession, record: UserSession) -> None:
    await db.delete(record)
    await db.flush()


async def delete_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, keep_session_id: uuid.UUID | None = None
) -> None:
    statement = delete(UserSession).where(UserSession.user_id == user_id)
    if keep_session_id is not None:
        statement = statement.where(UserSession.id != keep_session_id)
    await db.execute(statement)
