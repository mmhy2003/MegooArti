# Maven Proxy and Group Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mvn` builds a project whose plugins and dependencies all arrive through one MegooArti URL: a group of hosted Maven repositories and a proxy of Maven Central, with `maven-metadata.xml` merged across the members.

**Architecture:** Each engine (hosted, proxy, group) becomes a hook on the format, with today's generic engine as the default, so Maven can answer checksum and metadata paths itself and leave everything else alone. The proxy engine splits into `ensure_cached` (make a path servable from the cache) and responding, and the outbound HTTP client travels with the repository context, so a format can fetch a file and then read it. The group engine exposes its walk over members, and Maven's group handler merges every member's metadata into one document.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, httpx (outbound), the standard library's XML modules, pytest + pytest-asyncio, Docker (the `maven:3.9-eclipse-temurin-21` image, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-08-maven-format-design.md](../specs/2026-10-08-maven-format-design.md), sections 4.2, 5.1, 5.2, 7, 8 and the plan 4b part of 11. Business requirements: [docs/BRD.md](../../BRD.md) FMT-1 (proxy, group), REP-12 (Maven), NFR-1.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `Format.handle_proxy` and `Format.handle_group` import the generic engines inside the method. | The engines are written against the format module; importing them at the top would be a cycle. |
| P2 | The context carries `outbound`, a function that returns the application's HTTP client, and `http()` calls it. | The client is still built on first use, and a member's context can be given the group's. |
| P3 | `ensure_cached(context, path)` returns nothing; the caller then reads through the context. | One function has one job, and the context already knows how to read. |
| P4 | `require_write` and `maintain` raise `RuntimeError` on a repository that is not hosted. | Like `cache` on a non-proxy, this is a programming error, not bad input. Deferred from the 4a review. |
| P5 | Building, merging, reading and writing metadata run in a worker thread. | A long version list must not hold up every other request. Deferred from the 4a review. |
| P6 | Parsed XML is limited to 16 levels of nesting and 100,000 elements. | Remote documents are read without any permission being needed. Deferred from the 4a review. |
| P7 | A proxy still serves a path its policy now excludes, if it is already cached. It does not ask the remote for one that is not. | Spec 5.1: the policy governs what is added, not what is served. |
| P8 | The format's `content_type` hook also applies to files a proxy fetches. | A proxied `.pom` should have the same type as a deployed one. |
| P9 | In a group, `latest`, `release` and the order of versions are always recomputed from the merged list. | A member's own `latest` describes only that member. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; settings prefixed `MEGOOARTI_`; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; only the security package reads `Principal.patterns`; every route authenticates unless on the open list; content responses always carry `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; formats do not commit, the route does; remote secrets are never returned, logged or stored unsealed; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration and no dependency.**
- **Only `maven/format.py` touches the repository context.** The other Maven modules stay pure.
- **`ensure_cached` commits.** It commits before waiting for a download and after recording its result. A caller must have no uncommitted work of its own when it calls it.
- **A proxy never requests a checksum file from its remote**, and never stores one.
- **A proxy serves the remote's `maven-metadata.xml` exactly as received.** Only a group builds a new document.
- **Reading through a group needs `read` on the group only.** Members are not checked again.
- **A member that cannot contribute is skipped, never fatal:** offline, remote unavailable, path excluded by its policy, document over 4 MiB, document unreadable. The last two are logged.
- A test must never contact a real network host: tests replace `app.state.http` with a client wired to the in-process fake remote. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A remote's metadata that is huge, broken or hostile:** over 4 MiB, not XML, carrying a `DOCTYPE`, nested hundreds of levels deep, or holding hundreds of thousands of elements. The member is left out, the group still answers, and nothing is expanded (Tasks 4, 6).
2. **A member that cannot answer:** its remote is down, it is offline, or its policy excludes the path. The group answers from the others; if none can, the answer is `404`, never `502` (Task 6).
3. **A checksum asked for before its file,** through a proxy and through a group, by `GET` and by `HEAD`. The file is fetched once, the hash matches the bytes later served, and the remote is never asked for a checksum file (Tasks 5, 6).
4. **A reader allowed on the group only.** They get merged metadata, with proxies fetching on their behalf. A reader allowed on a member but not on the group gets nothing from the group (Task 6).
5. **A path a release proxy must not ask for:** a snapshot file, its checksum, its metadata, or a path outside the layout. Each is `404` with no request to the remote; a file cached before the policy was tightened is still served (Task 5).

---

### Task 1: Core: every engine is a hook on the format

