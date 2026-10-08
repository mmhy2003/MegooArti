# Hosted Maven Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mvn deploy` publishes releases and snapshots to hosted Maven repositories whose checksum files and `maven-metadata.xml` are generated from the files stored, never kept as uploaded.

**Architecture:** The storage facade gains read operations, a response built from bytes in memory, and a locked read-modify-write for documents the server maintains. A `maven` format package classifies each path (artifact, metadata, checksum, catalog, other) with pure functions, and one class, `MavenFormat`, answers requests to a hosted repository through the facade: files are stored like Raw files, checksums are answered from recorded hashes, and metadata is built on each request from the versions and files present.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, the standard library's `xml.parsers.expat` and `xml.etree.ElementTree`, pytest + pytest-asyncio, Docker (the `maven:3.9-eclipse-temurin-21` image, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-08-maven-format-design.md](../specs/2026-10-08-maven-format-design.md), sections 4.1, 5, 6, 9, 10 and the plan 4a part of 11. Business requirements: [docs/BRD.md](../../BRD.md) FMT-1 (hosted), REP-4, NFR-1.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `maintain(path, update)` takes a function from the stored bytes to the new bytes and runs it under the path lock. | Merging plugin prefixes is a read-modify-write. Handing the format a lock would let it touch the session. |
| P2 | The facade gains `receive(stream, limit)`, which commits to release the connection and then reads a bounded body. | The rule that no connection is held while a body moves stays inside the facade. |
| P3 | Layout policy is checked only on `PUT`. | A file stored while a repository was permissive must stay readable and deletable after it is made strict. |
| P4 | Version order is written from Maven's published Version Order Specification, with a qualifier after a dot opening a sub-list as one after a hyphen does. A Docker-marked test compares it with Maven itself. | The specification is public and precise; Maven's own behaviour is the arbiter. |
| P5 | An update that omits `version_policy` keeps the stored one. `layout_policy` falls back to `strict`, like every other replaced setting. | The version policy cannot change, so its absence cannot mean "reset". |
| P6 | In this plan the Maven format offers only `hosted`. Plan 4b adds `proxy` and `group`. | A Maven proxy on the generic engine would cache the remote's checksum files, which D1 forbids. |
| P7 | The base format gains `content_type(path, declared)`. | Maven sets the type from the extension without copying the generic upload code. |
| P8 | The container-test helpers move to `tests/containers.py`, and the `stack` and `administrator` fixtures to `tests/conftest.py`, still one stack per test module. | A second module of container tests needs them, and each module should start from a clean stack. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only, one migration head; settings prefixed `MEGOOARTI_` and listed in `README.md`; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; file and hash work off the event loop; only the security package reads `Principal.patterns`; every route authenticates unless on the open list; content responses always carry `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; formats do not commit, the route does; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration and no dependency.**
- **The format's name is `maven`.** Permissions are `repository:maven:<name>:<action>`.
- **Only `maven/format.py` touches the repository context.** `maven/paths.py`, `maven/versions.py`, `maven/metadata.py` and `maven/checksums.py` are pure functions: no database, no files, no clock.
- **Formats never query tables or handle the session.** They use the context's operations.
- **XML is parsed only by `maven.metadata.parse`**, which refuses any `DOCTYPE`.
- **In-memory reads are bounded:** an uploaded checksum 1 KiB, uploaded metadata 1 MiB, a stored metadata document 4 MiB. These small bounded reads of stored documents may hold the connection; uploads never do.
- **No checksum file and no client-made `maven-metadata.xml` is ever stored.**
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A CI account that may only `add`.** It must complete a whole deploy: files, checksums, metadata and plugin prefixes, twice, on a repository that forbids redeploys. An account that may only `read` must not be able to upload even what is dropped (Tasks 3, 8, 9).
2. **Checksums written the way real tools write them:** upper-case, followed by a file name, in `SHA1(file)= …` form, with a byte-order mark or trailing newline. All must verify; anything else must fail the upload, not crash (Tasks 4, 8).
3. **Hostile or broken uploaded metadata:** a `DOCTYPE` with entities, text that is not XML, a document over the limit. Each is `400`, nothing is stored, and nothing is expanded (Tasks 6, 9).
4. **File names that fit two readings, and versions that are not numbers:** `app-1.0.1.jar` inside `1.0/`, classifiers and extensions with dots, versions such as `RELEASE`, an empty qualifier, or non-ASCII digits. Each is classified or sorted, never an error (Tasks 4, 5).
5. **Two deploys at the same moment:** two versions of one artifact, and two plugins of one group. Afterwards the metadata lists both (Task 9).

---

### Task 1: Core: optional component, settings that see their past, content-type hook

**Files:**
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/service.py`
- Modify: `backend/tests/repositories/test_formats.py`
- Modify: `backend/tests/repositories/test_content.py`
- Modify: `backend/tests/repositories/test_service.py`

**Interfaces:**
- Consumes: `Format`, `ComponentKey`, `RepositoryContext._record`, `service.update_repository`.
- Produces:
  - `Format.validate_config(repository_type: str, config: dict, current: dict | None = None) -> dict` — `current` is the stored `format_config` on an update, `None` on creation.
  - `Format.describe_component(path: str) -> ComponentKey | None` — `None` stores the file with `component_id = None`.
  - `Format.content_type(path: str, declared: str | None) -> str | None` — what the generic upload records; the base returns `declared`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/repositories/test_formats.py`:

```python
def test_the_generic_content_type_is_whatever_the_client_declared():
    raw = get_format("raw")

    assert raw.content_type("a/b.bin", "application/x-thing") == "application/x-thing"
    assert raw.content_type("a/b.bin", None) is None


def test_settings_validation_is_given_the_stored_settings():
    assert get_format("raw").validate_config("hosted", {}, {}) == {}
```

In `backend/tests/repositories/test_content.py`, add `from megooarti.repositories.formats import Format` to the imports, then append:

```python
class Loose(Format):
    """A format whose files belong to no package."""

    name = "raw"

    def describe_component(self, path):
        return None


async def test_a_file_can_belong_to_no_component(db, files, context_for):
    context = await context_for(files, EVERYTHING)
    context.format = Loose()

    asset, created = await context.put("notes/readme.txt", body(HELLO))

    assert created is True
    assert asset.component_id is None
    assert await count(db, Component) == 0
    assert await context.delete("notes/readme.txt") is True
    assert await count(db, Asset) == 0
```

In `backend/tests/repositories/test_service.py`, change the import `from megooarti.repositories import service` to `from megooarti.repositories import formats, service`, add `from megooarti.repositories.formats import Format`, then append:

```python
class Sticky(Format):
    """A format whose settings cannot change once stored."""

    name = "sticky"

    def validate_config(self, repository_type, config, current=None):
        if current is not None and config != current:
            raise ApiError(409, "immutable", "These settings cannot be changed.")
        return dict(config)


async def test_a_format_sees_its_stored_settings_on_update(db, monkeypatch):
    monkeypatch.setitem(formats._registry, "sticky", Sticky())
    repository = await create(db, format="sticky", format_config={"colour": "red"})

    refused = await error_of(
        service.update_repository(
            db, repository, online=True, hosted=None, format_config={"colour": "blue"}
        )
    )
    await service.update_repository(
        db, repository, online=False, hosted=None, format_config={"colour": "red"}
    )

    assert (refused.status_code, refused.code) == (409, "immutable")
    assert repository.config["format_config"] == {"colour": "red"}
    assert repository.online is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_formats.py tests/repositories/test_content.py tests/repositories/test_service.py -q`
Expected: 4 failures. `content_type` is not an attribute of `RawFormat`; `validate_config()` takes 3 positional arguments but 4 were given; `'NoneType' object has no attribute 'namespace'`; and the update to `blue` is not refused.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`, replace the `validate_config` and `describe_component` methods of `Format` with:

```python
    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Check and return this format's own settings. The generic format has none.

        `current` is what is stored, on an update, so a format can refuse a change.
        """
        if config:
            details = [
                {"field": "format_config", "message": f"The {self.name} format has no settings."}
            ]
            raise ApiError(422, "validation_error", "The request is not valid.", details)
        return {}

    def describe_component(self, path: str) -> ComponentKey | None:
        """Which component a stored path belongs to: the file, in its directory.

        A format returns None for a file that belongs to no package.
        """
        directory, _, filename = path.rpartition("/")
        return ComponentKey(namespace=directory, name=filename)

    def content_type(self, path: str, declared: str | None) -> str | None:
        """The content type to record for an upload. The generic format trusts the client."""
        return declared
```

In the same file, in `handle_hosted`, replace the line `content_type=request.headers.get("Content-Type"),` with:

```python
                content_type=self.content_type(path, request.headers.get("Content-Type")),
```

In `backend/src/megooarti/repositories/content.py`, in `_record`, replace:

```python
            component = await self._component(self.format.describe_component(path))
            asset = Asset(
                repository_id=self.repository.id,
                component_id=component.id,
```

with:

```python
            key = self.format.describe_component(path)
            component_id = None if key is None else (await self._component(key)).id
            asset = Asset(
                repository_id=self.repository.id,
                component_id=component_id,
```

In `backend/src/megooarti/repositories/service.py`, in `update_repository`, replace the line `"format_config": handler.validate_config(repository.type, format_config or {}),` with:

```python
        "format_config": handler.validate_config(
            repository.type, format_config or {}, repository.config.get("format_config")
        ),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(repositories): optional components, settings that see their past, content-type hook"
```

---

### Task 2: Core: reading through the context

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py`
- Test: `backend/tests/repositories/test_content_reads.py`

**Interfaces:**
- Consumes: `RepositoryContext`, `serving.Servable`, `serving.plan`, `Asset`, `Component`, `Blob`.
- Produces, all in `megooarti.repositories.content`:
  - `Stored(path, kind, size, md5, sha1, sha256, sha512, content_type, modified)` — frozen dataclass; `modified` is a `datetime`.
  - `FileEntry(path, modified)` — frozen dataclass.
  - `TooLarge(Exception)`.
  - `await context.stat(path: str) -> Stored | None`
  - `await context.versions(namespace: str, name: str) -> dict[str, datetime]` — each version that has at least one file, with when its files last changed.
  - `await context.files(namespace: str, name: str, version: str) -> list[FileEntry]` — ordered by path.
  - `await context.names(namespace: str, candidates: Collection[str]) -> set[str]` — which of `candidates` have a component in `namespace`.
  - `await context.read(path: str, *, limit: int) -> bytes | None` — `None` if nothing is there; raises `TooLarge` above `limit`.
  - `await context.receive(chunks: AsyncIterator[bytes], *, limit: int) -> bytes | None` — commits first; `None` if the body is longer than `limit`.
  - `context.respond_with(data: bytes, request: Request, *, filename: str, content_type: str, last_modified: datetime) -> Response` — not a coroutine.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_reads.py`:

```python
import hashlib
from datetime import UTC, datetime

import pytest
from starlette.requests import Request

from megooarti.repositories.content import FileEntry, Stored, TooLarge
from megooarti.repositories.formats import ComponentKey, Format
from tests.repositories.conftest import body, someone

EVERYTHING = someone("repository:raw:files")
WHEN = datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC)
DOCUMENT = b"<metadata>generated</metadata>"


class Packaged(Format):
    """Files at namespace/name/version/file belong to a package; others to none."""

    name = "raw"

    def describe_component(self, path):
        parts = path.split("/")
        return ComponentKey(*parts[:3]) if len(parts) == 4 else None


def request(method: str = "GET", **headers: str) -> Request:
    raw = [(name.replace("_", "-").encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "method": method, "path": "/", "headers": raw})


@pytest.fixture
async def context(files, context_for):
    made = await context_for(files, EVERYTHING)
    made.format = Packaged()
    return made


def answer(context, incoming: Request):
    return context.respond_with(
        DOCUMENT,
        incoming,
        filename="maven-metadata.xml",
        content_type="application/xml",
        last_modified=WHEN,
    )


async def test_stat_describes_what_is_at_a_path(context):
    asset, _ = await context.put("acme/app/1.0/app.jar", body(b"jar bytes"))

    stored = await context.stat("acme/app/1.0/app.jar")

    assert stored == Stored(
        path="acme/app/1.0/app.jar",
        kind="asset",
        size=9,
        md5=hashlib.md5(b"jar bytes").hexdigest(),
        sha1=hashlib.sha1(b"jar bytes").hexdigest(),
        sha256=hashlib.sha256(b"jar bytes").hexdigest(),
        sha512=hashlib.sha512(b"jar bytes").hexdigest(),
        content_type=asset.content_type,
        modified=asset.updated_at,
    )
    assert await context.stat("acme/app/1.0/missing.jar") is None


async def test_versions_lists_each_version_with_its_latest_change(context):
    first, _ = await context.put("acme/app/1.0/app.jar", body(b"a"))
    second, _ = await context.put("acme/app/1.0/app.pom", body(b"b"))
    third, _ = await context.put("acme/app/2.0/app.jar", body(b"c"))
    await context.put("acme/other/9.0/other.jar", body(b"d"))
    await context.put("elsewhere/app/7.0/app.jar", body(b"e"))

    versions = await context.versions("acme", "app")

    assert versions == {
        "1.0": max(first.updated_at, second.updated_at),
        "2.0": third.updated_at,
    }
    assert await context.versions("acme", "nothing") == {}


async def test_files_lists_the_files_of_one_version(context):
    jar, _ = await context.put("acme/app/1.0/app.jar", body(b"a"))
    pom, _ = await context.put("acme/app/1.0/app.pom", body(b"b"))
    await context.put("acme/app/2.0/app.jar", body(b"c"))

    assert await context.files("acme", "app", "1.0") == [
        FileEntry("acme/app/1.0/app.jar", jar.updated_at),
        FileEntry("acme/app/1.0/app.pom", pom.updated_at),
    ]
    assert await context.files("acme", "app", "3.0") == []


async def test_names_says_which_packages_exist_in_a_namespace(context):
    await context.put("acme/app/1.0/app.jar", body(b"a"))
    await context.put("acme/tool/1.0/tool.jar", body(b"b"))

    assert await context.names("acme", ["app", "tool", "ghost"]) == {"app", "tool"}
    assert await context.names("acme", []) == set()
    assert await context.names("other", ["app"]) == set()


async def test_read_returns_a_small_file_and_refuses_a_large_one(context):
    await context.put("notes.txt", body(b"x" * 2000))

    assert await context.read("notes.txt", limit=2000) == b"x" * 2000
    assert await context.read("missing.txt", limit=2000) is None
    with pytest.raises(TooLarge):
        await context.read("notes.txt", limit=1999)


async def test_receive_reads_a_small_upload_and_gives_up_on_a_large_one(context):
    assert await context.receive(body(b"y" * 1500), limit=1500) == b"y" * 1500
    assert await context.receive(body(b"y" * 1501), limit=1500) is None
    assert await context.receive(body(b""), limit=10) == b""


async def test_generated_bytes_are_answered_like_a_stored_file(context):
    response = answer(context, request())

    digest = hashlib.sha256(DOCUMENT).hexdigest()
    assert (response.status_code, response.body) == (200, DOCUMENT)
    assert response.headers["ETag"] == f'"{digest}"'
    assert response.headers["X-Checksum-Sha1"] == hashlib.sha1(DOCUMENT).hexdigest()
    assert response.headers["Content-Type"] == "application/xml"
    assert response.headers["Content-Length"] == str(len(DOCUMENT))
    assert response.headers["Last-Modified"] == "Wed, 04 Mar 2026 05:06:07 GMT"
    assert response.headers["Content-Disposition"].startswith(
        'attachment; filename="maven-metadata.xml"'
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox"


async def test_generated_bytes_honour_head_conditions_and_ranges(context):
    etag = answer(context, request()).headers["ETag"]

    head = answer(context, request("HEAD"))
    unchanged = answer(context, request(if_none_match=etag))
    partial = answer(context, request(range="bytes=1-8"))

    assert (head.status_code, head.body) == (200, b"")
    assert head.headers["Content-Length"] == str(len(DOCUMENT))
    assert (unchanged.status_code, unchanged.body) == (304, b"")
    assert (partial.status_code, partial.body) == (206, DOCUMENT[1:9])
    assert partial.headers["Content-Range"] == f"bytes 1-8/{len(DOCUMENT)}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_reads.py -q`
Expected: collection error, `cannot import name 'FileEntry' from 'megooarti.repositories.content'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/content.py`, change these imports:

```python
from collections.abc import AsyncIterator, Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
```

Add, after the `_verify` function and before `class RepositoryContext`:

```python
@dataclass(frozen=True)
class Stored:
    """What is at a path, as plain values a format may read."""

    path: str
    kind: str
    size: int
    md5: str
    sha1: str
    sha256: str
    sha512: str
    content_type: str
    modified: datetime


@dataclass(frozen=True)
class FileEntry:
    path: str
    modified: datetime


class TooLarge(Exception):
    """A file that was to be read into memory is larger than the caller allows."""
```

Add these methods to `RepositoryContext`, after `get`:

