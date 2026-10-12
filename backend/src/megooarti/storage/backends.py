"""Where blob bytes live. One backend today: a directory on a filesystem.

Content is named only by its SHA-256, so nothing a client sends can choose a file path.
All file and hash work runs in worker threads, in chunks of at most CHUNK_SIZE.
"""

import asyncio
import hashlib
import os
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

CHUNK_SIZE = 1024 * 1024
_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")
_TEMPORARY_PREFIX = "upload-"
# A chunk of an upload that arrives over several requests: `chunk-<upload>-<where it
# starts>`. Not under the prefix above: a chunk lives as long as its upload, not a day.
_PART_PREFIX = "chunk-"
_PART = re.compile(r"chunk-([0-9a-f]{32})-([0-9]{20})")
_UPLOAD = re.compile(r"[0-9a-f]{32}")
# Each chunk is a file. Clients that send chunks send megabytes in each.
MAX_UPLOAD_PARTS = 10_000
_JOIN_ATTEMPTS = 100


class UploadFull(Exception):
    """The upload already has as many chunks as one may have."""


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

    async def discard(self, staged: StagedBlob) -> None:
        """Drop staged content. For what has been committed since, this does nothing."""

    def open_staged(self, staged: StagedBlob) -> AsyncIterator[bytes]: ...

    def open(self, sha256: str, start: int = 0, end: int | None = None) -> AsyncIterator[bytes]: ...

    async def exists(self, sha256: str) -> bool: ...

    async def delete(self, sha256: str) -> None: ...

    async def available_bytes(self) -> int | None: ...

    async def sweep_temporary(self, older_than_seconds: float) -> int: ...

    async def upload_size(self, upload: str) -> int: ...

    async def append(
        self, upload: str, chunks: AsyncIterator[bytes], *, at: int | None = None
    ) -> int | None: ...

    async def adopt(self, upload: str) -> StagedBlob: ...

    async def abandon(self, upload: str) -> None: ...

    async def sweep_uploads(self, keep: Collection[str], older_than_seconds: float) -> int: ...


def _write(handle: BinaryIO, hashers: dict, data: bytes) -> None:
    handle.write(data)
    for hasher in hashers.values():
        hasher.update(data)


