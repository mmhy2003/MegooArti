"""add a repository's revision, and the keys repositories sign their indexes with

A repository whose format writes its indexes from its packages counts its changes, so
that an index is written once for each. Repositories that exist start at 0.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column("repositories", sa.Column("changed_at", sa.DateTime(timezone=True)))
    op.create_table(
        "signing_keys",
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("private_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_signing_keys_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repository_id", name=op.f("pk_signing_keys")),
    )


def downgrade() -> None:
    op.drop_table("signing_keys")
    op.drop_column("repositories", "changed_at")
    op.drop_column("repositories", "revision")
