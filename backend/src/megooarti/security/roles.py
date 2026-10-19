"""Roles: named sets of permission patterns, which may contain other roles."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.models import Role, RoleMember, RolePermission
from megooarti.system.settings_store import get_setting, set_setting


@dataclass(frozen=True)
class RoleView:
    name: str
    description: str
    builtin: bool
    permissions: list[str]
    roles: list[str]


async def get_role(db: AsyncSession, name: str) -> Role | None:
    return await db.scalar(select(Role).where(Role.name == name))


async def roles_named(db: AsyncSession, names: Iterable[str]) -> list[Role]:
    """The roles with these names. An unknown name is a validation error."""
    wanted = sorted(set(names))
    if not wanted:
        return []
    found = list(await db.scalars(select(Role).where(Role.name.in_(wanted))))
    missing = sorted(set(wanted) - {role.name for role in found})
    if missing:
        details = [{"field": "roles", "message": f"Unknown role: {name}"} for name in missing]
        raise ApiError(422, "validation_error", "The request is not valid.", details)
    return found


async def reachable_role_ids(db: AsyncSession, role_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """The given roles plus every role they contain, directly or indirectly."""
    start = list(role_ids)
    if not start:
        return set()
    reachable = select(Role.id).where(Role.id.in_(start)).cte("reachable", recursive=True)
    # UNION (not UNION ALL) removes duplicates, which also stops at a cycle.
    reachable = reachable.union(
        select(RoleMember.member_role_id).join(reachable, RoleMember.role_id == reachable.c.id)
    )
    return set(await db.scalars(select(reachable.c.id)))


async def effective_patterns(db: AsyncSession, role_ids: Iterable[uuid.UUID]) -> frozenset[str]:
    ids = await reachable_role_ids(db, role_ids)
    if not ids:
        return frozenset()
    patterns = await db.scalars(
        select(RolePermission.pattern).where(RolePermission.role_id.in_(ids))
    )
    return frozenset(patterns)


async def describe(db: AsyncSession, role: Role) -> RoleView:
    permissions = await db.scalars(
        select(RolePermission.pattern)
        .where(RolePermission.role_id == role.id)
        .order_by(RolePermission.pattern)
    )
    members = await db.scalars(
        select(Role.name)
        .join(RoleMember, RoleMember.member_role_id == Role.id)
        .where(RoleMember.role_id == role.id)
        .order_by(Role.name)
    )
    return RoleView(role.name, role.description, role.builtin, list(permissions), list(members))


async def list_roles(db: AsyncSession, limit: int, offset: int) -> tuple[list[RoleView], int]:
    total = await db.scalar(select(func.count()).select_from(Role))
    page = list(await db.scalars(select(Role).order_by(Role.name).limit(limit).offset(offset)))
    return [await describe(db, role) for role in page], total or 0


async def _replace_content(
    db: AsyncSession, role: Role, permissions: Iterable[str], member_names: Iterable[str]
) -> None:
    members = await roles_named(db, member_names)
    member_ids = {member.id for member in members}
    if role.id in await reachable_role_ids(db, member_ids):
        raise ApiError(409, "role_cycle", "A role cannot contain itself, directly or indirectly.")
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    await db.execute(delete(RoleMember).where(RoleMember.role_id == role.id))
    patterns = sorted(set(permissions))
    if patterns:
        await db.execute(
            insert(RolePermission),
            [{"role_id": role.id, "pattern": pattern} for pattern in patterns],
        )
    if member_ids:
        await db.execute(
            insert(RoleMember),
            [{"role_id": role.id, "member_role_id": member_id} for member_id in member_ids],
        )


async def create_role(
    db: AsyncSession,
    name: str,
    description: str,
    permissions: Iterable[str],
    member_names: Iterable[str],
) -> Role:
    if await get_role(db, name) is not None:
        raise ApiError(409, "conflict", f"A role named {name} already exists.")
    role = Role(name=name, description=description, builtin=False)
    db.add(role)
    await db.flush()
    await _replace_content(db, role, permissions, member_names)
    return role


async def update_role(
    db: AsyncSession,
    role: Role,
    description: str,
    permissions: Iterable[str],
    member_names: Iterable[str],
) -> None:
    if role.builtin and role.name == "admin":
        raise ApiError(409, "builtin_protected", "The admin role cannot be changed.")
    role.description = description
    await db.flush()
    await _replace_content(db, role, permissions, member_names)


async def delete_role(db: AsyncSession, role: Role) -> None:
    if role.builtin:
        raise ApiError(409, "builtin_protected", "Built-in roles cannot be deleted.")
    if await get_setting(db, "default_role") == role.name:
        await set_setting(db, "default_role", None)  # it gives nobody anything any more
    await db.delete(role)
    await db.flush()
