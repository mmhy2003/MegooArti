# npm Proxy and Group Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** npm, pnpm and Yarn install through one address that serves a team's own packages and a cache of the public registry, and a public package can never add to or replace a package the team publishes.

**Architecture:** A proxy caches the remote's package document as a file and serves it through a streaming rewriter that points every tarball link at MegooArti; the document is never parsed. A group looks at every hosted and proxy repository behind it at once: if a hosted one holds the package, hosted ones alone answer for its document and its tarballs; otherwise the proxies do, one document streamed as it is or several merged within a memory limit. The core gains a response that streams a stored file through a transformer, a list of the repositories behind a group, and a package search across repositories.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, the standard library's `re` and `json`, pytest + pytest-asyncio, Docker (the `node:22-slim` image, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-08-npm-format-design.md](../specs/2026-10-08-npm-format-design.md), sections 4.2, 8, 9, 10 and the plan 5b part of 13. Business requirements: [docs/BRD.md](../../BRD.md) FMT-2 (proxy, group; npm, pnpm and Yarn), REP-12, NFR-1. Task 6 amends the spec where this plan settles something the spec left open or had wrong.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | D2 covers tarballs as well as documents. If a hosted repository behind a group holds a package, only hosted repositories serve its tarballs. | The spec had the first member with the file answer. With a proxy listed before a hosted repository, the remote's file would then be served for a version the hosted repository published. |
| P2 | A hosted repository that is offline still claims the packages it holds. Through a group they answer `503 repository_offline`, not the remote's package of the same name. | Otherwise taking a hosted repository offline for maintenance opens exactly the hole D2 closes. |
| P3 | The npm group handler works on `group.leaves`: every hosted and proxy repository behind the group, nested groups flattened, each marked online or offline. It does not use the generic group engine. | The rule is about all the hosted repositories behind a group at once, however they are nested, and about offline ones too. |
| P4 | A transformed response takes a `variant` string, and its `ETag` is the SHA-256 of the file's hash and the variant. npm's variant is the address the links are pointed at. | One cached file is served with different links by the proxy, by each group in front of it, and after the base URL changes. Each must have its own `ETag`. |
| P5 | A response whose length is not known declares none, for `HEAD` too, and serves no ranges. | Its length is known only by rewriting it. `Content-Length: 0` on `HEAD` would be a false statement. |
| P6 | Several proxies' documents are merged only while they fit in 16 MiB together, two merges at a time. One that does not fit, or is not a package document, is left out and logged; fewer than two left means one is streamed as it is. | Parsed, a document takes several times its size. The spec's limit was for each document, which let memory grow with the number of proxies. |
| P7 | A merged document has its links rewritten by the same rewriter as a streamed one. | One rule decides which links are rewritten. |
| P8 | A group's search is one query over the online repositories behind it: each package once, ordered by name. A package's version and description come from a hosted repository if one holds it. | The spec's "members' results in order" cannot be paged without reading every member's whole list. |
| P9 | A version manifest and the dist-tags endpoints answer `405` with an empty `Allow` on a proxy and on a group. | Both are answered from stored versions, which only a hosted repository has. An empty `Allow` says no method works here. |
| P10 | Between Tasks 3 and 5 the format offers `hosted` and `proxy`. Task 5 adds `group`. | On the generic group engine a group would serve a member's document, with links that name the member. |
| P11 | The real-client test uses npm 10, pnpm 9 and Yarn 1.22. pnpm is itself installed through the group. Yarn gets `always-auth=true`. | Yarn 1 ships in the Node image and is what `yarn` means to most projects; it sends a token for an unscoped package only when told to. Installing pnpm exercises a large public package. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; settings prefixed `MEGOOARTI_` and listed in `README.md`; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; only the security package reads `Principal.patterns`; content responses always carry `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; formats do not commit, the route does; a token or password is never logged; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration, no setting and no dependency.**
- **Only `npm/format.py` touches the repository context.** `npm/rewrite.py` and `npm/documents.py` are pure functions: no database, no files, no clock.
- **A remote's package document is never parsed**, with one exception: to merge the documents of several proxies behind a group, within `MERGE_LIMIT` (16 MiB together) and two merges at a time.
- **D2 applies to every answer about a package** a group gives: its document and its tarballs. An offline hosted repository still counts as holding its packages.
- **Reading through a group needs `read` on the group only.** Members are not checked again.
- **The sign-in endpoints work on every repository type.** Everything that changes a package answers `405` on a proxy and on a group.
- **Document work runs on the npm worker threads**, with the database connection given back first.
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A public package with the name of a private one**, by every way in: the document; the tarball of a version only the remote has; the tarball of a version both have, with the proxy listed first; the hosted repository offline; the hosted repository behind a nested group that is offline. None may reach the remote's package (Task 5).
2. **A link the rewriter meets in an awkward place:** cut at any byte by the pieces a file is read in; in a document larger than one piece; text in a README that looks like a link; a link written with escaped slashes; a value that never ends (Tasks 2, 3).
3. **A remote that fails:** down, with and without a cached copy; answering `404`; answering something that is not a package document. Alone it is `502` or `404` or served as it came; behind a group the others answer (Tasks 3, 5).
4. **Conditional requests and `HEAD` for content whose length is not known.** The `ETag` changes with the file, with the address in the links, and between a proxy and the group in front of it. `HEAD` declares no length. A `Range` is ignored (Tasks 1, 3, 5).
5. **Memory.** Documents too large to merge together are not parsed; no more than two merges run at once, and they do not wait for publishes (Task 5).

---

### Task 1: Core: a transformed response, the repositories behind a group, names across repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/serving.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/group.py`
- Modify: `backend/tests/repositories/fake_remote.py`
- Test: `backend/tests/repositories/test_serving.py`
- Test: `backend/tests/repositories/test_content_reads.py`
- Test: `backend/tests/repositories/test_content_components.py`
- Test: `backend/tests/repositories/test_group.py`

**Interfaces:**
- Consumes: `serving.Servable`, `serving._base_headers`, `context.respond`, `context.package_names`, `service.members`, `build_context`.
- Produces:
  - `serving.StreamPlan(status: int, headers: dict[str, str], send_body: bool)` and `serving.plan_stream(method: str, request_headers: Mapping[str, str], item: Servable) -> StreamPlan`. `item.etag` must be set; its size and digests are not used.
  - `content.Transformer`: a protocol with `feed(chunk: bytes) -> bytes` and `finish() -> bytes`.
  - `await context.respond_transformed(path, request, transformer, *, variant: str, content_type: str | None = None, filename: str | None = None) -> Response`. Raises `404 not_found`. Commits before the body is sent, like `respond`.
  - `await context.package_names(text, *, limit, offset, within: Sequence[RepositoryContext] | None = None) -> tuple[list[tuple[str, str]], int]`. `within` defaults to the repository itself.
  - `group.Leaf(context: RepositoryContext, online: bool)` and `await group.leaves(context) -> list[Leaf]`.
  - `FakeRemote.requests[n]["raw_path"]`: the request path as it was written, escapes and all.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/fake_remote.py`:

After

```python
                "path": request.url.path,
```

add

```python
                # As it was written in the request, before any escape was decoded.
                "raw_path": request.scope["raw_path"].decode("ascii"),
```

In `backend/tests/repositories/test_serving.py`:

Replace

```python
from megooarti.repositories.serving import Plan, Servable, plan
```

with

```python
from megooarti.repositories.serving import Plan, Servable, plan, plan_stream
```

Add to the end of `backend/tests/repositories/test_serving.py`:

```python
MADE = replace(ITEM, sha256="", md5=None, sha1=None, sha512=None, size=0, etag="made")


def test_content_made_as_it_is_sent_declares_no_length_and_serves_no_range():
    made = plan_stream("GET", Headers({"range": "bytes=0-9"}), MADE)

    assert (made.status, made.send_body) == (200, True)
    assert made.headers["ETag"] == '"made"'
    assert made.headers["Accept-Ranges"] == "none"
    assert "Content-Length" not in made.headers
    assert "Content-Range" not in made.headers
    assert made.headers["Last-Modified"] == MODIFIED
    assert made.headers["Content-Disposition"].startswith('attachment; filename="notes.txt"')
    assert made.headers["X-Content-Type-Options"] == "nosniff"
    assert made.headers["Content-Security-Policy"] == "sandbox"
    assert not [name for name in made.headers if name.startswith("X-Checksum")]


@pytest.mark.parametrize(
    ("method", "headers", "expected"),
    [
        ("HEAD", {}, (200, False)),
        ("GET", {"if-none-match": '"made"'}, (304, False)),
        ("GET", {"if-none-match": '"other"'}, (200, True)),
        ("GET", {"if-modified-since": MODIFIED}, (304, False)),
        ("GET", {"if-none-match": '"other"', "if-modified-since": MODIFIED}, (200, True)),
        ("HEAD", {"if-none-match": "*"}, (304, False)),
    ],
)
def test_content_made_as_it_is_sent_honours_head_and_conditions(method, headers, expected):
    made = plan_stream(method, Headers(headers), MADE)

    assert (made.status, made.send_body) == expected
    assert made.headers["ETag"] == '"made"'
```

In `backend/tests/repositories/test_content_reads.py`:

Before

```python
from megooarti.repositories.content import FileEntry, Stored, TooLarge
```

add

```python
from megooarti.errors import ApiError
```

Add to the end of `backend/tests/repositories/test_content_reads.py`:

```python
class Shout:
    """Upper-cases what passes through, and holds the last byte back until the end."""

    def __init__(self) -> None:
        self._held = b""

    def feed(self, chunk: bytes) -> bytes:
        data = self._held + chunk.upper()
        self._held = data[-1:]
        return data[:-1]

    def finish(self) -> bytes:
        return self._held + b"!"


async def sent(response) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


async def shouted(context, incoming: Request, variant: str = "shout", **options):
    return await context.respond_transformed(
        "notes/readme.txt", incoming, Shout(), variant=variant, **options
    )


async def test_a_stored_file_is_sent_through_a_transformer(context):
    await context.put("notes/readme.txt", body(b"hello, " * 100_000 + b"world"))

    response = await shouted(context, request())

    assert response.status_code == 200
    assert await sent(response) == b"HELLO, " * 100_000 + b"WORLD!"
    assert "content-length" not in response.headers
    assert response.headers["Accept-Ranges"] == "none"
    assert response.headers["Content-Type"] == "text/plain"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="readme.txt"')
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox"
    assert not [name for name in response.headers if name.lower().startswith("x-checksum")]


async def test_the_etag_of_a_transformed_file_names_the_file_and_the_transformation(context):
    await context.put("notes/readme.txt", body(b"one"))
    first = (await shouted(context, request())).headers["ETag"]
    again = (await shouted(context, request())).headers["ETag"]
    another_way = (await shouted(context, request(), "whisper")).headers["ETag"]
    await context.put("notes/readme.txt", body(b"two"))
    another_file = (await shouted(context, request())).headers["ETag"]

    stored = hashlib.sha256(b"one").hexdigest()
    assert first == '"' + hashlib.sha256(f"{stored}\nshout".encode()).hexdigest() + '"'
    assert again == first
    assert len({first, another_way, another_file}) == 3


async def test_a_transformed_file_honours_head_and_conditions_and_serves_no_range(context):
    await context.put("notes/readme.txt", body(b"hello"))
    etag = (await shouted(context, request())).headers["ETag"]

    head = await shouted(context, request("HEAD"))
    unchanged = await shouted(context, request(if_none_match=etag))
    ranged = await shouted(context, request(range="bytes=0-1"))

    assert (head.status_code, await sent(head), head.headers["ETag"]) == (200, b"", etag)
    assert "content-length" not in head.headers  # not 0: the length is simply not known
    assert (unchanged.status_code, unchanged.body) == (304, b"")
    assert (ranged.status_code, await sent(ranged)) == (200, b"HELLO!")
    assert "content-range" not in ranged.headers


async def test_a_transformed_response_can_name_its_type_and_its_file(context):
    await context.put("notes/readme.txt", body(b"{}"))

    response = await shouted(
        context, request(), content_type="application/json", filename="package.json"
    )

    assert response.headers["Content-Type"] == "application/json"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="package.json"')


async def test_transforming_a_file_that_is_not_stored_is_not_found(context):
    with pytest.raises(ApiError) as caught:
        await shouted(context, request())

    assert (caught.value.status_code, caught.value.code) == (404, "not_found")


async def test_sending_a_transformed_file_notes_the_download_and_keeps_no_transaction(context, db):
    asset, _ = await context.put("notes/readme.txt", body(b"hello"))
    await db.commit()

    await shouted(context, request("HEAD"))
    after_head = asset.last_downloaded_at
    response = await shouted(context, request())
    in_transaction = db.in_transaction()
    await sent(response)

    assert after_head is None
    assert asset.last_downloaded_at is not None
    assert in_transaction is False  # the connection is given back before the body is sent
```

Add to the end of `backend/tests/repositories/test_content_components.py`:

```python
async def test_package_names_can_cover_several_repositories(context, context_for, db):
    more = await service.create_repository(
        db, name="more", format="raw", type="hosted", online=True, blob_store="default"
    )
    await db.commit()
    second = await context_for(more, someone("repository:raw:more"))
    second.format = Packaged()
    await store(context, "acme/left-pad/1.0/a.tgz")
    await store(context, "acme/only-here/1.0/a.tgz")
    await store(second, "acme/left-pad/3.0/a.tgz")
    await store(second, "zeta/pad-there/1.0/a.tgz")
    both = [context, second]

    names, total = await context.package_names("", limit=10, offset=0, within=both)
    page, page_total = await context.package_names("pad", limit=1, offset=1, within=both)
    alone = await second.package_names("", limit=10, offset=0)
    nowhere = await context.package_names("", limit=10, offset=0, within=[])

    # A package both hold is listed once.
    assert names == [("acme", "left-pad"), ("acme", "only-here"), ("zeta", "pad-there")]
    assert total == 3
    assert (page, page_total) == ([("zeta", "pad-there")], 2)
    assert alone == ([("acme", "left-pad"), ("zeta", "pad-there")], 2)
    assert nowhere == ([], 0)
