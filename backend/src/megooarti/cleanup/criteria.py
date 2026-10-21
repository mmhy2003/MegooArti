"""What a cleanup policy selects (spec 4.2): a component whose criteria are all met.

A policy's days are what a database narrows by; whether a component is selected is
`Criteria.selects`, which the preview and the run alike ask, so they never disagree.
"""

import functools
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from megooarti.repositories.formats import Format, get_format
from megooarti.security.selectors import SelectorError, checked_pattern

MAX_DAYS = 36500
ANY_FORMAT = "*"

ReleaseType = Literal["release", "prerelease"]


@dataclass(frozen=True)
class Held:
    """A component as a policy sees it."""

    id: uuid.UUID
    namespace: str
    name: str
    version: str
    modified: datetime  # the latest its files were written
    downloaded: datetime  # the latest its files were downloaded, else when it was made
    paths: tuple[str, ...]  # its files', as kept: without a leading `/`


@functools.lru_cache(maxsize=256)
def _pattern(text: str) -> re.Pattern[str]:
    return checked_pattern(text)


@dataclass(frozen=True)
class Criteria:
    updated_days: int | None = None
    downloaded_days: int | None = None
    release_type: ReleaseType | None = None
    asset_pattern: str | None = None

    def cutoffs(self, now: datetime) -> tuple[datetime | None, datetime | None]:
        """The latest a selected component may have been written, and downloaded."""
        return (
            None if self.updated_days is None else now - timedelta(days=self.updated_days),
            None if self.downloaded_days is None else now - timedelta(days=self.downloaded_days),
        )

    def selects(self, held: Held, now: datetime, handler: Format) -> bool:
        """Whether every criterion given is met."""
        written, downloaded = self.cutoffs(now)
        if written is not None and not held.modified < written:
            return False
        if downloaded is not None and not held.downloaded < downloaded:
            return False
        if self.release_type is not None:
            prerelease = handler.is_prerelease(held.version)
            if prerelease != (self.release_type == "prerelease"):
                return False
        if self.asset_pattern is not None:
            pattern = _pattern(self.asset_pattern)
            if not any(pattern.fullmatch(f"/{path}") for path in held.paths):
                return False
        return True


def problems(format: str, criteria: Criteria) -> list[dict[str, str]]:
    """Why these cannot be a policy of this format (a format's name, or `*`), each at
    its field; none when they can."""
    found: list[dict[str, str]] = []

    def say(field: str, message: str) -> None:
        found.append({"field": field, "message": message})

    handler = None if format == ANY_FORMAT else get_format(format)
    if format != ANY_FORMAT and handler is None:
        say("format", "Unknown format.")
    given = (
        criteria.updated_days,
        criteria.downloaded_days,
        criteria.release_type,
        criteria.asset_pattern,
    )
    if all(value is None for value in given):
        say("criteria", "A policy needs at least one criterion.")
    for field in ("updated_days", "downloaded_days"):
        days = getattr(criteria, field)
        if days is not None and not 1 <= days <= MAX_DAYS:
            say(field, f"Must be from 1 to {MAX_DAYS} days.")
    if criteria.release_type is not None:
        if format == ANY_FORMAT:
            say("release_type", "A policy of every format has no release type.")
        elif handler is not None and not handler.has_prereleases:
            say("release_type", "This format has no pre-releases.")
    if criteria.asset_pattern is not None:
        try:
            _pattern(criteria.asset_pattern)
        except SelectorError as error:
            say("asset_pattern", error.message)
    return found
