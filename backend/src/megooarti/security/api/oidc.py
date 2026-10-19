"""Signing in at an OIDC provider (spec 5): the two addresses a browser goes through.

`start` sends the browser to the provider, keeping what this sign-in needs sealed in a
cookie of ten minutes; `callback` is where the provider sends it back, with a code, which
is traded for an ID token. Either ends at the sign-in screen: signed in, it goes on to
where the person was going; else it says why not, in words of its own.
"""

import json
import secrets
import uuid
from urllib.parse import quote, urlencode

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.clock import utcnow
from megooarti.db.session import get_session
from megooarti.secrets_box import seal_at, unseal_within
from megooarti.security import oidc, sources, users
from megooarti.security.api.auth import start_session
from megooarti.security.api.sources import redirect_uri
from megooarti.security.models import AuthSource
from megooarti.system.settings_store import get_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth/oidc", tags=["authentication"])

COOKIE = "megooarti_oidc"
COOKIE_PATH = "/api/v1/auth/oidc/"
LASTS_SECONDS = 600
SIGN_IN = "/login"


async def _sign_in_screen(db: AsyncSession, **query: str) -> RedirectResponse:
    """Back to the sign-in screen, which goes on to `next` once signed in (the UI checks
    that it is an address of its own), or says why the sign-in did not happen."""
    base = (await get_setting(db, "base_url") or "").rstrip("/")
    said = urlencode({name: value for name, value in query.items() if value}, quote_via=quote)
    return RedirectResponse(f"{base}{SIGN_IN}{'?' + said if said else ''}", status_code=302)


async def _source(db: AsyncSession, source_id: uuid.UUID) -> AuthSource | None:
    source = await sources.get_source(db, source_id)
    if source is None or source.kind != oidc.KIND or not source.enabled:
        return None
    return source


def _opened(request: Request, source: AuthSource) -> dict:
    return sources.opened_settings(
        request.app.state.settings, sources.KINDS[oidc.KIND], source.settings
    )


@router.get("/{source_id}/start", response_class=RedirectResponse, status_code=302)
async def start(
    source_id: uuid.UUID,
    request: Request,
    next: str = "",
    db: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Send the browser to the provider to sign in, with a state, a nonce and PKCE."""
    next = next[:2048]
    source = await _source(db, source_id)
    if source is None:
        return await _sign_in_screen(db, error="unavailable", next=next)
    settings = _opened(request, source)
    try:
        provider = await oidc.discover(sources.outbound(request.app), settings["issuer"])
    except sources.SourceUnavailable as error:
        log.warning("oidc_unavailable", source=source.name, error=str(error))
        return await _sign_in_screen(db, error="unavailable", next=next)
    started = oidc.Started.new()
    back = await redirect_uri(db, request, source)
    kept = {
        "source": str(source.id),
        "state": started.state,
        "nonce": started.nonce,
        "verifier": started.verifier,
        "next": next,
        "redirect_uri": back,
    }
    response = RedirectResponse(
        oidc.authorization_address(provider, settings, started, back), status_code=302
    )
    response.set_cookie(
        COOKIE,
        seal_at(request.app.state.settings, json.dumps(kept), utcnow()),
        max_age=LASTS_SECONDS,
        httponly=True,
        secure=request.app.state.settings.session_cookie_secure,
        samesite="lax",  # sent along when the provider sends the browser back
        path=COOKIE_PATH,
    )
    return response


@router.get("/{source_id}/callback", response_class=RedirectResponse, status_code=302)
async def callback(
    source_id: uuid.UUID,
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    iss: str = "",
    db: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Where the provider sends the browser back: the code traded, the ID token checked,
    the user made or brought up to date (spec 4.2), and a session started."""
    sealed = request.cookies.get(COOKIE, "")
    opened = (
        unseal_within(request.app.state.settings, sealed, LASTS_SECONDS, utcnow())
        if sealed
        else None
    )
    kept = json.loads(opened) if opened else None
    next = "" if kept is None else kept["next"]

    async def failed(why: str, said: str) -> RedirectResponse:
        log.warning("oidc_sign_in_failed", source_id=str(source_id), why=why, said=said[:300])
        await db.rollback()  # nothing is made of a sign-in that did not happen
        response = await _sign_in_screen(db, error=why, next=next)
        response.delete_cookie(COOKIE, path=COOKIE_PATH)
        return response

    if kept is None:
        return await failed("expired", "no sign-in was started here, or it took too long")
    if kept["source"] != str(source_id) or not secrets.compare_digest(kept["state"], state):
        return await failed("failed", "the state is not this browser's sign-in")
    source = await _source(db, source_id)
    if source is None:
        return await failed("unavailable", "the source is not there, or is off")
    if error:
        return await failed("denied", f"the provider answered {error}")
    settings = _opened(request, source)
    reach = sources.outbound(request.app)
    try:
        provider = await oidc.discover(reach, settings["issuer"])
        # RFC 9207: a provider that names itself must name this one.
        if iss and iss != provider.issuer:
            raise oidc.NotChecked(f"the answer came from {iss}")
        token = await oidc.exchange(
            reach, provider, settings, code, kept["verifier"], kept["redirect_uri"]
        )
        claims = await oidc.verify(reach, provider, settings, token, kept["nonce"])
        identity = oidc.identity(claims, settings)
    except sources.SourceUnavailable as problem:
        return await failed("unavailable", str(problem))
    except oidc.NotChecked as problem:
        return await failed("failed", str(problem))
    except oidc.Refused as problem:
        return await failed("refused", str(problem))
    user = await sources.provision(db, source, identity)
    if not await users.can_act(db, user):
        return await failed("refused", f"{user.username} may not sign in")
    response = await _sign_in_screen(db, next=next, signed_in="1")
    await start_session(db, request, response, user, source=source.name)
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    return response