```python
    async def stat(self, path: str) -> Stored | None:
        """What is at a path, read from the database now."""
        row = (
            await self.db.execute(
                select(
                    Asset.kind,
                    Asset.content_type,
                    Asset.updated_at,
                    Blob.size,
                    Blob.md5,
                    Blob.sha1,
                    Blob.sha256,
                    Blob.sha512,
                )
                .join(Blob, Blob.id == Asset.blob_id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if row is None:
            return None
        return Stored(
            path=path,
            kind=row.kind,
            size=row.size,
            md5=row.md5,
            sha1=row.sha1,
            sha256=row.sha256,
            sha512=row.sha512,
            content_type=row.content_type,
            modified=row.updated_at,
        )

    async def versions(self, namespace: str, name: str) -> dict[str, datetime]:
        """Each version of a package that has a file, with when its files last changed."""
        rows = await self.db.execute(
            select(Component.version, func.max(Asset.updated_at))
            .join(Asset, Asset.component_id == Component.id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
            )
            .group_by(Component.version)
        )
        return {version: changed for version, changed in rows}

    async def files(self, namespace: str, name: str, version: str) -> list[FileEntry]:
        """The files of one version of a package, ordered by path."""
        rows = await self.db.execute(
            select(Asset.path, Asset.updated_at)
            .join(Component, Component.id == Asset.component_id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
                Component.version == version,
            )
            .order_by(Asset.path)
        )
        return [FileEntry(path, changed) for path, changed in rows]

    async def names(self, namespace: str, candidates: Collection[str]) -> set[str]:
        """Which of `candidates` are packages in `namespace`."""
        if not candidates:
            return set()
        rows = await self.db.scalars(
            select(Component.name)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name.in_(candidates),
            )
            .distinct()
        )
        return set(rows)

    async def read(self, path: str, *, limit: int) -> bytes | None:
        """A stored file's bytes, for a small document a format must look inside.

        The limit is what makes it acceptable to hold the connection meanwhile.
        """
        row = (
            await self.db.execute(
                select(Blob.sha256, Blob.size)
                .join(Asset, Asset.blob_id == Blob.id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if row is None:
            return None
        if row.size > limit:
            raise TooLarge(path)
        return b"".join([chunk async for chunk in self.backend.open(row.sha256)])

    async def receive(self, chunks: AsyncIterator[bytes], *, limit: int) -> bytes | None:
        """A small upload, read into memory. None if it is longer than `limit`."""
        await self.db.commit()  # give the connection back while the body arrives
        received = bytearray()
        async for chunk in chunks:
            received += chunk
            if len(received) > limit:
                return None
        return bytes(received)

    def respond_with(
        self,
        data: bytes,
        request: Request,
        *,
        filename: str,
        content_type: str,
        last_modified: datetime,
    ) -> Response:
        """Answer a GET or HEAD with bytes made for this request.

        The same planning as for a stored file, so the headers, conditions and ranges
        are the same too.
        """
        item = serving.Servable(
            sha256=hashlib.sha256(data).hexdigest(),
            md5=hashlib.md5(data).hexdigest(),
            sha1=hashlib.sha1(data).hexdigest(),
            sha512=hashlib.sha512(data).hexdigest(),
            size=len(data),
            content_type=content_type,
            last_modified=last_modified,
            filename=filename,
        )
        plan = serving.plan(request.method, request.headers, item)
        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return Response(
            content=data[start : end + 1], status_code=plan.status, headers=plan.headers
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/test_content_reads.py tests/repositories/test_content.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/content.py backend/tests/repositories/test_content_reads.py
git commit -m "feat(repositories): read operations and generated responses on the context"
```

---

### Task 3: Core: uploads that store nothing, and server-maintained documents

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py`
- Test: `backend/tests/repositories/test_content_maintain.py`

**Interfaces:**
- Consumes: Task 2's `stat` and `read`; `_record`, `_lock`, `_check_policy`, `blobs.dereference`.
- Produces:
  - `context.require_write() -> None` — not a coroutine. Raises `401`/`403` unless the principal has `add` or `edit`; raises `403 repository_read_only` on a read-only repository.
  - `await context.maintain(path: str, update: Callable[[bytes | None], Awaitable[bytes | None]], *, content_type: str, limit: int) -> None` — calls `require_write`, locks the path, passes the stored bytes (or `None`) to `update`, and stores what it returns with kind `metadata` and no component. A `None` result removes the document. Raises `409 conflict` if the path holds a file of another kind. Does not commit.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_maintain.py`:

```python
import pytest
from sqlalchemy import func, select

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.models import Asset
from tests.repositories.conftest import body, someone

ADD = someone("repository:raw:files:add")
EDIT = someone("repository:raw:files:edit")
READ = someone("repository:raw:files:read")
PATH = "acme/maven-metadata.xml"
XML = "application/xml"


def becomes(wanted: bytes | None):
    """An update that ignores what is stored."""

    async def update(current: bytes | None) -> bytes | None:
        return wanted

    return update


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


async def hosted(db, name: str, policy: str):
    return await service.create_repository(
        db,
        name=name,
        format="raw",
        type="hosted",
        online=True,
        blob_store="default",
        hosted={"deployment_policy": policy},
        format_config={},
    )


@pytest.mark.parametrize("principal", [ADD, EDIT])
async def test_adding_or_editing_is_enough_to_write(files, context_for, principal):
    (await context_for(files, principal)).require_write()


async def test_reading_is_not_enough_to_write(files, context_for):
    readers = await context_for(files, READ)
    nobody = await context_for(files, None)

    with pytest.raises(ApiError) as forbidden:
        readers.require_write()
    with pytest.raises(ApiError) as unauthorised:
        nobody.require_write()

    assert (forbidden.value.status_code, forbidden.value.code) == (403, "forbidden")
    assert unauthorised.value.status_code == 401


async def test_nothing_is_written_to_a_read_only_repository(db, context_for):
    locked = await hosted(db, "locked", "read_only")
    context = await context_for(locked, someone("repository:raw:locked"))

    with pytest.raises(ApiError) as caught:
        context.require_write()

    assert (caught.value.status_code, caught.value.code) == (403, "repository_read_only")


async def test_maintain_stores_a_document_of_the_metadata_kind(files, context_for):
    context = await context_for(files, ADD)
    seen = []

    async def update(current: bytes | None) -> bytes | None:
        seen.append(current)
        return b"<plugins/>"

    await context.maintain(PATH, update, content_type=XML, limit=1000)

    stored = await context.stat(PATH)
    asset = await context.get(PATH)
    assert seen == [None]
    assert (stored.kind, stored.content_type, stored.size) == ("metadata", XML, 10)
    assert await context.read(PATH, limit=1000) == b"<plugins/>"
    assert (asset.component_id, asset.created_by) == (None, "dana")


async def test_maintain_hands_the_stored_bytes_to_the_update(files, context_for):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)
    seen = []

    async def update(current: bytes | None) -> bytes | None:
        seen.append(current)
        return current + b" two"

    await context.maintain(PATH, update, content_type=XML, limit=1000)

    assert seen == [b"one"]
    assert await context.read(PATH, limit=1000) == b"one two"


async def test_maintain_removes_the_document_when_the_update_returns_nothing(
    db, files, context_for
):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)

    await context.maintain(PATH, becomes(None), content_type=XML, limit=1000)
    await context.maintain(PATH, becomes(None), content_type=XML, limit=1000)

    assert await context.stat(PATH) is None
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_an_unchanged_document_is_left_alone(files, context_for):
    context = await context_for(files, ADD)
    await context.maintain(PATH, becomes(b"same"), content_type=XML, limit=1000)
    before = (await context.stat(PATH)).modified

    await context.maintain(PATH, becomes(b"same"), content_type=XML, limit=1000)

    assert (await context.stat(PATH)).modified == before


async def test_maintain_replaces_despite_disable_redeploy_and_without_edit(db, context_for):
    once = await hosted(db, "once", "disable_redeploy")
    context = await context_for(once, someone("repository:raw:once:add"))
    await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)

    await context.maintain(PATH, becomes(b"two"), content_type=XML, limit=1000)

    assert await context.read(PATH, limit=1000) == b"two"


async def test_maintain_never_touches_a_file_that_is_not_metadata(files, context_for):
    context = await context_for(files, someone("repository:raw:files"))
    await context.put("acme/app.jar", body(b"an artifact"))

    replaced = await error_of(
        context.maintain("acme/app.jar", becomes(b"overwritten"), content_type=XML, limit=1000)
    )
    removed = await error_of(
        context.maintain("acme/app.jar", becomes(None), content_type=XML, limit=1000)
    )

    assert (replaced.status_code, replaced.code) == (409, "conflict")
    assert (removed.status_code, removed.code) == (409, "conflict")
    assert await context.read("acme/app.jar", limit=1000) == b"an artifact"


async def test_maintain_needs_permission_to_write(files, context_for):
    context = await context_for(files, READ)

    error = await error_of(context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000))

    assert error.status_code == 403
    assert await context.stat(PATH) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_maintain.py -q`
Expected: 11 failures, each `AttributeError: 'RepositoryContext' object has no attribute 'require_write'` or `'maintain'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/content.py`, change the first import to:

```python
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
```

Add after the `PROXY_CREATOR` line:

```python
# The kind of a document the server keeps on an uploader's behalf.
_MAINTAINED = "metadata"
_PIECE = 1024 * 1024
```

Add after the `_verify` function:

```python
async def _pieces(data: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(data), _PIECE):
        yield data[start : start + _PIECE]
```

In `_record`, add a keyword parameter `packaged: bool = True` after `verified_at`, and replace the line `key = self.format.describe_component(path)` with:

```python
            key = self.format.describe_component(path) if packaged else None
```

Add these methods to `RepositoryContext`, after `_check_may_store`:

```python
    def require_write(self) -> None:
        """Refuse a caller who may not change this repository's content at all.

        For an upload a format accepts without storing it as sent: it needs `add` or
        `edit`, and the repository must not be read-only.
        """
        try:
            authorize(self.principal, self.permission("add"), scheme="Basic")
        except ApiError:
            authorize(self.principal, self.permission("edit"), scheme="Basic")
        self._check_policy(replacing=False)
```

and after `cache`:

```python
    async def maintain(
        self,
        path: str,
        update: Callable[[bytes | None], Awaitable[bytes | None]],
        *,
        content_type: str,
        limit: int,
    ) -> None:
        """Change a document the server keeps on an uploader's behalf. The caller commits.

        `update` is given the stored bytes, or None, and returns what to store, or None
        to store nothing. It runs under the path lock, so two changes never overwrite
        each other. This needs `add` or `edit` and is not subject to `disable_redeploy`,
        because the uploader is not replacing anything they published. It refuses a
        path that holds any other kind of file, so it cannot overwrite an artifact.
        """
        path = normalise_path(path)
        self.require_write()
        await self._lock("path", path)
        existing = await self.get(path, fresh=True)
        if existing is not None and existing.kind != _MAINTAINED:
            raise ApiError(409, "conflict", "A file that is not metadata is stored at this path.")
        current = None if existing is None else await self.read(path, limit=limit)
        wanted = await update(current)
        if wanted == current:
            return
        if wanted is None:
            blob_id = existing.blob_id
            await self.db.delete(existing)
            await self.db.flush()
            await blobs.dereference(self.db, [blob_id], utcnow())
            return
        staged = await self.backend.stage(_pieces(wanted))
        await self._record(
            path,
            staged,
            content_type=content_type,
            kind=_MAINTAINED,
            checked=False,
            packaged=False,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/content.py backend/tests/repositories/test_content_maintain.py
git commit -m "feat(repositories): uploads that store nothing, and server-maintained documents"
```

---

### Task 4: Maven paths and uploaded checksums

**Files:**
- Create: `backend/src/megooarti/repositories/maven/__init__.py`
- Create: `backend/src/megooarti/repositories/maven/paths.py`
- Create: `backend/src/megooarti/repositories/maven/checksums.py`
- Create: `backend/tests/repositories/maven/__init__.py` (empty)
- Test: `backend/tests/repositories/maven/test_paths.py`
- Test: `backend/tests/repositories/maven/test_checksums.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `megooarti.repositories.maven.paths`:
  - Constants `CHECKSUM_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")`, `METADATA_FILE = "maven-metadata.xml"`, `CATALOG = "archetype-catalog.xml"`, `SNAPSHOT = "-SNAPSHOT"`, `VERSION_POLICIES = ("release", "snapshot", "mixed")`, `LAYOUT_POLICIES = ("strict", "permissive")`.
  - `MavenPath(kind, group_id="", artifact_id="", version="", classifier="", extension="", build=None, plugin_group="")` — frozen dataclass. `kind` is `"artifact"`, `"metadata"` (artifact-level), `"snapshot_metadata"` (version-level), `"catalog"` or `"other"`. `build` is `(timestamp, number)` for a timestamped snapshot file. For `"metadata"`, `group_id`/`artifact_id` are the directory read as an artifact (empty if it cannot be one) and `plugin_group` is the directory read as a group ID (empty if it cannot be one). Properties `is_metadata` and `is_snapshot`.
  - `split_checksum(path: str) -> tuple[str, str | None]` — the path a checksum belongs to and its algorithm, or `(path, None)`.
  - `classify(path: str) -> MavenPath` — for a path that is not a checksum path.
  - `allowed_by(version_policy: str, parsed: MavenPath) -> bool`
  - `content_type(path: str) -> str | None`
- Produces, in `megooarti.repositories.maven.checksums`:
  - `LIMIT = 1024`
  - `read_uploaded(body: bytes, algorithm: str) -> str | None` — the lower-case hex digest, or `None` if the body is not a checksum of that algorithm.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_paths.py`:

```python
import pytest

from megooarti.repositories.maven.paths import (
    MavenPath,
    allowed_by,
    classify,
    content_type,
    split_checksum,
)

BASE = "com/acme/app/1.0"
SNAP = "com/acme/app/1.0-SNAPSHOT"


def artifact(**fields) -> MavenPath:
    fields.setdefault("group_id", "com.acme")
    fields.setdefault("artifact_id", "app")
    fields.setdefault("version", "1.0")
    return MavenPath("artifact", **fields)


def snapshot(**fields) -> MavenPath:
    return artifact(version="1.0-SNAPSHOT", **fields)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"{BASE}/app-1.0.jar", artifact(extension="jar")),
        (f"{BASE}/app-1.0.pom", artifact(extension="pom")),
        (f"{BASE}/app-1.0-sources.jar", artifact(classifier="sources", extension="jar")),
        (f"{BASE}/app-1.0.tar.gz", artifact(extension="tar.gz")),
        (f"{BASE}/app-1.0-bin.tar.gz", artifact(classifier="bin", extension="tar.gz")),
        (f"{BASE}/app-1.0.jar.asc", artifact(extension="jar.asc")),
        ("acme/app/1.0/app-1.0.jar", artifact(group_id="acme", extension="jar")),
        (
            "com/acme/my.app/1.0.1/my.app-1.0.1.jar",
            artifact(artifact_id="my.app", version="1.0.1", extension="jar"),
        ),
        # A name that fits two readings is read the simplest way, never refused.
        (f"{BASE}/app-1.0.1.jar", artifact(extension="1.jar")),
        (
            "com/acme/app/1.0-20261008.101500-3/app-1.0-20261008.101500-3.jar",
            artifact(version="1.0-20261008.101500-3", extension="jar"),
        ),
    ],
)
def test_release_artifact_paths(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("app-1.0-20261008.101500-3.jar", snapshot(extension="jar", build=("20261008.101500", 3))),
        (
            "app-1.0-20261008.101500-3-sources.jar",
            snapshot(classifier="sources", extension="jar", build=("20261008.101500", 3)),
        ),
        (
            "app-1.0-20261008.101500-12.pom",
            snapshot(extension="pom", build=("20261008.101500", 12)),
        ),
        ("app-1.0-SNAPSHOT.jar", snapshot(extension="jar")),
        ("app-1.0-SNAPSHOT-sources.jar", snapshot(classifier="sources", extension="jar")),
    ],
)
def test_snapshot_artifact_paths(name, expected):
    assert classify(f"{SNAP}/{name}") == expected
    assert classify(f"{SNAP}/{name}").is_snapshot is True


@pytest.mark.parametrize(
    "path",
    [
        "app/1.0/app-1.0.jar",  # no group directory
        f"{BASE}/other-1.0.jar",
        f"{BASE}/app-2.0.jar",
        f"{BASE}/app-1.0",
        f"{BASE}/app-1.0.",
        f"{BASE}/app-1.0-.jar",
        f"{BASE}/app-1.0jar",
        "com.acme/app/1.0/app-1.0.jar",  # a dot in a group directory
        f"{SNAP}/app-1.0-2026-1.jar",
        f"{SNAP}/app-1.0-SNAPSHOTS.jar",
        f"{SNAP}/app-1.0-٢٠٢٦١٠٠٨.١٠١٥٠٠-٣.jar",  # digits, but not ASCII ones
        "com/acme/app/-SNAPSHOT/app--SNAPSHOT.jar",
        f"com/acme/app/{'9' * 256}/app-{'9' * 256}.jar",  # longer than a version may be
        "notes/readme.txt",
        "maven-metadata.xml",
        "deep/archetype-catalog.xml",
        "com.acme/app/maven-metadata.xml",
        "com.acme/app/1.0-SNAPSHOT/maven-metadata.xml",
    ],
)
def test_paths_outside_the_layout_are_other(path):
    assert classify(path) == MavenPath("other")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "com/acme/app/maven-metadata.xml",
            MavenPath(
                "metadata", group_id="com.acme", artifact_id="app", plugin_group="com.acme.app"
            ),
        ),
        ("com/maven-metadata.xml", MavenPath("metadata", plugin_group="com")),
        (
            "com/acme/my.app/maven-metadata.xml",
            MavenPath("metadata", group_id="com.acme", artifact_id="my.app"),
        ),
        (
            f"{SNAP}/maven-metadata.xml",
            MavenPath(
                "snapshot_metadata", group_id="com.acme", artifact_id="app", version="1.0-SNAPSHOT"
            ),
        ),
        # Too shallow to be a version directory: an artifact that happens to be named so.
        (
            "app/1.0-SNAPSHOT/maven-metadata.xml",
            MavenPath("metadata", group_id="app", artifact_id="1.0-SNAPSHOT"),
        ),
    ],
)
def test_metadata_paths(path, expected):
    assert classify(path) == expected
    assert classify(path).is_metadata is True


