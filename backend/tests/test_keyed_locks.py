import asyncio

from megooarti.keyed_locks import KeyedLocks


async def test_holders_of_one_key_take_turns():
    locks, order = KeyedLocks(), []

    async def work(name: str) -> None:
        async with locks.hold("same"):
            order.append(f"{name} in")
            await asyncio.sleep(0.02)
            order.append(f"{name} out")

    await asyncio.gather(work("a"), work("b"))

    assert order == ["a in", "a out", "b in", "b out"]


async def test_holders_of_different_keys_do_not_wait_for_each_other():
    locks, order = KeyedLocks(), []

    async def work(key: str) -> None:
        async with locks.hold(key):
            order.append(f"{key} in")
            await asyncio.sleep(0.02)
            order.append(f"{key} out")

    await asyncio.gather(work("one"), work("two"))

    assert order[:2] == ["one in", "two in"]


async def test_nothing_is_kept_once_a_key_is_released_even_after_an_error():
    locks = KeyedLocks()

    async with locks.hold("a"):
        assert len(locks) == 1
    try:
        async with locks.hold("b"):
            raise RuntimeError("the work failed")
    except RuntimeError:
        pass

    assert len(locks) == 0