**Files:**
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/dispatch.py`
- Modify: `backend/src/megooarti/repositories/proxy.py`
- Modify: `backend/tests/repositories/test_dispatch.py`
- Modify: `backend/tests/repositories/test_proxy.py`

**Interfaces:**
- Consumes: `proxy.handle_proxy(context, request, path)`, `group.handle_group(context, request, path, serve)`, `Format.content_type`.
- Produces:
  - `megooarti.repositories.formats.Serve` — the type of the dispatcher: `Callable[[RepositoryContext, Request, str], Awaitable[Response]]`.
  - `await Format.handle_proxy(context, request, path) -> Response` — default: the generic proxy engine.
  - `await Format.handle_group(context, request, path, serve: Serve) -> Response` — default: the generic group engine.
  - The dispatcher calls `handle_hosted`, `handle_proxy` or `handle_group` on `context.format`, by repository type.
  - The generic proxy engine records `context.format.content_type(path, <remote's Content-Type>)` for a fetched file.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/test_dispatch.py`, replace the imports with:

```python
from starlette.responses import Response

from megooarti.repositories import formats, service
from megooarti.repositories.dispatch import ENGINES
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic, error_code
```

and append:

```python
class Answering(Format):
    """A format that answers for its own proxy and group repositories."""

    name = "raw"

    async def handle_proxy(self, context, request, path):
        return Response(f"proxy hook: {path}")

    async def handle_group(self, context, request, path, serve):
        return Response(f"group hook: {path}")


async def test_a_format_answers_for_its_proxy_and_group_repositories(
    client, make_user, db, mirror, fake_remote, monkeypatch
):
    await make_user("root", roles=["admin"])
    root = basic("root", PASSWORD)
    await service.create_repository(
        db,
        name="all",
        format="raw",
        type="group",
        online=True,
        blob_store=None,
        group={"members": ["mirror"]},
    )
    await db.commit()
    monkeypatch.setitem(formats._registry, "raw", Answering())

    through_proxy = await client.get("/repository/mirror/a/b.bin", headers=root)
    through_group = await client.get("/repository/all/a/b.bin", headers=root)

    assert through_proxy.text == "proxy hook: a/b.bin"
    assert through_group.text == "group hook: a/b.bin"
```

In `backend/tests/repositories/test_proxy.py`, change the import `from megooarti.repositories import proxy` to `from megooarti.repositories import formats, proxy`, then append:

```python
class Typed(Format):
    """A format that decides the content type of what it stores."""

    name = "raw"

    def content_type(self, path, declared):
        return "application/x-chosen"


async def test_the_format_chooses_the_type_recorded_for_a_fetched_file(
    client, root, remote, monkeypatch
):
    monkeypatch.setitem(formats._registry, "raw", Typed())

    response = await client.get(URL, headers=root)

    assert response.headers["Content-Type"] == "application/x-chosen"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_dispatch.py tests/repositories/test_proxy.py -q`
Expected: 2 failures. The proxy and the group answer `404` from the generic engines, not from the hooks; and the fetched file's type is `application/x-remote`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`, change the first two import lines to:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
```

Add after the `if TYPE_CHECKING:` block:

```python
# The dispatcher, as an engine sees it: answer this request from that repository.
Serve = Callable[["RepositoryContext", Request, str], Awaitable[Response]]
```

Replace the `content_type` method of `Format` with:

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        """The content type to record for a file: an upload, or one a proxy fetched.

        The generic format trusts what the client or the remote declared.
        """
        return declared
```

Add these methods to `Format`, after `handle_hosted`:

```python
    async def handle_proxy(
        self, context: "RepositoryContext", request: Request, path: str
    ) -> Response:
        """Answer a request to a proxy repository. The route has checked `read`.

        The generic engine: fetch from the remote on a miss, cache, and keep serving.
        """
        # Imported here: the engine is written against this module, so a top-level
        # import would be circular.
        from megooarti.repositories import proxy

        return await proxy.handle_proxy(context, request, path)

    async def handle_group(
        self, context: "RepositoryContext", request: Request, path: str, serve: Serve
    ) -> Response:
        """Answer a request to a group. `serve` is the dispatcher, for asking a member.

        The generic engine: the first member, in order, that has the path.
        """
        from megooarti.repositories import group

        return await group.handle_group(context, request, path, serve)
```

Replace `backend/src/megooarti/repositories/dispatch.py` with:

```python
"""Send a request for repository content to the engine for the repository's type.

An engine answers for one type of repository, through the format's hook for that type,
so a format can answer some paths itself and leave the rest to the generic engine. An
engine does not authenticate, authorise `read`, or commit: the route does those.
"""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext

Engine = Callable[[RepositoryContext, Request, str], Awaitable[Response]]


async def _hosted(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_hosted(context, request, path)


async def _proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_proxy(context, request, path)


async def _group(context: RepositoryContext, request: Request, path: str) -> Response:
    return await context.format.handle_group(context, request, path, serve)


ENGINES: dict[str, Engine] = {"hosted": _hosted, "proxy": _proxy, "group": _group}


async def serve(context: RepositoryContext, request: Request, path: str) -> Response:
    engine = ENGINES.get(context.repository.type)
    if engine is None:
        raise ApiError(
            503, "repository_unavailable", "This version cannot serve this kind of repository."
        )
    return await engine(context, request, path)
```

In `backend/src/megooarti/repositories/proxy.py`, in `_refresh`, replace the line `content_type=outcome.content_type,` with:

```python
            content_type=context.format.content_type(path, outcome.content_type),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(repositories): every engine is a hook on the format"
```

---

### Task 2: Core: the outbound client travels with the context, and fetching is its own step

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/routes.py`
- Modify: `backend/src/megooarti/repositories/group.py`
- Modify: `backend/src/megooarti/repositories/proxy.py`
- Modify: `backend/tests/repositories/conftest.py`
- Modify: `backend/tests/repositories/test_proxy.py`
- Modify: `backend/tests/repositories/test_proxy_races.py`

**Interfaces:**
- Consumes: `remote.client_of(app)`, `remote.download`, `remote.head`, `proxy_state`, `KeyedLocks`.
- Produces:
  - `RepositoryContext(…, outbound: Callable[[], Any] | None = None)`; attribute `context.outbound`; `context.http()` returns the client, or raises `RuntimeError` if the context has none.
  - `await build_context(db, settings, repository, principal, outbound=None) -> RepositoryContext`.
  - `await proxy.ensure_cached(context, path: str) -> None` — returns when `path` can be served from the cache; raises `ApiError` `404 not_found` or `502 remote_unavailable` otherwise. It commits.
  - `proxy.handle_proxy(context, request, path)` no longer reads `request.app`.
  - Test fixture `context_for(repository, principal, outbound=None)`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/conftest.py`, replace the `context_for` fixture with:

```python
@pytest.fixture
def context_for(db, settings):
    async def make(
        repository: Repository, principal: Principal | None, outbound=None
    ) -> RepositoryContext:
        return await build_context(db, settings, repository, principal, outbound=outbound)

    return make
```

In `backend/tests/repositories/test_proxy.py`, add `from megooarti.errors import ApiError` to the imports, then append:

```python
async def test_ensure_cached_fetches_a_missing_file_once(app, context_for, mirror, remote):
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    await proxy.ensure_cached(context, "lib/a.bin")
    await proxy.ensure_cached(context, "lib/a.bin")

    assert await context.read("lib/a.bin", limit=1000) == CONTENT
    assert remote.paths() == [REMOTE_PATH]


async def test_ensure_cached_raises_what_the_engine_would_answer(
    app, context_for, mirror, remote
):
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    with pytest.raises(ApiError) as missing:
        await proxy.ensure_cached(context, "lib/absent.bin")
    remote.down = True
    with pytest.raises(ApiError) as unavailable:
        await proxy.ensure_cached(context, "lib/other.bin")

    assert (missing.value.status_code, missing.value.code) == (404, "not_found")
    assert (unavailable.value.status_code, unavailable.value.code) == (
        502,
        "remote_unavailable",
    )


async def test_ensure_cached_keeps_a_stale_copy_when_the_remote_is_down(
    app, context_for, mirror, remote, db
):
    context = await context_for(mirror, None, outbound=lambda: app.state.http)
    await proxy.ensure_cached(context, "lib/a.bin")
    await make_stale(db)
    remote.down = True

    await proxy.ensure_cached(context, "lib/a.bin")

    assert await context.read("lib/a.bin", limit=1000) == CONTENT


async def test_a_context_without_an_outbound_client_cannot_fetch(context_for, mirror):
    context = await context_for(mirror, None)

    with pytest.raises(RuntimeError):
        await proxy.ensure_cached(context, "lib/a.bin")
```

Replace `backend/tests/repositories/test_proxy_races.py` with:

```python
"""Many readers of one uncached file, with real concurrent database sessions."""

import asyncio

from starlette.requests import Request

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import build_context
from megooarti.repositories.models import Repository
from megooarti.repositories.proxy import handle_proxy
from tests.repositories.fake_remote import FakeRemote
from tests.storage.test_races import Factory, run

CONTENT = b"a large file, slowly served" * 1000


def test_many_readers_of_one_uncached_file_ask_the_remote_once(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        async with factory() as db:
            repository = await service.create_repository(
                db,
                name="mirror",
                format="raw",
                type="proxy",
                online=True,
                blob_store=None,
                proxy={"remote_url": "http://remote.test/files"},
            )
            await db.commit()
        fake = FakeRemote()
        fake.files["files/big.bin"] = CONTENT
        fake.delay = 0.2
        http = fake.client()

        async def read_once() -> bytes:
            async with factory() as db:
                mirror = await db.get(Repository, repository.id)
                context = await build_context(db, settings, mirror, None, outbound=lambda: http)
                request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
                response = await handle_proxy(context, request, "big.bin")
                return b"".join([chunk async for chunk in response.body_iterator])

        try:
            bodies = await asyncio.gather(*(read_once() for _ in range(6)))
        finally:
            await http.aclose()

        assert bodies == [CONTENT] * 6
        assert fake.paths() == ["/files/big.bin"]

    run(empty_database, tmp_path, scenario)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_proxy.py tests/repositories/test_proxy_races.py -q`
Expected: the four new tests and the race test fail with `TypeError: build_context() got an unexpected keyword argument 'outbound'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/content.py`, in `RepositoryContext.__init__`, add the parameter `outbound: Callable[[], Any] | None = None,` after `backend: BlobBackend | None,`, and add after the line `self.backend = backend  # None for a group, which stores nothing itself`:

```python
        # How to get the application's outbound HTTP client; None if there is none.
        self.outbound = outbound
```

Add this method to `RepositoryContext`, after `permission`:

```python
    def http(self) -> Any:
        """The application's outbound HTTP client, for fetching from a remote."""
        if self.outbound is None:
            raise RuntimeError("this context was built without an outbound client")
        return self.outbound()
```

Replace `build_context` with:

```python
async def build_context(
    db: AsyncSession,
    settings: Settings,
    repository: Repository,
    principal: Principal | None,
    outbound: Callable[[], Any] | None = None,
) -> RepositoryContext:
    backend = None
    if repository.blob_store_id is not None:
        store = await db.get(BlobStore, repository.blob_store_id)
        backend = backend_for(settings, store)
    return RepositoryContext(
        db=db,
        settings=settings,
        repository=repository,
        principal=principal,
        format=get_format(repository.format),
        backend=backend,
        outbound=outbound,
    )
```

In `backend/src/megooarti/repositories/routes.py`, change the import `from megooarti.repositories import dispatch, service` to `from megooarti.repositories import dispatch, remote, service`, and replace the line that builds the context with:

```python
    context = await build_context(
        db,
        request.app.state.settings,
        repository,
        principal,
        # Built on first use: most requests never reach a remote.
        outbound=lambda: remote.client_of(request.app),
    )
```

In `backend/src/megooarti/repositories/group.py`, replace the call to `build_context` with:

```python
            member_context = await build_context(
                context.db,
                context.settings,
                member,
                context.principal,
                outbound=context.outbound,
            )
```

Replace `backend/src/megooarti/repositories/proxy.py` with:

```python
"""Proxy repositories: fetch from the remote on a miss, cache, and keep serving.

A missing file is downloaded completely, verified and recorded, and only then served.
Every exit that the client should remember (a cached file, a remembered miss, a
recorded failure) is committed here, because several of them end in an error response.
"""

from datetime import datetime, timedelta
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.keyed_locks import KeyedLocks
from megooarti.repositories import proxy_state, remote
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import Format
from megooarti.repositories.models import Asset
from megooarti.repositories.paths import normalise_path
from megooarti.secrets_box import SecretUnreadable
from megooarti.storage.backends import StagedBlob

log = structlog.get_logger(__name__)

# Within this process, concurrent requests for one uncached path share one download.
_downloads = KeyedLocks()


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


def _unavailable(reason: str) -> ApiError:
    return ApiError(502, "remote_unavailable", f"The remote repository is not available: {reason}.")


def is_fresh(
    settings: dict[str, Any], format: Format, asset: Asset, path: str, now: datetime
) -> bool:
    """Whether a cached file may be served without asking the remote."""
    if asset.last_verified_at is None:
        return False
    kind = "metadata" if format.is_metadata(path) else "content"
    minutes = settings[f"{kind}_max_age_minutes"]
    return minutes < 0 or now - asset.last_verified_at < timedelta(minutes=minutes)


def _fresh(context: RepositoryContext, asset: Asset | None, path: str) -> bool:
    if asset is None:
        return False
    settings = context.repository.config["proxy"]
    return is_fresh(settings, context.format, asset, path, utcnow())


async def _target(context: RepositoryContext, path: str) -> tuple[str, str | None]:
    """The remote URL for a path and the Authorization header to send with it."""
    settings = context.repository.config["proxy"]
    try:
        credential = remote.authorization(context.settings, settings["remote_auth"])
    except SecretUnreadable:
        # Recorded and logged, not only raised: behind a group this 502 becomes a 404,
        # and the repository's status is then the only place the cause can be seen.
        unreadable = remote.Failed(
            "its stored credential cannot be read with the current key; enter it again",
            blockable=False,
        )
        raise _unavailable(await _fail(context, path, unreadable)) from None
    return context.format.remote_url(settings["remote_url"], path), credential


async def _fail(context: RepositoryContext, path: str, outcome: object) -> str:
    """Record that the remote did not help. Returns the reason, for the caller to use."""
    if isinstance(outcome, remote.Failed):
        reason, blockable = outcome.reason, outcome.blockable
    else:
        reason, blockable = "it gave an answer that makes no sense here", False
    await proxy_state.record_failure(
        context.db, context.repository, utcnow(), reason, blockable=blockable
    )
    await context.db.commit()
    log.warning("remote_failed", repository=context.repository.name, path=path, reason=reason)
    return reason


async def _refresh(context: RepositoryContext, path: str, asset: Asset | None) -> None:
    """Make `path` servable from the cache, or raise 404 or 502.

    Returning without raising means there is a copy to serve: a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.
    """
    db, repository = context.db, context.repository
    now = utcnow()
    if asset is None and await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        if asset is None:
            raise _unavailable("it is blocked")
        return
    url, credential = await _target(context, path)
    known = {} if asset is None else asset.attributes
    await db.commit()  # give the connection back for the length of the download

    async def stage(chunks, size: int | None) -> StagedBlob:
        return await context.stage(chunks, expected_size=size)

    outcome = await remote.download(
        context.http(),
        url,
        authorization=credential,
        stage=stage,
        etag=known.get("remote_etag"),
        last_modified=known.get("remote_last_modified"),
    )
    now = utcnow()

    if isinstance(outcome, remote.Fetched):
        origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
        await context.cache(
            path,
            outcome.staged,
            content_type=context.format.content_type(path, outcome.content_type),
            attributes={name: value for name, value in origin.items() if value},
            now=now,
        )
        await proxy_state.record_success(db, repository, now)
        await db.commit()
    elif isinstance(outcome, remote.NotModified) and asset is not None:
        asset.last_verified_at = now
        await proxy_state.record_success(db, repository, now)
        await db.commit()
    elif isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)  # the remote did answer
        if asset is None:
            await proxy_state.remember_missing(db, repository, path, now)
            await db.commit()
            raise _not_found()
        # The remote dropped a file we hold. An artifact manager keeps it.
        asset.last_verified_at = now
        await db.commit()
    else:
        reason = await _fail(context, path, outcome)
        if asset is None:
            raise _unavailable(reason)


async def _head_remote(context: RepositoryContext, path: str) -> Response:
    """Answer HEAD for a file that is not cached by asking the remote. Caches nothing."""
    db, repository = context.db, context.repository
    now = utcnow()
    if await proxy_state.known_missing(db, repository, path, now):
        raise _not_found()
    if await proxy_state.blocked(db, repository, now):
        raise _unavailable("it is blocked")
    url, credential = await _target(context, path)
    await db.commit()

    outcome = await remote.head(context.http(), url, authorization=credential)
    now = utcnow()
    if isinstance(outcome, remote.Exists):
        await proxy_state.record_success(db, repository, now)
        await db.commit()
        headers = {**outcome.headers, "X-Content-Type-Options": "nosniff"}
        return Response(status_code=200, headers=headers)
    if isinstance(outcome, remote.Missing):
        await proxy_state.record_success(db, repository, now)
        await proxy_state.remember_missing(db, repository, path, now)
        await db.commit()
        raise _not_found()
    raise _unavailable(await _fail(context, path, outcome))


async def ensure_cached(context: RepositoryContext, path: str) -> None:
    """Make `path` servable from this proxy's cache, or raise 404 or 502.

    Returning means there is a copy to serve: a fresh one, a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.

    This commits: before waiting for a download, and to record what came of it. A
    caller must have no uncommitted work of its own when it calls this.
    """
    path = normalise_path(path)
    asset = await context.get(path)
    if _fresh(context, asset, path):
        return
    await context.db.commit()  # hold no connection while waiting for another's download
    async with _downloads.hold((context.repository.id, path)):
        asset = await context.get(path, fresh=True)  # the previous holder may have fetched it
        if not _fresh(context, asset, path):
            await _refresh(context, path, asset)


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a proxy repository. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    if request.method == "HEAD" and await context.get(path) is None:
        return await _head_remote(context, path)
    await ensure_cached(context, path)
    return await context.respond(path, request)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(repositories): carry the outbound client on the context and split fetching from answering"
```

---

### Task 3: Core: the group's walk over its members, and uploads only to hosted repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/group.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/tests/repositories/test_group.py`
- Modify: `backend/tests/repositories/test_content_maintain.py`

**Interfaces:**
- Consumes: Task 1's `Serve`; Task 2's `outbound`.
- Produces:
  - `megooarti.repositories.group.TRY_NEXT = frozenset({404, 502, 503})` — the statuses by which a member says "not from me".
  - `await group.member_contexts(context, request) -> list[RepositoryContext]` — the online members in order, each with the group's principal and outbound client. A group gives its members once in a request; asked again, it gives none.
  - `context.require_write()` and `context.maintain(…)` raise `RuntimeError` on a repository whose type is not `hosted`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/test_group.py`, replace the imports with:

```python
import pytest
from sqlalchemy import insert
from starlette.requests import Request

from megooarti.repositories import group, service
from megooarti.repositories.models import RepositoryMember
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.conftest import someone
```

and append:

```python
def bare_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def test_member_contexts_are_the_online_members_in_order(db, everything, context_for):
    reader = someone("repository:raw:all:read")
    context = await context_for(everything, reader, outbound=bare_request)

    members = await group.member_contexts(context, bare_request())

    assert [member.repository.name for member in members] == ["one", "two"]
    assert all(member.principal is reader for member in members)
    assert all(member.outbound is bare_request for member in members)


async def test_an_offline_member_has_no_context(db, everything, context_for):
    one = await service.get_repository(db, "one")
    await service.update_repository(db, one, online=False)
    await db.commit()
    context = await context_for(everything, None)

    members = await group.member_contexts(context, bare_request())

    assert [member.repository.name for member in members] == ["two"]


async def test_a_group_gives_its_members_once_in_a_request(everything, context_for):
    context = await context_for(everything, None)
    request = bare_request()

    first = await group.member_contexts(context, request)
    again = await group.member_contexts(context, request)

    assert (len(first), again) == (2, [])
```

In `backend/tests/repositories/test_content_maintain.py`, append:

```python
async def test_only_a_hosted_repository_takes_uploads(mirror, context_for):
    context = await context_for(mirror, someone("repository:raw:mirror"))

    with pytest.raises(RuntimeError):
        context.require_write()
    with pytest.raises(RuntimeError):
        await context.maintain(PATH, becomes(b"one"), content_type=XML, limit=1000)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_group.py tests/repositories/test_content_maintain.py -q`
Expected: 4 failures. `module 'megooarti.repositories.group' has no attribute 'member_contexts'`, three times; and `require_write` on the proxy does not raise.

- [ ] **Step 3: Implement**

Replace `backend/src/megooarti/repositories/group.py` with:

```python
"""Group repositories: several repositories behind one URL.

Members are tried in order and the first that has the path answers. Permission is
decided on the group, by the route, before this runs: members are not checked again.
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.formats import Serve
from megooarti.repositories.paths import normalise_path

# What a member may answer to mean "not from me; try the next": it lacks the path,
# its remote is unavailable, or it has no engine in this version.
TRY_NEXT = frozenset({404, 502, 503})
_SEEN = "megooarti.groups_seen"


async def member_contexts(context: RepositoryContext, request: Request) -> list[RepositoryContext]:
    """The online members of a group, in order, each as its own context.

    A group gives its members once in a request; asked again, it gives none. Cycles
    are refused when a group is saved, but two simultaneous saves could create one, and
    this makes that harmless.
    """
    seen = request.scope.setdefault(_SEEN, set())
    if context.repository.id in seen:
        return []
    seen.add(context.repository.id)
    return [
        await build_context(
            context.db, context.settings, member, context.principal, outbound=context.outbound
        )
        for member in await service.members(context.db, context.repository)
        if member.online
    ]


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """Answer a request to a group. `serve` is the dispatcher, used for each member."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A group repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    path = normalise_path(path)
    for member_context in await member_contexts(context, request):
        try:
            return await serve(member_context, request, path)
        except ApiError as error:
            if error.status_code not in TRY_NEXT:
                raise
    raise ApiError(404, "not_found", "No such file.")
```

In `backend/src/megooarti/repositories/content.py`, in `require_write`, add as the first statements of the method body, after the docstring:

```python
        if self.repository.type != "hosted":
            # A programming error, like caching into a repository that is not a proxy.
            raise RuntimeError("only a hosted repository takes uploads")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(repositories): expose the group's walk over its members; uploads only to hosted repositories"
```

---

### Task 4: Maven metadata: bounds on what is parsed, and merging

**Files:**
- Modify: `backend/src/megooarti/repositories/maven/metadata.py`
- Modify: `backend/tests/repositories/maven/test_metadata.py`

**Interfaces:**
- Consumes: `Metadata`, `Plugin`, `SnapshotVersion`, `InvalidMetadata`, `sorted_versions`, `SNAPSHOT`.
- Produces:
  - `metadata.parse` raises `InvalidMetadata` for a document nested more than 16 levels deep or holding more than 100,000 elements.
  - `metadata.merge(documents: Sequence[Metadata]) -> Metadata | None` — several repositories' documents for one path as one document; `None` for no documents. Earlier documents win ties.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/repositories/maven/test_metadata.py`:

```python
def test_a_document_nested_too_deeply_is_refused():
    acceptable = b"<metadata>" + b"<a>" * 15 + b"</a>" * 15 + b"</metadata>"
    too_deep = b"<metadata>" + b"<a>" * 16 + b"</a>" * 16 + b"</metadata>"

    assert metadata.parse(acceptable) == Metadata()
    with pytest.raises(InvalidMetadata, match="nested"):
        metadata.parse(too_deep)


def test_a_document_with_too_many_elements_is_refused():
    def listing(count: int) -> bytes:
        versions = "".join(f"<version>{number}</version>" for number in range(count))
        document = f"<metadata><versioning><versions>{versions}</versions></versioning></metadata>"
        return document.encode()

    assert len(metadata.parse(listing(20_000)).versions) == 20_000
    with pytest.raises(InvalidMetadata, match="too many"):
        metadata.parse(listing(100_000))


def test_merging_nothing_is_nothing():
    assert metadata.merge([]) is None


def test_merged_versions_are_the_union_in_maven_order():
    ours = Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.0", "1.10"),
        latest="1.10",
        release="1.10",
        last_updated="20261008101500",
    )
    theirs = Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.9", "1.0", "2.0-SNAPSHOT"),
        latest="1.0",
        release="1.0",
        last_updated="20250101000000",
    )

    assert metadata.merge([ours, theirs]) == Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=("1.0", "1.9", "1.10", "2.0-SNAPSHOT"),
        latest="2.0-SNAPSHOT",
        release="1.10",
        last_updated="20261008101500",
    )


def test_latest_and_release_are_recomputed_even_for_one_document():
    misleading = Metadata(versions=("2.0", "1.0"), latest="1.0", release="1.0")

    merged = metadata.merge([misleading])

    assert (merged.versions, merged.latest, merged.release) == (("1.0", "2.0"), "2.0", "2.0")


def test_coordinates_come_from_the_first_document_that_has_them():
    merged = metadata.merge(
        [PLUGINS, Metadata(group_id="com.acme", artifact_id="app"), Metadata(group_id="other")]
    )

    assert (merged.group_id, merged.artifact_id) == ("com.acme", "app")


def test_plugins_are_merged_by_prefix_and_the_earlier_document_wins():
    ours = Metadata(plugins=(Plugin("Ours", "acme", "acme-maven-plugin"),))
    theirs = Metadata(
        plugins=(Plugin("Theirs", "acme", "their-plugin"), Plugin("Other", "other", "other-plugin"))
    )

    assert metadata.merge([ours, theirs]).plugins == (
        Plugin("Ours", "acme", "acme-maven-plugin"),
        Plugin("Other", "other", "other-plugin"),
    )


def test_the_snapshot_is_the_one_built_last():
    older = Metadata(snapshot_timestamp="20261008.101500", snapshot_build=9)
    newer = Metadata(snapshot_timestamp="20261009.080000", snapshot_build=2)
    none = Metadata()

    merged = metadata.merge([older, none, newer])

    assert (merged.snapshot_timestamp, merged.snapshot_build) == ("20261009.080000", 2)


def test_the_higher_build_decides_between_equal_timestamps():
    lower = Metadata(snapshot_timestamp="20261008.101500", snapshot_build=2)
    higher = Metadata(snapshot_timestamp="20261008.101500", snapshot_build=3)

    assert metadata.merge([lower, higher]).snapshot_build == 3
    assert metadata.merge([higher, lower]).snapshot_build == 3


def test_each_snapshot_file_comes_from_the_document_that_updated_it_last():
    ours = Metadata(
        snapshot_versions=(
            SnapshotVersion("", "jar", "1.0-20261008.101500-1", "20261008101500"),
            SnapshotVersion("", "pom", "1.0-20261008.101500-1", "20261008101500"),
        )
    )
    theirs = Metadata(
        snapshot_versions=(
            SnapshotVersion("", "jar", "1.0-20261009.080000-2", "20261009080000"),
            SnapshotVersion("", "pom", "1.0-20261008.101500-7", "20261008101500"),
            SnapshotVersion("sources", "jar", "1.0-20261009.080000-2", "20261009080000"),
        )
    )

    assert metadata.merge([ours, theirs]).snapshot_versions == (
        SnapshotVersion("", "jar", "1.0-20261009.080000-2", "20261009080000"),
        SnapshotVersion("", "pom", "1.0-20261008.101500-1", "20261008101500"),
        SnapshotVersion("sources", "jar", "1.0-20261009.080000-2", "20261009080000"),
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_metadata.py -q`
Expected: 10 failures. The two bounds tests do not raise; the others fail with `module 'megooarti.repositories.maven.metadata' has no attribute 'merge'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/maven/metadata.py`, change the import `from collections.abc import Iterable, Mapping` to:

```python
from collections.abc import Iterable, Mapping, Sequence
```

Add after the `_DECLARATION` line:

```python
# Real metadata nests five levels and lists a few thousand versions at most. These
# bound what a document can cost to read, whoever sent it.
_MAX_DEPTH = 16
_MAX_ELEMENTS = 100_000
```

Add after `merge_plugins`:

```python
def merge(documents: Sequence[Metadata]) -> Metadata | None:
    """Several repositories' documents for one path, as one. None if there are none.

    Versions are the union, and `latest` and `release` are worked out again from it:
    a member's own answer describes only that member. Where two documents disagree
    about the same thing, the earlier one wins.
    """
    if not documents:
        return None
    versions = sorted_versions(version for document in documents for version in document.versions)
    releases = [version for version in versions if not version.endswith(SNAPSHOT)]

    def built(document: Metadata) -> tuple[str, int]:
        build = -1 if document.snapshot_build is None else document.snapshot_build
        return document.snapshot_timestamp, build

    newest = max(documents, key=built)

    files: dict[tuple[str, str], SnapshotVersion] = {}
    plugins: dict[str, Plugin] = {}
    for document in documents:
        for entry in document.snapshot_versions:
            key = (entry.classifier, entry.extension)
            if key not in files or entry.updated > files[key].updated:
                files[key] = entry
        for plugin in document.plugins:
            plugins.setdefault(plugin.prefix, plugin)

    def first(values: Iterable[str]) -> str:
        return next((value for value in values if value), "")

    return Metadata(
        group_id=first(document.group_id for document in documents),
        artifact_id=first(document.artifact_id for document in documents),
        version=first(document.version for document in documents),
        versions=tuple(versions),
        latest=versions[-1] if versions else "",
        release=releases[-1] if releases else "",
        snapshot_timestamp=newest.snapshot_timestamp,
        snapshot_build=newest.snapshot_build,
        snapshot_versions=tuple(files[key] for key in sorted(files)),
        last_updated=max(document.last_updated for document in documents),
        plugins=tuple(
            sorted(plugins.values(), key=lambda plugin: (plugin.prefix, plugin.artifact_id))
        ),
    )
```

Replace `_tree` with:

```python
def _tree(data: bytes) -> ET.Element:
    builder = ET.TreeBuilder()
    depth = 0
    elements = 0

    def start(tag: str, attributes: dict[str, str]) -> None:
        nonlocal depth, elements
        depth += 1
        elements += 1
        if depth > _MAX_DEPTH:
            raise InvalidMetadata("it is nested too deeply")
        if elements > _MAX_ELEMENTS:
            raise InvalidMetadata("it has too many elements")
        builder.start(tag, attributes)

    def end(tag: str) -> None:
        nonlocal depth
        depth -= 1
        builder.end(tag)

    parser = expat.ParserCreate()
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise InvalidMetadata(f"it is not well-formed XML (line {error.lineno})") from None
    except (ValueError, LookupError):
        # It declares an encoding expat cannot read: a multi-byte one, or one unknown.
        raise InvalidMetadata("it is in an encoding that cannot be read") from None
    return builder.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/maven -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/maven/metadata.py backend/tests/repositories/maven/test_metadata.py
git commit -m "feat(maven): bound what metadata parsing costs, and merge documents"
```

---

### Task 5: Maven proxy repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Modify: `backend/tests/repositories/maven/conftest.py`
- Modify: `backend/tests/repositories/maven/test_format.py`
- Test: `backend/tests/repositories/maven/test_proxy.py`

**Interfaces:**
- Consumes: Task 1's `handle_proxy` hook and `content_type` on fetched files; Task 2's `proxy.ensure_cached`; `context.stat`, `context.respond_with`.
- Produces:
  - `MavenFormat.types` is all three types. A Maven group has no settings: `validate_config("group", {}) == {}`, and anything else is `422`. (Until Task 6 a Maven group uses the generic group engine.)
  - `MavenFormat.is_metadata(path) -> bool` — true for `maven-metadata.xml`, the catalog, and old-style snapshot files.
  - `MavenFormat.handle_proxy` — policies first, checksums from the cached file, everything else to the generic engine.
  - In `maven/format.py`: `_excluded(settings, parsed) -> ApiError | None` (replaces `_check_policies`), `_checksum_response(context, request, path, digest, modified) -> Response`.
  - Test helpers: `create(db, name, *, type="hosted", hosted=None, proxy=None, group=None, **format_config)`, the constant `REMOTE = "http://remote.test/maven2"`, and the fixture `central` (a release, strict proxy of `REMOTE`).

- [ ] **Step 1: Extend the test helpers**

Replace `backend/tests/repositories/maven/conftest.py` with:

```python
import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

REMOTE = "http://remote.test/maven2"


async def create(
    db,
    name: str,
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
    **format_config,
) -> Repository:
    """A Maven repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="maven",
        type=type,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        group=group,
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
async def central(db) -> Repository:
    """A proxy of the fake remote, taking releases in the strict layout."""
    return await create(db, "central", type="proxy", proxy={"remote_url": REMOTE})


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

- [ ] **Step 2: Write the failing tests**

In `backend/tests/repositories/maven/test_format.py`, replace `test_maven_is_registered_as_a_hosted_format` with:

```python
def test_maven_is_registered_for_every_repository_type():
    assert isinstance(get_format("maven"), MavenFormat)
    assert get_format("maven").types == {"hosted", "proxy", "group"}


def test_a_maven_group_has_no_settings():
    assert MAVEN.validate_config("group", {}) == {}
    with pytest.raises(ApiError) as caught:
        MAVEN.validate_config("group", {"version_policy": "mixed"})
    assert (caught.value.status_code, caught.value.code) == (422, "validation_error")


@pytest.mark.parametrize(
    ("path", "changes"),
    [
        ("com/acme/app/maven-metadata.xml", True),
        ("com/acme/app/1.0-SNAPSHOT/maven-metadata.xml", True),
        ("archetype-catalog.xml", True),
        ("com/acme/app/1.0-SNAPSHOT/app-1.0-SNAPSHOT.jar", True),
        ("com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-1.jar", False),
        ("com/acme/app/1.0/app-1.0.jar", False),
        ("notes/readme.txt", False),
    ],
)
def test_what_changes_at_the_remote_is_checked_on_the_metadata_age(path, changes):
    assert MAVEN.is_metadata(path) is changes
```

and replace `test_proxy_and_group_maven_repositories_are_not_offered_yet` (with its `parametrize` line) with:

```python
async def test_maven_proxy_and_group_repositories_are_created_through_the_api(admin_client):
    proxy = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "central",
            "format": "maven",
            "type": "proxy",
            "proxy": {"remote_url": "https://repo.example/maven2"},
        },
    )
    everything = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "public",
            "format": "maven",
            "type": "group",
            "group": {"members": ["central"]},
        },
    )
    with_settings = await admin_client.post(
        "/api/v1/repositories",
        json={
            "name": "other",
            "format": "maven",
            "type": "group",
            "format_config": {"layout_policy": "strict"},
        },
    )

    assert proxy.status_code == 201, proxy.text
    assert proxy.json()["format_config"] == {
        "version_policy": "release",
        "layout_policy": "strict",
    }
    assert everything.status_code == 201, everything.text
    assert everything.json()["format_config"] == {}
    assert (with_settings.status_code, error_code(with_settings)) == (422, "validation_error")