def test_the_catalog_is_only_at_the_root():
    assert classify("archetype-catalog.xml") == MavenPath("catalog")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/b/app-1.0.jar.md5", ("a/b/app-1.0.jar", "md5")),
        ("a/b/app-1.0.jar.sha1", ("a/b/app-1.0.jar", "sha1")),
        ("a/b/app-1.0.jar.sha256", ("a/b/app-1.0.jar", "sha256")),
        ("a/b/app-1.0.jar.sha512", ("a/b/app-1.0.jar", "sha512")),
        ("a/b/maven-metadata.xml.sha1", ("a/b/maven-metadata.xml", "sha1")),
        ("a/b/app-1.0.jar", ("a/b/app-1.0.jar", None)),
        ("a/b/app-1.0.jar.SHA1", ("a/b/app-1.0.jar.SHA1", None)),
        ("a/b/.sha1", ("a/b/.sha1", None)),
        (".md5", (".md5", None)),
    ],
)
def test_a_checksum_path_names_its_file_and_algorithm(path, expected):
    assert split_checksum(path) == expected


RELEASE = classify(f"{BASE}/app-1.0.jar")
SNAPSHOT_FILE = classify(f"{SNAP}/app-1.0-SNAPSHOT.jar")
ARTIFACT_LEVEL = classify("com/acme/app/maven-metadata.xml")
VERSION_LEVEL = classify(f"{SNAP}/maven-metadata.xml")


@pytest.mark.parametrize(
    ("policy", "parsed", "allowed"),
    [
        ("release", RELEASE, True),
        ("release", SNAPSHOT_FILE, False),
        ("release", ARTIFACT_LEVEL, True),
        ("release", VERSION_LEVEL, False),
        ("release", MavenPath("other"), True),
        ("release", MavenPath("catalog"), True),
        ("snapshot", RELEASE, False),
        ("snapshot", SNAPSHOT_FILE, True),
        ("snapshot", ARTIFACT_LEVEL, True),
        ("snapshot", VERSION_LEVEL, True),
        ("snapshot", MavenPath("other"), True),
        ("mixed", RELEASE, True),
        ("mixed", SNAPSHOT_FILE, True),
        ("mixed", VERSION_LEVEL, True),
    ],
)
def test_the_version_policy(policy, parsed, allowed):
    assert allowed_by(policy, parsed) is allowed


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("a/app-1.0.pom", "application/xml"),
        ("a/maven-metadata.xml", "application/xml"),
        ("a/app-1.0.jar", "application/java-archive"),
        ("a/app-1.0.war", "application/java-archive"),
        ("a/app-1.0.module", "application/json"),
        ("a/app-1.0.jar.asc", "text/plain"),
        ("a/app-1.0.zip", None),
        ("a/no-extension", None),
    ],
)
def test_content_types_for_the_files_maven_uses(path, expected):
    assert content_type(path) == expected
```

`backend/tests/repositories/maven/test_checksums.py`:

```python
import pytest

from megooarti.repositories.maven.checksums import read_uploaded

SHA1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
MD5 = "d41d8cd98f00b204e9800998ecf8427e"


@pytest.mark.parametrize(
    "body",
    [
        SHA1.encode(),
        SHA1.encode() + b"\n",
        SHA1.upper().encode(),
        f"{SHA1}  app-1.0.jar\n".encode(),
        f"{SHA1} *app-1.0.jar\r\n".encode(),
        f"SHA1(app-1.0.jar)= {SHA1}\n".encode(),
        f"SHA1 (my app.jar) = {SHA1}".encode(),
        f"\n\n  {SHA1}\r\n".encode(),
        b"\xef\xbb\xbf" + SHA1.encode(),
    ],
)
def test_the_ways_tools_write_a_checksum_are_all_read(body):
    assert read_uploaded(body, "sha1") == SHA1


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"   \n",
        b"not a checksum",
        SHA1[:-1].encode(),
        (SHA1 + "0").encode(),
        ("z" * 40).encode(),
        ("٣" * 40).encode(),
        b"\xff\xfe\x00",
    ],
)
def test_anything_else_is_not_a_checksum(body):
    assert read_uploaded(body, "sha1") is None


def test_the_length_must_fit_the_algorithm():
    assert read_uploaded(MD5.encode(), "md5") == MD5
    assert read_uploaded(MD5.encode(), "sha1") is None
    assert read_uploaded(b"a" * 64, "sha256") == "a" * 64
    assert read_uploaded(b"a" * 128, "sha512") == "a" * 128
    assert read_uploaded(b"a" * 64, "sha512") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven -q`
Expected: collection errors, `No module named 'megooarti.repositories.maven'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/maven/__init__.py`:

```python
"""The Maven format."""
```

`backend/src/megooarti/repositories/maven/paths.py`:

```python
"""Maven repository paths: what kind of path this is, and whose file.

Pure functions over the Maven 2 repository layout:
<group dirs>/<artifactId>/<version>/<artifactId>-<version>[-<classifier>].<extension>
"""

import re
from dataclasses import dataclass

CHECKSUM_ALGORITHMS = ("md5", "sha1", "sha256", "sha512")
METADATA_FILE = "maven-metadata.xml"
CATALOG = "archetype-catalog.xml"
SNAPSHOT = "-SNAPSHOT"
VERSION_POLICIES = ("release", "snapshot", "mixed")
LAYOUT_POLICIES = ("strict", "permissive")

# What the component table can hold.
_MAX_VERSION_LENGTH = 255
# The timestamp and build number in a snapshot file name: 20261008.101500-3
_BUILD = re.compile(r"([0-9]{8}\.[0-9]{6})-([0-9]{1,9})")
_CONTENT_TYPES = {
    "pom": "application/xml",
    "xml": "application/xml",
    "jar": "application/java-archive",
    "war": "application/java-archive",
    "ear": "application/java-archive",
    "module": "application/json",
    "asc": "text/plain",
}


@dataclass(frozen=True)
class MavenPath:
    """A path, classified. Fields that do not apply to its kind are left empty."""

    kind: str  # artifact, metadata, snapshot_metadata, catalog or other
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""  # the version directory: 1.0 or 1.0-SNAPSHOT
    classifier: str = ""
    extension: str = ""
    build: tuple[str, int] | None = None  # timestamp and number of a timestamped snapshot
    plugin_group: str = ""  # metadata only: the directory read as a group ID

    @property
    def is_metadata(self) -> bool:
        return self.kind in ("metadata", "snapshot_metadata")

    @property
    def is_snapshot(self) -> bool:
        return self.version.endswith(SNAPSHOT)


_OTHER = MavenPath("other")


def split_checksum(path: str) -> tuple[str, str | None]:
    """The path a checksum file belongs to, and its algorithm; `(path, None)` if not one."""
    target, dot, suffix = path.rpartition(".")
    if dot and target and not target.endswith("/") and suffix in CHECKSUM_ALGORITHMS:
        return target, suffix
    return path, None


def _group_id(directories: list[str]) -> str | None:
    """Directories as a group ID. A dot in one would make two paths share a group ID."""
    if not directories or any("." in directory for directory in directories):
        return None
    return ".".join(directories)


def _is_snapshot_version(version: str) -> bool:
    return version.endswith(SNAPSHOT) and len(version) > len(SNAPSHOT)


def _metadata(directories: list[str]) -> MavenPath | None:
    if not directories:
        return None
    if len(directories) >= 3 and _is_snapshot_version(directories[-1]):
        group_id = _group_id(directories[:-2])
        if group_id is None or len(directories[-1]) > _MAX_VERSION_LENGTH:
            return None
        return MavenPath(
            "snapshot_metadata",
            group_id=group_id,
            artifact_id=directories[-2],
            version=directories[-1],
        )
    # The same directory can be an artifact (com.acme:app) and a group (com.acme.app).
    as_artifact = _group_id(directories[:-1])
    as_group = _group_id(directories)
    if as_artifact is None and as_group is None:
        return None
    return MavenPath(
        "metadata",
        group_id=as_artifact or "",
        artifact_id=directories[-1] if as_artifact else "",
        plugin_group=as_group or "",
    )


def _artifact(segments: list[str]) -> MavenPath | None:
    if len(segments) < 4:
        return None
    *directories, artifact_id, version, filename = segments
    group_id = _group_id(directories)
    if group_id is None or len(version) > _MAX_VERSION_LENGTH:
        return None

    build = None
    if version.endswith(SNAPSHOT):
        if not _is_snapshot_version(version):
            return None
        prefix = f"{artifact_id}-{version.removesuffix(SNAPSHOT)}-"
        if not filename.startswith(prefix):
            return None
        rest = filename[len(prefix) :]
        timestamped = _BUILD.match(rest)
        if timestamped is not None:
            build = (timestamped[1], int(timestamped[2]))
            rest = rest[timestamped.end() :]
        elif rest.startswith("SNAPSHOT"):
            rest = rest.removeprefix("SNAPSHOT")
        else:
            return None
    else:
        prefix = f"{artifact_id}-{version}"
        if not filename.startswith(prefix):
            return None
        rest = filename[len(prefix) :]

    # What is left is "-classifier.extension" or ".extension".
    if rest.startswith("-"):
        classifier, dot, extension = rest[1:].partition(".")
        if not classifier:
            return None
    elif rest.startswith("."):
        classifier, dot, extension = "", ".", rest[1:]
    else:
        return None
    if not dot or not extension:
        return None
    return MavenPath(
        "artifact",
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        classifier=classifier,
        extension=extension,
        build=build,
    )


def classify(path: str) -> MavenPath:
    """What a path is. For a checksum path, classify the path it belongs to."""
    if path == CATALOG:
        return MavenPath("catalog")
    segments = path.split("/")
    if segments[-1] == METADATA_FILE:
        return _metadata(segments[:-1]) or _OTHER
    return _artifact(segments) or _OTHER


def allowed_by(version_policy: str, parsed: MavenPath) -> bool:
    """Whether a repository with this version policy holds such a path."""
    if parsed.kind not in ("artifact", "snapshot_metadata") or version_policy == "mixed":
        return True
    return (version_policy == "snapshot") == parsed.is_snapshot


def content_type(path: str) -> str | None:
    """The content type for a file Maven uses, by its last extension."""
    return _CONTENT_TYPES.get(path.rpartition(".")[2])
```

`backend/src/megooarti/repositories/maven/checksums.py`:

```python
"""Reading a checksum file a client uploaded."""

import re

LIMIT = 1024

_DIGEST_LENGTH = {"md5": 32, "sha1": 40, "sha256": 64, "sha512": 128}
_HEX = frozenset("0123456789abcdef")
# The BSD style: "SHA1(file)= <digest>".
_LABELLED = re.compile(r".+= [0-9A-Fa-f]+")


def read_uploaded(body: bytes, algorithm: str) -> str | None:
    """The digest in an uploaded checksum file, in lower case, or None if there is none.

    Read the way Maven reads these files: the first line that is not blank; in it, the
    text after "= " if the line has that form, otherwise the first word.
    """
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if _LABELLED.fullmatch(line):
        word = line.rpartition(" ")[2]
    else:
        word = line.partition(" ")[0]
    word = word.lower()
    if len(word) != _DIGEST_LENGTH[algorithm] or not _HEX.issuperset(word):
        return None
    return word
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/maven backend/tests/repositories/maven
git commit -m "feat(maven): classify repository paths and read uploaded checksums"
```

---

### Task 5: Maven version order

**Files:**
- Create: `backend/src/megooarti/repositories/maven/versions.py`
- Test: `backend/tests/repositories/maven/test_versions.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `megooarti.repositories.maven.versions`:
  - `compare(left: str, right: str) -> int` — `-1`, `0` or `1`. Never raises, whatever the text.
  - `sorted_versions(versions: Iterable[str]) -> list[str]` — distinct versions, oldest first; versions that compare equal are in text order.

The rules, from Maven's [Version Order Specification](https://maven.apache.org/pom.html#version-order-specification): a version is split at dots, hyphens and changes between digits and letters; a change between digits and letters acts as a hyphen; an empty part is `0`; trailing "null" parts (`0`, the empty qualifier, `final`, `ga`, `release`) are trimmed, at the end and before each hyphen. Parts are then compared in turn: numbers by value; qualifiers in the order `alpha` < `beta` < `milestone` < `rc` = `cr` < `snapshot` < (empty) < `sp` < any other, alphabetically; a qualifier is older than a number after a hyphen, which is older than a number after a dot. `a`, `b` and `m` mean `alpha`, `beta` and `milestone` when a digit follows directly.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_versions.py`:

```python
from itertools import pairwise

import pytest

from megooarti.repositories.maven.versions import compare, sorted_versions

EQUAL = [
    ("1", "1.0"),
    ("1", "1.0.0"),
    ("1.0", "1-0"),
    ("1", "1-ga"),
    ("1", "1-final"),
    ("1", "1.ga"),
    ("1.0", "1.0-release"),
    ("1.0", "1."),
    ("1.0", "1-"),
    ("1.0-alpha1", "1.0-a1"),
    ("1.0-alpha1", "1.0-alpha-1"),
    ("1.0-beta1", "1.0-b1"),
    ("1.0-milestone1", "1.0-m1"),
    ("1.0-rc1", "1.0-cr1"),
    ("1.0-RC1", "1.0-rc1"),
    ("1.0-SNAPSHOT", "1.0-snapshot"),
    ("1.0.0-foo.0.0", "1-foo"),
    ("1.0.0-0.0.0", "1"),
    # A qualifier after a dot is the same as one after a hyphen.
    ("1.foo", "1-foo"),
    ("1.0.RC1", "1.0-RC1"),
    ("5.0.0.Final", "5.0.0"),
    ("1.2.3.RELEASE", "1.2.3"),
]

OLDER_THEN_NEWER = [
    ("1", "2"),
    ("1.5", "2"),
    ("1", "2.5"),
    ("1.0", "1.1"),
    ("1.1", "1.2"),
    ("1.0.0", "1.1"),
    ("1.0.1", "1.1"),
    ("1.1", "1.2.0"),
    ("1.9", "1.10"),
    ("1.0-alpha-1", "1.0"),
    ("1.0-alpha-1", "1.0-alpha-2"),
    ("1.0-alpha-1", "1.0-beta-1"),
    ("1.0-beta-1", "1.0-milestone-1"),
    ("1.0-milestone-1", "1.0-rc-1"),
    ("1.0-rc-1", "1.0-SNAPSHOT"),
    ("1.0-SNAPSHOT", "1.0"),
    ("1.0-alpha-1-SNAPSHOT", "1.0-alpha-1"),
    ("1.0-SNAPSHOT", "1.1-SNAPSHOT"),
    ("1.0", "1.0-1"),
    ("1.0-1", "1.0-2"),
    ("1.0.0", "1.0-1"),
    ("2.0-1", "2.0.1"),
    ("2.0.1-klm", "2.0.1-lmn"),
    ("2.0.1", "2.0.1-xyz"),
    ("2.0.1", "2.0.1-123"),
    ("2.0.1-xyz", "2.0.1-123"),
    ("1.0", "1.0-sp"),
    ("1.0-sp", "1.0-sp1"),
    ("1.0-sp", "1.0-xyz"),
    ("1-foo2", "1-foo10"),
    ("1-foo", "1-1"),
    ("1-1", "1.1"),
    ("1-ga.1", "1-sp.1"),
    ("1-sp-1", "1-ga-1"),
    ("4.1.0.Beta1", "4.1.0.Final"),
    ("1.0.RC1", "1.0.RC2"),
]


@pytest.mark.parametrize(("left", "right"), EQUAL)
def test_versions_that_differ_only_in_form_are_equal(left, right):
    assert compare(left, right) == 0
    assert compare(right, left) == 0


@pytest.mark.parametrize(("older", "newer"), OLDER_THEN_NEWER)
def test_an_older_version_sorts_before_a_newer_one(older, newer):
    assert compare(older, newer) == -1
    assert compare(newer, older) == 1


def test_the_qualifier_order():
    ordered = [
        "1-alpha2",
        "1-beta-2",
        "1-m2",
        "1-m11",
        "1-rc",
        "1-cr2",
        "1-rc123",
        "1-SNAPSHOT",
        "1",
        "1-sp",
        "1-sp2",
        "1-abc",
        "1-def",
        "1-1",
        "1-2",
        "1-123",
    ]

    for older, newer in pairwise(ordered):
        assert compare(older, newer) == -1, (older, newer)


def test_sorting_is_by_version_not_by_text():
    shuffled = ["1.10", "1.9", "1.0", "1.2-SNAPSHOT", "1.2", "1.0-rc1"]

    assert sorted_versions(shuffled) == ["1.0-rc1", "1.0", "1.2-SNAPSHOT", "1.2", "1.9", "1.10"]


def test_equal_versions_are_kept_apart_in_text_order():
    assert sorted_versions(["1.0.0", "1", "1.0", "1"]) == ["1", "1.0", "1.0.0"]


@pytest.mark.parametrize(
    "odd",
    ["", "-", ".", "..", "--", "RELEASE", "latest", "1..2", "1--2", "ünïcode", "٣.٤", "v1.0", "00"]
    + ["9" * 255, "1-" * 127, "a1" * 127],
)
def test_any_text_can_be_compared(odd):
    assert compare(odd, odd) == 0
    assert compare(odd, "1.0") in (-1, 0, 1)
    assert compare("1.0", odd) == -compare(odd, "1.0")
    assert set(sorted_versions([odd, "1.0"])) == {odd, "1.0"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_versions.py -q`
