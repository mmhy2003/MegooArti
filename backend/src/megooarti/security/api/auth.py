"""Sign in, sign out, and "who am I?"."""

import uuid

import structlog
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.pagination import Page, PageParams, page
from megooarti.security import sessions, sources, users
from megooarti.security.authentication import (
    SESSION_COOKIE,
    Principal,
    authenticate_password,
    build_principal,
    client_ip,
    current_principal,
    refuse_cross_site,
)
from megooarti.security.models import User
from megooarti.system import audit

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


class SignInSource(BaseModel):
    """A source the sign-in screen sends people to, to sign in there (spec 4.3)."""

    id: uuid.UUID
    name: str
    kind: str


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


async def start_session(
    db: AsyncSession, request: Request, response: Response, user: User, **logged: str
) -> SessionInfo:
    """Sign a user in to the web UI: a session, its cookie, and the session's description.
    The user was checked already, by a password or by a provider."""
    settings = request.app.state.settings
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
    audit.identified(principal)
    source = logged.get("source") or (await users.describe(db, user)).source
    audit.record(
        db, "sign_in.succeeded", ("user", user.username), audit.diff(None, {"source": source})
    )
    await db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        value,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    log.info("login_succeeded", username=user.username, ip=client_ip(request), **logged)
    return session_info(principal)


@router.post("/login", response_model=SessionInfo, dependencies=[Depends(refuse_cross_site)])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> SessionInfo:
    user = await authenticate_password(db, request, body.username, body.password)
    return await start_session(db, request, response, user)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    principal: Principal | None = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
) -> None:
    if principal is not None and principal.session is not None:
        await sessions.delete_session(db, principal.session)
        audit.record(db, "session.signed_out", ("user", principal.user.username))
        await db.commit()
        log.info("logout", username=principal.user.username)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/sources", response_model=Page[SignInSource])
async def sign_in_sources(
    params: PageParams = Depends(), db: AsyncSession = Depends(get_session)
) -> dict:
    """The enabled sources people sign in to in the browser, for the sign-in screen. Asked
    before anyone is signed in, so it says no more than their names."""
    shown = [
        SignInSource(id=source.id, name=source.name, kind=source.kind)
        for source in await sources.in_order(db)
        if source.enabled and (kind := sources.KINDS.get(source.kind)) and kind.in_browser
    ]
    return page(shown[params.offset : params.offset + params.limit], len(shown), params)


@router.get("/session", response_model=SessionInfo)
async def session(principal: Principal | None = Depends(current_principal)) -> SessionInfo:
    """Describe the caller. Answers 200 when nobody is signed in, so a UI can start here."""
    return session_info(principal)
