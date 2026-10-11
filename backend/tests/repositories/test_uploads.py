import asyncio
import hashlib
import os
import time
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import service, uploads
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Asset, Upload
from megooarti.repositories.uploads import OutOfOrder, Progress, TooManyChunks, UnknownUpload
from megooarti.storage import backends
from tests.repositories.conftest import body, someone
from tests.storage.test_races import Factory, create_files, run

EVERYTHING = someone("repository:raw:files")
LAYER = bytes(range(256)) * 40


@pytest.fixture
async def context(files, context_for):
    return await context_for(files, EVERYTHING)


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def temporary_files(settings) -> list[str]:
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    return [path.name for path in directory.iterdir()] if directory.exists() else []


async def test_an_upload_is_begun_added_to_and_completed(context, db):
    upload = await uploads.begin(context, "app")
    await db.commit()

    first = await uploads.append(context, upload, "app", body(LAYER[:6000]))
    so_far = await uploads.progress(context, upload, "app")
    second = await uploads.append(context, upload, "app", body(LAYER[6000:]), at=6000)
    staged = await uploads.complete(context, upload, "app")
    await context.store("layers/one", staged)
    await db.commit()

    assert len(upload) == 32
    assert (first, second) == (6000, len(LAYER))
    assert so_far == Progress(upload, 6000)
    assert staged.sha256 == hashlib.sha256(LAYER).hexdigest()
    assert await context.read("layers/one", limit=len(LAYER)) == LAYER
    assert await count(db, Upload) == 0


async def test_a_completed_upload_is_over(context, db, settings):
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER))
    staged = await uploads.complete(context, upload, "app")
    await context.discard(staged)
    await db.commit()

    for attempt in (
        uploads.progress(context, upload, "app"),
        uploads.append(context, upload, "app", body(b"more")),
        uploads.complete(context, upload, "app"),
        uploads.abandon(context, upload, "app"),
    ):
        with pytest.raises(UnknownUpload):
            await attempt
    assert temporary_files(settings) == []


async def test_a_chunk_must_start_where_the_upload_ends(context):
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER[:6000]), at=0)

    for start in (0, 5999, 6001, 99999):
        with pytest.raises(OutOfOrder) as refused:
            await uploads.append(context, upload, "app", body(b"chunk"), at=start)
        assert refused.value.size == 6000
    assert (await uploads.progress(context, upload, "app")).size == 6000


async def test_a_chunk_that_stops_arriving_is_taken_back(context):
    async def interrupted() -> AsyncIterator[bytes]:
        yield LAYER[6000:7000]
        raise ConnectionError("the client went away")

    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER[:6000]))

    with pytest.raises(ConnectionError):
        await uploads.append(context, upload, "app", interrupted())

    assert (await uploads.progress(context, upload, "app")).size == 6000


async def test_an_abandoned_upload_leaves_nothing(context, db, settings):
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(LAYER))

    await uploads.abandon(context, upload, "app")
    await db.commit()

    assert await count(db, Upload) == 0
    assert temporary_files(settings) == []
    with pytest.raises(UnknownUpload):
        await uploads.progress(context, upload, "app")


@pytest.mark.parametrize(
    "upload_id",
    [
        "0" * 32,  # nobody began it
        "not-an-upload",
        "",
        "../../etc/passwd",
        "0" * 31,
        "G" * 32,
        "ABCDEF0123456789ABCDEF0123456789",  # the one spelling is lower case
        "01234567-89ab-cdef-0123-456789abcdef",
    ],
)
async def test_an_upload_that_was_never_begun_is_unknown(context, upload_id):
    with pytest.raises(UnknownUpload):
        await uploads.progress(context, upload_id, "app")
    with pytest.raises(UnknownUpload):
        await uploads.append(context, upload_id, "app", body(b"x"))