Expected: collection error, `No module named 'megooarti.repositories.maven.versions'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/maven/versions.py`:

```python
"""Maven's version order.

Written from the Version Order Specification in the Maven POM reference
(https://maven.apache.org/pom.html#version-order-specification).

A version is parsed into a list of numbers and qualifiers. A hyphen, a change between
digits and letters, and any qualifier each open a nested list, so that "1.0-rc1",
"1.0.rc1" and "1.0-rc-1" all become [1, ["rc", [1]]] once trailing zeros are trimmed.
Nesting is what makes "1-1" (a list after the 1) older than "1.1" (a number after it).
"""

from collections.abc import Iterable
from functools import cmp_to_key

# Oldest first. The empty qualifier is a plain release.
_QUALIFIERS = ("alpha", "beta", "milestone", "rc", "snapshot", "", "sp")
_ALIASES = {"ga": "", "final": "", "release": "", "cr": "rc"}
# Only when a digit follows directly: 1.0-a1 is 1.0-alpha-1.
_SHORT = {"a": "alpha", "b": "beta", "m": "milestone"}

Item = int | str | list


def _qualifier(text: str, followed_by_digit: bool) -> str:
    if followed_by_digit:
        text = _SHORT.get(text, text)
    return _ALIASES.get(text, text)


def _rank(qualifier: str) -> tuple[int, str]:
    """Known qualifiers in their order, then every other one alphabetically."""
    if qualifier in _QUALIFIERS:
        return _QUALIFIERS.index(qualifier), ""
    return len(_QUALIFIERS), qualifier


def _is_null(item: Item) -> bool:
    return item in (0, "", [])


def _trim(items: list) -> None:
    """Drop trailing parts that mean nothing: "1.0.0" is "1"."""
    for index in range(len(items) - 1, -1, -1):
        if _is_null(items[index]):
            del items[index]
        elif not isinstance(items[index], list):
            break


def _parse(version: str) -> list:
    text = version.lower()
    items: list = []
    opened = [items]

    def descend() -> None:
        if opened[-1]:  # an empty list is still waiting for its first part
            nested: list = []
            opened[-1].append(nested)
            opened.append(nested)

    def add(piece: str, digits: bool, followed_by_digit: bool = False) -> None:
        if digits:
            opened[-1].append(int(piece))
        else:
            descend()  # ".rc" is "-rc"
            opened[-1].append(_qualifier(piece, followed_by_digit))

    digits = False
    start = 0
    for index, character in enumerate(text):
        if character in ".-":
            if index == start:
                opened[-1].append(0)
            else:
                add(text[start:index], digits)
            start = index + 1
            if character == "-":
                descend()
        elif character in "0123456789":
            if not digits and index > start:
                add(text[start:index], False, followed_by_digit=True)
                start = index
                descend()
            digits = True
        else:
            if digits and index > start:
                add(text[start:index], True)
                start = index
                descend()
            digits = False
    if len(text) > start:
        add(text[start:], digits)

    for nested in reversed(opened):
        _trim(nested)
    return items


def _sign(left, right) -> int:
    return (left > right) - (left < right)


def _compare(left: Item, right: Item | None) -> int:
    """Compare two parts. `right` is None where the other version has run out."""
    if isinstance(left, int):
        if right is None:
            return _sign(left, 0)
        if isinstance(right, int):
            return _sign(left, right)
        return 1  # a number after a dot is newer than a qualifier or a nested list
    if isinstance(left, str):
        if right is None:
            return _sign(_rank(left), _rank(""))
        if isinstance(right, str):
            return _sign(_rank(left), _rank(right))
        return -1  # a qualifier is older than a number or a nested list
    if right is None:
        return _compare(left[0], None) if left else 0
    if isinstance(right, int):
        return -1
    if isinstance(right, str):
        return 1
    for index in range(max(len(left), len(right))):
        ours = left[index] if index < len(left) else None
        theirs = right[index] if index < len(right) else None
        result = -_compare(theirs, None) if ours is None else _compare(ours, theirs)
        if result:
            return result
    return 0


def compare(left: str, right: str) -> int:
    """-1 if `left` is the older version, 1 if it is the newer, 0 if they are the same."""
    return _compare(_parse(left), _parse(right))


def sorted_versions(versions: Iterable[str]) -> list[str]:
    """Distinct versions, oldest first. Versions that are equal stay in text order."""
    parsed = {version: _parse(version) for version in versions}
    return sorted(
        sorted(parsed), key=cmp_to_key(lambda one, other: _compare(parsed[one], parsed[other]))
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven/test_versions.py -q`
Expected: all pass. If a pair fails, work it through the specification's rules before changing anything: the tests state the specification, and the implementation is what must follow it.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/maven/versions.py backend/tests/repositories/maven/test_versions.py
git commit -m "feat(maven): Maven's version order"
```

---

### Task 6: Maven metadata documents

**Files:**
- Create: `backend/src/megooarti/repositories/maven/metadata.py`
- Test: `backend/tests/repositories/maven/test_metadata.py`

**Interfaces:**
- Consumes: `paths.MavenPath`, `paths.SNAPSHOT`, `versions.sorted_versions`.
- Produces, in `megooarti.repositories.maven.metadata`:
  - `Plugin(name, prefix, artifact_id)`, `SnapshotVersion(classifier, extension, value, updated)` — frozen dataclasses of strings.
  - `Metadata(group_id="", artifact_id="", version="", versions=(), latest="", release="", snapshot_timestamp="", snapshot_build=None, snapshot_versions=(), last_updated="", plugins=())` — frozen dataclass; the sequences are tuples; `snapshot_build` is `int | None`; `last_updated` is `yyyyMMddHHmmss`.
  - `InvalidMetadata(Exception)` — its message completes the sentence "The metadata cannot be read: …".
  - `stamp(moment: datetime) -> str` — `yyyyMMddHHmmss` in UTC.
  - `for_artifact(group_id, artifact_id, versions: Mapping[str, datetime], plugins: Iterable[Plugin] = ()) -> Metadata | None` — `None` when there are neither versions nor plugins.
  - `for_snapshot(group_id, artifact_id, version, files: Iterable[tuple[MavenPath, datetime]]) -> Metadata | None` — `None` when there are no files.
  - `serialise(metadata: Metadata) -> bytes`
  - `parse(data: bytes) -> Metadata` — raises `InvalidMetadata`; refuses any `DOCTYPE`.
  - `merge_plugins(stored: Iterable[Plugin], uploaded: Iterable[Plugin]) -> tuple[Plugin, ...]` — by artifact ID, the uploaded entry winning; ordered by prefix, then artifact ID.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_metadata.py`:

```python
from datetime import UTC, datetime, timedelta, timezone

import pytest

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.metadata import (
    InvalidMetadata,
    Metadata,
    Plugin,
    SnapshotVersion,
)
from megooarti.repositories.maven.paths import classify

T1 = datetime(2026, 10, 8, 10, 15, 0, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
T3 = T1 + timedelta(hours=2)
SNAP = "com/acme/app/1.0-SNAPSHOT"

ARTIFACT = Metadata(
    group_id="com.acme",
    artifact_id="app",
    versions=("1.0", "1.1"),
    latest="1.1",
    release="1.1",
    last_updated="20261008101500",
)
SNAPSHOT = Metadata(
    group_id="com.acme",
    artifact_id="app",
    version="1.0-SNAPSHOT",
    snapshot_timestamp="20261008.101500",
    snapshot_build=3,
    snapshot_versions=(
        SnapshotVersion("", "jar", "1.0-20261008.101500-3", "20261008101500"),
        SnapshotVersion("sources", "jar", "1.0-20261008.101500-3", "20261008101500"),
    ),
    last_updated="20261008101500",
)
PLUGINS = Metadata(plugins=(Plugin("Acme Plugin", "acme", "acme-maven-plugin"),))


def entry(name: str, when: datetime):
    return classify(f"{SNAP}/{name}"), when


def snapshot_of(*entries) -> Metadata | None:
    return metadata.for_snapshot("com.acme", "app", "1.0-SNAPSHOT", entries)


def test_stamp_is_utc_to_the_second():
    east = timezone(timedelta(hours=3))

    assert metadata.stamp(datetime(2026, 10, 8, 13, 15, 59, 999, tzinfo=east)) == "20261008101559"


def test_artifact_metadata_lists_versions_in_maven_order():
    built = metadata.for_artifact("com.acme", "app", {"1.10": T1, "1.9": T3, "2.0-SNAPSHOT": T2})

    assert built == Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.9", "1.10", "2.0-SNAPSHOT"),
        latest="2.0-SNAPSHOT",
        release="1.10",
        last_updated=metadata.stamp(T3),
    )


def test_artifact_metadata_without_a_release_names_none():
    built = metadata.for_artifact("com.acme", "app", {"1.0-SNAPSHOT": T1})

    assert (built.latest, built.release) == ("1.0-SNAPSHOT", "")


def test_metadata_for_nothing_is_nothing():
    assert metadata.for_artifact("com.acme", "app", {}) is None
    assert snapshot_of() is None


def test_plugins_alone_make_a_group_document():
    built = metadata.for_artifact("com", "acme", {}, PLUGINS.plugins)

    assert built == PLUGINS


def test_an_artifact_that_is_also_a_group_carries_both():
    built = metadata.for_artifact("com", "acme", {"1.0": T1}, PLUGINS.plugins)

    assert (built.group_id, built.artifact_id, built.versions) == ("com", "acme", ("1.0",))
    assert built.plugins == PLUGINS.plugins


def test_snapshot_metadata_points_at_the_highest_build():
    built = snapshot_of(
        entry("app-1.0-20261008.101500-1.jar", T1),
        entry("app-1.0-20261008.101500-1.pom", T1),
        entry("app-1.0-20261008.101500-1-sources.jar", T1),
        entry("app-1.0-20261008.111500-2.jar", T2),
        entry("app-1.0-20261008.111500-2.pom", T2),
    )

    assert (built.group_id, built.artifact_id, built.version) == (
        "com.acme",
        "app",
        "1.0-SNAPSHOT",
    )
    assert (built.snapshot_timestamp, built.snapshot_build) == ("20261008.111500", 2)
    assert built.last_updated == metadata.stamp(T2)
    assert built.snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-20261008.111500-2", metadata.stamp(T2)),
        SnapshotVersion("", "pom", "1.0-20261008.111500-2", metadata.stamp(T2)),
        SnapshotVersion("sources", "jar", "1.0-20261008.101500-1", metadata.stamp(T1)),
    )


def test_the_build_number_decides_before_the_timestamp():
    built = snapshot_of(
        entry("app-1.0-20261008.120000-2.jar", T1),
        entry("app-1.0-20261008.090000-3.jar", T2),
    )

    assert (built.snapshot_timestamp, built.snapshot_build) == ("20261008.090000", 3)


def test_old_style_snapshot_names_are_listed_with_the_literal_version():
    built = snapshot_of(entry("app-1.0-SNAPSHOT.jar", T1), entry("app-1.0-SNAPSHOT.pom", T2))

    assert (built.snapshot_timestamp, built.snapshot_build) == ("", None)
    assert built.snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-SNAPSHOT", metadata.stamp(T1)),
        SnapshotVersion("", "pom", "1.0-SNAPSHOT", metadata.stamp(T2)),
    )


def test_a_timestamped_build_wins_over_an_old_style_name():
    built = snapshot_of(
        entry("app-1.0-SNAPSHOT.jar", T2), entry("app-1.0-20261008.101500-1.jar", T1)
    )

    assert built.snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-20261008.101500-1", metadata.stamp(T1)),
    )
    assert built.last_updated == metadata.stamp(T2)


def test_an_artifact_document_is_written_in_mavens_layout():
    assert metadata.serialise(ARTIFACT).decode() == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<metadata>\n"
        "  <groupId>com.acme</groupId>\n"
        "  <artifactId>app</artifactId>\n"
        "  <versioning>\n"
        "    <latest>1.1</latest>\n"
        "    <release>1.1</release>\n"
        "    <versions>\n"
        "      <version>1.0</version>\n"
        "      <version>1.1</version>\n"
        "    </versions>\n"
        "    <lastUpdated>20261008101500</lastUpdated>\n"
        "  </versioning>\n"
        "</metadata>\n"
    )


def test_a_snapshot_document_declares_the_newer_model():
    assert b'<metadata modelVersion="1.1.0">' in metadata.serialise(SNAPSHOT)
    assert b"<buildNumber>3</buildNumber>" in metadata.serialise(SNAPSHOT)
    assert b"modelVersion" not in metadata.serialise(ARTIFACT)


@pytest.mark.parametrize("original", [ARTIFACT, SNAPSHOT, PLUGINS])
def test_a_document_survives_being_written_and_read(original):
    assert metadata.parse(metadata.serialise(original)) == original


def test_special_characters_are_escaped():
    awkward = Metadata(plugins=(Plugin("A & B <plugin>", "ab", "ab-maven-plugin"),))

    written = metadata.serialise(awkward)

    assert b"A &amp; B &lt;plugin&gt;" in written
    assert metadata.parse(written) == awkward


WRITTEN_BY_MAVEN = b"""<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://maven.apache.org/METADATA/1.1.0"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <groupId>com.acme</groupId>
  <artifactId>app</artifactId>
  <versioning>
    <latest>1.1</latest>
    <release>1.1</release>
    <versions>
      <version> 1.0 </version>
      <version>1.1</version>
      <version></version>
    </versions>
    <lastUpdated>20261008101500</lastUpdated>
  </versioning>
  <plugins>
    <plugin>
      <name>Acme Plugin</name>
      <prefix>acme</prefix>
      <artifactId>acme-maven-plugin</artifactId>
    </plugin>
    <plugin>
      <name>No prefix</name>
      <artifactId>broken-plugin</artifactId>
    </plugin>
  </plugins>
</metadata>
"""


def test_a_document_written_by_maven_is_read():
    assert metadata.parse(WRITTEN_BY_MAVEN) == Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.0", "1.1"),
        latest="1.1",
        release="1.1",
        last_updated="20261008101500",
        plugins=PLUGINS.plugins,
    )


EXPANDING = b"""<?xml version="1.0"?>
<!DOCTYPE metadata [
  <!ENTITY a "aaaaaaaaaa">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
]>
<metadata><groupId>&b;</groupId></metadata>"""
EXTERNAL = b"""<!DOCTYPE metadata [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<metadata><groupId>&x;</groupId></metadata>"""


@pytest.mark.parametrize("document", [EXPANDING, EXTERNAL, b"<!DOCTYPE metadata><metadata/>"])
def test_a_document_with_a_doctype_is_refused(document):
    with pytest.raises(InvalidMetadata, match="DOCTYPE"):
        metadata.parse(document)


@pytest.mark.parametrize(
    "document",
    [
        b"",
        b"not xml",
        b"<metadata>",
        b"<metadata></wrong>",
        b"<project/>",
        b"\x00\x01\x02",
        "<metadata>".encode("utf-16"),
    ],
)
def test_a_document_that_is_not_metadata_is_refused(document):
    with pytest.raises(InvalidMetadata):
        metadata.parse(document)


def test_overlong_fields_are_ignored():
    long = "x" * 256
    document = (
        f"<metadata><groupId>{long}</groupId>"
        f"<versioning><versions><version>{long}</version><version>1.0</version></versions>"
        f"</versioning><plugins><plugin><prefix>{long}</prefix><artifactId>p</artifactId>"
        "</plugin></plugins></metadata>"
    )

    assert metadata.parse(document.encode()) == Metadata(versions=("1.0",))


@pytest.mark.parametrize(("written", "expected"), [("7", 7), ("seven", None), ("9" * 30, None)])
def test_a_build_number_must_be_a_small_number(written, expected):
    document = (
        "<metadata><versioning><snapshot><timestamp>20261008.101500</timestamp>"
        f"<buildNumber>{written}</buildNumber></snapshot></versioning></metadata>"
    )

    assert metadata.parse(document.encode()).snapshot_build == expected


def test_uploaded_plugins_replace_stored_ones_for_the_same_artifact():
    stored = (Plugin("Old", "old", "a-plugin"), Plugin("Kept", "kept", "b-plugin"))
    uploaded = (Plugin("New", "new", "a-plugin"), Plugin("Added", "added", "c-plugin"))

    assert metadata.merge_plugins(stored, uploaded) == (
        Plugin("Added", "added", "c-plugin"),
        Plugin("Kept", "kept", "b-plugin"),
        Plugin("New", "new", "a-plugin"),
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_metadata.py -q`
Expected: collection error, `cannot import name 'metadata' from 'megooarti.repositories.maven'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/maven/metadata.py`:

