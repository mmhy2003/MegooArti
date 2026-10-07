"""Where blob bytes live. One backend today: a directory on a filesystem.

Content is named only by its SHA-256, so nothing a client sends can choose a file path.
All file and hash work runs in worker threads, in chunks of at most CHUNK_SIZE.
"""

import asyncio
import hashlib
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

CHUNK_SIZE = 1024 * 1024
_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


@dataclass(frozen=True)
class StagedBlob:
    """Content received and hashed, but not yet permanent."""

    token: str  # where the backend is holding it; meaningful only to that backend
    sha256: str
    md5: str
    sha1: str
    sha512: str
    size: int


class BlobBackend(Protocol):
    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob: ...

    async def commit(self, staged: StagedBlob) -> None: ...

    async def discard(self, staged: StagedBlob) -> None: ...

    def open(self, sha256: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]: ...

    async def exists(self, sha256: str) -> bool: ...

    async def delete(self, sha256: str) -> None: ...

    async def available_bytes(self) -> int | None: ...

    async def sweep_temporary(self, older_than_seconds: float) -> int: ...


def _write(handle: BinaryIO, hashers: dict, data: bytes) -> None:
    handle.write(data)
    for hasher in hashers.values():
        hasher.update(data)


def _finish(handle: BinaryIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


class FileBlobBackend:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _content_path(self, sha256: str) -> Path:
        return self._root / "content" / sha256[:2] / sha256[2:4] / sha256

    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob:
        directory = self._root / "tmp"
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        temporary = directory / uuid.uuid4().hex
        # MD5 and SHA-1 are published for clients that expect them, not used for security.
        hashers = {name: hashlib.new(name, usedforsecurity=False) for name in _ALGORITHMS}
        size = 0
        pending = bytearray()
        handle = await asyncio.to_thread(open, temporary, "wb")
        try:
            async for chunk in chunks:
                pending += chunk
                size += len(chunk)
                while len(pending) >= CHUNK_SIZE:
                    piece = bytes(pending[:CHUNK_SIZE])
                    del pending[:CHUNK_SIZE]
                    await asyncio.to_thread(_write, handle, hashers, piece)
            if pending:
                await asyncio.to_thread(_write, handle, hashers, bytes(pending))
            await asyncio.to_thread(_finish, handle)
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
        digests = {name: hasher.hexdigest() for name, hasher in hashers.items()}
        return StagedBlob(token=str(temporary), size=size, **digests)

    async def commit(self, staged: StagedBlob) -> None:
        def place() -> None:
            temporary = Path(staged.token)
            final = self._content_path(staged.sha256)
            if final.exists():
                temporary.unlink(missing_ok=True)
                return
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temporary, final)

        await asyncio.to_thread(place)

    async def discard(self, staged: StagedBlob) -> None:
        await asyncio.to_thread(Path(staged.token).unlink, True)

    async def open(
        self, sha256: str, start: int = 0, end: int | None = None
    ) -> AsyncIterator[bytes]:
        handle = await asyncio.to_thread(open, self._content_path(sha256), "rb")
        try:
            if start:
                await asyncio.to_thread(handle.seek, start)
            remaining = None if end is None else end - start + 1
            while remaining is None or remaining > 0:
                wanted = CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining)
                chunk = await asyncio.to_thread(handle.read, wanted)
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk
        finally:
            handle.close()

    async def exists(self, sha256: str) -> bool:
        return await asyncio.to_thread(self._content_path(sha256).is_file)

    async def delete(self, sha256: str) -> None:
        await asyncio.to_thread(self._content_path(sha256).unlink, True)

    async def available_bytes(self) -> int | None:
        def free() -> int:
            existing = self._root
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            return shutil.disk_usage(existing).free

        return await asyncio.to_thread(free)

    async def sweep_temporary(self, older_than_seconds: float) -> int:
        def sweep() -> int:
            directory = self._root / "tmp"
            if not directory.exists():
                return 0
            cutoff = time.time() - older_than_seconds
            removed = 0
            for path in directory.iterdir():
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            return removed

        return await asyncio.to_thread(sweep)
