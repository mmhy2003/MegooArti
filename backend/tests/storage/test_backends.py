import asyncio
import hashlib
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from megooarti.storage import backends
from megooarti.storage.backends import FileBlobBackend

BODY = bytes(range(256)) * 41  # 10,496 bytes: not a multiple of the test chunk size


async def pieces(body: bytes, size: int = 700) -> AsyncIterator[bytes]:
    for start in range(0, len(body), size):
        yield body[start : start + size]


async def read(
    backend: FileBlobBackend, sha256: str, start: int = 0, end: int | None = None
) -> bytes:
    return b"".join([chunk async for chunk in backend.open(sha256, start, end)])


def temporary_files(root) -> list:
    directory = root / "tmp"
    return list(directory.iterdir()) if directory.exists() else []


@pytest.fixture
def backend(tmp_path, monkeypatch) -> FileBlobBackend:
    monkeypatch.setattr(backends, "CHUNK_SIZE", 1024)
    return FileBlobBackend(tmp_path / "store")


async def test_stage_reports_size_and_every_checksum(backend):
    staged = await backend.stage(pieces(BODY))

    assert staged.size == len(BODY)
    assert staged.sha256 == hashlib.sha256(BODY).hexdigest()
    assert staged.md5 == hashlib.md5(BODY).hexdigest()
    assert staged.sha1 == hashlib.sha1(BODY).hexdigest()
    assert staged.sha512 == hashlib.sha512(BODY).hexdigest()


async def test_committed_content_is_stored_under_its_hash_and_read_back(backend, tmp_path):
    staged = await backend.stage(pieces(BODY))
    assert not await backend.exists(staged.sha256)

    await backend.commit(staged)

    sha = staged.sha256
    assert (tmp_path / "store" / "content" / sha[:2] / sha[2:4] / sha).is_file()
    assert await backend.exists(sha)
    assert await read(backend, sha) == BODY
    assert temporary_files(tmp_path / "store") == []


async def test_an_empty_body_can_be_stored(backend):
    staged = await backend.stage(pieces(b""))
    await backend.commit(staged)

    assert staged.size == 0
    assert await read(backend, staged.sha256) == b""


async def test_committing_the_same_content_twice_keeps_one_file(backend, tmp_path):
    first = await backend.stage(pieces(BODY))
    await backend.commit(first)
    second = await backend.stage(pieces(BODY))
    await backend.commit(second)

    stored = [path for path in (tmp_path / "store" / "content").rglob("*") if path.is_file()]
    assert len(stored) == 1
    assert temporary_files(tmp_path / "store") == []


async def test_content_moves_in_bounded_chunks(backend, monkeypatch):
    written = []
    real_write = backends._write

    def spy(handle, hashers, data):
        written.append(len(data))
        real_write(handle, hashers, data)

    monkeypatch.setattr(backends, "_write", spy)

    staged = await backend.stage(pieces(BODY, size=5000))
    await backend.commit(staged)
    read_sizes = [len(chunk) async for chunk in backend.open(staged.sha256)]

    assert sum(written) == len(BODY)
    assert max(written) <= 1024
    assert len(written) > 5
    assert max(read_sizes) <= 1024


async def test_an_interrupted_stream_leaves_nothing_behind(backend, tmp_path):
    async def broken() -> AsyncIterator[bytes]:
        yield BODY[:3000]
        raise ConnectionError("the client went away")

    with pytest.raises(ConnectionError):
        await backend.stage(broken())

    assert temporary_files(tmp_path / "store") == []


async def test_discard_removes_staged_content_and_is_safe_after_commit(backend, tmp_path):
    staged = await backend.stage(pieces(BODY))
    await backend.discard(staged)
    assert temporary_files(tmp_path / "store") == []

    kept = await backend.stage(pieces(BODY))
    await backend.commit(kept)
    await backend.discard(kept)

    assert await backend.exists(kept.sha256)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0, 0, BODY[:1]),
        (10, 2999, BODY[10:3000]),
        (len(BODY) - 1, len(BODY) - 1, BODY[-1:]),
        (5000, None, BODY[5000:]),
    ],
)
async def test_open_reads_an_inclusive_range(backend, start, end, expected):
    staged = await backend.stage(pieces(BODY))
    await backend.commit(staged)

    assert await read(backend, staged.sha256, start, end) == expected


async def test_delete_removes_content_and_ignores_what_is_absent(backend):
    staged = await backend.stage(pieces(BODY))
    await backend.commit(staged)

    await backend.delete(staged.sha256)
    await backend.delete(staged.sha256)

    assert not await backend.exists(staged.sha256)


async def test_available_bytes_works_before_the_store_directory_exists(backend):
    assert await backend.available_bytes() > 0


async def test_sweep_removes_only_old_temporary_files(backend, tmp_path):
    old = await backend.stage(pieces(BODY))
    fresh = await backend.stage(pieces(BODY))
    two_days_ago = time.time() - 2 * 86400
    os.utime(old.token, (two_days_ago, two_days_ago))

    removed = await backend.sweep_temporary(older_than_seconds=86400)

    assert removed == 1
    assert [str(path) for path in temporary_files(tmp_path / "store")] == [fresh.token]


