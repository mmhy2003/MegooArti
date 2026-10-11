# Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `GET /api/v1/search` finds components by what people type, by field and by checksum, in every repository the caller may browse, and an administrator can rebuild a repository's index.

**Architecture:** Each component carries the words it is found by in a column, `components.search`, in lower case. Its format says what they are, from the component's key and attributes, and the facade writes them whenever it creates a component or changes its attributes. "Contains" is a `LIKE` on that column behind a trigram index; fields are `ILIKE` on the name and namespace, also behind trigram indexes; a checksum is an exact lookup on a hash index of the blobs. The route works out which repositories the caller may browse and hands only those to the query. Rebuilding walks a repository's files and components through the facade in committed pieces.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, Alembic, PostgreSQL (`pg_trgm`, GIN and hash indexes), pytest + pytest-asyncio.

**Spec:** [docs/superpowers/specs/2026-10-11-browse-search-upload-design.md](../specs/2026-10-11-browse-search-upload-design.md), sections 4.2, 6 and the search part of 10; D8 to D11. Business requirements: [docs/BRD.md](../../BRD.md) CMP-5, CMP-6, CMP-9, the rest of REP-13, API-4, API-5. Task 4 amends the spec where this plan settles something the spec left open.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `Format.search_text(key, attributes)` gives a component's words; the facade lowers them, cuts them at 4,000 characters and stores them when it creates a component and whenever it sets its attributes. | One place writes the column, so no format can forget to. A description can be a book. |
| P2 | Maven's words are its coordinates and `group:artifact:version`. The POM's name and description are not read. | Reading POMs means parsing XML that anyone who may deploy wrote, at upload. It is left for when someone asks; Task 4 amends the spec. |
| P3 | What is typed becomes a pattern in which `*` is anything and `%`, `_` and `\\` are themselves. | People type `*`. The pattern characters of SQL must not be a second, hidden syntax. |
| P4 | `q` is matched in lower case against the search text, word by word, at most ten words. `namespace`, `name` and `version` match a whole value with `ILIKE`, so whatever the case. | Names differ in case between formats and people do not remember which. Ten conditions are more than anyone means. |
| P5 | Trigram (GIN) indexes on `search`, `name` and `namespace`; a hash index on each of a blob's four checksums. The migration creates `pg_trgm` if it is not there and does not drop it on the way back. | "Contains" and patterns with `*` otherwise read every row; a checksum is only ever looked up whole. Something else in the database may use the extension. |
| P6 | Components in a namespace their format keeps for itself (`Format.unlisted_namespaces`, from plan 8a) are left out, format by format. | D10: a Docker manifest without a tag is not found. |
| P7 | Results are ordered by name and namespace in byte order, then repository, then newest first. | The order is then the same on every database, whatever its collation. |
| P8 | A group is not searched. | It holds nothing of its own; what is behind it is found in its members. |
| P9 | A checksum must be the lower-case hexadecimal digits of its kind, or the request is `422`. | A value of the wrong length can only be a mistake, and saying so is kinder than finding nothing. |
| P10 | The migration gives existing components their namespace, name and version as search text. | It cannot run a format's code. Rebuilding an index writes the rest. |
| P11 | Rebuilding is done in the request, 500 files and then 500 components at a time, each piece committed. A file the format keeps for itself (`kind` `metadata`) gets no component; a component with no file left is removed. The answer counts `files`, `moved`, `components` and `removed`. | D11, D6's reasoning: no task system yet, and a rebuild that is interrupted has done part of the work and can be repeated. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; the standard error envelope; services never commit; no ORM relationships; only the security package reads `Principal.patterns`; every route authenticates via a dependency that reaches one in `AUTHENTICATION_DEPENDENCIES`; list endpoints use `Page` and `PageParams`; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds one migration (`0007`), no setting and no dependency.**
- **`search.py` knows nothing of permissions or HTTP.** The route decides which repositories are searched: those the caller may `browse`.
- **Nothing is found, counted or hinted at in a repository the caller may not browse:** not by a word, not by a checksum, not in a total.
- **What a remote or an uploader wrote reaches a pattern only as text:** every character but `*` matches itself.
- **Only the facade writes `components.search`.**

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **Characters that mean something in a pattern:** `%`, `_`, `\\`, `*` in every position; a word shorter than three characters; more words than are looked at; capitals (Task 2).
2. **Who finds what:** a repository the caller may not browse, by word, by checksum, named in `repository`, and in the total; the anonymous user; a namespace a format keeps for itself; a group (Task 2).
3. **What a component is found by when it changes:** attributes replaced, a manifest whose description or keywords are not text, text longer than the limit (Task 1).
4. **A rebuild:** a file with no component, with the wrong one, a component with no file, a file the format keeps for itself, a repository larger than one piece, twice in a row, a group, a caller who is not an administrator (Task 3).
5. **The migration:** components that exist, the way back, the extension (Task 1).

---

### Task 1: Core: what a component is found by

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0007_add_component_search.py`
- Modify: `backend/src/megooarti/repositories/models.py`
- Modify: `backend/src/megooarti/storage/models.py`
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Modify: `backend/src/megooarti/repositories/pypi/format.py`
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Test: `backend/tests/repositories/test_search_text.py`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `RepositoryContext._component`, `_record`, `annotate`; `ComponentKey`; each format's attribute key (`_MANIFEST` for npm, `_DECLARED` for PyPI).
- Produces:
  - `components.search` (text, not null, default empty), trigram indexes `ix_components_search_trgm`, `ix_components_name_trgm`, `ix_components_namespace_trgm`, and hash indexes `ix_blobs_md5`, `ix_blobs_sha1`, `ix_blobs_sha256`, `ix_blobs_sha512`.
  - `Format.search_text(key: ComponentKey, attributes: dict[str, Any]) -> str`, overridden by Maven, npm, PyPI and Docker.
  - `RepositoryContext._describe(component, attributes=None)`: sets the attributes if given, and writes the search text.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_search_text.py`:

```python
"""What a component is found by: the words each format gives it."""

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.formats import ComponentKey, Format
from megooarti.repositories.models import Component
from tests.accounts import PASSWORD, basic
from tests.repositories.conftest import someone
from tests.repositories.docker.conftest import push_image
from tests.repositories.npm.conftest import publish
from tests.repositories.pypi.conftest import upload


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str):
    made = await service.create_repository(
        db, name=name, format=format, type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    return made


async def texts(db, namespace: str | None = "") -> list[str]:
    found = select(Component.search).order_by(Component.search)
    if namespace is not None:
        found = found.where(Component.namespace == namespace)
    return list(await db.scalars(found))


def test_a_component_is_found_by_its_namespace_name_and_version_unless_its_format_adds_more():
    described = Format().search_text(ComponentKey("docs/api", "Index.html", ""), {})
    versioned = Format().search_text(ComponentKey("", "tool", "1.0"), {"anything": "ignored"})

    assert (described, versioned) == ("docs/api Index.html", "tool 1.0")


async def test_a_raw_file_is_found_by_its_folder_and_name_in_lower_case(client, files, root, db):
    await client.put("/repository/files/Docs/Guide.MD", content=b"x", headers=root)

    assert await texts(db, None) == ["docs guide.md"]


async def test_a_maven_artifact_is_found_by_its_coordinates(client, root, db):
    await create(db, "releases", "maven")
    await client.put(
        "/repository/releases/com/acme/app/1.0/app-1.0.jar", content=b"x", headers=root
    )

    assert await texts(db, None) == ["com.acme app 1.0 com.acme:app:1.0"]


async def test_an_npm_package_is_found_by_its_name_description_and_keywords(client, root, db):
    await create(db, "npm", "npm")
    await publish(
        client,
        root,
        "@acme/tool",
        "1.0.0",
        description="Cuts Things",
        keywords=["saw", "Blade", 7, {"not": "a word"}],
    )
    await publish(client, root, "plain", "2.0.0", description=["not text"], keywords="one two")

    assert await texts(db, None) == [
        "acme tool 1.0.0 @acme/tool cuts things saw blade",
        "plain 2.0.0 plain one two",
    ]


async def test_a_python_release_is_found_by_its_name_and_summary(client, root, db):
    await create(db, "pypi", "pypi")
    await upload(client, root, "greeter-1.0-py3-none-any.whl", summary="Says Hello")

    assert await texts(db, None) == ["greeter 1.0 says hello"]


async def test_a_docker_tag_is_found_as_people_write_images(client, root, db):
    await create(db, "images", "docker")
    await push_image(client, root, "team/app", "1.0", "one")

    assert await texts(db, "") == ["team/app 1.0 team/app:1.0"]


async def test_what_a_component_is_found_by_has_a_limit(client, root, db):
    await create(db, "npm", "npm")

    await publish(client, root, "tool", "1.0.0", description="word " * 5000)

    (text,) = await texts(db, None)
    assert len(text) == 4000 and text.startswith("tool 1.0.0 tool word word")


async def test_changing_what_is_said_about_a_component_changes_what_it_is_found_by(
    client, root, db, context_for
):
    repository = await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0", description="first words")
    context = await context_for(repository, someone("repository:npm:npm"))

    await context.annotate("", "tool", "1.0.0", {"npm": {"description": "Deprecated: use saw"}})
    await db.commit()

    assert await texts(db, None) == ["tool 1.0.0 tool deprecated: use saw"]
```

In `backend/tests/test_migrations.py`:

Replace

```python
from tests.databases import fetch_all
```

with

```python
from tests.databases import fetch_all, run_sql
```

Add to the end of `backend/tests/test_migrations.py`:

```python
SEARCH_INDEXES = (
    "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' "
    "AND (indexname LIKE 'ix_components_%_trgm' OR indexname LIKE 'ix_blobs_%') ORDER BY indexname"
)


def test_components_that_exist_are_given_what_they_are_found_by(empty_database):
    config = alembic_config(empty_database)
    command.upgrade(config, "0006")
    repository = "00000000-0000-0000-0000-000000000001"
    run_sql(
        empty_database,
        "INSERT INTO repositories (id, name, name_key, format, type, online, config, "
        f"created_at, updated_at) VALUES ('{repository}', 'old', 'old', 'maven', 'group', true, "
        "'{}', now(), now())",
        "INSERT INTO components (id, repository_id, namespace, name, version, attributes, "
        "created_at, updated_at) VALUES "
        f"(gen_random_uuid(), '{repository}', 'Com.Acme', 'App', '1.0', '{{}}', now(), now()), "
        f"(gen_random_uuid(), '{repository}', '', 'readme.TXT', '', '{{}}', now(), now())",
    )

    command.upgrade(config, "head")

    found = fetch_all(empty_database, "SELECT search FROM components ORDER BY search")
    assert found == [("com.acme app 1.0",), ("readme.txt",)]
    assert fetch_all(empty_database, SEARCH_INDEXES) == [
        ("ix_blobs_md5",),
        ("ix_blobs_sha1",),
        ("ix_blobs_sha256",),
        ("ix_blobs_sha512",),
        ("ix_components_name_trgm",),
        ("ix_components_namespace_trgm",),
        ("ix_components_search_trgm",),
    ]


def test_the_search_column_and_its_indexes_go_on_the_way_back(empty_database):
    config = alembic_config(empty_database)
    command.upgrade(config, "head")

    command.downgrade(config, "0006")

    columns = fetch_all(
        empty_database,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'components' AND column_name = 'search'",
    )
    assert columns == []
    assert fetch_all(empty_database, SEARCH_INDEXES) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_search_text.py tests/test_migrations.py -q`
