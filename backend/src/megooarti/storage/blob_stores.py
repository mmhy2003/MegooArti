"""Blob stores: named places where blob content is kept."""

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.repositories.models import Repository
from megooarti.storage.backends import BlobBackend, FileBlobBackend
from megooarti.storage.models import Blob, BlobStore

# The one a migration made, and where a repository is put that names none.
DEFAULT_BLOB_STORE = "default"


@dataclass(frozen=True)
class BlobStoreView:
    name: str
    type: str
    path: str
    blob_count: int
    total_bytes: int
    available_bytes: int | None


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _is_absolute(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def _root(settings: Settings, path: str) -> Path:
    return Path(path) if _is_absolute(path) else settings.data_dir / "blobs" / path


def root_of(settings: Settings, store: BlobStore) -> Path:
    return _root(settings, store.config["path"])


def _comparable(root: Path) -> Path:
    """A root in one spelling, so two ways of writing the same directory compare equal."""
    return Path(os.path.normcase(os.path.abspath(root)))


def _overlap(one: Path, other: Path) -> bool:
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def backend_for(settings: Settings, store: BlobStore) -> BlobBackend:
    return FileBlobBackend(root_of(settings, store))


async def get_blob_store(db: AsyncSession, name: str) -> BlobStore | None:
    return await db.scalar(select(BlobStore).where(BlobStore.name == name))


async def describe(db: AsyncSession, settings: Settings, store: BlobStore) -> BlobStoreView:
    count, total = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Blob.size), 0)).where(
                Blob.blob_store_id == store.id
            )
        )
    ).one()
    available = await backend_for(settings, store).available_bytes()
    return BlobStoreView(
        name=store.name,
        type=store.type,
        path=store.config["path"],
        blob_count=count,
        total_bytes=int(total),
        available_bytes=available,
    )


async def list_blob_stores(
    db: AsyncSession, settings: Settings, limit: int, offset: int
) -> tuple[list[BlobStoreView], int]:
    total = await db.scalar(select(func.count()).select_from(BlobStore))
    page = list(
        await db.scalars(select(BlobStore).order_by(BlobStore.name).limit(limit).offset(offset))
    )
    return [await describe(db, settings, store) for store in page], total or 0


async def create_blob_store(
    db: AsyncSession, settings: Settings, *, name: str, type: str, path: str | None
) -> BlobStore:
    if type != "file":
        raise _invalid("type", "The only blob store type is file.")
    if path is None:
        path = name
    parts = PurePosixPath(path.replace("\\", "/")).parts
    if not path.strip() or ".." in parts:
        raise _invalid("path", "The path must not be empty or contain '..'.")
    if await get_blob_store(db, name) is not None:
        raise ApiError(409, "conflict", f"A blob store named {name} already exists.")
    # Two stores over one directory would share files: compacting one would delete
    # content the other still serves.
    root = _comparable(_root(settings, path))
    for other in await db.scalars(select(BlobStore)):
        if _overlap(root, _comparable(root_of(settings, other))):
            raise _invalid("path", f"The directory overlaps the blob store {other.name}.")
    store = BlobStore(name=name, type=type, config={"path": path})
    db.add(store)
    await db.flush()
    return store


async def delete_blob_store(db: AsyncSession, store: BlobStore) -> None:
    """Forget a blob store. Its files stay on disk for the operator to remove."""
    user = await db.scalar(
        select(Repository.name).where(Repository.blob_store_id == store.id).limit(1)
    )
    if user is not None:
        raise ApiError(409, "in_use", f"The repository {user} uses this blob store.")
    if store.name == DEFAULT_BLOB_STORE:
        raise ApiError(
            409,
            "default_blob_store",
            "The default blob store cannot be deleted: "
            "a repository made without naming one is put in it.",
        )
    # With no repository there is no asset, so every remaining blob is unreferenced.
    await db.execute(delete(Blob).where(Blob.blob_store_id == store.id))
    await db.delete(store)
    await db.flush()
