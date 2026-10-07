from datetime import timedelta

from sqlalchemy import func, select

from megooarti.security import sessions
from megooarti.security.models import UserSession
from tests.security.conftest import NOW

HOUR = 3600


async def start(db, user, now=NOW, lifetime_seconds=12 * HOUR):
    return await sessions.create_session(
        db, user.id, ip="10.0.0.1", user_agent="pytest", now=now, lifetime_seconds=lifetime_seconds
    )


async def count(db) -> int:
    return await db.scalar(select(func.count()).select_from(UserSession))


async def test_a_session_is_found_by_its_value_but_stores_only_a_hash(db, dana):
    record, value = await start(db, dana)

    found = await sessions.find_session(db, value, now=NOW, idle_seconds=HOUR)

    assert found.id == record.id
    assert record.token_hash != value
    assert value not in (record.token_hash, record.csrf_token)
    assert len(record.csrf_token) == 43
    assert await sessions.find_session(db, "wrong", now=NOW, idle_seconds=HOUR) is None


async def test_a_session_ends_after_the_idle_limit(db, dana):
    _, value = await start(db, dana)

    just_inside = NOW + timedelta(seconds=HOUR)
    just_outside = NOW + timedelta(seconds=HOUR + 1)

    assert await sessions.find_session(db, value, now=just_inside, idle_seconds=HOUR)
    assert await sessions.find_session(db, value, now=just_outside, idle_seconds=HOUR) is None


async def test_a_session_ends_at_the_absolute_limit_even_if_active(db, dana):
    record, value = await start(db, dana, lifetime_seconds=2 * HOUR)
    record.last_seen_at = NOW + timedelta(seconds=2 * HOUR - 1)
    await db.flush()

    at_limit = NOW + timedelta(seconds=2 * HOUR)

    assert await sessions.find_session(db, value, now=at_limit, idle_seconds=HOUR) is None


async def test_touch_moves_last_seen_at_most_once_a_minute(db, dana):
    record, _ = await start(db, dana)

    sessions.touch(record, NOW + timedelta(seconds=59))
    assert record.last_seen_at == NOW

    sessions.touch(record, NOW + timedelta(seconds=60))
    assert record.last_seen_at == NOW + timedelta(seconds=60)


async def test_creating_a_session_removes_expired_ones(db, dana):
    await start(db, dana, lifetime_seconds=HOUR)
    assert await count(db) == 1

    await start(db, dana, now=NOW + timedelta(seconds=HOUR + 1))

    assert await count(db) == 1


async def test_delete_user_sessions_can_keep_one(db, dana):
    keep, _ = await start(db, dana)
    await start(db, dana)

    await sessions.delete_user_sessions(db, dana.id, keep_session_id=keep.id)
    assert await db.scalar(select(UserSession.id)) == keep.id

    await sessions.delete_user_sessions(db, dana.id)
    assert await count(db) == 0
