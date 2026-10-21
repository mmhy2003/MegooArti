"""Cleanup policies (spec 4.1): criteria of a format, or of all formats, attached to
hosted and proxy repositories."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.cleanup.criteria import Criteria
from megooarti.clock import utcnow
from megooarti.db.base import Base


class CleanupPolicy(Base):
    __tablename__ = "cleanup_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    # The name in lower case: names are unique ignoring case, but looked up exactly.
    name_key: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    # A format's name, or `*` for every format. It does not change (E9).
    format: Mapped[str] = mapped_column(String(32))
    updated_days: Mapped[int | None] = mapped_column()
    downloaded_days: Mapped[int | None] = mapped_column()
    release_type: Mapped[str | None] = mapped_column(String(16))
    asset_pattern: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    @property
    def criteria(self) -> Criteria:
        return Criteria(
            updated_days=self.updated_days,
            downloaded_days=self.downloaded_days,
            release_type=self.release_type,  # type: ignore[arg-type]
            asset_pattern=self.asset_pattern,
        )


class RepositoryCleanupPolicy(Base):
    """A policy attached to a repository: each goes with either."""

    __tablename__ = "repository_cleanup_policies"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cleanup_policies.id", ondelete="CASCADE"), primary_key=True, index=True
    )
