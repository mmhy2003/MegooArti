"""Administration of users, and of other people's API tokens."""

import uuid
from datetime import datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import tokens, users
from megooarti.security.api.schemas import TokenInfo
from megooarti.security.authentication import Principal, require
from megooarti.security.bootstrap import discard_initial_password
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.models import User
from megooarti.security.users import UserView

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])

_USERNAME = r"^[A-Za-z0-9._@-]{1,64}$"
_EMAIL = r"^[^@\s]+@[^@\s]+$"


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    status: str
    must_change_password: bool
    builtin: bool
    roles: list[str]
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(BaseModel):
    username: str = Field(pattern=_USERNAME)
    display_name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)
    password: str = Field(max_length=1024)
    roles: list[str] = []
    must_change_password: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=254, pattern=_EMAIL)
    status: Literal["active", "disabled"] | None = None
    roles: list[str] | None = None


class PasswordReset(BaseModel):
    password: str = Field(max_length=1024)
    must_change_password: bool = True


async def _load(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await users.get_user(db, user_id)
    if user is None:
        raise ApiError(404, "not_found", "No such user.")
    return user


@router.get("", response_model=Page[UserOut])
async def list_users(
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:users:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await users.list_users(db, params.limit, params.offset)
    return page(items, total, params)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> UserView:
    user = await users.create_user(
        db,
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        password=body.password,
        role_names=body.roles,
        must_change_password=body.must_change_password,
    )
    view = await users.describe(db, user)
    await db.commit()
    log.info("user_created", username=user.username, by=principal.user.username)
    return view


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    _: Principal = Depends(require("admin:users:read")),
    db: AsyncSession = Depends(get_session),
) -> UserView:
    return await users.describe(db, await _load(db, user_id))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> UserView:
    user = await _load(db, user_id)
    # A field sent as null means "no change", except email, where null clears it.
    changes = {
        name: value
        for name, value in body.model_dump(exclude_unset=True).items()
        if value is not None or name == "email"
    }
    if user.id == principal.user.id and changes.get("status") == "disabled":
        raise ApiError(409, "self_protected", "You cannot disable your own account.")
    await users.update_user(db, user, changes)
    await ensure_administrator_remains(db)
    view = await users.describe(db, user)
    await db.commit()
    log.info("user_updated", username=user.username, by=principal.user.username)
    return view


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: uuid.UUID,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await _load(db, user_id)
    if user.id == principal.user.id:
        raise ApiError(409, "self_protected", "You cannot delete your own account.")
    await users.delete_user(db, user)
    await ensure_administrator_remains(db)
    await db.commit()
    log.info("user_deleted", username=user.username, by=principal.user.username)


@router.put("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    request: Request,
    principal: Principal = Depends(require("admin:users:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await _load(db, user_id)
    if user.id == principal.user.id:
        # Here nobody is asked who they are: a session left open, or a stolen cookie,
        # would be enough to keep the account.
        raise ApiError(
            409,
            "own_password",
            "Change your own password at PUT /api/v1/me/password, which asks for the present one.",
        )
    await users.set_password(
        db, user, body.password, must_change_password=body.must_change_password
    )
    await db.commit()
    discard_initial_password(request.app.state.settings, user)
    log.info("password_changed", username=user.username, by=principal.user.username)


@router.get("/{user_id}/tokens", response_model=Page[TokenInfo])
async def list_user_tokens(
    user_id: uuid.UUID,
    params: PageParams = Depends(),
    _: Principal = Depends(require("admin:tokens:read")),
    db: AsyncSession = Depends(get_session),
) -> dict:
    user = await _load(db, user_id)
    items, total = await tokens.list_tokens(db, user.id, params.limit, params.offset)
    return page(items, total, params)


@router.delete("/{user_id}/tokens/{token_id}", status_code=204)
async def revoke_user_token(
    user_id: uuid.UUID,
    token_id: uuid.UUID,
    principal: Principal = Depends(require("admin:tokens:write")),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = await _load(db, user_id)
    await tokens.revoke_token(db, user.id, token_id)
    await db.commit()
    log.info("token_revoked", username=user.username, by=principal.user.username)
