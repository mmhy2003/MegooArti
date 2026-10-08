from datetime import UTC, datetime

from sqlalchemy import insert, select

from megooarti.repositories.models import (
    NegativeCacheEntry,
    ProxyState,
    Repository,
    RepositoryMember,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def repository(db, name: str, type: str) -> Repository:
    row = Repository(name=name, name_key=name, format="raw", type=type)
    db.add(row)
    await db.flush()
    return row


async def test_a_group_keeps_its_members_in_order(db):
    group = await repository(db, "all", "group")
    first = await repository(db, "first", "hosted")
    second = await repository(db, "second", "hosted")
    await db.execute(
        insert(RepositoryMember),
        [
            {"group_id": group.id, "member_id": second.id, "position": 1},
            {"group_id": group.id, "member_id": first.id, "position": 0},
        ],
    )

    ordered = await db.scalars(
        select(RepositoryMember.member_id)
        .where(RepositoryMember.group_id == group.id)
        .order_by(RepositoryMember.position)
    )

    assert list(ordered) == [first.id, second.id]


async def test_proxy_state_starts_with_no_failures(db):
    proxy = await repository(db, "mirror", "proxy")
    db.add(ProxyState(repository_id=proxy.id))
    await db.flush()

    state = await db.get(ProxyState, proxy.id)

    assert (state.failures, state.blocked_until, state.last_error) == (0, None, None)


async def test_negative_cache_entries_are_per_repository_and_path(db):
    proxy = await repository(db, "mirror", "proxy")
    db.add(NegativeCacheEntry(repository_id=proxy.id, path="missing/a.bin", expires_at=NOW))
    await db.flush()

    found = await db.get(NegativeCacheEntry, (proxy.id, "missing/a.bin"))

    assert found.expires_at == NOW