async def test_an_upload_belongs_to_what_it_was_begun_for(context, context_for, db):
    upload = await uploads.begin(context, "app")
    more = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    elsewhere = await context_for(more, someone("repository:raw:more"))

    with pytest.raises(UnknownUpload):
        await uploads.progress(context, upload, "another-app")
    with pytest.raises(UnknownUpload):
        await uploads.append(elsewhere, upload, "app", body(b"x"))
    assert (await uploads.progress(context, upload, "app")).size == 0


async def test_an_upload_needs_the_right_to_write(files, context_for, db):
    writer = await context_for(files, EVERYTHING)
    upload = await uploads.begin(writer, "app")
    await db.commit()
    reader = await context_for(files, someone("repository:raw:files:read"))
    nobody = await context_for(files, None)

    for context, status in ((reader, 403), (nobody, 401)):
        for attempt in (
            uploads.begin(context, "app"),
            uploads.progress(context, upload, "app"),
            uploads.append(context, upload, "app", body(b"x")),
            uploads.complete(context, upload, "app"),
            uploads.abandon(context, upload, "app"),
        ):
            with pytest.raises(ApiError) as refused:
                await attempt
            assert refused.value.status_code == status
    assert (await uploads.progress(writer, upload, "app")).size == 0
    assert await count(db, Asset) == 0


async def test_no_database_connection_is_held_while_a_chunk_arrives(context, db):
    upload = await uploads.begin(context, "app")
    await db.commit()
    in_transaction = []

    async def watched() -> AsyncIterator[bytes]:
        in_transaction.append(db.in_transaction())
        yield LAYER

    await uploads.append(context, upload, "app", watched())

    assert in_transaction == [False]


@pytest.mark.parametrize("stated", [False, True])
def test_two_chunks_that_arrive_together_do_not_mix(empty_database, tmp_path, stated):
    first, second = b"a" * 300_000, b"b" * 300_000

    sending = []

    async def slowly(data: bytes) -> AsyncIterator[bytes]:
        # Stay in the middle of the chunk until the other request is in the middle of
        # its own, or for long enough that it would be if nothing made it wait.
        sending.append(data[:1])
        for _ in range(50):
            if len(sending) == 2:
                break
            await asyncio.sleep(0.01)
        yield data

    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, _ = await create_files(factory)

        async def send(data: bytes) -> int:
            # Each request has a session of its own.
            async with factory() as db:
                sender = await build_context(db, settings, repository, EVERYTHING)
                at = 0 if stated else None
                size = await uploads.append(sender, upload, "app", slowly(data), at=at)
                await db.commit()
                return size

        async with factory() as db:
            upload = await uploads.begin(
                await build_context(db, settings, repository, EVERYTHING), "app"
            )
            await db.commit()

        results = await asyncio.gather(send(first), send(second), return_exceptions=True)

        async with factory() as db:
            context = await build_context(db, settings, repository, EVERYTHING)
            staged = await uploads.complete(context, upload, "app")
            await context.discard(staged)
            await db.commit()
        possible = (first, second) if stated else (first + second, second + first)
        assert staged.sha256 in {hashlib.sha256(data).hexdigest() for data in possible}
        if stated:
            # Both said they were the first chunk. One was; the other is told where to go on.
            refused = [result for result in results if isinstance(result, OutOfOrder)]
            assert [error.size for error in refused] == [300_000]
        else:
            assert sorted(results) == [300_000, 600_000]  # one after the other

    run(empty_database, tmp_path, scenario)


