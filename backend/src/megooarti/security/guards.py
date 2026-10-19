"""Checks that protect the installation from locking itself out."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.models import RoleMember, RolePermission, User, UserRole
from megooarti.security.permissions import FULL_ACCESS
from megooarti.system.settings_store import get_setting

# Arbitrary constant, distinct from the migration lock key.
ADMINISTRATOR_LOCK_KEY = 0x4D45474F50


async def ensure_administrator_remains(db: AsyncSession) -> None:
    """Refuse the pending change if nobody who can sign in would have full access.

    Call after changing users or roles and before committing.
    """
    # One checked change at a time. Without this, two requests that each remove the other
    # administrator would both pass, because neither sees the other's uncommitted change.
    # The lock is released when the transaction ends.
    await db.execute(text(f"SELECT pg_advisory_xact_lock({ADMINISTRATOR_LOCK_KEY})"))

    # Roles that grant full access: those holding "*" and every role that contains one.
    granting = (
        select(RolePermission.role_id.label("id"))
        .where(RolePermission.pattern == FULL_ACCESS)
        .cte("granting", recursive=True)
    )
    granting = granting.union(
        select(RoleMember.role_id).join(granting, RoleMember.member_role_id == granting.c.id)
    )
    # Who signs in with a password of ours: while our own sign-in is off, `admin` alone (E1).
    signs_in = [User.password_hash.is_not(None), User.source_id.is_(None)]
    if not (await get_setting(db, "local_sign_in"))["enabled"]:
        signs_in += [User.builtin.is_(True), User.username == "admin"]
    administrator = await db.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.status == "active",
            *signs_in,
            UserRole.role_id.in_(select(granting.c.id)),
        )
        .limit(1)
    )
    if administrator is None:
        raise ApiError(
            409,
            "last_administrator",
            "This change would leave no active user with full access.",
        )