```python
"""maven-metadata.xml: build it from what a repository holds, read it safely, write it.

Pure functions. Reading uses expat directly so that any DOCTYPE is refused before an
entity can be declared: metadata never needs one, and entities are how XML is abused.
"""

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.parsers import expat

from megooarti.repositories.maven.paths import SNAPSHOT, MavenPath
from megooarti.repositories.maven.versions import sorted_versions

# Longer than any real coordinate; a field beyond it is ignored.
_MAX_FIELD = 255
_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n'


class InvalidMetadata(Exception):
    """The bytes are not a metadata document. The message says why."""


@dataclass(frozen=True)
class Plugin:
    name: str
    prefix: str
    artifact_id: str


@dataclass(frozen=True)
class SnapshotVersion:
    classifier: str
    extension: str
    value: str  # the version in the file name: 1.0-20261008.101500-3
    updated: str


@dataclass(frozen=True)
class Metadata:
    group_id: str = ""
    artifact_id: str = ""
    version: str = ""
    versions: tuple[str, ...] = ()
    latest: str = ""
    release: str = ""
    snapshot_timestamp: str = ""
    snapshot_build: int | None = None
    snapshot_versions: tuple[SnapshotVersion, ...] = ()
    last_updated: str = ""
    plugins: tuple[Plugin, ...] = ()


def stamp(moment: datetime) -> str:
    """A time as metadata writes it: yyyyMMddHHmmss, in UTC."""
    return moment.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def for_artifact(
    group_id: str,
    artifact_id: str,
    versions: Mapping[str, datetime],
    plugins: Iterable[Plugin] = (),
) -> Metadata | None:
    """The document for an artifact's directory: its versions, and any plugins there.

    `versions` maps each version to when its files last changed.
    """
    plugins = tuple(plugins)
    if not versions:
        return Metadata(plugins=plugins) if plugins else None
    ordered = sorted_versions(versions)
    releases = [version for version in ordered if not version.endswith(SNAPSHOT)]
    return Metadata(
        group_id=group_id,
        artifact_id=artifact_id,
        versions=tuple(ordered),
        latest=ordered[-1],
        release=releases[-1] if releases else "",
        last_updated=stamp(max(versions.values())),
        plugins=plugins,
    )


def for_snapshot(
    group_id: str,
    artifact_id: str,
    version: str,
    files: Iterable[tuple[MavenPath, datetime]],
) -> Metadata | None:
    """The document for a snapshot version's directory, from its files.

    For each classifier and extension it names the highest build. An old-style name
    (app-1.0-SNAPSHOT.jar) counts as the lowest build of all.
    """
    base = version.removesuffix(SNAPSHOT)
    highest: dict[tuple[str, str], tuple[tuple[int, str], str, datetime]] = {}
    latest_build: tuple[int, str] | None = None
    changed: datetime | None = None
    for parsed, modified in files:
        if parsed.build is None:
            rank, value = (-1, ""), version
        else:
            timestamp, number = parsed.build
            rank, value = (number, timestamp), f"{base}-{timestamp}-{number}"
            if latest_build is None or rank > latest_build:
                latest_build = rank
        key = (parsed.classifier, parsed.extension)
        if key not in highest or rank > highest[key][0]:
            highest[key] = (rank, value, modified)
        if changed is None or modified > changed:
            changed = modified
    if changed is None:
        return None
    return Metadata(
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        snapshot_timestamp="" if latest_build is None else latest_build[1],
        snapshot_build=None if latest_build is None else latest_build[0],
        snapshot_versions=tuple(
            SnapshotVersion(classifier, extension, value, stamp(modified))
            for (classifier, extension), (_, value, modified) in sorted(highest.items())
        ),
        last_updated=stamp(changed),
    )


def merge_plugins(stored: Iterable[Plugin], uploaded: Iterable[Plugin]) -> tuple[Plugin, ...]:
    """Stored plugin entries with uploaded ones added, the upload winning per artifact."""
    by_artifact = {plugin.artifact_id: plugin for plugin in stored}
    by_artifact.update({plugin.artifact_id: plugin for plugin in uploaded})
    return tuple(
        sorted(by_artifact.values(), key=lambda plugin: (plugin.prefix, plugin.artifact_id))
    )


def _add(parent: ET.Element, name: str, value: str) -> None:
    if value:
        ET.SubElement(parent, name).text = value


def serialise(metadata: Metadata) -> bytes:
    """The document as XML, with elements in the order Maven writes them."""
    root = ET.Element("metadata")
    if metadata.snapshot_versions:
        root.set("modelVersion", "1.1.0")
    _add(root, "groupId", metadata.group_id)
    _add(root, "artifactId", metadata.artifact_id)
    _add(root, "version", metadata.version)

    versioning = ET.Element("versioning")
    _add(versioning, "latest", metadata.latest)
    _add(versioning, "release", metadata.release)
    if metadata.snapshot_timestamp or metadata.snapshot_build is not None:
        snapshot = ET.SubElement(versioning, "snapshot")
        _add(snapshot, "timestamp", metadata.snapshot_timestamp)
        if metadata.snapshot_build is not None:
            _add(snapshot, "buildNumber", str(metadata.snapshot_build))
    if metadata.versions:
        versions = ET.SubElement(versioning, "versions")
        for version in metadata.versions:
            _add(versions, "version", version)
    _add(versioning, "lastUpdated", metadata.last_updated)
    if metadata.snapshot_versions:
        listed = ET.SubElement(versioning, "snapshotVersions")
        for entry in metadata.snapshot_versions:
            element = ET.SubElement(listed, "snapshotVersion")
            _add(element, "classifier", entry.classifier)
            _add(element, "extension", entry.extension)
            _add(element, "value", entry.value)
            _add(element, "updated", entry.updated)
    if len(versioning):
        root.append(versioning)

    if metadata.plugins:
        plugins = ET.SubElement(root, "plugins")
        for plugin in metadata.plugins:
            element = ET.SubElement(plugins, "plugin")
            _add(element, "name", plugin.name)
            _add(element, "prefix", plugin.prefix)
            _add(element, "artifactId", plugin.artifact_id)

    ET.indent(root)
    return _DECLARATION + ET.tostring(root, encoding="utf-8") + b"\n"


def _refuse_doctype(*_: object) -> None:
    raise InvalidMetadata("it has a DOCTYPE, which is not allowed")


def _tree(data: bytes) -> ET.Element:
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.StartElementHandler = builder.start
    parser.EndElementHandler = builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise InvalidMetadata(f"it is not well-formed XML (line {error.lineno})") from None
    return builder.close()


def _text(parent: ET.Element | None, name: str) -> str:
    """A child element's text, or "" if it is absent, empty or implausibly long."""
    child = None if parent is None else parent.find(name)
    if child is None:
        return ""
    text = (child.text or "").strip()
    return text if len(text) <= _MAX_FIELD else ""


def _own_text(element: ET.Element) -> str:
    text = (element.text or "").strip()
    return text if len(text) <= _MAX_FIELD else ""


def _number(text: str) -> int | None:
    return int(text) if text.isascii() and text.isdigit() and len(text) <= 9 else None


def parse(data: bytes) -> Metadata:
    """Read a metadata document. Raises InvalidMetadata; unknown elements are ignored."""
    root = _tree(data)
    if root.tag != "metadata":
        raise InvalidMetadata("its root element is not <metadata>")
    versioning = root.find("versioning")
    snapshot = None if versioning is None else versioning.find("snapshot")

    versions = [] if versioning is None else versioning.findall("versions/version")
    listed = [] if versioning is None else versioning.findall("snapshotVersions/snapshotVersion")
    snapshot_versions = [
        SnapshotVersion(
            classifier=_text(entry, "classifier"),
            extension=_text(entry, "extension"),
            value=_text(entry, "value"),
            updated=_text(entry, "updated"),
        )
        for entry in listed
    ]
    plugins = [
        Plugin(
            name=_text(entry, "name"),
            prefix=_text(entry, "prefix"),
            artifact_id=_text(entry, "artifactId"),
        )
        for entry in root.findall("plugins/plugin")
    ]
    return Metadata(
        group_id=_text(root, "groupId"),
        artifact_id=_text(root, "artifactId"),
        version=_text(root, "version"),
        versions=tuple(text for element in versions if (text := _own_text(element))),
        latest=_text(versioning, "latest"),
        release=_text(versioning, "release"),
        snapshot_timestamp=_text(snapshot, "timestamp"),
        snapshot_build=_number(_text(snapshot, "buildNumber")),
        snapshot_versions=tuple(
            entry for entry in snapshot_versions if entry.extension and entry.value
        ),
        last_updated=_text(versioning, "lastUpdated"),
        plugins=tuple(plugin for plugin in plugins if plugin.prefix and plugin.artifact_id),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/maven/metadata.py backend/tests/repositories/maven/test_metadata.py
git commit -m "feat(maven): build, read and write maven-metadata.xml"
```

---

### Task 7: The Maven format: settings, components and hosted files

**Files:**
- Create: `backend/src/megooarti/repositories/maven/format.py`
- Modify: `backend/src/megooarti/main.py`
- Create: `backend/tests/repositories/maven/conftest.py`
- Test: `backend/tests/repositories/maven/test_format.py`
- Test: `backend/tests/repositories/maven/test_hosted_files.py`

**Interfaces:**
- Consumes: Task 1's `validate_config(…, current)`, optional component and `content_type` hook; Task 4's `paths`.
- Produces:
  - `megooarti.repositories.maven.format.MavenFormat`, registered as `"maven"`, with `types == frozenset({"hosted"})`.
  - Stored `format_config`: `{"version_policy": "release" | "snapshot" | "mixed", "layout_policy": "strict" | "permissive"}`.
  - `_check_policies(settings: dict, parsed: MavenPath) -> None` — raises `400 invalid_path` or `400 version_policy_violation`. Called for `PUT` only.
  - Test helpers in `tests/repositories/maven/conftest.py`: `await create(db, name, *, hosted=None, **format_config) -> Repository` (a committed hosted Maven repository), and the fixtures `releases` (release, strict), `snapshots` (snapshot, strict) and `root` (Basic headers of an administrator).

- [ ] **Step 1: Write the test helpers**

`backend/tests/repositories/maven/conftest.py`:

```python
import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic


async def create(db, name: str, *, hosted: dict | None = None, **format_config) -> Repository:
    """A hosted Maven repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="maven",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config=format_config,
    )
    await db.commit()
    return repository


@pytest.fixture
async def releases(db) -> Repository:
    return await create(db, "releases")


@pytest.fixture
async def snapshots(db) -> Repository:
    return await create(db, "snapshots", version_policy="snapshot")


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/repositories/maven/test_format.py`:

```python
import pytest

from megooarti.errors import ApiError
from megooarti.repositories.formats import ComponentKey, get_format
from megooarti.repositories.maven.format import MavenFormat
from tests.accounts import error_code

MAVEN = MavenFormat()
STRICT_RELEASES = {"version_policy": "release", "layout_policy": "strict"}


def test_maven_is_registered_as_a_hosted_format():
    assert isinstance(get_format("maven"), MavenFormat)
    assert get_format("maven").types == {"hosted"}


def test_settings_default_to_releases_in_a_strict_layout():
    assert MAVEN.validate_config("hosted", {}) == STRICT_RELEASES


def test_settings_are_taken_as_given():
    given = {"version_policy": "snapshot", "layout_policy": "permissive"}

    assert MAVEN.validate_config("hosted", given) == given


@pytest.mark.parametrize(
    "config",
    [
        {"version_policy": "nightly"},
        {"version_policy": None},
        {"version_policy": ["release"]},
        {"layout_policy": "loose"},
        {"layout_policy": 1},
        {"unknown": 1},
    ],
)
def test_bad_settings_are_refused(config):
    with pytest.raises(ApiError) as caught:
        MAVEN.validate_config("hosted", config)

    assert (caught.value.status_code, caught.value.code) == (422, "validation_error")


def test_the_version_policy_cannot_change():
    with pytest.raises(ApiError) as caught:
        MAVEN.validate_config("hosted", {"version_policy": "mixed"}, STRICT_RELEASES)

    assert (caught.value.status_code, caught.value.code) == (409, "immutable")


def test_an_update_that_omits_the_version_policy_keeps_it():
    stored = {"version_policy": "snapshot", "layout_policy": "permissive"}

    assert MAVEN.validate_config("hosted", {}, stored) == {
        "version_policy": "snapshot",
        "layout_policy": "strict",
    }


def test_the_layout_policy_can_change():
    changed = MAVEN.validate_config("hosted", {"layout_policy": "permissive"}, STRICT_RELEASES)

    assert changed == {"version_policy": "release", "layout_policy": "permissive"}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("com/acme/app/1.0/app-1.0.jar", ComponentKey("com.acme", "app", "1.0")),
        (
            "com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-3.pom",
            ComponentKey("com.acme", "app", "1.0-SNAPSHOT"),
        ),
        ("com/acme/app/maven-metadata.xml", None),
        ("archetype-catalog.xml", None),
        ("notes/readme.txt", None),
    ],
)
def test_only_artifact_files_belong_to_a_component(path, expected):
    assert MAVEN.describe_component(path) == expected


def test_known_extensions_decide_the_content_type():
    assert MAVEN.content_type("a/app-1.0.pom", "application/octet-stream") == "application/xml"
    assert MAVEN.content_type("a/app-1.0.zip", "application/zip") == "application/zip"
    assert MAVEN.content_type("a/app-1.0.zip", None) is None


async def test_a_maven_repository_is_configured_through_the_api(admin_client):
    created = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "snapshots",
            "format": "maven",
            "type": "hosted",
            "format_config": {"version_policy": "snapshot"},
        },
    )
    changed = await admin_client.put(
        "/api/v1/repositories/snapshots", json={"format_config": {"version_policy": "release"}}
    )
    relaxed = await admin_client.put(
        "/api/v1/repositories/snapshots", json={"format_config": {"layout_policy": "permissive"}}
    )

    assert created.status_code == 201, created.text
    assert created.json()["format_config"] == {
        "version_policy": "snapshot",
        "layout_policy": "strict",
    }
    assert (changed.status_code, error_code(changed)) == (409, "immutable")
    assert relaxed.json()["format_config"] == {
        "version_policy": "snapshot",
        "layout_policy": "permissive",
    }


@pytest.mark.parametrize("kind", ["proxy", "group"])
async def test_proxy_and_group_maven_repositories_are_not_offered_yet(admin_client, kind):
    response = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "central",
            "format": "maven",
            "type": kind,
            "proxy": {"remote_url": "https://repo.example/maven2"},
            "group": {"members": []},
        },
    )

    assert (response.status_code, error_code(response)) == (422, "validation_error")
```

`backend/tests/repositories/maven/test_hosted_files.py`:

```python
import pytest
from sqlalchemy import func, select

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

JAR = "/repository/releases/com/acme/app/1.0/app-1.0.jar"
POM = "/repository/releases/com/acme/app/1.0/app-1.0.pom"
BYTES = b"PK\x03\x04 pretend this is a jar"
SNAPSHOTS = "/repository/snapshots/com/acme/app/1.0-SNAPSHOT"


async def test_an_artifact_is_stored_served_and_given_its_component(client, releases, root, db):
    stored = await client.put(JAR, content=BYTES, headers=root)
    fetched = await client.get(JAR, headers=root)

    assert stored.status_code == 201
    assert (fetched.status_code, fetched.content) == (200, BYTES)
    assert fetched.headers["Content-Type"] == "application/java-archive"
    assert fetched.headers["Content-Disposition"].startswith('attachment; filename="app-1.0.jar"')
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("com.acme", "app", "1.0")


async def test_the_files_of_a_version_share_one_component(client, releases, root, db):
    await client.put(JAR, content=BYTES, headers=root)
    await client.put(POM, content=b"<project/>", headers={**root, "Content-Type": "text/weird"})

    assert await db.scalar(select(func.count()).select_from(Component)) == 1
    assert (await client.get(POM, headers=root)).headers["Content-Type"] == "application/xml"


@pytest.mark.parametrize(
    "path",
    ["notes/readme.txt", "com/acme/app/1.0/other-1.0.jar", "com.acme/app/1.0/app-1.0.jar"],
)
async def test_a_strict_repository_refuses_paths_outside_the_layout(client, releases, root, path):
    refused = await client.put(f"/repository/releases/{path}", content=b"x", headers=root)
    missing = await client.get(f"/repository/releases/{path}", headers=root)

    assert (refused.status_code, error_code(refused)) == (400, "invalid_path")
    assert (missing.status_code, error_code(missing)) == (404, "not_found")


async def test_a_permissive_repository_stores_other_paths_as_plain_files(client, db, root):
    await create(db, "loose", layout_policy="permissive")
    url = "/repository/loose/notes/readme.txt"

    stored = await client.put(url, content=b"hello", headers=root)

    assert stored.status_code == 201
    assert (await client.get(url, headers=root)).content == b"hello"
    assert await db.scalar(select(Asset.component_id)) is None


async def test_files_stored_while_permissive_stay_reachable_once_strict(client, db, root):
    loose = await create(db, "loose", layout_policy="permissive")
    url = "/repository/loose/notes/readme.txt"
    await client.put(url, content=b"hello", headers=root)
    await service.update_repository(
        db, loose, online=True, hosted=None, format_config={"layout_policy": "strict"}
    )
    await db.commit()

    another = await client.put("/repository/loose/notes/other.txt", content=b"x", headers=root)

    assert (another.status_code, error_code(another)) == (400, "invalid_path")
    assert (await client.get(url, headers=root)).content == b"hello"
    assert (await client.delete(url, headers=root)).status_code == 204


async def test_the_catalog_is_a_plain_file(client, releases, root, db):
    url = "/repository/releases/archetype-catalog.xml"

    stored = await client.put(url, content=b"<archetype-catalog/>", headers=root)

    assert stored.status_code == 201
    assert (await client.get(url, headers=root)).content == b"<archetype-catalog/>"
    assert await db.scalar(select(Asset.component_id)) is None


async def test_a_release_repository_refuses_snapshots(client, releases, root):
    url = "/repository/releases/com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-1.jar"

    refused = await client.put(url, content=BYTES, headers=root)

    assert (refused.status_code, error_code(refused)) == (400, "version_policy_violation")
    assert (await client.get(url, headers=root)).status_code == 404


async def test_a_snapshot_repository_refuses_releases(client, snapshots, root, db):
    release = await client.put(
        "/repository/snapshots/com/acme/app/1.0/app-1.0.jar", content=BYTES, headers=root
    )
    timestamped = await client.put(
        f"{SNAPSHOTS}/app-1.0-20261008.101500-1.jar", content=BYTES, headers=root
    )
    old_style = await client.put(f"{SNAPSHOTS}/app-1.0-SNAPSHOT.jar", content=BYTES, headers=root)

    assert (release.status_code, error_code(release)) == (400, "version_policy_violation")
    assert (timestamped.status_code, old_style.status_code) == (201, 201)
    component = await db.scalar(select(Component))
    assert (component.name, component.version) == ("app", "1.0-SNAPSHOT")


async def test_a_mixed_repository_accepts_both(client, db, root):
    await create(db, "mixed", version_policy="mixed")
    base = "/repository/mixed/com/acme/app"

    release = await client.put(f"{base}/1.0/app-1.0.jar", content=BYTES, headers=root)
    snapshot = await client.put(
        f"{base}/1.1-SNAPSHOT/app-1.1-SNAPSHOT.jar", content=BYTES, headers=root
    )

    assert (release.status_code, snapshot.status_code) == (201, 201)


async def test_the_deployment_policy_applies_to_artifacts(client, db, root):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    url = "/repository/once/com/acme/app/1.0/app-1.0.jar"
    await client.put(url, content=BYTES, headers=root)

    again = await client.put(url, content=b"different", headers=root)

    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
    assert (await client.get(url, headers=root)).content == BYTES


async def test_an_artifact_can_be_deleted(client, releases, root, db):
    await client.put(JAR, content=BYTES, headers=root)

    assert (await client.delete(JAR, headers=root)).status_code == 204
    assert (await client.get(JAR, headers=root)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Component)) == 0


async def test_permissions_use_the_maven_format_name(client, releases, make_user, db):
    await roles.create_role(db, "deployers", "", ["repository:maven:releases:add"], [])
    await db.commit()
    await make_user("ci", roles=["deployers"])
    ci = basic("ci", PASSWORD)

    stored = await client.put(JAR, content=BYTES, headers=ci)
    read = await client.get(JAR, headers=ci)

    assert stored.status_code == 201
    assert (read.status_code, error_code(read)) == (403, "forbidden")


async def test_an_invalid_path_is_still_a_bad_request(client, releases, root):
    response = await client.get("/repository/releases/com//app", headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_path")


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_other_methods_are_not_allowed(client, releases, root, method):
    response = await client.request(method, JAR, content=BYTES, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_format.py tests/repositories/maven/test_hosted_files.py -q`
