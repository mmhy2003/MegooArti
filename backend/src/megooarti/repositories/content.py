"""The storage facade formats and engines work through.

It enforces the add, edit and delete permissions and the deployment policy, so a format
cannot bypass them, and it is the only code that ties assets to blobs.
"""

import hashlib
import mimetypes
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, func, insert, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories import serving
from megooarti.repositories.formats import ComponentKey, Format, get_format
from megooarti.repositories.models import Asset, AssetReference, Component, Repository
from megooarti.repositories.paths import normalise_path
from megooarti.security import client_login
from megooarti.security.authentication import Principal, authorize, unauthorized
from megooarti.storage import blobs
from megooarti.storage.backends import BlobBackend, StagedBlob
from megooarti.storage.blob_stores import backend_for
from megooarti.storage.models import Blob, BlobStore
from megooarti.system.settings_store import get_setting

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
    # A proxy's cached file: when the remote last confirmed it. None once the cache
    # was invalidated, and for anything that is not a proxy's.
    verified: datetime | None = None


@dataclass(frozen=True)
class FileEntry:
    path: str
    modified: datetime


@dataclass(frozen=True)
class ComponentInfo:
    """One version of a package: what its component says, and when it changed."""

    version: str
    attributes: dict[str, Any]
    created: datetime
    modified: datetime


@dataclass(frozen=True)
class Held:
    """A stored file, as an index that lists it needs it."""

    path: str
    size: int
    md5: str
    sha1: str
    sha256: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class Snapshot:
    """What a repository held at one revision: every file, and when the revision was made."""

    revision: int
    changed: datetime
    files: list[Held]


@dataclass(frozen=True)
class PackageFile:
    """One file of a package, with what its version's component says."""

    path: str
    version: str
    size: int
    sha256: str
    modified: datetime
    attributes: dict[str, Any]  # the file's own
    component_attributes: dict[str, Any]


# What a component is found by is cut to this: a description can be a book.
_SEARCH_MOST = 4000


class TooLarge(Exception):
    """A file that was to be read into memory is larger than the caller allows."""


class Transformer(Protocol):
    """Rewrites content as it is sent, piece by piece."""

    def feed(self, chunk: bytes) -> bytes:
        """What can be sent now that `chunk` has been seen."""

    def finish(self) -> bytes:
        """What is left to send once every piece has been fed."""


