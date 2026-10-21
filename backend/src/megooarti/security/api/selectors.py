"""Content selectors (spec 10): named expressions of a repository's format and paths, which
selector permissions (`selector:<name>:<format>:<repository>:<action>`) name. Kept with
`admin:selectors:read` and `write`; one a role names is not deleted."""

import uuid
from datetime import datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.names import NewName
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories.paths import MAX_PATH_BYTES
from megooarti.security.authentication import Principal, require
from megooarti.security.models import ContentSelector, Role, RolePermission
from megooarti.security.selectors import MAX_LENGTH, SelectorError, parse
from megooarti.system import audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/content-selectors", tags=["content selectors"])


class SelectorOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    expression: str
    created_at: datetime
    updated_at: datetime


class SelectorContent(BaseModel):
    description: str = Field(default="", max_length=255)
    expression: str = Field(min_length=1, max_length=MAX_LENGTH)


class SelectorCreate(SelectorContent):
    name: NewName


class Preview(BaseModel):
    expression: str = Field(min_length=1, max_length=MAX_LENGTH)
    format: str = Field(default="", max_length=32)
    # A path is at most as long as one kept can be.
    paths: list[Annotated[str, Field(max_length=MAX_PATH_BYTES)]] = Field(
        default=[], max_length=100
    )


class Previewed(BaseModel):
    path: str
    matches: bool


class PreviewOut(BaseModel):
    paths: list[Previewed]


def _parsed(expression: str, field: str = "expression") -> None:
    """Refuse an expression that does not parse, at its field, saying where."""
    try:
        parse(expression)
    except SelectorError as error:
        details = [{"field": field, "message": str(error)}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None


def _told(selector: ContentSelector) -> dict:
    return {"description": selector.description, "expression": selector.expression}


async def _load(db: AsyncSession, name: str) -> ContentSelector:
    found = await db.scalar(select(ContentSelector).where(ContentSelector.name == name))
    if found is None:
        raise ApiError(404, "not_found", "No such content selector.")
    return found


@router.get("", response_model=Page[SelectorOut])
async def list_selectors(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:selectors:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    total = await db.scalar(select(func.count()).select_from(ContentSelector))
    found = await db.scalars(
        select(ContentSelector)
        .order_by(ContentSelector.name)
        .limit(params.limit)
        .offset(params.offset)
    )
    return page(list(found), total or 0, params)


@router.post("", response_model=SelectorOut, status_code=201)
async def create_selector(
    body: SelectorCreate,
    principal: Principal = Depends(require("admin:selectors:write")),
    db: AsyncSession = Depends(get_session),
) -> ContentSelector:
    _parsed(body.expression)
    if await db.scalar(select(ContentSelector.id).where(ContentSelector.name == body.name)):
        raise ApiError(409, "conflict", f"A content selector named {body.name} already exists.")
    selector = ContentSelector(
        name=body.name, description=body.description, expression=body.expression
    )
    db.add(selector)
    await db.flush()
    audit.record(
        db, "selector.created", ("selector", selector.name), audit.diff(None, _told(selector))
    )
    await db.commit()
    log.info("selector_created", selector=selector.name, by=principal.user.username)
    return selector


@router.post("/preview", response_model=PreviewOut)
async def preview(
    body: Preview,
    _: Principal = Depends(require("admin:selectors:read")),
) -> PreviewOut:
    """Which of these paths an expression matches, in a repository of this format. A path
    is taken as starting with `/`."""
    _parsed(body.expression)
    expression = parse(body.expression)
    paths = [path if path.startswith("/") else f"/{path}" for path in body.paths]
    return PreviewOut(
        paths=[
            Previewed(path=path, matches=expression.matches(body.format, path)) for path in paths
        ]
    )


@router.get("/{name}", response_model=SelectorOut)
async def get_selector(
    name: str,
    _: Principal = Depends(require("admin:selectors:read")),
    db: AsyncSession = Depends(get_session),
) -> ContentSelector:
    return await _load(db, name)


@router.put("/{name}", response_model=SelectorOut)
async def update_selector(
    name: str,
    body: SelectorContent,
    principal: Principal = Depends(require("admin:selectors:write")),
    db: AsyncSession = Depends(get_session),
) -> ContentSelector:
    """Change what a selector matches: at once, for every permission that names it."""
    _parsed(body.expression)
    selector = await _load(db, name)
    before = _told(selector)
    selector.description, selector.expression = body.description, body.expression
    await db.flush()
    audit.record(
        db, "selector.updated", ("selector", selector.name), audit.diff(before, _told(selector))
    )
    await db.commit()
    log.info("selector_updated", selector=selector.name, by=principal.user.username)
    return selector


@router.delete("/{name}", status_code=204)
async def delete_selector(
    name: str,
    principal: Principal = Depends(require("admin:selectors:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a selector no role names."""
    selector = await _load(db, name)
    naming = list(
        await db.scalars(
            select(Role.name)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(
                or_(
                    RolePermission.pattern == f"selector:{name}",
                    RolePermission.pattern.startswith(f"selector:{name}:", autoescape=True),
                )
            )
            .distinct()
            .order_by(Role.name)
        )
    )
    if naming:
        raise ApiError(409, "in_use", f"Roles name this content selector: {', '.join(naming)}.")
    before = _told(selector)
    await db.delete(selector)
    audit.record(db, "selector.deleted", ("selector", name), audit.diff(before, None))
    await db.commit()
    log.info("selector_deleted", selector=name, by=principal.user.username)
