"""Personal API tokens."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.keys import TOKEN_PREFIX, hash_secret, new_api_token
from megooarti.security.models import ApiToken

_TOUCH_INTERVAL = timedelta(seconds=60)


async def create_token(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    name: str,
    expires_at: datetime | None,
    scopes: list[str] | None,
) -> tuple[ApiToken, str]:
    """Create a token. Returns the record and the secret value, which is not stored."""
    duplicate = await db.scalar(
        select(ApiToken.id).where(ApiToken.user_id == user_id, ApiToken.name == name)
    )
    if duplicate is not None:
        raise ApiError(409, "conflict", f"A token named {name} already exists.")
    value = new_api_token()
    token = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=hash_secret(value),
        display_prefix=value[:8],
        scopes=scopes,
        expires_at=expires_at,
    )
    db.add(token)
    await db.flush()
    return token, value


async def find_token(db: AsyncSession, value: str, now: datetime) -> ApiToken | None:
    if not value.startswith(TOKEN_PREFIX):
        return None
    token = await db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_secret(value)))
    if token is None:
        return None
    if token.expires_at is not None and token.expires_at <= now:
        return None
    return token


async def get_token(db: AsyncSession, token_id: uuid.UUID, now: datetime) -> ApiToken | None:
    """A token by its ID, if it still exists and has not expired."""
    token = await db.get(ApiToken, token_id)
    if token is None or (token.expires_at is not None and token.expires_at <= now):
        return None
    return token


def touch(token: ApiToken, now: datetime) -> None:
    """Note use, writing at most once a minute per token."""
    if token.last_used_at is None or now - token.last_used_at >= _TOUCH_INTERVAL:
        token.last_used_at = now


async def list_tokens(
    db: AsyncSession, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[ApiToken], int]:
    owned = ApiToken.user_id == user_id
    total = await db.scalar(select(func.count()).select_from(ApiToken).where(owned))
    rows = await db.scalars(
        select(ApiToken)
        .where(owned)
        .order_by(ApiToken.created_at.desc(), ApiToken.name)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def revoke_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    token = await db.scalar(
        select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
    )
    if token is None:
        raise ApiError(404, "not_found", "No such token.")
    await db.delete(token)
    await db.flush()
