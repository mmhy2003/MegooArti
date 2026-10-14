"""A repository whose format writes its indexes counts its changes, and is read whole."""

import hashlib
import uuid

import pytest
from sqlalchemy import select

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


async def test_a_snapshot_is_read_again_when_a_change_came_while_it_was_read(
    db, files, indexed, monkeypatch
):
    context = await indexed()
    await context.put("a.txt", body(b"one"))
    await db.commit()
    asked = []
    revision = type(context).revision

    async def changing(self):
        asked.append(1)
        if len(asked) == 2:  # between the first reading of the files and the check
            await self.put("b.txt", body(b"two"))
            await self.db.commit()
        return await revision(self)

    monkeypatch.setattr(type(context), "revision", changing)

    snapshot = await context.snapshot()

    assert [held.path for held in snapshot.files] == ["a.txt", "b.txt"]
    assert snapshot.revision == 2
    assert len(asked) == 4


async def test_a_repository_that_never_stops_changing_is_answered_busy(db, indexed, monkeypatch):
    context = await indexed()
    count = iter(range(100))

    async def always_new(self):
        return next(count), utcnow()

    monkeypatch.setattr(type(context), "revision", always_new)

    with pytest.raises(ApiError) as refused:
        await context.snapshot()

    assert (refused.value.status_code, refused.value.code) == (503, "repository_busy")


def test_written_indexes_are_kept_by_repository_and_revision_until_more_are_written():
    derived.forget()
    first, second = uuid.uuid4(), uuid.uuid4()

    derived.put(first, 1, {"Release": b"one"})
    for revision in range(derived.MOST):
        derived.put(second, revision, {"Release": b"other"})

    assert derived.get(first, 1) is None  # the least recently used went first
    assert derived.get(second, derived.MOST - 1) == {"Release": b"other"}
    assert derived.get(second, derived.MOST) is None
    derived.forget()
