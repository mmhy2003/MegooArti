"""What a signed-in person may do to their own account."""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.security import oauth, tokens, users
from megooarti.security.api.schemas import ConnectedApp, Pattern, TokenCreated, TokenInfo
from megooarti.security.authentication import (
    Principal,
    authenticate_password,
    require_interactive,
)
from megooarti.security.bootstrap import discard_initial_password
from megooarti.system import audit

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/me", tags=["account"])


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_at: AwareDatetime | None = None
    scopes: list[Pattern] | None = None


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": field, "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


@router.put("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    request: Request,
    principal: Principal = Depends(require_interactive(allow_pending_password_change=True)),
    db: AsyncSession = Depends(get_session),
) -> None:
    user = principal.user
    try:
        await authenticate_password(db, request, user.username, body.current_password)
    except ApiError as error:
        if error.status_code != 401:
            raise
        raise _invalid("body.current_password", "The current password is not correct.") from None
    if body.new_password == body.current_password:
        raise _invalid("password", "The new password must be different from the current one.")
    keep = None if principal.session is None else principal.session.id
    await users.set_password(
        db, user, body.new_password, must_change_password=False, keep_session_id=keep
    )
    audit.record(
        db,
        "user.password_changed",
        ("user", user.username),
        audit.diff(None, None, secrets=["password"]),
    )
    await db.commit()
    discard_initial_password(request.app.state.settings, user)
    log.info("password_changed", username=user.username, by=user.username)


@router.get("/tokens", response_model=Page[TokenInfo])
async def list_tokens(
    params: PageParams = Depends(),
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> dict:
    items, total = await tokens.list_tokens(db, principal.user.id, params.limit, params.offset)
    return page(items, total, params)


@router.post("/tokens", response_model=TokenCreated, status_code=201)
async def create_token(
    body: TokenCreate,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> TokenCreated:
    if body.expires_at is not None and body.expires_at <= utcnow():
        raise _invalid("body.expires_at", "The expiry must be in the future.")
    token, value = await tokens.create_token(
        db, principal.user.id, name=body.name, expires_at=body.expires_at, scopes=body.scopes
    )
    created = TokenCreated(
        id=token.id,
        name=token.name,
        display_prefix=token.display_prefix,
        scopes=token.scopes,
        expires_at=token.expires_at,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        token=value,
    )
    audit.record(
        db,
        "token.created",
        ("token", f"{principal.user.username}/{token.name}"),
        audit.diff(None, {"scopes": token.scopes, "expires_at": token.expires_at}),
    )
    await db.commit()
    log.info("token_created", username=principal.user.username, token=token.name)
    return created


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: uuid.UUID,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> None:
    name = await tokens.revoke_token(db, principal.user.id, token_id)
    audit.record(db, "token.revoked", ("token", f"{principal.user.username}/{name}"))
    await db.commit()
    log.info("token_revoked", username=principal.user.username, by=principal.user.username)


@router.get("/connected-apps", response_model=Page[ConnectedApp])
async def list_connected_apps(
    params: PageParams = Depends(),
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The applications the caller let sign in as them with OAuth, the newest first."""
    every = await oauth.approvals(db, principal.user.id, utcnow())
    return page(every[params.offset : params.offset + params.limit], len(every), params)


@router.delete("/connected-apps/{app_id}", status_code=204)
async def revoke_connected_app(
    app_id: uuid.UUID,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Revoke an approval: the application's tokens stop working at once."""
    client = await oauth.revoke(db, principal.user.id, app_id)
    audit.record(
        db, "connected_app.revoked", ("connected_app", f"{principal.user.username}/{client}")
    )
    await db.commit()
    log.info("connected_app_revoked", username=principal.user.username)