```

Add to the end of `backend/tests/repositories/test_group.py`:

```python
async def nested(db):
    """`outer` presents `three`, then the group `all` (`one`, `two`), then `one` again."""
    await create(db, "three")
    return await create(db, "outer", "group", group={"members": ["three", "all", "one"]})


def named(found: list[group.Leaf]) -> list[tuple[str, bool]]:
    return [(leaf.context.repository.name, leaf.online) for leaf in found]


async def test_leaves_are_every_repository_behind_a_group_in_order(db, everything, context_for):
    reader = someone("repository:raw:outer:read")
    context = await context_for(await nested(db), reader, outbound=bare_request)

    found = await group.leaves(context)
    again = await group.leaves(context)

    assert named(found) == [("three", True), ("one", True), ("two", True)]
    assert named(again) == named(found)  # unlike member_contexts, as often as it is asked
    assert all(leaf.context.principal is reader for leaf in found)
    assert all(leaf.context.outbound is bare_request for leaf in found)


async def test_leaves_include_what_is_offline_and_say_so(db, everything, context_for):
    context = await context_for(await nested(db), None)
    two = await service.get_repository(db, "two")
    await service.update_repository(db, two, online=False)
    await db.commit()

    one_offline = await group.leaves(context)
    await service.update_repository(db, everything, online=False, group={"members": ["one", "two"]})
    await db.commit()
    group_offline = await group.leaves(context)

    assert named(one_offline) == [("three", True), ("one", True), ("two", False)]
    # `one` is still a member of `outer` in its own right, and is tried where that puts it.
    assert named(group_offline) == [("three", True), ("two", False), ("one", True)]


async def test_leaves_of_a_cycle_that_slipped_into_the_data_end(db, context_for):
    first = await create(db, "all", "group")
    second = await create(db, "loop", "group", group={"members": ["all"]})
    await db.execute(
        insert(RepositoryMember).values(group_id=first.id, member_id=second.id, position=0)
    )
    await db.commit()

    assert await group.leaves(await context_for(first, None)) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_serving.py tests/repositories/test_content_reads.py tests/repositories/test_content_components.py tests/repositories/test_group.py -q`
Expected: the run stops while collecting. `test_serving.py`: `cannot import name 'plan_stream'`. `test_group.py`: `module 'megooarti.repositories.group' has no attribute 'Leaf'`.

Run: `uv run pytest tests/repositories/test_content_reads.py tests/repositories/test_content_components.py -q`
Expected: 7 failures. `'RepositoryContext' object has no attribute 'respond_transformed'`, and `package_names() got an unexpected keyword argument 'within'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/serving.py`:

After

```python
@dataclass(frozen=True)
class Plan:
    status: int
    headers: dict[str, str]
    byte_range: tuple[int, int] | None  # inclusive offsets; None means send no body
```

add

```python
@dataclass(frozen=True)
class StreamPlan:
    """How to answer for content whose length is not known until it has been sent."""

    status: int
    headers: dict[str, str]
    send_body: bool
```

Replace

```python
def plan(method: str, request_headers: Mapping[str, str], item: Servable) -> Plan:
    headers = _base_headers(item)
    etag = _etag(item)

    if_none_match = request_headers.get("if-none-match")
    if if_none_match is not None:
        if _etag_matches(if_none_match, etag):
            return Plan(304, headers, None)
    else:
        since = request_headers.get("if-modified-since")
        if since and _not_modified_since(since, item.last_modified):
            return Plan(304, headers, None)
```

with

```python
def _unchanged(request_headers: Mapping[str, str], item: Servable) -> bool:
    """Whether the client says it already has this content."""
    if_none_match = request_headers.get("if-none-match")
    if if_none_match is not None:
        return _etag_matches(if_none_match, _etag(item))
    since = request_headers.get("if-modified-since")
    return bool(since) and _not_modified_since(since, item.last_modified)


def plan_stream(method: str, request_headers: Mapping[str, str], item: Servable) -> StreamPlan:
    """Plan the answer for content that is made as it is sent.

    `item.etag` says what the content will be; its size and digests are not used. No
    length is declared and no range is honoured: a `Range` header is ignored, as HTTP
    allows.
    """
    headers = _base_headers(item)
    headers["Accept-Ranges"] = "none"
    if _unchanged(request_headers, item):
        return StreamPlan(304, headers, False)
    return StreamPlan(200, headers, method == "GET")


def plan(method: str, request_headers: Mapping[str, str], item: Servable) -> Plan:
    headers = _base_headers(item)
    etag = _etag(item)

    if _unchanged(request_headers, item):
        return Plan(304, headers, None)
```

In `backend/src/megooarti/repositories/content.py`:

Replace

```python
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
```

with

```python
from collections.abc import AsyncIterator, Awaitable, Callable, Collection, Sequence
```

Replace

```python
from typing import Any
```

with

```python
from typing import Any, Protocol
```

After

```python
class TooLarge(Exception):
    """A file that was to be read into memory is larger than the caller allows."""
```

add

```python
class Transformer(Protocol):
    """Rewrites content as it is sent, piece by piece."""

    def feed(self, chunk: bytes) -> bytes:
        """What can be sent now that `chunk` has been seen."""

    def finish(self) -> bytes:
        """What is left to send once every piece has been fed."""


async def _nothing() -> AsyncIterator[bytes]:
    return
    yield b""  # what makes this a generator