def _finish(handle: BinaryIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


def _hash_more(handle: BinaryIO, hashers: dict) -> int:
    """Read the next piece of a file into the hashers. Returns its length, 0 at the end."""
    data = handle.read(CHUNK_SIZE)
    for hasher in hashers.values():
        hasher.update(data)
    return len(data)


def _sync_directory(directory: Path) -> None:
    """Make a rename into this directory survive a power loss.

    The database commit that follows is durable, so the file it refers to must be too.
    Windows has no directory sync; the target is the Linux container.
    """
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileBlobBackend:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _content_path(self, sha256: str) -> Path:
        return self._root / "content" / sha256[:2] / sha256[2:4] / sha256

    async def _spool(self, chunks: AsyncIterator[bytes], hashers: dict) -> tuple[Path, int]:
        """Write what arrives to a new temporary file, on disk and closed. Returns it and its size.

        Nothing is left if the chunks stop arriving.
        """
        directory = self._root / "tmp"
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        temporary = directory / f"{_TEMPORARY_PREFIX}{uuid.uuid4().hex}"
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
        return temporary, size

    async def stage(self, chunks: AsyncIterator[bytes]) -> StagedBlob:
        # MD5 and SHA-1 are published for clients that expect them, not used for security.
        hashers = {name: hashlib.new(name, usedforsecurity=False) for name in _ALGORITHMS}
        temporary, size = await self._spool(chunks, hashers)
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
            _sync_directory(final.parent)

        await asyncio.to_thread(place)

    async def discard(self, staged: StagedBlob) -> None:
        await asyncio.to_thread(Path(staged.token).unlink, True)

    async def open_staged(self, staged: StagedBlob) -> AsyncIterator[bytes]:
        """Read content that is staged and not yet stored, for a caller that must look at it."""
        handle = await asyncio.to_thread(open, staged.token, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, CHUNK_SIZE):
                yield chunk
        finally:
            handle.close()

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

    # --- Uploads that arrive over several requests ------------------------------------
    #
    # Each chunk is written to a file of its own, and joins the upload only when all of
    # it has arrived, under a name that says where it starts. A file that has joined is
    # never written again. Completing an upload takes its files out of the upload's
    # name before reading them. So what is hashed is what becomes the blob, whatever
    # other requests for the same upload do meanwhile, in this process or in another.

    def _part_path(self, upload: str, offset: int) -> Path:
        return self._root / "tmp" / f"{_PART_PREFIX}{upload}-{offset:020d}"

    def _all_parts(self, upload: str) -> list[tuple[int, Path, int]]:
        """Every chunk file of an upload: (where it starts, the file, its size), in order."""
        if not _UPLOAD.fullmatch(upload):
            # The name becomes part of a file name. Callers check it; so does this.
            raise ValueError("an upload is named by 32 hexadecimal digits")
        found = []
        for path in (self._root / "tmp").glob(f"{_PART_PREFIX}{upload}-*"):
            named = _PART.fullmatch(path.name)
            if named is None:
                continue
            try:
                found.append((int(named[2]), path, path.stat().st_size))
            except FileNotFoundError:  # taken while we looked
                continue
        return sorted(found)

    def _parts(self, upload: str) -> list[tuple[int, Path, int]]:
        """The chunks of an upload that follow one another from its start."""
        parts: list[tuple[int, Path, int]] = []
        end = 0
        for offset, path, size in self._all_parts(upload):
            if offset != end:
                break
            parts.append((offset, path, size))
            end += size
        return parts

    def _join(self, upload: str, received: Path, size: int, at: int | None) -> int | None:
        """Make a received chunk the next one of an upload. None if `at` is not its end."""
        for _ in range(_JOIN_ATTEMPTS):
            parts = self._parts(upload)
            end = sum(part[2] for part in parts)
            if at is not None and at != end:
                return None
            if size == 0:
                return end
            try:
                # A link, not a rename: it fails if another chunk has taken the place.
                os.link(received, self._part_path(upload, end))
            except FileExistsError:
                continue  # one joined there first; look again
            return end + size
        return None

    async def upload_size(self, upload: str) -> int:
        """How much of an upload has arrived, in whole chunks."""
        parts = await asyncio.to_thread(self._parts, upload)
        return sum(part[2] for part in parts)

    async def append(
        self, upload: str, chunks: AsyncIterator[bytes], *, at: int | None = None
    ) -> int | None:
        """Add a chunk to an upload and return the upload's size.

        `at` is where the sender says the chunk starts. If the upload does not end
        there, before the chunk arrives or after, nothing is added and the answer is
        None. A chunk that stops arriving leaves nothing. Raises UploadFull.
        """
        parts = await asyncio.to_thread(self._parts, upload)
        if at is not None and at != sum(part[2] for part in parts):
            return None
        if len(parts) >= MAX_UPLOAD_PARTS:
            raise UploadFull
        received, size = await self._spool(chunks, {})
        try:
            return await asyncio.to_thread(self._join, upload, received, size, at)
        finally:
            received.unlink(missing_ok=True)

    async def adopt(self, upload: str) -> StagedBlob:
        """Turn an upload into staged content. Its chunks are the upload's no longer.

        An upload sent as one chunk, which is how container clients send a layer, is
        hashed where it lies and not copied. Several chunks are joined into one file.
        Raises FileNotFoundError if another request took the upload meanwhile.
        """
        parts = await asyncio.to_thread(self._parts, upload)
        directory = self._root / "tmp"
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
        whole = directory / f"{_TEMPORARY_PREFIX}{uuid.uuid4().hex}"
        hashers = {name: hashlib.new(name, usedforsecurity=False) for name in _ALGORITHMS}
        size = 0
        try:
            if len(parts) == 1:
                # Out of the upload's name first: from here on nobody else can find it.
                await asyncio.to_thread(os.rename, parts[0][1], whole)
                with await asyncio.to_thread(open, whole, "rb") as handle:
                    while read := await asyncio.to_thread(_hash_more, handle, hashers):
                        size += read
            else:
                handle = await asyncio.to_thread(open, whole, "wb")
                try:
                    for _, path, _ in parts:
                        with await asyncio.to_thread(open, path, "rb") as part:
                            while piece := await asyncio.to_thread(part.read, CHUNK_SIZE):
                                await asyncio.to_thread(_write, handle, hashers, piece)
                                size += len(piece)
                    await asyncio.to_thread(_finish, handle)
                finally:
                    handle.close()
                for _, path, _ in parts:
                    path.unlink(missing_ok=True)
        except BaseException:
            whole.unlink(missing_ok=True)
            raise
        digests = {name: hasher.hexdigest() for name, hasher in hashers.items()}
        return StagedBlob(token=str(whole), size=size, **digests)

    async def abandon(self, upload: str) -> None:
        """Remove every chunk of an upload. Harmless if there are none."""

        def remove() -> None:
            for _, path, _ in self._all_parts(upload):
                path.unlink(missing_ok=True)

        await asyncio.to_thread(remove)

    async def sweep_uploads(self, keep: Collection[str], older_than_seconds: float) -> int:
        """Remove chunks of uploads that are not in `keep` and are older than this.

        For chunks no upload owns any more: one that joined just as its upload was
        completed, or whose repository was deleted. Returns how many files went.
        """

        def sweep() -> int:
            cutoff = time.time() - older_than_seconds
            removed = 0
            for path in (self._root / "tmp").glob(f"{_PART_PREFIX}*"):
                named = _PART.fullmatch(path.name)
                if named is None or named[1] in keep:
                    continue
                try:
                    expired = path.stat().st_mtime < cutoff
                except FileNotFoundError:
                    continue
                if expired:
                    path.unlink(missing_ok=True)
                    removed += 1
            return removed

        return await asyncio.to_thread(sweep)

    async def sweep_temporary(self, older_than_seconds: float) -> int:
        def sweep() -> int:
            directory = self._root / "tmp"
            if not directory.exists():
                return 0
            cutoff = time.time() - older_than_seconds
            removed = 0
            # Only files this backend created: a store rooted at a shared directory must
            # never sweep someone else's files out of its tmp/.
            for path in directory.glob(f"{_TEMPORARY_PREFIX}*"):
                try:
                    expired = path.is_file() and path.stat().st_mtime < cutoff
                except FileNotFoundError:  # an upload finished while we looked
                    continue
                if expired:
                    path.unlink(missing_ok=True)
                    removed += 1
            return removed

        return await asyncio.to_thread(sweep)
