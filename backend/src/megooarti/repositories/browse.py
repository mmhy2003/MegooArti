"""What a repository holds, as a person looks at it: folders, files and components.

Nothing here is kept apart from the files themselves. A folder is the part of a path
before a slash, and its children are found by jumping through the index on paths from
one child to the next, so the work is that of the children shown, whatever lies
beneath them. That needs paths to be ordered by their bytes, which a migration sees to.

Queries and plain values only. Who may see what is decided by the routes.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.models import Asset, Component, Repository
from megooarti.repositories.reached import holding, unreached
from megooarti.security.access import Reached
from megooarti.storage.models import Blob, BlobStore

# The character after "/" in byte order. Every path under `folder/` is below `folder0`.
_AFTER_SLASH = "0"

# One row for each child of a folder: the first path under it. From a path, the next
# child is the first path after everything that shares its first segment.
_WALK = text(
    """
    WITH RECURSIVE walk(path, n) AS (
        (SELECT a.path, 1 FROM assets a
          WHERE a.repository_id = :repository
            AND a.path >= :lower AND (:inclusive OR a.path <> :lower)
          ORDER BY a.path LIMIT 1)
      UNION ALL
        SELECT following.path, walk.n + 1
        FROM walk CROSS JOIN LATERAL (
            SELECT a.path FROM assets a
            WHERE a.repository_id = :repository
              AND a.path > walk.path
              AND a.path >= CASE
                    WHEN strpos(substr(walk.path, :start), '/') > 0
                    THEN left(walk.path, :start - 2 + strpos(substr(walk.path, :start), '/'))
                         || '0'
                    ELSE walk.path
                  END
            ORDER BY a.path LIMIT 1
        ) following
        WHERE walk.n < :most AND (:upper = '' OR walk.path < :upper)
    )
    SELECT path FROM walk WHERE :upper = '' OR path < :upper ORDER BY n
    """
)


@dataclass(frozen=True)
class ComponentRef:
    id: uuid.UUID
    namespace: str
    name: str
    version: str


@dataclass(frozen=True)
class Child:
    """Something directly in a folder."""

    name: str
    path: str
    kind: str  # "folder" or "file"
    size: int | None = None
    modified: datetime | None = None
    component: ComponentRef | None = None


@dataclass(frozen=True)
class AssetDetail:
    path: str
    size: int
    content_type: str
    md5: str
    sha1: str
    sha256: str
    sha512: str
    blob_store: str
    created_by: str
    created: datetime
    modified: datetime
    last_downloaded: datetime | None
    last_verified: datetime | None
    component: ComponentRef | None


@dataclass(frozen=True)
class ComponentSummary:
    id: uuid.UUID
    namespace: str
    name: str
    version: str
    created: datetime
    modified: datetime


class BadCursor(ValueError):
    """What was given as `after` is not something a listing returned."""


def _cursor(child: Child) -> str:
    return ("d:" if child.kind == "folder" else "f:") + child.name


def _lower_bound(prefix: str, after: str) -> tuple[str, bool]:
    """Where what is still to be listed begins, and whether that path itself is part of it."""
    if not after:
        return prefix, True
    kind, _, name = after.partition(":")
    if kind not in ("d", "f") or not name or "/" in name:
        raise BadCursor(after)
    if kind == "d":
        # Past everything in the folder: a file named like it with "0" on the end is next.
        return prefix + name + _AFTER_SLASH, True
    return prefix + name, False


async def children(
    db: AsyncSession,
    repository: Repository,
    folder: str,
    *,
    unlisted: frozenset[str] = frozenset(),
    after: str = "",
    limit: int,
) -> tuple[list[Child], str | None]:
    """What is directly in a folder, in byte order of the paths, and where to go on.

    `folder` is a path without a slash at either end, or "" for the root. A name that
    is both a file and a folder is listed as each. The second value is what to give
    as `after` for the rest, or None at the end. A file's component is left out if it
    is in one of the `unlisted` namespaces, which nobody can open. Raises BadCursor.
    """
    prefix = f"{folder}/" if folder else ""
    lower, inclusive = _lower_bound(prefix, after)
    rows = await db.execute(
        _WALK,
        {
            "repository": repository.id,
            "lower": lower,
            "inclusive": inclusive,
            "upper": prefix[:-1] + _AFTER_SLASH if prefix else "",
            "start": len(prefix) + 1,
            "most": limit + 1,
        },
    )
    firsts = [path for (path,) in rows]
    found: list[Child] = []
    for path in firsts[:limit]:
        name, nested, _ = path[len(prefix) :].partition("/")
        found.append(Child(name, prefix + name, "folder" if nested else "file"))

    files = [child.path for child in found if child.kind == "file"]
    details = {}
    if files:
        held = await db.execute(
            select(Asset.path, Blob.size, Asset.updated_at, Component)
            .join(Blob, Blob.id == Asset.blob_id)
            .outerjoin(Component, Component.id == Asset.component_id)
            .where(Asset.repository_id == repository.id, Asset.path.in_(files))
        )
        details = {
            path: (size, modified, _ref(part, unlisted)) for path, size, modified, part in held
        }
    listed = [
        child
        if child.kind == "folder"
        else Child(child.name, child.path, "file", *details[child.path])
        for child in found
        if child.kind == "folder" or child.path in details  # deleted since it was walked
    ]
    following = _cursor(found[-1]) if len(firsts) > limit and found else None
    return listed, following


def _ref(
    component: Component | None, unlisted: frozenset[str] = frozenset()
) -> ComponentRef | None:
    if component is None or component.namespace in unlisted:
        return None
    return ComponentRef(component.id, component.namespace, component.name, component.version)


async def asset(
    db: AsyncSession, repository: Repository, path: str, *, unlisted: frozenset[str] = frozenset()
) -> AssetDetail | None:
    """Everything about one file, or None if there is none at the path."""
    found = (
        await db.execute(
            select(Asset, Blob, BlobStore.name, Component)
            .join(Blob, Blob.id == Asset.blob_id)
            .join(BlobStore, BlobStore.id == Blob.blob_store_id)
            .outerjoin(Component, Component.id == Asset.component_id)
            .where(Asset.repository_id == repository.id, Asset.path == path)
        )
    ).one_or_none()
    if found is None:
        return None
    held, blob, store, component = found
    return AssetDetail(
        path=held.path,
        size=blob.size,
        content_type=held.content_type,
        md5=blob.md5,
        sha1=blob.sha1,
        sha256=blob.sha256,
        sha512=blob.sha512,
        blob_store=store,
        created_by=held.created_by,
        created=held.created_at,
        modified=held.updated_at,
        last_downloaded=held.last_downloaded_at,
        last_verified=held.last_verified_at,
        component=_ref(component, unlisted),
    )


def _listed(repository: Repository, unlisted: frozenset[str]):
    conditions = [Component.repository_id == repository.id]
    if unlisted:
        conditions.append(Component.namespace.not_in(unlisted))
    return conditions


async def components(
    db: AsyncSession,
    repository: Repository,
    *,
    unlisted: frozenset[str],
    namespace: str | None = None,
    name: str | None = None,
    limit: int,
    offset: int,
    reached: Reached | None = None,
) -> tuple[list[ComponentSummary], int]:
    """A page of a repository's components, and how many there are.

    In the order of namespace and name, the newest first. `unlisted` are the
    namespaces the repository's format keeps for itself. With `reached`, only the
    components with a file it reaches (spec 10).
    """
    conditions = _listed(repository, unlisted)
    if namespace is not None:
        conditions.append(Component.namespace == namespace)
    if name is not None:
        conditions.append(Component.name == name)
    if reached is not None and not reached.whole:
        by_id = {repository.id: reached}
        conditions.append(holding(by_id))
        hidden = await unreached(db, by_id, conditions)
        if hidden:
            conditions.append(Component.id.not_in(hidden))
    total = await db.scalar(select(func.count()).select_from(Component).where(*conditions))
    # The page is chosen first, and only its components' files are looked at: grouping
    # every component with its files to show fifty would read the whole repository.
    modified = (
        select(func.max(Asset.updated_at))
        .where(Asset.component_id == Component.id)
        .correlate(Component)
        .scalar_subquery()
    )
    order = (Component.namespace, Component.name, Component.created_at.desc(), Component.id)
    chosen = (
        select(Component.id).where(*conditions).order_by(*order).limit(limit).offset(offset)
    ).subquery()
    rows = await db.execute(
        select(*_COLUMNS, modified).join(chosen, chosen.c.id == Component.id).order_by(*order)
    )
    return [_summary(*row) for row in rows], total or 0


# What is shown of a component. Not its attributes: a format may keep a whole manifest there.
_COLUMNS = (
    Component.id,
    Component.namespace,
    Component.name,
    Component.version,
    Component.created_at,
    Component.updated_at,
)


def _summary(
    identifier: uuid.UUID,
    namespace: str,
    name: str,
    version: str,
    created: datetime,
    updated: datetime,
    modified: datetime | None,
) -> ComponentSummary:
    return ComponentSummary(identifier, namespace, name, version, created, modified or updated)


async def component(
    db: AsyncSession,
    repository: Repository,
    component_id: uuid.UUID,
    *,
    unlisted: frozenset[str],
    reached: Reached | None = None,
) -> tuple[ComponentSummary, list[Child]] | None:
    """One component and its files, in path order, or None if it is not one to show.
    With `reached`, only the files it reaches, and None if it reaches none (spec 10)."""
    found = (
        await db.execute(
            select(*_COLUMNS).where(Component.id == component_id, *_listed(repository, unlisted))
        )
    ).one_or_none()
    if found is None:
        return None
    rows = await db.execute(
        select(Asset.path, Blob.size, Asset.updated_at)
        .join(Blob, Blob.id == Asset.blob_id)
        .where(Asset.component_id == component_id)
        .order_by(Asset.path)
    )
    reference = ComponentRef(*found[:4])
    files = [
        Child(path.rpartition("/")[2], path, "file", size, modified, reference)
        for path, size, modified in rows
        if reached is None or reached.allows(path)
    ]
    if reached is not None and not files:
        return None
    newest = max((child.modified for child in files), default=None)
    return _summary(*found, newest), files


async def paths_under(
    db: AsyncSession, repository: Repository, folder: str, *, after: str = "", limit: int
) -> list[str]:
    """The paths of the files under a folder, in order, starting after `after`.

    Never a path outside the folder, whatever `after` is.
    """
    prefix = f"{folder}/"
    rows = await db.scalars(
        select(Asset.path)
        .where(
            Asset.repository_id == repository.id,
            Asset.path > max(after.encode(), prefix.encode()).decode(),
            Asset.path < prefix[:-1] + _AFTER_SLASH,
        )
        .order_by(Asset.path)
        .limit(limit)
    )
    return list(rows)