Expected: collection error for `test_format.py`, `No module named 'megooarti.repositories.maven.format'`; every test in `test_hosted_files.py` errors while creating its repository, because `maven` is an unknown format.

- [ ] **Step 4: Implement**

`backend/src/megooarti/repositories/maven/format.py`:

```python
"""The Maven format: the Maven 2 layout, with generated checksums and metadata.

This is the only Maven module that touches the repository context. What it decides
about a path comes from the pure functions beside it.
"""

from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.maven import paths
from megooarti.repositories.paths import normalise_path

_SETTINGS = ("version_policy", "layout_policy")


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": f"format_config.{field}", "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _choice(config: dict[str, Any], field: str, choices: tuple[str, ...], default: str) -> str:
    value = config.get(field, default)
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field, f"Must be one of: {', '.join(choices)}.")
    return value


def _check_policies(settings: dict[str, Any], parsed: paths.MavenPath) -> None:
    """Refuse an upload to a path this repository does not take.

    Checked for uploads only. What is already stored stays readable and deletable,
    so a repository can be made strict without stranding files.
    """
    if parsed.kind == "other" and settings["layout_policy"] == "strict":
        raise ApiError(
            400, "invalid_path", "The path is not valid: it is not in the Maven repository layout."
        )
    if not paths.allowed_by(settings["version_policy"], parsed):
        accepted = settings["version_policy"]
        raise ApiError(
            400, "version_policy_violation", f"This repository takes {accepted} versions only."
        )


class MavenFormat(Format):
    name = "maven"
    # Proxy and group repositories need Maven's own handling of checksums and metadata.
    types = frozenset({"hosted"})

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        unknown = sorted(set(config) - set(_SETTINGS))
        if unknown:
            raise _invalid(unknown[0], "Maven repositories have no such setting.")
        stored = (current or {}).get("version_policy")
        version_policy = _choice(
            config, "version_policy", paths.VERSION_POLICIES, stored or "release"
        )
        if stored is not None and version_policy != stored:
            # Changing it would leave content the repository refuses to take or list.
            raise ApiError(409, "immutable", "A repository's version policy cannot be changed.")
        return {
            "version_policy": version_policy,
            "layout_policy": _choice(config, "layout_policy", paths.LAYOUT_POLICIES, "strict"),
        }

    def describe_component(self, path: str) -> ComponentKey | None:
        """An artifact file belongs to its group, artifact and version. Nothing else does."""
        parsed = paths.classify(path)
        if parsed.kind != "artifact":
            return None
        return ComponentKey(parsed.group_id, parsed.artifact_id, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        # Maven clients rarely declare a type, and never a useful one.
        return paths.content_type(path) or declared

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        parsed = paths.classify(path)
        if request.method == "PUT":
            _check_policies(context.repository.config["format_config"], parsed)
        return await super().handle_hosted(context, request, path)


register(MavenFormat())
```

In `backend/src/megooarti/main.py`, add after the line `from megooarti.repositories.api import router as repositories_router`:

```python
from megooarti.repositories.maven import format as _maven_format  # noqa: F401  (registers it)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/maven/format.py backend/src/megooarti/main.py backend/tests/repositories/maven
git commit -m "feat(maven): hosted Maven repositories with version and layout policy"
```

---

### Task 8: Hosted checksums

**Files:**
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Test: `backend/tests/repositories/maven/test_hosted_checksums.py`

**Interfaces:**
- Consumes: Task 2's `stat`, `receive`, `respond_with`; Task 3's `require_write`; Task 4's `split_checksum` and `checksums.read_uploaded`.
- Produces, in `maven/format.py`:
  - `await _digest(context, target: str, parsed: MavenPath, algorithm: str) -> tuple[str, datetime] | None` — the checksum of what a `GET` of `target` returns, and when that last changed. Task 9 extends it to metadata.
  - `await _checksum(context, request, path, target, parsed, algorithm) -> Response`

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_hosted_checksums.py`:

```python
import hashlib

import pytest
from sqlalchemy import select

from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

JAR = "/repository/releases/com/acme/app/1.0/app-1.0.jar"
BYTES = b"PK\x03\x04 pretend this is a jar"
SHA1 = hashlib.sha1(BYTES).hexdigest()


@pytest.fixture
async def jar(client, releases, root) -> None:
    response = await client.put(JAR, content=BYTES, headers=root)
    assert response.status_code == 201


@pytest.mark.parametrize("algorithm", ["md5", "sha1", "sha256", "sha512"])
async def test_a_checksum_is_answered_from_the_stored_file(client, jar, root, algorithm):
    response = await client.get(f"{JAR}.{algorithm}", headers=root)
    file = await client.head(JAR, headers=root)

    assert (response.status_code, response.text) == (200, hashlib.new(algorithm, BYTES).hexdigest())
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Last-Modified"] == file.headers["Last-Modified"]
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"].startswith(
        f'attachment; filename="app-1.0.jar.{algorithm}"'
    )


async def test_a_checksum_supports_head(client, jar, root):
    response = await client.head(f"{JAR}.sha1", headers=root)

    assert (response.status_code, response.content) == (200, b"")
    assert response.headers["Content-Length"] == "40"


