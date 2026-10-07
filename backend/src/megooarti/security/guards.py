"""Checks that protect the installation from locking itself out."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.models import RoleMember, RolePermission, User, UserRole
from megooarti.security.permissions import FULL_ACCESS


async def ensure_administrator_remains(db: AsyncSession) -> None:
    """Refuse the pending change if nobody who can sign in would have full access.

    Call after changing users or roles and before committing.
    """
    # Roles that grant full access: those holding "*" and every role that contains one.
    granting = (
        select(RolePermission.role_id.label("id"))
        .where(RolePermission.pattern == FULL_ACCESS)
        .cte("granting", recursive=True)
    )
    granting = granting.union(
        select(RoleMember.role_id).join(granting, RoleMember.member_role_id == granting.c.id)
    )
    administrator = await db.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.status == "active",
            User.password_hash.is_not(None),
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
