"""Cleanup policies (spec 4): criteria of a format, or of every format, that select the
components to remove from the repositories they are attached to. Kept with
`admin:cleanup:read` and `write`."""

import uuid
from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.cleanup import selection
from megooarti.cleanup.criteria import ANY_FORMAT, Criteria, problems
from megooarti.cleanup.models import CleanupPolicy, RepositoryCleanupPolicy
from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.names import NewName
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import api as repositories_api
from megooarti.repositories import service
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Asset, Repository
from megooarti.security import access
from megooarti.security.authentication import Principal, require
from megooarti.system import audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/cleanup-policies", tags=["cleanup policies"])


class PolicyContent(BaseModel):
    description: str = Field(default="", max_length=255)
    updated_days: int | None = None
    downloaded_days: int | None = None
    release_type: Literal["release", "prerelease"] | None = None
    asset_pattern: str | None = Field(default=None, max_length=1000)
    # Accepted so a client can send back what it read, but it cannot change (E9).
    format: str | None = Field(default=None, max_length=32)

    @property
    def criteria(self) -> Criteria:
        return Criteria(
            updated_days=self.updated_days,
            downloaded_days=self.downloaded_days,
            release_type=self.release_type,
            asset_pattern=self.asset_pattern,
        )


class PolicyCreate(PolicyContent):
    name: NewName
    format: str = Field(max_length=32)  # a format's name, or `*` for every format


class Previewing(PolicyContent):
    format: str = Field(max_length=32)
    repository: str = Field(max_length=64)


class Selected(BaseModel):
    """A component a policy would remove."""

    id: uuid.UUID
    namespace: str
    name: str
    version: str
    modified: datetime
    last_downloaded: datetime | None


class PolicyOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    format: str
    updated_days: int | None
    downloaded_days: int | None
    release_type: str | None
    asset_pattern: str | None
    repositories: list[str]  # those it is attached to, by name
    created_at: datetime
    updated_at: datetime


def _refused(found: list[dict[str, str]]) -> None:
    if found:
        raise ApiError(422, "validation_error", "The request is not valid.", found)


def _told(policy: CleanupPolicy) -> dict[str, Any]:
    """A policy as its records tell it."""
    return {
        "description": policy.description,
        "format": policy.format,
        "updated_days": policy.updated_days,
        "downloaded_days": policy.downloaded_days,
        "release_type": policy.release_type,
        "asset_pattern": policy.asset_pattern,
    }


def _set(policy: CleanupPolicy, body: PolicyContent) -> None:
    policy.description = body.description
    policy.updated_days = body.updated_days
    policy.downloaded_days = body.downloaded_days
    policy.release_type = body.release_type
    policy.asset_pattern = body.asset_pattern


async def attached_to(db: AsyncSession, policy: CleanupPolicy) -> list[str]:
    """The names of the repositories a policy is attached to, in name order."""
    return list(
        await db.scalars(
            select(Repository.name)
            .join(RepositoryCleanupPolicy, RepositoryCleanupPolicy.repository_id == Repository.id)
            .where(RepositoryCleanupPolicy.policy_id == policy.id)
            .order_by(Repository.name_key)
        )
    )


async def _shown(db: AsyncSession, policy: CleanupPolicy) -> PolicyOut:
    return PolicyOut(
        id=policy.id,
        name=policy.name,
        repositories=await attached_to(db, policy),
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        **_told(policy),
    )


async def _load(db: AsyncSession, name: str) -> CleanupPolicy:
    found = await db.scalar(select(CleanupPolicy).where(CleanupPolicy.name == name))
    if found is None:
        raise ApiError(404, "not_found", "No such cleanup policy.")
    return found