async def _nothing() -> AsyncIterator[bytes]:
    return
    yield b""  # what makes this a generator


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

    async def lock(self, name: str) -> None:
        """Serialise work on something a format names, until this transaction ends.

        For a change that is only right if nothing else of its kind happens meanwhile,
        such as deciding that a file is no longer referred to and removing it.
        """
        await self._lock("format", name)

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
                    Asset.last_verified_at,
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
            verified=row.last_verified_at,
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

    async def present(self, paths: Collection[str]) -> set[str]:
        """Which of these paths have a file."""
        if not paths:
            return set()
        rows = await self.db.scalars(
            select(Asset.path).where(
                Asset.repository_id == self.repository.id, Asset.path.in_(paths)
            )
        )
        return set(rows)

    async def references(self, path: str) -> list[str]:
        """The paths the file at `path` refers to, in order."""
        rows = await self.db.scalars(
            select(AssetReference.target)
            .join(Asset, Asset.id == AssetReference.asset_id)
            .where(Asset.repository_id == self.repository.id, Asset.path == path)
            .order_by(AssetReference.target)
        )
        return list(rows)

    async def referenced(self, paths: Collection[str]) -> set[str]:
        """Which of these paths some file in this repository refers to."""
        if not paths:
            return set()
        rows = await self.db.scalars(
            select(AssetReference.target)
            .join(Asset, Asset.id == AssetReference.asset_id)
            .where(Asset.repository_id == self.repository.id, AssetReference.target.in_(paths))
            .distinct()
        )
        return set(rows)

    async def unreferenced(self, prefix: str, *, before: datetime, limit: int) -> list[str]:
        """Files under `prefix` that nothing refers to and that have not changed since `before`.

        For maintenance: what a format stored for the sake of other files, and no file
        ended up using.
        """
        referrer = aliased(Asset)
        used = (
            select(AssetReference.asset_id)
            .join(referrer, referrer.id == AssetReference.asset_id)
            .where(
                referrer.repository_id == self.repository.id,
                AssetReference.target == Asset.path,
            )
            .exists()
        )
        rows = await self.db.scalars(
            select(Asset.path)
            .where(
                Asset.repository_id == self.repository.id,
                Asset.path.startswith(prefix, autoescape=True),
                Asset.updated_at < before,
                ~used,
            )
            .order_by(Asset.path)
            .limit(limit)
        )
        return list(rows)

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

    async def components(self, namespace: str, name: str) -> list[ComponentInfo]:
        """The versions of a package that have a file, with their attributes."""
        rows = await self.db.execute(
            select(
                Component.version,
                Component.attributes,
                Component.created_at,
                func.max(Asset.updated_at),
            )
            .join(Asset, Asset.component_id == Component.id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
            )
            .group_by(Component.id)
        )
        return [
            ComponentInfo(version, attributes, created, changed)
            for version, attributes, created, changed in rows
        ]

    async def package_files(self, namespace: str, name: str) -> list[PackageFile]:
        """Every file of every version of a package, ordered by path."""
        rows = await self.db.execute(
            select(
                Asset.path,
                Component.version,
                Blob.size,
                Blob.sha256,
                Asset.updated_at,
                Asset.attributes,
                Component.attributes,
            )
            .join(Component, Component.id == Asset.component_id)
            .join(Blob, Blob.id == Asset.blob_id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
            )
            .order_by(Asset.path)
        )
        return [PackageFile(*row) for row in rows]

    async def component(self, namespace: str, name: str, version: str) -> ComponentInfo | None:
        """One version of a package, or None if it has no file."""
        row = (
            await self.db.execute(
                select(Component.attributes, Component.created_at, func.max(Asset.updated_at))
                .join(Asset, Asset.component_id == Component.id)
                .where(
                    Component.repository_id == self.repository.id,
                    Component.namespace == namespace,
                    Component.name == name,
                    Component.version == version,
                )
                .group_by(Component.id)
            )
        ).one_or_none()
        return None if row is None else ComponentInfo(version, *row)

    async def package_names(
        self,
        text: str,
        *,
        limit: int,
        offset: int,
        within: Sequence["RepositoryContext"] | None = None,
    ) -> tuple[list[tuple[str, str]], int]:
        """Packages whose name or namespace contains `text`, and how many there are.

        The text is matched literally and without regard to case. An empty text matches
        every package. `within` names the repositories to look in, for a group, which
        holds nothing itself: a package several of them hold is listed once.
        """
        literal = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{literal}%"
        searched = [self] if within is None else within
        found = (
            select(Component.namespace, Component.name)
            .where(
                Component.repository_id.in_([context.repository.id for context in searched]),
                or_(
                    Component.name.ilike(pattern, escape="\\"),
                    Component.namespace.ilike(pattern, escape="\\"),
                ),
            )
            .distinct()
        )
        total = await self.db.scalar(select(func.count()).select_from(found.subquery()))
        rows = await self.db.execute(
            found.order_by(Component.namespace, Component.name).limit(limit).offset(offset)
        )
        return [(namespace, name) for namespace, name in rows], total or 0

    async def revision(self) -> tuple[int, datetime]:
        """This repository's revision, and when it was made, read from the database now.

        A repository that never changed was made at its creation.
        """
        row = (
            await self.db.execute(
                select(Repository.revision, Repository.changed_at, Repository.created_at).where(
                    Repository.id == self.repository.id
                )
            )
        ).one()
        return row.revision, row.changed_at or row.created_at

    async def snapshot(self) -> Snapshot:
        """Every file this repository holds, as one revision of it has them.

        The revision and the files are read in one statement, which sees the database as
        it was at one moment: an index written from a snapshot names exactly the files
        its revision had, however busy the repository is.
        """
        held = (
            select(
                Asset.repository_id,
                Asset.path,
                Asset.attributes,
                Blob.size,
                Blob.md5,
                Blob.sha1,
                Blob.sha256,
            )
            .join(Blob, Blob.id == Asset.blob_id)
            .where(Asset.repository_id == self.repository.id, Asset.kind == "asset")
            .subquery()
        )
        rows = (
            await self.db.execute(
                select(
                    Repository.revision,
                    func.coalesce(Repository.changed_at, Repository.created_at),
                    held.c.path,
                    held.c.size,
                    held.c.md5,
                    held.c.sha1,
                    held.c.sha256,
                    held.c.attributes,
                )
                .outerjoin(held, held.c.repository_id == Repository.id)
                .where(Repository.id == self.repository.id)
                .order_by(held.c.path)
            )
        ).all()
        revision, changed = rows[0][0], rows[0][1]
        files = [Held(*row[2:]) for row in rows if row[2] is not None]
        return Snapshot(revision, changed, files)

    async def public_url(self, request: Request) -> str:
        """The address clients use to reach this repository, without a trailing slash.

        The `base_url` setting if there is one: behind a reverse proxy the request's
        own address may not be the public one.
        """
        base = await get_setting(self.db, "base_url") or str(request.base_url)
        return f"{base.rstrip('/')}/repository/{self.repository.name}"

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

    def open(self, stored: Stored) -> AsyncIterator[bytes]:
        """The bytes of what `stat` described, in pieces. Uses no database."""
        return self.backend.open(stored.sha256)

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
        etag: str | None = None,
        dated: bool = True,
    ) -> Response:
        """Answer a GET or HEAD with bytes made for this request.

        The same planning as for a stored file, so the headers, conditions and ranges
        are the same too. With `etag`, the caller already knows a value that changes
        whenever the bytes do: they are then not hashed here, and no checksum headers
        are sent. With `dated` false, a date a client has (`If-Modified-Since`) does not
        say it has these bytes: only their `ETag` does.
        """

        def digest(algorithm: str) -> str | None:
            return None if etag is not None else hashlib.new(algorithm, data).hexdigest()

        item = serving.Servable(
            sha256=digest("sha256") or "",
            md5=digest("md5"),
            sha1=digest("sha1"),
            sha512=digest("sha512"),
            size=len(data),
            content_type=content_type,
            last_modified=last_modified,
            filename=filename,
            etag=etag,
            dated=dated,
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

    async def _new_revision(self) -> None:
        """Count a change to a hosted repository whose format writes its indexes.

        In the transaction of the change, so that the two are seen together. The row
        is locked until the transaction ends: after a path's lock, and before a blob's
        or a component's, so that two changes to one repository wait in one order.
        """
        if not self.format.derives_indexes or self.repository.type != "hosted":
            return
        await self.db.execute(
            update(Repository)
            .where(Repository.id == self.repository.id)
            .values(
                revision=Repository.revision + 1,
                changed_at=utcnow(),
                updated_at=Repository.updated_at,  # what changed is the content, not it
            )
            .execution_options(synchronize_session=False)
        )

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
                attributes={},
            )
            self._describe(component)
            self.db.add(component)
            await self.db.flush()
        return component

    def _describe(self, component: Component, attributes: dict[str, Any] | None = None) -> None:
        """Write what a component is found by, and its attributes if they are given."""
        if attributes is not None:
            component.attributes = attributes
        key = ComponentKey(component.namespace, component.name, component.version)
        words = self.format.search_text(key, component.attributes)
        component.search = words.lower()[:_SEARCH_MOST]

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

    async def stage_bytes(self, data: bytes) -> StagedBlob:
        """Stage content that is already in memory, such as a file decoded from a body."""
        return await self.stage(_pieces(data))

    def open_staged(self, staged: StagedBlob) -> AsyncIterator[bytes]:
        """Staged content, in pieces, for a format that reads the start of a large upload."""
        return self.backend.open_staged(staged)

    async def read_staged(self, staged: StagedBlob, *, limit: int) -> bytes | None:
        """Staged content, read into memory. None if it is longer than `limit`.

        For a format that has to look inside an upload to know where it belongs.
        """
        if staged.size > limit:
            return None
        return b"".join([chunk async for chunk in self.backend.open_staged(staged)])

    async def discard(self, staged: StagedBlob) -> None:
        """Drop staged content that will not be stored after all.

        For content that was stored after it was staged, this does nothing: whoever
        staged several files can give all of them back without asking which were kept.
        """
        await self.backend.discard(staged)

    async def forget(self, staged: Collection[StagedBlob]) -> None:
        """Remove what staged content became in the store, where no record of it was kept.

        For whoever stored several files in one transaction that was then rolled back:
        each file was put in place as it was stored. Call after the rollback. What
        anything else holds is left alone. The caller commits.
        """
        hashes = [blob.sha256 for blob in staged]
        # A rollback lets go of everything that was loaded, the repository too.
        await self.db.refresh(self.repository)
        await blobs.forget(self.db, self.backend, self.repository.blob_store_id, hashes)

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
        component_attributes: dict[str, Any] | None = None,
    ) -> tuple[Asset, bool]:
        """Tie staged content to a path. `checked` applies permission and policy."""
        try:
            path = normalise_path(path)
            await self._lock("path", path)
            existing = await self.get(path, fresh=True)
            if checked:
                self._check_may_store(existing)
            await self._new_revision()
            blob = await blobs.record(self.db, self.backend, self.repository.blob_store_id, staged)
        except BaseException:
            await self.backend.discard(staged)
            raise

        now = utcnow()
        media_type = _media_type(content_type, path)
        if existing is None:
            key = self.format.describe_component(path, attributes or {}) if packaged else None
            component = None if key is None else await self._component(key)
            if component is not None and component_attributes is not None:
                self._describe(component, component_attributes)
            asset = Asset(
                repository_id=self.repository.id,
                component_id=None if component is None else component.id,
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
        if component_attributes is not None and existing.component_id is not None:
            component = await self.db.get(Component, existing.component_id, populate_existing=True)
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            self._describe(component, component_attributes)
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
        attributes: dict[str, Any] | None = None,
        component_attributes: dict[str, Any] | None = None,
        references: Collection[str] | None = None,
    ) -> tuple[Asset, bool]:
        """Record staged content at a path, in the caller's transaction.

        Checks permission and policy under the path lock. Never commits: the caller
        does, and a rollback undoes everything recorded here. `attributes`, when given,
        become what is recorded about the file itself, and `component_attributes` the
        attributes of the component it belongs to. `references`, when given, are the
        paths of the files in this repository that this one refers to, replacing any
        recorded before.
        """
        asset, created = await self._record(
            path,
            staged,
            content_type=content_type,
            kind=kind,
            checked=True,
            attributes=attributes,
            component_attributes=component_attributes,
        )
        await self._refer(asset, references)
        return asset, created

    async def _refer(self, asset: Asset, references: Collection[str] | None) -> None:
        """Record what a file refers to, in place of what was recorded. None changes nothing."""
        if references is None:
            return
        await self.db.execute(delete(AssetReference).where(AssetReference.asset_id == asset.id))
        targets = sorted(set(references))
        if targets:
            await self.db.execute(
                insert(AssetReference),
                [{"asset_id": asset.id, "target": target} for target in targets],
            )

    async def cache(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None,
        attributes: dict[str, Any],
        now: datetime,
        references: Collection[str] | None = None,
    ) -> Asset:
        """Record content a proxy repository fetched from its remote.

        No permission or policy check: a reader triggered this, and their `read` on the
        proxy (or on the group in front of it) has already been checked. For that reason
        it works only on a proxy repository. `references` are as for `store`; what they
        name need not have been fetched yet.
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
        await self._refer(asset, references)
        return asset

    async def maintain(
        self,
        path: str,
        update: Callable[[bytes | None], Awaitable[bytes | None]],
        *,
        content_type: str,
        limit: int,
        removing: bool = False,
    ) -> None:
        """Change a document the server keeps on an uploader's behalf. The caller commits.

        `update` is given the stored bytes, or None, and returns what to store, or None
        to store nothing. It runs under the path lock, so two changes never overwrite
        each other. This needs `add` or `edit` and is not subject to `disable_redeploy`,
        because the uploader is not replacing anything they published. It refuses a
        path that holds any other kind of file, so it cannot overwrite an artifact.

        `removing` says the change follows something the caller deleted, and is part
        of that: it then needs `delete`, as the deletion did, and nothing more.
        """
        path = normalise_path(path)
        if removing:
            authorize(self.principal, self.permission("delete"), scheme="Basic")
            self._check_policy(replacing=False)
        else:
            self.require_write()
        await self._lock("path", path)
        existing = await self.get(path, fresh=True)
        if existing is not None and existing.kind != _MAINTAINED:
            raise ApiError(409, "conflict", "A file that is not metadata is stored at this path.")
        current = None if existing is None else await self.read(path, limit=limit)
        wanted = await update(current)
        if wanted == current:
            return
        if wanted is not None and len(wanted) > limit:
            # Stored, it could never be read back, and every later change would fail.
            raise ApiError(
                413, "payload_too_large", "The document would be larger than this server keeps."
            )
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

    async def annotate(
        self, namespace: str, name: str, version: str, attributes: dict[str, Any]
    ) -> bool:
        """Replace a component's attributes. False if there is no such component.

        Changing what is said about a published version needs `edit`. It is not a
        redeploy, so `disable_redeploy` does not stop it; a read-only repository does.
        """
        authorize(self.principal, self.permission("edit"), scheme="Basic")
        self._check_policy(replacing=False)
        key = ComponentKey(namespace, name, version)
        await self._lock_component(key)
        component = await self.db.scalar(
            select(Component)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
                Component.version == version,
            )
            .execution_options(populate_existing=True)
        )
        if component is None:
            return False
        self._describe(component, attributes)
        await self.db.flush()
        return True

    async def delete(self, path: str) -> bool:
        """Remove what is at a path. False if there was nothing. The caller commits."""
        path = normalise_path(path)
        authorize(self.principal, self.permission("delete"), scheme="Basic")
        self._check_policy(replacing=False)
        return await self._remove(path)

    async def sweep(self, path: str) -> bool:
        """Remove what is at a path as maintenance does. False if there was nothing.

        Nobody asked for this, so no permission is checked and a read-only repository
        does not stop it. Never call it for a request.
        """
        return await self._remove(normalise_path(path))

    async def _remove(self, path: str) -> bool:
        await self._lock("path", path)
        asset = await self.get(path, fresh=True)
        if asset is None:
            return False
        await self._new_revision()
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

    async def reindex(self, *, after: str = "", limit: int = 500) -> tuple[int, int, str | None]:
        """Give a piece of this repository's files to the components their paths name.

        For rebuilding an index: what an older version stored may belong to no
        component, or to another than it would now. Returns how many files were looked
        at, how many changed hands, and the path to go on after, or None at the end.
        Nobody's permission is involved. The caller commits.
        """
        rows = list(
            await self.db.scalars(
                select(Asset)
                .where(Asset.repository_id == self.repository.id, Asset.path > after)
                .order_by(Asset.path)
                .limit(limit)
            )
        )
        moved = 0
        for asset in rows:
            # What a format keeps for itself was stored as belonging to nothing.
            kept = asset.kind == _MAINTAINED
            key = None if kept else self.format.describe_component(asset.path, asset.attributes)
            component = None if key is None else await self._component(key)
            wanted = None if component is None else component.id
            if asset.component_id != wanted:
                # By statement: the file may have been deleted since the piece was
                # read, and that is no reason to stop.
                given = await self.db.execute(
                    update(Asset).where(Asset.id == asset.id).values(component_id=wanted)
                )
                moved += given.rowcount
        return len(rows), moved, rows[-1].path if len(rows) == limit else None

    async def redescribe(
        self, *, after: uuid.UUID | None = None, limit: int = 500
    ) -> tuple[int, int, uuid.UUID | None]:
        """Write again what a piece of this repository's components are found by.

        A component that has no file left is removed. Returns how many components were
        looked at, how many were removed, and the ID to go on after, or None at the
        end. Nobody's permission is involved. The caller commits.
        """
        wanted = select(Component).where(Component.repository_id == self.repository.id)
        if after is not None:
            wanted = wanted.where(Component.id > after)
        wanted = wanted.order_by(Component.id)
        keys = (Component.id, Component.namespace, Component.name, Component.version)
        rows = (await self.db.execute(wanted.with_only_columns(*keys).limit(limit))).all()
        removed = 0
        for identifier, namespace, name, version in rows:
            # The lock an upload into the component holds, so that one being added to
            # is not taken for empty. Read under it: what is said about the component
            # may have changed since the piece was read.
            await self._lock_component(ComponentKey(namespace, name, version))
            component = await self.db.get(Component, identifier, populate_existing=True)
            if component is None:
                continue  # deleted meanwhile, with its last file
            has_file = await self.db.scalar(
                select(Asset.id).where(Asset.component_id == identifier).limit(1)
            )
            if has_file is None:
                await self.db.delete(component)
                removed += 1
            else:
                self._describe(component)
        await self.db.flush()
        return len(rows), removed, rows[-1][0] if len(rows) == limit else None

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

    async def respond_transformed(
        self,
        path: str,
        request: Request,
        transformer: Transformer,
        *,
        variant: str,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> Response:
        """The response to a GET or HEAD for a stored file, rewritten as it is sent.

        For a file too large to hold in memory whose content depends on who asks, such
        as a document with links to this server in it. `variant` names what the
        transformer does to the file: the `ETag` is made from it and the file's hash, so
        it must change whenever the result would. The length is not known beforehand,
        so none is declared and ranges are not served.
        """
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
            sha256="",
            md5=None,
            sha1=None,
            sha512=None,
            size=0,
            content_type=content_type or asset.content_type,
            last_modified=asset.updated_at,
            filename=filename or path.rpartition("/")[2],
            etag=hashlib.sha256(f"{blob.sha256}\n{variant}".encode()).hexdigest(),
        )
        plan = serving.plan_stream(request.method, request.headers, item)

        now = utcnow()
        noted = asset.last_downloaded_at
        if plan.send_body and (noted is None or now - noted >= _DOWNLOAD_NOTE_INTERVAL):
            asset.last_downloaded_at = now
        await self.db.commit()  # give the connection back before the body is sent

        if plan.status == 304:
            return Response(status_code=304, headers=plan.headers)
        # A streaming response even for HEAD: a plain one would declare a length of 0.
        body = self._transformed(blob.sha256, transformer) if plan.send_body else _nothing()
        return StreamingResponse(body, status_code=plan.status, headers=plan.headers)

    async def respond_stream(
        self,
        request: Request,
        body: Callable[[], AsyncIterator[bytes]],
        *,
        etag: str,
        content_type: str,
        filename: str,
        last_modified: datetime,
    ) -> Response:
        """Answer a GET or HEAD with content that is made as it is sent.

        For content put together from stored files that are too large to hold, such
        as one page made from several. `etag` must change whenever the content would:
        the caller makes it from what the content is built from, so a request that
        already has it is answered without `body` being called. No length is
        declared and ranges are not served.
        """
        item = serving.Servable(
            sha256="",
            md5=None,
            sha1=None,
            sha512=None,
            size=0,
            content_type=content_type,
            last_modified=last_modified,
            filename=filename,
            etag=etag,
        )
        plan = serving.plan_stream(request.method, request.headers, item)
        await self.db.commit()  # give the connection back before the body is sent
        if plan.status == 304:
            return Response(status_code=304, headers=plan.headers)
        # A streaming response even for HEAD: a plain one would declare a length of 0.
        content = body() if plan.send_body else _nothing()
        return StreamingResponse(content, status_code=plan.status, headers=plan.headers)

    async def _transformed(self, sha256: str, transformer: Transformer) -> AsyncIterator[bytes]:
        async for chunk in self.backend.open(sha256):
            passed = transformer.feed(chunk)
            if passed:
                yield passed
        rest = transformer.finish()
        if rest:
            yield rest


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
