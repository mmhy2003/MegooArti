# Browsing and Deleting Content Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone who may browse a repository can list it as folders and files, open a file or a component, and, with `delete`, remove a file, a component or a folder, through `/api/v1/content`, leaving the repository as its format's own client would.

**Architecture:** Nothing is kept besides the files. A folder is the part of a path before a slash; its children are found by one recursive query that jumps through the index on paths from one child to the next, which needs paths ordered by their bytes, so a migration gives `assets.path` the `C` collation. Details are plain joins. Deleting asks the repository's format to delete a stored file, so that npm moves its dist-tags and Docker removes what only that image used; a component is deleted file by file, and a folder in bounded pieces. The routes decide who may see and delete; the queries know nothing of permissions.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, Alembic, PostgreSQL (recursive CTE, `C` collation), pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-10-11-browse-search-upload-design.md](../specs/2026-10-11-browse-search-upload-design.md), sections 4.1, 5 and the plan 8a parts of 10; D1 to D7 and D10. Business requirements: [docs/BRD.md](../../BRD.md) CMP-1, CMP-2, CMP-3, CMP-8, CMP-9, API-1, API-4, API-5. Task 4 amends the spec where this plan settles something the spec left open or had wrong.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | A folder's children are listed in the byte order of their paths, not folders first. A name that is both a file and a folder is listed as each, the file first. | The walk reads the index in order and cannot know all the folders without reading everything. The spec said "folders first"; Task 4 corrects it. |
| P2 | The cursor of a listing is `d:<name>` or `f:<name>`, the last child shown. After a folder the walk goes on at `<folder>0`, the first path that is not under it; after a file, past the file. | `0` is the character after `/`. A file whose name is the folder's with `0` on the end must not be skipped, so that bound is inclusive. |
| P3 | A listing is two statements: the walk, and the details of the files it found. A test counts them. | D3 of the spec is a claim about cost, and nothing else would notice it break. |
| P4 | A folder that has nothing in it does not exist: listing it is `404`, like a path that is a file. The root of an empty repository is an empty list. | Folders are not stored, so an empty one cannot be told from a missing one. |
| P5 | The spec's `delete_component` hook is not built. A component is deleted by deleting each of its files through `delete_asset`. | Every format's component is exactly its files (a Maven version, an npm tarball, a PyPI release, a Docker tag). |
| P6 | Only npm and Docker override `delete_asset`. Maven's checksums and metadata and PyPI's pages are computed from the stored files when they are asked for, so they follow a delete by themselves. | The spec's table said Maven had to rewrite metadata; it does not store any. Task 4 corrects it. |
| P7 | On a proxy the format is not asked: the file is removed and nothing else. | D7. What a proxy holds is a cache; its format's bookkeeping is rebuilt from the remote. |
| P8 | Deleting a folder goes through at most 1,000 files and answers `deleted`, `skipped` and `next` (the last path looked at). A file the format keeps for itself is skipped, not an error. | A caller that repeats while there is a `next` always ends, even where some files can never be deleted this way. The spec said `more`; Task 4 corrects it. |
| P9 | The components the content API lists leave out the namespaces a format names as its own (`Format.unlisted_namespaces`): Docker's `manifests`. | D10, without waiting for plan 8b's search column. Search will use the same. |
| P10 | A file's `download` address comes from its format (`Format.download_path`). For Docker a tag and a manifest are fetched through `/v2/`; a blob has none. | Docker repositories are not served under `/repository/`. |
| P11 | A new dependency, `require_caller`, is what these routes authenticate with: somebody is calling, signed in or anonymous, and has no password change pending. The route then asks the principal what it may do. | The list of repositories has no one permission to require. `Principal.allows` is already how routes ask. |
| P12 | A repository the caller may not browse is `403` (or `401` for nobody), not `404`. | D2. That a repository exists is not hidden anywhere else either. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; only the security package reads `Principal.patterns`; every route authenticates via a dependency that reaches one in `AUTHENTICATION_DEPENDENCIES`; formats do not commit, the route does; list endpoints use `Page` and `PageParams` (the folder tree is the stated exception); LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds one migration (`0006`), no setting and no dependency.**
- **`browse.py` knows nothing of permissions or HTTP.** The routes in `content_api.py` check `browse` before every read and `delete` before every delete.
- **Nothing is revealed of a repository the caller may not browse:** not in a list, not by a detail, not by the difference between two refusals.
- **A delete through the content API leaves what the format's own client's delete would leave.**
- **No request does unbounded work:** a listing shows at most 200 entries, a folder delete goes through at most 1,000 files.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **Names around a slash.** Folders that are prefixes of one another (`app`, `app-old`, `app.bak`, `apple`), a file named like a folder plus `0`, a name that is both a file and a folder, capitals and small letters, a space; a folder read page by page across those (Task 1).
2. **Who sees what.** `browse` without `read`, `read` without `browse`, nobody, the anonymous user, someone whose password change is pending; a list that leaves out; a component of another repository asked for under this one (Task 2).
3. **Deleting what a format keeps.** An npm package's dist-tags, a Docker layer an image uses, a Docker manifest two tags name, a folder that holds both kinds; what the format's own client then sees (Task 3).
4. **Deleting at the edges.** The root, a path with `..`, a folder next to one with a longer name, a read-only repository, a group, a proxy, without `delete`; a folder larger than one piece (Task 3).
5. **What a path can be.** `..`, an empty segment, a file asked for as a folder, a cursor that no listing returned, a limit of 0 or 201 (Tasks 1, 2).

---

### Task 1: Core: paths in byte order, and walking a folder

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0006_order_paths_by_bytes.py`
- Create: `backend/src/megooarti/repositories/browse.py`
- Modify: `backend/src/megooarti/repositories/models.py`
- Test: `backend/tests/repositories/test_browse.py`

**Interfaces:**
- Consumes: the `Asset`, `Component`, `Repository`, `Blob` and `BlobStore` models.
- Produces:
  - `assets.path` with the `C` collation.
  - `browse.Child(name, path, kind, size=None, modified=None, component=None)`, `browse.ComponentRef(id, namespace, name, version)`, `browse.AssetDetail`, `browse.ComponentSummary(id, namespace, name, version, created, modified, attributes)`, `browse.BadCursor`.
  - `await browse.children(db, repository, folder: str, *, after: str = "", limit: int) -> tuple[list[Child], str | None]`.
  - `await browse.asset(db, repository, path: str) -> AssetDetail | None`.
  - `await browse.components(db, repository, *, unlisted: frozenset[str], namespace=None, name=None, limit: int, offset: int) -> tuple[list[ComponentSummary], int]`.
  - `await browse.component(db, repository, component_id, *, unlisted) -> tuple[ComponentSummary, list[Child]] | None`.
  - `await browse.paths_under(db, repository, folder: str, *, after: str = "", limit: int) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_browse.py`:

```python
"""What a repository holds, as folders, files and components."""

import hashlib
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from megooarti.repositories import browse, service
from megooarti.repositories.browse import BadCursor
from tests.repositories.conftest import someone

EVERYTHING = someone("repository:raw:files", "repository:maven:releases")


@pytest.fixture
async def context(files, context_for):
    return await context_for(files, EVERYTHING)


async def put(context, *paths: str) -> None:
    for path in paths:
        await context.store(path, await context.stage_bytes(path.encode()))


async def listing(db, repository, folder: str = "", **options) -> list[tuple[str, str]]:
    options.setdefault("limit", 50)
    items, _ = await browse.children(db, repository, folder, **options)
    return [(child.kind, child.name) for child in items]


@contextmanager
def statements(connection):
    """Counts what is sent to the database while it is open."""
    seen: list[str] = []

    def note(connection, cursor, statement, *rest) -> None:
        seen.append(statement)

    event.listen(connection, "before_cursor_execute", note)
    try:
        yield seen
    finally:
        event.remove(connection, "before_cursor_execute", note)


async def test_a_folder_shows_what_is_directly_in_it(context, db, files):
    await put(context, "readme.txt", "docs/guide.md", "docs/api/index.html", "src/a/b/c.py")

    root = await listing(db, files)
    docs = await listing(db, files, "docs")
    deep = await listing(db, files, "src/a")

    assert root == [("folder", "docs"), ("file", "readme.txt"), ("folder", "src")]
    assert docs == [("folder", "api"), ("file", "guide.md")]
    assert deep == [("folder", "b")]


async def test_a_file_in_a_listing_says_what_it_is(context, db, files):
    await put(context, "docs/guide.md")

    (child,), following = await browse.children(db, files, "docs", limit=10)

    assert (child.name, child.path, child.kind) == ("guide.md", "docs/guide.md", "file")
    assert child.size == len(b"docs/guide.md")
    assert child.modified is not None
    # A file of a Raw repository is a component of its own: its folder and its name.
    assert (child.component.namespace, child.component.name) == ("docs", "guide.md")
    assert following is None


async def test_names_are_in_the_order_of_their_bytes(context, db, files):
    # "-" and "." come before "/", digits and letters after it, capitals before small.
    await put(context, "a/x", "a-b", "a.b", "a0", "aa", "B", "a", "ab/c", "a b")

    assert await listing(db, files) == [
        ("file", "B"),
        ("file", "a"),
        ("file", "a b"),
        ("file", "a-b"),
        ("file", "a.b"),
        ("folder", "a"),  # a name can be a file and a folder
        ("file", "a0"),
        ("file", "aa"),
        ("folder", "ab"),
    ]
    assert await listing(db, files, "a") == [("file", "x")]
    assert await listing(db, files, "ab") == [("file", "c")]


async def test_a_folder_does_not_show_its_neighbours(context, db, files):
    await put(context, "app/one", "app-old/two", "app.bak/three", "apple/four", "ap/five")

    assert await listing(db, files, "app") == [("file", "one")]
    assert await listing(db, files, "ap") == [("file", "five")]
    assert await listing(db, files, "apple") == [("file", "four")]


