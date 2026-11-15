"""Which components of a repository its cleanup policies select (spec 4.2, 5.2).

A repository is walked a page of components at a time, in the order of their ids. The
database narrows each page by the policies' days (P2); `Criteria.selects` then decides,
with the pattern, the release type, and what the format says of a component's use. The
preview and the run both walk this way, so they never disagree.
"""

import heapq
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import datetime

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, true

from megooarti.cleanup.criteria import Criteria, Held
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.models import Asset, Component
from megooarti.security.access import Reached

BATCH = 500


def _columns():
    """A component's id, name, when its newest file was written and downloaded (else when
    it was made), and its files' paths."""
    files = Asset.component_id == Component.id
    modified = select(func.max(Asset.updated_at)).where(files).correlate(Component)
    downloaded = select(func.max(Asset.last_downloaded_at)).where(files).correlate(Component)
    paths = select(func.array_agg(Asset.path)).where(files).correlate(Component)
    return (
        modified.scalar_subquery(),
        func.coalesce(downloaded.scalar_subquery(), Component.created_at),
        paths.scalar_subquery(),
    )


def _narrowing(policies: Sequence[Criteria], now: datetime, modified, downloaded):
    """What a component must meet for any policy to select it: by the days alone."""
    either: list[ColumnElement[bool]] = []
    for policy in policies:
        written, used = policy.cutoffs(now)
        conditions = []
        if written is not None:
            conditions.append(modified < written)
        if used is not None:
            conditions.append(downloaded < used)
        if not conditions:
            return true()  # a policy of no days narrows nothing
        either.append(and_(*conditions))
    return or_(*either) if either else true()


async def _page(
    context: RepositoryContext, conditions: list, *, after: uuid.UUID | None, limit: int
) -> list[Held]:
    modified, downloaded, paths = _columns()
    where = [
        Component.repository_id == context.repository.id,
        # A component with no file (an index's rebuild cut short) is no candidate: left
        # in a page, it would make the page look like the last one.
        exists().where(Asset.component_id == Component.id),
        *conditions,
    ]
    unlisted = context.format.unlisted_namespaces
    if unlisted:
        where.append(Component.namespace.not_in(sorted(unlisted)))
    if after is not None:
        where.append(Component.id > after)
    rows = await context.db.execute(
        select(
            Component.id,
            Component.namespace,
            Component.name,
            Component.version,
            modified,
            downloaded,
            paths,
        )
        .where(*where)
        .order_by(Component.id)
        .limit(limit)
    )
    return [
        Held(id, namespace, name, version, written, used, tuple(sorted(held)))
        for id, namespace, name, version, written, used, held in rows
        if held  # a component whose last file went meanwhile
    ]


async def _used(context: RepositoryContext, held: Held) -> Held:
    """The component, with what its format says of its use (P3)."""
    used = await context.format.last_used(context, held)
    return held if used is None or used <= held.downloaded else replace(held, downloaded=used)


async def selected(
    context: RepositoryContext,
    policies: Sequence[Criteria],
    now: datetime,
    *,
    batch: int = BATCH,
) -> AsyncIterator[Held]:
    """Every component of the repository any of these policies selects (E2)."""
    if not policies:
        return
    modified, downloaded, _ = _columns()
    narrowed = _narrowing(policies, now, modified, downloaded)
    after = None
    while True:
        # The page is asked for with the narrowing: a component it leaves out is selected
        # by no policy, and nothing more is read of it.
        found = await _page(context, [narrowed], after=after, limit=batch)
        for held in found:
            held = await _used(context, held)
            if any(policy.selects(held, now, context.format) for policy in policies):
                yield held
        if len(found) < batch:
            return
        after = found[-1].id


async def held(context: RepositoryContext, component_id: uuid.UUID) -> Held | None:
    """One component of the repository, read afresh; None if it is not there."""
    found = await _page(context, [Component.id == component_id], after=None, limit=1)
    return await _used(context, found[0]) if found else None


async def preview(
    context: RepositoryContext,
    criteria: Criteria,
    now: datetime,
    *,
    limit: int,
    offset: int,
    reached: Reached,
) -> tuple[list[Held], int]:
    """A page of what a policy selects, newest first by when it was written, and how many
    it selects: of what `reached` reaches (a component, by any of its files). Only the
    page is held while they are counted (P4)."""
    kept: list[tuple[datetime, str, Held]] = []
    total = 0
    async for found in selected(context, [criteria], now):
        if not reached.whole and not any(reached.allows(path) for path in found.paths):
            continue
        total += 1
        heapq.heappush(kept, (found.modified, str(found.id), found))
        if len(kept) > offset + limit:
            heapq.heappop(kept)
    newest = [found for _, _, found in sorted(kept, reverse=True)]
    return newest[offset : offset + limit], total
