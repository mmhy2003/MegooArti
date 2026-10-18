"""Administering accounts (spec 6.2): users, their API tokens, and roles. Each calls the
REST route beside it, with its permission, and names a user by their user name, a token
by its name and a role by its name (E2). No tool makes a token or sets a password but
one its user must change at their first sign-in (D4 of the identity-access spec)."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.errors import ApiError
from megooarti.mcp.results import Cursor, Limit, Page, offset_of, page_of
from megooarti.mcp.tools import CHANGE, DESTRUCTIVE, READ, WRITE, caller, database, holding, tool
from megooarti.pagination import PageParams
from megooarti.security import tokens, users
from megooarti.security.api import roles as roles_api
from megooarti.security.api import users as users_api
from megooarti.security.api.roles import RoleContent, RoleCreate, RoleOut
from megooarti.security.api.schemas import TokenInfo
from megooarti.security.api.users import UserCreate, UserOut, UserUpdate

Username = Annotated[str, Field(max_length=64)]
RoleName = Annotated[str, Field(max_length=64)]


async def _user_id(db: AsyncSession, username: str) -> uuid.UUID:
    found = await users.get_user_by_username(db, username)
    if found is None:
        raise ApiError(404, "not_found", "No such user.")
    return found.id


def _user(view: object) -> UserOut:
    return UserOut.model_validate(view, from_attributes=True)


def _role(view: object) -> RoleOut:
    return RoleOut.model_validate(view, from_attributes=True)


# --- Users ----------------------------------------------------------------------------


@tool(annotations=READ, shown_to=holding("admin:users:read"))
async def list_users(limit: Limit = 50, cursor: Cursor = None) -> Page[UserOut]:
    """The users, by user name: each one's name, email, status (active or disabled),
    roles, and when they last signed in."""
    offset = offset_of(cursor)
    async with database() as db:
        listed = await users_api.list_users(
            PageParams(limit=limit, offset=offset), caller().principal, db
        )
    items = [_user(one) for one in listed["items"]]
    return page_of(items, listed["total"], offset, limit)


class UserDetails(BaseModel):
    user: UserOut
    # Their API tokens: names, first characters, scopes, expiry, last use; never a value.
    # Null to those who may not read tokens.
    tokens: list[TokenInfo] | None


@tool(annotations=READ, shown_to=holding("admin:users:read"))
async def user_details(username: Username) -> UserDetails:
    """One user: their account and roles, and, to those who may read tokens, their API
    tokens (never a token's value)."""
    principal = caller().principal
    async with database() as db:
        user_id = await _user_id(db, username)
        view = await users_api.get_user(user_id, principal, db)
        held = None
        if principal.allows("admin:tokens:read"):
            listed = await users_api.list_user_tokens(
                user_id, PageParams(limit=200, offset=0), principal, db
            )
            held = [TokenInfo.model_validate(one, from_attributes=True) for one in listed["items"]]
    return UserDetails(user=_user(view), tokens=held)


@tool(annotations=WRITE, shown_to=holding("admin:users:write"))
async def create_user(
    username: Annotated[str, Field(pattern=r"^[A-Za-z0-9._@-]{1,64}$")],
    display_name: Annotated[str, Field(min_length=1, max_length=128)],
    password: Annotated[str, Field(max_length=1024)],
    email: Annotated[str | None, Field(max_length=254)] = None,
    roles: list[str] | None = None,
) -> UserOut:
    """Make a user with these roles. The password is one they must change when they first
    sign in: give it to them by a way of your own."""
    body = UserCreate(
        username=username,
        display_name=display_name,
        email=email,
        password=password,
        roles=roles or [],
        must_change_password=True,
    )
    async with database() as db:
        return _user(await users_api.create_user(body, caller().principal, db))


@tool(annotations=CHANGE, shown_to=holding("admin:users:write"))
async def update_user(
    username: Username,
    display_name: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
    email: Annotated[str | None, Field(max_length=254)] = None,
    status: Literal["active", "disabled"] | None = None,
    roles: list[str] | None = None,
) -> UserOut:
    """Change a user: their name, email, status (`disabled` stops them signing in, and
    their tokens working), or roles (all of them: what they hold is replaced). What is
    not given stays as it is. You cannot disable yourself."""
    given = {
        "display_name": display_name,
        "email": email,
        "status": status,
        "roles": roles,
    }
    body = UserUpdate(**{name: value for name, value in given.items() if value is not None})
    async with database() as db:
        user_id = await _user_id(db, username)
        return _user(await users_api.update_user(user_id, body, caller().principal, db))


class Gone(BaseModel):
    deleted: str  # what is gone: the user, the token or the role, by its name


@tool(annotations=DESTRUCTIVE, shown_to=holding("admin:users:write"))
async def delete_user(username: Username) -> Gone:
    """Delete a user, with their tokens. It cannot be undone; disabling them (with
    `update_user`) can be. You cannot delete yourself, nor the last administrator."""
    async with database() as db:
        user_id = await _user_id(db, username)
        await users_api.delete_user(user_id, caller().principal, db)
    return Gone(deleted=username)


@tool(annotations=DESTRUCTIVE, shown_to=holding("admin:tokens:write"))
async def revoke_token(username: Username, token: Annotated[str, Field(max_length=100)]) -> Gone:
    """Revoke a user's API token, by its name as `user_details` shows it: whatever signed in
    with it is refused from then on."""
    async with database() as db:
        user_id = await _user_id(db, username)
        listed, _ = await tokens.list_tokens(db, user_id, 200, 0)
        found = next((one for one in listed if one.name == token), None)
        if found is None:
            raise ApiError(404, "not_found", "No such token.")
        await users_api.revoke_user_token(user_id, found.id, caller().principal, db)
    return Gone(deleted=token)


# --- Roles ----------------------------------------------------------------------------


@tool(annotations=READ, shown_to=holding("admin:roles:read"))
async def list_roles(limit: Limit = 50, cursor: Cursor = None) -> Page[RoleOut]:
    """The roles: each one's permissions (patterns such as `repository:maven:releases:read`,
    `admin:users:write`, `*`) and the roles it holds."""
    offset = offset_of(cursor)
    async with database() as db:
        listed = await roles_api.list_roles(
            PageParams(limit=limit, offset=offset), caller().principal, db
        )
    items = [_role(one) for one in listed["items"]]
    return page_of(items, listed["total"], offset, limit)


@tool(annotations=WRITE, shown_to=holding("admin:roles:write"))
async def create_role(
    name: RoleName,
    description: Annotated[str, Field(max_length=255)] = "",
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
) -> RoleOut:
    """Make a role of permissions (`repository:<format>:<repository>:<action>`, where the
    action is browse, read, add, edit or delete; `admin:<area>:read` or `write`; `*` for
    any one part) and of other roles it holds."""
    body = RoleCreate(
        name=name, description=description, permissions=permissions or [], roles=roles or []
    )
    async with database() as db:
        return _role(await roles_api.create_role(body, caller().principal, db))


@tool(annotations=CHANGE, shown_to=holding("admin:roles:write"))
async def update_role(
    name: RoleName,
    description: Annotated[str | None, Field(max_length=255)] = None,
    permissions: list[str] | None = None,
    roles: list[str] | None = None,
) -> RoleOut:
    """Change a role: its description, its permissions (all of them: they are replaced) or
    the roles it holds. What is not given stays as it is. A change that would leave no
    administrator is refused."""
    principal = caller().principal
    async with database() as db:
        current = _role(await roles_api.get_role(name, principal, db))
        body = RoleContent(
            description=current.description if description is None else description,
            permissions=current.permissions if permissions is None else permissions,
            roles=current.roles if roles is None else roles,
        )
        return _role(await roles_api.update_role(name, body, principal, db))


@tool(annotations=DESTRUCTIVE, shown_to=holding("admin:roles:write"))
async def delete_role(name: RoleName) -> Gone:
    """Delete a role; whoever held it no longer has what it gave. The built-in roles stay."""
    async with database() as db:
        await roles_api.delete_role(name, caller().principal, db)
    return Gone(deleted=name)