```

`backend/tests/repositories/maven/test_proxy.py`:

```python
import hashlib

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.models import Asset, Component
from tests.accounts import error_code
from tests.repositories.maven.conftest import REMOTE, create

JAR_PATH = "com/acme/app/1.0/app-1.0.jar"
JAR = f"/repository/central/{JAR_PATH}"
BYTES = b"PK\x03\x04 a jar the remote holds"
LISTING_PATH = "com/acme/app/maven-metadata.xml"
LISTING = f"/repository/central/{LISTING_PATH}"
# Not how MegooArti would write it: a proxy passes metadata on untouched.
REMOTE_LISTING = (
    b"<metadata>\n\t<groupId>com.acme</groupId><artifactId>app</artifactId>\n"
    b"<versioning><release>1.0</release><versions><version>1.0</version></versions>"
    b"</versioning></metadata>"
)
SNAPSHOT_DIR = "/repository/central/com/acme/app/1.0-SNAPSHOT"


def asked(remote, method: str = "GET") -> list[str]:
    return [path.removeprefix("/maven2/") for path in remote.paths(method)]


@pytest.fixture
def remote(fake_remote, central):
    fake_remote.files[f"maven2/{JAR_PATH}"] = BYTES
    fake_remote.files[f"maven2/{LISTING_PATH}"] = REMOTE_LISTING
    return fake_remote


