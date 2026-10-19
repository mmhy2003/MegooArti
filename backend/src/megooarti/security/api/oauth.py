"""OAuth's addresses (MCP spec 7): what a client finds (RFC 9728, RFC 8414), registers
at (RFC 7591), sends a person to (authorize), and trades a code at (token); and the
web UI's consent page's calls."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.security import oauth
from megooarti.security.authentication import Principal, client_ip, require_interactive
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

well_known = APIRouter(prefix="/.well-known", include_in_schema=False)
endpoints = APIRouter(prefix="/oauth", include_in_schema=False)
consent = APIRouter(prefix="/oauth", tags=["account"])

_NO_STORE = {"Cache-Control": "no-store"}


async def issuer(db: AsyncSession) -> str:
    """This server as OAuth names it: its base URL, which must be set (spec 7.1)."""
    base = await get_setting(db, "base_url")
    if not base:
        raise oauth.OAuthError(
            "temporarily_unavailable",
            "Sign-in with OAuth needs the server's base URL: an administrator sets it "
            "under System.",
            503,
        )
    return str(base).rstrip("/")


def _answer(error: oauth.OAuthError) -> JSONResponse:
    return JSONResponse(
        {"error": error.error, "error_description": error.description},
        status_code=error.status,
        headers=_NO_STORE,
    )


# --- Discovery ------------------------------------------------------------------------


@well_known.get("/oauth-protected-resource/mcp")
@well_known.get("/oauth-protected-resource")
async def protected_resource(db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """What protects /mcp, and who signs a client in to it (RFC 9728)."""
    try:
        base = await issuer(db)
    except oauth.OAuthError as error:
        return _answer(error)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": [],
        }
    )


@well_known.get("/oauth-authorization-server")
async def authorization_server(db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """How a client is signed in here (RFC 8414)."""
    try:
        base = await issuer(db)
    except oauth.OAuthError as error:
        return _answer(error)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [],
        }
    )


# --- Registration ---------------------------------------------------------------------


class Registration(BaseModel):
    client_name: str = Field(default="", max_length=4096)  # cut to 200 when kept
    redirect_uris: list[str] = Field(default=[], max_length=10)


@endpoints.post("/register")
async def register(request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A client registers itself (RFC 7591), as any may: a person still approves it."""
    body = await request.body()
    if len(body) > 16 * 1024:
        return _answer(oauth.OAuthError("invalid_client_metadata", "At most 16 KiB.", 413))
    try:
        said = Registration.model_validate_json(body)
    except ValueError:
        return _answer(oauth.OAuthError("invalid_client_metadata", "The metadata is not valid."))
    try:
        client = await oauth.register(
            db, said.client_name, said.redirect_uris, client_ip(request), utcnow()
        )
    except oauth.OAuthError as error:
        return _answer(error)
    described = oauth.describe(client)
    await db.commit()
    log.info("oauth_client_registered", client=described["client_id"], name=client.name)
    return JSONResponse(described, status_code=201, headers=_NO_STORE)


# --- Authorization --------------------------------------------------------------------


@endpoints.get("/authorize", response_model=None)
async def authorize(
    request: Request,
    client_id: str = "",
    redirect_uri: str = "",
    response_type: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    state: str | None = None,
    resource: str = "",
    db: AsyncSession = Depends(get_session),
) -> JSONResponse | RedirectResponse:
    """Check what a client asks, and send the person to the consent page with it sealed.

    Whatever is wrong is answered here, never at the client's redirect address.
    """
    try:
        base = await issuer(db)
    except oauth.OAuthError as error:
        return _answer(error)
    client = await oauth.get_client(db, client_id)
    if client is None:
        return _answer(oauth.OAuthError("invalid_client", "No such client."))
    if redirect_uri not in client.redirect_uris:
        return _answer(
            oauth.OAuthError("invalid_request", "The redirect address is not one it registered.")
        )

    # Any other fault is answered here too, not at the client's address: anyone may
    # register one, and this server's address must not be a link to it (RFC 9700 4.11.2).
    if response_type != "code":
        return _answer(
            oauth.OAuthError("unsupported_response_type", "Only the code flow is offered.")
        )
    if code_challenge_method != "S256" or not 43 <= len(code_challenge) <= 128:
        return _answer(oauth.OAuthError("invalid_request", "PKCE with S256 is required."))
    if resource.rstrip("/") != f"{base}/mcp":
        return _answer(oauth.OAuthError("invalid_target", f"The resource is {base}/mcp."))
    sealed = oauth.seal_request(
        request.app.state.settings,
        oauth.Request(str(client.id), redirect_uri, code_challenge, state),
        utcnow(),
    )
    return RedirectResponse(f"{base}/connect?request={sealed}", status_code=302)


