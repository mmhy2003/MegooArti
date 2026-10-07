from datetime import timedelta

from megooarti.security import throttle
from tests.security.conftest import NOW

LIMITS = {"max_failures": 3, "window_seconds": 900}
BOTH = ["user:dana", "ip:10.0.0.1"]


async def fail(db, subjects, times, now=NOW):
    for _ in range(times):
        await throttle.record_failure(db, subjects, now=now, window_seconds=900)


def test_subjects():
    assert throttle.subjects("dana", "10.0.0.1") == BOTH
    assert throttle.subjects(None, "10.0.0.1") == ["ip:10.0.0.1"]
    assert throttle.subjects("x" * 200, "10.0.0.1")[0] == "user:" + "x" * 64


async def test_nothing_recorded_means_not_blocked(db):
    assert await throttle.standing(db, BOTH, now=NOW, **LIMITS) == throttle.Standing(0, False)


async def test_blocked_once_the_limit_is_reached_until_the_window_ends(db):
    await fail(db, BOTH, 2)
    assert (await throttle.standing(db, BOTH, now=NOW, **LIMITS)).blocked_for == 0

    await fail(db, BOTH, 1, now=NOW + timedelta(seconds=100))
    later = NOW + timedelta(seconds=300)

    assert await throttle.standing(db, BOTH, now=later, **LIMITS) == throttle.Standing(600, True)
    at_end = NOW + timedelta(seconds=900)
    assert (await throttle.standing(db, BOTH, now=at_end, **LIMITS)).blocked_for == 0


async def test_one_blocked_subject_is_enough(db):
    await fail(db, ["ip:10.0.0.1"], 3)

    assert (await throttle.standing(db, BOTH, now=NOW, **LIMITS)).blocked_for == 900
    assert (await throttle.standing(db, ["user:dana"], now=NOW, **LIMITS)).blocked_for == 0


async def test_a_failure_after_the_window_starts_a_new_count(db):
    await fail(db, BOTH, 3)
    after = NOW + timedelta(seconds=901)

    await fail(db, BOTH, 1, now=after)

    assert await throttle.standing(db, BOTH, now=after, **LIMITS) == throttle.Standing(0, True)


async def test_clear_forgets_the_given_subjects_only(db):
    await fail(db, BOTH, 3)

    await throttle.clear(db, ["user:dana"])

    assert (await throttle.standing(db, ["user:dana"], now=NOW, **LIMITS)).has_failures is False
    assert (await throttle.standing(db, ["ip:10.0.0.1"], now=NOW, **LIMITS)).blocked_for == 900


async def test_recording_a_failure_discards_other_expired_windows(db):
    await fail(db, ["ip:10.9.9.9"], 1)
    after = NOW + timedelta(seconds=901)

    await fail(db, ["user:dana"], 1, now=after)

    assert not (await throttle.standing(db, ["ip:10.9.9.9"], now=after, **LIMITS)).has_failures
