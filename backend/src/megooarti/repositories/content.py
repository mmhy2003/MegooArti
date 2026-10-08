"""The storage facade formats and engines work through.

It enforces the add, edit and delete permissions and the deployment policy, so a format
cannot bypass them, and it is the only code that ties assets to blobs.
"""

import hashlib
import mimetypes
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import serving
from megooarti.repositories.formats import ComponentKey, Format, get_format
from megooarti.repositories.models import Asset, Component, Repository
from megooarti.repositories.paths import normalise_path
from megooarti.security import client_login
from megooarti.security.authentication import Principal, authorize, unauthorized
from megooarti.storage import blobs
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore

# First key of the two-key advisory lock; the second is derived from what is locked.
_LOCK_NAMESPACE = 0x4D48
_DOWNLOAD_NOTE_INTERVAL = timedelta(hours=1)
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(;[\x20-\x7e]*)?")
# Recorded as the creator of content a proxy repository fetched for a reader.
PROXY_CREATOR = "proxy"
# The kind of a document the server keeps on an uploader's behalf.
_MAINTAINED = "metadata"
_PIECE = 1024 * 1024


def _media_type(declared: str | None, path: str) -> str:
    """The declared type if it is a well-formed media type, else a guess from the name."""
    if declared is not None:
        declared = declared.strip()
        if len(declared) <= 255 and _MEDIA_TYPE.fullmatch(declared):
            return declared
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _verify(
    staged: StagedBlob, expected_size: int | None, expected_hashes: dict[str, str] | None
) -> None:
    if expected_size is not None and staged.size != expected_size:
        raise ApiError(
            400,
            "checksum_mismatch",
            f"Received {staged.size} bytes but {expected_size} were declared.",
        )
    for algorithm, expected in (expected_hashes or {}).items():
        if getattr(staged, algorithm) != expected.strip().lower():
            raise ApiError(
                400, "checksum_mismatch", f"The {algorithm} checksum does not match the content."
            )


async def _pieces(data: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(data), _PIECE):
        yield data[start : start + _PIECE]


@dataclass(frozen=True)
class Stored:
    """What is at a path, as plain values a format may read."""

    path: str
    kind: str
    size: int
    md5: str
    sha1: str
    sha256: str
    sha512: str
    content_type: str
    modified: datetime


@dataclass(frozen=True)
class FileEntry:
    path: str
    modified: datetime


class TooLarge(Exception):
    """A file that was to be read into memory is larger than the caller allows."""