async def test_sweep_leaves_files_it_did_not_create(backend, tmp_path):
    staged = await backend.stage(pieces(BODY))
    foreign = tmp_path / "store" / "tmp" / "someone-elses-file.dat"
    foreign.write_bytes(b"not ours")
    two_days_ago = time.time() - 2 * 86400
    os.utime(staged.token, (two_days_ago, two_days_ago))
    os.utime(foreign, (two_days_ago, two_days_ago))

    removed = await backend.sweep_temporary(older_than_seconds=86400)

    assert removed == 1
    assert foreign.exists()


async def test_commit_makes_the_rename_durable(backend, tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(backends, "_sync_directory", synced.append)

    staged = await backend.stage(pieces(BODY))
    await backend.commit(staged)

    sha = staged.sha256
    assert tmp_path / "store" / "content" / sha[:2] / sha[2:4] in synced


UPLOAD = "0123456789abcdef0123456789abcdef"
OTHER = "f" * 32


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def age(path: Path, days: int) -> None:
    long_ago = time.time() - days * 86400
    os.utime(path, (long_ago, long_ago))


async def test_an_upload_grows_by_whole_chunks(backend):
    empty = await backend.upload_size(UPLOAD)
    first = await backend.append(UPLOAD, pieces(BODY[:5000]))
    second = await backend.append(UPLOAD, pieces(BODY[5000:]), at=5000)
    nothing = await backend.append(UPLOAD, pieces(b""))

    assert (empty, first, second, nothing) == (0, 5000, len(BODY), len(BODY))
    assert await backend.upload_size(UPLOAD) == len(BODY)
    assert await backend.upload_size(OTHER) == 0


async def test_a_chunk_joins_only_where_the_upload_ends(backend, tmp_path):
    await backend.append(UPLOAD, pieces(BODY[:5000]))

    for start in (0, 4999, 5001):
        assert await backend.append(UPLOAD, pieces(b"chunk"), at=start) is None

    assert await backend.upload_size(UPLOAD) == 5000
    assert len(temporary_files(tmp_path / "store")) == 1  # nothing of what was refused


async def test_a_chunk_that_stops_arriving_leaves_nothing(backend, tmp_path):
    async def interrupted() -> AsyncIterator[bytes]:
        yield BODY[5000:8000]
        raise ConnectionError("the client went away")

    await backend.append(UPLOAD, pieces(BODY[:5000]))

    with pytest.raises(ConnectionError):
        await backend.append(UPLOAD, interrupted())
    after = await backend.upload_size(UPLOAD)
    resumed = await backend.append(UPLOAD, pieces(BODY[5000:]))

    assert (after, resumed) == (5000, len(BODY))
    assert (await backend.adopt(UPLOAD)).sha256 == sha(BODY)


@pytest.mark.parametrize("stated", [True, False])
async def test_two_chunks_that_arrive_together_do_not_mix(backend, tmp_path, stated):
    # Two containers that share a store: nothing in one process can make them take turns.
    other = FileBlobBackend(tmp_path / "store")
    first, second = b"a" * 3000, b"b" * 3000
    sending = []

    async def slowly(data: bytes) -> AsyncIterator[bytes]:
        sending.append(data[:1])
        while len(sending) < 2:  # until the other chunk is arriving too
            await asyncio.sleep(0.01)
        yield data

    at = 0 if stated else None
    sizes = await asyncio.gather(
        backend.append(UPLOAD, slowly(first), at=at), other.append(UPLOAD, slowly(second), at=at)
    )

    staged = await backend.adopt(UPLOAD)
    if stated:
        # Both said they were the first chunk. One was.
        assert sorted(sizes, key=str) == [3000, None]
        assert staged.sha256 in (sha(first), sha(second))
    else:
        assert sorted(sizes) == [3000, 6000]  # one after the other
        assert staged.sha256 in (sha(first + second), sha(second + first))


async def test_an_upload_sent_in_one_piece_becomes_staged_content_without_a_copy(backend, tmp_path):
    await backend.append(UPLOAD, pieces(BODY))
    (only,) = temporary_files(tmp_path / "store")
    file = only.stat().st_ino

    staged = await backend.adopt(UPLOAD)

    assert staged.size == len(BODY)
    assert staged.sha256 == sha(BODY)
    assert staged.md5 == hashlib.md5(BODY).hexdigest()
    assert staged.sha1 == hashlib.sha1(BODY).hexdigest()
    assert staged.sha512 == hashlib.sha512(BODY).hexdigest()
    assert Path(staged.token).stat().st_ino == file  # the same file, not another one
    assert not only.exists()  # but no longer where the upload could find it
    await backend.commit(staged)
    assert await read(backend, staged.sha256) == BODY
    assert temporary_files(tmp_path / "store") == []
    assert await backend.upload_size(UPLOAD) == 0


async def test_an_upload_sent_in_several_pieces_is_joined(backend, tmp_path):
    for start in range(0, len(BODY), 3000):
        await backend.append(UPLOAD, pieces(BODY[start : start + 3000]))

    staged = await backend.adopt(UPLOAD)

    assert (staged.size, staged.sha256) == (len(BODY), sha(BODY))
    assert staged.sha512 == hashlib.sha512(BODY).hexdigest()
    assert temporary_files(tmp_path / "store") == [Path(staged.token)]  # the pieces are gone
    await backend.commit(staged)
    assert await read(backend, staged.sha256) == BODY


async def test_an_upload_with_nothing_in_it_is_empty_content(backend):
    staged = await backend.adopt(UPLOAD)

    assert (staged.size, staged.sha256) == (0, sha(b""))


@pytest.mark.parametrize("chunks", [1, 3])
async def test_what_was_adopted_is_out_of_the_uploads_reach(backend, chunks):
    size = -(-len(BODY) // chunks)
    for start in range(0, len(BODY), size):
        await backend.append(UPLOAD, pieces(BODY[start : start + size]))
    staged = await backend.adopt(UPLOAD)

    # A chunk that arrives late, a second completion, giving the upload up: whatever
    # another request does with the upload now, what was hashed is what is stored.
    await backend.append(UPLOAD, pieces(b"never hashed"))
    again = await backend.adopt(UPLOAD)
    await backend.append(UPLOAD, pieces(b"nor this"))
    await backend.abandon(UPLOAD)
    await backend.commit(staged)

    assert again.sha256 == sha(b"never hashed")
    assert sha(await read(backend, staged.sha256)) == staged.sha256 == sha(BODY)


async def test_an_upload_taken_by_another_request_is_not_there(backend, tmp_path, monkeypatch):
    await backend.append(UPLOAD, pieces(BODY))
    (only,) = temporary_files(tmp_path / "store")
    looked = backend._parts

    def taken_meanwhile(upload: str) -> list:
        found = looked(upload)
        only.unlink()  # another request completed or abandoned it after we looked
        return found

    monkeypatch.setattr(backend, "_parts", taken_meanwhile)

    with pytest.raises(FileNotFoundError):
        await backend.adopt(UPLOAD)
    assert temporary_files(tmp_path / "store") == []


async def test_an_abandoned_upload_is_gone_and_abandoning_twice_is_harmless(backend, tmp_path):
    await backend.append(UPLOAD, pieces(BODY[:5000]))
    await backend.append(UPLOAD, pieces(BODY[5000:]))
    await backend.append(OTHER, pieces(BODY))

    await backend.abandon(UPLOAD)
    await backend.abandon(UPLOAD)

    assert await backend.upload_size(UPLOAD) == 0
    assert await backend.upload_size(OTHER) == len(BODY)
    assert len(temporary_files(tmp_path / "store")) == 1


async def test_an_upload_takes_only_so_many_chunks(backend, monkeypatch):
    monkeypatch.setattr(backends, "MAX_UPLOAD_PARTS", 3)
    for _ in range(3):
        await backend.append(UPLOAD, pieces(b"x"))

    with pytest.raises(backends.UploadFull):
        await backend.append(UPLOAD, pieces(b"x"))

    assert await backend.upload_size(UPLOAD) == 3


@pytest.mark.parametrize("upload", ["", "../x", "0" * 31, "G" * 32, UPLOAD.upper(), UPLOAD + "\n"])
async def test_an_upload_is_named_by_32_hexadecimal_digits_and_nothing_else(backend, upload):
    for attempt in (
        backend.upload_size(upload),
        backend.append(upload, pieces(b"x")),
        backend.adopt(upload),
        backend.abandon(upload),
    ):
        with pytest.raises(ValueError):
            await attempt


async def test_chunks_are_swept_with_their_upload_not_by_their_age(backend, tmp_path):
    await backend.append(UPLOAD, pieces(BODY))  # still in progress, however old
    await backend.append(OTHER, pieces(BODY))  # nobody knows this upload any more
    await backend.append("e" * 32, pieces(BODY))  # nor this one, but it is recent
    for path in temporary_files(tmp_path / "store"):
        if UPLOAD in path.name or OTHER in path.name:
            age(path, 3)

    by_age = await backend.sweep_temporary(86400)
    removed = await backend.sweep_uploads({UPLOAD}, 86400)

    assert (by_age, removed) == (0, 1)
    sizes = [await backend.upload_size(upload) for upload in (UPLOAD, OTHER, "e" * 32)]
    assert sizes == [len(BODY), 0, len(BODY)]


async def test_a_chunk_whose_request_is_cancelled_leaves_nothing(backend, tmp_path):
    async def never_ends() -> AsyncIterator[bytes]:
        yield BODY
        raise asyncio.CancelledError  # the worker is going away

    with pytest.raises(asyncio.CancelledError):
        await backend.append(UPLOAD, never_ends())

    assert temporary_files(tmp_path / "store") == []
