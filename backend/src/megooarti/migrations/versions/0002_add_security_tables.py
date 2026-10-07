"""add security tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("name", name=op.f("uq_roles_name")),
    )
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "pattern", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "role_members",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("member_role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_members_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["member_role_id"],
            ["roles.id"],
            name=op.f("fk_role_members_member_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "member_role_id", name=op.f("pk_role_members")),
    )
    user_roles = op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_roles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_user_roles_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name=op.f("pk_user_roles")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("user_agent", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("display_prefix", sa.String(length=8), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_api_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_api_tokens_user_id")),
    )
    op.create_table(
        "login_failures",
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("subject", name=op.f("pk_login_failures")),
    )

    now = datetime.now(UTC)
    admin_role, anonymous_role, admin_user, anonymous_user = (uuid.uuid4() for _ in range(4))
    op.bulk_insert(
        roles,
        [
            {
                "id": admin_role,
                "name": "admin",
                "description": "Full access to everything.",
                "builtin": True,
            },
            {
                "id": anonymous_role,
                "name": "anonymous",
                "description": "What requests without credentials may do.",
                "builtin": True,
            },
        ],
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_id": admin_role, "pattern": "*"},
            {"role_id": anonymous_role, "pattern": "repository:*:*:browse"},
            {"role_id": anonymous_role, "pattern": "repository:*:*:read"},
        ],
    )
    op.bulk_insert(
        users,
        [
            {
                "id": admin_user,
                "username": "admin",
                "display_name": "Administrator",
                "email": None,
                "password_hash": None,
                "status": "active",
                "must_change_password": True,
                "builtin": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            },
            {
                "id": anonymous_user,
                "username": "anonymous",
                "display_name": "Anonymous",
                "email": None,
                "password_hash": None,
                "status": "active",
                "must_change_password": False,
                "builtin": True,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            },
        ],
    )
    op.bulk_insert(
        user_roles,
        [
            {"user_id": admin_user, "role_id": admin_role},
            {"user_id": anonymous_user, "role_id": anonymous_role},
        ],
    )


def downgrade() -> None:
    op.drop_table("login_failures")
    op.drop_table("api_tokens")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_table("role_members")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("users")
