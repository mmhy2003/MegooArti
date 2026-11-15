"""add cleanup policies, and the repositories they are attached to

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cleanup_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("updated_days", sa.Integer(), nullable=True),
        sa.Column("downloaded_days", sa.Integer(), nullable=True),
        sa.Column("release_type", sa.String(length=16), nullable=True),
        sa.Column("asset_pattern", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cleanup_policies")),
        sa.UniqueConstraint("name_key", name=op.f("uq_cleanup_policies_name_key")),
    )
    op.create_table(
        "repository_cleanup_policies",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["cleanup_policies.id"],
            name=op.f("fk_repository_cleanup_policies_policy_id_cleanup_policies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_repository_cleanup_policies_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "repository_id", "policy_id", name=op.f("pk_repository_cleanup_policies")
        ),
    )
    op.create_index(
        op.f("ix_repository_cleanup_policies_policy_id"),
        "repository_cleanup_policies",
        ["policy_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_repository_cleanup_policies_policy_id"),
        table_name="repository_cleanup_policies",
    )
    op.drop_table("repository_cleanup_policies")
    op.drop_table("cleanup_policies")
