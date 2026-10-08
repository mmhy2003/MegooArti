"""Administration of repositories."""

from datetime import datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.config import Settings
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import service
from megooarti.repositories.models import Repository
from megooarti.repositories.service import RepositoryView
from megooarti.secrets_box import seal
from megooarti.security.authentication import Principal, require

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/repositories", tags=["repositories"])

# The same characters as a permission segment, so a name can never shift a permission.
_NAME = r"^[A-Za-z0-9_.-]{1,64}$"


class HostedSettings(BaseModel):
    deployment_policy: Literal["allow_redeploy", "disable_redeploy", "read_only"] = "allow_redeploy"


class NegativeCache(BaseModel):
    enabled: bool = True
    ttl_minutes: int = Field(default=1440, ge=1)


class RemoteAuthIn(BaseModel):
    type: Literal["none", "basic", "bearer"] = "none"
    username: str = Field(default="", max_length=255)
    # Write-only. Leave it out on an update to keep the stored secret.
    secret: str | None = Field(default=None, min_length=1, max_length=4096)


class ProxyIn(BaseModel):
    remote_url: str = Field(min_length=1, max_length=2048)
    content_max_age_minutes: int = Field(default=1440, ge=-1)
    metadata_max_age_minutes: int = Field(default=1440, ge=-1)
    negative_cache: NegativeCache = NegativeCache()
    remote_auth: RemoteAuthIn = RemoteAuthIn()
    blocked: bool = False
    auto_block: bool = True


class RemoteAuthOut(BaseModel):
    type: str
    username: str
    has_secret: bool


class ProxyOut(BaseModel):
    remote_url: str
    content_max_age_minutes: int
    metadata_max_age_minutes: int
    negative_cache: NegativeCache
    remote_auth: RemoteAuthOut
    blocked: bool
    auto_block: bool


class GroupSettings(BaseModel):
    members: list[str] = []


class ProxyStatus(BaseModel):
    blocked: bool
    auto_blocked_until: datetime | None
    failures: int
    last_error: str | None


class RepositoryOut(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    blob_store: str | None
    url_path: str
    hosted: HostedSettings | None
    format_config: dict[str, Any]
    proxy: ProxyOut | None
    group: GroupSettings | None
    status: ProxyStatus | None


class RepositoryCreate(BaseModel):
    name: str = Field(pattern=_NAME)
    format: str
    type: Literal["hosted", "proxy", "group"]
    online: bool = True
    blob_store: str | None = None
    hosted: HostedSettings | None = None
    proxy: ProxyIn | None = None
    group: GroupSettings | None = None
    format_config: dict[str, Any] = {}


class RepositoryUpdate(BaseModel):
    online: bool = True
    hosted: HostedSettings | None = None
    proxy: ProxyIn | None = None
    group: GroupSettings | None = None
    format_config: dict[str, Any] = {}
    # Accepted so a client can send back what it read, but they cannot change.
    format: str | None = None
    type: str | None = None
    blob_store: str | None = None


def _plain(model: BaseModel | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump()


def _proxy(settings: Settings, proxy: ProxyIn | None) -> dict[str, Any] | None:
    """The proxy settings as the service takes them, with the secret sealed."""
    if proxy is None:
        return None
    values = proxy.model_dump()
    secret = values["remote_auth"]["secret"]
    if secret is not None:
        values["remote_auth"]["secret"] = seal(settings, secret)
    return values


async def _load(db: AsyncSession, name: str) -> Repository:
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    return repository


@router.get("", response_model=Page[RepositoryOut])
async def list_repositories(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await service.list_repositories(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=RepositoryOut, status_code=201)
async def create_repository(
    body: RepositoryCreate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await service.create_repository(
        db,
        name=body.name,
        format=body.format,
        type=body.type,
        online=body.online,
        blob_store=body.blob_store,
        hosted=_plain(body.hosted),
        proxy=_proxy(request.app.state.settings, body.proxy),
        group=_plain(body.group),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    await db.commit()
    log.info("repository_created", repository=repository.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=RepositoryOut)
async def get_repository(
    name: str,
    _: Principal = Depends(require("admin:repositories:read")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    return await service.describe(db, await _load(db, name))


@router.put("/{name}", response_model=RepositoryOut)
async def update_repository(
    name: str,
    body: RepositoryUpdate,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    repository = await _load(db, name)
    current = await service.describe(db, repository)
    fixed = {"format": current.format, "type": current.type, "blob_store": current.blob_store}
    for field, value in fixed.items():
        sent = getattr(body, field)
        if sent is not None and sent != value:
            raise ApiError(409, "immutable", f"A repository's {field} cannot be changed.")
    await service.update_repository(
        db,
        repository,
        online=body.online,
        hosted=_plain(body.hosted),
        proxy=_proxy(request.app.state.settings, body.proxy),
        group=_plain(body.group),
        format_config=body.format_config,
    )
    view = await service.describe(db, repository)
    await db.commit()
    log.info("repository_updated", repository=repository.name, by=principal.user.username)
    return view


@router.delete("/{name}", status_code=204)
async def delete_repository(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    await service.delete_repository(db, repository, utcnow())
    await db.commit()
    log.info("repository_deleted", repository=name, by=principal.user.username)


@router.post("/{name}/invalidate-cache", status_code=204)
async def invalidate_cache(
    name: str,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    repository = await _load(db, name)
    await service.invalidate_cache(db, repository)
    await db.commit()
    log.info("repository_cache_invalidated", repository=name, by=principal.user.username)