async def test_a_folder_that_is_not_there_is_empty(context, db, files):
    await put(context, "docs/guide.md")

    assert await listing(db, files, "nothing") == []
    assert await listing(db, files, "docs/guide.md") == []  # a file has nothing in it
    assert await listing(db, files, "doc") == []


async def test_a_long_folder_is_read_page_by_page(context, db, files):
    names = [f"file-{number:03}" for number in range(25)] + ["sub/one", "sub/two", "zeta"]
    await put(context, *(f"big/{name}" for name in names))
    read, after, pages = [], "", 0

    while True:
        items, following = await browse.children(db, files, "big", after=after, limit=10)
        read += [child.name for child in items]
        pages += 1
        if following is None:
            break
        after = following

    assert read == [f"file-{number:03}" for number in range(25)] + ["sub", "zeta"]
    assert pages == 3


async def test_reading_on_from_a_folder_or_a_file_skips_exactly_that(context, db, files):
    await put(context, "a", "a/one", "a/two", "b", "c/one")

    assert await listing(db, files, after="f:a") == [
        ("folder", "a"),
        ("file", "b"),
        ("folder", "c"),
    ]
    assert await listing(db, files, after="d:a") == [("file", "b"), ("folder", "c")]
    assert await listing(db, files, after="d:c") == []


@pytest.mark.parametrize("after", ["a", "x:a", "d:", "d:a/b", ":"])
async def test_what_is_not_a_cursor_is_refused(db, files, after):
    with pytest.raises(BadCursor):
        await browse.children(db, files, "", after=after, limit=10)


async def test_listing_a_folder_costs_the_same_whatever_lies_beneath_it(context, db, files):
    await put(
        context,
        *(
            f"top-{folder}/deep/{n}/file-{m}"
            for folder in "abc"
            for n in range(8)
            for m in range(8)
        ),
    )
    await put(context, "top-file")
    await db.commit()

    with statements((await db.connection()).sync_connection) as seen:
        items, _ = await browse.children(db, files, "", limit=50)

    assert [child.name for child in items] == ["top-a", "top-b", "top-c", "top-file"]
    assert len(seen) == 2  # the walk, and the details of the files it found


async def test_only_this_repository_is_listed(context, db, files, context_for):
    more = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    await put(await context_for(more, someone("repository:raw:more")), "theirs/file", "zzz")
    await put(context, "ours/file")

    assert await listing(db, files) == [("folder", "ours")]
    assert await listing(db, more) == [("folder", "theirs"), ("file", "zzz")]
    assert await listing(db, files, "theirs") == []


async def test_everything_about_a_file(context, db, files):
    data = b"docs/guide.md"
    await put(context, "docs/guide.md")

    detail = await browse.asset(db, files, "docs/guide.md")

    assert (detail.path, detail.size) == ("docs/guide.md", len(data))
    assert detail.sha256 == hashlib.sha256(data).hexdigest()
    assert detail.sha512 == hashlib.sha512(data).hexdigest()
    assert detail.sha1 == hashlib.sha1(data).hexdigest()
    assert detail.md5 == hashlib.md5(data).hexdigest()
    assert (detail.blob_store, detail.created_by) == ("default", "dana")
    assert detail.created is not None and detail.modified is not None
    assert (detail.last_downloaded, detail.last_verified) == (None, None)
    assert (detail.component.namespace, detail.component.name) == ("docs", "guide.md")
    assert await browse.asset(db, files, "docs") is None