Expected: 9 failed, 8 passed. `'Format' object has no attribute 'search_text'`, `column "search" does not exist`, and no revision `0007`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/migrations/versions/0007_add_component_search.py`:

```python
"""add what a component is found by, and indexes to search with

Search matches text that is contained in a component's search text, which needs a
trigram index, and so the `pg_trgm` extension. It is trusted since PostgreSQL 13: the
owner of the database can create it. Where the application's role may not, have an
administrator run `CREATE EXTENSION pg_trgm` in the database first.

Components that exist are given their namespace, name and version as search text.
Rebuilding a repository's index writes what its format would have written.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKSUMS = ("md5", "sha1", "sha256", "sha512")
_TRIGRAMS = ("search", "name", "namespace")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column("components", sa.Column("search", sa.Text(), nullable=False, server_default=""))
    op.execute(
        "UPDATE components SET search = lower(concat_ws(' ', nullif(namespace, ''), name, "
        "nullif(version, '')))"
    )
    for column in _TRIGRAMS:
        op.create_index(
            f"ix_components_{column}_trgm",
            "components",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )
    # A checksum is only ever looked up whole: a hash index is the small one for that.
    for column in _CHECKSUMS:
        op.create_index(f"ix_blobs_{column}", "blobs", [column], postgresql_using="hash")


def downgrade() -> None:
    for column in _CHECKSUMS:
        op.drop_index(f"ix_blobs_{column}", table_name="blobs")
    for column in _TRIGRAMS:
        op.drop_index(f"ix_components_{column}_trgm", table_name="components")
    op.drop_column("components", "search")
    # The extension stays: something else in the database may use it.
```

In `backend/src/megooarti/repositories/models.py`:

Replace

```python
from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
```

with

```python
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
```

Replace

```python
    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("repository_id", "namespace", "name", "version"),)
```

with

```python
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
```

Replace

```python
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
```

with

```python
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # The words it is found by, in lower case. Its format says what they are.
    search: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
```

In `backend/src/megooarti/storage/models.py`:

Replace

```python
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
```

with

```python
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
```

Replace

```python
    __tablename__ = "blobs"
    __table_args__ = (UniqueConstraint("blob_store_id", "sha256"),)
```

with

```python
    __tablename__ = "blobs"
    __table_args__ = (
        UniqueConstraint("blob_store_id", "sha256"),
        # For finding a file by any of its checksums. Hash: a checksum is looked up whole.
        *(
            Index(f"ix_blobs_{column}", column, postgresql_using="hash")
            for column in ("md5", "sha1", "sha256", "sha512")
        ),
    )
```

In `backend/src/megooarti/repositories/formats.py`:

Before

```python
    async def delete_asset(self, context: "RepositoryContext", path: str) -> bool:
```

add

```python
    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """The words a component is found by. They are stored in lower case.

        `attributes` are the component's own. The generic format gives its namespace,
        name and version; a format adds what its users would type.
        """
        return " ".join(part for part in (key.namespace, key.name, key.version) if part)
```

In `backend/src/megooarti/repositories/content.py`:

Replace

```python
        if component is None:
            component = Component(
                repository_id=self.repository.id,
                namespace=key.namespace,
                name=key.name,
                version=key.version,
            )
            self.db.add(component)
            await self.db.flush()
        return component
```

with

```python
        if component is None:
            component = Component(
                repository_id=self.repository.id,
                namespace=key.namespace,
                name=key.name,
                version=key.version,
                attributes={},
            )
            self._describe(component)
            self.db.add(component)
            await self.db.flush()
        return component

    def _describe(self, component: Component, attributes: dict[str, Any] | None = None) -> None:
        """Write what a component is found by, and its attributes if they are given."""
        if attributes is not None:
            component.attributes = attributes
        key = ComponentKey(component.namespace, component.name, component.version)
        words = self.format.search_text(key, component.attributes)
        component.search = words.lower()[:_SEARCH_MOST]
```

Replace

```python
            if component is not None and component_attributes is not None:
                component.attributes = component_attributes
```

with

```python
            if component is not None and component_attributes is not None:
                self._describe(component, component_attributes)
```

Replace

```python
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            component.attributes = component_attributes
        await self.db.flush()
```

with

```python
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            self._describe(component, component_attributes)
        await self.db.flush()
```

Replace

```python
        if component is None:
            return False
        component.attributes = attributes
        await self.db.flush()
        return True
```

with

```python
        if component is None:
            return False
        self._describe(component, attributes)
        await self.db.flush()
        return True
```

Before

```python
class TooLarge(Exception):
```

add

```python
# What a component is found by is cut to this: a description can be a book.
_SEARCH_MOST = 4000
```

In `backend/src/megooarti/repositories/maven/format.py`:

Before

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        # Maven clients rarely declare a type, and never a useful one.
```

add

```python
    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its coordinates, and the three of them as they are written in a build file."""
        together = f"{key.namespace}:{key.name}:{key.version}"
        return f"{super().search_text(key, attributes)} {together}"
```

In `backend/src/megooarti/repositories/npm/format.py`:

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A tarball belongs to its package and version. Nothing else is part of one."""
```

add

```python
    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its name as npm writes it, and the description and keywords of its manifest."""
        manifest = attributes.get(_MANIFEST)
        manifest = manifest if isinstance(manifest, dict) else {}
        words = [f"@{key.namespace}/{key.name}" if key.namespace else key.name]
        description, keywords = manifest.get("description"), manifest.get("keywords")
        if isinstance(description, str):
            words.append(description)
        if isinstance(keywords, str):
            words.append(keywords)
        elif isinstance(keywords, list):
            words += [word for word in keywords if isinstance(word, str)]
        return " ".join([super().search_text(key, attributes), *words])
```

In `backend/src/megooarti/repositories/pypi/format.py`:

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A file belongs to its project and version. Nothing else is part of one."""
```

add

```python
    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """Its name and version, and the summary its upload declared."""
        declared = attributes.get(_DECLARED)
        summary = declared.get("summary") if isinstance(declared, dict) else None
        words = super().search_text(key, attributes)
        return f"{words} {summary}" if isinstance(summary, str) else words
```

In `backend/src/megooarti/repositories/docker/format.py`:

Replace

```python
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin, urlsplit
```

with

```python
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin, urlsplit
```

Before

```python
    def describe_component(self, path: str) -> ComponentKey | None:
        """A tag is a component: the image, and the tag as its version.
