"""add what a component is found by, and indexes to search with

Search matches text that is contained in a component's search text, which needs a
trigram index, and so the `pg_trgm` extension. It is trusted since PostgreSQL 13: the
owner of the database can create it. Where the application's role may not, have an
administrator run `CREATE EXTENSION pg_trgm` in the database first.

Components that exist are given their namespace, name and version as search text.
Rebuilding a repository's index writes what its format would have written.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKSUMS = ("md5", "sha1", "sha256", "sha512")
_TRIGRAMS = ("search", "name", "namespace")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column("components", sa.Column("search", sa.Text(), nullable=False, server_default=""))
    op.execute(
        "UPDATE components SET search = lower(concat_ws(' ', nullif(namespace, ''), name, "
        "nullif(version, '')))"
    )
    for column in _TRIGRAMS:
        op.create_index(
            f"ix_components_{column}_trgm",
            "components",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )
    # A checksum is only ever looked up whole: a hash index is the small one for that.
    for column in _CHECKSUMS:
        op.create_index(f"ix_blobs_{column}", "blobs", [column], postgresql_using="hash")


def downgrade() -> None:
    for column in _CHECKSUMS:
        op.drop_index(f"ix_blobs_{column}", table_name="blobs")
    for column in _TRIGRAMS:
        op.drop_index(f"ix_components_{column}_trgm", table_name="components")
    op.drop_column("components", "search")
    # The extension stays: something else in the database may use it.