async def test_the_paths_under_a_folder_are_read_in_order_and_in_pieces(context, db, files):
    await put(context, "a/1", "a/2", "a/b/3", "a-not/4", "a0", "b/5")

    everything = await browse.paths_under(db, files, "a", limit=10)
    first = await browse.paths_under(db, files, "a", limit=2)
    rest = await browse.paths_under(db, files, "a", after=first[-1], limit=10)

    assert everything == ["a/1", "a/2", "a/b/3"]
    assert (first, rest) == (["a/1", "a/2"], ["a/b/3"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_browse.py -q`
Expected: collection error, `cannot import name 'browse' from 'megooarti.repositories'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/migrations/versions/0006_order_paths_by_bytes.py`:

```python
"""order asset paths by their bytes

A folder's children are found by jumping through the index on paths, which is only
right if paths are ordered by their bytes: everything under `a/` then lies between
`a/` and `a0`. The database's own collation orders by language rules instead.

This rebuilds the index on paths, which takes time on a large installation.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "assets",
        "path",
        type_=sa.String(length=1024, collation="C"),
        existing_type=sa.String(length=1024),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "assets",
        "path",
        type_=sa.String(length=1024, collation="default"),
        existing_type=sa.String(length=1024, collation="C"),
        existing_nullable=False,
    )
```

In `backend/src/megooarti/repositories/models.py`:

Replace

```python
    component_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("components.id"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
```

with

```python
    component_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("components.id"), index=True)
    # Ordered by its bytes, so that what is under a folder lies together in the index.
    path: Mapped[str] = mapped_column(String(1024, collation="C"))
```

`backend/src/megooarti/repositories/browse.py`:

```python
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
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.repositories.models import Asset, Component, Repository
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
    attributes: dict[str, Any]


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
    db: AsyncSession, repository: Repository, folder: str, *, after: str = "", limit: int
) -> tuple[list[Child], str | None]:
    """What is directly in a folder, in byte order of the paths, and where to go on.

    `folder` is a path without a slash at either end, or "" for the root. A name that
    is both a file and a folder is listed as each. The second value is what to give
    as `after` for the rest, or None at the end. Raises BadCursor.
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
        details = {path: (size, modified, _ref(part)) for path, size, modified, part in held}
    listed = [
        child
        if child.kind == "folder"
        else Child(child.name, child.path, "file", *details[child.path])
        for child in found
        if child.kind == "folder" or child.path in details  # deleted since it was walked
    ]
    following = _cursor(found[-1]) if len(firsts) > limit and found else None
    return listed, following


def _ref(component: Component | None) -> ComponentRef | None:
    if component is None:
        return None
    return ComponentRef(component.id, component.namespace, component.name, component.version)


async def asset(db: AsyncSession, repository: Repository, path: str) -> AssetDetail | None:
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
        component=_ref(component),
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
) -> tuple[list[ComponentSummary], int]:
    """A page of a repository's components, and how many there are.

    In the order of namespace and name, the newest first. `unlisted` are the
    namespaces the repository's format keeps for itself.
    """
    conditions = _listed(repository, unlisted)
    if namespace is not None:
        conditions.append(Component.namespace == namespace)
    if name is not None:
        conditions.append(Component.name == name)
    total = await db.scalar(select(func.count()).select_from(Component).where(*conditions))
    modified = func.max(Asset.updated_at)
    rows = await db.execute(
        select(Component, modified)
        .outerjoin(Asset, Asset.component_id == Component.id)
        .where(*conditions)
        .group_by(Component.id)
        .order_by(Component.namespace, Component.name, Component.created_at.desc(), Component.id)
        .limit(limit)
        .offset(offset)
    )
    return [_summary(part, changed) for part, changed in rows], total or 0


def _summary(component: Component, modified: datetime | None) -> ComponentSummary:
    return ComponentSummary(
        id=component.id,
        namespace=component.namespace,
        name=component.name,
        version=component.version,
        created=component.created_at,
        modified=modified or component.updated_at,
        attributes=component.attributes,
    )


async def component(
    db: AsyncSession, repository: Repository, component_id: uuid.UUID, *, unlisted: frozenset[str]
) -> tuple[ComponentSummary, list[Child]] | None:
    """One component and its files, in path order, or None if it is not one to show."""
    found = await db.scalar(
        select(Component).where(Component.id == component_id, *_listed(repository, unlisted))
    )
    if found is None:
        return None
    rows = await db.execute(
        select(Asset.path, Blob.size, Asset.updated_at)
        .join(Blob, Blob.id == Asset.blob_id)
        .where(Asset.component_id == found.id)
        .order_by(Asset.path)
    )
    reference = _ref(found)
    files = [
        Child(path.rpartition("/")[2], path, "file", size, modified, reference)
        for path, size, modified in rows
    ]
    newest = max((child.modified for child in files), default=None)
    return _summary(found, newest), files


async def paths_under(
    db: AsyncSession, repository: Repository, folder: str, *, after: str = "", limit: int
) -> list[str]:
    """The paths of the files under a folder, in order, starting after `after`."""
    prefix = f"{folder}/"
    rows = await db.scalars(
        select(Asset.path)
        .where(
            Asset.repository_id == repository.id,
            Asset.path > (after or prefix),
            Asset.path < prefix[:-1] + _AFTER_SLASH,
        )
        .order_by(Asset.path)
        .limit(limit)
    )
    return list(rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_browse.py tests/test_migrations.py -q`
Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/migrations backend/src/megooarti/repositories backend/tests/repositories/test_browse.py
git commit -m "feat(repositories): walk a repository as folders, with paths in byte order"
```

---

### Task 2: The content API: repositories, folders, files and components

**Files:**
- Create: `backend/src/megooarti/repositories/content_api.py`
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/service.py`
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Modify: `backend/src/megooarti/security/authentication.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `backend/tests/test_route_guards.py`
- Test: `backend/tests/repositories/test_content_api.py`
- Test: `backend/tests/repositories/maven/test_content.py`
- Test: `backend/tests/repositories/docker/test_content.py`

**Interfaces:**
- Consumes: everything Task 1 produces; `service.get_repository`, `service.member_names`; `authorize`, `current_principal`, `Principal.allows`; `get_format`; `Page`, `PageParams`, `page`; `normalise_path`; `get_setting`.
- Produces:
  - `await authentication.require_caller(principal) -> Principal`: a dependency.
  - `await service.all_repositories(db) -> list[Repository]`.
  - `Format.unlisted_namespaces: frozenset[str]` and `Format.download_path(repository: str, path: str) -> str | None`.
  - The routes `GET /api/v1/content`, `/content/{repository}`, `/content/{repository}/tree`, `/content/{repository}/asset`, `/content/{repository}/components` and `/content/{repository}/components/{component_id}`.
  - In `content_api.py`, for Task 3: `router`, `_holding(db, name, caller)`, `_permission(repository, action)`, `_handler(repository)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_api.py`:

```python
"""The content API: what repositories hold, for the people who use them."""

import hashlib

import pytest

from megooarti.repositories import service
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code

CONTENT = "/api/v1/content"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


@pytest.fixture
async def reader(make_user, db) -> dict[str, str]:
    """May browse the repository `files`, and nothing else."""
    await roles.create_role(db, "browsers", "", ["repository:raw:files:browse"], [])
    await db.commit()
    await make_user("reader", roles=["browsers"])
    return basic("reader", PASSWORD)


async def put(client, headers, path: str, data: bytes | None = None, repository: str = "files"):
    sent = path.encode() if data is None else data
    response = await client.put(f"/repository/{repository}/{path}", content=sent, headers=headers)
    assert response.status_code == 201, response.text


async def create(db, name: str, **settings):
    made = await service.create_repository(
        db,
        name=name,
        format=settings.pop("format", "raw"),
        type=settings.pop("type", "hosted"),
        online=True,
        blob_store="default",
        **settings,
    )
    await db.commit()
    return made


async def test_the_repositories_a_caller_may_browse_are_listed(client, files, root, reader, db):
    await create(db, "private")
    await create(db, "mirror", type="proxy", proxy={"remote_url": "https://remote.test/files"})
    await create(db, "all", type="group", group={"members": ["files", "mirror"]})

    everything = await client.get(CONTENT, headers=root)
    some = await client.get(CONTENT, headers=reader)
    one = await client.get(f"{CONTENT}/files", headers=reader)
    hidden = await client.get(f"{CONTENT}/private", headers=reader)
    absent = await client.get(f"{CONTENT}/nothing", headers=reader)

    assert [item["name"] for item in everything.json()["items"]] == [
        "all",
        "files",
        "mirror",
        "private",
    ]
    assert everything.json()["total"] == 4
    group = everything.json()["items"][0]
    assert (group["type"], group["members"]) == ("group", ["files", "mirror"])
    assert some.json()["items"] == [one.json()]
    assert one.json() == {
        "name": "files",
        "format": "raw",
        "type": "hosted",
        "online": True,
        "url": "https://test/repository/files/",
        "members": None,
    }
    assert (hidden.status_code, error_code(hidden)) == (403, "forbidden")
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_the_list_is_paged(client, root, db):
    for name in ("a", "b", "c"):
        await create(db, name)

    page = await client.get(CONTENT, params={"limit": 2, "offset": 1}, headers=root)

    assert [item["name"] for item in page.json()["items"]] == ["b", "c"]
    assert (page.json()["total"], page.json()["limit"], page.json()["offset"]) == (3, 2, 1)


async def test_addresses_are_those_of_the_public_address(client, files, root, db):
    await set_setting(db, "base_url", "https://repo.example.com/")
    await db.commit()
    await put(client, root, "docs/guide.md")

    listed = await client.get(f"{CONTENT}/files", headers=root)
    detail = await client.get(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )

    assert listed.json()["url"] == "https://repo.example.com/repository/files/"
    assert detail.json()["download"] == "https://repo.example.com/repository/files/docs/guide.md"


async def test_a_folder_is_listed_with_its_files_and_folders(client, files, root):
    for path in ("readme.txt", "docs/guide.md", "docs/api/index.html"):
        await put(client, root, path)

    top = await client.get(f"{CONTENT}/files/tree", headers=root)
    docs = await client.get(f"{CONTENT}/files/tree", params={"path": "docs/"}, headers=root)

    assert [(item["kind"], item["name"]) for item in top.json()["items"]] == [
        ("folder", "docs"),
        ("file", "readme.txt"),
    ]
    assert top.json()["next"] is None
    folder, file = docs.json()["items"]
    assert folder == {
        "name": "api",
        "path": "docs/api",
        "kind": "folder",
        "size": None,
        "modified": None,
        "component": None,
    }
    assert (file["path"], file["size"]) == ("docs/guide.md", len(b"docs/guide.md"))
    assert file["component"]["name"] == "guide.md"


async def test_a_folder_is_read_page_by_page(client, files, root):
    for number in range(7):
        await put(client, root, f"logs/day-{number}.txt")

    first = await client.get(
        f"{CONTENT}/files/tree", params={"path": "logs", "limit": 3}, headers=root
    )
    names, following = [item["name"] for item in first.json()["items"]], first.json()["next"]
    while following:
        more = await client.get(
            f"{CONTENT}/files/tree",
            params={"path": "logs", "limit": 3, "after": following},
            headers=root,
        )
        names += [item["name"] for item in more.json()["items"]]
        following = more.json()["next"]

    assert names == [f"day-{number}.txt" for number in range(7)]


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"path": "nothing"}, 404, "not_found"),
        ({"path": "readme.txt"}, 404, "not_found"),  # a file is not a folder
        ({"path": "../etc"}, 400, "invalid_path"),
        ({"path": "a//b"}, 400, "invalid_path"),
        ({"after": "nonsense"}, 422, "validation_error"),
        ({"limit": 0}, 422, "validation_error"),
        ({"limit": 201}, 422, "validation_error"),
    ],
)
async def test_what_cannot_be_listed(client, files, root, params, status, code):
    await put(client, root, "readme.txt")

    response = await client.get(f"{CONTENT}/files/tree", params=params, headers=root)

    assert (response.status_code, error_code(response)) == (status, code)


async def test_an_empty_repository_has_an_empty_root(client, files, root):
    response = await client.get(f"{CONTENT}/files/tree", headers=root)

    assert response.json() == {"items": [], "next": None}


async def test_everything_about_a_file_is_told(client, files, root):
    data = b"the guide"
    await put(client, root, "docs/guide.md", data)
    await client.get("/repository/files/docs/guide.md", headers=root)

    response = await client.get(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )
    missing = await client.get(f"{CONTENT}/files/asset", params={"path": "docs"}, headers=root)
    unnamed = await client.get(f"{CONTENT}/files/asset", headers=root)

    detail = response.json()
    assert (detail["path"], detail["size"]) == ("docs/guide.md", len(data))
    assert detail["sha256"] == hashlib.sha256(data).hexdigest()
    assert detail["sha512"] == hashlib.sha512(data).hexdigest()
    assert detail["sha1"] == hashlib.sha1(data).hexdigest()
    assert detail["md5"] == hashlib.md5(data).hexdigest()
    assert (detail["blob_store"], detail["created_by"]) == ("default", "root")
    assert detail["created"] and detail["modified"] and detail["last_downloaded"]
    assert detail["last_verified"] is None  # only a proxy's file was ever verified
    assert detail["download"] == "https://test/repository/files/docs/guide.md"
    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert (unnamed.status_code, error_code(unnamed)) == (422, "validation_error")


async def test_the_components_of_a_repository_are_listed_and_opened(client, files, root):
    for path in ("docs/guide.md", "docs/intro.md", "readme.txt"):
        await put(client, root, path)

    listed = await client.get(f"{CONTENT}/files/components", headers=root)
    some = await client.get(
        f"{CONTENT}/files/components", params={"namespace": "docs"}, headers=root
    )
    one = await client.get(
        f"{CONTENT}/files/components",
        params={"namespace": "docs", "name": "intro.md"},
        headers=root,
    )
    opened = await client.get(
        f"{CONTENT}/files/components/{one.json()['items'][0]['id']}", headers=root
    )
    absent = await client.get(
        f"{CONTENT}/files/components/00000000-0000-0000-0000-000000000000", headers=root
    )

    assert listed.json()["total"] == 3
    assert [item["name"] for item in some.json()["items"]] == ["guide.md", "intro.md"]
    detail = opened.json()
    assert (detail["namespace"], detail["name"], detail["version"]) == ("docs", "intro.md", "")
    assert [file["path"] for file in detail["files"]] == ["docs/intro.md"]
    assert detail["created"] and detail["modified"]
    assert (absent.status_code, error_code(absent)) == (404, "not_found")


async def test_a_component_is_found_only_in_its_own_repository(client, files, root, db):
    await create(db, "other")
    await put(client, root, "docs/guide.md")
    listed = await client.get(f"{CONTENT}/files/components", headers=root)

    elsewhere = await client.get(
        f"{CONTENT}/other/components/{listed.json()['items'][0]['id']}", headers=root
    )

    assert elsewhere.status_code == 404


async def test_a_group_lists_its_members_and_holds_nothing(client, files, root, db):
    await create(db, "all", type="group", group={"members": ["files"]})

    view = await client.get(f"{CONTENT}/all", headers=root)
    attempts = [
        await client.get(f"{CONTENT}/all/tree", headers=root),
        await client.get(f"{CONTENT}/all/asset", params={"path": "x"}, headers=root),
        await client.get(f"{CONTENT}/all/components", headers=root),
    ]

    assert view.json()["members"] == ["files"]
    for response in attempts:
        assert (response.status_code, error_code(response)) == (409, "not_browsable")


async def test_a_proxy_is_browsed_for_what_it_has_cached(client, mirror, fake_remote, root):
    fake_remote.files["files/lib/a.bin"] = b"from the remote"
    await client.get("/repository/mirror/lib/a.bin", headers=root)

    tree = await client.get(f"{CONTENT}/mirror/tree", params={"path": "lib"}, headers=root)
    detail = await client.get(f"{CONTENT}/mirror/asset", params={"path": "lib/a.bin"}, headers=root)

    assert [item["name"] for item in tree.json()["items"]] == ["a.bin"]
    assert detail.json()["created_by"] == "proxy"
    assert detail.json()["last_verified"] is not None


READS = [
    ("", {}),
    ("/files", {}),
    ("/files/tree", {}),
    ("/files/asset", {"path": "docs/guide.md"}),
    ("/files/components", {}),
]


@pytest.mark.parametrize(("path", "params"), READS)
async def test_seeing_needs_browse_and_nothing_else(
    client, files, root, reader, make_user, db, path, params
):
    await put(client, root, "docs/guide.md")
    await roles.create_role(db, "downloaders", "", ["repository:raw:files:read"], [])
    await db.commit()
    await make_user("downloader", roles=["downloaders"])
    downloader = basic("downloader", PASSWORD)

    allowed = await client.get(CONTENT + path, params=params, headers=reader)
    only_reads = await client.get(CONTENT + path, params=params, headers=downloader)
    nobody = await client.get(CONTENT + path, params=params)
    download = await client.get("/repository/files/docs/guide.md", headers=reader)

    assert allowed.status_code == 200
    if path:
        assert (only_reads.status_code, error_code(only_reads)) == (403, "forbidden")
    else:
        assert only_reads.json()["items"] == []  # the list leaves out what may not be browsed
    assert (nobody.status_code, error_code(nobody)) == (401, "unauthorized")
    assert download.status_code == 403  # browsing is not downloading


async def test_anyone_browses_what_the_anonymous_user_may(client, files, root, db):
    await create(db, "private")
    await put(client, root, "docs/guide.md")
    await roles.create_role(db, "public", "", ["repository:raw:files:browse"], [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    listed = await client.get(CONTENT)
    tree = await client.get(f"{CONTENT}/files/tree")
    hidden = await client.get(f"{CONTENT}/private/tree")

    assert [item["name"] for item in listed.json()["items"]] == ["files"]
    assert tree.status_code == 200
    assert hidden.status_code == 401  # nobody is signed in, so the answer is to sign in


async def test_someone_who_must_change_their_password_sees_nothing_yet(client, files, make_user):
    await make_user("fresh", roles=["admin"], must_change_password=True)

    response = await client.get(CONTENT, headers=basic("fresh", PASSWORD))

    assert (response.status_code, error_code(response)) == (403, "password_change_required")
```

`backend/tests/repositories/maven/test_content.py`:

```python
"""A Maven repository through the content API."""

CONTENT = "/api/v1/content/releases"
VERSION = "com/acme/app/1.0"


async def deploy(client, root, *paths: str) -> None:
    for path in paths:
        response = await client.put(
            f"/repository/releases/{path}", content=path.encode(), headers=root
        )
        assert response.status_code == 201, response.text


async def test_an_artifact_is_a_component_with_its_files(client, releases, root):
    await deploy(client, root, f"{VERSION}/app-1.0.jar", f"{VERSION}/app-1.0.pom")
    await deploy(client, root, "com/acme/app/1.1/app-1.1.jar", "com/acme/lib/2.0/lib-2.0.jar")

    listed = await client.get(f"{CONTENT}/components", headers=root)
    versions = await client.get(
        f"{CONTENT}/components", params={"namespace": "com.acme", "name": "app"}, headers=root
    )
    first = next(item for item in versions.json()["items"] if item["version"] == "1.0")
    opened = await client.get(f"{CONTENT}/components/{first['id']}", headers=root)
    tree = await client.get(f"{CONTENT}/tree", params={"path": VERSION}, headers=root)

    named = [(item["namespace"], item["name"], item["version"]) for item in listed.json()["items"]]
    assert named == [
        ("com.acme", "app", "1.1"),
        ("com.acme", "app", "1.0"),
        ("com.acme", "lib", "2.0"),
    ]
    assert [file["name"] for file in opened.json()["files"]] == ["app-1.0.jar", "app-1.0.pom"]
    # What Maven computes when it is asked (checksums, metadata) is not a stored file.
    assert [item["name"] for item in tree.json()["items"]] == ["app-1.0.jar", "app-1.0.pom"]
    assert tree.json()["items"][0]["component"]["version"] == "1.0"
```

`backend/tests/repositories/docker/test_content.py`:

```python
"""A Docker repository through the content API."""

from tests.repositories.docker.conftest import digest_of, layer, push_image

CONTENT = "/api/v1/content/images"


async def test_a_registry_is_given_as_a_host_and_a_name(client, images, root):
    view = await client.get(CONTENT, headers=root)

    assert view.json()["url"] == "test/images"


async def test_tags_are_the_components_and_everything_is_in_the_tree(client, images, root):
    manifest = await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "team/app", "2.0", "one", "two")
    digest = digest_of(manifest)

    listed = await client.get(f"{CONTENT}/components", headers=root)
    top = await client.get(f"{CONTENT}/tree", headers=root)
    manifests = await client.get(
        f"{CONTENT}/tree", params={"path": "manifests/team/app"}, headers=root
    )
    untagged = manifests.json()["items"][0]["component"]["id"]
    hidden = await client.get(f"{CONTENT}/components/{untagged}", headers=root)

    named = [(item["name"], item["version"]) for item in listed.json()["items"]]
    assert sorted(named) == [("team/app", "1.0"), ("team/app", "2.0")]  # no digests among them
    assert [item["name"] for item in top.json()["items"]] == ["blobs", "manifests", "tags"]
    assert digest in [item["name"] for item in manifests.json()["items"]]
    assert hidden.status_code == 404  # a manifest's component is the registry's own


async def test_what_is_stored_is_fetched_through_the_registry(client, images, root):
    manifest = await push_image(client, root, "team/app", "1.0", "one")
    digest = digest_of(manifest)

    async def download(path: str) -> str | None:
        response = await client.get(f"{CONTENT}/asset", params={"path": path}, headers=root)
        return response.json()["download"]

    assert await download("tags/team/app/1.0") == "https://test/v2/images/team/app/manifests/1.0"
    by_digest = await download(f"manifests/team/app/{digest}")
    assert by_digest == f"https://test/v2/images/team/app/manifests/{digest}"
    # A layer is fetched as part of an image: by itself it belongs to none.
    assert await download(f"blobs/{digest_of(layer('one'))}") is None
    fetched = await client.get(by_digest.removeprefix("https://test"), headers=root)
    assert fetched.content == manifest
```

In `backend/tests/test_route_guards.py`:

After

```python
    assert {"/v2/", "/v2/token", "/v2/_catalog", "/v2/{name}/{path:path}"} <= paths
```

add

```python
    assert {"/api/v1/content", "/api/v1/content/{repository}/tree"} <= paths
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_api.py tests/repositories/maven/test_content.py tests/repositories/docker/test_content.py tests/test_route_guards.py -q`
Expected: 28 failed, 5 passed. The failures are `404` where a route is expected.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/security/authentication.py`:

Before

```python
def require_interactive(
```

add

```python
async def require_caller(
    principal: Principal | None = Depends(current_principal),
) -> Principal:
    """Dependency: somebody is calling, signed in or anonymous.

    For a route whose answer depends on what the caller may do, such as a list that
    leaves out what they may not see. What they may do is for the route to check.
    """
    if principal is None:
        raise unauthorized()
    _refuse_pending_password_change(principal)
    return principal
```

In `backend/src/megooarti/repositories/service.py`:

Before

```python
async def repositories_of(db: AsyncSession, format: str) -> list[Repository]:
```

add

```python
async def all_repositories(db: AsyncSession) -> list[Repository]:
    """Every repository, in name order."""
    return list(await db.scalars(select(Repository).order_by(Repository.name_key)))
```

In `backend/src/megooarti/repositories/formats.py`:

After

```python
    remote_signs_in: bool = False
```

add

```python
    # Namespaces whose components are the format's own bookkeeping. They are not
    # listed as components and not found by search.
    unlisted_namespaces: frozenset[str] = frozenset()
```

Before

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        """The content type to record for a file: an upload, or one a proxy fetched.
```

add

```python
    def download_path(self, repository: str, path: str) -> str | None:
        """Where a stored file is fetched, from the root of the site.

        None for a file that has no address of its own.
        """
        return f"/repository/{repository}/{quote(path, safe='/')}"
```

In `backend/src/megooarti/repositories/docker/format.py`:

After

```python
    remote_signs_in = True
```

add

```python
    unlisted_namespaces = frozenset({names.MANIFESTS})

    def download_path(self, repository: str, path: str) -> str | None:
        """A tag and a manifest are fetched through the registry. A blob is an image's part."""
        named = names.tag_of(path) or names.manifest_of(path)
        if named is None:
            return None
        return f"/v2/{repository}/{named[0]}/manifests/{named[1]}"
```

`backend/src/megooarti/repositories/content_api.py`:

```python
"""The content API: what the repositories hold, for the people who use them.

`/api/v1/repositories` configures repositories and is an administrator's. This is for
everyone else: which repositories there are to use, what is in them as folders, files
and components, and removing things. Seeing anything needs `browse` on the repository;
downloading goes through the content route and needs `read`, as it always has.
"""

import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import browse, service
from megooarti.repositories.formats import Format, get_format
from megooarti.repositories.models import Repository
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import Principal, authorize, require_caller
from megooarti.system.settings_store import get_setting

router = APIRouter(prefix="/content", tags=["content"])


class RepositoryView(BaseModel):
    name: str
    format: str
    type: str
    online: bool
    url: str  # what a client is given: an address, or for a registry a host and a name
    members: list[str] | None = None  # a group's, in the order they are tried


class ComponentRef(BaseModel):
    id: uuid.UUID
    namespace: str
    name: str
    version: str


class Entry(BaseModel):
    name: str
    path: str
    kind: str  # "folder" or "file"
    size: int | None = None
    modified: datetime | None = None
    component: ComponentRef | None = None


class Listing(BaseModel):
    items: list[Entry]
    next: str | None  # give it as `after` for what follows; null at the end


class AssetView(BaseModel):
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
    download: str | None  # where the file is fetched, if it has an address of its own


class ComponentView(ComponentRef):
    created: datetime
    modified: datetime


class ComponentDetail(ComponentView):
    files: list[Entry]


def _permission(repository: Repository, action: str) -> str:
    return f"repository:{repository.format}:{repository.name}:{action}"


async def _base(request: Request, db: AsyncSession) -> str:
    """The public address of this server, without a slash at its end."""
    return (await get_setting(db, "base_url") or str(request.base_url)).rstrip("/")


def _handler(repository: Repository) -> Format:
    handler = get_format(repository.format)
    if handler is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return handler


async def _view(db: AsyncSession, repository: Repository, base: str) -> RepositoryView:
    handler = get_format(repository.format)
    if handler is not None and handler.served_at == "registry":
        # A container client is given a host and a name, not an address.
        url = f"{urlsplit(base).netloc}/{repository.name}"
    else:
        url = f"{base}/repository/{repository.name}/"
    members = None
    if repository.type == "group":
        members = await service.member_names(db, repository)
    return RepositoryView(
        name=repository.name,
        format=repository.format,
        type=repository.type,
        online=repository.online,
        url=url,
        members=members,
    )


async def _repository(
    db: AsyncSession, name: str, caller: Principal, action: str = "browse"
) -> Repository:
    """The repository, if the caller may do this to it. Raises 404, 401 or 403."""
    repository = await service.get_repository(db, name)
    if repository is None:
        raise ApiError(404, "not_found", "No such repository.")
    authorize(caller, _permission(repository, action))
    return repository


async def _holding(db: AsyncSession, name: str, caller: Principal) -> Repository:
    """A repository that holds files of its own, which the caller may browse."""
    repository = await _repository(db, name, caller)
    if repository.type == "group":
        raise ApiError(
            409, "not_browsable", "A group holds nothing of its own. Browse its members."
        )
    return repository


def _entry(child: browse.Child) -> Entry:
    return Entry.model_validate(child, from_attributes=True)


@router.get("", response_model=Page[RepositoryView])
async def list_repositories(
    request: Request,
    params: PageParams = Depends(),
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """The repositories the caller may browse."""
    every = await service.all_repositories(db)
    allowed = [found for found in every if caller.allows(_permission(found, "browse"))]
    base = await _base(request, db)
    shown = allowed[params.offset : params.offset + params.limit]
    return page([await _view(db, found, base) for found in shown], len(allowed), params)


@router.get("/{repository}", response_model=RepositoryView)
async def get_repository(
    repository: str,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> RepositoryView:
    found = await _repository(db, repository, caller)
    return await _view(db, found, await _base(request, db))


@router.get("/{repository}/tree", response_model=Listing)
async def list_folder(
    repository: str,
    path: str = "",
    after: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> Listing:
    """What is directly in a folder. An empty `path` is the root of the repository.

    A folder may hold millions of entries, so there is no total: `next` leads on.
    """
    found = await _holding(db, repository, caller)
    folder = path.strip("/")
    if folder:
        normalise_path(folder)
    try:
        items, following = await browse.children(db, found, folder, after=after, limit=limit)
    except browse.BadCursor:
        details = [{"field": "after", "message": "Not something a listing returned."}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None
    if folder and not items and not after:
        raise ApiError(404, "not_found", "No such folder.")
    return Listing(items=[_entry(child) for child in items], next=following)


@router.get("/{repository}/asset", response_model=AssetView)
async def get_asset(
    repository: str,
    path: str,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> AssetView:
    found = await _holding(db, repository, caller)
    detail = await browse.asset(db, found, normalise_path(path))
    if detail is None:
        raise ApiError(404, "not_found", "No such file.")
    address = _handler(found).download_path(found.name, detail.path)
    download = None if address is None else await _base(request, db) + address
    return AssetView.model_validate({**vars(detail), "download": download}, from_attributes=True)


@router.get("/{repository}/components", response_model=Page[ComponentView])
async def list_components(
    repository: str,
    namespace: str | None = None,
    name: str | None = None,
    params: PageParams = Depends(),
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """A repository's components, by namespace and name, the newest first."""
    found = await _holding(db, repository, caller)
    items, total = await browse.components(
        db,
        found,
        unlisted=_handler(found).unlisted_namespaces,
        namespace=namespace,
        name=name,
        limit=params.limit,
        offset=params.offset,
    )
    return page(items, total, params)


@router.get("/{repository}/components/{component_id}", response_model=ComponentDetail)
async def get_component(
    repository: str,
    component_id: uuid.UUID,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> ComponentDetail:
    found = await _holding(db, repository, caller)
    held = await browse.component(
        db, found, component_id, unlisted=_handler(found).unlisted_namespaces
    )
    if held is None:
        raise ApiError(404, "not_found", "No such component.")
    summary, files = held
    return ComponentDetail.model_validate(
        {**vars(summary), "files": [_entry(child) for child in files]}, from_attributes=True
    )
```

In `backend/src/megooarti/main.py`:

After

```python
from megooarti.repositories.api import router as repositories_router
```

add

```python
from megooarti.repositories.content_api import router as content_api_router
```

After

```python
    app.include_router(repositories_router, prefix=API_PREFIX)
```

add

```python
    app.include_router(content_api_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_content_api.py tests/repositories/maven/test_content.py tests/repositories/docker/test_content.py tests/test_route_guards.py -q`
Expected: 33 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories backend/tests/test_route_guards.py
git commit -m "feat(content): an API to see what repositories hold"
```

---

### Task 3: Deleting through the format

**Files:**
- Modify: `backend/src/megooarti/repositories/content_api.py`
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Test: `backend/tests/repositories/test_content_delete.py`
- Test: `backend/tests/repositories/maven/test_content_delete.py`
- Test: `backend/tests/repositories/npm/test_content_delete.py`
- Test: `backend/tests/repositories/pypi/test_content_delete.py`
- Test: `backend/tests/repositories/docker/test_content_delete.py`

**Interfaces:**
- Consumes: `browse.paths_under`, `browse.component` (Task 1); `_holding`, `_permission`, `_handler`, `router` (Task 2); `build_context`, `context.delete`, `context.stat`, `context.lock`, `context.referenced`; npm's `_change_tags` and `documents.effective_tags`; Docker's `_drop`, `_REFERENCES` and `names.manifest_of`.
- Produces:
  - `formats.managed_by_format(reason: str) -> ApiError` (`409`).
  - `await Format.delete_asset(context, path: str) -> bool`, overridden by the npm and Docker formats.
  - The routes `DELETE /api/v1/content/{repository}/asset`, `/content/{repository}/tree` and `/content/{repository}/components/{component_id}`.
  - `content_api._FOLDER_AT_ONCE = 1000`, which a test replaces.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_delete.py`:

```python
"""Deleting through the content API: a file, a component, a folder."""

import pytest

from megooarti.repositories import content_api, service
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

CONTENT = "/api/v1/content"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def put(client, headers, *paths: str, repository: str = "files") -> None:
    for path in paths:
        response = await client.put(
            f"/repository/{repository}/{path}", content=path.encode(), headers=headers
        )
        assert response.status_code == 201, response.text


async def names(client, headers, folder: str = "", repository: str = "files") -> list[str]:
    response = await client.get(
        f"{CONTENT}/{repository}/tree", params={"path": folder}, headers=headers
    )
    return [item["name"] for item in response.json().get("items", [])]


async def test_a_file_is_deleted(client, files, root):
    await put(client, root, "docs/guide.md", "docs/intro.md")

    deleted = await client.delete(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )
    again = await client.delete(
        f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=root
    )
    fetched = await client.get("/repository/files/docs/guide.md", headers=root)

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert (again.status_code, error_code(again)) == (404, "not_found")
    assert fetched.status_code == 404
    assert await names(client, root, "docs") == ["intro.md"]


async def test_a_component_is_deleted_with_its_files(client, files, root):
    await put(client, root, "docs/guide.md", "docs/intro.md")
    listed = await client.get(
        f"{CONTENT}/files/components", params={"name": "guide.md"}, headers=root
    )
    address = f"{CONTENT}/files/components/{listed.json()['items'][0]['id']}"

    deleted = await client.delete(address, headers=root)
    again = await client.delete(address, headers=root)

    assert (deleted.status_code, again.status_code) == (204, 404)
    assert await names(client, root, "docs") == ["intro.md"]


async def test_a_folder_is_deleted_with_everything_under_it(client, files, root):
    await put(client, root, "app/one", "app/deep/two", "app/deep/er/three", "app-old/four", "apple")

    response = await client.delete(f"{CONTENT}/files/tree", params={"path": "app/"}, headers=root)
    nothing = await client.delete(f"{CONTENT}/files/tree", params={"path": "app"}, headers=root)

    assert response.json() == {"deleted": 3, "skipped": 0, "next": None}
    assert nothing.json() == {"deleted": 0, "skipped": 0, "next": None}
    assert await names(client, root) == ["app-old", "apple"]  # its neighbours are untouched


async def test_a_large_folder_is_deleted_in_pieces(client, files, root, monkeypatch):
    monkeypatch.setattr(content_api, "_FOLDER_AT_ONCE", 3)
    await put(client, root, *(f"logs/day-{number}" for number in range(8)), "logs-kept")
    counts, after = [], ""

    while after is not None:
        response = await client.delete(
            f"{CONTENT}/files/tree", params={"path": "logs", "after": after}, headers=root
        )
        counts.append(response.json()["deleted"])
        after = response.json()["next"]

    assert counts == [3, 3, 2]
    assert await names(client, root) == ["logs-kept"]


@pytest.mark.parametrize("path", ["", "/", "a/../b", "a//b"])
async def test_a_folder_to_delete_must_be_named(client, files, root, path):
    await put(client, root, "a/b/c")

    response = await client.delete(f"{CONTENT}/files/tree", params={"path": path}, headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_path")
    assert await names(client, root) == ["a"]


async def test_deleting_needs_delete_whatever_else_one_may_do(client, files, root, make_user, db):
    await put(client, root, "docs/guide.md")
    may = ["repository:raw:files:browse", "repository:raw:files:read", "repository:raw:files:add"]
    await roles.create_role(db, "writers", "", may, [])
    await db.commit()
    await make_user("writer", roles=["writers"])
    writer = basic("writer", PASSWORD)
    listed = await client.get(f"{CONTENT}/files/components", headers=writer)
    component = listed.json()["items"][0]["id"]

    attempts = [
        await client.delete(
            f"{CONTENT}/files/asset", params={"path": "docs/guide.md"}, headers=writer
        ),
        await client.delete(f"{CONTENT}/files/asset", params={"path": "nothing"}, headers=writer),
        await client.delete(f"{CONTENT}/files/tree", params={"path": "docs"}, headers=writer),
        await client.delete(f"{CONTENT}/files/components/{component}", headers=writer),
    ]
    nobody = await client.delete(f"{CONTENT}/files/asset", params={"path": "docs/guide.md"})

    for response in attempts:
        assert (response.status_code, error_code(response)) == (403, "forbidden")
    assert nobody.status_code == 401
    assert await names(client, root, "docs") == ["guide.md"]


async def test_nothing_is_deleted_from_a_read_only_repository(client, root, db):
    frozen = await service.create_repository(
        db, name="frozen", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    await put(client, root, "a/b", repository="frozen")
    frozen.config = {**frozen.config, "hosted": {"deployment_policy": "read_only"}}
    await db.commit()

    file = await client.delete(f"{CONTENT}/frozen/asset", params={"path": "a/b"}, headers=root)
    folder = await client.delete(f"{CONTENT}/frozen/tree", params={"path": "a"}, headers=root)

    for response in (file, folder):
        assert (response.status_code, error_code(response)) == (403, "repository_read_only")
    assert await names(client, root, "a", repository="frozen") == ["b"]


async def test_a_group_has_nothing_to_delete(client, files, root, db):
    await service.create_repository(
        db,
        name="all",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["files"]},
    )
    await db.commit()
    await put(client, root, "docs/guide.md")

    attempts = [
        await client.delete(f"{CONTENT}/all/asset", params={"path": "docs/guide.md"}, headers=root),
        await client.delete(f"{CONTENT}/all/tree", params={"path": "docs"}, headers=root),
    ]

    for response in attempts:
        assert (response.status_code, error_code(response)) == (409, "not_browsable")
    assert await names(client, root, "docs") == ["guide.md"]


async def test_deleting_from_a_proxy_removes_the_cached_copy(client, mirror, fake_remote, root):
    fake_remote.files["files/lib/a.bin"] = b"from the remote"
    await client.get("/repository/mirror/lib/a.bin", headers=root)

    deleted = await client.delete(
        f"{CONTENT}/mirror/asset", params={"path": "lib/a.bin"}, headers=root
    )
    gone = await names(client, root, repository="mirror")
    fake_remote.files["files/lib/a.bin"] = b"what the remote has now"
    again = await client.get("/repository/mirror/lib/a.bin", headers=root)

    assert (deleted.status_code, gone) == (204, [])
    assert again.content == b"what the remote has now"  # fetched again when asked for
```

`backend/tests/repositories/maven/test_content_delete.py`:

```python
"""Deleting from a Maven repository through the content API."""

CONTENT = "/api/v1/content/releases"
APP = "com/acme/app"


async def deploy(client, root, *paths: str) -> None:
    for path in paths:
        response = await client.put(
            f"/repository/releases/{path}", content=path.encode(), headers=root
        )
        assert response.status_code == 201, response.text


async def versions(client, root) -> str:
    response = await client.get(f"/repository/releases/{APP}/maven-metadata.xml", headers=root)
    return response.text if response.status_code == 200 else ""


async def test_a_version_is_deleted_as_a_component_and_the_metadata_follows(client, releases, root):
    await deploy(client, root, f"{APP}/1.0/app-1.0.jar", f"{APP}/1.0/app-1.0.pom")
    await deploy(client, root, f"{APP}/1.1/app-1.1.jar")
    listed = await client.get(f"{CONTENT}/components", params={"name": "app"}, headers=root)
    first = next(item for item in listed.json()["items"] if item["version"] == "1.0")

    deleted = await client.delete(f"{CONTENT}/components/{first['id']}", headers=root)
    metadata = await versions(client, root)
    jar = await client.get(f"/repository/releases/{APP}/1.0/app-1.0.jar", headers=root)
    checksum = await client.get(f"/repository/releases/{APP}/1.0/app-1.0.jar.sha1", headers=root)

    assert deleted.status_code == 204
    assert "<version>1.1</version>" in metadata and "<version>1.0</version>" not in metadata
    assert (jar.status_code, checksum.status_code) == (404, 404)


async def test_one_file_of_a_version_is_deleted_and_the_rest_stays(client, releases, root):
    await deploy(client, root, f"{APP}/1.0/app-1.0.jar", f"{APP}/1.0/app-1.0-sources.jar")

    deleted = await client.delete(
        f"{CONTENT}/asset", params={"path": f"{APP}/1.0/app-1.0-sources.jar"}, headers=root
    )
    tree = await client.get(f"{CONTENT}/tree", params={"path": f"{APP}/1.0"}, headers=root)

    assert deleted.status_code == 204
    assert [item["name"] for item in tree.json()["items"]] == ["app-1.0.jar"]
    assert "<version>1.0</version>" in await versions(client, root)


async def test_an_artifact_is_deleted_as_a_folder(client, releases, root):
    await deploy(client, root, f"{APP}/1.0/app-1.0.jar", f"{APP}/1.1/app-1.1.jar")
    await deploy(client, root, "com/acme/lib/2.0/lib-2.0.jar")

    response = await client.delete(f"{CONTENT}/tree", params={"path": APP}, headers=root)
    left = await client.get(f"{CONTENT}/tree", params={"path": "com/acme"}, headers=root)

    assert response.json() == {"deleted": 2, "skipped": 0, "next": None}
    assert await versions(client, root) == ""
    assert [item["name"] for item in left.json()["items"]] == ["lib"]
```

`backend/tests/repositories/npm/test_content_delete.py`:

```python
"""Deleting from an npm repository through the content API leaves it as `npm unpublish` would."""

from megooarti.repositories.npm import paths
from tests.accounts import error_code
from tests.repositories.npm.conftest import address, publish

CONTENT = "/api/v1/content/npm"


async def delete_file(client, root, path: str):
    return await client.delete(f"{CONTENT}/asset", params={"path": path}, headers=root)


async def test_a_deleted_tarball_is_a_version_that_was_unpublished(client, registry, root):
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "@acme/tool", version)

    deleted = await delete_file(client, root, paths.tarball_path("@acme/tool", "2.0.0"))
    document = (await client.get(address("@acme/tool"), headers=root)).json()
    tarball = await client.get(
        f"/repository/npm/{paths.tarball_path('@acme/tool', '2.0.0')}", headers=root
    )

    assert deleted.status_code == 204
    assert list(document["versions"]) == ["1.0.0"]
    assert document["dist-tags"] == {"latest": "1.0.0"}  # the tag moved off what is gone
    assert tarball.status_code == 404


async def test_deleting_the_last_version_leaves_no_package(client, registry, root):
    await publish(client, root, "tool", "1.0.0")

    await delete_file(client, root, paths.tarball_path("tool", "1.0.0"))
    document = await client.get(address("tool"), headers=root)
    tree = await client.get(f"{CONTENT}/tree", headers=root)

    assert document.status_code == 404
    assert tree.json()["items"] == []  # its dist-tags went with it


async def test_a_version_is_deleted_as_a_component(client, registry, root):
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "tool", version)
    listed = await client.get(f"{CONTENT}/components", params={"name": "tool"}, headers=root)
    newest = next(item for item in listed.json()["items"] if item["version"] == "2.0.0")

    deleted = await client.delete(f"{CONTENT}/components/{newest['id']}", headers=root)
    document = (await client.get(address("tool"), headers=root)).json()

    assert deleted.status_code == 204
    assert (list(document["versions"]), document["dist-tags"]) == (["1.0.0"], {"latest": "1.0.0"})


async def test_what_the_registry_keeps_for_a_package_does_not_go_by_itself(client, registry, root):
    await publish(client, root, "tool", "1.0.0")

    response = await delete_file(client, root, paths.dist_tags_path("tool"))
    missing = await delete_file(client, root, paths.dist_tags_path("other"))
    document = (await client.get(address("tool"), headers=root)).json()

    assert (response.status_code, error_code(response)) == (409, "managed_by_format")
    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert document["dist-tags"] == {"latest": "1.0.0"}


async def test_a_package_is_deleted_as_a_folder(client, registry, root):
    for version in ("1.0.0", "2.0.0"):
        await publish(client, root, "tool", version)
    await publish(client, root, "other", "1.0.0")

    response = await client.delete(f"{CONTENT}/tree", params={"path": "tool"}, headers=root)
    gone = await client.get(address("tool"), headers=root)
    kept = await client.get(address("other"), headers=root)

    assert response.json() == {"deleted": 2, "skipped": 0, "next": None}
    assert (gone.status_code, kept.status_code) == (404, 200)
```

`backend/tests/repositories/pypi/test_content_delete.py`:

```python
"""Deleting from a PyPI repository through the content API."""

from tests.repositories.pypi.conftest import upload

CONTENT = "/api/v1/content/pypi"
WHEEL = "greeter-1.0-py3-none-any.whl"
SDIST = "greeter-1.0.tar.gz"
NEWER = "greeter-2.0-py3-none-any.whl"


async def page(client, root) -> str:
    response = await client.get("/repository/pypi/simple/greeter/", headers=root)
    return response.text if response.status_code == 200 else ""


async def test_a_deleted_file_is_off_its_projects_page(client, index, root):
    for filename in (WHEEL, SDIST, NEWER):
        assert (await upload(client, root, filename)).status_code == 200

    deleted = await client.delete(
        f"{CONTENT}/asset", params={"path": f"packages/greeter/1.0/{SDIST}"}, headers=root
    )
    listed = await page(client, root)

    assert deleted.status_code == 204
    assert WHEEL in listed and NEWER in listed and SDIST not in listed


async def test_a_release_is_deleted_as_a_component(client, index, root):
    for filename in (WHEEL, SDIST, NEWER):
        await upload(client, root, filename)
    found = await client.get(f"{CONTENT}/components", params={"name": "greeter"}, headers=root)
    first = next(item for item in found.json()["items"] if item["version"] == "1.0")

    deleted = await client.delete(f"{CONTENT}/components/{first['id']}", headers=root)
    listed = await page(client, root)

    assert deleted.status_code == 204
    assert NEWER in listed and WHEEL not in listed and SDIST not in listed


async def test_a_project_is_deleted_as_a_folder(client, index, root):
    for filename in (WHEEL, SDIST, NEWER):
        await upload(client, root, filename)

    response = await client.delete(
        f"{CONTENT}/tree", params={"path": "packages/greeter"}, headers=root
    )

    assert response.json() == {"deleted": 3, "skipped": 0, "next": None}
    assert await page(client, root) == ""
```

`backend/tests/repositories/docker/test_content_delete.py`:

```python
"""Deleting from a Docker repository through the content API, as the registry API deletes."""

from sqlalchemy import select

from megooarti.repositories.models import Asset
from tests.accounts import error_code
from tests.repositories.docker.conftest import (
    V2,
    config_for,
    digest_of,
    layer,
    push_blob,
    push_image,
)

CONTENT = "/api/v1/content/images"


async def delete_file(client, root, path: str):
    return await client.delete(f"{CONTENT}/asset", params={"path": path}, headers=root)


async def stored(db) -> set[str]:
    return set(await db.scalars(select(Asset.path)))


async def test_deleting_a_tag_removes_the_tag_alone(client, images, root, db):
    manifest = await push_image(client, root, "team/app", "1.0", "one")

    deleted = await delete_file(client, root, "tags/team/app/1.0")
    by_tag = await client.get(f"{V2}/team/app/manifests/1.0", headers=root)
    by_digest = await client.get(f"{V2}/team/app/manifests/{digest_of(manifest)}", headers=root)

    assert deleted.status_code == 204
    assert (by_tag.status_code, by_digest.content) == (404, manifest)


async def test_deleting_a_manifest_removes_its_tags_and_what_only_it_used(client, images, root, db):
    old = await push_image(client, root, "team/app", "1.0", "base", "old")
    await push_image(client, root, "team/app", "2.0", "base", "new")
    await client.put(
        f"{V2}/team/app/manifests/stable",
        content=old,
        headers={**root, "Content-Type": "application/vnd.oci.image.manifest.v1+json"},
    )

    deleted = await delete_file(client, root, f"manifests/team/app/{digest_of(old)}")
    left = await stored(db)
    tags = await client.get(f"{V2}/team/app/tags/list", headers=root)

    assert deleted.status_code == 204
    assert tags.json()["tags"] == ["2.0"]  # both tags that named it went
    assert f"blobs/{digest_of(layer('old'))}" not in left
    assert f"blobs/{digest_of(config_for('base', 'old'))}" not in left
    assert f"blobs/{digest_of(layer('base'))}" in left  # the other image uses it
    pulled = await client.get(f"{V2}/team/app/manifests/2.0", headers=root)
    assert pulled.status_code == 200


async def test_a_layer_an_image_uses_does_not_go_by_itself(client, images, root, db):
    await push_image(client, root, "team/app", "1.0", "one")
    stray = await push_blob(client, root, "team/app", layer("never used"))

    used = await delete_file(client, root, f"blobs/{digest_of(layer('one'))}")
    unused = await delete_file(client, root, f"blobs/{stray}")

    assert (used.status_code, error_code(used)) == (409, "managed_by_format")
    assert unused.status_code == 204
    left = await stored(db)
    assert f"blobs/{digest_of(layer('one'))}" in left and f"blobs/{stray}" not in left


async def test_a_tag_is_deleted_as_a_component(client, images, root):
    await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "team/app", "2.0", "one")
    listed = await client.get(f"{CONTENT}/components", headers=root)
    first = next(item for item in listed.json()["items"] if item["version"] == "1.0")

    deleted = await client.delete(f"{CONTENT}/components/{first['id']}", headers=root)
    tags = await client.get(f"{V2}/team/app/tags/list", headers=root)

    assert deleted.status_code == 204
    assert tags.json()["tags"] == ["2.0"]


async def test_an_image_is_deleted_as_the_folder_of_its_manifests(client, images, root, db):
    await push_image(client, root, "team/app", "1.0", "one")
    await push_image(client, root, "team/app", "2.0", "two")
    await push_image(client, root, "team/other", "1.0", "three")

    response = await client.delete(
        f"{CONTENT}/tree", params={"path": "manifests/team/app"}, headers=root
    )

    assert response.json() == {"deleted": 2, "skipped": 0, "next": None}
    left = await stored(db)
    assert {path for path in left if "team/app" in path} == set()  # tags too
    assert f"blobs/{digest_of(layer('one'))}" not in left
    assert f"blobs/{digest_of(layer('three'))}" in left
    assert (await client.get(f"{V2}/team/other/manifests/1.0", headers=root)).status_code == 200


async def test_the_blobs_folder_gives_up_only_what_no_image_uses(client, images, root, db):
    await push_image(client, root, "team/app", "1.0", "one")
    stray = await push_blob(client, root, "team/app", layer("never used"))

    response = await client.delete(f"{CONTENT}/tree", params={"path": "blobs"}, headers=root)

    assert response.json() == {"deleted": 1, "skipped": 2, "next": None}
    assert f"blobs/{stray}" not in await stored(db)
    assert (await client.get(f"{V2}/team/app/manifests/1.0", headers=root)).status_code == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_delete.py tests/repositories/maven/test_content_delete.py tests/repositories/npm/test_content_delete.py tests/repositories/pypi/test_content_delete.py tests/repositories/docker/test_content_delete.py -q`
Expected: 29 failed, with `405` where a delete is expected.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`:

Before

```python
    def download_path(self, repository: str, path: str) -> str | None:
```

add

```python
    async def delete_asset(self, context: "RepositoryContext", path: str) -> bool:
        """Delete a stored file of a hosted repository as this format's own client would.

        False if there is nothing at the path. Raises `managed_by_format` for a file
        the format keeps itself, which goes with what it describes. The generic format
        removes the file and nothing else. The caller has checked `delete`, and commits.
        """
        return await context.delete(path)
```

Before

```python
class Format:
```

add

```python
def managed_by_format(reason: str) -> ApiError:
    """The refusal to delete, on its own, a file that a format keeps itself."""
    return ApiError(409, "managed_by_format", reason)
```

In `backend/src/megooarti/repositories/npm/format.py`:

Replace

```python
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
```

with

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    managed_by_format,
    register,
)
```

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A tarball belongs to its package and version. Nothing else is part of one."""
```

add

```python
    async def delete_asset(self, context: RepositoryContext, path: str) -> bool:
        """A tarball goes as `npm unpublish <name>@<version>` removes it.

        Nothing else is deleted by itself.
        """
        parsed = paths.classify(path)
        if parsed.kind != "tarball":
            if await context.stat(path) is None:
                return False
            reason = "A package's dist-tags are the registry's. They go with its last version."
            raise managed_by_format(reason)
        if not await context.delete(path):
            return False
        # A tag that named the version moves to what is left, or goes with the last one.
        await _change_tags(context, parsed.package, documents.effective_tags)
        return True
```

In `backend/src/megooarti/repositories/docker/format.py`:

Replace

```python
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
```

with

```python
from megooarti.repositories.formats import (
    ComponentKey,
    Format,
    Serve,
    managed_by_format,
    register,
)
```

Before

```python
    def download_path(self, repository: str, path: str) -> str | None:
        """A tag and a manifest are fetched through the registry. A blob is an image's part."""
```

add

```python
    async def delete_asset(self, context: RepositoryContext, path: str) -> bool:
        """A tag goes alone. A manifest goes as by its digest in the registry API.

        A blob goes only if no manifest refers to it: otherwise it is part of an image.
        """
        held = names.manifest_of(path)
        if held is None and not path.startswith("blobs/"):
            return await context.delete(path)
        await context.lock(_REFERENCES)
        if held is not None:
            return await _drop(context, *held)
        if await context.referenced([path]):
            reason = "An image uses this layer. It goes when the images that use it are deleted."
            raise managed_by_format(reason)
        return await context.delete(path)
```

In `backend/src/megooarti/repositories/content_api.py`:

After

```python
from megooarti.repositories import browse, service
```

add

```python
from megooarti.repositories.content import RepositoryContext, build_context
```

Add to the end of `backend/src/megooarti/repositories/content_api.py`:

```python
# --- Deleting -------------------------------------------------------------------------

# How many files one request to delete a folder goes through. The caller repeats.
_FOLDER_AT_ONCE = 1000


class FolderDeleted(BaseModel):
    deleted: int
    skipped: int  # files the format keeps itself: they go with what they describe
    next: str | None  # give it as `after` to go on; null once the folder has been gone through


async def _deletable(
    request: Request, db: AsyncSession, name: str, caller: Principal
) -> RepositoryContext:
    """A context for deleting from a repository that holds files. Raises as `_holding` does."""
    repository = await _holding(db, name, caller)
    authorize(caller, _permission(repository, "delete"))
    return await build_context(db, request.app.state.settings, repository, caller)


async def _delete_file(context: RepositoryContext, path: str) -> bool:
    """Delete one stored file as its format would. False if there is none."""
    if context.repository.type == "proxy":
        # Only ever a cached copy. It is fetched again when it is next asked for.
        return await context.delete(path)
    return await _handler(context.repository).delete_asset(context, path)


@router.delete("/{repository}/asset", status_code=204)
async def delete_asset(
    repository: str,
    path: str,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a file, as deleting it with its format's own client would."""
    context = await _deletable(request, db, repository, caller)
    if not await _delete_file(context, normalise_path(path)):
        raise ApiError(404, "not_found", "No such file.")
    await db.commit()


@router.delete("/{repository}/tree", response_model=FolderDeleted)
async def delete_folder(
    repository: str,
    path: str,
    request: Request,
    after: str = "",
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> FolderDeleted:
    """Delete what is under a folder, a bounded number of files at a time.

    While `next` is not null there may be more: repeat the request with it as `after`.
    """
    context = await _deletable(request, db, repository, caller)
    folder = normalise_path(path.strip("/"))
    found = await browse.paths_under(
        db, context.repository, folder, after=after, limit=_FOLDER_AT_ONCE
    )
    deleted = skipped = 0
    for held in found:
        try:
            deleted += await _delete_file(context, held)  # 0 if it went with an earlier one
        except ApiError as error:
            if error.code != "managed_by_format":
                raise
            skipped += 1
    await db.commit()
    following = found[-1] if len(found) == _FOLDER_AT_ONCE else None
    return FolderDeleted(deleted=deleted, skipped=skipped, next=following)


@router.delete("/{repository}/components/{component_id}", status_code=204)
async def delete_component(
    repository: str,
    component_id: uuid.UUID,
    request: Request,
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> None:
    """Delete a component: every file of it, each as its format would delete it."""
    context = await _deletable(request, db, repository, caller)
    unlisted = _handler(context.repository).unlisted_namespaces
    held = await browse.component(db, context.repository, component_id, unlisted=unlisted)
    if held is None:
        raise ApiError(404, "not_found", "No such component.")
    for file in held[1]:
        await _delete_file(context, file.path)
    await db.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: the command of Step 2.
Expected: 29 passed.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2402 passed, 1 skipped; no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(content): delete a file, a component or a folder as its format would"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-11-browse-search-upload-design.md`

**Interfaces:**
- Consumes: the content API as built.
- Produces: a section of the README, and a spec that says what was built.

- [ ] **Step 1: Document browsing and deleting**

In `README.md`:

Replace

```markdown
- **Permissions** are `repository:<format>:<name>:<action>`, where the action is `read`,
  `add` (a new path), `edit` (replace a path) or `delete`. For example
  `repository:raw:files:read`, or `repository:raw` for everything on every Raw repository.
```

with

```markdown
- **Permissions** are `repository:<format>:<name>:<action>`, where the action is `browse`
  (see what is there), `read` (download), `add` (a new path), `edit` (replace a path) or
  `delete`. For example `repository:raw:files:read`, or `repository:raw` for everything
  on every Raw repository.
```

After

```markdown
Reading through a group needs `read` on the group only, for example
`repository:docker:docker-all:read`.
```

add

````markdown
## Browsing and deleting

What the repositories hold can be looked at and removed without a package client,
through `/api/v1/content`. It is what the web UI will use.

```bash
# The repositories you may browse, and one of them
curl -u alice https://repo.example.com/api/v1/content
curl -u alice https://repo.example.com/api/v1/content/maven-releases

# A folder, a file, and the components (packages and their versions)
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/tree?path=com/acme'
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/asset?path=com/acme/app/1.0/app-1.0.jar'
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/components?namespace=com.acme&name=app'

# Delete a file, a component, or everything under a folder
curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/asset?path=com/acme/app/1.0/app-1.0-sources.jar'
curl -u alice -X DELETE https://repo.example.com/api/v1/content/maven-releases/components/<id>
curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/tree?path=com/acme/app'
```

- **Seeing needs `browse`** on the repository; downloading needs `read`, and deleting
  `delete`. The list leaves out what you may not browse.
- **A folder** (`tree`) lists what is directly in it, in the byte order of the names,
  each entry a `folder` or a `file`. It is read a page at a time: give the `next` of
  one answer as `after` in the following request. There is no total, because a
  folder can hold millions of entries and counting them would mean reading them. An
  empty `path` is the root.
- **A file** (`asset`) is described with its size, content type, four checksums, blob
  store, who stored it and when, when it was last downloaded, the component it
  belongs to, and the address to download it from.
- **A component** is a package version: a Maven artifact version, an npm package
  version, a PyPI release, a Docker tag. In a Raw repository every file is one.
  `components/<id>` lists its files.
- **Deleting goes through the format**, so the repository is left as the format's own
  client would leave it. A deleted npm tarball is an unpublished version, and
  dist-tags that named it move. A deleted Docker manifest takes its tags and the
  layers nothing else uses with it; a deleted tag goes alone. Maven's metadata and
  checksums and PyPI's pages are computed from the files, so they follow by
  themselves.
- **What a format keeps for itself cannot be deleted on its own** (`409
  managed_by_format`): an npm package's dist-tags, a Docker layer that an image uses.
- **Deleting a folder** removes the files under it through the same rules, at most
  1,000 in one request. The answer says how many were `deleted`, how many were
  `skipped` because the format keeps them, and gives a `next` to repeat the request
  with while there may be more.
- **A proxy** is browsed for what it has cached, and deleting from it removes the
  cached copy: it is fetched again when it is next asked for.
- **A group** holds nothing of its own. It lists its `members`, which are browsed one
  by one.
````

- [ ] **Step 2: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-11-browse-search-upload-design.md`:

Replace

```markdown
| D9 | Each component carries its search text in a column, written when the component is stored and indexed with trigrams (`pg_trgm`). A component with no search text is not listed and not found. | "Contains" needs a trigram index to stay fast. One column also gives one place to say that something is not for listing. |
| D10 | A Docker manifest without a tag is seen in the folder tree only. Tags are what is listed as components and found by search. | Chosen by the product owner. Plan 7c made every manifest a component so that a repository knows which images it has; those components have no search text (D9). |
```

with

```markdown
| D9 | Each component carries its search text in a column, written when the component is stored and indexed with trigrams (`pg_trgm`). | "Contains" needs a trigram index to stay fast. |
| D10 | A Docker manifest without a tag is seen in the folder tree only. Tags are what is listed as components and found by search. A format names the namespaces whose components are its own bookkeeping; they are neither listed nor found. | Chosen by the product owner. Plan 7c made every manifest a component, in a namespace of its own, so that a repository knows which images it has. |
```

Replace

```markdown
- **Deleting through the format.** Two hooks on a format, `delete_asset` and `delete_component`. The generic format deletes the file, or every file of the component.
- **Which repositories a caller may browse.** The security package answers this for a principal and a list of repositories, so that no route reads permission patterns.
```

with

```markdown
- **Deleting through the format.** A hook on a format, `delete_asset`. The generic format deletes the file. A component is deleted by deleting each of its files this way.
- **Somebody is calling.** A dependency for a route whose answer depends on what the caller may do: it needs a caller, signed in or anonymous, and leaves what they may do to the route, which asks the principal.
- **What a format keeps for itself, and where a file is fetched.** A format names the namespaces of components that are not for listing, and says at which address a stored file is downloaded.
```

Replace

```markdown
| `GET /content/{repository}/tree?path=&after=&limit=` | The children of a folder, folders first: `name`, `path`, `kind` (`folder` or `file`), and for a file `size`, `modified` and the `component` it belongs to. `next` is the cursor for the following page, or null. An empty `path` is the root. A group has no tree (`409`) |
```

with

```markdown
| `GET /content/{repository}/tree?path=&after=&limit=` | The children of a folder, in the byte order of their names: `name`, `path`, `kind` (`folder` or `file`), and for a file `size`, `modified` and the `component` it belongs to. A name that is both a file and a folder is listed as each. `next` is the cursor for the following page, or null. An empty `path` is the root. A group has no tree (`409`) |
```

Replace

```markdown
| `DELETE /content/{repository}/tree?path=` | Delete what is under a folder (D6). `200` with `deleted` and `more` |
```

with

```markdown
| `DELETE /content/{repository}/tree?path=&after=` | Delete what is under a folder (D6). `200` with `deleted`, `skipped` (files the format keeps itself) and `next`, which is given as `after` to go on, or is null. The root cannot be deleted this way |
```

Replace

```markdown
| Raw | Nothing more | A file is not a component |
| Maven | Its checksum files go with it; the artifact's and the version's metadata are written again. Metadata and checksum files cannot be deleted by themselves | Every file of the version, then the same |
| npm | A tarball is unpublished as `npm unpublish <name>@<version>` does. The package document cannot be deleted by itself | The same, for that version |
| PyPI | Nothing more: pages are written from the files | Every file of the version |
| Docker | A tag is removed. A manifest is removed with its tags and what only it used, as by its digest in the registry API. A blob that a manifest refers to cannot be deleted | A tag is removed |
```

with

```markdown
| Raw | Nothing more | Its one file: in a Raw repository every file is a component, its folder the namespace |
| Maven | Nothing more: checksums and metadata are computed from the files when they are asked for, so they follow by themselves | Every file of the version |
| npm | A tarball is unpublished as `npm unpublish <name>@<version>` does, and dist-tags that named it move. A package's dist-tags cannot be deleted by themselves | The same, for that version |
| PyPI | Nothing more: pages are written from the files | Every file of the release |
| Docker | A tag is removed. A manifest is removed with its tags and what only it used, as by its digest in the registry API. A blob that a manifest refers to cannot be deleted | A tag is removed |
```

Replace

```markdown
| Raw | Has no components. Its files are found by browsing |
```

with

```markdown
| Raw | Nothing: a file's component is its folder and its name |
```

- [ ] **Step 3: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2402 passed, 1 skipped; no findings.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-11-browse-search-upload-design.md
git commit -m "docs: browsing and deleting through the content API"
```
