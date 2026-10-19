"""add sign-in sources, the source a user signs in from, and who gave a user a role

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("group_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sources")),
        sa.UniqueConstraint("name", name=op.f("uq_auth_sources_name")),
    )
    op.add_column("users", sa.Column("source_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("external_id", sa.String(length=512), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_source_id_auth_sources"),
        "users",
        "auth_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_users_source_id"), "users", ["source_id"])
    op.create_unique_constraint(op.f("uq_users_source_id"), "users", ["source_id", "external_id"])
    # Every role held until now was given by an administrator.
    op.add_column(
        "user_roles",
        sa.Column("granted_by", sa.String(length=8), nullable=False, server_default="admin"),
    )


def downgrade() -> None:
    op.drop_column("user_roles", "granted_by")
    op.drop_constraint(op.f("uq_users_source_id"), "users", type_="unique")
    op.drop_index(op.f("ix_users_source_id"), table_name="users")
    op.drop_constraint(op.f("fk_users_source_id_auth_sources"), "users", type_="foreignkey")
    op.drop_column("users", "external_id")
    op.drop_column("users", "source_id")
    op.drop_table("auth_sources")
