"""Tables for users, roles, sessions, API tokens and failed sign-ins.

There are no ORM relationships. Services query the link tables explicitly, so every
database round trip is visible in async code and nothing is loaded lazily.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class User(Base):
    __tablename__ = "users"
    # One user for each identity a source has: a name taken by two is two users (E2).
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(254))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")
    must_change_password: Mapped[bool] = mapped_column(default=False)
    builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Where the user signs in: None for MegooArti's own users, else a sign-in source, and
    # who they are there (an OIDC subject, an LDAP DN, a header's name). E2.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("auth_sources.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(512))


class AuthSource(Base):
    """Somewhere people sign in from besides MegooArti's own users: a directory (LDAP),
    an identity provider (OIDC), or a reverse proxy that says who they are (spec 4.1)."""

    __tablename__ = "auth_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    # Where it is asked, after MegooArti's own users: the lowest first.
    position: Mapped[int]
    # What its kind needs to reach it; its secrets sealed (E5).
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # [{"group": ..., "roles": [...]}]: the roles a member of a group is given (E4).
    group_mapping: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    builtin: Mapped[bool] = mapped_column(default=False)


class ContentSelector(Base):
    """Which content of repositories a selector permission reaches, by an expression of
    their format and their paths (spec 10): `selector:<name>:<format>:<repository>:<action>`."""

    __tablename__ = "content_selectors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    expression: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    pattern: Mapped[str] = mapped_column(String(255), primary_key=True)


class RoleMember(Base):
    """`role_id` contains `member_role_id`."""

    __tablename__ = "role_members"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    member_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    # Who gave it: an administrator ("admin"), or a source's group mapping ("source"),
    # which takes back at the next sign-in what the groups no longer give (E4).
    granted_by: Mapped[str] = mapped_column(String(8), default="admin", server_default="admin")


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str] = mapped_column(String(45))
    user_agent: Mapped[str] = mapped_column(String(255))


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    display_prefix: Mapped[str] = mapped_column(String(8))
    scopes: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthClient(Base):
    """A client that registered itself for OAuth (RFC 7591): an agent's host."""

    __tablename__ = "oauth_clients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list[Any]] = mapped_column(JSONB)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    registered_from: Mapped[str] = mapped_column(String(64))


class OAuthGrant(Base):
    """An approval: what a user let a client do as them, and until when."""

    __tablename__ = "oauth_grants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    # Patterns that narrow the user's permissions, as an API token's scopes do; null: none.
    scopes: Mapped[list[Any] | None] = mapped_column(JSONB(none_as_null=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthToken(Base):
    """A code, an access token or a refresh token of a grant, kept as its hash."""

    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    grant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("oauth_grants.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # "code", "access" or "refresh"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A code's: what the token request must show again (RFC 7636, RFC 6749 4.1.3).
    code_challenge: Mapped[str | None] = mapped_column(String(128))
    redirect_uri: Mapped[str | None] = mapped_column(String(2048))


class LoginFailure(Base):
    __tablename__ = "login_failures"

    subject: Mapped[str] = mapped_column(String(128), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column()
