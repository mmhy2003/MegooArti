from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from megooarti.repositories import proxy_state, service
from megooarti.repositories.models import NegativeCacheEntry, ProxyState

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REMOTE = {"remote_url": "http://remote.test/files"}


def after(seconds: int) -> datetime:
    return NOW + timedelta(seconds=seconds)


async def fail(db, repository, when=NOW, *, blockable=True, reason="ConnectError"):
    await proxy_state.record_failure(db, repository, when, reason, blockable=blockable)


async def reconfigure(db, repository, **settings):
    await service.update_repository(db, repository, online=True, proxy={**REMOTE, **settings})


@pytest.mark.parametrize(
    ("failures", "seconds"), [(1, 60), (2, 120), (3, 240), (6, 1920), (7, 3600), (40, 3600)]
)
def test_the_block_doubles_from_a_minute_up_to_an_hour(failures, seconds):
    assert proxy_state.block_seconds(failures) == seconds


async def test_a_proxy_starts_unblocked(db, mirror):
    assert await proxy_state.blocked(db, mirror, NOW) is False


async def test_a_failure_blocks_for_a_minute_and_records_what_happened(db, mirror):
    await fail(db, mirror)

    state = await db.get(ProxyState, mirror.id)

    assert (state.failures, state.last_error, state.last_checked_at) == (1, "ConnectError", NOW)
    assert state.blocked_until == after(60)
    assert await proxy_state.blocked(db, mirror, after(59)) is True
    assert await proxy_state.blocked(db, mirror, after(60)) is False


async def test_consecutive_failures_lengthen_the_block(db, mirror):
    await fail(db, mirror)
    await fail(db, mirror, after(60))
    await fail(db, mirror, after(180))

    state = await db.get(ProxyState, mirror.id)

    assert state.failures == 3
    assert state.blocked_until == after(180 + 240)


async def test_a_failure_that_is_not_blockable_is_recorded_without_blocking(db, mirror):
    await fail(db, mirror, blockable=False, reason="the remote answered 401")

    state = await db.get(ProxyState, mirror.id)

    assert (state.failures, state.blocked_until) == (0, None)
    assert state.last_error == "the remote answered 401"
    assert await proxy_state.blocked(db, mirror, NOW) is False


async def test_auto_block_can_be_turned_off(db, mirror):
    await reconfigure(db, mirror, auto_block=False)

    await fail(db, mirror)

    assert await proxy_state.blocked(db, mirror, NOW) is False
    assert (await db.get(ProxyState, mirror.id)).last_error == "ConnectError"


async def test_a_success_clears_the_block(db, mirror):
    await fail(db, mirror)
    await fail(db, mirror, after(60))

    await proxy_state.record_success(db, mirror, after(61))

    state = await db.get(ProxyState, mirror.id, populate_existing=True)
    assert (state.failures, state.blocked_until, state.last_error) == (0, None, None)
    assert await proxy_state.blocked(db, mirror, after(61)) is False


async def test_a_success_with_nothing_recorded_is_harmless(db, mirror):
    await proxy_state.record_success(db, mirror, NOW)

    assert await db.get(ProxyState, mirror.id) is None


async def test_a_proxy_blocked_by_hand_stays_blocked(db, mirror):
    await reconfigure(db, mirror, blocked=True)

    assert await proxy_state.blocked(db, mirror, after(10**6)) is True


async def test_a_long_reason_is_shortened_to_fit(db, mirror):
    await fail(db, mirror, reason="x" * 1000)

    assert len((await db.get(ProxyState, mirror.id)).last_error) == 255


async def test_a_missing_path_is_remembered_until_it_expires(db, mirror):
    await reconfigure(db, mirror, negative_cache={"ttl_minutes": 10})

    await proxy_state.remember_missing(db, mirror, "nothing/here.bin", NOW)

    assert await proxy_state.known_missing(db, mirror, "nothing/here.bin", after(599)) is True
    assert await proxy_state.known_missing(db, mirror, "nothing/here.bin", after(600)) is False
    assert await proxy_state.known_missing(db, mirror, "something/else.bin", NOW) is False


async def test_remembering_again_extends_the_time(db, mirror):
    await reconfigure(db, mirror, negative_cache={"ttl_minutes": 10})
    await proxy_state.remember_missing(db, mirror, "a.bin", NOW)

    await proxy_state.remember_missing(db, mirror, "a.bin", after(300))

    assert await proxy_state.known_missing(db, mirror, "a.bin", after(899)) is True


async def test_nothing_is_remembered_when_the_negative_cache_is_off(db, mirror):
    await reconfigure(db, mirror, negative_cache={"enabled": False})

    await proxy_state.remember_missing(db, mirror, "a.bin", NOW)

    assert await proxy_state.known_missing(db, mirror, "a.bin", NOW) is False


async def test_failures_that_arrive_while_blocked_do_not_lengthen_the_block(db, mirror):
    # Several requests in flight when the remote fails are one blip, not several.
    await fail(db, mirror)
    await fail(db, mirror, after(1))
    await fail(db, mirror, after(2), reason="ReadTimeout")

    state = await db.get(ProxyState, mirror.id)

    assert (state.failures, state.blocked_until) == (1, after(60))
    assert state.last_error == "ReadTimeout"


async def test_turning_auto_block_off_lifts_a_block_already_in_place(db, mirror):
    await fail(db, mirror)
    settings = {**mirror.config["proxy"], "auto_block": False}
    mirror.config = {**mirror.config, "proxy": settings}

    assert await proxy_state.blocked(db, mirror, after(1)) is False


async def test_remembering_a_miss_clears_out_this_repositorys_expired_entries(db, mirror):
    await reconfigure(db, mirror, negative_cache={"ttl_minutes": 10})
    other = await service.create_repository(
        db,
        name="other",
        format="raw",
        type="proxy",
        online=True,
        blob_store=None,
        proxy={**REMOTE, "negative_cache": {"ttl_minutes": 10}},
    )
    await proxy_state.remember_missing(db, mirror, "old.bin", NOW)
    await proxy_state.remember_missing(db, other, "theirs.bin", NOW)

    await proxy_state.remember_missing(db, mirror, "new.bin", after(601))

    remaining = await db.execute(
        select(NegativeCacheEntry.repository_id, NegativeCacheEntry.path).order_by(
            NegativeCacheEntry.path
        )
    )
    assert [tuple(row) for row in remaining] == [(mirror.id, "new.bin"), (other.id, "theirs.bin")]
