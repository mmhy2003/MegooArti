"""Sign in, sign out, and "who am I?"."""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.security import sessions
from megooarti.security.authentication import (
    SESSION_COOKIE,
    Principal,
    authenticate_password,
    build_principal,
    client_ip,
    current_principal,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UserSummary(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None


class SessionInfo(BaseModel):
    authenticated: bool
    method: str | None
    user: UserSummary | None
    permissions: list[str]
    must_change_password: bool
    csrf_token: str | None


def session_info(principal: Principal | None) -> SessionInfo:
    if principal is None:
        return SessionInfo(
            authenticated=False,
            method=None,
            user=None,
            permissions=[],
            must_change_password=False,
            csrf_token=None,
        )
    identified = not principal.is_anonymous
    user = principal.user
    summary = UserSummary(
        id=user.id, username=user.username, display_name=user.display_name, email=user.email
    )
    return SessionInfo(
        authenticated=identified,
        method=principal.method,
        user=summary if identified else None,
        permissions=sorted(principal.patterns),
        must_change_password=principal.is_interactive and user.must_change_password,
        csrf_token=None if principal.session is None else principal.session.csrf_token,
    )


@router.post("/login", response_model=SessionInfo)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> SessionInfo:
    settings = request.app.state.settings
    user = await authenticate_password(db, request, body.username, body.password)
    now = utcnow()
    user.last_login_at = now
    record, value = await sessions.create_session(
        db,
        user.id,
        ip=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
        now=now,
        lifetime_seconds=settings.session_absolute_seconds,
    )
    principal = await build_principal(db, user, "session", session=record)
    await db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        value,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    log.info("login_succeeded", username=user.username, ip=client_ip(request))
    return session_info(principal)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    principal: Principal | None = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    if principal is not None and principal.session is not None:
        await sessions.delete_session(db, principal.session)
        await db.commit()
        log.info("logout", username=principal.user.username)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/session", response_model=SessionInfo)
async def session(principal: Principal | None = Depends(current_principal)) -> SessionInfo:
    """Describe the caller. Answers 200 when nobody is signed in, so a UI can start here."""
    return session_info(principal)
