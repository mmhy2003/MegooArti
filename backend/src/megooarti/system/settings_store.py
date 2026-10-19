"""Instance settings that administrators change at runtime."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.system.models import SystemSetting

DEFAULTS: dict[str, Any] = {
    "base_url": None,
    "anonymous_access": {"enabled": False},
    # The role every signed-in user has besides their own, by its name (spec 4.1).
    "default_role": None,
    # Whether MegooArti's own users sign in: off, only the built-in `admin` does (E1).
    "local_sign_in": {"enabled": True},
}


async def get_setting(db: AsyncSession, key: str) -> Any:
    default = DEFAULTS[key]
    row = await db.get(SystemSetting, key)
    return default if row is None else row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Store a value. None removes the stored value, so the default applies again."""
    if key not in DEFAULTS:  # a programming error, not bad input
        raise KeyError(key)
    row = await db.get(SystemSetting, key)
    if value is None:
        if row is not None:
            await db.delete(row)
    elif row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value
    await db.flush()
