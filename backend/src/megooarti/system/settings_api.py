"""Instance settings an administrator can change."""

from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.security.authentication import Principal, require
from megooarti.system.settings_store import get_setting, set_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class AnonymousAccess(BaseModel):
    enabled: bool


class SettingsOut(BaseModel):
    base_url: str | None
    anonymous_access: AnonymousAccess


class BaseUrl(BaseModel):
    base_url: str | None

    @field_validator("base_url")
    @classmethod
    def _http_url_without_trailing_slash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("must be an http or https URL")
        if "@" in parts.netloc:
            # Every address the server gives out is built from it, and would carry them.
            raise ValueError("must not contain a user name or a password")
        if parts.query or parts.fragment:
            raise ValueError("must not contain a query or a fragment")
        return value.rstrip("/")


async def _current(db: AsyncSession) -> SettingsOut:
    return SettingsOut(
        base_url=await get_setting(db, "base_url"),
        anonymous_access=AnonymousAccess(**await get_setting(db, "anonymous_access")),
    )


@router.get("", response_model=SettingsOut)
async def read_settings(
    _: Principal = Depends(require("admin:settings:read")),
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    return await _current(db)


@router.put("/base-url", response_model=SettingsOut)
async def set_base_url(
    body: BaseUrl,
    principal: Principal = Depends(require("admin:settings:write")),
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    await set_setting(db, "base_url", body.base_url)
    result = await _current(db)
    await db.commit()
    log.info("setting_changed", setting="base_url", by=principal.user.username)
    return result


@router.put("/anonymous-access", response_model=SettingsOut)
async def set_anonymous_access(
    body: AnonymousAccess,
    principal: Principal = Depends(require("admin:settings:write")),
    db: AsyncSession = Depends(get_session),
) -> SettingsOut:
    await set_setting(db, "anonymous_access", {"enabled": body.enabled})
    result = await _current(db)
    await db.commit()
    log.info(
        "setting_changed",
        setting="anonymous_access",
        enabled=body.enabled,
        by=principal.user.username,
    )
    return result
