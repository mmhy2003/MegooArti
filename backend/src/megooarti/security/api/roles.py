"""Administration of roles."""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import roles
from megooarti.security.api.schemas import Pattern
from megooarti.security.authentication import Principal, require
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import Role
from megooarti.security.roles import RoleView

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/roles", tags=["roles"])


class RoleOut(BaseModel):
    name: str
    description: str
    builtin: bool
    permissions: list[str]
    roles: list[str]


class RoleContent(BaseModel):
    description: str = Field(default="", max_length=255)
    permissions: list[Pattern] = []
    roles: list[str] = []


class RoleCreate(RoleContent):
    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")


async def _load(db: AsyncSession, name: str) -> Role:
    role = await roles.get_role(db, name)
    if role is None:
        raise ApiError(404, "not_found", "No such role.")
    return role


@router.get("", response_model=Page[RoleOut])
async def list_roles(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:roles:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await roles.list_roles(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreate,
    principal: Principal = Depends(require("admin:roles:write")),
    db: AsyncSession = Depends(get_session),
) -> RoleView:
    role = await roles.create_role(db, body.name, body.description, body.permissions, body.roles)
    view = await roles.describe(db, role)
    await db.commit()
    log.info("role_created", role=role.name, by=principal.user.username)
    return view


@router.get("/{name}", response_model=RoleOut)
async def get_role(
    name: str,
    _: Principal = Depends(require("admin:roles:read")),
    db: AsyncSession = Depends(get_session),
) -> RoleView:
    return await roles.describe(db, await _load(db, name))


@router.put("/{name}", response_model=RoleOut)
async def update_role(
    name: str,
    body: RoleContent,
    principal: Principal = Depends(require("admin:roles:write")),
    db: AsyncSession = Depends(get_session),
) -> RoleView:
    role = await _load(db, name)
    await roles.update_role(db, role, body.description, body.permissions, body.roles)
    await ensure_administrator_remains(db)
    view = await roles.describe(db, role)
    await db.commit()
    log.info("role_updated", role=role.name, by=principal.user.username)
    return view


@router.delete("/{name}", status_code=204)
async def delete_role(
    name: str,
    principal: Principal = Depends(require("admin:roles:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    role = await _load(db, name)
    await roles.delete_role(db, role)
    await ensure_administrator_remains(db)
    await db.commit()
    log.info("role_deleted", role=name, by=principal.user.username)
