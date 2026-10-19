"""add OAuth's clients, approvals and tokens, for AI agents' sign-in to /mcp

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("redirect_uris", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_from", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
    )
    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_grants_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_grants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_grants")),
    )
    op.create_index(op.f("ix_oauth_grants_client_id"), "oauth_grants", ["client_id"])
    op.create_index(op.f("ix_oauth_grants_user_id"), "oauth_grants", ["user_id"])
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_challenge", sa.String(length=128), nullable=True),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=True),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["oauth_grants.id"],
            name=op.f("fk_oauth_tokens_grant_id_oauth_grants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_tokens_token_hash")),
    )
    op.create_index(op.f("ix_oauth_tokens_grant_id"), "oauth_tokens", ["grant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_oauth_tokens_grant_id"), table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_index(op.f("ix_oauth_grants_user_id"), table_name="oauth_grants")
    op.drop_index(op.f("ix_oauth_grants_client_id"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")
