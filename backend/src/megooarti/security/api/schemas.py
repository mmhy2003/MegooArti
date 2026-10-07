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
