"""Repositories: creating, changing, finding and deleting them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.repositories.formats import format_names, get_format
from megooarti.repositories.models import Repository
from megooarti.storage import blobs
from megooarti.storage.blob_stores import get_blob_store
from megooarti.storage.models import BlobStore

DEPLOYMENT_POLICIES = ("allow_redeploy", "disable_redeploy", "read_only")
# Proxy and group repositories arrive with plan 3b.
_AVAILABLE_TYPES = frozenset({"hosted"})


@dataclass(frozen=True)
class RepositoryView:
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: dict[str, Any] | None
    format_config: dict[str, Any]


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _hosted_settings(hosted: dict[str, Any] | None) -> dict[str, Any]:
    policy = (hosted or {}).get("deployment_policy", "allow_redeploy")
    if policy not in DEPLOYMENT_POLICIES:
        choices = ", ".join(DEPLOYMENT_POLICIES)
        raise _invalid("hosted.deployment_policy", f"Must be one of: {choices}.")
    return {"deployment_policy": policy}


async def get_repository(db: AsyncSession, name: str) -> Repository | None:
    return await db.scalar(select(Repository).where(Repository.name == name))


async def describe(db: AsyncSession, repository: Repository) -> RepositoryView:
    store = None
    if repository.blob_store_id is not None:
        store = await db.scalar(
            select(BlobStore.name).where(BlobStore.id == repository.blob_store_id)
        )
    return RepositoryView(
        name=repository.name,
        format=repository.format,
        type=repository.type,
        online=repository.online,
        blob_store=store,
        url_path=f"/repository/{repository.name}/",
        hosted=repository.config.get("hosted"),
        format_config=repository.config.get("format_config", {}),
    )


async def list_repositories(
    db: AsyncSession, limit: int, offset: int
) -> tuple[list[RepositoryView], int]:
    total = await db.scalar(select(func.count()).select_from(Repository))
    page = list(
        await db.scalars(
            select(Repository).order_by(Repository.name_key).limit(limit).offset(offset)
        )
    )
    return [await describe(db, repository) for repository in page], total or 0


async def create_repository(
    db: AsyncSession,
    *,
    name: str,
    format: str,
    type: str,
    online: bool,
    blob_store: str,
    hosted: dict[str, Any] | None,
    format_config: dict[str, Any] | None,
) -> Repository:
    handler = get_format(format)
    if handler is None:
        known = ", ".join(format_names())
        raise _invalid("format", f"Unknown format. Known formats: {known}.")
    if type not in handler.types or type not in _AVAILABLE_TYPES:
        raise _invalid("type", f"{type} repositories are not available for this format.")
    settings = {
        "hosted": _hosted_settings(hosted),
        "format_config": handler.validate_config(type, format_config or {}),
    }
    store = await get_blob_store(db, blob_store)
    if store is None:
        raise _invalid("blob_store", f"Unknown blob store: {blob_store}.")
    taken = await db.scalar(select(Repository.id).where(Repository.name_key == name.lower()))
    if taken is not None:
        raise ApiError(409, "conflict", f"A repository named {name} already exists.")
    repository = Repository(
        name=name,
        name_key=name.lower(),
        format=format,
        type=type,
        online=online,
        blob_store_id=store.id,
        config=settings,
    )
    db.add(repository)
    await db.flush()
    return repository


async def update_repository(
    db: AsyncSession,
    repository: Repository,
    *,
    online: bool,
    hosted: dict[str, Any] | None,
    format_config: dict[str, Any] | None,
) -> None:
    """Replace what can change. Name, format, type and blob store never do."""
    handler = get_format(repository.format)
    repository.config = {
        "hosted": _hosted_settings(hosted),
        "format_config": handler.validate_config(repository.type, format_config or {}),
    }
    repository.online = online
    await db.flush()


async def delete_repository(db: AsyncSession, repository: Repository, now: datetime) -> None:
    """Delete a repository and everything in it. Its blobs become unreferenced."""
    await db.delete(repository)  # the database removes its components and assets
    await db.flush()
    # One set-based statement, however many assets there were.
    await blobs.mark_unreferenced(db, now)
