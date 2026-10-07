"""The one place the application reads the current time."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
