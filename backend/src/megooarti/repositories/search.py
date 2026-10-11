"""Finding components across repositories.

What was typed is matched as it reads: each word must be contained in a component's
search text, `*` stands for anything, and every other character is itself. Fields
match a whole value. A checksum finds the components that have a file with it.

Queries and plain values only. Which repositories may be searched is the route's to say.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.formats import get_format
from megooarti.repositories.models import Asset, Component, Repository
from megooarti.storage.models import Blob

# Lower-case hexadecimal digits of each checksum.
CHECKSUMS = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}
# More words than this narrow nothing a person meant, and each is a condition.
MAX_WORDS = 10
_ESCAPE = "\\"


@dataclass(frozen=True)
class Wanted:
    """What to search for. An empty value asks for nothing."""

    q: str = ""
    namespace: str = ""
    name: str = ""
    version: str = ""
    md5: str = ""
    sha1: str = ""
    sha256: str = ""
    sha512: str = ""


@dataclass(frozen=True)
class Found:
    id: uuid.UUID
    repository: str
    format: str
    namespace: str
    name: str
    version: str
    created: datetime
    modified: datetime


class BadChecksum(ValueError):
    """A checksum that is not the lower-case hexadecimal digits of its kind. Names the field."""


def pattern(typed: str) -> str:
    """A LIKE pattern in which `*` is anything and every other character is itself."""
    escaped = typed.replace(_ESCAPE, _ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    return escaped.replace("*", "%")


def _conditions(wanted: Wanted) -> list:
    conditions = []
    for word in wanted.q.lower().split()[:MAX_WORDS]:
        conditions.append(Component.search.like(f"%{pattern(word)}%", escape=_ESCAPE))
    for column, value in (
        (Component.namespace, wanted.namespace),
        (Component.name, wanted.name),
        (Component.version, wanted.version),
    ):
        if value:
            conditions.append(column.ilike(pattern(value), escape=_ESCAPE))
    for field, length in CHECKSUMS.items():
        value = getattr(wanted, field)
        if not value:
            continue
        if len(value) != length or value.strip("0123456789abcdef"):
            raise BadChecksum(field)
        conditions.append(
            exists()
            .where(
                Asset.component_id == Component.id,
                Blob.id == Asset.blob_id,
                getattr(Blob, field) == value,
            )
            .correlate(Component)
        )
    return conditions


def _unlisted(repositories: Sequence[Repository]) -> list:
    """Conditions that leave out what each format keeps for itself."""
    by_format: dict[str, list[uuid.UUID]] = {}
    for repository in repositories:
        by_format.setdefault(repository.format, []).append(repository.id)
    conditions = []
    for name, held in by_format.items():
        handler = get_format(name)
        if handler is not None and handler.unlisted_namespaces:
            theirs = and_(
                Component.repository_id.in_(held),
                Component.namespace.in_(handler.unlisted_namespaces),
            )
            conditions.append(not_(theirs))
    return conditions


async def search(
    db: AsyncSession,
    repositories: Sequence[Repository],
    wanted: Wanted,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Found], int]:
    """A page of the components in these repositories that match, and how many there are.

    In the order of name, namespace and repository, the newest first. Raises BadChecksum.
    """
    conditions = _conditions(wanted)
    if not repositories:
        return [], 0
    conditions.append(Component.repository_id.in_([repository.id for repository in repositories]))
    conditions += _unlisted(repositories)
    total = await db.scalar(select(func.count()).select_from(Component).where(*conditions))
    modified = (
        select(func.max(Asset.updated_at))
        .where(Asset.component_id == Component.id)
        .correlate(Component)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(
            Component.id,
            Repository.name,
            Repository.format,
            Component.namespace,
            Component.name,
            Component.version,
            Component.created_at,
            Component.updated_at,
            modified,
        )
        .join(Repository, Repository.id == Component.repository_id)
        .where(*conditions)
        .order_by(
            # By bytes, so that the order is the same whatever the database orders by.
            Component.name.collate("C"),
            Component.namespace.collate("C"),
            Repository.name_key,
            Component.created_at.desc(),
            Component.id,
        )
        .limit(limit)
        .offset(offset)
    )
    # The last two columns: when the component itself changed, and when a file of it did.
    found = [Found(*row[:7], row[8] or row[7]) for row in rows]
    return found, total or 0