# --- Tokens ---------------------------------------------------------------------------


@endpoints.post("/token")
async def token(
    grant_type: Annotated[str, Form()] = "",
    client_id: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    redirect_uri: Annotated[str, Form()] = "",
    code_verifier: Annotated[str, Form()] = "",
    refresh_token: Annotated[str, Form()] = "",
    resource: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Tokens for a code, or for a refresh token (RFC 6749 4.1.3, 6)."""
    now = utcnow()
    try:
        base = await issuer(db)
        if resource and resource.rstrip("/") != f"{base}/mcp":
            raise oauth.OAuthError("invalid_target", f"The resource is {base}/mcp.")
        if grant_type == "authorization_code":
            issued = await oauth.exchange_code(
                db, client_id, code, redirect_uri, code_verifier, now
            )
        elif grant_type == "refresh_token":
            issued = await oauth.refresh(db, client_id, refresh_token, now)
        else:
            raise oauth.OAuthError("unsupported_grant_type", "A code or a refresh token.")
    except oauth.OAuthError as error:
        await db.commit()  # an approval revoked for a code or a token used twice
        return _answer(error)
    await db.commit()
    return JSONResponse(
        {
            "access_token": issued.access_token,
            "token_type": "Bearer",
            "expires_in": issued.expires_in,
            "refresh_token": issued.refresh_token,
        },
        headers=_NO_STORE,
    )


# --- The consent page's calls ---------------------------------------------------------


class Asked(BaseModel):
    client: str  # the client's name, in its own words
    redirect_host: str  # where the browser is sent back to


class Answer(BaseModel):
    request: str = Field(max_length=4096)


class Consent(Answer):
    access: Literal["read", "all"]
    lasts: Literal["1d", "30d", "90d", "forever"]


class Redirect(BaseModel):
    redirect: str  # where the browser goes next: back to the client


async def _asked(request: Request, db: AsyncSession, sealed: str) -> oauth.Request:
    found = oauth.open_request(request.app.state.settings, sealed, utcnow())
    if found is None or await oauth.get_client(db, found.client_id) is None:
        raise ApiError(
            410, "request_expired", "This request has expired. Start again from the application."
        )
    return found


@consent.get("/consent", response_model=Asked)
async def asked(
    request: Request,
    sealed: Annotated[str, Query(alias="request", max_length=4096)],
    _: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> Asked:
    """What a client asks of the signed-in person, for the consent page to show."""
    found = await _asked(request, db, sealed)
    client = await oauth.get_client(db, found.client_id)
    assert client is not None
    host = urlsplit(found.redirect_uri).hostname or ""
    return Asked(client=client.name, redirect_host=host)


@consent.post("/consent", response_model=Redirect)
async def approve(
    body: Consent,
    request: Request,
    principal: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> Redirect:
    """The person approves: a code for the client, back at its redirect address."""
    found = await _asked(request, db, body.request)
    address = await oauth.approve(db, principal.user, found, body.access, body.lasts, utcnow())
    await db.commit()
    log.info("oauth_approved", client=found.client_id, by=principal.user.username)
    return Redirect(redirect=address)


@consent.post("/refusal", response_model=Redirect)
async def refuse(
    body: Answer,
    request: Request,
    _: Principal = Depends(require_interactive()),
    db: AsyncSession = Depends(get_session),
) -> Redirect:
    """The person refuses: the client is told so (`access_denied`)."""
    return Redirect(redirect=oauth.refuse(await _asked(request, db, body.request)))