```

add

```python
    def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
        """A tag is found by its image and tag, also as `image:tag`."""
        words = super().search_text(key, attributes)
        return words if key.namespace else f"{words} {key.name}:{key.version}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_search_text.py tests/test_migrations.py -q`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/test_search_text.py backend/tests/test_migrations.py
git commit -m "feat(repositories): the words a component is found by"
```

---

### Task 2: The search API

**Files:**
- Create: `backend/src/megooarti/repositories/search.py`
- Create: `backend/src/megooarti/repositories/search_api.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `backend/tests/test_route_guards.py`
- Test: `backend/tests/repositories/test_search.py`

**Interfaces:**
- Consumes: `components.search` and the indexes (Task 1); `Format.unlisted_namespaces`, `require_caller`, `service.all_repositories` (plan 8a); `Page`, `PageParams`, `page`.
- Produces:
  - `search.pattern(typed: str) -> str`.
  - `search.Wanted(q, namespace, name, version, md5, sha1, sha256, sha512)`, all strings, empty for "not asked".
  - `search.Found(id, repository, format, namespace, name, version, created, modified)`.
  - `search.BadChecksum`, whose text is the field's name; `search.CHECKSUMS`.
  - `await search.search(db, repositories: Sequence[Repository], wanted, *, limit, offset) -> tuple[list[Found], int]`.
  - The route `GET /api/v1/search`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_search.py`:

```python
"""Searching for components across repositories."""

import hashlib

import pytest

from megooarti.repositories import service
from megooarti.repositories.search import pattern
from megooarti.security import roles, users
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.docker.conftest import push_image
from tests.repositories.npm.conftest import publish
from tests.repositories.pypi.conftest import upload

SEARCH = "/api/v1/search"
JAR = b"the bytes of the jar"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str, **settings):
    made = await service.create_repository(
        db,
        name=name,
        format=format,
        type=settings.pop("type", "hosted"),
        online=True,
        blob_store="default",
        **settings,
    )
    await db.commit()
    return made


@pytest.fixture
async def stocked(client, root, db, files) -> None:
    """Something of every format, in repositories named for it."""
    for name in ("maven", "npm", "pypi", "docker"):
        await create(db, name, name)
    for path, data in (
        ("com/acme/commons-lang/3.0/commons-lang-3.0.jar", JAR),
        ("com/acme/commons-lang/3.1/commons-lang-3.1.jar", b"3.1"),
        ("org/other/commons-io/1.0/commons-io-1.0.jar", b"io"),
    ):
        assert (
            await client.put(f"/repository/maven/{path}", content=data, headers=root)
        ).is_success
    await publish(client, root, "@acme/saw", "1.0.0", description="Cuts wood", keywords=["blade"])
    await publish(client, root, "commons", "2.0.0", description="100% shared_code")
    await upload(client, root, "greeter-1.0-py3-none-any.whl", summary="Says hello to commons")
    await push_image(client, root, "acme/saw", "1.0", "one", repository="docker")
    await client.put("/repository/files/docs/Commons-Guide.md", content=b"guide", headers=root)


async def find(client, headers, **params) -> list[str]:
    response = await client.get(SEARCH, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [
        f"{item['repository']}:{item['namespace']}:{item['name']}:{item['version']}"
        for item in response.json()["items"]
    ]


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("a*b", "a%b"),
        ("100%", r"100\%"),
        ("a_b", r"a\_b"),
        ("back\\slash", "back\\\\slash"),
        ("*", "%"),
        ("plain", "plain"),
    ],
)
def test_what_is_typed_becomes_a_pattern_in_which_only_the_star_means_anything(typed, expected):
    assert pattern(typed) == expected


async def test_a_word_finds_what_contains_it_in_every_format(client, root, stocked):
    found = await find(client, root, q="commons")

    assert found == [
        "files:docs:Commons-Guide.md:",
        "npm::commons:2.0.0",
        "maven:org.other:commons-io:1.0",
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
        "pypi::greeter:1.0",  # by its summary
    ]


async def test_results_say_where_and_what_each_component_is(client, root, stocked):
    response = await client.get(SEARCH, params={"q": "saw", "format": "npm"}, headers=root)

    (item,) = response.json()["items"]
    assert (item["repository"], item["format"]) == ("npm", "npm")
    assert (item["namespace"], item["name"], item["version"]) == ("acme", "saw", "1.0.0")
    assert item["id"] and item["created"] and item["modified"]
    opened = await client.get(f"/api/v1/content/npm/components/{item['id']}", headers=root)
    assert opened.status_code == 200


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ("COMMONS lang", ["maven:com.acme:commons-lang:3.1", "maven:com.acme:commons-lang:3.0"]),
        ("lang commons 3.1", ["maven:com.acme:commons-lang:3.1"]),
        ("com.acme:commons-lang:3.0", ["maven:com.acme:commons-lang:3.0"]),
        ("@acme/saw", ["npm:acme:saw:1.0.0"]),
        ("acme/saw:1.0", ["docker::acme/saw:1.0"]),
        ("blade", ["npm:acme:saw:1.0.0"]),
        ("cuts wood", ["npm:acme:saw:1.0.0"]),
        ("io", ["maven:org.other:commons-io:1.0"]),  # shorter than three characters is fine
        ("comm*lang", ["maven:com.acme:commons-lang:3.1", "maven:com.acme:commons-lang:3.0"]),
        ("lang*zzz", []),
        ("100%", ["npm::commons:2.0.0"]),
        ("10%0", []),  # a percent sign is itself
        ("shared_code", ["npm::commons:2.0.0"]),
        ("shared*code", ["npm::commons:2.0.0"]),
        ("sharedXcode", []),
        ("shared-code", []),  # an underscore is itself too
        ("nothing-like-this", []),
    ],
)
async def test_how_words_match(client, root, stocked, q, expected):
    assert await find(client, root, q=q) == expected


