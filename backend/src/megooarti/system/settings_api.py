"""Instance settings an administrator can change."""

from urllib.parse import urlsplit

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.proxies import networks
from megooarti.security import users
from megooarti.security.authentication import Principal, require
from megooarti.security.guards import ensure_administrator_remains
from megooarti.security.roles import get_role
from megooarti.system.settings_store import get_setting, set_setting

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class AnonymousAccess(BaseModel):
    enabled: bool


class SettingsOut(BaseModel):
    base_url: str | None
    anonymous_access: AnonymousAccess


class LocalSignIn(BaseModel):
    enabled: bool


class DefaultRole(BaseModel):
    default_role: str | None = Field(max_length=64)


class TrustedProxies(BaseModel):
    trusted_proxies: list[str] = Field(max_length=100)


class SignInSettings(BaseModel):
    """How people sign in, besides the sources (spec 4.1): the role every signed-in user
    has, whether MegooArti's own users sign in, and the proxies trusted to say who a
    request comes from (spec 8)."""

    default_role: str | None
    local_sign_in: LocalSignIn
    trusted_proxies: list[str]


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


async def _sign_in(db: AsyncSession) -> SignInSettings:
    return SignInSettings(
        default_role=await get_setting(db, "default_role"),
        local_sign_in=LocalSignIn(**await get_setting(db, "local_sign_in")),
        trusted_proxies=await get_setting(db, "trusted_proxies"),
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


@router.get("/sign-in", response_model=SignInSettings)
async def read_sign_in_settings(
    _: Principal = Depends(require("admin:security:read")),
    db: AsyncSession = Depends(get_session),
) -> SignInSettings:
    return await _sign_in(db)


@router.put("/default-role", response_model=SignInSettings)
async def set_default_role(
    body: DefaultRole,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SignInSettings:
    """The role every signed-in user has, besides their own; null for none."""
    if body.default_role is not None and await get_role(db, body.default_role) is None:
        details = [{"field": "default_role", "message": f"Unknown role: {body.default_role}"}]
        raise ApiError(422, "validation_error", "The request is not valid.", details)
    await set_setting(db, "default_role", body.default_role)
    result = await _sign_in(db)
    await db.commit()
    log.info(
        "setting_changed",
        setting="default_role",
        role=body.default_role,
        by=principal.user.username,
    )
    return result


@router.put("/local-sign-in", response_model=SignInSettings)
async def set_local_sign_in(
    body: LocalSignIn,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SignInSettings:
    """Whether MegooArti's own users sign in. Off, the built-in `admin` still does (E1),
    and must then hold full access: else nobody who signs in would."""
    await set_setting(db, "local_sign_in", {"enabled": body.enabled})
    await ensure_administrator_remains(db)
    if not body.enabled:
        await users.sign_out_our_own(db)  # signed out for good, as a disabled user is
    result = await _sign_in(db)
    await db.commit()
    log.info(
        "setting_changed", setting="local_sign_in", enabled=body.enabled, by=principal.user.username
    )
    return result


@router.put("/trusted-proxies", response_model=SignInSettings)
async def set_trusted_proxies(
    body: TrustedProxies,
    request: Request,
    principal: Principal = Depends(require("admin:security:write")),
    db: AsyncSession = Depends(get_session),
) -> SignInSettings:
    """The proxies in front of the gateway, by address or network (CIDR): their
    X-Forwarded-For is believed, and a header source's header is taken from them only."""
    kept: list[str] = []
    for index, entry in enumerate(body.trusted_proxies):
        try:
            network = str(networks([entry], strict=True)[0])
        except ValueError:
            details = [
                {
                    "field": f"trusted_proxies.{index}",
                    "message": "An address, or a network as 10.0.0.0/8 (no bits past its prefix).",
                }
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details) from None
        if network not in kept:
            kept.append(network)
    await set_setting(db, "trusted_proxies", kept or None)
    result = await _sign_in(db)
    await db.commit()
    request.app.state.trusted_proxies = networks(kept)  # at once, for the next request
    log.info("setting_changed", setting="trusted_proxies", proxies=kept, by=principal.user.username)
    return result
