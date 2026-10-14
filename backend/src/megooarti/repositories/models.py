"""Repositories and what they hold: components (packages) made of assets (files)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # The name in lower case: names are unique ignoring case, but looked up exactly.
    name_key: Mapped[str] = mapped_column(String(64), unique=True)
    format: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(16))
    online: Mapped[bool] = mapped_column(default=True)
    blob_store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("blob_stores.id", ondelete="RESTRICT")
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Raised by every change to what a hosted repository holds, for a format that writes
    # its indexes from its packages, and by a new signing key: an index is written once
    # for each revision, and dated when the revision was made.
    revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint("repository_id", "namespace", "name", "version"),
        # Trigrams, so that "contains" and patterns with `*` do not read every row.
        *(
            Index(
                f"ix_components_{column}_trgm",
                column,
                postgresql_using="gin",
                postgresql_ops={column: "gin_trgm_ops"},
            )
            for column in ("search", "name", "namespace")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    namespace: Mapped[str] = mapped_column(String(1024), default="")
    name: Mapped[str] = mapped_column(String(1024))
    version: Mapped[str] = mapped_column(String(255), default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # The words it is found by, in lower case. Its format says what they are.
    search: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    # No cascade: a component is deleted only by code that has checked, under the
    # component lock, that no asset is left. Deleting a repository still works, because
    # the check runs at the end of the statement, after its assets have gone too.
    component_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("components.id"), index=True)
    # Ordered by its bytes, so that what is under a folder lies together in the index.
    path: Mapped[str] = mapped_column(String(1024, collation="C"))
    blob_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blobs.id", ondelete="RESTRICT"), index=True
    )
    content_type: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="asset")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set by the code when the content changes. Deliberately no onupdate: noting a
    # download must not change Last-Modified.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssetReference(Base):
    """A file refers to another file of its repository, by path.

    For formats in which one file is only usable with others: a container image's
    manifest refers to its layers. A file nothing refers to can be told apart.
    """

    __tablename__ = "asset_references"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    # A path, compared with paths, so ordered as they are.
    target: Mapped[str] = mapped_column(String(1024, collation="C"), primary_key=True, index=True)


class Upload(Base):
    """An upload that arrives over several requests. Its bytes are with the blob store."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    # What it is an upload for, in the format's own terms.
    key: Mapped[str] = mapped_column(String(1024))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RepositoryMember(Base):
    """`group_id` presents `member_id`, at `position` in its order."""

    __tablename__ = "repository_members"

    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    # A repository cannot be deleted while a group presents it.
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class ProxyState(Base):
    """How a proxy repository's remote has been behaving. Shared by every container."""

    __tablename__ = "proxy_state"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    failures: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NegativeCacheEntry(Base):
    """A path the remote said it does not have, remembered until `expires_at`."""

    __tablename__ = "negative_cache"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SigningKey(Base):
    """The key a repository signs its indexes with. The private key is sealed."""

    __tablename__ = "signing_keys"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # openpgp, or rsa
    algorithm: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(128))
    public_key: Mapped[str] = mapped_column(Text)
    private_key: Mapped[str] = mapped_column(Text)  # sealed with secrets_box
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