async def test_an_artifact_is_fetched_cached_and_given_its_component(client, root, remote, db):
    first = await client.get(JAR, headers=root)
    second = await client.get(JAR, headers=root)

    assert (first.status_code, first.content) == (200, BYTES)
    assert second.content == BYTES
    assert first.headers["Content-Type"] == "application/java-archive"
    assert asked(remote) == [JAR_PATH]
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("com.acme", "app", "1.0")


@pytest.mark.parametrize("algorithm", ["md5", "sha1", "sha256", "sha512"])
async def test_a_checksum_comes_from_the_cached_file(client, root, remote, algorithm):
    await client.get(JAR, headers=root)

    response = await client.get(f"{JAR}.{algorithm}", headers=root)

    assert (response.status_code, response.text) == (200, hashlib.new(algorithm, BYTES).hexdigest())
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert asked(remote) == [JAR_PATH]


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_a_checksum_asked_for_first_fetches_its_file_once(client, root, remote, db, method):
    checksum = await client.request(method, f"{JAR}.sha1", headers=root)
    file = await client.get(JAR, headers=root)

    assert checksum.status_code == 200
    assert checksum.headers["Content-Length"] == "40"
    assert file.content == BYTES
    assert asked(remote) == [JAR_PATH]
    assert asked(remote, "HEAD") == []
    assert list(await db.scalars(select(Asset.path))) == [JAR_PATH]


