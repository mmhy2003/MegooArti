"""Users: creation, changes, passwords and their effective permissions."""

import asyncio
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.security.keys import TOKEN_PREFIX
from megooarti.security.models import AuthSource, Role, User, UserRole, UserSession
from megooarti.security.passwords import hash_password, password_problem
from megooarti.security.roles import effective_patterns, get_role, roles_named
from megooarti.security.sessions import delete_user_sessions
from megooarti.system.settings_store import get_setting

# The name Python's packaging tools send with an API token (`__token__` and the token
# as HTTP Basic credentials). It stands for whoever owns the token, so nobody has it.
TOKEN_USERNAME = "__token__"


@dataclass(frozen=True)
class UserView:
    id: uuid.UUID
    username: str
    display_name: str
    email: str | None
    status: str
    must_change_password: bool
    builtin: bool
    roles: list[str]
    created_at: datetime
    last_login_at: datetime | None
    # The source they sign in through, by its name: None for MegooArti's own users, and
    # for the users of a source that was deleted, who keep their `external_id`.
    source: str | None
    external_id: str | None


def normalise_username(username: str) -> str:
    return username.strip().lower()


def looks_like_token(username: str) -> bool:
    """Whether what was given as a user name is shaped like an API token.

    A token sometimes arrives where the name belongs (`https://<token>@host/`). No
    user can have such a name, so it is never taken for one, logged or remembered.
    """
    return normalise_username(username).startswith(TOKEN_PREFIX)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return await db.scalar(select(User).where(User.username == normalise_username(username)))


async def user_patterns(db: AsyncSession, user: User) -> frozenset[str]:
    role_ids = await db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id))
    return await effective_patterns(db, list(role_ids))


async def signed_in_patterns(db: AsyncSession, user: User) -> frozenset[str]:
    """What a signed-in user may do: what their roles give, and what the default role
    gives, which every signed-in user has without its being kept on any (spec 4.1)."""
    role_ids = list(await db.scalars(select(UserRole.role_id).where(UserRole.user_id == user.id)))
    default = await get_setting(db, "default_role")
    role = None if default is None else await get_role(db, default)
    if role is not None:
        role_ids.append(role.id)
    return await effective_patterns(db, role_ids)


def is_builtin_admin(user: User) -> bool:
    """The built-in administrator, who signs in with a password of MegooArti's own
    whatever sources are on or off (E1)."""
    return user.builtin and user.username == "admin"


def is_external(user: User) -> bool:
    """A user of a sign-in source, or of one that was deleted: their password is not ours."""
    return user.source_id is not None or user.external_id is not None


async def sign_out_our_own(db: AsyncSession) -> None:
    """End the sessions of MegooArti's own users but the built-in `admin` (E1)."""
    ours = select(User.id).where(
        User.source_id.is_(None),
        User.external_id.is_(None),
        ~(User.builtin.is_(True) & (User.username == "admin")),
    )
    await db.execute(delete(UserSession).where(UserSession.user_id.in_(ours)))


async def can_act(db: AsyncSession, user: User) -> bool:
    """Whether a user may be anybody now: active, and signing in where sign-in is on. A
    user of a source that is off, or one of ours while our own sign-in is off, is refused
    as a disabled user is (spec 4.1, 4.2)."""
    if user.status != "active":
        return False
    if user.source_id is not None:
        source = await db.get(AuthSource, user.source_id)
        return source is not None and source.enabled
    if user.external_id is not None:
        return False  # their source was deleted
    return is_builtin_admin(user) or (await get_setting(db, "local_sign_in"))["enabled"]


async def describe(db: AsyncSession, user: User) -> UserView:
    names = await db.scalars(
        select(Role.name)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
        .order_by(Role.name)
    )
    source = None if user.source_id is None else await db.get(AuthSource, user.source_id)
    return UserView(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        status=user.status,
        must_change_password=user.must_change_password,
        builtin=user.builtin,
        roles=list(names),
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        source=None if source is None else source.name,
        external_id=user.external_id,
    )


async def list_users(db: AsyncSession, limit: int, offset: int) -> tuple[list[UserView], int]:
    total = await db.scalar(select(func.count()).select_from(User))
    page = list(await db.scalars(select(User).order_by(User.username).limit(limit).offset(offset)))
    return [await describe(db, user) for user in page], total or 0


def _check_password(password: str, username: str) -> None:
    problem = password_problem(password, username)
    if problem:
        details = [{"field": "password", "message": problem}]
        raise ApiError(422, "validation_error", "The request is not valid.", details)


async def set_roles(db: AsyncSession, user: User, role_names: Iterable[str]) -> None:
    """Give the user these roles, as an administrator does. One a source's group mapping
    gave stays the source's, to be taken back when the groups no longer give it (E4)."""
    chosen = await roles_named(db, role_names)
    from_source = set(
        await db.scalars(
            select(UserRole.role_id).where(
                UserRole.user_id == user.id, UserRole.granted_by == "source"
            )
        )
    )
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    if chosen:
        await db.execute(
            insert(UserRole),
            [
                {
                    "user_id": user.id,
                    "role_id": role.id,
                    "granted_by": "source" if role.id in from_source else "admin",
                }
                for role in chosen
            ],
        )


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    display_name: str,
    email: str | None,
    password: str,
    role_names: Iterable[str],
    must_change_password: bool,
) -> User:
    username = normalise_username(username)
    if username == TOKEN_USERNAME or looks_like_token(username):
        details = [
            {"field": "username", "message": "This name is reserved for signing in with a token."}
        ]
        raise ApiError(422, "validation_error", "The request is not valid.", details)
    if await get_user_by_username(db, username) is not None:
        raise ApiError(409, "conflict", f"A user named {username} already exists.")
    _check_password(password, username)
    user = User(
        username=username,
        display_name=display_name,
        email=email,
        password_hash=await asyncio.to_thread(hash_password, password),
        status="active",
        must_change_password=must_change_password,
        builtin=False,
    )
    db.add(user)
    await db.flush()
    await set_roles(db, user, role_names)
    return user


async def update_user(db: AsyncSession, user: User, changes: dict[str, Any]) -> None:
    """Apply any of display_name, email, status and roles."""
    for field in ("display_name", "email", "status"):
        if field in changes:
            setattr(user, field, changes[field])
    await db.flush()
    if "roles" in changes:
        await set_roles(db, user, changes["roles"])
    if user.status != "active":
        await delete_user_sessions(db, user.id)


async def set_password(
    db: AsyncSession,
    user: User,
    password: str,
    *,
    must_change_password: bool,
    keep_session_id: uuid.UUID | None = None,
) -> None:
    if user.builtin and user.username == "anonymous":
        raise ApiError(409, "builtin_protected", "The anonymous user cannot have a password.")
    if is_external(user):
        raise ApiError(
            409, "external_user", f"{user.username} signs in through a source, with its password."
        )
    _check_password(password, user.username)
    user.password_hash = await asyncio.to_thread(hash_password, password)
    user.must_change_password = must_change_password
    await db.flush()
    await delete_user_sessions(db, user.id, keep_session_id)


async def delete_user(db: AsyncSession, user: User) -> None:
    if user.builtin:
        raise ApiError(409, "builtin_protected", "Built-in users cannot be deleted.")
    await db.delete(user)
    await db.flush()
