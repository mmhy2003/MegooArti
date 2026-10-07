"""Administration of blob stores."""

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security.authentication import Principal, require
from megooarti.storage import blob_stores
from megooarti.storage.blob_stores import BlobStoreView
from megooarti.storage.models import BlobStore

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/blob-stores", tags=["blob stores"])


class BlobStoreOut(BaseModel):
    name: str
    type: str
    path: str
    blob_count: int
    total_bytes: int
    available_bytes: int | None


class BlobStoreCreate(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    type: str = "file"
    path: str | None = Field(default=None, max_length=1024)


async def _load(db: AsyncSession, name: str) -> BlobStore:
    store = await blob_stores.get_blob_store(db, name)
    if store is None:
        raise ApiError(404, "not_found", "No such blob store.")
    return store


@router.get("", response_model=Page[BlobStoreOut])
async def list_blob_stores(
    request: Request,
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:blobstores:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    settings = request.app.state.settings
    items, total = await blob_stores.list_blob_stores(db, settings, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=BlobStoreOut, status_code=201)
async def create_blob_store(
    body: BlobStoreCreate,
    request: Request,
    principal: Principal = Depends(require("admin:blobstores:write")),
    db: AsyncSession = Depends(get_session),
) -> BlobStoreView:
    settings = request.app.state.settings
    store = await blob_stores.create_blob_store(
        db, settings, name=body.name, type=body.type, path=body.path
    )
    view = await blob_stores.describe(db, settings, store)
    await db.commit()
    log.info("blob_store_created", blob_store=store.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=BlobStoreOut)
async def get_blob_store(
    name: str,
    request: Request,
    _: Principal = Depends(require("admin:blobstores:read")),
    db: AsyncSession = Depends(get_session),
) -> BlobStoreView:
    return await blob_stores.describe(db, request.app.state.settings, await _load(db, name))


@router.delete("/{name}", status_code=204)
async def delete_blob_store(
    name: str,
    principal: Principal = Depends(require("admin:blobstores:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    store = await _load(db, name)
    await blob_stores.delete_blob_store(db, store)
    await db.commit()
    log.info("blob_store_deleted", blob_store=name, by=principal.user.username)