async def test_a_checksum_of_what_the_remote_lacks_is_not_found(client, root, remote):
    url = "/repository/central/com/acme/app/9.9/app-9.9.jar.sha1"

    first = await client.get(url, headers=root)
    again = await client.get(url, headers=root)

    assert (first.status_code, error_code(first)) == (404, "not_found")
    assert again.status_code == 404
    assert asked(remote) == ["com/acme/app/9.9/app-9.9.jar"]  # remembered, not asked twice


async def test_a_checksum_cannot_be_made_while_the_remote_is_down(client, root, remote):
    remote.down = True

    response = await client.get(f"{JAR}.sha1", headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")


async def test_metadata_is_served_as_the_remote_wrote_it(client, root, remote):
    listing = await client.get(LISTING, headers=root)
    sha1 = await client.get(f"{LISTING}.sha1", headers=root)

    assert (listing.status_code, listing.content) == (200, REMOTE_LISTING)
    assert listing.headers["Content-Type"] == "application/xml"
    assert sha1.text == hashlib.sha1(REMOTE_LISTING).hexdigest()
    assert asked(remote) == [LISTING_PATH]


async def test_metadata_is_asked_about_again_and_releases_are_not(client, root, db, fake_remote):
    ages = {"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": -1}
    await create(db, "eager", type="proxy", proxy=ages)
    fake_remote.files[f"maven2/{JAR_PATH}"] = BYTES
    fake_remote.files[f"maven2/{LISTING_PATH}"] = REMOTE_LISTING

    for _ in range(2):
        await client.get(f"/repository/eager/{JAR_PATH}", headers=root)
        await client.get(f"/repository/eager/{LISTING_PATH}", headers=root)

    assert asked(fake_remote) == [JAR_PATH, LISTING_PATH, LISTING_PATH]


@pytest.mark.parametrize(
    "name", ["app-1.0-SNAPSHOT.jar", "app-1.0-SNAPSHOT.jar.sha1", "maven-metadata.xml"]
)
async def test_a_release_proxy_does_not_ask_for_snapshots(client, root, remote, name):
    remote.files[f"maven2/com/acme/app/1.0-SNAPSHOT/{name}"] = b"at the remote"

    fetched = await client.get(f"{SNAPSHOT_DIR}/{name}", headers=root)
    headed = await client.head(f"{SNAPSHOT_DIR}/{name}", headers=root)

    assert (fetched.status_code, error_code(fetched)) == (404, "not_found")
    assert headed.status_code == 404
    assert asked(remote) == asked(remote, "HEAD") == []


async def test_a_snapshot_proxy_fetches_snapshots(client, root, db, fake_remote):
    await create(
        db, "nightly", type="proxy", proxy={"remote_url": REMOTE}, version_policy="snapshot"
    )
    name = "com/acme/app/1.0-SNAPSHOT/app-1.0-20261008.101500-1.jar"
    fake_remote.files[f"maven2/{name}"] = BYTES

    snapshot = await client.get(f"/repository/nightly/{name}", headers=root)
    release = await client.get(f"/repository/nightly/{JAR_PATH}", headers=root)

    assert snapshot.content == BYTES
    assert release.status_code == 404
    assert asked(fake_remote) == [name]


async def test_a_strict_proxy_does_not_ask_for_paths_outside_the_layout(client, root, remote):
    remote.files["maven2/notes/readme.txt"] = b"hello"

    response = await client.get("/repository/central/notes/readme.txt", headers=root)
    checksum = await client.get("/repository/central/notes/readme.txt.md5", headers=root)

    assert (response.status_code, checksum.status_code) == (404, 404)
    assert asked(remote) == []


async def test_what_was_cached_while_permissive_is_still_served_once_strict(
    client, root, db, fake_remote
):
    loose = await create(
        db, "loose", type="proxy", proxy={"remote_url": REMOTE}, layout_policy="permissive"
    )
    fake_remote.files["maven2/notes/readme.txt"] = b"hello"
    fake_remote.files["maven2/notes/other.txt"] = b"never fetched"
    url = "/repository/loose/notes/readme.txt"
    assert (await client.get(url, headers=root)).content == b"hello"
    await service.update_repository(
        db,
        loose,
        online=True,
        proxy={"remote_url": REMOTE},
        format_config={"layout_policy": "strict"},
    )
    await db.commit()

    cached = await client.get(url, headers=root)
    checksum = await client.get(f"{url}.md5", headers=root)
    other = await client.get("/repository/loose/notes/other.txt", headers=root)

    assert cached.content == b"hello"
    assert checksum.text == hashlib.md5(b"hello").hexdigest()
    assert other.status_code == 404
    assert asked(fake_remote) == ["notes/readme.txt"]


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
@pytest.mark.parametrize("path", [JAR, f"{JAR}.sha1", LISTING])
async def test_a_maven_proxy_cannot_be_written_to(client, root, remote, method, path):
    response = await client.request(method, path, content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
    assert asked(remote) == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_format.py tests/repositories/maven/test_proxy.py -q`
Expected: every test in `test_proxy.py` errors while creating its repository (`proxy repositories are not available for this format`); in `test_format.py` the four new tests fail.

- [ ] **Step 4: Implement**

Replace `backend/src/megooarti/repositories/maven/format.py` with:

```python
"""The Maven format: the Maven 2 layout, with generated checksums and metadata.

This is the only Maven module that touches the repository context. What it decides
about a path comes from the pure functions beside it.
"""

import hashlib
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.maven import checksums, metadata, paths
from megooarti.repositories.paths import normalise_path

log = structlog.get_logger(__name__)

_SETTINGS = ("version_policy", "layout_policy")
# The most that is read into memory: of an upload, and of a stored or cached document.
METADATA_LIMIT = 1024 * 1024
STORED_LIMIT = 4 * 1024 * 1024
_XML = "application/xml"


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": f"format_config.{field}", "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _choice(config: dict[str, Any], field: str, choices: tuple[str, ...], default: str) -> str:
    value = config.get(field, default)
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field, f"Must be one of: {', '.join(choices)}.")
    return value


def _excluded(settings: dict[str, Any], parsed: paths.MavenPath) -> ApiError | None:
    """Why this repository does not take such a path: the error an upload gets, or None.

    It governs what is added, not what is served. What is already stored or cached
    stays readable, so a repository can be made strict without stranding files.
    """
    if parsed.kind == "other" and settings["layout_policy"] == "strict":
        return ApiError(
            400, "invalid_path", "The path is not valid: it is not in the Maven repository layout."
        )
    if not paths.allowed_by(settings["version_policy"], parsed):
        accepted = settings["version_policy"]
        return ApiError(
            400, "version_policy_violation", f"This repository takes {accepted} versions only."
        )
    return None


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


def _checksum_response(
    context: RepositoryContext, request: Request, path: str, digest: str, modified: datetime
) -> Response:
    """A checksum file's content: the digest in lower-case hex, and nothing else."""
    return context.respond_with(
        digest.encode(),
        request,
        filename=path.rpartition("/")[2],
        content_type="text/plain",
        last_modified=modified,
    )


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
            "Metadata is generated from the files stored. It can be read or uploaded, not deleted.",
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


async def _checksum(
    context: RepositoryContext,
    request: Request,
    path: str,
    target: str,
    parsed: paths.MavenPath,
    algorithm: str,
) -> Response:
    """Answer for a checksum path on a hosted repository. Checksums are never stored."""
    if request.method in ("GET", "HEAD"):
        found = await _digest(context, target, parsed, algorithm)
        if found is None:
            raise _not_found()
        return _checksum_response(context, request, path, *found)
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "A checksum is computed from its file. It can be read or uploaded, not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=checksums.LIMIT)
    if parsed.is_metadata:
        # It cannot be checked: the client's document is not the one served.
        return Response(status_code=201)
    found = await _digest(context, target, parsed, algorithm)
    if found is None:
        raise ApiError(404, "not_found", "There is no file here for this checksum to belong to.")
    declared = None if body is None else checksums.read_uploaded(body, algorithm)
    if declared != found[0]:
        # Maven only warns when a checksum upload fails, so this log line is where a
        # corrupted deploy becomes visible.
        log.warning(
            "checksum_mismatch",
            repository=context.repository.name,
            path=target,
            algorithm=algorithm,
            by=context.principal.user.username,
        )
        # The file stays. Removing it would let anyone who may add delete files by
        # sending a wrong checksum.
        raise ApiError(
            400, "checksum_mismatch", f"The {algorithm} checksum does not match the stored file."
        )
    return Response(status_code=201)


class MavenFormat(Format):
    name = "maven"

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if repository_type == "group":
            # A group holds nothing of its own, so it has no policy of its own.
            if config:
                raise _invalid(sorted(config)[0], "A Maven group has no settings.")
            return {}
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

    def is_metadata(self, path: str) -> bool:
        """What changes at a remote: metadata, the catalog, and old-style snapshot files.

        Release files and timestamped snapshot files never change once published.
        """
        parsed = paths.classify(path)
        if parsed.is_metadata or parsed.kind == "catalog":
            return True
        return parsed.kind == "artifact" and parsed.is_snapshot and parsed.build is None

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        # A checksum path is treated as the path it belongs to.
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if request.method == "PUT":
            refusal = _excluded(context.repository.config["format_config"], parsed)
            if refusal is not None:
                raise refusal
        if algorithm is not None:
            return await _checksum(context, request, path, target, parsed, algorithm)
        if parsed.is_metadata:
            return await _metadata(context, request, path, parsed)
        return await super().handle_hosted(context, request, path)

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        if request.method not in ("GET", "HEAD"):
            return await super().handle_proxy(context, request, path)  # refuses it
        path = normalise_path(path)
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        settings = context.repository.config["format_config"]
        if _excluded(settings, parsed) is not None and await context.stat(target) is None:
            # Not asked of the remote: this repository would not keep the answer.
            raise _not_found()
        if algorithm is None:
            # Files, and metadata exactly as the remote wrote it: a proxy does not hold
            # every version, so it cannot write the list itself.
            return await super().handle_proxy(context, request, path)
        # The remote's own checksum file is never requested. The file is, if it is not
        # cached yet, and the checksum is of the bytes that will be served.
        await proxy.ensure_cached(context, target)
        stored = await context.stat(target)
        if stored is None:
            raise _not_found()
        return _checksum_response(
            context, request, path, getattr(stored, algorithm), stored.modified
        )


register(MavenFormat())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/maven/format.py backend/tests/repositories/maven
git commit -m "feat(maven): proxy repositories that answer checksums from what they cache"
```

---

### Task 6: Maven group repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/maven/format.py`
- Test: `backend/tests/repositories/maven/test_group.py`

**Interfaces:**
- Consumes: Task 1's `handle_group` hook and `Serve`; Task 2's `proxy.ensure_cached`; Task 3's `group.member_contexts` and `group.TRY_NEXT`; Task 4's `metadata.merge`; Task 5's `_excluded` and `_checksum_response`.
- Produces, in `maven/format.py`:
  - `await built(context, path, parsed) -> tuple[Metadata, datetime] | None` — a hosted repository's metadata as a model. `document` is now `built` plus serialising.
  - `MavenFormat.handle_group` — metadata and its checksums merged from the members; everything else to the generic engine.
  - Building, merging, parsing and serialising metadata run through `asyncio.to_thread` (P5). This changes no behaviour and is covered by the existing tests.
  - The log event `member_metadata_unusable` with `repository`, `path` and `reason`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/maven/test_group.py`:

```python
import hashlib

import pytest
import structlog

from megooarti.repositories import service
from megooarti.repositories.maven import metadata
from megooarti.repositories.maven.metadata import Metadata, Plugin
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.maven.conftest import create

APP = "com/acme/app"
LISTING = f"/repository/public/{APP}/maven-metadata.xml"
REMOTE_LISTING = f"maven2/{APP}/maven-metadata.xml"
SNAPSHOT_DIR = f"{APP}/1.0-SNAPSHOT"


@pytest.fixture
async def public(db, releases, snapshots, central):
    """The hosted `releases` and `snapshots` and the proxy `central`, in that order."""
    members = {"members": ["releases", "snapshots", "central"]}
    return await create(db, "public", type="group", group=members)


def remote_listing(*versions: str) -> bytes:
    """What a remote holds. Its own `latest` and `release` are deliberately wrong."""
    held = Metadata(
        group_id="com.acme",
        artifact_id="app",
        versions=versions,
        latest=versions[0],
        release=versions[0],
        last_updated="20200101000000",
    )
    return metadata.serialise(held)


async def put(client, root, path: str, content: bytes = b"x") -> None:
    response = await client.put(f"/repository/{path}", content=content, headers=root)
    assert response.status_code in (201, 204), response.text


async def release(client, root, version: str) -> None:
    await put(client, root, f"releases/{APP}/{version}/app-{version}.jar")


async def listing(client, headers, url: str = LISTING) -> Metadata:
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return metadata.parse(response.content)


async def test_metadata_is_merged_from_every_member(client, root, public, fake_remote):
    await release(client, root, "1.0")
    await release(client, root, "1.10")
    await put(client, root, f"snapshots/{APP}/2.1-SNAPSHOT/app-2.1-20261008.101500-1.jar")
    fake_remote.files[REMOTE_LISTING] = remote_listing("0.9", "2.0", "1.0", "1.9")

    document = await listing(client, root)

    assert (document.group_id, document.artifact_id) == ("com.acme", "app")
    assert document.versions == ("0.9", "1.0", "1.9", "1.10", "2.0", "2.1-SNAPSHOT")
    assert (document.latest, document.release) == ("2.1-SNAPSHOT", "2.0")
    assert document.last_updated > "20200101000000"


async def test_group_metadata_is_answered_like_any_file(client, root, public, fake_remote):
    await release(client, root, "1.0")
    first = await client.get(LISTING, headers=root)
    etag = first.headers["ETag"]

    headed = await client.head(LISTING, headers=root)
    unchanged = await client.get(LISTING, headers={**root, "If-None-Match": etag})

    assert first.headers["Content-Type"] == "application/xml"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["Content-Disposition"].startswith(
        'attachment; filename="maven-metadata.xml"'
    )
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Content-Length"] == str(len(first.content))
    assert (unchanged.status_code, unchanged.content) == (304, b"")


async def test_the_checksum_of_group_metadata_is_of_the_merged_document(
    client, root, public, fake_remote
):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")

    document = await client.get(LISTING, headers=root)
    sha1 = await client.get(f"{LISTING}.sha1", headers=root)
    md5 = await client.head(f"{LISTING}.md5", headers=root)

    assert metadata.parse(document.content).versions == ("1.0", "2.0")
    assert sha1.text == hashlib.sha1(document.content).hexdigest()
    assert sha1.headers["Content-Type"] == "text/plain"
    assert (md5.status_code, md5.headers["Content-Length"]) == (200, "32")
    assert fake_remote.paths() == [f"/{REMOTE_LISTING}"]  # never the remote's checksum file


async def test_metadata_no_member_has_is_not_found(client, root, public, fake_remote):
    document = await client.get(LISTING, headers=root)
    checksum = await client.get(f"{LISTING}.sha1", headers=root)

    assert (document.status_code, error_code(document)) == (404, "not_found")
    assert checksum.status_code == 404


async def test_a_member_whose_remote_is_down_is_left_out(client, root, public, fake_remote):
    await release(client, root, "1.0")
    fake_remote.down = True

    document = await listing(client, root)

    assert document.versions == ("1.0",)


async def test_a_group_whose_only_source_is_down_has_nothing(client, root, public, fake_remote):
    fake_remote.down = True

    response = await client.get(LISTING, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


@pytest.mark.parametrize(
    "held",
    [
        b"this is not xml",
        b'<!DOCTYPE metadata [<!ENTITY a "b">]><metadata><groupId>&a;</groupId></metadata>',
        b"<metadata>" + b"<a>" * 500 + b"</a>" * 500 + b"</metadata>",
        b"<metadata>" + b" " * (4 * 1024 * 1024) + b"</metadata>",
    ],
    ids=["not-xml", "doctype", "deeply-nested", "over-4-mib"],
)
async def test_a_member_document_that_cannot_be_used_is_left_out_and_logged(
    client, root, public, fake_remote, held
):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = held

    with structlog.testing.capture_logs() as logs:
        document = await listing(client, root)

    assert document.versions == ("1.0",)
    unusable = [entry for entry in logs if entry["event"] == "member_metadata_unusable"]
    assert [(entry["repository"], entry["path"]) for entry in unusable] == [
        ("central", f"{APP}/maven-metadata.xml")
    ]


async def test_an_offline_member_is_left_out(client, root, public, fake_remote, db):
    await release(client, root, "1.0")
    await put(client, root, f"snapshots/{APP}/2.1-SNAPSHOT/app-2.1-SNAPSHOT.jar")
    snapshots = await service.get_repository(db, "snapshots")
    await service.update_repository(
        db, snapshots, online=False, format_config={"version_policy": "snapshot"}
    )
    await db.commit()

    document = await listing(client, root)

    assert document.versions == ("1.0",)


async def test_snapshot_metadata_comes_through_a_group(client, root, public, fake_remote):
    for name in ("app-1.0-20261008.101500-1.jar", "app-1.0-20261008.111500-2.jar"):
        await put(client, root, f"snapshots/{SNAPSHOT_DIR}/{name}")

    document = await listing(client, root, f"/repository/public/{SNAPSHOT_DIR}/maven-metadata.xml")

    assert document.version == "1.0-SNAPSHOT"
    assert (document.snapshot_timestamp, document.snapshot_build) == ("20261008.111500", 2)
    assert [entry.value for entry in document.snapshot_versions] == ["1.0-20261008.111500-2"]
    assert fake_remote.paths() == []  # `central` takes releases only, so it is not asked


async def test_files_and_their_checksums_come_from_the_member_that_has_them(
    client, root, public, fake_remote
):
    ours, theirs = b"PK deployed here", b"PK held by the remote"
    await put(client, root, f"releases/{APP}/1.0/app-1.0.jar", ours)
    fake_remote.files["maven2/com/acme/lib/3.0/lib-3.0.jar"] = theirs
    hosted = f"/repository/public/{APP}/1.0/app-1.0.jar"
    proxied = "/repository/public/com/acme/lib/3.0/lib-3.0.jar"

    hosted_sha1 = await client.get(f"{hosted}.sha1", headers=root)
    proxied_sha1 = await client.get(f"{proxied}.sha1", headers=root)
    proxied_file = await client.get(proxied, headers=root)

    assert (await client.get(hosted, headers=root)).content == ours
    assert hosted_sha1.text == hashlib.sha1(ours).hexdigest()
    assert proxied_sha1.text == hashlib.sha1(theirs).hexdigest()
    assert proxied_file.content == theirs
    assert fake_remote.paths() == ["/maven2/com/acme/lib/3.0/lib-3.0.jar"]


async def test_plugins_are_merged_and_the_earlier_member_wins_a_prefix(
    client, root, public, fake_remote
):
    ours = Plugin("Ours", "acme", "acme-maven-plugin")
    await put(client, root, "releases/com/acme/acme-maven-plugin/1.0/acme-maven-plugin-1.0.jar")
    await put(
        client,
        root,
        "releases/com/acme/maven-metadata.xml",
        metadata.serialise(Metadata(plugins=(ours,))),
    )
    theirs = (Plugin("Theirs", "acme", "their-plugin"), Plugin("Other", "other", "other-plugin"))
    fake_remote.files["maven2/com/acme/maven-metadata.xml"] = metadata.serialise(
        Metadata(plugins=theirs)
    )

    document = await listing(client, root, "/repository/public/com/acme/maven-metadata.xml")

    assert document.plugins == (ours, Plugin("Other", "other", "other-plugin"))


async def test_a_group_inside_a_group_contributes_its_merged_document(
    client, root, public, fake_remote, db
):
    await create(db, "extra")
    await create(db, "outer", type="group", group={"members": ["extra", "public"]})
    await release(client, root, "1.0")
    await put(client, root, f"extra/{APP}/3.0/app-3.0.jar")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")

    document = await listing(client, root, f"/repository/outer/{APP}/maven-metadata.xml")

    assert document.versions == ("1.0", "2.0", "3.0")


async def test_reading_through_the_group_needs_read_on_the_group_only(
    client, root, public, fake_remote, make_user, db
):
    await release(client, root, "1.0")
    fake_remote.files[REMOTE_LISTING] = remote_listing("2.0")
    members = ["repository:maven:releases:read", "repository:maven:central:read"]
    await roles.create_role(db, "group-readers", "", ["repository:maven:public:read"], [])
    await roles.create_role(db, "member-readers", "", members, [])
    await db.commit()
    await make_user("gina", roles=["group-readers"])
    await make_user("mel", roles=["member-readers"])

    by_group_reader = await listing(client, basic("gina", PASSWORD))
    by_member_reader = await client.get(LISTING, headers=basic("mel", PASSWORD))
    by_nobody = await client.get(LISTING)

    assert by_group_reader.versions == ("1.0", "2.0")
    assert (by_member_reader.status_code, error_code(by_member_reader)) == (403, "forbidden")
    assert by_nobody.status_code == 401


@pytest.mark.parametrize("method", ["PUT", "POST", "DELETE"])
@pytest.mark.parametrize("suffix", ["", ".sha1"])
async def test_group_metadata_cannot_be_written(client, root, public, method, suffix):
    response = await client.request(method, f"{LISTING}{suffix}", content=b"mine", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/maven/test_group.py -q`
Expected: most fail. Until now a Maven group uses the generic engine, so metadata comes from the first member that has it instead of being merged, and its checksum is that member's.

- [ ] **Step 3: Implement**

Replace `backend/src/megooarti/repositories/maven/format.py` with:

```python
"""The Maven format: the Maven 2 layout, with generated checksums and metadata.

This is the only Maven module that touches the repository context. What it decides
about a path comes from the pure functions beside it.

Building, merging, reading and writing metadata run in a worker thread: a long list of
versions takes real time to sort, and must not hold up every other request.
"""

import asyncio
import hashlib
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import group, proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
from megooarti.repositories.maven import checksums, metadata, paths
from megooarti.repositories.paths import normalise_path

log = structlog.get_logger(__name__)

_SETTINGS = ("version_policy", "layout_policy")
# The most that is read into memory: of an upload, and of a stored or cached document.
METADATA_LIMIT = 1024 * 1024
STORED_LIMIT = 4 * 1024 * 1024
_XML = "application/xml"


def _invalid(field: str, message: str) -> ApiError:
    details = [{"field": f"format_config.{field}", "message": message}]
    return ApiError(422, "validation_error", "The request is not valid.", details)


def _choice(config: dict[str, Any], field: str, choices: tuple[str, ...], default: str) -> str:
    value = config.get(field, default)
    if not isinstance(value, str) or value not in choices:
        raise _invalid(field, f"Must be one of: {', '.join(choices)}.")
    return value


def _excluded(settings: dict[str, Any], parsed: paths.MavenPath) -> ApiError | None:
    """Why this repository does not take such a path: the error an upload gets, or None.

    It governs what is added, not what is served. What is already stored or cached
    stays readable, so a repository can be made strict without stranding files.
    """
    if parsed.kind == "other" and settings["layout_policy"] == "strict":
        return ApiError(
            400, "invalid_path", "The path is not valid: it is not in the Maven repository layout."
        )
    if not paths.allowed_by(settings["version_policy"], parsed):
        accepted = settings["version_policy"]
        return ApiError(
            400, "version_policy_violation", f"This repository takes {accepted} versions only."
        )
    return None


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")


def _checksum_response(
    context: RepositoryContext, request: Request, path: str, digest: str, modified: datetime
) -> Response:
    """A checksum file's content: the digest in lower-case hex, and nothing else."""
    return context.respond_with(
        digest.encode(),
        request,
        filename=path.rpartition("/")[2],
        content_type="text/plain",
        last_modified=modified,
    )


def _metadata_response(
    context: RepositoryContext, request: Request, data: bytes, modified: datetime
) -> Response:
    return context.respond_with(
        data,
        request,
        filename=paths.METADATA_FILE,
        content_type=_XML,
        last_modified=modified,
    )


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
        data = await context.read(path, limit=STORED_LIMIT)
        record = await asyncio.to_thread(metadata.parse, data or b"")
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


async def built(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """A hosted repository's metadata for `path`, and when it last changed.

    Built from the files the repository holds, so it is right after a delete and after
    two deploys at once. None when there is nothing to list.
    """
    if parsed.kind == "snapshot_metadata":
        entries = await context.files(parsed.group_id, parsed.artifact_id, parsed.version)
        files = [(paths.classify(entry.path), entry.modified) for entry in entries]
        made = await asyncio.to_thread(
            metadata.for_snapshot, parsed.group_id, parsed.artifact_id, parsed.version, files
        )
        changes = [entry.modified for entry in entries]
    else:
        versions = {}
        if parsed.artifact_id:
            versions = await context.versions(parsed.group_id, parsed.artifact_id)
        plugins, plugins_changed = await _plugins(context, path, parsed)
        made = await asyncio.to_thread(
            metadata.for_artifact, parsed.group_id, parsed.artifact_id, versions, plugins
        )
        changes = [*versions.values(), *([plugins_changed] if plugins_changed else [])]
    if made is None:
        return None
    return made, max(changes)


async def document(
    context: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[bytes, datetime] | None:
    """The metadata a GET of `path` on a hosted repository returns now, as bytes."""
    found = await built(context, path, parsed)
    if found is None:
        return None
    made, modified = found
    return await asyncio.to_thread(metadata.serialise, made), modified


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
                stored = (await asyncio.to_thread(metadata.parse, current)).plugins
        plugins = metadata.merge_plugins(stored, uploaded)
        present = await context.names(group_id, [plugin.artifact_id for plugin in plugins])
        kept = tuple(plugin for plugin in plugins if plugin.artifact_id in present)
        return metadata.serialise(metadata.Metadata(plugins=kept)) if kept else None

    await context.maintain(path, merged, content_type=_XML, limit=STORED_LIMIT)


async def _metadata(
    context: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> Response:
    """Answer for a maven-metadata.xml path on a hosted repository.

    The document is generated, never stored.
    """
    if request.method in ("GET", "HEAD"):
        found = await document(context, path, parsed)
        if found is None:
            raise _not_found()
        return _metadata_response(context, request, *found)
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "Metadata is generated from the files stored. It can be read or uploaded, not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=METADATA_LIMIT)
    if body is None:
        raise ApiError(400, "invalid_metadata", "The metadata is larger than 1 MiB.")
    if parsed.kind == "metadata":
        try:
            uploaded = await asyncio.to_thread(metadata.parse, body)
        except metadata.InvalidMetadata as error:
            raise ApiError(
                400, "invalid_metadata", f"The metadata cannot be read: {error}."
            ) from None
        if parsed.plugin_group and uploaded.plugins:
            await keep_plugins(context, path, parsed.plugin_group, uploaded.plugins)
    # Everything else a client puts in metadata is derived here from the files stored.
    return Response(status_code=201)


async def _checksum(
    context: RepositoryContext,
    request: Request,
    path: str,
    target: str,
    parsed: paths.MavenPath,
    algorithm: str,
) -> Response:
    """Answer for a checksum path on a hosted repository. Checksums are never stored."""
    if request.method in ("GET", "HEAD"):
        found = await _digest(context, target, parsed, algorithm)
        if found is None:
            raise _not_found()
        return _checksum_response(context, request, path, *found)
    if request.method != "PUT":
        raise ApiError(
            405,
            "method_not_allowed",
            "A checksum is computed from its file. It can be read or uploaded, not deleted.",
            headers={"Allow": "GET, HEAD, PUT"},
        )

    context.require_write()
    body = await context.receive(request.stream(), limit=checksums.LIMIT)
    if parsed.is_metadata:
        # It cannot be checked: the client's document is not the one served.
        return Response(status_code=201)
    found = await _digest(context, target, parsed, algorithm)
    if found is None:
        raise ApiError(404, "not_found", "There is no file here for this checksum to belong to.")
    declared = None if body is None else checksums.read_uploaded(body, algorithm)
    if declared != found[0]:
        # Maven only warns when a checksum upload fails, so this log line is where a
        # corrupted deploy becomes visible.
        log.warning(
            "checksum_mismatch",
            repository=context.repository.name,
            path=target,
            algorithm=algorithm,
            by=context.principal.user.username,
        )
        # The file stays. Removing it would let anyone who may add delete files by
        # sending a wrong checksum.
        raise ApiError(
            400, "checksum_mismatch", f"The {algorithm} checksum does not match the stored file."
        )
    return Response(status_code=201)


async def _cached_by(
    member: RepositoryContext, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """The metadata a proxy has for `path`, fetched if need be, as a model."""
    settings = member.repository.config["format_config"]
    if _excluded(settings, parsed) is not None and await member.stat(path) is None:
        return None
    try:
        await proxy.ensure_cached(member, path)
    except ApiError as error:
        if error.status_code not in group.TRY_NEXT:
            raise
        return None
    stored = await member.stat(path)
    if stored is None:
        return None
    try:
        data = await member.read(path, limit=STORED_LIMIT)
        held = await asyncio.to_thread(metadata.parse, data or b"")
    except TooLarge:
        reason = "it is larger than 4 MiB"
    except metadata.InvalidMetadata as error:
        reason = str(error)
    else:
        return held, stored.modified
    # Logged, because the group still answers and nothing else would show it.
    log.warning(
        "member_metadata_unusable", repository=member.repository.name, path=path, reason=reason
    )
    return None


async def _held_by(
    member: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """What one member of a group has for a metadata path, or None if it has nothing.

    A member that cannot answer is left out, never an error: the group answers from
    the others.
    """
    kind = member.repository.type
    if kind == "hosted":
        return await built(member, path, parsed)
    if kind == "proxy":
        return await _cached_by(member, path, parsed)
    if kind == "group":
        return await _merged(member, request, path, parsed)
    return None


async def _merged(
    context: RepositoryContext, request: Request, path: str, parsed: paths.MavenPath
) -> tuple[metadata.Metadata, datetime] | None:
    """A group's metadata for `path`: every member's, as one document."""
    found = []
    for member in await group.member_contexts(context, request):
        held = await _held_by(member, request, path, parsed)
        if held is not None:
            found.append(held)
    if not found:
        return None
    merged = await asyncio.to_thread(metadata.merge, [held for held, _ in found])
    return merged, max(modified for _, modified in found)


class MavenFormat(Format):
    name = "maven"

    def validate_config(
        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if repository_type == "group":
            # A group holds nothing of its own, so it has no policy of its own.
            if config:
                raise _invalid(sorted(config)[0], "A Maven group has no settings.")
            return {}
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

    def is_metadata(self, path: str) -> bool:
        """What changes at a remote: metadata, the catalog, and old-style snapshot files.

        Release files and timestamped snapshot files never change once published.
        """
        parsed = paths.classify(path)
        if parsed.is_metadata or parsed.kind == "catalog":
            return True
        return parsed.kind == "artifact" and parsed.is_snapshot and parsed.build is None

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        path = normalise_path(path)
        # A checksum path is treated as the path it belongs to.
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        if request.method == "PUT":
            refusal = _excluded(context.repository.config["format_config"], parsed)
            if refusal is not None:
                raise refusal
        if algorithm is not None:
            return await _checksum(context, request, path, target, parsed, algorithm)
        if parsed.is_metadata:
            return await _metadata(context, request, path, parsed)
        return await super().handle_hosted(context, request, path)

    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        if request.method not in ("GET", "HEAD"):
            return await super().handle_proxy(context, request, path)  # refuses it
        path = normalise_path(path)
        target, algorithm = paths.split_checksum(path)
        parsed = paths.classify(target)
        settings = context.repository.config["format_config"]
        if _excluded(settings, parsed) is not None and await context.stat(target) is None:
            # Not asked of the remote: this repository would not keep the answer.
            raise _not_found()
        if algorithm is None:
            # Files, and metadata exactly as the remote wrote it: a proxy does not hold
            # every version, so it cannot write the list itself.
            return await super().handle_proxy(context, request, path)
        # The remote's own checksum file is never requested. The file is, if it is not
        # cached yet, and the checksum is of the bytes that will be served.
        await proxy.ensure_cached(context, target)
        stored = await context.stat(target)
        if stored is None:
            raise _not_found()
        return _checksum_response(
            context, request, path, getattr(stored, algorithm), stored.modified
        )

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if request.method in ("GET", "HEAD"):
            path = normalise_path(path)
            target, algorithm = paths.split_checksum(path)
            parsed = paths.classify(target)
            if parsed.is_metadata:
                found = await _merged(context, request, target, parsed)
                if found is None:
                    raise _not_found()
                merged, modified = found
                data = await asyncio.to_thread(metadata.serialise, merged)
                if algorithm is None:
                    return _metadata_response(context, request, data, modified)
                digest = hashlib.new(algorithm, data).hexdigest()
                return _checksum_response(context, request, path, digest, modified)
        # A file and its checksums: the first member that has the file answers both.
        return await super().handle_group(context, request, path, serve)


register(MavenFormat())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/maven/format.py backend/tests/repositories/maven/test_group.py
git commit -m "feat(maven): group repositories that merge their members' metadata"
```

---

### Task 7: A real Maven build through a group, and documentation

**Files:**
- Modify: `backend/tests/test_maven_client.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-08-maven-format-design.md`

**Interfaces:**
- Consumes: Maven proxy and group repositories; the existing helpers in `tests/test_maven_client.py` (`write`, `maven`, `fetch`, `LIBRARY_POM`, `LIBRARY_SOURCE`, `CONSUMER_SOURCE`, the `repositories` fixture).
- Produces: one more Docker-marked test. It needs internet access: the proxy fetches from Maven Central.

- [ ] **Step 1: Write the test**

In `backend/tests/test_maven_client.py`, in the `repositories` fixture, add directly before the line `role = {`:

```python
    central = {
        "name": "central",
        "format": "maven",
        "type": "proxy",
        "proxy": {"remote_url": "https://repo1.maven.org/maven2"},
    }
    everything = {
        "name": "maven-public",
        "format": "maven",
        "type": "group",
        "group": {"members": ["releases", "snapshots", "central"]},
    }
    for repository in (central, everything):
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body
```

Add after the `CONSUMER_SOURCE` definition:

```python
# Everything Maven asks for goes to one group: nothing comes from Maven Central directly.
MIRRORED = f"""<settings>
  <servers>
    <server>
      <id>megooarti</id><username>{USERNAME}</username><password>{PASSWORD}</password>
    </server>
  </servers>
  <mirrors>
    <mirror>
      <id>megooarti</id>
      <mirrorOf>*</mirrorOf>
      <url>{INSIDE}/maven-public/</url>
    </mirror>
    <mirror>
      <id>maven-default-http-blocker</id>
      <mirrorOf>external:does-not-match-anything:*</mirrorOf>
      <url>http://0.0.0.0/</url>
      <blocked>false</blocked>
    </mirror>
  </mirrors>
</settings>
"""

MIRRORED_CONSUMER_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>io.megooarti.test</groupId>
  <artifactId>mirrored-consumer</artifactId>
  <version>1</version>
  <properties>
    <maven.compiler.release>17</maven.compiler.release>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>io.megooarti.test</groupId>
      <artifactId>library</artifactId>
      <version>2.0</version>
    </dependency>
  </dependencies>
</project>
"""
```

Add after `test_maven_deploys_a_release_and_two_snapshot_builds_and_resolves_them`:

```python
def test_maven_builds_from_an_empty_local_repository_through_a_group(
    repositories, administrator, tmp_path
):
    files = {
        "settings.xml": MIRRORED,
        "pom.xml": LIBRARY_POM.format(version="2.0", server=INSIDE),
        "src/main/java/io/megooarti/test/Library.java": LIBRARY_SOURCE,
        "consumer/pom.xml": MIRRORED_CONSUMER_POM,
        "consumer/src/main/java/io/megooarti/test/consumer/Consumer.java": CONSUMER_SOURCE,
    }
    project = write(tmp_path / "mirrored", files)
    # One local repository that starts empty. The library is removed from it between
    # the two builds, so the consumer has to resolve it through the group as well.
    local = f"{MAVEN} -Dmaven.repo.local=/tmp/local-repository"
    forget = "rm -rf /tmp/local-repository/io/megooarti"

    built = maven(project, f"{local} deploy && {forget} && {local} -f consumer/pom.xml compile")

    through = f"Downloaded from megooarti: {INSIDE}/maven-public"
    assert built.returncode == 0, built.stdout[-6000:]
    assert "repo.maven.apache.org" not in built.stdout
    assert f"{through}/org/apache/maven/plugins/" in built.stdout
    assert f"{through}/{LIBRARY}/2.0/library-2.0.jar" in built.stdout

    # What came through the group from Maven Central is now in the proxy, and the
    # checksum the proxy computes is of those bytes.
    proxied = re.search(rf"{re.escape(through)}/(org/apache/maven/\S+\.pom)", built.stdout)
    assert proxied is not None
    pom = fetch(f"central/{proxied[1]}")
    assert pom.lstrip().startswith(b"<")
    assert fetch(f"central/{proxied[1]}.sha1").decode() == hashlib.sha1(pom).hexdigest()

    # Metadata through the group: ours generated, Maven Central's fetched, both merged.
    ours = metadata.parse(fetch(f"maven-public/{LIBRARY}/maven-metadata.xml"))
    assert "2.0" in ours.versions
    compiler = "org/apache/maven/plugins/maven-compiler-plugin"
    theirs = metadata.parse(fetch(f"maven-public/{compiler}/maven-metadata.xml"))
    assert len(theirs.versions) > 10
    assert theirs.release == theirs.versions[-1]

    status, _, shown = call("GET", "/repositories/central", headers=administrator)
    assert status == 200
    assert (shown["status"]["blocked"], shown["status"]["auto_blocked_until"]) == (False, None)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_maven_client.py -q`
Expected: 3 passed. This run downloads a few hundred files from Maven Central through the proxy and can take several minutes.

If it fails, the Maven output in the assertion message names the request that failed and its status. Fix the server, not the test.

- [ ] **Step 3: Document it**

In `README.md`, replace the first paragraph of the section `## Repositories` (it begins "A **blob store** is where") with:

```markdown
A **blob store** is where file content is kept; the `default` one is a directory under
the data directory. A **repository** holds files in one format. The formats so far are
`raw` (arbitrary files by path) and `maven`. A repository has one of three types:
`hosted` (files you publish), `proxy` (a cache of a remote repository) or `group`
(several repositories behind one URL).
```

In the section `### Maven repositories`, add after the two `curl` commands that create the hosted repositories (inside the same code block):

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "central", "format": "maven", "type": "proxy",
  "proxy": {"remote_url": "https://repo1.maven.org/maven2"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "maven-public", "format": "maven", "type": "group",
  "group": {"members": ["releases", "snapshots", "central"]}
}' http://localhost:8000/api/v1/repositories
```

In the same section, replace the last bullet (`- Proxy and group Maven repositories are not available yet.`) with:

````markdown
- **A proxy** caches what it fetches. It serves the remote's `maven-metadata.xml` as
  received, and answers checksum requests from the cached file: it never asks the
  remote for a checksum file. Metadata and old-style snapshot files are checked again
  after `metadata_max_age_minutes`; release files after `content_max_age_minutes`. A
  proxy with the `release` policy does not ask its remote for snapshots.
- **A group** serves a file from the first member that has it, and merges
  `maven-metadata.xml` from every member that can answer, so one URL lists your own
  versions and the remote's. A group has no policies of its own.

To send everything Maven resolves through the group, mirror it in `~/.m2/settings.xml`:

```xml
<mirrors>
  <mirror>
    <id>megooarti</id>
    <mirrorOf>*</mirrorOf>
    <url>https://repo.example.com/repository/maven-public/</url>
  </mirror>
</mirrors>
```

Reading through a group needs `read` on the group only, for example
`repository:maven:maven-public:read`.
````

In `docs/superpowers/specs/2026-10-08-maven-format-design.md`:

1. In section 4.1, at the end of the bullet that begins "**Accepting an upload that stores nothing.**", add the sentence:

   ```markdown
   Both it and `maintain` refuse to run on a repository that is not hosted.
   ```

2. In section 6.4, at the end of the paragraph, add the sentence:

   ```markdown
   A document nested more than 16 levels deep, or holding more than 100,000 elements, is refused as well.
   ```

3. In section 7, at the end of the first paragraph (it ends "without a remote request."), add the sentence:

   ```markdown
   A file cached before the layout policy was tightened is still served.
   ```

4. In section 8, at the end of the last paragraph (it begins "The merged document is built on each request"), add the sentence:

   ```markdown
   Building and merging run in a worker thread, so a long list of versions does not hold up other requests.
   ```

- [ ] **Step 4: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -m docker -q`
Expected: all pass, no findings; 11 container tests.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_maven_client.py README.md docs/superpowers/specs/2026-10-08-maven-format-design.md
git commit -m "test(maven): build through a group with Maven itself; document proxy and group repositories"
```
