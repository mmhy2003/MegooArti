"""Blob stores and the blobs in them."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class BlobStore(Base):
    __tablename__ = "blob_stores"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    type: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Blob(Base):
    """One piece of content in one blob store, named by its SHA-256."""

    __tablename__ = "blobs"
    __table_args__ = (
        UniqueConstraint("blob_store_id", "sha256"),
        # For finding a file by any of its checksums. Hash: a checksum is looked up whole.
        *(
            Index(f"ix_blobs_{column}", column, postgresql_using="hash")
            for column in ("md5", "sha1", "sha256", "sha512")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    blob_store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blob_stores.id", ondelete="RESTRICT")
    )
    sha256: Mapped[str] = mapped_column(String(64))
    md5: Mapped[str] = mapped_column(String(32))
    sha1: Mapped[str] = mapped_column(String(40))
    sha512: Mapped[str] = mapped_column(String(128))
    size: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # A hint for compaction: when the last asset using this blob went away.
    unreferenced_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