async def test_fields_match_a_whole_value(client, root, stocked):
    assert await find(client, root, name="commons") == ["npm::commons:2.0.0"]
    assert await find(client, root, name="commons*") == [
        "files:docs:Commons-Guide.md:",  # whatever the case
        "npm::commons:2.0.0",
        "maven:org.other:commons-io:1.0",
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
    ]
    assert await find(client, root, name="COMMONS-IO") == ["maven:org.other:commons-io:1.0"]
    assert await find(client, root, namespace="com.acme") == [
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
    ]
    assert await find(client, root, namespace="*acme") == [
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
        "npm:acme:saw:1.0.0",
    ]
    assert await find(client, root, version="3.*", name="commons-lang") == [
        "maven:com.acme:commons-lang:3.1",
        "maven:com.acme:commons-lang:3.0",
    ]
    assert await find(client, root, version="3") == []


async def test_where_to_look_is_narrowed_by_format_and_repository(client, root, stocked, db):
    await create(db, "more-maven", "maven")
    await client.put(
        "/repository/more-maven/com/acme/saw/1.0/saw-1.0.jar", content=b"saw", headers=root
    )

    assert await find(client, root, q="saw", format="maven") == ["more-maven:com.acme:saw:1.0"]
    assert await find(client, root, q="saw", repository="docker") == ["docker::acme/saw:1.0"]
    assert await find(client, root, q="saw", repository="npm", format="maven") == []
    assert await find(client, root, q="saw", repository="nothing") == []
    assert len(await find(client, root, q="saw")) == 3


