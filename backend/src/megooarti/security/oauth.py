"""OAuth 2.1 for AI agents' sign-in to /mcp (MCP spec 7): clients that register
themselves, a user's approval of one, and the codes and tokens that follow from it.

Every code and token is random, given once, and kept as its hash, as API tokens are.
An approval's request is sealed into the address of the consent page, not stored.
"""

import base64
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti import secrets_box
from megooarti.config import Settings
from megooarti.errors import ApiError
from megooarti.security.keys import hash_secret
from megooarti.security.models import OAuthClient, OAuthGrant, OAuthToken, User

ACCESS_PREFIX = "mgo_"
REFRESH_PREFIX = "mgf_"
CODE_PREFIX = "mgc_"
ACCESS_SECONDS = 3600
CODE_SECONDS = 60
# How long the consent page may take: a person reads it, perhaps signs in first.
REQUEST_SECONDS = 600
REGISTRATIONS_PER_HOUR = 20
# A client that no approval names is forgotten this long after it registered.
UNAPPROVED_DAYS = 30
# A refresh token of an approval that does not expire still has to have an end.
_FOREVER = timedelta(days=3650)
_REQUEST = "oauth-request"

# What the consent page offers (spec 7.3): what an agent may do, and for how long.
ACCESS = {
    "read": ["repository:*:*:browse", "repository:*:*:read", "admin:*:read"],
    "all": None,
}
LASTS = {
    "1d": timedelta(days=1),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "forever": None,
}
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}


