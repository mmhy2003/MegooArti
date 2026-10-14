"""A repository whose format writes its indexes counts its changes, and is read whole."""

import asyncio
import hashlib
import uuid

import pytest
from sqlalchemy import event, select

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import derived
from megooarti.repositories.content import Held
from megooarti.repositories.models import Repository
from megooarti.repositories.raw import RawFormat
from tests.repositories.conftest import body, someone

EVERYTHING = someone("repository:raw:files")


class Indexed(RawFormat):
    """Raw, as a format that writes its indexes from what a repository holds."""

    derives_indexes = True


@pytest.fixture
def indexed(context_for, files):
    async def make(principal=EVERYTHING):
        context = await context_for(files, principal)
        context.format = Indexed()
        return context

    return make


async def revision_of(db, repository_id) -> int:
    return await db.scalar(
        select(Repository.revision)
        .where(Repository.id == repository_id)
        .execution_options(populate_existing=True)
    )


async def test_each_file_stored_replaced_or_deleted_is_a_revision(db, files, indexed):
    files_id = files.id
    context = await indexed()

    await context.put("a.txt", body(b"one"))
    await db.commit()
    assert await revision_of(db, files_id) == 1
    await context.put("a.txt", body(b"two"))
    await db.commit()
    assert await revision_of(db, files_id) == 2
    assert await context.delete("a.txt") is True
    await db.commit()
    assert await revision_of(db, files_id) == 3


async def test_a_revision_is_dated_when_it_was_made(db, files, indexed):
    context = await indexed()
    assert await context.revision() == (0, files.created_at)
    before = utcnow()

    await context.put("a.txt", body(b"one"))
    await db.commit()

    revision, changed = await context.revision()
    assert revision == 1 and changed >= before


async def test_a_change_that_is_refused_is_no_revision(db, files, indexed):
    files_id = files.id
    context = await indexed(someone("repository:raw:files:read"))

    with pytest.raises(ApiError):
        await context.put("a.txt", body(b"one"))
    await db.rollback()

    assert await revision_of(db, files_id) == 0


async def test_a_repository_whose_format_derives_nothing_counts_nothing(db, files, context_for):
    files_id = files.id
    context = await context_for(files, EVERYTHING)

    await context.put("a.txt", body(b"one"))
    await db.commit()

    assert await revision_of(db, files_id) == 0


async def test_a_snapshot_has_every_file_with_its_checksums_and_attributes(db, files, indexed):
    context = await indexed()
    staged = await context.stage_bytes(b"one")
    await context.store("b/one.txt", staged, attributes={"said": "one"})
    await context.put("a.txt", body(b"two"))
    await db.commit()

    snapshot = await context.snapshot()

    assert snapshot.revision == 2
    assert snapshot.files == [
        Held(
            "a.txt",
            3,
            hashlib.md5(b"two").hexdigest(),
            hashlib.sha1(b"two").hexdigest(),
            hashlib.sha256(b"two").hexdigest(),
            {},
        ),
        Held(
            "b/one.txt",
            3,
            hashlib.md5(b"one").hexdigest(),
            hashlib.sha1(b"one").hexdigest(),
            hashlib.sha256(b"one").hexdigest(),
            {"said": "one"},
        ),
    ]


async def test_a_snapshot_is_read_in_one_statement_so_that_no_change_can_come_between(
    db, files, indexed
):
    context = await indexed()
    await context.put("a.txt", body(b"one"))
    await db.commit()
    statements = []

    def seen(connection, cursor, statement, *rest):
        if not statement.startswith(("SAVEPOINT", "RELEASE SAVEPOINT")):  # the test's own
            statements.append(statement)

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", seen)
    try:
        snapshot = await context.snapshot()
    finally:
        event.remove(engine, "before_cursor_execute", seen)

    assert len(statements) == 1
    assert (snapshot.revision, [held.path for held in snapshot.files]) == (1, ["a.txt"])


async def test_a_snapshot_of_a_repository_that_holds_nothing_has_its_revision(db, files, indexed):
    context = await indexed()

    snapshot = await context.snapshot()

    assert (snapshot.revision, snapshot.changed, snapshot.files) == (0, files.created_at, [])


def written(revision: int, size: int = 10) -> derived.Written:
    return derived.Written(revision, utcnow(), {"Release": bytes(size)})


def test_written_indexes_are_kept_by_repository_and_revision():
    derived.forget()
    first, second = uuid.uuid4(), uuid.uuid4()

    derived.put(first, written(1))
    derived.put(second, written(4))

    assert derived.get(first, 1).revision == 1
    assert derived.get(second, 4).revision == 4
    assert derived.get(first, 2) is None
    derived.forget()


def test_a_newer_revision_takes_the_place_of_the_older_ones_of_its_repository():
    derived.forget()
    repository = uuid.uuid4()

    for revision in range(5):
        derived.put(repository, written(revision))

    assert [derived.get(repository, revision) is None for revision in range(5)] == [
        True,
        True,
        True,
        True,
        False,
    ]
    derived.forget()


def test_what_is_kept_is_bounded_by_its_size_and_the_least_recently_used_goes_first(
    monkeypatch,
):
    derived.forget()
    monkeypatch.setattr(derived, "MOST_BYTES", 25)
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    derived.put(first, written(1))
    derived.put(second, written(1))
    derived.get(first, 1)  # used again: the second is now the least recently used
    derived.put(third, written(1))

    assert derived.get(second, 1) is None
    assert derived.get(first, 1) is not None and derived.get(third, 1) is not None
    derived.forget()


async def test_requests_for_one_revision_at_once_write_it_once():
    derived.forget()
    repository = uuid.uuid4()
    made = []

    async def make() -> derived.Written:
        made.append(1)
        await asyncio.sleep(0.05)
        return written(3)

    results = await asyncio.gather(*(derived.written(repository, 3, make) for _ in range(5)))

    assert len(made) == 1
    assert {result.revision for result in results} == {3}
    assert derived.get(repository, 3) is not None
    derived.forget()


async def test_a_failure_to_write_is_given_to_every_request_that_waited_and_kept_by_none():
    derived.forget()
    repository = uuid.uuid4()

    async def broken() -> derived.Written:
        await asyncio.sleep(0.01)
        raise ApiError(500, "signing_key_unreadable", "No.")

    results = await asyncio.gather(
        *(derived.written(repository, 1, broken) for _ in range(3)), return_exceptions=True
    )

    assert [type(result) for result in results] == [ApiError] * 3
    assert derived.get(repository, 1) is None
    assert derived._writing == {}
    derived.forget()
