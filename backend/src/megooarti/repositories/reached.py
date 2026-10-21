"""Which components of repositories a caller reaches (spec 10): for listing and searching
them where a selector permission reaches some of a repository and not the whole.

A component is reached if one of its files is. The database is asked first for the
components with a file the reach's narrowing keeps; where that is not exact (a pattern
is in it), the files it kept are then checked one by one, and the components none of
whose files is reached are left out too. Who reaches every repository whole pays
nothing for this.
"""

import uuid
from collections.abc import Mapping

from sqlalchemy import ColumnElement, and_, exists, false, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from megooarti.repositories.models import Asset, Component
from megooarti.security.access import Reached


def _path(asset: type[Asset] = Asset) -> ColumnElement[str]:
    """An asset's path as an expression sees it: from `/`."""
    return literal("/").concat(asset.path)


def holding(reached: Mapping[uuid.UUID, Reached]) -> ColumnElement[bool]:
    """The components of these repositories (by their ids) with a file reached: exactly
    where a reach is the whole or exact, and a superset where it is not."""
    # A file of its own, so that a query that has assets already still has these.
    held = aliased(Asset)
    parts = []
    for repository_id, reach in reached.items():
        theirs = Component.repository_id == repository_id
        condition, _ = reach.narrowing(_path(held))
        if condition is None:
            parts.append(theirs)
        else:
            parts.append(and_(theirs, exists().where(held.component_id == Component.id, condition)))
    return or_(*parts) if parts else false()


async def unreached(
    db: AsyncSession, reached: Mapping[uuid.UUID, Reached], conditions: list
) -> list[uuid.UUID]:
    """The components `holding` keeps, of those the conditions give, none of whose files
    is reached after all: to be left out too. Only a reach through a pattern has any."""
    left: list[uuid.UUID] = []
    for repository_id, reach in reached.items():
        condition, exact = reach.narrowing(_path())
        if condition is None or exact:
            continue
        rows = await db.execute(
            select(Component.id, Asset.path)
            .join(Asset, Asset.component_id == Component.id)
            .where(*conditions, Component.repository_id == repository_id, condition)
        )
        seen: set[uuid.UUID] = set()
        kept: set[uuid.UUID] = set()
        for component_id, path in rows:
            seen.add(component_id)
            if component_id not in kept and reach.allows(path):
                kept.add(component_id)
        left.extend(seen - kept)
    return left