```

Replace

```python
    async def package_names(
        self, text: str, *, limit: int, offset: int
    ) -> tuple[list[tuple[str, str]], int]:
        """Packages whose name or namespace contains `text`, and how many there are.

        The text is matched literally and without regard to case. An empty text matches
        every package.
        """
        literal = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{literal}%"
        found = (
            select(Component.namespace, Component.name)
            .where(
                Component.repository_id == self.repository.id,
```

with

```python
    async def package_names(
        self,
        text: str,
        *,
        limit: int,
        offset: int,
        within: Sequence["RepositoryContext"] | None = None,
    ) -> tuple[list[tuple[str, str]], int]:
        """Packages whose name or namespace contains `text`, and how many there are.

        The text is matched literally and without regard to case. An empty text matches
        every package. `within` names the repositories to look in, for a group, which
        holds nothing itself: a package several of them hold is listed once.
        """
        literal = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{literal}%"
        searched = [self] if within is None else within
        found = (
            select(Component.namespace, Component.name)
            .where(
                Component.repository_id.in_([context.repository.id for context in searched]),
```

After

```python
        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return StreamingResponse(
            self.backend.open(blob.sha256, start, end),
            status_code=plan.status,
            headers=plan.headers,
        )
```

add

```python
    async def respond_transformed(
        self,
        path: str,
        request: Request,
        transformer: Transformer,
        *,
        variant: str,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> Response:
        """The response to a GET or HEAD for a stored file, rewritten as it is sent.

        For a file too large to hold in memory whose content depends on who asks, such
        as a document with links to this server in it. `variant` names what the
        transformer does to the file: the `ETag` is made from it and the file's hash, so
        it must change whenever the result would. The length is not known beforehand,
        so none is declared and ranges are not served.
        """
        path = normalise_path(path)
        found = (
            await self.db.execute(
                select(Asset, Blob)
                .join(Blob, Blob.id == Asset.blob_id)
                .where(Asset.repository_id == self.repository.id, Asset.path == path)
            )
        ).one_or_none()
        if found is None:
            raise ApiError(404, "not_found", "No such file.")
        asset, blob = found
        item = serving.Servable(
            sha256="",
            md5=None,
            sha1=None,
            sha512=None,
            size=0,
            content_type=content_type or asset.content_type,
            last_modified=asset.updated_at,
            filename=filename or path.rpartition("/")[2],
            etag=hashlib.sha256(f"{blob.sha256}\n{variant}".encode()).hexdigest(),
        )
        plan = serving.plan_stream(request.method, request.headers, item)

        now = utcnow()
        noted = asset.last_downloaded_at
        if plan.send_body and (noted is None or now - noted >= _DOWNLOAD_NOTE_INTERVAL):
            asset.last_downloaded_at = now
        await self.db.commit()  # give the connection back before the body is sent

        if plan.status == 304:
            return Response(status_code=304, headers=plan.headers)
        # A streaming response even for HEAD: a plain one would declare a length of 0.
        body = self._transformed(blob.sha256, transformer) if plan.send_body else _nothing()
        return StreamingResponse(body, status_code=plan.status, headers=plan.headers)

    async def _transformed(self, sha256: str, transformer: Transformer) -> AsyncIterator[bytes]:
        async for chunk in self.backend.open(sha256):
            passed = transformer.feed(chunk)
            if passed:
                yield passed
        rest = transformer.finish()
        if rest:
            yield rest
```

In `backend/src/megooarti/repositories/group.py`:

Before

```python
from starlette.requests import Request
```

add

```python
import uuid
from dataclasses import dataclass
```

Before

```python
async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
```

add

```python
@dataclass(frozen=True)
class Leaf:
    """A repository behind a group that is not itself a group."""

    context: RepositoryContext
    online: bool  # False if it is offline, or is reached only through an offline group


async def leaves(context: RepositoryContext) -> list[Leaf]:
    """Every hosted and proxy repository behind a group, in the order they are tried.

    For a format that answers from all of them at once instead of from the first that
    has the path. Offline ones are included and marked, because what an offline
    repository holds can still decide what the others may answer. A repository reached
    more than once is listed once, where it is first reached online if it ever is.
    """
    reached: list[tuple[Repository, bool]] = []
    walked = {context.repository.id: True}

    async def walk(repository: Repository, online: bool) -> None:
        for member in await service.members(context.db, repository):
            usable = online and member.online
            if member.type != "group":
                reached.append((member, usable))
            elif member.id not in walked or (usable and not walked[member.id]):
                # Again only if it was reached through something offline before, so a
                # cycle that slipped into the data ends.
                walked[member.id] = usable
                await walk(member, usable)

    await walk(context.repository, True)
    online = {member.id for member, usable in reached if usable}
    found: dict[uuid.UUID, Leaf] = {}
    for member, usable in reached:
        if member.id in found or (not usable and member.id in online):
            continue
        made = await build_context(
            context.db, context.settings, member, context.principal, outbound=context.outbound
        )
        found[member.id] = Leaf(made, usable)
    return list(found.values())
```

After

```python
from megooarti.repositories.formats import Serve
```

add

```python
from megooarti.repositories.models import Repository
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(repositories): stream a stored file through a transformer, list what is behind a group"
```

---

### Task 2: The tarball link rewriter

**Files:**
- Create: `backend/src/megooarti/repositories/npm/rewrite.py`
- Test: `backend/tests/repositories/npm/test_rewrite.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `rewrite.TarballLinks(base: str, package: str)` with `feed(chunk: bytes) -> bytes` and `finish() -> bytes`. It satisfies `content.Transformer`. `base` is the public address of a repository, without a trailing slash.
  - `rewrite.rewrite(document: bytes, base: str, package: str) -> bytes`, for a whole document in memory.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/npm/test_rewrite.py`:

```python
import json
import random

import pytest

from megooarti.repositories.npm.rewrite import TarballLinks, rewrite

BASE = "https://repo.example/repository/npmjs"
REMOTE = "https://registry.npmjs.org"


def document(package: str = "left-pad", versions: tuple[str, ...] = ("1.0.0", "1.3.0")) -> bytes:
    """A package document as a remote serves it."""
    name = package.rpartition("/")[2]
    body = {
        "name": package,
        "readme": 'It says "tarball": "http://x/-/y.tgz" in prose, and \\ too.',
        "versions": {
            version: {
                "name": package,
                "version": version,
                "dist": {
                    "shasum": "0" * 40,
                    "tarball": f"{REMOTE}/{package}/-/{name}-{version}.tgz",
                },
            }
            for version in versions
        },
    }
    return json.dumps(body).encode()


def links(data: bytes) -> list[str]:
    return [version["dist"]["tarball"] for version in json.loads(data)["versions"].values()]


def in_pieces(data: bytes, cuts: list[int]) -> bytes:
    rewriter = TarballLinks(BASE, "left-pad")
    edges = [0, *sorted(cuts), len(data)]
    out = [rewriter.feed(data[start:end]) for start, end in zip(edges, edges[1:], strict=False)]
    return b"".join(out) + rewriter.finish()


def test_every_link_points_at_this_repository():
    rewritten = rewrite(document(), BASE, "left-pad")

    assert links(rewritten) == [
        f"{BASE}/left-pad/-/left-pad-1.0.0.tgz",
        f"{BASE}/left-pad/-/left-pad-1.3.0.tgz",
    ]


def test_nothing_else_changes():
    original, rewritten = json.loads(document()), json.loads(rewrite(document(), BASE, "left-pad"))
    for version in original["versions"].values():
        version["dist"]["tarball"] = "x"
    for version in rewritten["versions"].values():
        version["dist"]["tarball"] = "x"

    assert rewritten == original
    assert "http://x/-/y.tgz" in rewritten["readme"]  # prose that looks like a link


def test_a_scoped_package_links_to_its_scoped_path():
    rewritten = rewrite(document("@acme/widget", ("2.0.0",)), BASE, "@acme/widget")

    assert links(rewritten) == [f"{BASE}/@acme/widget/-/widget-2.0.0.tgz"]


@pytest.mark.parametrize(
    "written",
    [
        '"tarball":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"',
        '"tarball" : "https://r.example/left-pad/-/left-pad-1.0.0.tgz"',
        '"tarball":\n\t"http://other.example:8080/deep/path/left-pad/-/left-pad-1.0.0.tgz"',
        '"tarball":"/left-pad/-/left-pad-1.0.0.tgz"',
    ],
)
def test_links_are_found_however_they_are_spaced_and_wherever_they_point(written):
    rewritten = rewrite(f'{{"dist":{{{written}}}}}'.encode(), BASE, "left-pad")

    assert json.loads(rewritten) == {"dist": {"tarball": f"{BASE}/left-pad/-/left-pad-1.0.0.tgz"}}


@pytest.mark.parametrize(
    "left_alone",
    [
        b'{"tarball":"https:\\/\\/r.example\\/left-pad\\/-\\/left-pad-1.0.0.tgz"}',
        b'{"tarball":"https://r.example/download/left-pad/1.0.0/abcdef"}',
        b'{"tarball":"https://r.example/left-pad/-/left-pad-1.0.0.zip"}',
        b'{"tarball":17,"other":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"}',
        b'{"not-tarball":"https://r.example/left-pad/-/left-pad-1.0.0.tgz"}',
        b"",
        b"not json at all",
    ],
)
def test_what_is_not_a_plain_link_is_passed_on_unchanged(left_alone):
    assert rewrite(left_alone, BASE, "left-pad") == left_alone


def test_the_result_is_the_same_wherever_the_document_is_cut():
    data = document()
    whole = rewrite(data, BASE, "left-pad")

    for cut in range(len(data) + 1):
        assert in_pieces(data, [cut]) == whole, cut


def test_the_result_is_the_same_in_pieces_of_any_size():
    data = document(versions=tuple(f"1.{minor}.0" for minor in range(40)))
    whole = rewrite(data, BASE, "left-pad")
    chooser = random.Random(5)

    for size in (1, 2, 3, 7, 64, 1000):
        assert in_pieces(data, list(range(size, len(data), size))) == whole, size
    for _ in range(50):
        cuts = sorted(chooser.sample(range(len(data)), 12))
        assert in_pieces(data, cuts) == whole, cuts


def test_only_the_start_of_an_unfinished_link_is_held_back():
    rewriter = TarballLinks(BASE, "left-pad")

    passed = rewriter.feed(b'{"a":"' + b"x" * 100_000 + b'","tarball":"https://r.example/le')

    assert len(passed) == len(b'{"a":"') + 100_000 + len(b'",')
    assert rewriter.feed(b'ft-pad/-/left-pad-1.0.0.tgz"}') == (
        f'"tarball":"{BASE}/left-pad/-/left-pad-1.0.0.tgz"}}'.encode()
    )
    assert rewriter.finish() == b""


def test_a_value_too_long_to_be_a_link_is_not_waited_for():
    rewriter = TarballLinks(BASE, "left-pad")
    endless = b'{"tarball":"' + b"x" * 20_000

    assert rewriter.feed(endless) == endless
    assert rewriter.finish() == b""


def test_an_address_with_characters_json_escapes_stays_valid_json():
    rewritten = rewrite(document(versions=("1.0.0",)), 'https://odd.example/a"b', "left-pad")

    assert links(rewritten) == ['https://odd.example/a"b/left-pad/-/left-pad-1.0.0.tgz']
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm/test_rewrite.py -q`
Expected: collection error, `No module named 'megooarti.repositories.npm.rewrite'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/npm/rewrite.py`:

```python
"""Point the tarball links of a package document at this repository, as it streams.

A proxy serves the remote's package document, and every `"tarball"` in it names the
remote. These documents reach tens of megabytes, so they are never parsed: the links
are rewritten in the bytes as they pass. Pure: no database, no files.

A JSON string cannot contain an unescaped quote, so `"tarball": "` can only be a key
and its value, never text inside a README.
"""

import json
import re

# "tarball": "<any address>/-/<file>.tgz" - the value has no quote and no backslash, so
# a link written with escaped slashes is left as it is.
_LINK = re.compile(rb'"tarball"\s*:\s*"[^"\\]*/-/([^"/\\]+\.tgz)"')
_KEY = b'"tarball"'
# The longest link that is waited for. Anything longer is passed on unchanged.
_MAX_LINK = 8192


class TarballLinks:
    """Rewrites links in a document fed to it in pieces.

    `feed` returns what can be passed on so far; `finish` returns the rest. What is
    held back is only the start of a link that has not ended yet.
    """

    def __init__(self, base: str, package: str) -> None:
        """`base` is the public address of the repository, without a trailing slash."""
        # As it is written inside a JSON string: an address may hold a character JSON escapes.
        self._opening = b'"tarball":"' + json.dumps(f"{base}/{package}/-/")[1:-1].encode()
        self._held = b""

    def feed(self, chunk: bytes) -> bytes:
        data = self._held + chunk
        passed = []
        position = 0
        for link in _LINK.finditer(data):
            passed.append(data[position : link.start()])
            passed.append(self._opening + link[1] + b'"')
            position = link.end()
        rest = data[position:]
        keep = _unfinished(rest)
        passed.append(rest[: len(rest) - keep])
        self._held = rest[len(rest) - keep :] if keep else b""
        return b"".join(passed)

    def finish(self) -> bytes:
        held, self._held = self._held, b""
        return held


def _unfinished(rest: bytes) -> int:
    """How many bytes at the end of `rest` may be the start of a link.

    Only the last `"tarball"` can be one: an earlier one that did not match is followed
    by a quote, which ends its value.
    """
    start = rest.rfind(_KEY)
    if start != -1:
        waiting = len(rest) - start
        return waiting if waiting <= _MAX_LINK else 0
    # No whole key: the end may still be the beginning of one.
    for length in range(min(len(_KEY) - 1, len(rest)), 0, -1):
        if rest.endswith(_KEY[:length]):
            return length
    return 0


def rewrite(document: bytes, base: str, package: str) -> bytes:
    """A whole document with its links rewritten."""
    links = TarballLinks(base, package)
    return links.feed(document) + links.finish()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/npm/test_rewrite.py -q`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/npm/rewrite.py backend/tests/repositories/npm/test_rewrite.py
git commit -m "feat(npm): rewrite the tarball links of a package document as it streams"
```

---

### Task 3: npm proxy repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Modify: `backend/tests/repositories/npm/conftest.py`
- Test: `backend/tests/repositories/npm/test_proxy.py`

**Interfaces:**
- Consumes: `context.respond_transformed` and `FakeRemote.requests[n]["raw_path"]` (Task 1); `rewrite.TarballLinks` (Task 2); `proxy.ensure_cached(context, path)`, `proxy.handle_proxy(context, request, path)`, `context.public_url(request)`, `registry_endpoint`.
- Produces:
  - `await _streamed(holder: RepositoryContext, request, package: str, base: str) -> Response`: a proxy's cached document with its links at `base`.
  - `_hosted_only() -> ApiError`: the `405` for what only a hosted repository answers.
  - `NpmFormat.remote_url`, `NpmFormat.is_metadata`, `NpmFormat.handle_proxy`; `NpmFormat.types` is `{"hosted", "proxy"}`.
  - Test helpers in `tests/repositories/npm/conftest.py`: `REMOTE`, `create(db, name, *, type="hosted", hosted=None, proxy=None, group=None)`, `remote_document(package, *versions, remote=REMOTE, **extra) -> bytes`, and the fixture `npmjs` (a proxy of `REMOTE`).

- [ ] **Step 1: Write the test helpers and the failing tests**

The helpers file is replaced: `create` can now make any type of repository, and `remote_document` and `npmjs` are new. The test file is new.

`backend/tests/repositories/npm/conftest.py`:

```python
import base64
import hashlib
import json

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/npm"
REMOTE = "http://remote.test/registry"


async def create(
    db,
    name: str,
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
) -> Repository:
    """An npm repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="npm",
        type=type,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        group=group,
        format_config={},
    )
    await db.commit()
    return repository


def tarball_of(package: str, version: str) -> bytes:
    """Stand-in tarball bytes, different for every package and version."""
    return f"\x1f\x8b tarball of {package}@{version}".encode()


def publish_body(package: str, version: str, *, tag: str = "latest", **manifest) -> dict:
    """What `npm publish` sends for one version."""
    data = tarball_of(package, version)
    dist = {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": f"http://client.example/{package}/-/{package}-{version}.tgz",
    }
    return {
        "_id": package,
        "name": package,
        "dist-tags": {tag: version},
        "versions": {version: {"name": package, "version": version, "dist": dist, **manifest}},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(data).decode(),
                "length": len(data),
            }
        },
    }


def address(package: str, repository: str = "npm") -> str:
    """A package's address as npm writes it: a scoped name has its slash encoded."""
    return f"/repository/{repository}/{package.replace('/', '%2f')}"


async def publish(client, headers, package: str, version: str, **changes):
    """Publish one version. Returns the response."""
    repository = changes.pop("repository", "npm")
    body = publish_body(package, version, **changes)
    return await client.put(address(package, repository), json=body, headers=headers)


def remote_document(package: str, *versions: str, remote: str = REMOTE, **extra) -> bytes:
    """A package document as a remote registry serves it, with its links at the remote."""
    name = package.rpartition("/")[2]
    listed = {
        version: {
            "name": package,
            "version": version,
            "dist": {
                "shasum": hashlib.sha1(tarball_of(package, version)).hexdigest(),
                "tarball": f"{remote}/{package}/-/{name}-{version}.tgz",
            },
        }
        for version in versions
    }
    document = {
        "_id": package,
        "name": package,
        "dist-tags": {"latest": versions[-1]},
        "versions": listed,
        "time": {version: "2020-01-01T00:00:00.000Z" for version in versions},
        **extra,
    }
    return json.dumps(document).encode()


@pytest.fixture
async def registry(db) -> Repository:
    return await create(db, "npm")


@pytest.fixture
async def npmjs(db) -> Repository:
    """A proxy of the fake remote."""
    return await create(db, "npmjs", type="proxy", proxy={"remote_url": REMOTE})


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

`backend/tests/repositories/npm/test_proxy.py`:

```python
import hashlib
import json

import pytest
from sqlalchemy import select

from megooarti.repositories.models import Asset, Component
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, bearer, error_code
from tests.repositories.npm.conftest import REMOTE, create, remote_document, tarball_of

PROXY = "/repository/npmjs"
HERE = "https://test/repository/npmjs"
TARBALL = f"{PROXY}/left-pad/-/left-pad-1.3.0.tgz"


def asked(remote, method: str = "GET") -> list[str]:
    return [path.removeprefix("/registry/") for path in remote.paths(method)]


def links(response) -> list[str]:
    return [version["dist"]["tarball"] for version in response.json()["versions"].values()]


@pytest.fixture
def remote(fake_remote, npmjs):
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0", "1.3.0")
    fake_remote.files["registry/left-pad/-/left-pad-1.3.0.tgz"] = tarball_of("left-pad", "1.3.0")
    fake_remote.files["registry/@acme/widget"] = remote_document("@acme/widget", "2.0.0")
    return fake_remote


async def test_a_package_document_is_served_with_its_links_pointing_here(client, root, remote):
    first = await client.get(f"{PROXY}/left-pad", headers=root)
    second = await client.get(f"{PROXY}/left-pad", headers=root)

    assert first.status_code == 200, first.text
    assert links(first) == [
        f"{HERE}/left-pad/-/left-pad-1.0.0.tgz",
        f"{HERE}/left-pad/-/left-pad-1.3.0.tgz",
    ]
    assert first.json()["dist-tags"] == {"latest": "1.3.0"}
    assert second.content == first.content
    assert asked(remote) == ["left-pad"]


async def test_the_document_is_answered_as_content_without_a_length(client, root, remote):
    first = await client.get(f"{PROXY}/left-pad", headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(f"{PROXY}/left-pad", headers={**root, "If-None-Match": etag})
    headed = await client.head(f"{PROXY}/left-pad", headers=root)
    ranged = await client.get(f"{PROXY}/left-pad", headers={**root, "Range": "bytes=0-9"})

    assert first.headers["Content-Type"] == "application/json"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert first.headers["Accept-Ranges"] == "none"
    assert "Content-Length" not in first.headers
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (headed.status_code, headed.content, headed.headers["ETag"]) == (200, b"", etag)
    assert "Content-Length" not in headed.headers  # not 0: the length is not known
    assert (ranged.status_code, ranged.content) == (200, first.content)


async def test_a_document_read_back_in_several_pieces_has_every_link_rewritten(
    client, root, npmjs, fake_remote
):
    versions = [f"1.0.{patch}" for patch in range(12_000)]
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", *versions)
    assert len(fake_remote.files["registry/left-pad"]) > 2 * 1024 * 1024  # over two pieces

    response = await client.get(f"{PROXY}/left-pad", headers=root)

    assert links(response) == [f"{HERE}/left-pad/-/left-pad-{version}.tgz" for version in versions]


async def test_a_document_asked_for_by_head_first_is_fetched_once(client, root, remote):
    headed = await client.head(f"{PROXY}/left-pad", headers=root)
    fetched = await client.get(f"{PROXY}/left-pad", headers=root)

    assert (headed.status_code, fetched.status_code) == (200, 200)
    assert (asked(remote), asked(remote, "HEAD")) == (["left-pad"], [])


async def test_a_scoped_package_is_asked_for_as_the_registry_spells_it(client, root, remote):
    encoded = await client.get(f"{PROXY}/@acme%2fwidget", headers=root)
    plain = await client.get(f"{PROXY}/@acme/widget", headers=root)

    assert links(encoded) == [f"{HERE}/@acme/widget/-/widget-2.0.0.tgz"]
    assert plain.content == encoded.content
    assert [seen["raw_path"] for seen in remote.requests] == ["/registry/@acme%2Fwidget"]


async def test_a_tarball_is_fetched_cached_and_given_its_component(client, root, remote, db):
    first = await client.get(TARBALL, headers=root)
    second = await client.get(f"{TARBALL}/-rev/anything", headers=root)

    data = tarball_of("left-pad", "1.3.0")
    assert (first.status_code, first.content, second.content) == (200, data, data)
    assert first.headers["Content-Type"] == "application/octet-stream"
    assert first.headers["X-Checksum-Sha1"] == hashlib.sha1(data).hexdigest()
    assert asked(remote) == ["left-pad/-/left-pad-1.3.0.tgz"]
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "left-pad", "1.3.0")


async def test_a_scoped_tarball_is_fetched_from_its_scoped_path(client, root, remote):
    remote.files["registry/@acme/widget/-/widget-2.0.0.tgz"] = tarball_of("@acme/widget", "2.0.0")

    response = await client.get(f"{PROXY}/@acme/widget/-/widget-2.0.0.tgz", headers=root)

    assert response.content == tarball_of("@acme/widget", "2.0.0")
    assert remote.requests[0]["raw_path"] == "/registry/@acme/widget/-/widget-2.0.0.tgz"


async def test_documents_are_asked_about_again_and_tarballs_are_not(client, root, db, fake_remote):
    ages = {"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": -1}
    await create(db, "eager", type="proxy", proxy=ages)
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.3.0")
    fake_remote.files["registry/left-pad/-/left-pad-1.3.0.tgz"] = tarball_of("left-pad", "1.3.0")

    for _ in range(2):
        await client.get("/repository/eager/left-pad", headers=root)
        await client.get("/repository/eager/left-pad/-/left-pad-1.3.0.tgz", headers=root)

    assert asked(fake_remote) == ["left-pad", "left-pad/-/left-pad-1.3.0.tgz", "left-pad"]


async def test_a_new_version_at_the_remote_appears_and_changes_the_etag(
    client, root, db, fake_remote
):
    await create(
        db, "eager", type="proxy", proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0}
    )
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0")
    before = await client.get("/repository/eager/left-pad", headers=root)
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0", "1.3.0")

    after = await client.get(
        "/repository/eager/left-pad", headers={**root, "If-None-Match": before.headers["ETag"]}
    )

    assert (after.status_code, list(after.json()["versions"])) == (200, ["1.0.0", "1.3.0"])
    assert after.headers["ETag"] != before.headers["ETag"]


async def test_what_the_remote_lacks_is_not_found_and_remembered(client, root, remote):
    first = await client.get(f"{PROXY}/no-such-package", headers=root)
    again = await client.get(f"{PROXY}/no-such-package", headers=root)

    assert (first.status_code, error_code(first)) == (404, "not_found")
    assert again.status_code == 404
    assert asked(remote) == ["no-such-package"]


async def test_a_cached_document_is_served_while_the_remote_is_down(client, root, db, fake_remote):
    await create(
        db, "eager", type="proxy", proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0}
    )
    fake_remote.files["registry/left-pad"] = remote_document("left-pad", "1.0.0")
    cached = await client.get("/repository/eager/left-pad", headers=root)
    fake_remote.down = True

    still = await client.get("/repository/eager/left-pad", headers=root)
    never_seen = await client.get("/repository/eager/right-pad", headers=root)

    assert (still.status_code, still.content) == (200, cached.content)
    assert (never_seen.status_code, error_code(never_seen)) == (502, "remote_unavailable")


async def test_links_use_the_configured_public_address(client, root, remote, db):
    by_request = await client.get(f"{PROXY}/left-pad", headers=root)
    await set_setting(db, "base_url", "https://packages.example")
    await db.commit()

    configured = await client.get(f"{PROXY}/left-pad", headers=root)

    assert links(configured)[0] == (
        "https://packages.example/repository/npmjs/left-pad/-/left-pad-1.0.0.tgz"
    )
    assert configured.headers["ETag"] != by_request.headers["ETag"]


async def test_a_link_written_with_escaped_slashes_is_left_as_it_is(client, root, remote):
    escaped = remote_document("left-pad", "1.0.0").replace(b"/", b"\\/")
    remote.files["registry/odd"] = escaped

    response = await client.get(f"{PROXY}/odd", headers=root)

    assert response.content == escaped
    assert json.loads(response.content)["versions"]["1.0.0"]["dist"]["tarball"].startswith(REMOTE)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "left-pad"),
        ("DELETE", "left-pad"),
        ("DELETE", "left-pad/-/left-pad-1.3.0.tgz"),
        ("PUT", "-/package/left-pad/dist-tags/beta"),
        ("POST", "-/v1/search"),
    ],
)
async def test_a_proxy_cannot_be_written_to(client, root, remote, method, path):
    response = await client.request(method, f"{PROXY}/{path}", json={}, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert asked(remote) == []


@pytest.mark.parametrize(
    "path", ["left-pad/1.3.0", "left-pad/latest", "-/package/left-pad/dist-tags"]
)
async def test_what_only_a_hosted_repository_answers_is_not_allowed(client, root, remote, path):
    response = await client.get(f"{PROXY}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert asked(remote) == []


async def test_signing_in_works_on_a_proxy(client, npmjs, make_user):
    await make_user("dana", roles=["admin"])
    login = f"{PROXY}/-/user/org.couchdb.user:dana"

    signed_in = await client.put(login, json={"name": "dana", "password": PASSWORD})
    token = signed_in.json()["token"]
    who = await client.get(f"{PROXY}/-/whoami", headers=bearer(token))
    signed_out = await client.delete(f"{PROXY}/-/user/token/{token}", headers=bearer(token))

    assert (signed_in.status_code, who.json()) == (201, {"username": "dana"})
    assert signed_out.status_code == 200
    assert (await client.get(f"{PROXY}/-/ping", headers=bearer(token))).status_code == 401


async def test_search_finds_what_the_proxy_has_cached(client, root, remote, db):
    before = await client.get(f"{PROXY}/-/v1/search", params={"text": "pad"}, headers=root)
    await client.get(TARBALL, headers=root)

    after = await client.get(f"{PROXY}/-/v1/search", params={"text": "pad"}, headers=root)

    assert before.json()["objects"] == []
    found = after.json()["objects"]
    assert [(entry["package"]["name"], entry["package"]["version"]) for entry in found] == [
        ("left-pad", "1.3.0")
    ]
    assert list(await db.scalars(select(Asset.path))) == ["left-pad/-/left-pad-1.3.0.tgz"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm -q`
Expected: every test in `test_proxy.py` fails or errors while creating its repository: `proxy repositories are not available for this format`. The tests of plan 5a still pass.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/npm/format.py`:

Replace

```python
right after an unpublish and after two publishes at once. Reading a publish and
building a document are CPU-bound work whose size a client decides, so they run on two
worker threads of their own.
"""
```

with

```python
right after an unpublish and after two publishes at once. Reading a publish and
building a document are CPU-bound work whose size a client decides, so they run on two
worker threads of their own.

A proxy does not hold every version of a package, so it cannot write the document
itself. It serves the remote's, with the tarball links in it pointed here as it is sent.
"""
```

Replace

```python
from typing import Any

from starlette.requests import Request
```

with

```python
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
```

Replace

```python
from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.npm import documents, paths, semver
from megooarti.repositories.paths import normalise_path
```

with

```python
from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.npm import documents, paths, semver
from megooarti.repositories.npm.rewrite import TarballLinks
from megooarti.repositories.paths import normalise_path
```

Before

```python
def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The request cannot be accepted: {reason}.")
```

add

```python
def _hosted_only() -> ApiError:
    """For what is answered from the versions stored, which only a hosted repository has."""
    return ApiError(
        405,
        "method_not_allowed",
        "Only a hosted repository answers at this address. Ask for the package itself.",
        headers={"Allow": ""},
    )
```

Replace

```python
    raise _not_allowed("GET, HEAD" if not tag else "PUT, DELETE")


class NpmFormat(Format):
    name = "npm"
    # Proxy and group repositories need npm's own handling of package documents.
    types = frozenset({"hosted"})
```

with

```python
    raise _not_allowed("GET, HEAD" if not tag else "PUT, DELETE")


# --- What a proxy serves -------------------------------------------------------------


async def _streamed(
    holder: RepositoryContext, request: Request, package: str, base: str
) -> Response:
    """A proxy's cached package document, its links pointed at `base` as it is sent.

    `base` is the public address of the repository that was asked. The document is
    never read into memory: such documents reach tens of megabytes.
    """
    return await holder.respond_transformed(
        package,
        request,
        TarballLinks(base, package),
        variant=f"tarball links to {base}",
        content_type=_JSON,
        filename=f"{paths.unscoped(package)}.json",
    )


class NpmFormat(Format):
    name = "npm"
    # A group needs npm's own handling of package documents.
    types = frozenset({"hosted", "proxy"})
```

Replace

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        return _TARBALL if paths.classify(path).kind == "tarball" else declared
```

with

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        kind = paths.classify(path).kind
        if kind == "tarball":
            return _TARBALL
        return _JSON if kind == "document" else declared

    def remote_url(self, base: str, path: str) -> str:
        """Where a proxy finds a path on its remote.

        A scoped package's document is asked for as registries spell it, with the
        slash of its name encoded: `@scope%2Fname`.
        """
        parsed = paths.classify(path)
        if parsed.kind == "document" and parsed.scope:
            return f"{base.rstrip('/')}/@{parsed.scope}%2F{parsed.name}"
        return f"{base.rstrip('/')}/{quote(path, safe='/@')}"

    def is_metadata(self, path: str) -> bool:
        """A package document changes with every publish. A tarball never changes."""
        return paths.classify(path).kind == "document"
```

After

```python
            return await _search(context, request)
        raise _not_found("Nothing is served at this address.")
```

add

```python
    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(normalise_path(path))
        answered = await registry_endpoint(context, request, parsed)
        if answered is not None:
            return answered
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "document":
            await proxy.ensure_cached(context, parsed.package)
            base = await context.public_url(request)
            return await _streamed(context, request, parsed.package, base)
        if parsed.kind == "tarball":
            # Asked for under its one spelling, whatever revision the address carried.
            canonical = paths.tarball_path(parsed.package, parsed.version)
            return await proxy.handle_proxy(context, request, canonical)
        if parsed.kind == "search":
            return await _search(context, request)
        if parsed.kind in ("version", "dist_tags"):
            raise _hosted_only()
        raise _not_found("Nothing is served at this address.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/npm/format.py backend/tests/repositories/npm
git commit -m "feat(npm): proxy repositories that serve package documents with their links pointed here"
```

---

### Task 4: Merging package documents

**Files:**
- Modify: `backend/src/megooarti/repositories/npm/documents.py`
- Test: `backend/tests/repositories/npm/test_documents.py`

**Interfaces:**
- Consumes: `rewrite.rewrite` (Task 2); `documents.Version`, `effective_tags`, `loads`, `dumps`, `render`.
- Produces:
  - `documents.combine(held: Sequence[tuple[Sequence[Version], Mapping[str, str]]]) -> tuple[list[Version], dict[str, str]]`: several hosted repositories' versions and stored dist-tags as one repository's. Its result goes to `documents.render`.
  - `documents.Merged(data: bytes | None, etag: str, used: tuple[int, ...])`.
  - `documents.merge_remote(package: str, raw: Sequence[bytes], base: str) -> Merged`: several registries' documents as one, links at `base`. `data` is `None` when fewer than two could be read.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/tests/repositories/npm/test_documents.py`:

```python
def test_what_several_repositories_hold_is_combined_and_the_earlier_one_wins():
    first = ([stored("1.0.0", description="from the first")], {"latest": "1.0.0"})
    second = (
        [stored("1.0.0", T2, description="from the second"), stored("2.0.0-beta.1", T2)],
        {"latest": "1.0.0", "beta": "2.0.0-beta.1", "gone": "9.9.9"},
    )

    versions, tags = documents.combine([first, second])

    assert [version.version for version in versions] == ["1.0.0", "2.0.0-beta.1"]
    assert versions[0].manifest["description"] == "from the first"
    assert tags == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}


def test_the_first_repositorys_latest_is_the_latest_even_when_a_later_one_is_higher():
    first = ([stored("1.0.0")], {})  # no tags stored: its highest version is its latest
    second = ([stored("3.0.0")], {"latest": "3.0.0", "next": "3.0.0"})

    versions, tags = documents.combine([first, second])
    built = documents.document("left-pad", versions, tags, BASE)

    assert tags == {"latest": "1.0.0", "next": "3.0.0"}
    assert list(built["versions"]) == ["1.0.0", "3.0.0"]
    assert built["dist-tags"] == {"latest": "1.0.0", "next": "3.0.0"}


def test_combining_one_repository_changes_nothing():
    only = ([stored("1.0.0"), stored("1.1.0", T2)], {"latest": "1.0.0"})

    versions, tags = documents.combine([only])

    assert documents.render("left-pad", versions, tags, BASE) == documents.render(
        "left-pad", only[0], only[1], BASE
    )
    assert documents.combine([]) == ([], {})


def served(*versions: str, at: str = "https://registry.example", **extra) -> bytes:
    """A package document as another registry serves it."""
    body = {
        "_id": "left-pad",
        "name": "left-pad",
        "dist-tags": {"latest": versions[-1]},
        "versions": {
            version: {
                "name": "left-pad",
                "version": version,
                "dist": {"shasum": SHA1, "tarball": f"{at}/left-pad/-/left-pad-{version}.tgz"},
            }
            for version in versions
        },
        "time": {version: "2020-01-01T00:00:00.000Z" for version in versions},
        **extra,
    }
    return json.dumps(body).encode()


def test_the_documents_of_several_registries_are_merged_and_the_earlier_one_wins():
    first = served("1.0.0", "1.1.0", description="from the first", readme="# first")
    second = served("1.1.0", "2.0.0", at="https://other.example/npm", description="second")
    second = second.replace(b'"2020-01-01', b'"2024-06-01')

    merged = documents.merge_remote("left-pad", [first, second], BASE)

    body = json.loads(merged.data)
    assert merged.used == (0, 1)
    assert merged.etag == hashlib.sha256(merged.data).hexdigest()
    assert list(body["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]
    assert body["dist-tags"] == {"latest": "1.1.0"}
    assert (body["description"], body["readme"]) == ("from the first", "# first")
    assert body["time"] == {
        "1.0.0": "2020-01-01T00:00:00.000Z",
        "1.1.0": "2020-01-01T00:00:00.000Z",
        "2.0.0": "2024-06-01T00:00:00.000Z",
    }
    assert [version["dist"]["tarball"] for version in body["versions"].values()] == [
        f"{BASE}/left-pad/-/left-pad-{version}.tgz" for version in ("1.0.0", "1.1.0", "2.0.0")
    ]


def test_merged_tags_point_at_versions_and_latest_is_always_there():
    first = served("1.0.0", **{"dist-tags": {"next": "1.0.0", "broken": "7.7.7", "odd": 3}})
    second = served("0.9.0", **{"dist-tags": {"latest": "0.9.0", "next": "0.9.0"}})

    body = json.loads(documents.merge_remote("left-pad", [first, second], BASE).data)

    # `next` is the first one's; `latest` is the only one set, by the second.
    assert body["dist-tags"] == {"latest": "0.9.0", "next": "1.0.0"}


@pytest.mark.parametrize(
    "unreadable",
    [b"not json", b"[]", b'{"name":"left-pad"}', b'{"versions":[]}', b'{"versions":{"1.0.0":NaN}}'],
)
def test_a_document_that_cannot_be_read_is_left_out_of_the_merge(unreadable):
    good, other = served("1.0.0"), served("2.0.0")

    three = documents.merge_remote("left-pad", [good, unreadable, other], BASE)
    two = documents.merge_remote("left-pad", [unreadable, good], BASE)

    assert three.used == (0, 2)
    assert list(json.loads(three.data)["versions"]) == ["1.0.0", "2.0.0"]
    assert (two.data, two.used) == (None, (1,))  # one is left: there is nothing to merge


def test_fewer_than_two_documents_are_not_read_at_all():
    assert documents.merge_remote("left-pad", [b"not json"], BASE) == documents.Merged(
        None, "", (0,)
    )
    assert documents.merge_remote("left-pad", [], BASE) == documents.Merged(None, "", ())


def test_odd_parts_of_a_remote_document_do_not_break_the_merge():
    first = served("1.0.0", time="yesterday", **{"dist-tags": None})
    second = served("2.0.0", maintainers=[{"name": "someone"}])

    body = json.loads(documents.merge_remote("left-pad", [first, second], BASE).data)

    assert list(body["versions"]) == ["1.0.0", "2.0.0"]
    assert body["time"] == {"2.0.0": "2020-01-01T00:00:00.000Z"}
    assert body["dist-tags"] == {"latest": "2.0.0"}
    assert "maintainers" not in body  # everything else is the first one's
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm/test_documents.py -q`
Expected: 12 failures, `module 'megooarti.repositories.npm.documents' has no attribute 'combine'` and `... 'merge_remote'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/npm/documents.py`:

After

```python
from megooarti.repositories.npm import paths, semver
```

add

```python
from megooarti.repositories.npm.rewrite import rewrite
```

Add to the end of `backend/src/megooarti/repositories/npm/documents.py`:

```python
def combine(
    held: Sequence[tuple[Sequence[Version], Mapping[str, str]]],
) -> tuple[list[Version], dict[str, str]]:
    """What several repositories hold of one package, as if one repository held it.

    `held` gives each repository's versions and its stored dist-tags, in the order the
    repositories are tried. The earlier one wins a version both hold and a tag both
    set, so the `latest` of the first repository is the `latest` of the result.
    """
    versions: dict[str, Version] = {}
    tags: dict[str, str] = {}
    for theirs, stored in held:
        for version in theirs:
            versions.setdefault(version.version, version)
        shown = effective_tags(stored, [version.version for version in theirs])
        for tag, version in shown.items():
            tags.setdefault(tag, version)
    return list(versions.values()), tags


@dataclass(frozen=True)
class Merged:
    """The documents several registries serve for one package, as one."""

    data: bytes | None  # None when fewer than two of them could be read
    etag: str
    used: tuple[int, ...]  # the positions of those that could be read


def _served(raw: bytes) -> dict[str, Any] | None:
    """A package document another registry served, or None if it is not one."""
    try:
        value = loads(raw)
    except InvalidPackage:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("versions"), dict):
        return None
    return value


def merge_remote(package: str, raw: Sequence[bytes], base: str) -> Merged:
    """Merge the documents several registries serve for one package.

    `raw` is in the order the registries are tried. The earlier one wins a version, a
    time and a dist-tag that two of them have, and everything else is the first
    one's. Tarball links are pointed at `base`, the public address of the repository
    that answers. A document that cannot be read is left out.
    """
    if len(raw) < 2:
        return Merged(None, "", tuple(range(len(raw))))
    read = [(position, _served(data)) for position, data in enumerate(raw)]
    used = tuple(position for position, document in read if document is not None)
    documents = [document for _, document in read if document is not None]
    if len(documents) < 2:
        return Merged(None, "", used)

    merged = dict(documents[0])
    for field in ("versions", "time", "dist-tags"):
        union: dict[str, Any] = {}
        for document in documents:
            theirs = document.get(field)
            for key, value in theirs.items() if isinstance(theirs, dict) else ():
                union.setdefault(key, value)
        merged[field] = union
    tags = {
        tag: version for tag, version in merged["dist-tags"].items() if isinstance(version, str)
    }
    merged["dist-tags"] = effective_tags(tags, merged["versions"])
    data = rewrite(dumps(merged), base, package)
    return Merged(data, hashlib.sha256(data).hexdigest(), used)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/npm -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/npm/documents.py backend/tests/repositories/npm/test_documents.py
git commit -m "feat(npm): merge what several repositories hold of one package"
```

---

### Task 5: npm group repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Test: `backend/tests/repositories/npm/test_group.py`

**Interfaces:**
- Consumes: `group.leaves`, `group.Leaf`, `group.TRY_NEXT`, `context.package_names(..., within=)` (Task 1); `_streamed`, `_hosted_only`, the helpers in `conftest.py` (Task 3); `documents.combine`, `documents.merge_remote` (Task 4); `proxy.ensure_cached`, `context.names`, `context.stat`, `context.read`, `context.release`, `context.respond_with`.
- Produces:
  - `MERGE_LIMIT` (16 MiB) and `merging() -> asyncio.Semaphore`, beside `publishing()`.
  - `await _search(context, request, holders: Sequence[RepositoryContext]) -> Response`: the signature gains `holders`.
  - `NpmFormat.handle_group`; `NpmFormat.types` is no longer overridden, so the format offers all three types.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/npm/test_group.py`:

```python
import asyncio
import hashlib

import pytest
import structlog

from megooarti.repositories import service
from megooarti.repositories.npm import format as npm_format
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, bearer, error_code
from tests.repositories.npm.conftest import create, publish, remote_document, tarball_of

GROUP = "/repository/public"
HERE = "https://test/repository/public"


@pytest.fixture
async def public(db, registry, npmjs):
    """The hosted `npm` and the proxy `npmjs`, in that order."""
    return await create(db, "public", type="group", group={"members": ["npm", "npmjs"]})


async def document(client, headers, package: str, group: str = "public") -> dict:
    response = await client.get(f"/repository/{group}/{package}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def links(body: dict) -> list[str]:
    return [version["dist"]["tarball"] for version in body["versions"].values()]


async def take_offline(db, name: str) -> None:
    repository = await service.get_repository(db, name)
    repository.online = False
    await db.commit()


async def test_a_package_we_host_comes_from_us_and_the_remote_is_not_asked(
    client, root, public, fake_remote
):
    await publish(client, root, "left-pad", "1.0.0")

    body = await document(client, root, "left-pad")
    tarball = await client.get(f"{GROUP}/left-pad/-/left-pad-1.0.0.tgz", headers=root)

    assert list(body["versions"]) == ["1.0.0"]
    assert links(body) == [f"{HERE}/left-pad/-/left-pad-1.0.0.tgz"]  # the group, not `npm`
    assert tarball.content == tarball_of("left-pad", "1.0.0")
    assert fake_remote.requests == []


async def test_a_package_only_the_remote_has_comes_through_the_proxy(
    client, root, public, fake_remote
):
    fake_remote.files["registry/is-number"] = remote_document("is-number", "6.0.0", "7.0.0")
    fake_remote.files["registry/is-number/-/is-number-7.0.0.tgz"] = tarball_of("is-number", "7.0.0")

    first = await client.get(f"{GROUP}/is-number", headers=root)
    direct = await client.get("/repository/npmjs/is-number", headers=root)
    tarball = await client.get(f"{GROUP}/is-number/-/is-number-7.0.0.tgz", headers=root)

    assert links(first.json()) == [
        f"{HERE}/is-number/-/is-number-6.0.0.tgz",
        f"{HERE}/is-number/-/is-number-7.0.0.tgz",
    ]
    assert "Content-Length" not in first.headers  # sent as it is rewritten, never held
    # The same cached file, but not the same content: the links differ.
    assert first.headers["ETag"] != direct.headers["ETag"]
    assert tarball.content == tarball_of("is-number", "7.0.0")
    assert fake_remote.paths() == [
        "/registry/is-number",
        "/registry/is-number/-/is-number-7.0.0.tgz",
    ]


async def test_a_public_package_cannot_add_versions_to_a_name_we_host(
    client, root, public, fake_remote
):
    # Dependency confusion: the same name at the remote, with a higher version.
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "99.0.0")
    fake_remote.files["registry/internal-tool/-/internal-tool-99.0.0.tgz"] = b"hostile"

    body = await document(client, root, "internal-tool")
    theirs = await client.get(f"{GROUP}/internal-tool/-/internal-tool-99.0.0.tgz", headers=root)

    assert list(body["versions"]) == ["1.0.0"]
    assert body["dist-tags"] == {"latest": "1.0.0"}
    assert (theirs.status_code, error_code(theirs)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_a_public_package_cannot_stand_in_for_a_version_we_host(
    client, root, db, registry, npmjs, fake_remote
):
    # The proxy is tried first here, and the remote has the very version we host.
    await create(db, "remote-first", type="group", group={"members": ["npmjs", "npm"]})
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool/-/internal-tool-1.0.0.tgz"] = b"hostile"

    body = await document(client, root, "internal-tool", "remote-first")
    tarball = await client.get(
        "/repository/remote-first/internal-tool/-/internal-tool-1.0.0.tgz", headers=root
    )

    ours = tarball_of("internal-tool", "1.0.0")
    assert body["versions"]["1.0.0"]["dist"]["shasum"] == hashlib.sha1(ours).hexdigest()
    assert tarball.content == ours
    assert fake_remote.requests == []


async def test_a_name_an_offline_repository_holds_is_not_answered_by_the_remote(
    client, root, public, fake_remote, db
):
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "99.0.0")
    fake_remote.files["registry/internal-tool/-/internal-tool-99.0.0.tgz"] = b"hostile"
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    await take_offline(db, "npm")

    ours = await client.get(f"{GROUP}/internal-tool", headers=root)
    tarball = await client.get(f"{GROUP}/internal-tool/-/internal-tool-99.0.0.tgz", headers=root)
    theirs = await document(client, root, "is-number")

    assert (ours.status_code, error_code(ours)) == (503, "repository_offline")
    assert (tarball.status_code, error_code(tarball)) == (503, "repository_offline")
    assert list(theirs["versions"]) == ["7.0.0"]  # a name nobody here holds is still served
    assert fake_remote.paths() == ["/registry/is-number"]


async def test_a_name_held_behind_an_offline_group_is_not_answered_by_the_remote(
    client, root, db, registry, npmjs, fake_remote
):
    await create(db, "inner", type="group", group={"members": ["npm"]})
    await create(db, "outer", type="group", group={"members": ["inner", "npmjs"]})
    await publish(client, root, "internal-tool", "1.0.0")
    fake_remote.files["registry/internal-tool"] = remote_document("internal-tool", "99.0.0")
    await take_offline(db, "inner")

    response = await client.get("/repository/outer/internal-tool", headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")
    assert fake_remote.requests == []


async def test_an_offline_proxy_is_left_out(client, root, public, fake_remote, db):
    await publish(client, root, "left-pad", "1.0.0")
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    await take_offline(db, "npmjs")

    ours = await document(client, root, "left-pad")
    theirs = await client.get(f"{GROUP}/is-number", headers=root)

    assert list(ours["versions"]) == ["1.0.0"]
    assert (theirs.status_code, error_code(theirs)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_hosted_members_are_merged_and_the_earlier_one_wins(client, root, db):
    await create(db, "npm")
    await create(db, "team")
    await create(db, "both", type="group", group={"members": ["npm", "team"]})
    await publish(client, root, "left-pad", "1.0.0", description="from npm")
    await publish(client, root, "left-pad", "1.0.0", repository="team", description="from team")
    await publish(client, root, "left-pad", "2.0.0-beta.1", repository="team", tag="beta")

    body = await document(client, root, "left-pad", "both")
    tarball = await client.get("/repository/both/left-pad/-/left-pad-1.0.0.tgz", headers=root)
    later = await client.get("/repository/both/left-pad/-/left-pad-2.0.0-beta.1.tgz", headers=root)

    assert list(body["versions"]) == ["1.0.0", "2.0.0-beta.1"]
    assert body["versions"]["1.0.0"]["description"] == "from npm"
    assert body["dist-tags"] == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}
    assert all(link.startswith("https://test/repository/both/left-pad/-/") for link in links(body))
    assert tarball.content == tarball_of("left-pad", "1.0.0")
    assert later.content == tarball_of("left-pad", "2.0.0-beta.1")


async def test_the_merged_document_is_answered_like_any_content(client, root, public):
    await publish(client, root, "left-pad", "1.0.0")
    first = await client.get(f"{GROUP}/left-pad", headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(f"{GROUP}/left-pad", headers={**root, "If-None-Match": etag})
    headed = await client.head(f"{GROUP}/left-pad", headers=root)

    assert first.headers["Content-Type"] == "application/json"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, headed.status_code, headed.content) == (304, 200, b"")


@pytest.fixture
async def mirrors(db, fake_remote):
    """Proxies `first` and `second` of two remotes that both have left-pad, in one group."""
    await create(db, "first", type="proxy", proxy={"remote_url": "http://remote.test/a"})
    await create(db, "second", type="proxy", proxy={"remote_url": "http://remote.test/b"})
    fake_remote.files["a/left-pad"] = remote_document(
        "left-pad", "1.0.0", "1.1.0", remote="http://remote.test/a", description="from a"
    )
    fake_remote.files["b/left-pad"] = remote_document(
        "left-pad", "1.1.0", "2.0.0", remote="http://remote.test/b", description="from b, " * 40
    )
    return await create(db, "mirrors", type="group", group={"members": ["first", "second"]})


async def test_two_proxies_that_both_have_a_package_are_merged(client, root, mirrors, fake_remote):
    fake_remote.files["a/left-pad/-/left-pad-1.1.0.tgz"] = b"from a"
    fake_remote.files["b/left-pad/-/left-pad-1.1.0.tgz"] = b"from b"
    fake_remote.files["b/left-pad/-/left-pad-2.0.0.tgz"] = b"only b"

    first = await client.get("/repository/mirrors/left-pad", headers=root)
    again = await client.get(
        "/repository/mirrors/left-pad", headers={**root, "If-None-Match": first.headers["ETag"]}
    )
    shared = await client.get("/repository/mirrors/left-pad/-/left-pad-1.1.0.tgz", headers=root)
    theirs = await client.get("/repository/mirrors/left-pad/-/left-pad-2.0.0.tgz", headers=root)

    body = first.json()
    assert list(body["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]
    assert body["dist-tags"] == {"latest": "1.1.0"}  # the earlier member's
    assert body["description"] == "from a"
    assert links(body) == [
        f"https://test/repository/mirrors/left-pad/-/left-pad-{version}.tgz"
        for version in ("1.0.0", "1.1.0", "2.0.0")
    ]
    assert first.headers["ETag"] == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert again.status_code == 304
    assert (shared.content, theirs.content) == (b"from a", b"only b")


async def test_documents_too_large_to_merge_together_are_not_merged_and_it_is_logged(
    client, root, mirrors, fake_remote, monkeypatch
):
    # The second proxy's document is the longer one. Either fits; both do not.
    monkeypatch.setattr(npm_format, "MERGE_LIMIT", len(fake_remote.files["b/left-pad"]))

    with structlog.testing.capture_logs() as logs:
        body = await document(client, root, "left-pad", "mirrors")

    assert list(body["versions"]) == ["1.0.0", "1.1.0"]
    assert links(body)[0] == "https://test/repository/mirrors/left-pad/-/left-pad-1.0.0.tgz"
    too_large = [entry for entry in logs if entry["event"] == "document_too_large_to_merge"]
    assert [(entry["repository"], entry["package"]) for entry in too_large] == [
        ("second", "left-pad")
    ]


async def test_at_most_two_merges_are_in_memory_at_once_and_publishes_do_not_hold_them_up():
    running, most = 0, 0

    async def one() -> None:
        nonlocal running, most
        async with npm_format.merging():
            running += 1
            most = max(most, running)
            await asyncio.sleep(0.01)
            running -= 1

    async with npm_format.publishing(), npm_format.publishing():
        await asyncio.wait_for(asyncio.gather(*(one() for _ in range(6))), timeout=5)

    assert most == 2


async def test_a_document_that_cannot_be_read_is_left_out_and_logged(
    client, root, mirrors, fake_remote
):
    fake_remote.files["a/left-pad"] = b"<html>not a package document</html>"

    with structlog.testing.capture_logs() as logs:
        body = await document(client, root, "left-pad", "mirrors")

    assert list(body["versions"]) == ["1.1.0", "2.0.0"]
    assert links(body)[0] == "https://test/repository/mirrors/left-pad/-/left-pad-1.1.0.tgz"
    unreadable = [entry for entry in logs if entry["event"] == "document_unreadable"]
    assert [entry["repository"] for entry in unreadable] == ["first"]


async def test_only_one_of_two_proxies_having_a_package_is_not_a_merge(
    client, root, mirrors, fake_remote
):
    fake_remote.files["b/is-number"] = remote_document(
        "is-number", "7.0.0", remote="http://remote.test/b"
    )

    response = await client.get("/repository/mirrors/is-number", headers=root)

    assert links(response.json()) == [
        "https://test/repository/mirrors/is-number/-/is-number-7.0.0.tgz"
    ]
    assert "Content-Length" not in response.headers  # streamed, not built


async def test_nobody_has_it(client, root, public, fake_remote):
    missing = await client.get(f"{GROUP}/no-such-package", headers=root)
    fake_remote.down = True
    unreachable = await client.get(f"{GROUP}/another-package", headers=root)
    tarball = await client.get(f"{GROUP}/another-package/-/another-package-1.0.0.tgz", headers=root)

    assert (missing.status_code, error_code(missing)) == (404, "not_found")
    assert (unreachable.status_code, error_code(unreachable)) == (404, "not_found")
    assert (tarball.status_code, error_code(tarball)) == (404, "not_found")


async def test_a_group_inside_a_group(client, root, public, fake_remote, db):
    await create(db, "extra")
    await create(db, "outer", type="group", group={"members": ["public", "extra"]})
    await publish(client, root, "left-pad", "1.0.0")
    await publish(client, root, "left-pad", "3.0.0", repository="extra")
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    fake_remote.files["registry/is-number/-/is-number-7.0.0.tgz"] = tarball_of("is-number", "7.0.0")

    ours = await document(client, root, "left-pad", "outer")
    theirs = await document(client, root, "is-number", "outer")
    tarball = await client.get("/repository/outer/is-number/-/is-number-7.0.0.tgz", headers=root)

    assert list(ours["versions"]) == ["1.0.0", "3.0.0"]
    assert links(theirs) == ["https://test/repository/outer/is-number/-/is-number-7.0.0.tgz"]
    assert tarball.content == tarball_of("is-number", "7.0.0")


async def test_reading_through_the_group_needs_read_on_the_group_only(
    client, root, public, fake_remote, make_user, db
):
    await publish(client, root, "left-pad", "1.0.0")
    fake_remote.files["registry/is-number"] = remote_document("is-number", "7.0.0")
    members = ["repository:npm:npm:read", "repository:npm:npmjs:read"]
    await roles.create_role(db, "group-readers", "", ["repository:npm:public:read"], [])
    await roles.create_role(db, "member-readers", "", members, [])
    await db.commit()
    await make_user("gina", roles=["group-readers"])
    await make_user("mel", roles=["member-readers"])
    gina, mel = basic("gina", PASSWORD), basic("mel", PASSWORD)

    ours = await document(client, gina, "left-pad")
    theirs = await document(client, gina, "is-number")
    tarball = await client.get(f"{GROUP}/left-pad/-/left-pad-1.0.0.tgz", headers=gina)
    refused = await client.get(f"{GROUP}/left-pad", headers=mel)

    assert (list(ours["versions"]), list(theirs["versions"])) == (["1.0.0"], ["7.0.0"])
    assert tarball.status_code == 200
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_signing_in_works_on_a_group_and_changing_packages_does_not(
    client, public, make_user
):
    await make_user("dana", roles=["admin"])
    login = f"{GROUP}/-/user/org.couchdb.user:dana"

    signed_in = await client.put(login, json={"name": "dana", "password": PASSWORD})
    token = bearer(signed_in.json()["token"])
    who = await client.get(f"{GROUP}/-/whoami", headers=token)
    published = await publish(client, token, "left-pad", "1.0.0", repository="public")
    tagged = await client.put(
        f"{GROUP}/-/package/left-pad/dist-tags/x", json="1.0.0", headers=token
    )
    removed = await client.delete(f"{GROUP}/left-pad/-/left-pad-1.0.0.tgz", headers=token)
    one_version = await client.get(f"{GROUP}/left-pad/latest", headers=token)
    tags = await client.get(f"{GROUP}/-/package/left-pad/dist-tags", headers=token)

    assert (signed_in.status_code, who.json()) == (201, {"username": "dana"})
    for response in (published, tagged, removed, one_version, tags):
        assert (response.status_code, error_code(response)) == (405, "method_not_allowed")


async def test_search_covers_every_member_and_lists_a_package_once(
    client, root, public, fake_remote
):
    await publish(client, root, "left-pad", "1.0.0", description="ours")
    await publish(client, root, "our-pad", "1.0.0")
    fake_remote.files["registry/left-pad/-/left-pad-9.0.0.tgz"] = b"theirs"
    fake_remote.files["registry/pad-right/-/pad-right-2.0.0.tgz"] = b"theirs"
    for path in ("left-pad/-/left-pad-9.0.0.tgz", "pad-right/-/pad-right-2.0.0.tgz"):
        await client.get(f"/repository/npmjs/{path}", headers=root)  # into the proxy's cache

    response = await client.get(f"{GROUP}/-/v1/search", params={"text": "pad"}, headers=root)
    page = await client.get(
        f"{GROUP}/-/v1/search", params={"text": "pad", "size": 1, "from": 1}, headers=root
    )

    found = [
        (entry["package"]["name"], entry["package"]["version"], entry["package"]["description"])
        for entry in response.json()["objects"]
    ]
    # What we host is described by us, whatever a proxy has cached under the same name.
    assert found == [
        ("left-pad", "1.0.0", "ours"),
        ("our-pad", "1.0.0", ""),
        ("pad-right", "2.0.0", ""),
    ]
    assert response.json()["total"] == 3
    assert [entry["package"]["name"] for entry in page.json()["objects"]] == ["our-pad"]
    assert page.json()["total"] == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm -q`
Expected: every test in `test_group.py` fails or errors. Creating a group is refused, `group repositories are not available for this format`, and `module 'megooarti.repositories.npm.format' has no attribute 'merging'`. Everything else passes.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/npm/format.py`:

Replace

```python
A proxy does not hold every version of a package, so it cannot write the document
itself. It serves the remote's, with the tarball links in it pointed here as it is sent.
"""
```

with

```python
A proxy does not hold every version of a package, so it cannot write the document
itself. It serves the remote's, with the tarball links in it pointed here as it is sent.

A group answers for a package from its hosted members if one of them holds it, and
only otherwise from its proxies: a public package must never add versions to a private
name. That holds for the document and for the tarballs alike.
"""
```

Replace

```python
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
```

with

```python
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

import structlog
from starlette.requests import Request
```

Replace

```python
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
```

with

```python
from megooarti.repositories import group, proxy
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
```

Replace

```python
from megooarti.security.authentication import unauthorized

# The most that is read into memory besides a publish: a sign-in or a tag, and the tags
# kept for a package.
SMALL_LIMIT = 16 * 1024
TAGS_LIMIT = 1024 * 1024
```

with

```python
from megooarti.security.authentication import unauthorized

log = structlog.get_logger(__name__)

# The most that is read into memory besides a publish: a sign-in or a tag, and the tags
# kept for a package.
SMALL_LIMIT = 16 * 1024
TAGS_LIMIT = 1024 * 1024
# The most that is parsed of proxies' documents, all together, to merge them.
MERGE_LIMIT = 16 * 1024 * 1024
```

Replace

```python
# How many publishes may be in memory at once. Each can be as large as the limit, and
# stays that large from the first byte read until its tarballs are stored.
_PUBLISHES_AT_ONCE = 2
_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)
```

with

```python
# How many publishes may be in memory at once. Each can be as large as the limit, and
# stays that large from the first byte read until its tarballs are stored.
_PUBLISHES_AT_ONCE = 2
# How many merges of proxies' documents may be in memory at once. Parsed, a document
# takes several times its size.
_MERGES_AT_ONCE = 2
_gates: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]]" = (
    weakref.WeakKeyDictionary()
)
```

Replace

```python
def publishing() -> asyncio.Semaphore:
    """The turn a publish takes: `async with publishing():` around reading and storing it.

    One for each event loop, since a semaphore belongs to the loop that first waits on it.
    """
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop)
    if gate is None:
        gate = _gates[loop] = asyncio.Semaphore(_PUBLISHES_AT_ONCE)
    return gate
```

with

```python
def _gate(kind: str, most: int) -> asyncio.Semaphore:
    """One for each event loop, since a semaphore belongs to the loop that first waits on it."""
    gates = _gates.setdefault(asyncio.get_running_loop(), {})
    if kind not in gates:
        gates[kind] = asyncio.Semaphore(most)
    return gates[kind]


def publishing() -> asyncio.Semaphore:
    """The turn a publish takes: `async with publishing():` around reading and storing it."""
    return _gate("publish", _PUBLISHES_AT_ONCE)


def merging() -> asyncio.Semaphore:
    """The turn a merge takes: `async with merging():` around reading and merging."""
    return _gate("merge", _MERGES_AT_ONCE)
```

Before

```python
def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The request cannot be accepted: {reason}.")
```

add

```python
def _offline() -> ApiError:
    return ApiError(503, "repository_offline", "A repository that holds this package is offline.")
```

Replace

```python
    rendered = await off_loop(documents.render, parsed.package, *found)
    return context.respond_with(
        rendered.data,
        request,
        filename=f"{parsed.name}.json",
        content_type=_JSON,
        last_modified=rendered.modified,
        etag=rendered.etag,
    )
```

with

```python
    rendered = await off_loop(documents.render, parsed.package, *found)
    return _as_document(context, request, parsed.package, rendered)
```

Before

```python
async def _document(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
```

add

```python
def _as_document(
    context: RepositoryContext, request: Request, package: str, rendered: documents.Rendered
) -> Response:
    """The answer to a request for a package document that was built for it."""
    return context.respond_with(
        rendered.data,
        request,
        filename=f"{paths.unscoped(package)}.json",
        content_type=_JSON,
        last_modified=rendered.modified,
        etag=rendered.etag,
    )
```

Replace

```python
async def _search(context: RepositoryContext, request: Request) -> Response:
    """Packages this repository holds whose name or scope contains the text."""

    def number(name: str, default: int, most: int) -> int:
        value = request.query_params.get(name, "")
        plain = value.isascii() and value.isdigit() and len(value) <= 9
        return min(int(value), most) if plain else default

    text = request.query_params.get("text", "").strip()[: paths.MAX_NAME_LENGTH]
    size = number("size", 20, _MAX_SEARCH_RESULTS)
    names, total = await context.package_names(text, limit=size, offset=number("from", 0, 10**9))
    found = []
    for scope, name in names:
        held = await context.versions(scope, name)
        if not held:
            continue  # its last file was removed between the two questions
        newest = max(held, key=semver.sort_key)
        # Only the newest version's manifest is read: a package can have thousands.
        info = await context.component(scope, name, newest)
        manifest = (info.attributes.get(_MANIFEST) if info is not None else None) or {}
        description = manifest.get("description")
        found.append(
            documents.Found(
                name=f"@{scope}/{name}" if scope else name,
                version=newest,
                description=description if isinstance(description, str) else "",
                date=held[newest],
            )
        )
    return _answer(documents.search_results(found, total, utcnow()))
```

with

```python
async def _found(
    holders: Sequence[RepositoryContext], scope: str, name: str
) -> documents.Found | None:
    """What a search says about a package: what the first of `holders` to have it holds."""
    for holder in holders:
        held = await holder.versions(scope, name)
        if not held:
            continue
        newest = max(held, key=semver.sort_key)
        # Only the newest version's manifest is read: a package can have thousands.
        info = await holder.component(scope, name, newest)
        manifest = (info.attributes.get(_MANIFEST) if info is not None else None) or {}
        description = manifest.get("description")
        return documents.Found(
            name=f"@{scope}/{name}" if scope else name,
            version=newest,
            description=description if isinstance(description, str) else "",
            date=held[newest],
        )
    return None  # its last file was removed between the two questions


async def _search(
    context: RepositoryContext, request: Request, holders: Sequence[RepositoryContext]
) -> Response:
    """Packages that `holders` hold whose name or scope contains the text.

    `holders` is the repository itself, or for a group the repositories behind it.
    """

    def number(name: str, default: int, most: int) -> int:
        value = request.query_params.get(name, "")
        plain = value.isascii() and value.isdigit() and len(value) <= 9
        return min(int(value), most) if plain else default

    text = request.query_params.get("text", "").strip()[: paths.MAX_NAME_LENGTH]
    size = number("size", 20, _MAX_SEARCH_RESULTS)
    names, total = await context.package_names(
        text, limit=size, offset=number("from", 0, 10**9), within=holders
    )
    found = [await _found(holders, scope, name) for scope, name in names]
    listed = [entry for entry in found if entry is not None]
    return _answer(documents.search_results(listed, total, utcnow()))
```

Replace

```python
class NpmFormat(Format):
    name = "npm"
    # A group needs npm's own handling of package documents.
    types = frozenset({"hosted", "proxy"})
```

with

```python
# --- What a group serves -------------------------------------------------------------


async def _owners(
    leaves: Sequence[group.Leaf], package: str
) -> tuple[list[RepositoryContext], bool]:
    """The hosted repositories behind a group that hold a package.

    Returns those that are online, in order, and whether one that is offline holds it
    too. A package that a hosted repository holds is answered for by hosted
    repositories only: npm's names are not verified, so a public package of the same
    name must not add versions to it, nor stand in for it while its repository is
    offline.
    """
    scope, name = _coordinates(package)
    online, offline = [], False
    for leaf in leaves:
        member = leaf.context
        if member.repository.type != "hosted" or not await member.names(scope, [name]):
            continue
        if leaf.online:
            online.append(member)
        else:
            offline = True
    return online, offline


def _proxies(leaves: Sequence[group.Leaf]) -> list[RepositoryContext]:
    return [
        leaf.context for leaf in leaves if leaf.online and leaf.context.repository.type == "proxy"
    ]


async def _cached_by(members: Sequence[RepositoryContext], package: str) -> list[RepositoryContext]:
    """Those of `members` that have a package's document, fetching it where need be.

    A proxy that cannot answer is left out, never an error: the group answers from
    the others.
    """
    have = []
    for member in members:
        try:
            await proxy.ensure_cached(member, package)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            continue
        have.append(member)
    return have


async def _several(
    context: RepositoryContext,
    request: Request,
    package: str,
    have: Sequence[RepositoryContext],
    base: str,
) -> Response:
    """Answer from the documents of several proxies, merged.

    This is the one place a remote's document is parsed, so they are read only up to
    a limit on their size together, and only two merges run at once. A document that
    does not fit or cannot be read is left out. If that leaves fewer than two, one is
    served as it is.
    """
    await context.release()  # waiting for a turn needs no connection
    async with merging():
        read = []
        room = MERGE_LIMIT
        for member in have:
            stored = await member.stat(package)
            try:
                data = None if stored is None else await member.read(package, limit=room)
            except TooLarge:
                log.warning(
                    "document_too_large_to_merge",
                    repository=member.repository.name,
                    package=package,
                )
                continue
            if data is not None:
                read.append((member, data, stored.modified))
                room -= len(data)
        await context.release()
        merged = await off_loop(
            documents.merge_remote, package, [data for _, data, _ in read], base
        )
    for position, (member, _, _) in enumerate(read):
        if position not in merged.used:
            log.warning("document_unreadable", repository=member.repository.name, package=package)
    used = [read[position] for position in merged.used]
    if merged.data is None:
        source = used[0][0] if used else have[0]
        return await _streamed(source, request, package, base)
    rendered = documents.Rendered(
        data=merged.data, etag=merged.etag, modified=max(modified for _, _, modified in used)
    )
    return _as_document(context, request, package, rendered)


async def _group_document(context: RepositoryContext, request: Request, package: str) -> Response:
    leaves = await group.leaves(context)
    owners, offline = await _owners(leaves, package)
    # The links name the group, so every download comes back through it.
    base = await context.public_url(request)
    if owners:
        held = [
            (await _versions(owner, package), await _stored_tags(owner, package))
            for owner in owners
        ]
        await context.release()  # the work that follows needs no connection
        rendered = await off_loop(documents.render, package, *documents.combine(held), base)
        if rendered is None:
            raise _not_found()  # its last version was removed between the two questions
        return _as_document(context, request, package, rendered)
    if offline:
        raise _offline()
    have = await _cached_by(_proxies(leaves), package)
    if not have:
        raise _not_found()
    if len(have) == 1:
        return await _streamed(have[0], request, package, base)
    return await _several(context, request, package, have, base)


async def _group_tarball(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath, serve: Serve
) -> Response:
    """A tarball, from the same members that answer for its package's document."""
    leaves = await group.leaves(context)
    owners, offline = await _owners(leaves, parsed.package)
    if not owners and offline:
        raise _offline()
    path = paths.tarball_path(parsed.package, parsed.version)
    for member in owners or _proxies(leaves):
        try:
            return await serve(member, request, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    raise _not_found("No such file.")


async def _group_search(context: RepositoryContext, request: Request) -> Response:
    members = [leaf.context for leaf in await group.leaves(context) if leaf.online]
    # A hosted member's word about a package comes first, as it does in its document.
    members.sort(key=lambda member: member.repository.type != "hosted")
    return await _search(context, request, members)


class NpmFormat(Format):
    name = "npm"
```

Replace

```python
            return await _search(context, request)
        raise _not_found("Nothing is served at this address.")

    async def handle_proxy(
```

with

```python
            return await _search(context, request, [context])
        raise _not_found("Nothing is served at this address.")

    async def handle_proxy(
```

Replace

```python
        if parsed.kind == "search":
            return await _search(context, request)
        if parsed.kind in ("version", "dist_tags"):
            raise _hosted_only()
        raise _not_found("Nothing is served at this address.")
```

with

```python
        if parsed.kind == "search":
            return await _search(context, request, [context])
        if parsed.kind in ("version", "dist_tags"):
            raise _hosted_only()
        raise _not_found("Nothing is served at this address.")

    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        parsed = paths.classify(normalise_path(path))
        answered = await registry_endpoint(context, request, parsed)
        if answered is not None:
            return answered
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind == "document":
            return await _group_document(context, request, parsed.package)
        if parsed.kind == "tarball":
            return await _group_tarball(context, request, parsed, serve)
        if parsed.kind == "search":
            return await _group_search(context, request)
        if parsed.kind in ("version", "dist_tags"):
            raise _hosted_only()
        raise _not_found("Nothing is served at this address.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/npm/format.py backend/tests/repositories/npm/test_group.py
git commit -m "feat(npm): group repositories in which a public package cannot take a private name"
```

---

### Task 6: npm, pnpm and Yarn through a group; documentation

**Files:**
- Modify: `backend/tests/test_npm_client.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-08-npm-format-design.md`

**Interfaces:**
- Consumes: npm hosted, proxy and group repositories; `tests/containers.py` (`HTTP_PORT`, `PROJECT`, `call`); the `stack` and `administrator` fixtures.
- Produces: a Docker-marked test in which the three clients install through a group.

These tests run only with `pytest -m docker`. They need a Docker daemon and internet access: the backend container fetches from `https://registry.npmjs.org`.

- [ ] **Step 1: Write the real-client test**

The file is replaced. The two tests of plan 5a are unchanged; the helpers now take the repository to talk to, and a third test is added.

`backend/tests/test_npm_client.py`:

```python
"""npm's own clients against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: the
first time to pull the Node image, and every time for the proxy of registry.npmjs.org
that the last test installs through. Everything a client asks for comes from MegooArti.
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "node:22-slim"
NETWORK = f"{PROJECT}_default"
HOSTED = "npm-hosted"
PROXY = "npm-proxy"
GROUP = "npm-public"
# What a publishing account gets: everything on npm repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "publishes-and-unpublishes-npm-packages"
PLAIN = "megooarti-greeter"
SCOPED = "@megooarti/greeter"
# Published to the hosted repository and installed through the group.
OURS = "megooarti-grouped"
# A real public package with no dependencies, and the name of another one.
PUBLIC = "is-number"
TAKEN = "is-odd"


def inside(repository: str) -> str:
    """A repository's address as a container on the Compose network writes it in .npmrc."""
    return f"backend:8000/repository/{repository}/"


def package(name: str, version: str, **fields) -> dict[str, str]:
    """The files of a package whose only export says which version it is."""
    manifest = {"name": name, "version": version, "main": "index.js", **fields}
    return {
        "package.json": json.dumps(manifest, indent=2),
        "index.js": f'module.exports = () => "hello from {name}@{version}";\n',
    }


def write(
    directory: Path, projects: dict[str, dict[str, str]], token: str, repository: str = HOSTED
) -> Path:
    """A directory with one sub-directory for each project, and the clients' configuration."""
    directory.mkdir(parents=True)
    settings = [
        f"registry=http://{inside(repository)}",
        f"//{inside(repository)}:_authToken={token}",
        "update-notifier=false",
        "fund=false",
    ]
    (directory / "npmrc").write_text("\n".join(settings) + "\n", encoding="utf-8", newline="\n")
    for project, files in projects.items():
        for name, content in files.items():
            target = directory / project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
    return directory


def npm(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Node image, in a copy of `directory`, beside the stack.

    Every run is a new container, so every client starts with an empty cache.
    """
    # pnpm and Yarn read the same file as npm, from the home directory.
    setup = (
        "cp -r /src /work && cd /work && cp npmrc ~/.npmrc"
        " && export NPM_CONFIG_USERCONFIG=/work/npmrc"
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        IMAGE,
        "sh",
        "-c",
        f"{setup} && {script}",
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def request(
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    repository: str = HOSTED,
):
    """A request to a repository from outside: (status, parsed JSON body or None)."""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    sent = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{repository}/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(sent, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


def sign_in(repository: str = HOSTED) -> str:
    """A token, by the request `npm login` sends once it has asked for name and password."""
    credentials = {"_id": f"org.couchdb.user:{USERNAME}", "name": USERNAME, "password": PASSWORD}
    status, answer = request(
        "PUT", f"-/user/org.couchdb.user:{USERNAME}", body=credentials, repository=repository
    )
    assert status == 201, answer
    return answer["token"]


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted npm repository, a publishing account, and a token from signing in."""
    repository = {
        "name": HOSTED,
        "format": "npm",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    role = {"name": "npm-publishers", "permissions": ["repository:npm"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["npm-publishers"],
        "must_change_password": False,
    }
    for path, body in (("/repositories", repository), ("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer
    return sign_in()


def test_npm_publishes_installs_changes_and_unpublishes(token, tmp_path):
    projects = {
        "first": package(PLAIN, "1.0.0", description="Says hello"),
        "second": package(PLAIN, "1.1.0", description="Says hello, again"),
        "scoped": package(SCOPED, "2.0.0"),
        "consumer": {
            "package.json": json.dumps(
                {
                    "name": "consumer",
                    "version": "1.0.0",
                    "private": True,
                    "dependencies": {PLAIN: "1.0.0", SCOPED: "^2.0.0"},
                }
            ),
            "main.js": f'console.log(require("{PLAIN}")(), require("{SCOPED}")());\n',
        },
    }
    work = write(tmp_path / "npm", projects, token)

    # Who we are, by the token that signing in gave.
    who = npm(work, "npm whoami && npm ping")
    assert who.returncode == 0, said(who)
    assert who.stdout.splitlines()[0] == USERNAME

    # Publish two versions of one package and one scoped package.
    published = npm(
        work,
        "(cd first && npm publish) && (cd scoped && npm publish)"
        " && (cd second && npm publish --tag next)",
    )
    assert published.returncode == 0, said(published)
    again = npm(work, "cd first && npm publish")
    assert again.returncode != 0, "a version was published twice despite disable_redeploy"

    # What the registry says about them.
    viewed = npm(work, f"npm view {PLAIN} versions dist-tags description --json")
    assert viewed.returncode == 0, said(viewed)
    about = json.loads(viewed.stdout)
    assert about["versions"] == ["1.0.0", "1.1.0"]
    assert about["dist-tags"] == {"latest": "1.0.0", "next": "1.1.0"}
    assert about["description"] == "Says hello"
    found = npm(work, "npm search megooarti --json")
    assert found.returncode == 0, said(found)
    assert {entry["name"] for entry in json.loads(found.stdout)} == {PLAIN, SCOPED}

    # Dist-tags and deprecation.
    changed = npm(
        work,
        f"npm dist-tag add {PLAIN}@1.1.0 stable && npm dist-tag ls {PLAIN}"
        f' && npm deprecate {PLAIN}@1.0.0 "use 1.1.0"',
    )
    assert changed.returncode == 0, said(changed)
    assert "stable: 1.1.0" in changed.stdout

    # Install both into a project, from an empty cache, and run them.
    installed = npm(work, "cd consumer && npm install && node main.js")
    assert installed.returncode == 0, said(installed)
    assert f"hello from {PLAIN}@1.0.0 hello from {SCOPED}@2.0.0" in installed.stdout
    assert "use 1.1.0" in installed.stderr  # npm warns that the version is deprecated

    # Remove one version, then a whole package.
    removed = npm(work, f"npm unpublish {PLAIN}@1.1.0 && npm unpublish {SCOPED} --force")
    assert removed.returncode == 0, said(removed)
    status, document = request("GET", PLAIN, token)
    assert (status, list(document["versions"])) == (200, ["1.0.0"])
    assert document["dist-tags"] == {"latest": "1.0.0"}
    assert request("GET", SCOPED.replace("/", "%2f"), token)[0] == 404

    # Signing out revokes the token npm was using.
    out = npm(work, "npm logout")
    assert out.returncode == 0, said(out)
    assert request("GET", "-/whoami", token)[0] == 401


def test_npm_login_itself_gets_a_token_that_works(token, tmp_path):
    """The `npm login` command, typed into a terminal, with a revoked token still saved."""
    work = write(tmp_path / "login", {}, token="mga_revoked-long-ago")
    # npm reads the answers from a terminal, so `script` gives it one, and the answers
    # are typed with pauses, as a person would.
    typing = f"(sleep 3; echo {USERNAME}; sleep 2; echo {PASSWORD}; sleep 5)"
    login = 'script --quiet --return --command "npm login --auth-type=legacy" /dev/null'

    signed_in = npm(work, f"{typing} | {login} && npm whoami")

    assert signed_in.returncode == 0, said(signed_in)
    assert signed_in.stdout.rstrip().endswith(USERNAME)


@pytest.fixture(scope="module")
def group_token(token, administrator) -> str:
    """A proxy of the public registry and a group of the hosted repository and it.

    Returns a token from signing in at the group, which is where developers point npm.
    """
    proxy = {
        "name": PROXY,
        "format": "npm",
        "type": "proxy",
        "proxy": {"remote_url": "https://registry.npmjs.org"},
    }
    public = {
        "name": GROUP,
        "format": "npm",
        "type": "group",
        "group": {"members": [HOSTED, PROXY]},
    }
    for body in (proxy, public):
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    return sign_in(GROUP)


def test_npm_pnpm_and_yarn_install_through_a_group(group_token, tmp_path):
    consumer = {
        "package.json": json.dumps(
            {
                "name": "consumer",
                "version": "1.0.0",
                "private": True,
                "dependencies": {OURS: "1.0.0", PUBLIC: "7.0.0"},
            }
        ),
        "main.js": f'console.log(require("{OURS}")(), require("{PUBLIC}")(5));\n',
    }
    # Our own package, and our own package under a name the public registry has too.
    publishing = write(
        tmp_path / "publish",
        {"ours": package(OURS, "1.0.0"), "taken": package(TAKEN, "99.0.0")},
        group_token,
    )
    published = npm(publishing, "(cd ours && npm publish) && (cd taken && npm publish)")
    assert published.returncode == 0, said(published)

    # What the group says: the public package from the proxy, with its links here, and
    # under the name we host only what we host.
    status, public = request("GET", PUBLIC, group_token, repository=GROUP)
    assert status == 200
    assert "7.0.0" in public["versions"] and len(public["versions"]) > 5
    assert public["versions"]["7.0.0"]["dist"]["tarball"] == (
        f"http://127.0.0.1:{HTTP_PORT}/repository/{GROUP}/{PUBLIC}/-/{PUBLIC}-7.0.0.tgz"
    )
    assert request("HEAD", PUBLIC, group_token, repository=GROUP)[0] == 200
    status, taken = request("GET", TAKEN, group_token, repository=GROUP)
    assert (status, list(taken["versions"])) == (200, ["99.0.0"])
    status, upstream = request("GET", TAKEN, group_token, repository=PROXY)
    assert status == 200 and "99.0.0" not in upstream["versions"]

    # Each client installs the project from an empty cache, through the group.
    work = write(tmp_path / "install", {"consumer": consumer}, group_token, GROUP)
    expected = f"hello from {OURS}@1.0.0 true"
    clients = {
        "npm": "cd consumer && npm install && node main.js",
        # pnpm is itself installed through the group: a large package from the proxy.
        "pnpm": "npm install --global pnpm@9 && cd consumer && pnpm install && node main.js",
        # Yarn 1 sends a token for an unscoped package only when told to always send it.
        "yarn": "echo always-auth=true >> ~/.npmrc"
        " && cd consumer && yarn install --non-interactive && node main.js",
    }
    for client, script in clients.items():
        installed = npm(work, script)
        assert installed.returncode == 0, f"{client}: {said(installed)}"
        assert expected in installed.stdout, f"{client}: {said(installed)}"

    # What was installed came through the proxy, and is cached there.
    status, found = request("GET", f"-/v1/search?text={PUBLIC}", group_token, repository=PROXY)
    assert status == 200
    cached = {entry["package"]["name"]: entry["package"]["version"] for entry in found["objects"]}
    assert cached.get(PUBLIC) == "7.0.0"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_npm_client.py -q`
Expected: 3 passed. This builds the image from the working tree, so it is the first run of the three clients against this plan's code. If a client fails, the assertion message carries the end of its output.

- [ ] **Step 3: Document npm proxies and groups**

In `README.md`:

Replace

```markdown
`raw` (arbitrary files by path), `maven` and `npm` (hosted repositories only, for now).
```

with

```markdown
`raw` (arbitrary files by path), `maven` and `npm`.
```

After

````markdown
In a pipeline, skip `npm login` and give npm a token directly:

```ini
registry=https://repo.example.com/repository/npm-hosted/
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```
````

add

````markdown
A proxy caches the public registry, and a group puts your own packages and the public
ones behind one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-proxy", "format": "npm", "type": "proxy",
  "proxy": {"remote_url": "https://registry.npmjs.org"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-public", "format": "npm", "type": "group",
  "group": {"members": ["npm-hosted", "npm-proxy"]}
}' http://localhost:8000/api/v1/repositories
```

Install through the group and publish to the hosted repository. In `.npmrc`:

```ini
registry=https://repo.example.com/repository/npm-public/
//repo.example.com/repository/npm-public/:_authToken=${NPM_TOKEN}
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```

and in the `package.json` of each package you publish:

```json
"publishConfig": {"registry": "https://repo.example.com/repository/npm-hosted/"}
```
````

Replace

```markdown
- **Search** (`npm search`) finds the packages this repository holds, by name.
- `npm audit` is not supported; installs do not need it.
- Proxy and group npm repositories are not available yet.
```

with

```markdown
- **Search** (`npm search`) finds the packages a repository holds, by name: at a proxy
  the packages it has cached, at a group those of all its members.
- `npm audit` is not supported; installs do not need it.
- **A proxy** caches what it fetches. It serves the remote's package document with the
  tarball links pointed at MegooArti, so tarballs are downloaded through it and cached
  too. A package document is checked again with the remote after
  `metadata_max_age_minutes`; a tarball after `content_max_age_minutes`.
- **A group protects the names you publish.** If a hosted member holds a package, only
  hosted members answer for it, for its document and its tarballs alike. A package on
  the public registry with the same name as one of yours cannot add a version to it or
  stand in for one (the dependency-confusion attack). While that hosted repository is
  offline the group answers `503` for the package; it does not fall back to the public
  one. To use your own build of a public package beside the public versions, publish
  it under a scope.
- **A group merges** what its hosted members hold of a package, the earlier member
  winning a version or a dist-tag both have. A package only proxies have is served
  from the proxy that has it. If several proxies have it their documents are merged,
  up to 16 MiB together; past that the first one's is served alone.
- **Signing in works at every npm repository**, so `npm login` can point at the group.
  `npm publish`, `npm dist-tag`, `npm deprecate` and `npm unpublish` work at a hosted
  repository only.
- **Set the base URL** under `/api/v1/settings` when clients reach MegooArti through a
  reverse proxy. Tarball links in package documents are built on it; without it they
  follow the address of each request.
- **Clients.** Installs are tested with npm, pnpm and Yarn 1. Yarn 1 sends a token for
  an unscoped package only if `.npmrc` also says `always-auth=true`.

Reading through a group needs `read` on the group only, for example
`repository:npm:npm-public:read`.
```

- [ ] **Step 4: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-08-npm-format-design.md`:

Replace

```markdown
| D2 | In a group, if any hosted member has a package, only hosted members contribute to that package's document. | npm's namespace is flat and unverified. Merging a proxy's versions into a private name is the dependency-confusion attack. |
```

with

```markdown
| D2 | In a group, if any hosted member has a package, only hosted members answer for that package: its document and its tarballs. A hosted member that is offline still counts. | npm's namespace is flat and unverified. Merging a proxy's versions into a private name is the dependency-confusion attack, and so is serving a proxy's tarball for a version of it. |
```

After

```markdown
- **A stored file served through a transformation.** The context can stream a stored file through a function that rewrites it chunk by chunk. The response has the same protective headers as any content, an `ETag` derived from the file's hash and a name for the transformation, no `Content-Length`, and no ranges. Conditional requests and `HEAD` work.
```

add

```markdown
- **Every repository behind a group.** The group engine can list the hosted and proxy repositories behind a group, through nested groups, in the order they are tried, each marked online or offline. A format that answers from all of them at once uses it.
- **Package names across repositories.** The search for package names can cover several repositories and lists a package once.
```

Replace

```markdown
A package matches if `text` appears in its name or scope. `size` is at most 250. A hosted repository takes the description from the manifest; a proxy has none to give. A group returns its members' results in order, without duplicates.
```

with

```markdown
A package matches if `text` appears in its name or scope. `size` is at most 250. A hosted repository takes the description from the manifest; a proxy has none to give, and lists the packages it has cached a tarball of. A group lists every package its online members hold, once, ordered by name; a package's version and description come from a hosted member if one holds it.
```

Replace

```markdown
| Tarball | The generic group behaviour: the first member that has it |
| Package document | Below |
```

with

```markdown
| Tarball | The first member that has it, among the members that answer for its package (below) |
| Package document | Below |
```

Replace

```markdown
**Who has the package.** Every online member is asked, in order: a hosted member has it if it holds a version; a proxy has it if `ensure_cached` succeeds; a group member answers for its own members. A member that cannot answer is left out, as in the Maven design.

**The document.**

- **A hosted member has it (D2):** the documents of the hosted members that have it are merged, and proxies are not asked to contribute. Versions are the union, the earlier member winning a version both hold. Dist-tags are the union, the earlier member winning a tag, and `latest` is recomputed if the version it names is not in the result.
- **Only one proxy has it:** that proxy's cached document is streamed through the link rewriter, with the group's address in the links.
- **Several proxies have it:** their documents are parsed and merged in the same way, each up to 16 MiB. One that is larger is left out and logged; if that leaves a single document, it is streamed as above.
- **Nobody has it:** `404`.

Tarball links always name the group, so every download goes through the group, where the first member that has the file answers. Because the earlier member wins a version in the document, that is the same member whose manifest the client was given.
```

with

```markdown
**Who answers for a package.** The repositories behind the group are taken in the order they are tried, with a nested group replaced by its own members. A hosted repository has the package if it holds a version of it; a proxy has it if `ensure_cached` succeeds for its document. A proxy that is offline or cannot answer is left out, as in the Maven design.

- **A hosted repository has it (D2):** only hosted repositories answer, and proxies are not asked. If every hosted repository that has it is offline, the answer is `503 repository_offline`: the remote's package of the same name must not stand in for it.
- **No hosted repository has it:** the online proxies answer.

**The document.**

- **From hosted repositories:** the documents of those that have it are merged. Versions are the union, the earlier one winning a version both hold. Dist-tags are the union, the earlier one winning a tag, and `latest` is recomputed if the version it names is not in the result.
- **From one proxy:** that proxy's cached document is streamed through the link rewriter, with the group's address in the links.
- **From several proxies:** their documents are parsed and merged in the same way, up to 16 MiB together and two merges at a time. One that does not fit or cannot be read is left out and logged; if that leaves fewer than two, one document is streamed as above.
- **Nobody has it:** `404`.

Tarball links always name the group, so every download goes through the group. A tarball is served by the first repository that has it among those that answer for its package, so a proxy listed before a hosted repository cannot serve its own file for a version the hosted repository published.
```

Replace

```markdown
  - *Plan 5b:* npm, pnpm and Yarn each install a project, from an empty cache, through a group of the hosted repository and a proxy of registry.npmjs.org. The project depends on the package published in 5a and on one small public package.
```

with

```markdown
  - *Plan 5b:* npm, pnpm and Yarn 1 each install a project, from an empty cache, through a group of the hosted repository and a proxy of registry.npmjs.org. The project depends on a package published to the hosted repository and on one small public package. A package published under a name the public registry also has is listed through the group with our version only.
```

After

```markdown
| A team needs its own build of a public package alongside the public versions (D2 hides them). | Publish it under a scope. A per-group switch can be added if this proves common. |
```

add

```markdown
| Taking a hosted repository offline makes the packages it holds unavailable through its groups (`503`), where a Maven group would answer from the other members. | That is D2 holding while the repository is away. The message says which state causes it. |
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

Run: `uv run pytest -m docker -q`
Expected: 14 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_npm_client.py README.md docs/superpowers/specs/2026-10-08-npm-format-design.md
git commit -m "test(npm): install through a group with npm, pnpm and Yarn; document npm proxies and groups"
```
