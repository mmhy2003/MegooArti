"""Administration of sign-in sources (spec 4.3): where people sign in from besides
MegooArti's own users, in the order they are asked."""

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import sources
from megooarti.security.authentication import Principal, require
from megooarti.security.models import AuthSource

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth-sources", tags=["sign-in sources"])

# Shown on the sign-in screen, and part of a user's name where theirs is taken (name@source).
_NAME = r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$"


class Mapping(BaseModel):
    """The roles a member of a group is given (E4)."""

    group: str = Field(min_length=1, max_length=255)
    roles: list[str] = Field(max_length=50)


class SourceIn(BaseModel):
    name: str = Field(pattern=_NAME)
    enabled: bool = False
    # What its kind needs. A secret left out keeps the stored one (E5).
    settings: dict[str, Any] = {}
    group_mapping: list[Mapping] = Field(default=[], max_length=200)


class SourceCreate(SourceIn):
    kind: str = Field(max_length=16)


class SourceOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    enabled: bool
    position: int
    settings: dict[str, Any]  # without its secrets
    secrets: list[str]  # the names of the secrets that are set
    group_mapping: list[Mapping]
    users: int  # how many users sign in through it
    created_at: datetime
    updated_at: datetime


class Order(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)


class TestIn(BaseModel):
    """A name and a password to try, or nothing: only whether the source answers."""

    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=1024)


class TestedUser(BaseModel):
    external_id: str
    username: str
    display_name: str
    email: str | None
    groups: list[str]
    roles: list[str]  # what the group mapping gives them


class TestOut(BaseModel):
    ok: bool
    message: str
    user: TestedUser | None


async def _out(db: AsyncSession, source: AuthSource) -> SourceOut:
    settings, secrets = sources.shown_settings(sources.KINDS.get(source.kind), source.settings)
    return SourceOut(
        id=source.id,
        kind=source.kind,
        name=source.name,
        enabled=source.enabled,
        position=source.position,
        settings=settings,
        secrets=secrets,
        group_mapping=[Mapping(**entry) for entry in source.group_mapping],
        users=await sources.users_of(db, source),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


async def _load(db: AsyncSession, source_id: uuid.UUID) -> AuthSource:
    source = await sources.get_source(db, source_id)
    if source is None:
        raise ApiError(404, "not_found", "No such sign-in source.")
    return source


def _kind(name: str) -> sources.Kind:
    kind = sources.KINDS.get(name)
    if kind is None:
        choices = ", ".join(sorted(sources.KINDS)) or "none yet"
        raise sources.invalid("kind", f"Must be one of: {choices}.")
    return kind


async def _check_name(db: AsyncSession, name: str, own: uuid.UUID | None) -> None:
    if name.casefold() == "local":
        raise sources.invalid("name", "local is the name of MegooArti's own users.")
    holder = await db.scalar(
        select(AuthSource.id).where(func.lower(AuthSource.name) == name.lower())
    )
    if holder is not None and holder != own:
        raise ApiError(409, "conflict", f"A sign-in source named {name} already exists.")


async def _apply(
    db: AsyncSession, request: Request, source: AuthSource, body: SourceIn, kind: sources.Kind
) -> None:
    await _check_name(db, body.name, source.id)
    mapping = [entry.model_dump() for entry in body.group_mapping]
    await sources.check_mapping(db, mapping)
    source.settings = sources.kept_settings(
        request.app.state.settings, kind, body.settings, source.settings or None
    )
    source.name, source.enabled, source.group_mapping = body.name, body.enabled, mapping


@router.get("", response_model=Page[SourceOut])
async def list_sources(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:security:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The sources, in the order they are asked, after MegooArti's own users."""
    every = await sources.in_order(db)
    shown = every[params.offset : params.offset + params.limit]
    return page([await _out(db, source) for source in shown], len(every), params)


@router.post("", response_model=SourceOut, status_code=201)
async def create_source(
    body: SourceCreate,
    request: Request,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SourceOut:
    """A new source, asked after every other. Test it before it is enabled."""
    kind = _kind(body.kind)
    source = AuthSource(kind=body.kind, position=await sources.next_position(db), settings={})
    await _apply(db, request, source, body, kind)
    db.add(source)
    await db.flush()
    result = await _out(db, source)
    await db.commit()
    log.info("auth_source_created", source=source.name, by=principal.user.username)
    return result


@router.put("/order", response_model=Page[SourceOut])
async def order_sources(
    body: Order,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Put the sources in the order they are to be asked: every one of them, once."""
    await sources.reorder(db, body.ids)
    every = await sources.in_order(db)
    items = [await _out(db, source) for source in every]
    await db.commit()
    log.info("auth_sources_ordered", by=principal.user.username)
    return page(items, len(items), PageParams(limit=200, offset=0))


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: uuid.UUID,
    _: Principal = Depends(require("admin:security:read")),
    db: AsyncSession = Depends(get_session),
) -> SourceOut:
    return await _out(db, await _load(db, source_id))


@router.put("/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID,
    body: SourceIn,
    request: Request,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SourceOut:
    """Change a source; its kind stays. Turned off, its users are refused until it is on."""
    source = await _load(db, source_id)
    await _apply(db, request, source, body, _kind(source.kind))
    await db.flush()
    result = await _out(db, source)
    await db.commit()
    log.info("auth_source_updated", source=source.name, by=principal.user.username)
    return result


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a source. Its users are disabled, and kept with what they own."""
    source = await _load(db, source_id)
    await sources.delete_source(db, source)
    await db.commit()
    log.info("auth_source_deleted", source=source.name, by=principal.user.username)


@router.post("/{source_id}/test", response_model=TestOut)
async def test_source(
    source_id: uuid.UUID,
    body: TestIn,
    request: Request,
    _: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> TestOut:
    """Whether the source answers, and, given a name and a password, who it says they are
    and the roles they would be given. Nobody is signed in, or made, by it."""
    source = await _load(db, source_id)
    kind = _kind(source.kind)
    opened = sources.opened_settings(request.app.state.settings, kind, source.settings)
    try:
        tested = await kind.test(opened, body.username, body.password)
    except sources.SourceUnavailable as error:
        return TestOut(ok=False, message=str(error), user=None)
    found = tested.identity
    user = None
    if found is not None:
        user = TestedUser(
            external_id=found.external_id,
            username=found.username,
            display_name=found.display_name,
            email=found.email,
            groups=sorted(found.groups),
            roles=sources.mapped_role_names(source, found.groups),
        )
    return TestOut(ok=tested.ok, message=tested.message, user=user)