def test_a_chunk_that_arrives_while_an_upload_completes_cannot_reach_the_content(
    empty_database, tmp_path
):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, _ = await create_files(factory)
        async with factory() as db:
            context = await build_context(db, settings, repository, EVERYTHING)
            upload = await uploads.begin(context, "app")
            await db.commit()
            await uploads.append(context, upload, "app", body(LAYER))
            await db.commit()

        async with factory() as completing, factory() as late:
            context = await build_context(completing, settings, repository, EVERYTHING)
            staged = await uploads.complete(context, upload, "app")  # hashed, not yet stored
            other = await build_context(late, settings, repository, EVERYTHING)
            # The upload is over for every other request, in this process or another.
            for attempt in (
                uploads.append(other, upload, "app", body(b"never hashed")),
                uploads.progress(other, upload, "app"),
                uploads.complete(other, upload, "app"),
                uploads.abandon(other, upload, "app"),
            ):
                with pytest.raises(UnknownUpload):
                    await asyncio.wait_for(attempt, 5)
                await late.rollback()
            await context.store("layers/one", staged)
            await completing.commit()

        async with factory() as db:
            context = await build_context(db, settings, repository, EVERYTHING)
            assert await context.read("layers/one", limit=len(LAYER) + 100) == LAYER
            assert await db.scalar(select(func.count()).select_from(Upload)) == 0

    run(empty_database, tmp_path, scenario)


def test_an_upload_is_completed_by_one_request_only(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository, _ = await create_files(factory)
        async with factory() as db:
            context = await build_context(db, settings, repository, EVERYTHING)
            upload = await uploads.begin(context, "app")
            await db.commit()
            await uploads.append(context, upload, "app", body(LAYER))
            await db.commit()

        async def complete() -> str:
            async with factory() as db:
                context = await build_context(db, settings, repository, EVERYTHING)
                try:
                    staged = await uploads.complete(context, upload, "app")
                except UnknownUpload:
                    return "unknown"
                await context.discard(staged)
                await db.commit()
                return staged.sha256

        outcomes = await asyncio.gather(complete(), complete(), complete())

        assert sorted(outcomes) == sorted([hashlib.sha256(LAYER).hexdigest(), "unknown", "unknown"])

    run(empty_database, tmp_path, scenario)


async def test_an_upload_takes_only_so_many_chunks(context, db, monkeypatch):
    monkeypatch.setattr(backends, "MAX_UPLOAD_PARTS", 2)
    upload = await uploads.begin(context, "app")
    await uploads.append(context, upload, "app", body(b"one"))
    await uploads.append(context, upload, "app", body(b"two"))

    with pytest.raises(TooManyChunks):
        await uploads.append(context, upload, "app", body(b"three"))

    assert (await uploads.progress(context, upload, "app")).size == 6


async def test_chunks_left_without_an_upload_are_swept(context, db, sessionmaker, settings):
    # A chunk that joined just as its upload was completed, or whose repository was deleted.
    kept = await uploads.begin(context, "app")
    await uploads.append(context, kept, "app", body(LAYER))
    await db.commit()
    backend = context.backend
    await backend.append("0" * 32, body(b"nobody's"))
    await backend.append("1" * 32, body(b"nobody's, but recent"))
    directory = settings.data_dir / "blobs" / "default" / "tmp"
    long_ago = time.time() - 3 * 86400
    for path in directory.iterdir():
        if "0" * 32 in path.name or kept in path.name:
            os.utime(path, (long_ago, long_ago))

    await uploads.sweep(sessionmaker, settings, now=utcnow(), max_age_seconds=86400)

    assert await backend.upload_size("0" * 32) == 0
    assert await backend.upload_size("1" * 32) == len(b"nobody's, but recent")
    assert (await uploads.progress(context, kept, "app")).size == len(LAYER)


async def test_uploads_nobody_adds_to_are_swept(context, db, sessionmaker, settings):
    old = await uploads.begin(context, "app")
    recent = await uploads.begin(context, "app")
    await uploads.append(context, old, "app", body(LAYER))
    await db.execute(
        update(Upload)
        .where(Upload.key == "app", Upload.id != uploads._identifier(recent))
        .values(updated_at=utcnow() - timedelta(days=2))
    )
    await db.commit()

    removed = await uploads.sweep(sessionmaker, settings, now=utcnow(), max_age_seconds=86400)

    assert removed == 1
    assert temporary_files(settings) == []  # the recent one has no chunk yet
    with pytest.raises(UnknownUpload):
        await uploads.progress(context, old, "app")
    assert (await uploads.progress(context, recent, "app")).size == 0