class OAuthError(Exception):
    """An answer of OAuth's own shape (RFC 6749 5.2, RFC 7591 3.2.2)."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(description)
        self.error, self.description, self.status = error, description, status


def _new(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def acceptable_redirect(address: str) -> bool:
    """`https`, or `http` to this machine (a desktop client's own listener), without a
    fragment or credentials (RFC 6749 3.1.2, the MCP authorization spec)."""
    try:
        parts = urlsplit(address)
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and parts.hostname in _LOOPBACK


# --- Registration ---------------------------------------------------------------------


async def register(
    db: AsyncSession, name: str, redirect_uris: list[str], address: str, now: datetime
) -> OAuthClient:
    """A client, registered by itself (RFC 7591), from `address`."""
    lately = await db.scalar(
        select(func.count())
        .select_from(OAuthClient)
        .where(
            OAuthClient.registered_from == address,
            OAuthClient.registered_at > now - timedelta(hours=1),
        )
    )
    if (lately or 0) >= REGISTRATIONS_PER_HOUR:
        raise OAuthError(
            "too_many_registrations", "Too many clients registered from here; try later.", 429
        )
    if not redirect_uris or len(redirect_uris) > 10:
        raise OAuthError("invalid_redirect_uri", "Give one to ten redirect addresses.")
    for uri in redirect_uris:
        if len(uri) > 2048 or not acceptable_redirect(uri):
            raise OAuthError(
                "invalid_redirect_uri",
                "A redirect address is https, or http to this machine, with no fragment.",
            )
    client = OAuthClient(
        name=(name.strip() or "An application")[:200],
        redirect_uris=redirect_uris,
        registered_at=now,
        registered_from=address[:64],
    )
    db.add(client)
    await db.flush()
    return client


async def get_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    try:
        return await db.get(OAuthClient, uuid.UUID(client_id))
    except ValueError:
        return None


# --- Authorization --------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """What a client asked to be authorized for, carried through the consent page."""

    client_id: str
    redirect_uri: str
    code_challenge: str
    state: str | None


def seal_request(settings: Settings, request: Request, now: datetime) -> str:
    stated = {"for": _REQUEST, **vars(request)}
    return secrets_box.seal_at(settings, json.dumps(stated), now)


def open_request(settings: Settings, sealed: str, now: datetime) -> Request | None:
    """The request a consent page was given, if it is one and not too old."""
    text = secrets_box.unseal_within(settings, sealed, REQUEST_SECONDS, now)
    if text is None:
        return None
    try:
        stated = json.loads(text)
        if stated.pop("for") != _REQUEST:
            return None
        return Request(**stated)
    except (ValueError, KeyError, TypeError):
        return None


def redirect_with(address: str, **values: str | None) -> str:
    """The client's redirect address with these in its query, beside its own."""
    parts = urlsplit(address)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query += [(name, value) for name, value in values.items() if value is not None]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def approve(
    db: AsyncSession, user: User, request: Request, access: str, lasts: str, now: datetime
) -> str:
    """An approval of the request, and where the browser goes with its code."""
    lifetime = LASTS[lasts]
    grant = OAuthGrant(
        user_id=user.id,
        client_id=uuid.UUID(request.client_id),
        scopes=ACCESS[access],
        expires_at=None if lifetime is None else now + lifetime,
        created_at=now,
    )
    db.add(grant)
    await db.flush()
    code = _new(CODE_PREFIX)
    db.add(
        OAuthToken(
            grant_id=grant.id,
            kind="code",
            token_hash=hash_secret(code),
            expires_at=now + timedelta(seconds=CODE_SECONDS),
            code_challenge=request.code_challenge,
            redirect_uri=request.redirect_uri,
        )
    )
    await db.flush()
    return redirect_with(request.redirect_uri, code=code, state=request.state)


def refuse(request: Request) -> str:
    return redirect_with(request.redirect_uri, error="access_denied", state=request.state)


# --- Tokens ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issued:
    access_token: str
    refresh_token: str
    expires_in: int


async def _issue(db: AsyncSession, grant: OAuthGrant, now: datetime) -> Issued:
    access, refresh = _new(ACCESS_PREFIX), _new(REFRESH_PREFIX)
    ends = grant.expires_at or now + _FOREVER
    access_ends = min(now + timedelta(seconds=ACCESS_SECONDS), ends)
    db.add(
        OAuthToken(
            grant_id=grant.id,
            kind="access",
            token_hash=hash_secret(access),
            expires_at=access_ends,
        )
    )
    db.add(
        OAuthToken(
            grant_id=grant.id, kind="refresh", token_hash=hash_secret(refresh), expires_at=ends
        )
    )
    await db.flush()
    return Issued(access, refresh, max(int((access_ends - now).total_seconds()), 0))


async def _held(db: AsyncSession, kind: str, value: str) -> tuple[OAuthToken, OAuthGrant] | None:
    found = await db.scalar(
        select(OAuthToken).where(
            OAuthToken.kind == kind, OAuthToken.token_hash == hash_secret(value)
        )
    )
    if found is None:
        return None
    grant = await db.get(OAuthGrant, found.grant_id)
    return None if grant is None else (found, grant)


def _invalid(description: str) -> OAuthError:
    return OAuthError("invalid_grant", description)


def _challenge_of(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii", errors="replace")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def exchange_code(
    db: AsyncSession,
    client_id: str,
    code: str,
    redirect_uri: str,
    verifier: str,
    now: datetime,
) -> Issued:
    """Tokens for a code (RFC 6749 4.1.3, RFC 7636 4.6). A code used twice revokes the
    approval it was given for (RFC 6749 4.1.2)."""
    held = await _held(db, "code", code)
    if held is None:
        raise _invalid("No such code.")
    token, grant = held
    if token.used_at is not None:
        await db.delete(grant)
        raise _invalid("The code was used already; the approval is revoked.")
    if token.expires_at <= now:
        raise _invalid("The code has expired.")
    if str(grant.client_id) != client_id:
        raise _invalid("The code was given to another client.")
    if token.redirect_uri != redirect_uri:
        raise _invalid("The redirect address is not the one the code was given with.")
    if not secrets.compare_digest(_challenge_of(verifier), token.code_challenge or ""):
        raise _invalid("The code verifier is not the code challenge's.")
    token.used_at = now
    return await _issue(db, grant, now)


async def refresh(db: AsyncSession, client_id: str, value: str, now: datetime) -> Issued:
    """New tokens for a refresh token, which is used once: one used twice was stolen, and
    revokes the approval (OAuth 2.1 4.3.1)."""
    held = await _held(db, "refresh", value)
    if held is None:
        raise _invalid("No such refresh token.")
    token, grant = held
    if token.used_at is not None:
        await db.delete(grant)
        raise _invalid("The refresh token was used already; the approval is revoked.")
    if token.expires_at <= now or (grant.expires_at is not None and grant.expires_at <= now):
        raise _invalid("The approval has expired.")
    if str(grant.client_id) != client_id:
        raise _invalid("The refresh token was given to another client.")
    token.used_at = now
    return await _issue(db, grant, now)


async def find_access(db: AsyncSession, value: str, now: datetime) -> OAuthGrant | None:
    """The approval an access token stands for, while both last."""
    held = await _held(db, "access", value)
    if held is None:
        return None
    token, grant = held
    if token.expires_at <= now or (grant.expires_at is not None and grant.expires_at <= now):
        return None
    if grant.last_used_at is None or now - grant.last_used_at > timedelta(seconds=60):
        grant.last_used_at = now
    return grant


# --- Approvals ------------------------------------------------------------------------


@dataclass(frozen=True)
class Approval:
    id: uuid.UUID
    client: str  # its name, in its own words
    redirect_host: str
    scopes: list[str] | None
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None


async def approvals(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> list[Approval]:
    """A user's approvals that have not expired, the newest first."""
    rows = await db.execute(
        select(OAuthGrant, OAuthClient)
        .join(OAuthClient, OAuthClient.id == OAuthGrant.client_id)
        .where(OAuthGrant.user_id == user_id)
        .where((OAuthGrant.expires_at.is_(None)) | (OAuthGrant.expires_at > now))
        .order_by(OAuthGrant.created_at.desc())
    )
    return [
        Approval(
            id=grant.id,
            client=client.name,
            redirect_host=urlsplit(client.redirect_uris[0]).hostname or "",
            scopes=grant.scopes,
            created_at=grant.created_at,
            last_used_at=grant.last_used_at,
            expires_at=grant.expires_at,
        )
        for grant, client in rows
    ]


async def revoke(db: AsyncSession, user_id: uuid.UUID, grant_id: uuid.UUID) -> None:
    """Revoke one of a user's approvals, and its tokens with it. Raises 404."""
    grant = await db.scalar(
        select(OAuthGrant).where(OAuthGrant.id == grant_id, OAuthGrant.user_id == user_id)
    )
    if grant is None:
        raise ApiError(404, "not_found", "No such connected app.")
    await db.delete(grant)
    await db.flush()


async def forget(db: AsyncSession, now: datetime) -> None:
    """Remove what has expired, and clients no approval names a month after they came."""
    await db.execute(delete(OAuthToken).where(OAuthToken.expires_at <= now))
    await db.execute(
        delete(OAuthGrant).where(OAuthGrant.expires_at.is_not(None), OAuthGrant.expires_at <= now)
    )
    named = exists().where(OAuthGrant.client_id == OAuthClient.id)
    await db.execute(
        delete(OAuthClient).where(
            OAuthClient.registered_at <= now - timedelta(days=UNAPPROVED_DAYS), ~named
        )
    )


def describe(client: OAuthClient) -> dict[str, Any]:
    """A client as registration answers it (RFC 7591 3.2.1)."""
    return {
        "client_id": str(client.id),
        "client_name": client.name,
        "redirect_uris": client.redirect_uris,
        "client_id_issued_at": int(client.registered_at.timestamp()),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
