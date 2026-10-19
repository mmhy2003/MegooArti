"""add trusted certificates, which every outbound TLS connection trusts

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trusted_certificates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=1024), nullable=False),
        sa.Column("issuer", sa.String(length=1024), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("not_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pem", sa.Text(), nullable=False),
        sa.Column("added_by", sa.String(length=64), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trusted_certificates")),
        sa.UniqueConstraint("fingerprint", name=op.f("uq_trusted_certificates_fingerprint")),
    )


def downgrade() -> None:
    op.drop_table("trusted_certificates")
