"""The content API: what the repositories hold, for the people who use them.

`/api/v1/repositories` configures repositories and is an administrator's. This is for
everyone else: which repositories there are to use, what is in them as folders, files
and components, and removing things. Seeing anything needs `browse` on the repository;
downloading goes through the content route and needs `read`, as it always has.
"""

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import browse, service
from megooarti.repositories.formats import Format, get_format
from megooarti.repositories.models import Repository
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import Principal, authorize, require_caller
from megooarti.system.settings_store import get_setting

router = APIRouter(prefix="/content", tags=["content"])


class RepositoryView(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    url: str  # what a client is given: an address, or for a registry a host and a name
    members: list[str] | None = None  # a group's, in the order they are tried


class ComponentRef(BaseModel):
    id: uuid.UUID
    namespace: str
    name: str
    version: str


class Entry(BaseModel):
    name: str
    path: str
    kind: str  # "folder" or "file"
    size: int | None = None
    modified: datetime | None = None
    component: ComponentRef | None = None


class Listing(BaseModel):
    items: list[Entry]
    next: str | None  # give it as `after` for what follows; null at the end


class AssetView(BaseModel):
    path: str
    size: int
    content_type: str
    md5: str
    sha1: str
    sha256: str
    sha512: str
    blob_store: str
    created_by: str
    created: datetime
    modified: datetime
    last_downloaded: datetime | None
    last_verified: datetime | None
    component: ComponentRef | None
    download: str | None  # where the file is fetched, if it has an address of its own


class ComponentView(ComponentRef):
    created: datetime
    modified: datetime


class ComponentDetail(ComponentView):
    files: list[Entry]


def _permission(repository: Repository, action: str) -> str:
    return f"repository:{repository.format}:{repository.name}:{action}"


async def _base(request: Request, db: AsyncSession) -> str:
    """The public address of this server, without a slash at its end."""
    return (await get_setting(db, "base_url") or str(request.base_url)).rstrip("/")


def _handler(repository: Repository) -> Format:
    handler = get_format(repository.format)
    if handler is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return handler


async def _view(db: AsyncSession, repository: Repository, base: str) -> RepositoryView:
    handler = get_format(repository.format)
    if handler is not None and handler.served_at == "registry":
        # A container client is given a host and a name, not an address.
        url = f"{urlsplit(base).netloc}/{repository.name}"
    else:
        url = f"{base}/repository/{repository.name}/"
    members = None
    if repository.type == "group":
        members = await service.member_names(db, repository)
    return RepositoryView(
        name=repository.name,
        format=repository.format,
        type=repository.type,
        online=repository.online,
        url=url,
        members=members,
    )


async def _repository(
    db: AsyncSession, name: str, caller: Principal, action: str = "browse"
) -> Repository:
    """The repository, if the caller may do this to it. Raises 404, 401 or 403."""
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    authorize(caller, _permission(repository, action))
    return repository


async def _holding(db: AsyncSession, name: str, caller: Principal) -> Repository:
    """A repository that holds files of its own, which the caller may browse."""
    repository = await _repository(db, name, caller)
    if repository.type == "group":
        raise ApiError(
            409, "not_browsable", "A group holds nothing of its own. Browse its members."
        )
    return repository


def _entry(child: browse.Child) -> Entry:
    return Entry.model_validate(child, from_attributes=True)


@router.get("", response_model=Page[RepositoryView])
async def list_repositories(
    request: Request,
    params: PageParams = Depends(),
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The repositories the caller may browse."""
    every = await service.all_repositories(db)
    allowed = [found for found in every if caller.allows(_permission(found, "browse"))]
    base = await _base(request, db)
    shown = allowed[params.offset : params.offset + params.limit]
    return page([await _view(db, found, base) for found in shown], len(allowed), params)


@router.get("/{repository}", response_model=RepositoryView)
async def get_repository(
    repository: str,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    found = await _repository(db, repository, caller)
    return await _view(db, found, await _base(request, db))


@router.get("/{repository}/tree", response_model=Listing)
async def list_folder(
    repository: str,
    path: str = "",
    after: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> Listing:
    """What is directly in a folder. An empty `path` is the root of the repository.

    A folder may hold millions of entries, so there is no total: `next` leads on.
    """
    found = await _holding(db, repository, caller)
    folder = path.strip("/")
    if folder:
        normalise_path(folder)
    try:
        items, following = await browse.children(db, found, folder, after=after, limit=limit)
    except browse.BadCursor:
        details = [{"field": "after", "message": "Not something a listing returned."}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None
    if folder and not items and not after:
        raise ApiError(404, "not_found", "No such folder.")
    return Listing(items=[_entry(child) for child in items], next=following)


@router.get("/{repository}/asset", response_model=AssetView)
async def get_asset(
    repository: str,
    path: str,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> AssetView:
    found = await _holding(db, repository, caller)
    detail = await browse.asset(db, found, normalise_path(path))
    if detail is None:
        raise ApiError(404, "not_found", "No such file.")
    address = _handler(found).download_path(found.name, detail.path)
    download = None if address is None else await _base(request, db) + address
    return AssetView.model_validate({**vars(detail), "download": download}, from_attributes=True)


@router.get("/{repository}/components", response_model=Page[ComponentView])
async def list_components(
    repository: str,
    namespace: str | None = None,
    name: str | None = None,
    params: PageParams = Depends(),
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """A repository's components, by namespace and name, the newest first."""
    found = await _holding(db, repository, caller)
    items, total = await browse.components(
        db,
        found,
        unlisted=_handler(found).unlisted_namespaces,
        namespace=namespace,
        name=name,
        limit=params.limit,
        offset=params.offset,
    )
    return page(items, total, params)


@router.get("/{repository}/components/{component_id}", response_model=ComponentDetail)
async def get_component(
    repository: str,
    component_id: uuid.UUID,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> ComponentDetail:
    found = await _holding(db, repository, caller)
    held = await browse.component(
        db, found, component_id, unlisted=_handler(found).unlisted_namespaces
    )
    if held is None:
        raise ApiError(404, "not_found", "No such component.")
    summary, files = held
    return ComponentDetail.model_validate(
        {**vars(summary), "files": [_entry(child) for child in files]}, from_attributes=True
    )
