"""add asset references and uploads in progress

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_references",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(length=1024), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["assets.id"],
            name=op.f("fk_asset_references_asset_id_assets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("asset_id", "target", name=op.f("pk_asset_references")),
    )
    op.create_index(
        op.f("ix_asset_references_target"), "asset_references", ["target"], unique=False
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=1024), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_uploads_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
    )


def downgrade() -> None:
    op.drop_table("uploads")
    op.drop_index(op.f("ix_asset_references_target"), table_name="asset_references")
    op.drop_table("asset_references")