async def test_a_checksum_of_nothing_is_not_found(client, releases, root):
    response = await client.get(f"{JAR}.sha1", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


@pytest.mark.parametrize(
    "body",
    [
        SHA1.encode(),
        f"{SHA1.upper()}  app-1.0.jar\n".encode(),
        f"SHA1(app-1.0.jar)= {SHA1}\n".encode(),
    ],
)
async def test_a_matching_checksum_is_accepted_and_not_stored(client, jar, root, db, body):
    response = await client.put(f"{JAR}.sha1", content=body, headers=root)

    assert (response.status_code, response.content) == (201, b"")
    assert list(await db.scalars(select(Asset.path))) == ["com/acme/app/1.0/app-1.0.jar"]


@pytest.mark.parametrize("body", [b"0" * 40, b"not a checksum", b"", b"a" * 2000])
async def test_a_wrong_checksum_fails_the_upload_and_leaves_the_file(client, jar, root, body):
    response = await client.put(f"{JAR}.sha1", content=body, headers=root)

    assert (response.status_code, error_code(response)) == (400, "checksum_mismatch")
    assert (await client.get(JAR, headers=root)).content == BYTES


async def test_a_checksum_for_a_missing_file_is_not_found(client, releases, root):
    response = await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_a_checksum_cannot_be_deleted(client, jar, root):
    response = await client.delete(f"{JAR}.sha1", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, PUT"
    assert (await client.get(JAR, headers=root)).status_code == 200


async def test_a_checksum_follows_the_policies_of_its_file(client, releases, root):
    snapshot = await client.put(
        "/repository/releases/com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT.jar.sha1",
        content=SHA1.encode(),
        headers=root,
    )
    outside = await client.put(
        "/repository/releases/notes/readme.txt.md5", content=b"0" * 32, headers=root
    )

    assert (snapshot.status_code, error_code(snapshot)) == (400, "version_policy_violation")
    assert (outside.status_code, error_code(outside)) == (400, "invalid_path")


async def test_uploading_a_checksum_needs_permission_to_write(client, jar, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:maven:releases:read"], [])
    await roles.create_role(db, "adders", "", ["repository:maven:releases:add"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    await make_user("ada", roles=["adders"])
    reader, adder = basic("rae", PASSWORD), basic("ada", PASSWORD)

    by_reader = await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=reader)
    by_adder = await client.put(f"{JAR}.sha1", content=SHA1.encode(), headers=adder)
    by_nobody = await client.put(f"{JAR}.sha1", content=SHA1.encode())
    read_by_reader = await client.get(f"{JAR}.sha1", headers=reader)
    read_by_adder = await client.get(f"{JAR}.sha1", headers=adder)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert by_adder.status_code == 201
    assert by_nobody.status_code == 401
    assert read_by_reader.text == SHA1
    assert (read_by_adder.status_code, error_code(read_by_adder)) == (403, "forbidden")


async def test_a_read_only_repository_refuses_checksum_uploads(client, db, root):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await client.put(
        "/repository/frozen/com/acme/app/1.0/app-1.0.jar.sha1", content=SHA1.encode(), headers=root
    )

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_hosted_checksums.py -q`
Expected: most fail. Reading a checksum is `404`; uploading one stores it as a file (`201` where `400` or `404` is expected, and two stored paths); deleting one is `404`, not `405`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/maven/format.py`, add `from datetime import datetime` above the `from typing import Any` line, and change the `maven` import to:

```python
from megooarti.repositories.maven import checksums, paths
```

Add after `_check_policies`:

```python
def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


async def _digest(
    context: RepositoryContext, target: str, parsed: paths.MavenPath, algorithm: str
) -> tuple[str, datetime] | None:
    """The checksum of what a GET of `target` returns, and when that last changed."""
    stored = await context.stat(target)
    if stored is None:
        return None
    return getattr(stored, algorithm), stored.modified


async def _checksum(
    context: RepositoryContext,
    request: Request,
    path: str,
    target: str,
    parsed: paths.MavenPath,
    algorithm: str,
) -> Response:
    """Answer for a checksum path. Checksums are computed, never stored."""
    if request.method in ("GET", "HEAD"):
        found = await _digest(context, target, parsed, algorithm)
        if found is None:
            raise _not_found()
        digest, modified = found
        return context.respond_with(
            digest.encode(),
            request,
            filename=path.rpartition("/")[2],
            content_type="text/plain",
            last_modified=modified,
        )
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "A checksum is computed from its file. It can be read or uploaded, not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=checksums.LIMIT)
    found = await _digest(context, target, parsed, algorithm)
    if found is None:
        raise ApiError(404, "not_found", "There is no file here for this checksum to belong to.")
    declared = None if body is None else checksums.read_uploaded(body, algorithm)
    if declared != found[0]:
        # The file stays. Removing it would let anyone who may add delete files by
        # sending a wrong checksum; the client sees its deploy fail instead.
        raise ApiError(
            400, "checksum_mismatch", f"The {algorithm} checksum does not match the stored file."
        )
    return Response(status_code=201)
```

Replace the `handle_hosted` method of `MavenFormat` with:

```python
    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        # A checksum path is treated as the path it belongs to.
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if request.method == "PUT":
            _check_policies(context.repository.config["format_config"], parsed)
        if algorithm is not None:
            return await _checksum(context, request, path, target, parsed, algorithm)
        return await super().handle_hosted(context, request, path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/maven/format.py backend/tests/repositories/maven/test_hosted_checksums.py
git commit -m "feat(maven): answer checksums from recorded hashes and verify uploaded ones"
```

---

### Task 9: Hosted metadata: generated documents, dropped uploads, plugin prefixes

**Files:**
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Test: `backend/tests/repositories/maven/test_hosted_metadata.py`
- Test: `backend/tests/repositories/maven/test_hosted_plugins.py`
- Test: `backend/tests/repositories/maven/test_races.py`

**Interfaces:**
- Consumes: Task 2's `versions`, `files`, `names`, `stat`, `read`, `receive`, `respond_with`; Task 3's `require_write`, `maintain`; Task 6's `metadata`; Task 8's `_digest`, `_checksum`.
- Produces, in `maven/format.py`:
  - `METADATA_LIMIT = 1024 * 1024`, `STORED_LIMIT = 4 * 1024 * 1024`.
  - `await document(context, path: str, parsed: MavenPath) -> tuple[bytes, datetime] | None` — the metadata a `GET` of `path` returns now, and when it last changed. Plan 4b's group handling calls this for a hosted member.
  - `await keep_plugins(context, path: str, group_id: str, uploaded: Iterable[Plugin]) -> None` — merges plugin entries into the stored record at `path`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_hosted_metadata.py`:

```python
import hashlib

from sqlalchemy import select

from megooarti.repositories.maven import metadata
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

APP = "releases/com/acme/app"
LISTING = f"/repository/{APP}/maven-metadata.xml"
SNAP = "snapshots/com/acme/app/1.0-SNAPSHOT"
CLIENT_MADE = (
    b"<metadata><groupId>com.acme</groupId><artifactId>app</artifactId>"
    b"<versioning><versions><version>9.9</version></versions></versioning></metadata>"
)


async def put(client, root, path: str, content: bytes = b"x") -> None:
    response = await client.put(f"/repository/{path}", content=content, headers=root)
    assert response.status_code in (201, 204), response.text


async def deploy(client, root, version: str) -> None:
    await put(client, root, f"{APP}/{version}/app-{version}.jar")
    await put(client, root, f"{APP}/{version}/app-{version}.pom")


async def listing(client, root, url: str = LISTING) -> metadata.Metadata:
    response = await client.get(url, headers=root)
    assert response.status_code == 200, response.text
    return metadata.parse(response.content)


async def test_artifact_metadata_is_generated_from_what_is_stored(client, releases, root):
    await deploy(client, root, "1.10")
    await deploy(client, root, "1.9")

    response = await client.get(LISTING, headers=root)

    document = metadata.parse(response.content)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/xml"
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert (document.group_id, document.artifact_id) == ("com.acme", "app")
    assert document.versions == ("1.9", "1.10")
    assert (document.latest, document.release) == ("1.10", "1.10")
    assert len(document.last_updated) == 14
    assert document.plugins == ()


async def test_metadata_for_nothing_is_not_found(client, releases, root):
    fetched = await client.get(LISTING, headers=root)
    headed = await client.head(LISTING, headers=root)

    assert (fetched.status_code, error_code(fetched)) == (404, "not_found")
    assert headed.status_code == 404


async def test_metadata_follows_a_delete(client, releases, root):
    await put(client, root, f"{APP}/1.0/app-1.0.jar")
    await put(client, root, f"{APP}/1.1/app-1.1.jar")

    await client.delete(f"/repository/{APP}/1.1/app-1.1.jar", headers=root)
    after_one = await listing(client, root)
    await client.delete(f"/repository/{APP}/1.0/app-1.0.jar", headers=root)
    after_both = await client.get(LISTING, headers=root)

    assert (after_one.versions, after_one.latest) == (("1.0",), "1.0")
    assert after_both.status_code == 404


async def test_metadata_supports_head_and_conditions(client, releases, root):
    await deploy(client, root, "1.0")
    first = await client.get(LISTING, headers=root)
    etag = first.headers["ETag"]

    headed = await client.head(LISTING, headers=root)
    unchanged = await client.get(LISTING, headers={**root, "If-None-Match": etag})
    await deploy(client, root, "1.1")
    changed = await client.get(LISTING, headers={**root, "If-None-Match": etag})

    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Content-Length"] == str(len(first.content))
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert changed.status_code == 200
    assert changed.headers["ETag"] != etag


async def test_uploaded_metadata_is_accepted_and_dropped(client, releases, root, db):
    await put(client, root, f"{APP}/1.0/app-1.0.jar")

    uploaded = await client.put(LISTING, content=CLIENT_MADE, headers=root)

    assert (uploaded.status_code, uploaded.content) == (201, b"")
    assert (await listing(client, root)).versions == ("1.0",)
    assert list(await db.scalars(select(Asset.path))) == ["com/acme/app/1.0/app-1.0.jar"]


async def test_uploaded_metadata_must_be_readable(client, releases, root):
    hostile = b'<!DOCTYPE metadata [<!ENTITY a "b">]><metadata><groupId>&a;</groupId></metadata>'

    for body in (b"not xml", hostile, b"<project/>"):
        response = await client.put(LISTING, content=body, headers=root)
        assert (response.status_code, error_code(response)) == (400, "invalid_metadata")


async def test_uploaded_metadata_has_a_size_limit(client, releases, root):
    huge = b"<metadata>" + b" " * (1024 * 1024) + b"</metadata>"

    response = await client.put(LISTING, content=huge, headers=root)

    assert (response.status_code, error_code(response)) == (400, "invalid_metadata")


async def test_metadata_cannot_be_deleted(client, releases, root):
    await deploy(client, root, "1.0")

    response = await client.delete(LISTING, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, PUT"
    assert (await listing(client, root)).versions == ("1.0",)


async def test_the_checksum_of_metadata_is_of_the_document_served(client, releases, root):
    missing = await client.get(f"{LISTING}.sha1", headers=root)
    await deploy(client, root, "1.0")

    document = await client.get(LISTING, headers=root)
    sha1 = await client.get(f"{LISTING}.sha1", headers=root)
    md5 = await client.get(f"{LISTING}.md5", headers=root)

    assert missing.status_code == 404
    assert sha1.text == hashlib.sha1(document.content).hexdigest()
    assert md5.text == hashlib.md5(document.content).hexdigest()
    assert sha1.headers["Last-Modified"] == document.headers["Last-Modified"]


async def test_a_checksum_uploaded_for_metadata_is_accepted_unchecked(client, releases, root, db):
    before_any_file = await client.put(f"{LISTING}.sha1", content=b"0" * 40, headers=root)
    await deploy(client, root, "1.0")
    after = await client.put(f"{LISTING}.md5", content=b"0" * 32, headers=root)

    assert (before_any_file.status_code, after.status_code) == (201, 201)
    assert len(list(await db.scalars(select(Asset.path)))) == 2


async def test_dropped_uploads_need_permission_to_write(client, releases, make_user, db):
    await roles.create_role(db, "readers", "", ["repository:maven:releases:read"], [])
    await roles.create_role(db, "adders", "", ["repository:maven:releases:add"], [])
    await db.commit()
    await make_user("rae", roles=["readers"])
    await make_user("ada", roles=["adders"])
    reader, adder = basic("rae", PASSWORD), basic("ada", PASSWORD)

    for url in (LISTING, f"{LISTING}.sha1"):
        refused = await client.put(url, content=CLIENT_MADE, headers=reader)
        assert (refused.status_code, error_code(refused)) == (403, "forbidden"), url
        assert (await client.put(url, content=CLIENT_MADE)).status_code == 401, url

    assert (await client.put(LISTING, content=CLIENT_MADE, headers=adder)).status_code == 201
    assert (await client.put(f"{LISTING}.sha1", content=b"0", headers=adder)).status_code == 201


async def test_snapshot_metadata_points_at_the_latest_build(client, snapshots, root):
    for name in (
        "app-1.0-20261008.101500-1.jar",
        "app-1.0-20261008.101500-1.pom",
        "app-1.0-20261008.111500-2.jar",
        "app-1.0-20261008.111500-2.pom",
    ):
        await put(client, root, f"{SNAP}/{name}")

    version_level = await listing(client, root, f"/repository/{SNAP}/maven-metadata.xml")
    artifact_level = await listing(
        client, root, "/repository/snapshots/com/acme/app/maven-metadata.xml"
    )

    assert (version_level.group_id, version_level.artifact_id, version_level.version) == (
        "com.acme",
        "app",
        "1.0-SNAPSHOT",
    )
    assert (version_level.snapshot_timestamp, version_level.snapshot_build) == (
        "20261008.111500",
        2,
    )
    assert {(entry.extension, entry.value) for entry in version_level.snapshot_versions} == {
        ("jar", "1.0-20261008.111500-2"),
        ("pom", "1.0-20261008.111500-2"),
    }
    assert artifact_level.versions == ("1.0-SNAPSHOT",)
    assert (artifact_level.latest, artifact_level.release) == ("1.0-SNAPSHOT", "")


async def test_uploaded_snapshot_metadata_is_dropped_without_being_read(client, snapshots, root):
    url = f"/repository/{SNAP}/maven-metadata.xml"

    uploaded = await client.put(url, content=b"this is not xml at all", headers=root)

    assert uploaded.status_code == 201
    assert (await client.get(url, headers=root)).status_code == 404


async def test_a_release_repository_has_no_snapshot_metadata(client, releases, root):
    url = f"/repository/{APP}/1.0-SNAPSHOT/maven-metadata.xml"

    fetched = await client.get(url, headers=root)
    uploaded = await client.put(url, content=CLIENT_MADE, headers=root)

    assert fetched.status_code == 404
    assert (uploaded.status_code, error_code(uploaded)) == (400, "version_policy_violation")
```

`backend/tests/repositories/maven/test_hosted_plugins.py`:

```python
from sqlalchemy import func, select

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.metadata import Metadata, Plugin
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

GROUP = "/repository/releases/com/acme/maven-metadata.xml"
ACME = Plugin("Acme Plugin", "acme", "acme-maven-plugin")


def group_metadata(*plugins: Plugin) -> bytes:
    return metadata.serialise(Metadata(plugins=plugins))


def jar_of(artifact: str, version: str = "1.0", repository: str = "releases") -> str:
    return f"/repository/{repository}/com/acme/{artifact}/{version}/{artifact}-{version}.jar"


async def deploy(client, root, artifact: str, version: str = "1.0") -> None:
    response = await client.put(jar_of(artifact, version), content=b"x", headers=root)
    assert response.status_code == 201, response.text


async def listed(client, root, url: str = GROUP) -> Metadata:
    response = await client.get(url, headers=root)
    assert response.status_code == 200, response.text
    return metadata.parse(response.content)


async def test_plugin_prefixes_are_kept_from_uploaded_group_metadata(client, releases, root):
    await deploy(client, root, "acme-maven-plugin")

    uploaded = await client.put(GROUP, content=group_metadata(ACME), headers=root)

    document = await listed(client, root)
    assert uploaded.status_code == 201
    assert document == Metadata(plugins=(ACME,))


async def test_a_second_plugin_is_merged_with_the_first(client, releases, root):
    other = Plugin("Other Plugin", "other", "other-maven-plugin")
    await deploy(client, root, "acme-maven-plugin")
    await deploy(client, root, "other-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    await client.put(GROUP, content=group_metadata(other), headers=root)

    assert (await listed(client, root)).plugins == (ACME, other)


async def test_a_newer_upload_wins_for_the_same_plugin(client, releases, root):
    renamed = Plugin("Acme Plugin 2", "acme2", "acme-maven-plugin")
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    await client.put(GROUP, content=group_metadata(renamed), headers=root)

    assert (await listed(client, root)).plugins == (renamed,)


async def test_a_plugin_that_was_never_deployed_is_not_kept(client, releases, root, db):
    uploaded = await client.put(GROUP, content=group_metadata(ACME), headers=root)

    assert uploaded.status_code == 201
    assert (await client.get(GROUP, headers=root)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_a_plugin_disappears_with_its_last_file(client, releases, root):
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    await client.delete(jar_of("acme-maven-plugin"), headers=root)

    assert (await client.get(GROUP, headers=root)).status_code == 404


async def test_a_path_can_be_both_an_artifact_and_a_group(client, releases, root):
    # com/acme is the artifact "acme" of group "com", and also the group "com.acme".
    await client.put("/repository/releases/com/acme/1.0/acme-1.0.jar", content=b"x", headers=root)
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    document = await listed(client, root)

    assert (document.group_id, document.artifact_id) == ("com", "acme")
    assert document.versions == ("1.0",)
    assert document.plugins == (ACME,)


async def test_the_stored_record_is_never_served_as_a_file(client, releases, root, db):
    await deploy(client, root, "acme-maven-plugin")
    await client.put(GROUP, content=group_metadata(ACME), headers=root)

    record = await db.scalar(select(Asset).where(Asset.kind == "metadata"))
    removed = await client.delete(GROUP, headers=root)

    assert (record.path, record.component_id) == ("com/acme/maven-metadata.xml", None)
    assert (removed.status_code, error_code(removed)) == (405, "method_not_allowed")


async def test_plugins_at_a_path_that_cannot_be_a_group_are_dropped(client, releases, root, db):
    url = "/repository/releases/com/acme/my.app/maven-metadata.xml"

    uploaded = await client.put(url, content=group_metadata(ACME), headers=root)
    unreadable = await client.put(url, content=b"not xml", headers=root)

    assert uploaded.status_code == 201
    assert (unreadable.status_code, error_code(unreadable)) == (400, "invalid_metadata")
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_an_account_that_may_only_add_completes_two_plugin_deploys(client, db, make_user):
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    await roles.create_role(
        db, "deployers", "", ["repository:maven:once:add", "repository:maven:once:read"], []
    )
    await db.commit()
    await make_user("ci", roles=["deployers"])
    ci = basic("ci", PASSWORD)
    group = "/repository/once/com/acme/maven-metadata.xml"
    artifact = "/repository/once/com/acme/acme-maven-plugin/maven-metadata.xml"
    renamed = Plugin("Acme Plugin 2", "acme", "acme-maven-plugin")

    async def upload(url: str, content: bytes | str) -> int:
        return (await client.put(url, content=content, headers=ci)).status_code

    statuses = []
    for version, plugin in (("1.0", ACME), ("1.1", renamed)):
        jar = jar_of("acme-maven-plugin", version, "once")
        statuses.append(await upload(jar, b"x"))
        sha1 = (await client.get(f"{jar}.sha1", headers=ci)).text
        statuses.append(await upload(f"{jar}.sha1", sha1))
        statuses.append(await upload(artifact, b"<metadata/>"))
        statuses.append(await upload(group, group_metadata(plugin)))
    first_jar = jar_of("acme-maven-plugin", "1.0", "once")
    replaced = await client.put(first_jar, content=b"y", headers=ci)

    assert statuses == [201] * 8
    assert (await listed(client, ci, group)).plugins == (renamed,)
    assert (await listed(client, ci, artifact)).versions == ("1.0", "1.1")
    assert (replaced.status_code, error_code(replaced)) == (403, "forbidden")
```

`backend/tests/repositories/maven/test_races.py`:

```python
"""Deploys at the same moment, which only real, concurrent transactions can show."""

import asyncio

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.format import STORED_LIMIT, keep_plugins
from megooarti.repositories.maven.metadata import Plugin
from megooarti.repositories.models import Repository
from tests.repositories.conftest import body, someone
from tests.storage.test_races import Factory, run

DEPLOYER = someone("repository:maven:releases")
GROUP = "com/acme/maven-metadata.xml"


async def create_releases(factory: Factory) -> Repository:
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="releases",
            format="maven",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        await db.commit()
        return repository


async def context_in(db, settings: Settings, repository: Repository) -> RepositoryContext:
    return await build_context(db, settings, repository, DEPLOYER)


def test_two_versions_deployed_at_once_are_both_listed(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_releases(factory)

        async def deploy(version: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                path = f"com/acme/app/{version}/app-{version}.jar"
                await context.put(path, body(version.encode()))
                await asyncio.sleep(0.2)  # stay open while the other deploy happens
                await db.commit()

        await asyncio.gather(deploy("1.0"), deploy("1.1"))

        async with factory() as db:
            context = await context_in(db, settings, repository)
            assert sorted(await context.versions("com.acme", "app")) == ["1.0", "1.1"]

    run(empty_database, tmp_path, scenario)


def test_two_plugin_prefix_uploads_at_once_are_both_kept(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_releases(factory)
        async with factory() as db:
            context = await context_in(db, settings, repository)
            for artifact in ("a-plugin", "b-plugin"):
                await context.put(f"com/acme/{artifact}/1.0/{artifact}-1.0.jar", body(b"x"))
            await db.commit()

        async def upload(artifact: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                plugin = Plugin(artifact, artifact[0], artifact)
                await keep_plugins(context, GROUP, "com.acme", (plugin,))
                await asyncio.sleep(0.2)  # hold the path lock while the other waits for it
                await db.commit()

        await asyncio.gather(upload("a-plugin"), upload("b-plugin"))

        async with factory() as db:
            context = await context_in(db, settings, repository)
            stored = metadata.parse(await context.read(GROUP, limit=STORED_LIMIT))
            assert {plugin.artifact_id for plugin in stored.plugins} == {"a-plugin", "b-plugin"}

    run(empty_database, tmp_path, scenario)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_hosted_metadata.py tests/repositories/maven/test_hosted_plugins.py tests/repositories/maven/test_races.py -q`
Expected: `test_races.py` does not collect (`cannot import name 'STORED_LIMIT'`); nearly every other test fails, because an uploaded `maven-metadata.xml` is stored and served as a plain file.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/maven/format.py`, replace everything from the first `import` line down to and including the `_SETTINGS = …` line with:

```python
import hashlib
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.maven import checksums, metadata, paths
from megooarti.repositories.paths import normalise_path

log = structlog.get_logger(__name__)

_SETTINGS = ("version_policy", "layout_policy")
# The most that is read into memory: of an upload, and of the record the server keeps.
METADATA_LIMIT = 1024 * 1024
STORED_LIMIT = 4 * 1024 * 1024
_XML = "application/xml"
```

Replace `_digest` with the following, and add the functions after it:

```python
async def _digest(
    context: RepositoryContext, target: str, parsed: paths.MavenPath, algorithm: str
) -> tuple[str, datetime] | None:
    """The checksum of what a GET of `target` returns, and when that last changed."""
    if parsed.is_metadata:
        found = await document(context, target, parsed)
        if found is None:
            return None
        data, modified = found
        return hashlib.new(algorithm, data).hexdigest(), modified
    stored = await context.stat(target)
    if stored is None:
        return None
    return getattr(stored, algorithm), stored.modified


async def _plugins(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[tuple[metadata.Plugin, ...], datetime | None]:
    """The plugin entries kept for a group that still have a file, and when they changed."""
    if not parsed.plugin_group:
        return (), None
    stored = await context.stat(path)
    if stored is None or stored.kind != "metadata":
        return (), None
    try:
        record = metadata.parse(await context.read(path, limit=STORED_LIMIT) or b"")
    except (metadata.InvalidMetadata, TooLarge) as error:
        log.warning(
            "plugin_record_unreadable",
            repository=context.repository.name,
            path=path,
            reason=type(error).__name__,
        )
        return (), None
    present = await context.names(
        parsed.plugin_group, [plugin.artifact_id for plugin in record.plugins]
    )
    kept = tuple(plugin for plugin in record.plugins if plugin.artifact_id in present)
    return kept, stored.modified if kept else None


async def document(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[bytes, datetime] | None:
    """The metadata a GET of `path` returns now, and when it last changed.

    Built from the files the repository holds, so it is right after a delete and after
    two deploys at once. None when there is nothing to list.
    """
    if parsed.kind == "snapshot_metadata":
        entries = await context.files(parsed.group_id, parsed.artifact_id, parsed.version)
        built = metadata.for_snapshot(
            parsed.group_id,
            parsed.artifact_id,
            parsed.version,
            [(paths.classify(entry.path), entry.modified) for entry in entries],
        )
        changes = [entry.modified for entry in entries]
    else:
        versions = {}
        if parsed.artifact_id:
            versions = await context.versions(parsed.group_id, parsed.artifact_id)
        plugins, plugins_changed = await _plugins(context, path, parsed)
        built = metadata.for_artifact(parsed.group_id, parsed.artifact_id, versions, plugins)
        changes = [*versions.values(), *([plugins_changed] if plugins_changed else [])]
    if built is None:
        return None
    return metadata.serialise(built), max(changes)


async def keep_plugins(
    context: RepositoryContext, path: str, group_id: str, uploaded: Iterable[metadata.Plugin]
) -> None:
    """Merge uploaded plugin entries into the record kept for a group.

    Only the plugin's jar knows its prefix, so this is the one part of uploaded
    metadata that cannot be derived and has to be kept.
    """
    uploaded = tuple(uploaded)

    async def merged(current: bytes | None) -> bytes | None:
        stored: tuple[metadata.Plugin, ...] = ()
        if current is not None:
            with suppress(metadata.InvalidMetadata):
                stored = metadata.parse(current).plugins
        plugins = metadata.merge_plugins(stored, uploaded)
        present = await context.names(group_id, [plugin.artifact_id for plugin in plugins])
        kept = tuple(plugin for plugin in plugins if plugin.artifact_id in present)
        return metadata.serialise(metadata.Metadata(plugins=kept)) if kept else None

    await context.maintain(path, merged, content_type=_XML, limit=STORED_LIMIT)


async def _metadata(
    context: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> Response:
    """Answer for a maven-metadata.xml path. The document is generated, never stored."""
    if request.method in ("GET", "HEAD"):
        found = await document(context, path, parsed)
        if found is None:
            raise _not_found()
        data, modified = found
        return context.respond_with(
            data,
            request,
            filename=paths.METADATA_FILE,
            content_type=_XML,
            last_modified=modified,
        )
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "Metadata is generated from the files stored. It can be read or uploaded, "
            "not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=METADATA_LIMIT)
    if body is None:
        raise ApiError(400, "invalid_metadata", "The metadata is larger than 1 MiB.")
    if parsed.kind == "metadata":
        try:
            uploaded = metadata.parse(body)
        except metadata.InvalidMetadata as error:
            raise ApiError(
                400, "invalid_metadata", f"The metadata cannot be read: {error}."
            ) from None
        if parsed.plugin_group and uploaded.plugins:
            await keep_plugins(context, path, parsed.plugin_group, uploaded.plugins)
    # Everything else a client puts in metadata is derived here from the files stored.
    return Response(status_code=201)
```

In `_checksum`, add directly after the `body = await context.receive(...)` line:

```python
    if parsed.is_metadata:
        # It cannot be checked: the client's document is not the one served.
        return Response(status_code=201)
```

Replace the `handle_hosted` method of `MavenFormat` with:

```python
    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        # A checksum path is treated as the path it belongs to.
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if request.method == "PUT":
            _check_policies(context.repository.config["format_config"], parsed)
        if algorithm is not None:
            return await _checksum(context, request, path, target, parsed, algorithm)
        if parsed.is_metadata:
            return await _metadata(context, request, path, parsed)
        return await super().handle_hosted(context, request, path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven -q`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/maven/format.py backend/tests/repositories/maven
git commit -m "feat(maven): generate maven-metadata.xml and keep plugin prefixes"
```

---

### Task 10: Maven's own client, and documentation

**Files:**
- Create: `backend/tests/containers.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_container.py`
- Test: `backend/tests/test_maven_client.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: the whole of hosted Maven; `metadata.parse`; `versions.compare`.
- Produces:
  - `tests/containers.py`: `BACKEND_DIR`, `REPOSITORY_ROOT`, `PROJECT`, `HTTP_PORT`, `ENVIRONMENT`, `DATA_FILE`, `compose(*arguments, check=True)`, `run_in_backend(*arguments)`, `call(method, path, payload=None, headers=None)`.
  - `tests/conftest.py`: module-scoped fixtures `stack` and `administrator`, for any module of container tests.

These tests run only with `pytest -m docker`. They need a Docker daemon and, for Maven's plugins, internet access.

- [ ] **Step 1: Move the container helpers where a second module can use them**

`backend/tests/containers.py`:

```python
"""Helpers for tests that run the built image. They need a Docker daemon."""

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
PROJECT = "megooarti-test"
HTTP_PORT = "18000"
ENVIRONMENT = {**os.environ, "MEGOOARTI_HTTP_PORT": HTTP_PORT, "MEGOOARTI_DB_PORT": "15432"}
DATA_FILE = "/var/lib/megooarti/admin.password"


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=REPOSITORY_ROOT,
        env=ENVIRONMENT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def run_in_backend(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Start a throwaway backend container; `arguments` are `docker compose run` arguments."""
    return compose("run", "--rm", "--no-deps", "-T", *arguments, check=False)


def call(method: str, path: str, payload: dict | None = None, headers: dict | None = None):
    """A JSON request to the published backend port: (status, headers, body)."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/api/v1{path}",
        method=method,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, response.headers, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, error.headers, json.loads(error.read() or b"null")
```

In `backend/tests/conftest.py`, add `from tests.containers import DATA_FILE, call, compose` after the `from tests.clients import client_for` line, and append:

```python
@pytest.fixture(scope="module")
def stack():
    """The built image and its database, started afresh for each module of container tests."""
    compose("down", "--volumes", check=False)
    compose("build", "backend")
    compose("up", "--detach", "--wait", "--wait-timeout", "180")
    yield
    compose("down", "--volumes", check=False)


@pytest.fixture(scope="module")
def administrator(stack) -> dict[str, str]:
    """Sign in as the first-start administrator and change the password, once per module.

    Returns the headers that authenticate later requests as that session.
    """
    password = compose("exec", "-T", "backend", "cat", DATA_FILE).stdout.strip()
    assert password

    status, headers, session = call(
        "POST", "/auth/login", {"username": "admin", "password": password}
    )
    assert status == 200
    assert session["must_change_password"] is True
    credentials = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }

    status, _, _ = call(
        "PUT",
        "/me/password",
        {"current_password": password, "new_password": "a brand new password"},
        credentials,
    )
    assert status == 204
    return credentials
```

In `backend/tests/test_container.py`:

1. Replace everything from the first `import` line down to and including the `UNREACHABLE = …` line with:

```python
import hashlib
import json
import os
import urllib.request

import pytest

from tests.containers import BACKEND_DIR, DATA_FILE, HTTP_PORT, call, compose, run_in_backend

UNREACHABLE = "MEGOOARTI_DATABASE_URL=postgresql://megooarti:megooarti@nowhere.invalid:5432/m"
```

2. Delete its definitions of `compose`, `run_in_backend`, the `stack` fixture, `DATA_FILE`, `call` and the `administrator` fixture. The tests themselves do not change.

Run: `uv run pytest -q && uv run ruff check . && uv run pytest -m docker tests/test_container.py -q`
Expected: the ordinary suite passes with the same count as before, ruff is clean, and the 8 container tests pass.

- [ ] **Step 2: Commit the move**

```bash
git add backend/tests/containers.py backend/tests/conftest.py backend/tests/test_container.py
git commit -m "test: share the container-test helpers and fixtures"
```

- [ ] **Step 3: Write the real-client tests**

`backend/tests/test_maven_client.py`:

```python
"""Maven's own client against the built image.

Run with `pytest -m docker`. Besides a Docker daemon these need internet access: Maven
fetches its plugins from Maven Central.
"""

import hashlib
import re
import subprocess
import urllib.request
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path

import pytest

from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.versions import compare
from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "maven:3.9-eclipse-temurin-21"
NETWORK = f"{PROJECT}_default"
CACHE = f"{PROJECT}-maven-cache"
# The backend as a container on the Compose network sees it, and as this test does.
INSIDE = "http://backend:8000/repository"
OUTSIDE = f"http://127.0.0.1:{HTTP_PORT}/repository"
LIBRARY = "io/megooarti/test/library"
MAVEN = "mvn --batch-mode --settings settings.xml"

# Maven refuses plain HTTP to another host unless its built-in blocking mirror is
# replaced. The stack has no TLS, so the test replaces it with one that matches nothing.
SETTINGS = """<settings>
  <servers>
    <server><id>megooarti</id><username>admin</username><password>{token}</password></server>
    <server>
      <id>megooarti-snapshots</id><username>admin</username><password>{token}</password>
    </server>
  </servers>
  <mirrors>
    <mirror>
      <id>maven-default-http-blocker</id>
      <mirrorOf>external:does-not-match-anything:*</mirrorOf>
      <url>http://0.0.0.0/</url>
      <blocked>false</blocked>
    </mirror>
  </mirrors>
</settings>
"""

LIBRARY_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.megooarti.test</groupId>
  <artifactId>library</artifactId>
  <version>{version}</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <distributionManagement>
    <repository><id>megooarti</id><url>{server}/releases/</url></repository>
    <snapshotRepository><id>megooarti</id><url>{server}/snapshots/</url></snapshotRepository>
  </distributionManagement>
</project>
"""

LIBRARY_SOURCE = """package io.megooarti.test;

public class Library {
    public static String greeting() {
        return "hello";
    }
}
"""

CONSUMER_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.megooarti.test</groupId>
  <artifactId>consumer</artifactId>
  <version>1</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <repositories>
    <repository>
      <id>megooarti</id>
      <url>{server}/releases/</url>
      <snapshots><enabled>false</enabled></snapshots>
    </repository>
    <repository>
      <id>megooarti-snapshots</id>
      <url>{server}/snapshots/</url>
      <releases><enabled>false</enabled></releases>
      <snapshots><enabled>true</enabled></snapshots>
    </repository>
  </repositories>
  <dependencies>
    <dependency>
      <groupId>io.megooarti.test</groupId>
      <artifactId>library</artifactId>
      <version>{version}</version>
    </dependency>
  </dependencies>
</project>
"""

CONSUMER_SOURCE = """package io.megooarti.test.consumer;

import io.megooarti.test.Library;

public class Consumer {
    public static String greeting() {
        return Library.greeting();
    }
}
"""


def write(directory: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    return directory


def library(directory: Path, version: str, token: str) -> Path:
    files = {
        "settings.xml": SETTINGS.format(token=token),
        "pom.xml": LIBRARY_POM.format(version=version, server=INSIDE),
        "src/main/java/io/megooarti/test/Library.java": LIBRARY_SOURCE,
    }
    return write(directory, files)


def consumers(directory: Path, versions: dict[str, str], token: str) -> Path:
    """One project per name in `versions`, each depending on that version of the library."""
    files = {"settings.xml": SETTINGS.format(token=token)}
    for name, version in versions.items():
        files[f"{name}/pom.xml"] = CONSUMER_POM.format(version=version, server=INSIDE)
        files[f"{name}/src/main/java/io/megooarti/test/consumer/Consumer.java"] = CONSUMER_SOURCE
    return write(directory, files)


def maven(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Maven image, in a copy of `project`, beside the stack."""
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{CACHE}:/root/.m2",
        "--volume",
        f"{project}:/src:ro",
        IMAGE,
        "sh",
        "-c",
        f"cp -r /src /work && cd /work && {script}",
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )


def fetch(path: str, token: str) -> bytes:
    request = urllib.request.Request(
        f"{OUTSIDE}/{path}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


@pytest.fixture(scope="module")
def token(administrator) -> Iterator[str]:
    """An API token for `admin`, with a release and a snapshot repository to deploy to."""
    status, _, created = call("POST", "/me/tokens", {"name": "maven-client"}, administrator)
    assert status == 201
    for name, version_policy, deployment_policy in (
        ("releases", "release", "disable_redeploy"),
        ("snapshots", "snapshot", "allow_redeploy"),
    ):
        repository = {
            "name": name,
            "format": "maven",
            "type": "hosted",
            "hosted": {"deployment_policy": deployment_policy},
            "format_config": {"version_policy": version_policy},
        }
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body
    yield created["token"]
    subprocess.run(["docker", "volume", "rm", "--force", CACHE], capture_output=True, check=False)


def test_maven_deploys_a_release_and_two_snapshot_builds_and_resolves_them(token, tmp_path):
    release = library(tmp_path / "release", "1.0", token)
    snapshot = library(tmp_path / "snapshot", "1.1-SNAPSHOT", token)

    deployed = maven(release, f"{MAVEN} deploy")
    assert deployed.returncode == 0, deployed.stdout[-4000:]
    again = maven(release, f"{MAVEN} deploy")
    assert again.returncode != 0, "a release was deployed twice despite disable_redeploy"
    assert "409" in again.stdout, again.stdout[-4000:]
    for _ in range(2):
        built = maven(snapshot, f"{MAVEN} deploy")
        assert built.returncode == 0, built.stdout[-4000:]

    jar = fetch(f"releases/{LIBRARY}/1.0/library-1.0.jar", token)
    sha1 = fetch(f"releases/{LIBRARY}/1.0/library-1.0.jar.sha1", token)
    assert jar.startswith(b"PK")
    assert sha1.decode() == hashlib.sha1(jar).hexdigest()
    assert b"<artifactId>library</artifactId>" in fetch(
        f"releases/{LIBRARY}/1.0/library-1.0.pom", token
    )
    listed = metadata.parse(fetch(f"releases/{LIBRARY}/maven-metadata.xml", token))
    assert (listed.versions, listed.latest, listed.release) == (("1.0",), "1.0", "1.0")

    directory = f"snapshots/{LIBRARY}/1.1-SNAPSHOT"
    builds = metadata.parse(fetch(f"{directory}/maven-metadata.xml", token))
    newest = {entry.extension: entry.value for entry in builds.snapshot_versions}
    assert builds.snapshot_build == 2
    assert set(newest) == {"jar", "pom"}
    assert newest["jar"].endswith("-2")
    assert fetch(f"{directory}/library-{newest['jar']}.jar", token).startswith(b"PK")

    # A local repository that has never seen the library: everything comes from the server.
    versions = {"release": "1.0", "snapshot": "1.1-SNAPSHOT"}
    projects = consumers(tmp_path / "consumers", versions, token)
    fresh = f"{MAVEN} -Dmaven.repo.local=/tmp/empty-repository"
    resolved = maven(
        projects, f"{fresh} -f release/pom.xml compile && {fresh} -f snapshot/pom.xml compile"
    )
    assert resolved.returncode == 0, resolved.stdout[-4000:]
    assert f"Downloaded from megooarti: {INSIDE}/releases/{LIBRARY}/1.0/library-1.0.jar" in (
        resolved.stdout
    )
    assert (
        f"Downloaded from megooarti-snapshots: {INSIDE}/{directory}/library-{newest['jar']}.jar"
        in resolved.stdout
    )


# Ordinary versions, the qualifiers, and the forms that are easy to get wrong.
VERSIONS = [
    "1.0",
    "1.0-alpha-1",
    "1.0-a2",
    "1.0-beta-1",
    "1.0-m3",
    "1.0-rc1",
    "1.0-cr1",
    "1.0-SNAPSHOT",
    "1.0-final",
    "1.0.0",
    "1",
    "1.0-sp1",
    "1.0-1",
    "1.0.1",
    "1.1",
    "1.10",
    "1.9",
    "2.0-1",
    "2.0.1",
    "1.2.3-jre",
    "1.2.3-android",
    "1.2.3",
    "1.2.3.RELEASE",
    "5.0.0.Final",
    "5.0.0",
    "4.1.0.Beta1",
    "4.1.0.Final",
    "1.0.RC1",
    "1.0-RC1",
    "1.0.RC2",
    "1.foo",
    "1-foo",
    "1-1",
    "1-sp-1",
    "1-ga-1",
    "1-sp.1",
    "1-ga.1",
    "20040616",
    "3.0-M1",
    "3.0",
]


def test_our_version_order_is_mavens():
    """Maven compares each version with the one before it; so do we."""
    java = (
        "java -cp /usr/share/maven/lib/maven-artifact-*.jar "
        "org.apache.maven.artifact.versioning.ComparableVersion"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", IMAGE, "sh", "-c", f"{java} {' '.join(VERSIONS)}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    theirs = re.findall(r"^\s+(\S+) (<|==|>) (\S+)$", result.stdout, re.MULTILINE)
    symbol = {-1: "<", 0: "==", 1: ">"}
    ours = [(one, symbol[compare(one, other)], other) for one, other in pairwise(VERSIONS)]

    assert [tuple(line) for line in theirs] == ours
```

- [ ] **Step 4: Run them**

Run: `uv run pytest -m docker tests/test_maven_client.py -q`
Expected: 2 passed. The first run pulls the Maven image and downloads Maven's plugins, and can take several minutes.

If `test_our_version_order_is_mavens` shows a pair on which Maven disagrees, Maven is right. Add the pair to `EQUAL` or `OLDER_THEN_NEWER` in `tests/repositories/maven/test_versions.py`, watch that test fail, and change `versions.py` until both pass.

If the deploy test fails, the Maven output in the assertion message names the request that failed and its status. Fix the server, not the test: this test is what "compatible with Maven" means.

- [ ] **Step 5: Document it**

In `README.md`, replace the first paragraph of the section `## Repositories` (it begins "A **blob store** is where") with:

```markdown
A **blob store** is where file content is kept; the `default` one is a directory under
the data directory. A **repository** holds files in one format. The formats so far are
`raw` (arbitrary files by path) and `maven` (hosted repositories only, for now). A
repository has one of three types: `hosted` (files you publish), `proxy` (a cache of a
remote repository) or `group` (several repositories behind one URL).
```

Add after the `### Group repositories` section, before `## Health endpoints`:

````markdown
### Maven repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "releases", "format": "maven", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"},
  "format_config": {"version_policy": "release"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "snapshots", "format": "maven", "type": "hosted",
  "format_config": {"version_policy": "snapshot"}
}' http://localhost:8000/api/v1/repositories
```

Point a project at them in its `pom.xml`:

```xml
<distributionManagement>
  <repository>
    <id>megooarti</id>
    <url>https://repo.example.com/repository/releases/</url>
  </repository>
  <snapshotRepository>
    <id>megooarti</id>
    <url>https://repo.example.com/repository/snapshots/</url>
  </snapshotRepository>
</distributionManagement>
```

and give Maven the credentials in `~/.m2/settings.xml`, under the same `id`:

```xml
<servers>
  <server>
    <id>megooarti</id>
    <username>ci</username>
    <password>an API token</password>
  </server>
</servers>
```

- **Version policy** (`version_policy`): `release` (default), `snapshot` or `mixed`. It
  decides which versions a repository takes, and cannot be changed after creation.
- **Layout policy** (`layout_policy`): `strict` (default) takes only paths in the Maven
  layout; `permissive` also takes other paths, as plain files.
- **Checksums are computed, never stored.** A request for `app-1.0.jar.sha1` (or `.md5`,
  `.sha256`, `.sha512`) is answered from the hash recorded for the file. A checksum that
  a client uploads is compared with the file, and a wrong one fails the upload with
  `400`, so a corrupted deploy fails visibly.
- **`maven-metadata.xml` is generated** on every request from the files stored, so it is
  right after a delete and after two deploys at the same moment. What clients upload is
  accepted and discarded, except plugin prefixes, which are kept for each group.
- `latest` and `release` are the highest versions in Maven's version order, not the
  most recently deployed ones.
- **A deploying account needs only `add`**, for example `repository:maven:releases:add`.
  It does not need `edit` to update metadata. Add `read` if it also resolves.
- **Maven refuses plain HTTP** to any host but `localhost` (since Maven 3.8.1). Put
  MegooArti behind HTTPS for clients on other machines.
- Proxy and group Maven repositories are not available yet.
````

In the section `## Development`, replace the line `uv run pytest -m docker       # builds the image and tests the entrypoint` with:

```bash
uv run pytest -m docker       # builds the image; tests it with real clients (needs internet)
```

- [ ] **Step 6: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -m docker -q`
Expected: all pass, no findings; 10 container tests.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_maven_client.py README.md
git commit -m "test(maven): deploy and resolve with Maven itself; document Maven repositories"
```
