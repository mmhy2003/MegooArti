"""Request and response shapes shared by the security routers."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel

from megooarti.security.permissions import is_valid_pattern


def _valid_pattern(value: str) -> str:
    if len(value) > 255 or not is_valid_pattern(value):
        raise ValueError("is not a valid permission pattern")
    return value


Pattern = Annotated[str, AfterValidator(_valid_pattern)]


class ConnectedApp(BaseModel):
    """An approval a user gave an application signed in with OAuth (MCP spec 7.6)."""

    id: uuid.UUID
    client: str  # the application's name, in its own words
    redirect_host: str  # where it was sent back to
    scopes: list[str] | None  # what it may do, narrowing the user's permissions; null: all
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None  # null: until it is revoked


class TokenInfo(BaseModel):
    id: uuid.UUID
    name: str
    display_prefix: str
    scopes: list[str] | None
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


class TokenCreated(TokenInfo):
    token: str
