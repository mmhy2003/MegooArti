"""Counters of failed sign-ins, kept in the database so every container shares them.

A subject is `user:<username>` or `ip:<address>`. Each subject has one fixed window that
starts at its first failure.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.security.models import LoginFailure


@dataclass(frozen=True)
class Standing:
    blocked_for: int  # seconds until another attempt is allowed; 0 when not blocked
    has_failures: bool


def subjects(username: str | None, ip: str) -> list[str]:
    found = [f"ip:{ip}"]
    if username:
        found.insert(0, f"user:{username[:64]}")
    return found


async def standing(
    db: AsyncSession,
    subjects: list[str],
    *,
    now: datetime,
    max_failures: int,
    window_seconds: int,
) -> Standing:
    window = timedelta(seconds=window_seconds)
    rows = (
        await db.execute(
            select(LoginFailure.window_started_at, LoginFailure.count).where(
                LoginFailure.subject.in_(subjects)
            )
        )
    ).all()
    waits = [
        (started + window - now).total_seconds()
        for started, count in rows
        if count >= max_failures and started + window > now
    ]
    return Standing(blocked_for=math.ceil(max(waits)) if waits else 0, has_failures=bool(rows))


async def record_failure(
    db: AsyncSession, subjects: list[str], *, now: datetime, window_seconds: int
) -> None:
    # Expired windows are deleted first, so a row that is then incremented is always
    # inside its window and a plain increment is correct.
    cutoff = now - timedelta(seconds=window_seconds)
    await db.execute(delete(LoginFailure).where(LoginFailure.window_started_at <= cutoff))
    for subject in subjects:
        statement = insert(LoginFailure).values(subject=subject, window_started_at=now, count=1)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[LoginFailure.subject],
                set_={"count": LoginFailure.count + 1},
            )
        )


async def clear(db: AsyncSession, subjects: list[str]) -> None:
    await db.execute(delete(LoginFailure).where(LoginFailure.subject.in_(subjects)))
