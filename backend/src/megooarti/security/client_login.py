"""Signing a package client in: credentials go in, a token to keep comes out.

Some clients have a sign-in command (`npm login`, later `docker login`) that sends a
user name and a secret and expects a token back. The secret is checked exactly as HTTP
Basic credentials are, so the same limits on failed attempts apply.
"""

import secrets

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.security import tokens
from megooarti.security.authentication import Principal, authenticate_secret
from megooarti.system import audit

log = structlog.get_logger(__name__)


async def issue_token(
    db: AsyncSession, request: Request, username: str, secret: str, *, label: str
) -> str:
    """A token for the user with this name and secret. Raises 401, 403 or 429.

    If the secret is already one of the user's API tokens, that token is the answer:
    the client keeps using it. Otherwise the secret is the password, and a new personal
    API token is created, named with `label` and the time. The caller commits.
    """
    user, token = await authenticate_secret(db, request, username, secret)
    if token is not None:
        return secret
    if user.must_change_password:
        # A token would let the account be used without ever changing the password.
        raise ApiError(
            403, "password_change_required", "Change your password before doing anything else."
        )
    name = f"{label} {utcnow():%Y-%m-%d %H:%M:%S} {secrets.token_hex(3)}"
    _, value = await tokens.create_token(db, user.id, name=name, expires_at=None, scopes=None)
    audit.acting(user.username, "password")
    audit.record(db, "token.created", ("token", f"{user.username}/{name}"))
    log.info("client_signed_in", username=user.username, token_name=name)
    return value


async def revoke_own_token(db: AsyncSession, principal: Principal, value: str) -> None:
    """Revoke the token with this value, if it is the caller's. Raises 404 otherwise."""
    token = await tokens.find_token(db, value, utcnow())
    if token is None or token.user_id != principal.user.id:
        raise ApiError(404, "not_found", "No such token.")
    await db.delete(token)
    await db.flush()
    audit.record(db, "token.revoked", ("token", f"{principal.user.username}/{token.name}"))
    log.info("client_signed_out", username=principal.user.username, token_name=token.name)
