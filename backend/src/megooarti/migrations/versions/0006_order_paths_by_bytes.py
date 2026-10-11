"""order asset paths by their bytes

A folder's children are found by jumping through the index on paths, which is only
right if paths are ordered by their bytes: everything under `a/` then lies between
`a/` and `a0`. The database's own collation orders by language rules instead.

What a file refers to is a path too, and is compared with paths, so it is ordered
the same way: otherwise the index on it could not be used for that comparison.

This rebuilds the indexes on both, which takes time on a large installation.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PATHS = (("assets", "path"), ("asset_references", "target"))


def upgrade() -> None:
    for table, column in _PATHS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=1024, collation="C"),
            existing_type=sa.String(length=1024),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table, column in _PATHS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=1024, collation="default"),
            existing_type=sa.String(length=1024, collation="C"),
            existing_nullable=False,
        )
