"""add the audit log's records

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=True),
        sa.Column("address", sa.String(length=45), nullable=True),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("target_kind", sa.String(length=32), nullable=True),
        sa.Column("target_name", sa.String(length=255), nullable=True),
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_records")),
    )
    op.create_index(op.f("ix_audit_records_at"), "audit_records", ["at"])
    op.create_index(op.f("ix_audit_records_actor"), "audit_records", ["actor"])
    op.create_index(op.f("ix_audit_records_event"), "audit_records", ["event"])
    op.create_index("ix_audit_records_target", "audit_records", ["target_kind", "target_name"])


def downgrade() -> None:
    op.drop_table("audit_records")