class RepositoryContext:
    """One request's view of one repository."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        repository: Repository,
        principal: Principal | None,
        format: Format,
        backend: BlobBackend | None,
        outbound: Callable[[], Any] | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository
        self.principal = principal
        self.format = format
        self.backend = backend  # None for a group, which stores nothing itself
        # How to get the application's outbound HTTP client; None if there is none.
        self.outbound = outbound

    def permission(self, action: str) -> str:
        return f"repository:{self.repository.format}:{self.repository.name}:{action}"

    def http(self) -> Any:
        """The application's outbound HTTP client, for fetching from a remote."""
        if self.outbound is None:
            raise RuntimeError("this context was built without an outbound client")
        return self.outbound()

    async def issue_token(self, request: Request, username: str, secret: str, *, label: str) -> str:
        """Sign a package client in: check a name and a secret, and return a token.

        For the request a format has named as carrying its credentials in its body.
        The secret is checked as HTTP Basic credentials are. The caller commits.
        """
        return await client_login.issue_token(self.db, request, username, secret, label=label)

    async def revoke_token(self, value: str) -> None:
        """Revoke the API token with this value, if it is the caller's."""
        if self.principal is None:
            raise unauthorized(scheme="Basic")
        await client_login.revoke_own_token(self.db, self.principal, value)

    async def _lock(self, kind: str, key: str) -> None:
        """Serialise work on one path or component until this transaction ends."""
        digest = hashlib.sha256(f"{self.repository.id}:{kind}:{key}".encode()).digest()
        number = int.from_bytes(digest[:4], "big", signed=True)
        await self.db.execute(text(f"SELECT pg_advisory_xact_lock({_LOCK_NAMESPACE}, {number})"))

    async def get(self, path: str, *, fresh: bool = False) -> Asset | None:
        statement = select(Asset).where(
            Asset.repository_id == self.repository.id, Asset.path == path
        )
        if fresh:  # reread from the database even if this session already loaded it
            statement = statement.execution_options(populate_existing=True)
        return await self.db.scalar(statement)

    async def stat(self, path: str) -> Stored | None:
        """What is at a path, read from the database now."""
        row = (
            await self.db.execute(
                select(
                    Asset.kind,
                    Asset.content_type,
                    Asset.updated_at,
                    Blob.size,
                    Blob.md5,
                    Blob.sha1,
                    Blob.sha256,
                    Blob.sha512,
                )
                .join(Blob, Blob.id == Asset.blob_id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if row is None:
            return None
        return Stored(
            path=path,
            kind=row.kind,
            size=row.size,
            md5=row.md5,
            sha1=row.sha1,
            sha256=row.sha256,
            sha512=row.sha512,
            content_type=row.content_type,
            modified=row.updated_at,
        )

    async def versions(self, namespace: str, name: str) -> dict[str, datetime]:
        """Each version of a package that has a file, with when its files last changed."""
        rows = await self.db.execute(
            select(Component.version, func.max(Asset.updated_at))
            .join(Asset, Asset.component_id == Component.id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
            )
            .group_by(Component.version)
        )
        return {version: changed for version, changed in rows}

    async def files(self, namespace: str, name: str, version: str) -> list[FileEntry]:
        """The files of one version of a package, ordered by path."""
        rows = await self.db.execute(
            select(Asset.path, Asset.updated_at)
            .join(Component, Component.id == Asset.component_id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
                Component.version == version,
            )
            .order_by(Asset.path)
        )
        return [FileEntry(path, changed) for path, changed in rows]

    async def names(self, namespace: str, candidates: Collection[str]) -> set[str]:
        """Which of `candidates` are packages in `namespace`."""
        if not candidates:
            return set()
        rows = await self.db.scalars(
            select(Component.name)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name.in_(candidates),
            )
            .distinct()
        )
        return set(rows)

    async def read(self, path: str, *, limit: int) -> bytes | None:
        """A stored file's bytes, for a small document a format must look inside.

        The limit is what makes it acceptable to hold the connection meanwhile.
        """
        row = (
            await self.db.execute(
                select(Blob.sha256, Blob.size)
                .join(Asset, Asset.blob_id == Blob.id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.size > limit:
            raise TooLarge(path)
        return b"".join([chunk async for chunk in self.backend.open(row.sha256)])

    async def release(self) -> None:
        """Give the database connection back before slow work that needs none.

        Only for a request that has read and not written: this commits, so nothing may
        be pending and no lock may be held.
        """
        await self.db.commit()

    async def receive(self, chunks: AsyncIterator[bytes], *, limit: int) -> bytes | None:
        """A small upload, read into memory. None if it is longer than `limit`."""
        await self.db.commit()  # give the connection back while the body arrives
        received = bytearray()
        async for chunk in chunks:
            received += chunk
            if len(received) > limit:
                return None
        return bytes(received)

    def respond_with(
        self,
        data: bytes,
        request: Request,
        *,
        filename: str,
        content_type: str,
        last_modified: datetime,
    ) -> Response:
        """Answer a GET or HEAD with bytes made for this request.

        The same planning as for a stored file, so the headers, conditions and ranges
        are the same too.
        """
        item = serving.Servable(
            sha256=hashlib.sha256(data).hexdigest(),
            md5=hashlib.md5(data).hexdigest(),
            sha1=hashlib.sha1(data).hexdigest(),
            sha512=hashlib.sha512(data).hexdigest(),
            size=len(data),
            content_type=content_type,
            last_modified=last_modified,
            filename=filename,
        )
        plan = serving.plan(request.method, request.headers, item)
        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return Response(
            content=data[start : end + 1], status_code=plan.status, headers=plan.headers
        )

    def _check_policy(self, *, replacing: bool) -> None:
        policy = self.repository.config.get("hosted", {}).get("deployment_policy")
        if policy == "read_only":
            raise ApiError(403, "repository_read_only", "This repository is read-only.")
        if replacing and policy == "disable_redeploy":
            raise ApiError(
                409, "redeploy_disabled", "This repository does not allow a path to be replaced."
            )

    def _check_may_store(self, existing: Asset | None) -> None:
        action = "add" if existing is None else "edit"
        authorize(self.principal, self.permission(action), scheme="Basic")
        self._check_policy(replacing=existing is not None)

    def require_write(self) -> None:
        """Refuse a caller who may not change this repository's content at all.

        For an upload a format accepts without storing it as sent: it needs `add` or
        `edit`, and the repository must not be read-only.
        """
        if self.repository.type != "hosted":
            # A programming error, like caching into a repository that is not a proxy.
            raise RuntimeError("only a hosted repository takes uploads")
        try:
            authorize(self.principal, self.permission("add"), scheme="Basic")
        except ApiError:
            authorize(self.principal, self.permission("edit"), scheme="Basic")
        self._check_policy(replacing=False)

    async def _lock_component(self, key: ComponentKey) -> None:
        await self._lock("component", f"{key.namespace}\x00{key.name}\x00{key.version}")

    async def _component(self, key: ComponentKey) -> Component:
        await self._lock_component(key)
        component = await self.db.scalar(
            select(Component).where(
                Component.repository_id == self.repository.id,
                Component.namespace == key.namespace,
                Component.name == key.name,
                Component.version == key.version,
            )
        )
        if component is None:
            component = Component(
                repository_id=self.repository.id,
                namespace=key.namespace,
                name=key.name,
                version=key.version,
            )
            self.db.add(component)
            await self.db.flush()
        return component

    async def put(
        self,
        path: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
        expected_size: int | None = None,
        expected_hashes: dict[str, str] | None = None,
        kind: str = "asset",
    ) -> tuple[Asset, bool]:
        """Store content at a path. Returns the asset and whether it is new.

        The caller commits. Permission and policy are checked before the body is read,
        so a refused upload is refused early, and again before recording, because the
        path may have been written while the body arrived.
        """
        path = normalise_path(path)
        self._check_may_store(await self.get(path))
        await self.db.commit()  # give the connection back while the body arrives
        staged = await self.stage(
            chunks, expected_size=expected_size, expected_hashes=expected_hashes
        )
        return await self.store(path, staged, content_type=content_type, kind=kind)

    async def stage(
        self,
        chunks: AsyncIterator[bytes],
        *,
        expected_size: int | None = None,
        expected_hashes: dict[str, str] | None = None,
    ) -> StagedBlob:
        """Receive content into temporary storage and verify it. Uses no database.

        A format that publishes several files in one request stages each of them first,
        then calls `store` for each inside one transaction, so the publish is atomic.
        """
        staged = await self.backend.stage(chunks)
        try:
            _verify(staged, expected_size, expected_hashes)
        except BaseException:
            await self.backend.discard(staged)
            raise
        return staged

    async def _record(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None,
        kind: str,
        checked: bool,
        created_by: str | None = None,
        attributes: dict[str, Any] | None = None,
        verified_at: datetime | None = None,
        packaged: bool = True,
    ) -> tuple[Asset, bool]:
        """Tie staged content to a path. `checked` applies permission and policy."""
        try:
            path = normalise_path(path)
            await self._lock("path", path)
            existing = await self.get(path, fresh=True)
            if checked:
                self._check_may_store(existing)
            blob = await blobs.record(self.db, self.backend, self.repository.blob_store_id, staged)
        except BaseException:
            await self.backend.discard(staged)
            raise

        now = utcnow()
        media_type = _media_type(content_type, path)
        if existing is None:
            key = self.format.describe_component(path) if packaged else None
            component_id = None if key is None else (await self._component(key)).id
            asset = Asset(
                repository_id=self.repository.id,
                component_id=component_id,
                path=path,
                blob_id=blob.id,
                content_type=media_type,
                kind=kind,
                attributes=attributes or {},
                created_by=created_by or self.principal.user.username,
                last_verified_at=verified_at,
            )
            self.db.add(asset)
            await self.db.flush()
            return asset, True

        previous = existing.blob_id
        changed = previous != blob.id
        existing.blob_id = blob.id
        existing.content_type = media_type
        existing.last_verified_at = verified_at
        if attributes is not None:
            existing.attributes = attributes
        if checked or changed:
            # An upload always counts as a change. Fetching the same bytes from the
            # remote again does not, so Last-Modified stays put.
            existing.updated_at = now
        await self.db.flush()
        if changed:
            await blobs.dereference(self.db, [previous], now)
        return existing, False

    async def store(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None = None,
        kind: str = "asset",
    ) -> tuple[Asset, bool]:
        """Record staged content at a path, in the caller's transaction.

        Checks permission and policy under the path lock. Never commits: the caller
        does, and a rollback undoes everything recorded here.
        """
        return await self._record(path, staged, content_type=content_type, kind=kind, checked=True)

    async def cache(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None,
        attributes: dict[str, Any],
        now: datetime,
    ) -> Asset:
        """Record content a proxy repository fetched from its remote.

        No permission or policy check: a reader triggered this, and their `read` on the
        proxy (or on the group in front of it) has already been checked. For that reason
        it works only on a proxy repository.
        """
        if self.repository.type != "proxy":
            await self.backend.discard(staged)
            raise RuntimeError("cache() is only for proxy repositories")
        asset, _ = await self._record(
            path,
            staged,
            content_type=content_type,
            kind="asset",
            checked=False,
            created_by=PROXY_CREATOR,
            attributes=attributes,
            verified_at=now,
        )
        return asset

    async def maintain(
        self,
        path: str,
        update: Callable[[bytes | None], Awaitable[bytes | None]],
        *,
        content_type: str,
        limit: int,
    ) -> None:
        """Change a document the server keeps on an uploader's behalf. The caller commits.

        `update` is given the stored bytes, or None, and returns what to store, or None
        to store nothing. It runs under the path lock, so two changes never overwrite
        each other. This needs `add` or `edit` and is not subject to `disable_redeploy`,
        because the uploader is not replacing anything they published. It refuses a
        path that holds any other kind of file, so it cannot overwrite an artifact.
        """
        path = normalise_path(path)
        self.require_write()
        await self._lock("path", path)
        existing = await self.get(path, fresh=True)
        if existing is not None and existing.kind != _MAINTAINED:
            raise ApiError(409, "conflict", "A file that is not metadata is stored at this path.")
        current = None if existing is None else await self.read(path, limit=limit)
        wanted = await update(current)
        if wanted == current:
            return
        if wanted is None:
            blob_id = existing.blob_id
            await self.db.delete(existing)
            await self.db.flush()
            await blobs.dereference(self.db, [blob_id], utcnow())
            return
        staged = await self.backend.stage(_pieces(wanted))
        await self._record(
            path,
            staged,
            content_type=content_type,
            kind=_MAINTAINED,
            checked=False,
            packaged=False,
        )

    async def delete(self, path: str) -> bool:
        """Remove what is at a path. False if there was nothing. The caller commits."""
        path = normalise_path(path)
        authorize(self.principal, self.permission("delete"), scheme="Basic")
        self._check_policy(replacing=False)
        await self._lock("path", path)
        asset = await self.get(path, fresh=True)
        if asset is None:
            return False
        blob_id, component_id = asset.blob_id, asset.component_id
        await self.db.delete(asset)
        await self.db.flush()
        if component_id is not None:
            # The same lock an upload into this component holds, so a sibling that is
            # being added is seen here instead of losing its component under it.
            component = await self.db.get(Component, component_id, populate_existing=True)
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            remaining = await self.db.scalar(
                select(Asset.id).where(Asset.component_id == component_id).limit(1)
            )
            if remaining is None:
                await self.db.execute(delete(Component).where(Component.id == component_id))
        await blobs.dereference(self.db, [blob_id], utcnow())
        return True

    async def respond(self, path: str, request: Request) -> Response:
        """The response to a GET or HEAD for a path. The caller has checked `read`."""
        path = normalise_path(path)
        found = (
            await self.db.execute(
                select(Asset, Blob)
                .join(Blob, Blob.id == Asset.blob_id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if found is None:
            raise ApiError(404, "not_found", "No such file.")
        asset, blob = found
        item = serving.Servable(
            sha256=blob.sha256,
            md5=blob.md5,
            sha1=blob.sha1,
            sha512=blob.sha512,
            size=blob.size,
            content_type=asset.content_type,
            last_modified=asset.updated_at,
            filename=path.rpartition("/")[2],
        )
        plan = serving.plan(request.method, request.headers, item)

        now = utcnow()
        noted = asset.last_downloaded_at
        if plan.byte_range is not None and (
            noted is None or now - noted >= _DOWNLOAD_NOTE_INTERVAL
        ):
            asset.last_downloaded_at = now
        await self.db.commit()  # give the connection back before the body is sent

        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return StreamingResponse(
            self.backend.open(blob.sha256, start, end),
            status_code=plan.status,
            headers=plan.headers,
        )


async def build_context(
    db: AsyncSession,
    settings: Settings,
    repository: Repository,
    principal: Principal | None,
    outbound: Callable[[], Any] | None = None,
) -> RepositoryContext:
    backend = None
    if repository.blob_store_id is not None:
        store = await db.get(BlobStore, repository.blob_store_id)
        backend = backend_for(settings, store)
    return RepositoryContext(
        db=db,
        settings=settings,
        repository=repository,
        principal=principal,
        format=get_format(repository.format),
        backend=backend,
        outbound=outbound,
    )