async def test_a_checksum_finds_the_component_of_the_file(client, root, stocked):
    digests = {
        name: hashlib.new(name, JAR).hexdigest() for name in ("md5", "sha1", "sha256", "sha512")
    }

    for field, value in digests.items():
        assert await find(client, root, **{field: value}) == ["maven:com.acme:commons-lang:3.0"]
    assert await find(client, root, sha1=digests["sha1"], q="io") == []
    assert await find(client, root, sha1="0" * 40) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("sha1", "abc"), ("sha256", "G" * 64), ("md5", "A" * 32), ("sha512", "0" * 127 + "!")],
)
async def test_a_checksum_must_be_one(client, root, stocked, field, value):
    response = await client.get(SEARCH, params={field: value}, headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")
    assert response.json()["error"]["details"][0]["field"] == field


async def test_with_nothing_to_look_for_everything_is_listed_a_page_at_a_time(
    client, root, stocked
):
    everything = await client.get(SEARCH, headers=root)
    page = await client.get(SEARCH, params={"limit": 2, "offset": 1}, headers=root)

    assert everything.json()["total"] == 8
    names = [item["name"] for item in everything.json()["items"]]
    assert names == sorted(names)  # in the order of their names
    assert [item["name"] for item in page.json()["items"]] == names[1:3]
    assert (page.json()["total"], page.json()["limit"], page.json()["offset"]) == (8, 2, 1)


async def test_what_a_format_keeps_for_itself_is_not_found(client, root, stocked):
    found = await find(client, root, q="sha256")
    images = await find(client, root, format="docker")

    assert found == []  # a manifest's component has its digest for a version
    assert images == ["docker::acme/saw:1.0"]


async def test_nothing_is_found_where_the_caller_may_not_browse(
    client, root, stocked, make_user, db
):
    may = ["repository:npm:npm:browse", "repository:maven:maven:read"]
    await roles.create_role(db, "npm-browsers", "", may, [])
    await db.commit()
    await make_user("reader", roles=["npm-browsers"])
    reader = basic("reader", PASSWORD)

    found = await find(client, reader, q="commons")
    elsewhere = await find(client, reader, q="commons", repository="maven")
    by_checksum = await find(client, reader, sha1=hashlib.sha1(JAR).hexdigest())
    everything = await client.get(SEARCH, headers=reader)
    nobody = await client.get(SEARCH, params={"q": "commons"})

    assert found == ["npm::commons:2.0.0"]
    assert elsewhere == by_checksum == []
    assert everything.json()["total"] == 2
    assert (nobody.status_code, error_code(nobody)) == (401, "unauthorized")


async def test_anyone_finds_what_the_anonymous_user_may_browse(client, root, stocked, db):
    await roles.create_role(db, "public", "", ["repository:npm:npm:browse"], [])
    await users.set_roles(db, await users.get_user_by_username(db, "anonymous"), ["public"])
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    assert await find(client, {}, q="commons") == ["npm::commons:2.0.0"]


async def test_a_group_and_what_is_behind_it_is_found_once(client, root, stocked, db):
    await create(db, "all", "maven", type="group", group={"members": ["maven"]})

    assert await find(client, root, name="commons-io") == ["maven:org.other:commons-io:1.0"]
    assert await find(client, root, name="commons-io", repository="all") == []


async def test_more_words_than_make_sense_are_not_all_looked_at(client, root, stocked):
    many = " ".join(["commons"] * 10 + ["never-matches"])

    assert len(await find(client, root, q=many)) == 6


async def test_what_is_asked_for_has_a_length(client, root, stocked):
    response = await client.get(SEARCH, params={"q": "x" * 1025}, headers=root)

    assert (response.status_code, error_code(response)) == (422, "validation_error")
```

In `backend/tests/test_route_guards.py`:

After

```python
    assert {"/api/v1/content", "/api/v1/content/{repository}/tree"} <= paths
```

add

```python
    assert "/api/v1/search" in paths
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_search.py tests/test_route_guards.py -q`
Expected: collection error, `No module named 'megooarti.repositories.search'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/search.py`:

```python
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
```

`backend/src/megooarti/repositories/search_api.py`:

```python
"""The search route: components across every repository the caller may browse."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti.db.session import get_session
from megooarti.errors import ApiError
from megooarti.pagination import Page, PageParams, page
from megooarti.repositories import search, service
from megooarti.security.authentication import Principal, require_caller

router = APIRouter(prefix="/search", tags=["content"])

Text = Annotated[str, Query(max_length=1024)]


class Result(BaseModel):
    id: uuid.UUID
    repository: str
    format: str
    namespace: str
    name: str
    version: str
    created: datetime
    modified: datetime


@router.get("", response_model=Page[Result])
async def search_components(
    q: Annotated[str, Query(max_length=1024, description="Words the component contains.")] = "",
    format: Text = "",
    repository: Text = "",
    namespace: Text = "",
    name: Text = "",
    version: Text = "",
    md5: Text = "",
    sha1: Text = "",
    sha256: Text = "",
    sha512: Text = "",
    params: PageParams = Depends(),
    caller: Principal = Depends(require_caller),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Find components in the repositories the caller may browse.

    Each word of `q` must be contained in the component's group, name, version or the
    words its format adds, whatever the case; `*` stands for anything. `namespace`,
    `name` and `version` match a whole value, also with `*`. A checksum finds the
    components that have a file with exactly that checksum. `format` and `repository`
    narrow where to look. With nothing given, everything is listed.
    """
    allowed = [
        found
        for found in await service.all_repositories(db)
        if found.type != "group"  # a group holds nothing of its own
        and (not format or found.format == format)
        and (not repository or found.name == repository)
        and caller.allows(f"repository:{found.format}:{found.name}:browse")
    ]
    wanted = search.Wanted(q, namespace, name, version, md5, sha1, sha256, sha512)
    try:
        items, total = await search.search(
            db, allowed, wanted, limit=params.limit, offset=params.offset
        )
    except search.BadChecksum as error:
        digits = search.CHECKSUMS[str(error)]
        message = f"Must be {digits} hexadecimal digits in lower case."
        details = [{"field": str(error), "message": message}]
        raise ApiError(422, "validation_error", "The request is not valid.", details) from None
    return page(items, total, params)
```

In `backend/src/megooarti/main.py`:

After

```python
from megooarti.repositories.routes import router as content_router
```

add

```python
from megooarti.repositories.search_api import router as search_router
```

After

```python
    app.include_router(content_api_router, prefix=API_PREFIX)
```

add

```python
    app.include_router(search_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_search.py tests/test_route_guards.py -q`
Expected: 43 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/test_search.py backend/tests/test_route_guards.py
git commit -m "feat(search): find components across the repositories a caller may browse"
```

---

### Task 3: Rebuilding a repository's index

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/api.py`
- Test: `backend/tests/repositories/test_rebuild_index.py`

**Interfaces:**
- Consumes: `RepositoryContext._component`, `_describe`, `_lock_component` (Task 1); `build_context`; `require("admin:repositories:write")`; the search route, to see what is found (Task 2).
- Produces:
  - `await context.reindex(*, after: str = "", limit: int = 500) -> tuple[int, int, str | None]`: files looked at, files moved, where to go on.
  - `await context.redescribe(*, after: uuid.UUID | None = None, limit: int = 500) -> tuple[int, int, uuid.UUID | None]`: components looked at, components removed, where to go on.
  - The route `POST /api/v1/repositories/{name}/rebuild-index`, answering `{"files", "moved", "components", "removed"}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_rebuild_index.py`:

```python
"""Rebuilding a repository's index: every file to its component, every component its words."""

import pytest
from sqlalchemy import delete, func, select, update

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import someone
from tests.repositories.docker.conftest import push_image
from tests.repositories.npm.conftest import publish

REPOSITORIES = "/api/v1/repositories"
SEARCH = "/api/v1/search"


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)


async def create(db, name: str, format: str, **settings):
    made = await service.create_repository(
        db,
        name=name,
        format=format,
        type=settings.pop("type", "hosted"),
        online=True,
        blob_store="default",
        **settings,
    )
    await db.commit()
    return made


async def deploy(client, root, *paths: str) -> None:
    for path in paths:
        response = await client.put(
            f"/repository/maven/{path}", content=path.encode(), headers=root
        )
        assert response.status_code == 201, response.text


async def found(client, root, **params) -> list[str]:
    response = await client.get(SEARCH, params=params, headers=root)
    return [f"{item['name']}:{item['version']}" for item in response.json()["items"]]


async def forget_components(db) -> None:
    """Leave the files as an older version would have: belonging to nothing."""
    await db.execute(update(Asset).values(component_id=None))
    await db.execute(delete(Component))
    await db.commit()


async def test_files_are_given_back_to_the_components_they_belong_to(client, root, db):
    await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar", "com/acme/app/1.0/app-1.0.pom")
    await deploy(client, root, "com/acme/lib/2.0/lib-2.0.jar")
    await forget_components(db)
    before = await found(client, root)

    response = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)

    assert before == []
    assert response.json() == {"files": 3, "moved": 3, "components": 2, "removed": 0}
    assert await found(client, root, q="com.acme:app:1.0") == ["app:1.0"]
    listed = await client.get(
        "/api/v1/content/maven/components", params={"name": "app"}, headers=root
    )
    opened = await client.get(
        f"/api/v1/content/maven/components/{listed.json()['items'][0]['id']}", headers=root
    )
    assert [file["name"] for file in opened.json()["files"]] == ["app-1.0.jar", "app-1.0.pom"]


async def test_what_components_are_found_by_is_written_again(client, root, db):
    await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0", description="Cuts wood")
    await db.execute(update(Component).values(search="tool 1.0.0"))  # as a migration left it
    await db.commit()
    before = await found(client, root, q="wood")

    response = await client.post(f"{REPOSITORIES}/npm/rebuild-index", headers=root)

    assert before == []
    assert response.json() == {"files": 2, "moved": 0, "components": 1, "removed": 0}
    assert await found(client, root, q="wood") == ["tool:1.0.0"]


async def test_a_second_rebuild_changes_nothing(client, root, db):
    await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar")

    first = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)
    second = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)

    assert first.json() == second.json() == {"files": 1, "moved": 0, "components": 1, "removed": 0}


async def test_a_file_with_the_wrong_component_is_moved_and_an_empty_component_goes(
    client, root, db
):
    repository = await create(db, "maven", "maven")
    await deploy(client, root, "com/acme/app/1.0/app-1.0.jar", "com/acme/lib/2.0/lib-2.0.jar")
    stray = Component(repository_id=repository.id, namespace="x", name="stray", version="0")
    db.add(stray)
    await db.flush()
    await db.execute(update(Asset).where(Asset.path.like("%lib%")).values(component_id=stray.id))
    await db.commit()

    response = await client.post(f"{REPOSITORIES}/maven/rebuild-index", headers=root)

    assert response.json() == {"files": 2, "moved": 1, "components": 3, "removed": 1}
    names = set(await db.scalars(select(Component.name)))
    assert names == {"app", "lib"}
    assert await found(client, root, name="lib") == ["lib:2.0"]