@router.get("", response_model=Page[PolicyOut])
async def list_policies(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:cleanup:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    total = await db.scalar(select(func.count()).select_from(CleanupPolicy))
    found = await db.scalars(
        select(CleanupPolicy)
        .order_by(CleanupPolicy.name_key)
        .limit(params.limit)
        .offset(params.offset)
    )
    return page([await _shown(db, policy) for policy in found], total or 0, params)


@router.post("", response_model=PolicyOut, status_code=201)
async def create_policy(
    body: PolicyCreate,
    principal: Principal = Depends(require("admin:cleanup:write")),
    db: AsyncSession = Depends(get_session),
) -> PolicyOut:
    _refused(problems(body.format, body.criteria))
    taken = await db.scalar(
        select(CleanupPolicy.id).where(CleanupPolicy.name_key == body.name.lower())
    )
    if taken is not None:
        raise ApiError(409, "conflict", f"A cleanup policy named {body.name} already exists.")
    policy = CleanupPolicy(name=body.name, name_key=body.name.lower(), format=body.format)
    _set(policy, body)
    db.add(policy)
    await db.flush()
    audit.record(
        db,
        "cleanup_policy.created",
        ("cleanup_policy", policy.name),
        audit.diff(None, _told(policy)),
    )
    await db.commit()
    log.info("cleanup_policy_created", policy=policy.name, by=principal.user.username)
    return await _shown(db, policy)


@router.post("/preview", response_model=Page[Selected])
async def preview_policy(
    body: Previewing,
    request: Request,
    params: PageParams = Depends(),
    caller: Principal = Depends(require("admin:cleanup:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """What a policy, kept or not, would remove from a repository now: of what the caller
    may browse there, newest first. Nothing is removed."""
    _refused(problems(body.format, body.criteria))
    repository = await service.get_repository(db, body.repository)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    if repository.type == "group" or body.format not in (repository.format, ANY_FORMAT):
        message = "A hosted or proxy repository of the policy's format."
        _refused([{"field": "repository", "message": message}])
    context = await build_context(db, request.app.state.settings, repository, caller)
    found, total = await selection.preview(
        context,
        body.criteria,
        utcnow(),
        limit=params.limit,
        offset=params.offset,
        reached=access.reach(caller, repository, "browse"),
    )
    items = [
        Selected(
            id=held.id,
            namespace=held.namespace,
            name=held.name,
            version=held.version,
            modified=held.modified,
            # `downloaded` is when it was made where nothing was downloaded: not a download.
            last_downloaded=await _last_download(db, held.id),
        )
        for held in found
    ]
    return page(items, total, params)


async def _last_download(db: AsyncSession, component_id: uuid.UUID) -> datetime | None:
    return await db.scalar(
        select(func.max(Asset.last_downloaded_at)).where(Asset.component_id == component_id)
    )


@router.get("/{name}", response_model=PolicyOut)
async def get_policy(
    name: str,
    _: Principal = Depends(require("admin:cleanup:read")),
    db: AsyncSession = Depends(get_session),
) -> PolicyOut:
    return await _shown(db, await _load(db, name))


@router.put("/{name}", response_model=PolicyOut)
async def update_policy(
    name: str,
    body: PolicyContent,
    principal: Principal = Depends(require("admin:cleanup:write")),
    db: AsyncSession = Depends(get_session),
) -> PolicyOut:
    """Change what a policy selects: from the next run, for every repository it is
    attached to."""
    policy = await _load(db, name)
    if body.format is not None and body.format != policy.format:
        raise ApiError(409, "immutable", "A cleanup policy's format cannot be changed.")
    _refused(problems(policy.format, body.criteria))
    before = _told(policy)
    _set(policy, body)
    await db.flush()
    audit.record(
        db,
        "cleanup_policy.updated",
        ("cleanup_policy", policy.name),
        audit.diff(before, _told(policy)),
    )
    await db.commit()
    log.info("cleanup_policy_updated", policy=policy.name, by=principal.user.username)
    return await _shown(db, policy)


@router.delete("/{name}", status_code=204)
async def delete_policy(
    name: str,
    principal: Principal = Depends(require("admin:cleanup:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a policy, detaching it from every repository it is attached to (E10)."""
    policy = await _load(db, name)
    holding = list(
        await db.scalars(
            select(Repository)
            .join(RepositoryCleanupPolicy, RepositoryCleanupPolicy.repository_id == Repository.id)
            .where(RepositoryCleanupPolicy.policy_id == policy.id)
            .order_by(Repository.name_key)
        )
    )
    was = {repository.id: await service.describe(db, repository) for repository in holding}
    before = _told(policy)
    await db.delete(policy)
    await db.flush()
    for repository in holding:
        audit.record(
            db,
            "repository.updated",
            ("repository", repository.name),
            audit.diff(
                repositories_api.told(was[repository.id]),
                repositories_api.told(await service.describe(db, repository)),
            ),
        )
    audit.record(db, "cleanup_policy.deleted", ("cleanup_policy", name), audit.diff(before, None))
    await db.commit()
    log.info("cleanup_policy_deleted", policy=name, by=principal.user.username)
