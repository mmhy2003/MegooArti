"""add storage and repositories

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    blob_stores = op.create_table(
        "blob_stores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("config", _json(), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blob_stores")),
        sa.UniqueConstraint("name", name=op.f("uq_blob_stores_name")),
    )
    op.create_table(
        "blobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("blob_store_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("md5", sa.String(length=32), nullable=False),
        sa.Column("sha1", sa.String(length=40), nullable=False),
        sa.Column("sha512", sa.String(length=128), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        _timestamp("created_at"),
        _timestamp("unreferenced_since", nullable=True),
        sa.ForeignKeyConstraint(
            ["blob_store_id"],
            ["blob_stores.id"],
            name=op.f("fk_blobs_blob_store_id_blob_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blobs")),
        sa.UniqueConstraint("blob_store_id", "sha256", name=op.f("uq_blobs_blob_store_id")),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("name_key", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("blob_store_id", sa.Uuid(), nullable=True),
        sa.Column("config", _json(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["blob_store_id"],
            ["blob_stores.id"],
            name=op.f("fk_repositories_blob_store_id_blob_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repositories")),
        sa.UniqueConstraint("name", name=op.f("uq_repositories_name")),
        sa.UniqueConstraint("name_key", name=op.f("uq_repositories_name_key")),
    )
    op.create_table(
        "components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=1024), nullable=False),
        sa.Column("name", sa.String(length=1024), nullable=False),
        sa.Column("version", sa.String(length=255), nullable=False),
        sa.Column("attributes", _json(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_components_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_components")),
        sa.UniqueConstraint(
            "repository_id",
            "namespace",
            "name",
            "version",
            name=op.f("uq_components_repository_id"),
        ),
    )
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("component_id", sa.Uuid(), nullable=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("blob_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("attributes", _json(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("last_downloaded_at", nullable=True),
        _timestamp("last_verified_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_assets_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["component_id"],
            ["components.id"],
            name=op.f("fk_assets_component_id_components"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blob_id"], ["blobs.id"], name=op.f("fk_assets_blob_id_blobs"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assets")),
        sa.UniqueConstraint("repository_id", "path", name=op.f("uq_assets_repository_id")),
    )
    op.create_index(op.f("ix_assets_component_id"), "assets", ["component_id"], unique=False)
    op.create_index(op.f("ix_assets_blob_id"), "assets", ["blob_id"], unique=False)

    op.bulk_insert(
        blob_stores,
        [
            {
                "id": uuid.uuid4(),
                "name": "default",
                "type": "file",
                "config": {"path": "default"},
                "created_at": datetime.now(UTC),
            }
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assets_blob_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_component_id"), table_name="assets")
    op.drop_table("assets")
    op.drop_table("components")
    op.drop_table("repositories")
    op.drop_table("blobs")
    op.drop_table("blob_stores")