async def test_docker_manifests_kept_before_they_were_components_get_theirs(client, root, db):
    await create(db, "docker", "docker")
    await push_image(client, root, "team/app", "1.0", "one", repository="docker")
    await forget_components(db)

    response = await client.post(f"{REPOSITORIES}/docker/rebuild-index", headers=root)

    # A tag, a manifest, a configuration and a layer; the tag and the manifest are components.
    assert response.json() == {"files": 4, "moved": 2, "components": 2, "removed": 0}
    held = set(await db.execute(select(Component.namespace, Component.name, Component.version)))
    assert ("", "team/app", "1.0") in held
    assert {namespace for namespace, _, _ in held} == {"", "manifests"}
    assert await found(client, root) == ["team/app:1.0"]  # the manifest's is still not listed


async def test_what_a_format_keeps_for_itself_stays_with_no_component(client, root, db):
    await create(db, "npm", "npm")
    await publish(client, root, "tool", "1.0.0")

    await client.post(f"{REPOSITORIES}/npm/rebuild-index", headers=root)

    without = list(await db.scalars(select(Asset.path).where(Asset.component_id.is_(None))))
    assert without == ["-/package/tool/dist-tags"]


async def test_a_large_repository_is_gone_through_in_pieces(db, context_for, files):
    context = await context_for(files, someone("repository:raw:files"))
    for number in range(7):
        await context.store(f"logs/day-{number}", await context.stage_bytes(b"x"))
    await forget_components(db)
    looked_at, moved, after, pieces = 0, 0, "", 0

    while after is not None:
        seen, changed, after = await context.reindex(after=after, limit=3)
        looked_at, moved, pieces = looked_at + seen, moved + changed, pieces + 1
    described, removed, following = await context.redescribe(limit=3)
    rest = await context.redescribe(after=following, limit=100)

    assert (looked_at, moved, pieces) == (7, 7, 3)
    assert (described, removed, following is not None) == (3, 0, True)
    assert rest[:2] == (4, 0) and rest[2] is None
    assert await db.scalar(select(func.count()).select_from(Component)) == 7


async def test_a_group_has_no_index(client, root, db, files):
    await create(db, "all", "raw", type="group", group={"members": ["files"]})

    response = await client.post(f"{REPOSITORIES}/all/rebuild-index", headers=root)

    assert response.json() == {"files": 0, "moved": 0, "components": 0, "removed": 0}


async def test_rebuilding_is_an_administrators(client, root, db, files, make_user):
    everything = ["repository:raw:files", "admin:repositories:read"]
    await roles.create_role(db, "users", "", everything, [])
    await db.commit()
    await make_user("user", roles=["users"])

    refused = await client.post(
        f"{REPOSITORIES}/files/rebuild-index", headers=basic("user", PASSWORD)
    )
    nobody = await client.post(f"{REPOSITORIES}/files/rebuild-index")
    absent = await client.post(f"{REPOSITORIES}/nothing/rebuild-index", headers=root)

    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert nobody.status_code == 401
    assert (absent.status_code, error_code(absent)) == (404, "not_found")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_rebuild_index.py -q`
Expected: 8 failed, 1 passed: there is no such route, and the context has no `reindex`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/content.py`:

After

```python
import hashlib
import mimetypes
import re
```

add

```python
import uuid
```

Before

```python
    async def respond(self, path: str, request: Request) -> Response:
        """The response to a GET or HEAD for a path. The caller has checked `read`."""
```

add

```python
    async def reindex(self, *, after: str = "", limit: int = 500) -> tuple[int, int, str | None]:
        """Give a piece of this repository's files to the components their paths name.

        For rebuilding an index: what an older version stored may belong to no
        component, or to another than it would now. Returns how many files were looked
        at, how many changed hands, and the path to go on after, or None at the end.
        Nobody's permission is involved. The caller commits.
        """
        rows = list(
            await self.db.scalars(
                select(Asset)
                .where(Asset.repository_id == self.repository.id, Asset.path > after)
                .order_by(Asset.path)
                .limit(limit)
            )
        )
        moved = 0
        for asset in rows:
            # What a format keeps for itself was stored as belonging to nothing.
            kept = asset.kind == _MAINTAINED
            key = None if kept else self.format.describe_component(asset.path)
            component = None if key is None else await self._component(key)
            wanted = None if component is None else component.id
            if asset.component_id != wanted:
                asset.component_id = wanted
                moved += 1
        await self.db.flush()
        return len(rows), moved, rows[-1].path if len(rows) == limit else None

    async def redescribe(
        self, *, after: uuid.UUID | None = None, limit: int = 500
    ) -> tuple[int, int, uuid.UUID | None]:
        """Write again what a piece of this repository's components are found by.

        A component that has no file left is removed. Returns how many components were
        looked at, how many were removed, and the ID to go on after, or None at the
        end. Nobody's permission is involved. The caller commits.
        """
        wanted = select(Component).where(Component.repository_id == self.repository.id)
        if after is not None:
            wanted = wanted.where(Component.id > after)
        rows = list(await self.db.scalars(wanted.order_by(Component.id).limit(limit)))
        removed = 0
        for component in rows:
            # The lock an upload into the component holds, so that one being added to
            # is not taken for empty.
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            has_file = await self.db.scalar(
                select(Asset.id).where(Asset.component_id == component.id).limit(1)
            )
            if has_file is None:
                await self.db.delete(component)
                removed += 1
            else:
                self._describe(component)
        await self.db.flush()
        return len(rows), removed, rows[-1].id if len(rows) == limit else None
```

In `backend/src/megooarti/repositories/api.py`:

After

```python
from megooarti.repositories import service
```

add

