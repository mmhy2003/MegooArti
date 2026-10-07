import hashlib
import os
import time
from collections.abc import AsyncIterator

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
