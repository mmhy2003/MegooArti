"""Instance-wide settings that administrators change at runtime."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from megooarti.clock import utcnow
from megooarti.db.base import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TrustedCertificate(Base):
    """A certificate every outbound TLS connection trusts, besides the authorities the
    server trusts already: an organisation's own authority, or a server's own (spec 6)."""

    __tablename__ = "trusted_certificates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(1024))
    issuer: Mapped[str] = mapped_column(String(1024))
    # SHA-256 of the certificate's DER bytes, in lower-case hex: how a person checks it.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pem: Mapped[str] = mapped_column(Text)
    added_by: Mapped[str] = mapped_column(String(64))  # the name, which outlives the user
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