```python
from megooarti.repositories.content import build_context
```

Add to the end of `backend/src/megooarti/repositories/api.py`:

```python
class IndexRebuilt(BaseModel):
    files: int  # looked at
    moved: int  # given to another component than they had, or to one at all
    components: int  # looked at
    removed: int  # that had no file left


@router.post("/{name}/rebuild-index", response_model=IndexRebuilt)
async def rebuild_index(
    name: str,
    request: Request,
    principal: Principal = Depends(require("admin:repositories:write")),
    db: AsyncSession = Depends(get_session),
) -> IndexRebuilt:
    """Go through a repository again: every file to its component, every component its words.

    It repairs what an older version stored differently. The work is done in this
    request, a piece at a time, each piece committed: it can be repeated or interrupted.
    """
    repository = await _load(db, name)
    done = IndexRebuilt(files=0, moved=0, components=0, removed=0)
    if repository.type != "group":  # a group holds nothing of its own
        # Nobody's permission on the content is involved: this is the administrator's.
        context = await build_context(db, request.app.state.settings, repository, None)
        after: str | None = ""
        while after is not None:
            seen, moved, after = await context.reindex(after=after)
            await db.commit()
            done.files, done.moved = done.files + seen, done.moved + moved
        following, first = None, True
        while first or following is not None:
            seen, removed, following = await context.redescribe(after=following)
            await db.commit()
            done.components, done.removed = done.components + seen, done.removed + removed
            first = False
    log.info(
        "repository_index_rebuilt",
        repository=name,
        by=principal.user.username,
        **done.model_dump(),
    )
    return done
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_rebuild_index.py -q`
Expected: 9 passed.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2501 passed, 1 skipped; no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories/test_rebuild_index.py
git commit -m "feat(repositories): rebuild a repository's index"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-11-browse-search-upload-design.md`

**Interfaces:**
- Consumes: search and the rebuild as built.
- Produces: a section of the README, and a spec that says what was built.

- [ ] **Step 1: Document search**

In `README.md`:

After

```markdown
- **A group** holds nothing of its own. It lists its `members`, which are browsed one
  by one.
```

add

````markdown
## Search

`/api/v1/search` finds components in every repository you may browse.

```bash
curl -u alice 'https://repo.example.com/api/v1/search?q=commons+lang'
curl -u alice 'https://repo.example.com/api/v1/search?format=maven&namespace=com.acme&name=app*'
curl -u alice 'https://repo.example.com/api/v1/search?sha1=2ef7bde608ce5404e97d5f042f95f89f1c232871'
```

- **`q`** is matched as it reads: each word must be contained in the component's
  group, name or version, or in the words its format adds, whatever the case. `*`
  stands for anything; every other character is itself. Results are in the order of
  their names, not ranked.
- **What a format adds:** for Maven `group:artifact:version` as one word; for npm
  `@scope/name` and the description and keywords of `package.json`; for PyPI the
  summary; for Docker `image:tag`. In a Raw repository a file is found by its folder
  and name.
- **`namespace`, `name` and `version`** match a whole value, whatever the case, with
  `*` for anything: `name=commons*`. The namespace is a Maven group, an npm scope
  (without the `@`), a Raw file's folder.
- **`md5`, `sha1`, `sha256`, `sha512`** find the components that have a file with
  exactly that checksum.
- **`format` and `repository`** narrow where to look. With nothing given, everything
  you may browse is listed, a page at a time (`limit`, `offset`).
- Each result names its `repository` and has an `id`, which opens at
  `/api/v1/content/<repository>/components/<id>`.
- A Docker manifest without a tag is not found: tags are. A group is not searched;
  what is behind it is.
- **Rebuilding an index.** `POST /api/v1/repositories/<name>/rebuild-index` (for an
  administrator) goes through a repository again: every file is given to the
  component its path says it belongs to, and every component's words are written
  again. Use it after an upgrade that changes what components are found by. It
  answers with how many files and components it looked at and changed.
- Search uses PostgreSQL's `pg_trgm` extension, which the migrations create. Where
  the application's database role may not create extensions, have a database
  administrator run `CREATE EXTENSION pg_trgm` in the database before upgrading.
````

- [ ] **Step 2: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-11-browse-search-upload-design.md`:

Replace

```markdown
| `namespace`, `name`, `version` | The whole value, with `*` |
```

with

```markdown
| `namespace`, `name`, `version` | The whole value, whatever the case, with `*` |
```

Replace

```markdown
The answer is a page of components, each with its repository and format, in the order of name, namespace, repository and newest first, from the repositories the caller may browse (D2).
```

with

```markdown
The answer is a page of components, each with its repository and format, in the order of name, namespace (both by their bytes), repository and newest first, from the repositories the caller may browse (D2). A group is not searched: what is behind it is. At most ten words of `q` are looked at.
```

Replace

```markdown
| Maven | `group:artifact:version` as one word; the POM's name and description, read when the POM is stored |
```

with

```markdown
| Maven | `group:artifact:version` as one word. The POM's name and description are not read yet |
```

Replace

```markdown
| PyPI | The summary and keywords the upload declared |
```

with

```markdown
| PyPI | The summary the upload declared |
```

Replace

```markdown
`POST /api/v1/repositories/{name}/rebuild-index` (an administrator's) does D11 and answers with what it changed.
```

with

```markdown
A component's search text is cut at 4,000 characters.

`POST /api/v1/repositories/{name}/rebuild-index` (an administrator's) does D11, a piece at a time, each piece committed, and answers with `files` and `components` (looked at), `moved` (files given to another component than they had) and `removed` (components that had no file left).
```

Replace

```markdown
- **Search text.** A migration adds `components.search`, the `pg_trgm` extension and a trigram index.
```

with

```markdown
- **Search text.** A migration adds `components.search`, the `pg_trgm` extension, trigram indexes on the search text, the name and the namespace, and a hash index on each checksum of a blob.
```

- [ ] **Step 3: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2501 passed, 1 skipped; no findings.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-11-browse-search-upload-design.md
git commit -m "docs: search and rebuilding an index"
```
