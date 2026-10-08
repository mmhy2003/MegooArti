# PyPI Proxy and Group Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pip, uv and Poetry install through one address that serves a team's own Python packages and a cache of pypi.org, and a public project can never add to or replace a project the team uploads.

**Architecture:** A proxy caches the remote's page for a project as a file and never serves it: the links are read out of it as it streams, and the page sent is written from them, pointing at MegooArti. A file is fetched from the address the remote's page gives for it, checked against the hash on that page, with the remote's credential kept to the remote's own origin and internal addresses refused. A group looks at every hosted and proxy repository behind it at once: if a hosted one holds the project, hosted ones alone answer for its page and its files; otherwise the proxies do, their pages read one after another into a single page. The core gains fetching from a given address, a response made from a stream, and the rule about who holds a name, moved out of the npm format.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, httpx, the standard library's `re` and `html`, pytest + pytest-asyncio, Docker (the `python:3.13-slim` image, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-08-pypi-format-design.md](../specs/2026-10-08-pypi-format-design.md), sections 4.2, 8, 9 and the plan 6b part of 12. Business requirements: [docs/BRD.md](../../BRD.md) FMT-3 (proxy, group; pip, uv and Poetry), REP-12, NFR-1. Task 5 amends the spec where this plan settles something the spec left open.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `ensure_cached` takes `source=Source(url, digests)`. With it, the address is the one given, the remote's credential is sent only if the address has the remote's scheme, host and port, an address on a loopback, link-local or private network is refused unless the remote is at that host, and content that does not match `digests` is discarded and answered `502`. | D8 of the spec, enforced in the one place that fetches. A wrong file is not counted towards blocking the remote: it is one bad file, not a failing remote. |
| P2 | A hash for an algorithm the blob store does not compute is a mismatch, not a pass. | A check that cannot be made must not look like one that passed. The PyPI format only passes on hashes that can be checked. |
| P3 | The context gains `open(stored)` and `respond_stream(request, body, etag=...)`. The caller makes the `ETag` from what the content is built from, so a request that already has it is answered without anything being read. | One page is made from several stored files, none of which may be held in memory. |
| P4 | `group.owners` and `group.proxies` replace the npm format's private helpers, and npm uses them. | D1 of the PyPI design is D2 of the npm design: one piece of code. |
| P5 | The reader takes links from the opening `<a ...>` tag alone, and settles one tag before looking at anything after it. An unfinished tag is held back, up to 16 KiB. | The text of a link adds nothing to its address. Settling tags in order makes what is read independent of the pieces the page arrives in, which the npm rewriter's review showed is easy to get wrong. |
| P6 | Reading a page runs on two worker threads of the PyPI format's own. | Measured on pypi.org's pages: about 0.15 s for a 2 MiB page with four thousand links. That is too long for the event loop. |
| P7 | A proxy's page lists a file under the version read from its name, and serves a file only at that address. | One address for a file, as on a hosted repository since plan 6a's review. |
| P8 | A cached file is served without `ensure_cached`, so it is never revalidated, whatever `content_max_age_minutes` says. | A file on an index does not change once published, and revalidating would need its page read again. |
| P9 | A `HEAD` or a range request for a file that is not cached fetches the whole file first. | The generic `HEAD` asks the remote at an address made from the path, which a PyPI file does not have. uv reads ranges of wheels only when there is no metadata file. |
| P10 | Metadata files (PEP 658) are files like any other: fetched from the file's address with `.metadata` added, checked against the hash in the link's attribute if it gives one, and cached. Both attribute names are written if the remote has either. | pip before 23.2 reads `data-dist-info-metadata`, newer clients `data-core-metadata`. |
| P11 | The remote address is the index's root, or the index itself if it ends in `/simple` or `/+simple`. | Nexus users enter `https://pypi.org`; pip users know the address ending in `/simple`; devpi's ends in `/+simple`. |
| P12 | In a group, the page from hosted repositories is built in memory as on a hosted repository; the page from proxies is written as it streams, its `ETag` made from the hashes of the proxies' cached pages. | Hosted pages are one query. Proxies' pages are megabytes. |
| P13 | Between Tasks 3 and 4 the format offers `hosted` and `proxy`. Task 4 adds `group`. | On the generic group engine a group would serve the first member's page only. |
| P14 | The real-client test installs pip's, uv's and Poetry's own packages through the group, and has Poetry publish a package it built. | The tools' dependency trees are several dozen real projects through the proxy. The README of plan 6a says `poetry publish` works; this runs it. |
| P15 | Changed after review. A link whose address a URL parser refuses is left out, where it raised and took the page with it. A cached file whose cache was invalidated is checked against the page again (P8 made that impossible), and a stale file that is not the one the index describes is fetched whole, without asking whether it changed. An internal address is recognised in every notation a resolver reads as one, and by whether it is globally reachable, not by three address classes. | One bad link broke a project and a group's merged page. A file replaced at the remote could never be replaced here. `http://2130706433/` and `http://localhost./` passed the guard of P1. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; settings prefixed `MEGOOARTI_` and listed in `README.md`; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; only the security package reads `Principal.patterns`; content responses always carry `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; formats do not commit, the route does; a token or password is never logged; remote secrets are never returned or logged; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration, no setting and no dependency.**
- **Only `pypi/format.py` touches the repository context.** `pypi/names.py`, `pypi/pages.py` and `pypi/upload.py` are pure.
- **A remote's page is never served and never held in memory.** Nothing a remote wrote reaches a client but file names, hashes, and the values of `data-requires-python`, `data-yanked` and the metadata attributes, each escaped.
- **D8 applies to every fetch from an address a remote's content names:** the credential stays with the remote's origin, internal addresses are refused unless the remote is there, and the content must match the hash given.
- **D1 applies to every answer about a project** a group gives: its page, its files and their metadata files. An offline hosted repository still counts as holding its projects.
- **Reading through a group needs `read` on the group only.**
- **Everything that changes a repository answers `405` on a proxy and on a group.**
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **Where a remote's page can send the proxy.** A file on another host; an address on a loopback, link-local or private network; an address that is not HTTP; the remote's credential on a request to another host, port or scheme; a file that does not match the hash the page gives. Only the first is fetched, and never with the credential (Tasks 1, 3).
2. **A public project with the name of a private one**, by every way in: the page; a file only the remote has, and its metadata file; a file both have, with the proxy listed first; the hosted repository offline; the hosted repository behind a nested group that is offline. None may reach the remote's project (Task 4).
3. **What a remote writes, on the page a client gets.** Scripts, event handlers, links to other things, attribute values written to break out of the attribute. Only what is read from a link reaches the page, escaped (Tasks 2, 3).
4. **A page in awkward pieces:** cut at any byte; larger than one piece; a link inside another tag's attribute; a tag that never ends; a `>` inside an attribute; text that is not UTF-8 (Tasks 2, 3).
5. **A remote that fails:** down, with and without a cached page or file; a project it does not have; one of two proxies failing behind a group (Tasks 3, 4).

---

### Task 1: Core: fetching from a given address, a response made from a stream, who holds a name

**Files:**
- Modify: `backend/src/megooarti/repositories/remote.py`
- Modify: `backend/src/megooarti/repositories/proxy.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/repositories/group.py`
- Modify: `backend/src/megooarti/repositories/npm/format.py`
- Test: `backend/tests/repositories/test_proxy.py`
- Test: `backend/tests/repositories/test_remote.py`
- Test: `backend/tests/repositories/test_content_reads.py`
- Test: `backend/tests/repositories/test_group.py`

**Interfaces:**
- Consumes: `proxy.ensure_cached`, `proxy._refresh`, `proxy._target`, `proxy._fail`, `remote._is_internal`, `remote.Failed`, `serving.plan_stream`, `content.Stored`, `group.Leaf`, `group.leaves`.
- Produces:
  - `remote.same_origin(first: str, second: str) -> bool` and `remote.refusal(remote_url: str, address: str) -> str | None`.
  - `proxy.Source(url: str, digests: Mapping[str, str] = {})` and `await proxy.ensure_cached(context, path, *, source: Source | None = None)`.
  - `context.open(stored: Stored) -> AsyncIterator[bytes]`.
  - `await context.respond_stream(request, body: Callable[[], AsyncIterator[bytes]], *, etag: str, content_type: str, filename: str, last_modified: datetime) -> Response`. Commits before the body is sent. `body` is called only if the body is sent.
  - `await group.owners(found: Sequence[Leaf], namespace: str, name: str) -> tuple[list[RepositoryContext], bool]` and `group.proxies(found: Sequence[Leaf]) -> list[RepositoryContext]`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/test_proxy.py`:

Replace

```python
from megooarti.repositories import formats, proxy
```

with

```python
from megooarti.repositories import formats, proxy, service
```

Add to the end of `backend/tests/repositories/test_proxy.py`:

```python
ELSEWHERE = "http://files.test/store/ab/a.bin"  # what a remote's index says, on another host
DIGESTS = {"sha256": hashlib.sha256(CONTENT).hexdigest(), "md5": hashlib.md5(CONTENT).hexdigest()}


async def asked(remote_seen) -> list[tuple[str, str]]:
    return [(seen["host"], seen["path"]) for seen in remote_seen.requests]


async def test_a_file_is_fetched_from_the_address_given_for_it(
    app, context_for, mirror, fake_remote
):
    fake_remote.files["store/ab/a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)
    source = proxy.Source(ELSEWHERE, DIGESTS)

    await proxy.ensure_cached(context, "lib/a.bin", source=source)
    await proxy.ensure_cached(context, "lib/a.bin", source=source)

    assert await context.read("lib/a.bin", limit=1000) == CONTENT
    assert await asked(fake_remote) == [("files.test", "/store/ab/a.bin")]


async def test_a_file_that_does_not_match_its_hash_is_not_kept(
    app, context_for, mirror, fake_remote, db, settings
):
    fake_remote.files["store/ab/a.bin"] = b"not the file the index describes"
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    for _ in range(6):  # more often than a failing remote is allowed before it is blocked
        with pytest.raises(ApiError) as refused:
            await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(ELSEWHERE, DIGESTS))

    assert (refused.value.status_code, refused.value.code) == (502, "remote_unavailable")
    assert "hash" in refused.value.message
    assert await count(db, Asset) == 0
    store = settings.data_dir / "blobs" / "default"
    assert not [path for path in store.rglob("*") if path.is_file()]
    state = await db.scalar(select(ProxyState))
    assert "hash" in state.last_error
    assert state.blocked_until is None  # one wrong file does not block the remote


async def test_an_algorithm_that_cannot_be_checked_is_a_mismatch(
    app, context_for, mirror, fake_remote
):
    fake_remote.files["store/ab/a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    with pytest.raises(ApiError) as refused:
        await proxy.ensure_cached(
            context, "lib/a.bin", source=proxy.Source(ELSEWHERE, {"blake2b": "0" * 64})
        )

    assert refused.value.status_code == 502


async def test_the_remotes_credential_stays_with_the_remote(
    admin_client, app, context_for, db, fake_remote
):
    for path in ("files/lib/a.bin", "store/ab/a.bin", "other/b.bin"):
        fake_remote.files[path] = CONTENT
    private = {
        "name": "private",
        "format": "raw",
        "type": "proxy",
        "proxy": {
            "remote_url": "http://remote.test/files",
            "remote_auth": {"type": "basic", "username": "robot", "secret": "s3cret"},
        },
    }
    await admin_client.post(REPOSITORIES, json=private)
    repository = await service.get_repository(db, "private")
    context = await context_for(repository, None, outbound=lambda: app.state.http)

    await proxy.ensure_cached(context, "lib/a.bin")
    await proxy.ensure_cached(context, "one", source=proxy.Source(ELSEWHERE))
    await proxy.ensure_cached(context, "two", source=proxy.Source("http://remote.test/other/b.bin"))
    await proxy.ensure_cached(
        context, "three", source=proxy.Source("http://remote.test:8080/other/b.bin")
    )
    await proxy.ensure_cached(
        context, "four", source=proxy.Source("https://remote.test/other/b.bin")
    )

    sent = [
        (seen["host"], seen["path"], "authorization" in seen["headers"])
        for seen in fake_remote.requests
    ]
    assert sent == [
        ("remote.test", "/files/lib/a.bin", True),
        ("files.test", "/store/ab/a.bin", False),  # another host
        ("remote.test", "/other/b.bin", True),  # the remote's own origin
        ("remote.test", "/other/b.bin", False),  # another port
        ("remote.test", "/other/b.bin", False),  # another scheme
    ]


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1/a.bin",
        "http://localhost:8000/a.bin",
        "http://LOCALHOST/a.bin",
        "http://10.0.0.5/a.bin",
        "http://192.168.1.1/a.bin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/a.bin",
        "ftp://files.test/a.bin",
        "file:///etc/passwd",
        "//files.test/a.bin",
        "/store/ab/a.bin",
        "",
    ],
)
async def test_an_address_a_remote_must_not_send_us_to_is_refused(
    app, context_for, mirror, fake_remote, db, address
):
    fake_remote.files["a.bin"] = CONTENT
    context = await context_for(mirror, None, outbound=lambda: app.state.http)

    with pytest.raises(ApiError) as refused:
        await proxy.ensure_cached(context, "lib/a.bin", source=proxy.Source(address))

    assert (refused.value.status_code, refused.value.code) == (502, "remote_unavailable")
    assert fake_remote.requests == []
    assert await count(db, Asset) == 0


async def test_a_remote_on_an_internal_network_may_name_its_own_host(
    admin_client, app, context_for, db, fake_remote
):
    fake_remote.files["elsewhere/a.bin"] = CONTENT
    inside = {
        "name": "inside",
        "format": "raw",
        "type": "proxy",
        "proxy": {"remote_url": "http://10.1.2.3/files"},
    }
    await admin_client.post(REPOSITORIES, json=inside)
    repository = await service.get_repository(db, "inside")
    context = await context_for(repository, None, outbound=lambda: app.state.http)

    await proxy.ensure_cached(
        context, "a.bin", source=proxy.Source("http://10.1.2.3/elsewhere/a.bin")
    )
    with pytest.raises(ApiError) as refused:
        await proxy.ensure_cached(context, "b.bin", source=proxy.Source("http://10.9.9.9/b.bin"))

    assert await context.read("a.bin", limit=1000) == CONTENT
    assert refused.value.status_code == 502
    assert await asked(fake_remote) == [("10.1.2.3", "/elsewhere/a.bin")]
```

Add to the end of `backend/tests/repositories/test_remote.py`:

```python
@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("https://pypi.org", "https://pypi.org/simple/x/", True),
        ("https://pypi.org:443/a", "https://PyPI.org/b", True),
        ("http://remote.test", "http://remote.test:80/x", True),
        ("https://pypi.org", "https://files.pythonhosted.org/x", False),
        ("https://pypi.org", "http://pypi.org/x", False),
        ("https://pypi.org", "https://pypi.org:8443/x", False),
        ("https://pypi.org", "https://pypi.org.evil.example/x", False),
        ("https://pypi.org", "not an address", False),
    ],
)
def test_two_addresses_have_the_same_origin(first, second, same):
    assert remote.same_origin(first, second) is same
```

In `backend/tests/repositories/test_content_reads.py`:

Before

```python
async def sent(response) -> bytes:
```

add

```python
async def letters():
    for letter in (b"a", b"b", b"c"):
        yield letter


async def test_a_stored_file_can_be_read_as_a_stream(context):
    await context.put("notes/big.txt", body(b"0123456789" * 200_000))
    stored = await context.stat("notes/big.txt")

    pieces = [piece async for piece in context.open(stored)]

    assert b"".join(pieces) == b"0123456789" * 200_000
    assert len(pieces) > 1  # never one piece of two megabytes


def streamed(context, incoming: Request, etag: str = "known"):
    return context.respond_stream(
        incoming,
        letters,
        etag=etag,
        content_type="text/html; charset=utf-8",
        filename="index.html",
        last_modified=WHEN,
    )


async def test_a_stream_is_answered_like_content_without_a_length(context):
    response = await streamed(context, request())

    assert (response.status_code, await sent(response)) == (200, b"abc")
    assert response.headers["ETag"] == '"known"'
    assert response.headers["Content-Type"] == "text/html; charset=utf-8"
    assert response.headers["Last-Modified"] == "Wed, 04 Mar 2026 05:06:07 GMT"
    assert response.headers["Accept-Ranges"] == "none"
    assert "content-length" not in response.headers
    assert response.headers["Content-Disposition"].startswith('attachment; filename="index.html"')
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "sandbox"


async def test_a_stream_is_not_started_when_it_is_not_sent(context, db):
    started = []

    def body_of_the_answer():
        started.append(True)
        return letters()

    def answer(incoming: Request):
        return context.respond_stream(
            incoming,
            body_of_the_answer,
            etag="known",
            content_type="text/plain",
            filename="x.txt",
            last_modified=WHEN,
        )

    head = await answer(request("HEAD"))
    unchanged = await answer(request(if_none_match='"known"'))
    ranged = await answer(request(range="bytes=0-0"))

    assert (head.status_code, await sent(head)) == (200, b"")
    assert "content-length" not in head.headers
    assert (unchanged.status_code, unchanged.body) == (304, b"")
    assert started == [True]  # only for the one that sends it
    assert (ranged.status_code, await sent(ranged)) == (200, b"abc")
    assert db.in_transaction() is False  # the connection is given back before the body
```

Add to the end of `backend/tests/repositories/test_group.py`:

```python
async def test_owners_are_the_hosted_repositories_that_hold_a_package(
    client, root, db, everything, mirror, context_for
):
    await put(client, root, "one", b"from one")
    await put(client, root, "two", b"from two")
    mixed = await create(db, "mixed", "group", group={"members": ["mirror", "one", "two"]})
    context = await context_for(mixed, None)

    behind = await group.leaves(context)
    online, offline = await group.owners(behind, "docs", "a.txt")
    nobody = await group.owners(behind, "docs", "another.txt")

    assert ([member.repository.name for member in online], offline) == (["one", "two"], False)
    assert nobody == ([], False)
    assert [member.repository.name for member in group.proxies(behind)] == ["mirror"]


async def test_an_offline_repository_still_holds_what_it_holds(
    client, root, db, everything, mirror, context_for
):
    await put(client, root, "one", b"from one")
    mixed = await create(db, "mixed", "group", group={"members": ["one", "mirror", "two"]})
    for name in ("one", "mirror"):
        repository = await service.get_repository(db, name)
        repository.online = False
    await db.commit()
    context = await context_for(mixed, None)

    behind = await group.leaves(context)
    online, offline = await group.owners(behind, "docs", "a.txt")

    assert (online, offline) == ([], True)
    assert group.proxies(behind) == []  # an offline proxy answers nothing
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_proxy.py tests/repositories/test_remote.py tests/repositories/test_content_reads.py tests/repositories/test_group.py -q`
Expected: 30 failures. `module 'megooarti.repositories.proxy' has no attribute 'Source'`, `... 'remote' has no attribute 'same_origin'`, `'RepositoryContext' object has no attribute 'open'` and `'respond_stream'`, `module 'megooarti.repositories.group' has no attribute 'owners'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/remote.py`:

Before

```python
def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
```

add

```python
def _origin(address: httpx.URL) -> tuple[str, str, int | None]:
    port = address.port or {"http": 80, "https": 443}.get(address.scheme)
    return address.scheme, address.host.lower(), port


def same_origin(first: str, second: str) -> bool:
    """Whether two addresses have the same scheme, host and port."""
    try:
        return _origin(httpx.URL(first)) == _origin(httpx.URL(second))
    except httpx.InvalidURL:
        return False


def refusal(remote_url: str, address: str) -> str | None:
    """Why an address that a remote's own content points at is not fetched, or None.

    A page a remote serves can name any address. One on a loopback, link-local or
    private network is refused unless the remote itself is at that host: the remote
    must not be able to make this server read from the network it is on.
    """
    try:
        target, configured = httpx.URL(address), httpx.URL(remote_url)
    except httpx.InvalidURL:
        return "it points at an address that cannot be read"
    if target.scheme not in ("http", "https") or not target.host:
        return "it points at an address that is not HTTP"
    if _is_internal(target.host) and target.host.lower() != configured.host.lower():
        return "it points at an internal address"
    return None
```

In `backend/src/megooarti/repositories/proxy.py`:

Before

```python
from datetime import datetime, timedelta
from typing import Any
```

add

```python
from collections.abc import Mapping
from dataclasses import dataclass, field
```

Before

```python
def _not_found() -> ApiError:
    return ApiError(404, "not_found", "No such file.")
```

add

```python
@dataclass(frozen=True)
class Source:
    """Where a path is found when the remote's own content says so, not the path.

    A PyPI index, for one, names the address of each of its files, often on another
    host, and the hash each must have. `digests` maps an algorithm the blob store
    computes to lower-case hex.
    """

    url: str
    digests: Mapping[str, str] = field(default_factory=dict)
```

Replace

```python
async def _target(context: RepositoryContext, path: str) -> tuple[str, str | None]:
    """The remote URL for a path and the Authorization header to send with it."""
    settings = context.repository.config["proxy"]
    try:
```

with

```python
async def _target(
    context: RepositoryContext, path: str, source: Source | None = None
) -> tuple[str, str | None]:
    """The remote URL for a path and the Authorization header to send with it."""
    settings = context.repository.config["proxy"]
    if source is not None:
        refused = remote.refusal(settings["remote_url"], source.url)
        if refused is not None:
            failed = remote.Failed(f"its index names a file's address, and {refused}", False)
            raise _unavailable(await _fail(context, path, failed))
        if not remote.same_origin(settings["remote_url"], source.url):
            # The credential is the remote's. Another host named by its content gets none.
            return source.url, None
    try:
```

Replace

```python
        raise _unavailable(await _fail(context, path, unreadable)) from None
    return context.format.remote_url(settings["remote_url"], path), credential
```

with

```python
        raise _unavailable(await _fail(context, path, unreadable)) from None
    if source is not None:
        return source.url, credential
    return context.format.remote_url(settings["remote_url"], path), credential
```

Replace

```python
async def _refresh(context: RepositoryContext, path: str, asset: Asset | None) -> None:
    """Make `path` servable from the cache, or raise 404 or 502.
```

with

```python
async def _refresh(
    context: RepositoryContext, path: str, asset: Asset | None, source: Source | None = None
) -> None:
    """Make `path` servable from the cache, or raise 404 or 502.
```

Replace

```python
    url, credential = await _target(context, path)
    known = {} if asset is None else asset.attributes
    await db.commit()  # give the connection back for the length of the download
```

with

```python
    url, credential = await _target(context, path, source)
    known = {} if asset is None else asset.attributes
    await db.commit()  # give the connection back for the length of the download
```

Replace

```python
    now = utcnow()

    if isinstance(outcome, remote.Fetched):
        origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
```

with

```python
    now = utcnow()

    if isinstance(outcome, remote.Fetched) and source is not None:
        staged = outcome.staged
        if any(getattr(staged, name, None) != digest for name, digest in source.digests.items()):
            # Not the file the index describes. It is not kept, and not served.
            await context.discard(staged)
            outcome = remote.Failed("a file does not match the hash its index gives", False)

    if isinstance(outcome, remote.Fetched):
        origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
```

Replace

```python
async def ensure_cached(context: RepositoryContext, path: str) -> None:
    """Make `path` servable from this proxy's cache, or raise 404 or 502.

    Returning means there is a copy to serve: a fresh one, a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.
```

with

```python
async def ensure_cached(
    context: RepositoryContext, path: str, *, source: Source | None = None
) -> None:
    """Make `path` servable from this proxy's cache, or raise 404 or 502.

    Returning means there is a copy to serve: a fresh one, a new one, the old one
    confirmed, or the old one kept because the remote could not be asked.

    `source` says where the path is found when the remote's own content names the
    address. The remote's credential then goes only to the remote's own origin, an
    internal address is refused unless the remote is at that host, and content that
    does not match the hashes given is not cached.
```

Replace

```python
        if not _fresh(context, asset, path):
            await _refresh(context, path, asset)
```

with

```python
        if not _fresh(context, asset, path):
            await _refresh(context, path, asset, source)
```

In `backend/src/megooarti/repositories/content.py`:

Before

```python
    async def release(self) -> None:
```

add

```python
    def open(self, stored: Stored) -> AsyncIterator[bytes]:
        """The bytes of what `stat` described, in pieces. Uses no database."""
        return self.backend.open(stored.sha256)
```

Before

```python
    async def _transformed(self, sha256: str, transformer: Transformer) -> AsyncIterator[bytes]:
```

add

```python
    async def respond_stream(
        self,
        request: Request,
        body: Callable[[], AsyncIterator[bytes]],
        *,
        etag: str,
        content_type: str,
        filename: str,
        last_modified: datetime,
    ) -> Response:
        """Answer a GET or HEAD with content that is made as it is sent.

        For content put together from stored files that are too large to hold, such
        as one page made from several. `etag` must change whenever the content would:
        the caller makes it from what the content is built from, so a request that
        already has it is answered without `body` being called. No length is
        declared and ranges are not served.
        """
        item = serving.Servable(
            sha256="",
            md5=None,
            sha1=None,
            sha512=None,
            size=0,
            content_type=content_type,
            last_modified=last_modified,
            filename=filename,
            etag=etag,
        )
        plan = serving.plan_stream(request.method, request.headers, item)
        await self.db.commit()  # give the connection back before the body is sent
        if plan.status == 304:
            return Response(status_code=304, headers=plan.headers)
        # A streaming response even for HEAD: a plain one would declare a length of 0.
        content = body() if plan.send_body else _nothing()
        return StreamingResponse(content, status_code=plan.status, headers=plan.headers)
```

In `backend/src/megooarti/repositories/group.py`:

Before

```python
async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
```

add

```python
async def owners(
    found: Sequence[Leaf], namespace: str, name: str
) -> tuple[list[RepositoryContext], bool]:
    """The hosted repositories behind a group that hold a package.

    Returns those that are online, in order, and whether one that is offline holds it
    too. A package that a hosted repository holds is answered for by hosted
    repositories only: package names are not verified, so a public package of the
    same name must not add to it, nor stand in for it while its repository is offline.
    """
    online, offline = [], False
    for leaf in found:
        member = leaf.context
        if member.repository.type != "hosted" or not await member.names(namespace, [name]):
            continue
        if leaf.online:
            online.append(member)
        else:
            offline = True
    return online, offline


def proxies(found: Sequence[Leaf]) -> list[RepositoryContext]:
    """The online proxy repositories behind a group, in order."""
    return [
        leaf.context for leaf in found if leaf.online and leaf.context.repository.type == "proxy"
    ]
```

Replace

```python
import uuid
from dataclasses import dataclass
```

with

```python
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
```

In `backend/src/megooarti/repositories/npm/format.py`:

Replace

```python
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
```

with

```python

```

Replace

```python
    owners, offline = await _owners(leaves, package)
```

with

```python
    owners, offline = await group.owners(leaves, *_coordinates(package))
```

Replace

```python
    have = await _cached_by(_proxies(leaves), package)
```

with

```python
    have = await _cached_by(group.proxies(leaves), package)
```

Replace

```python
    owners, offline = await _owners(leaves, parsed.package)
```

with

```python
    owners, offline = await group.owners(leaves, *_coordinates(parsed.package))
```

Replace

```python
    for member in owners or _proxies(leaves):
```

with

```python
    for member in owners or group.proxies(leaves):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass, the npm group tests among them: they now go through `group.owners`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories
git commit -m "feat(repositories): fetch from an address a remote names, answer with a stream, share who holds a name"
```

---

### Task 2: Reading a remote's page

**Files:**
- Modify: `backend/src/megooarti/repositories/pypi/pages.py`
- Modify: `backend/src/megooarti/repositories/pypi/names.py`
- Test: `backend/tests/repositories/pypi/test_pages.py`
- Test: `backend/tests/repositories/pypi/test_names.py`

**Interfaces:**
- Consumes: `names.is_valid_segment`, `names.version_of`.
- Produces:
  - `pages.Link` gains `yanked: str | None = None`, `metadata: str | None = None` and `url: str = ""`. `link_line` writes `data-yanked`, and both metadata attributes when `metadata` is set. `url` is never written.
  - `pages.Reader(project: str, address: str)` with `feed(chunk: bytes) -> list[Link]`. `project` is in its normal form; `address` is the remote page's own.
  - `pages.digest_of(text: str) -> tuple[str, str] | None` and `pages.metadata_address(address: str) -> str`.
  - `pages.MAX_TAG`.
  - `names.page_path(project: str) -> str`: `simple/<project>`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/repositories/pypi/test_pages.py`:

Replace

```python
from html.parser import HTMLParser

from megooarti.repositories.pypi import pages
from megooarti.repositories.pypi.pages import Link
```

with

```python
from html.parser import HTMLParser

import pytest

from megooarti.repositories.pypi import pages
from megooarti.repositories.pypi.pages import Link, Reader
```

Add to the end of `backend/tests/repositories/pypi/test_pages.py`:

```python
HOST = "https://files.example/packages"
ADDRESS = "https://index.example/simple/requests/"
FILE = "https://f.example/requests-1.0.tar.gz"


def remote_link(path: str, digest: str, *attributes: str) -> str:
    """A link as pypi.org writes it: an absolute address on another host, then the name."""
    name = path.rpartition("/")[2]
    written = "".join(f" {attribute}" for attribute in attributes)
    return f'<a href="{HOST}/{path}#sha256={digest}"{written}>{name}</a><br />\n'


# A project page as pypi.org writes it.
REMOTE_PAGE = (
    "<!DOCTYPE html>\n<html>\n  <head>\n"
    '    <meta name="pypi:repository-version" content="1.3">\n'
    "    <title>Links for requests</title>\n  </head>\n  <body>\n"
    "    <h1>Links for requests</h1>\n"
    + remote_link("ab/cd/requests-2.30.0.tar.gz", SHA)
    + remote_link(
        "ef/01/requests-2.31.0-py3-none-any.whl",
        "b" * 64,
        'data-requires-python="&gt;=3.7"',
        f'data-dist-info-metadata="sha256={"c" * 64}"',
        f'data-core-metadata="sha256={"c" * 64}"',
    )
    + remote_link(
        "23/45/requests-2.31.0.tar.gz",
        "d" * 64,
        'data-requires-python="&gt;=3.7"',
        'data-yanked="broken &amp; withdrawn"',
    )
    + "</body>\n</html>\n<!--SERIAL 12345-->\n"
).encode()


def read_in_pieces(page: bytes, cuts: list[int], project: str = "requests") -> list[Link]:
    reader = Reader(project, ADDRESS)
    edges = [0, *sorted(cuts), len(page)]
    found = []
    for start, end in zip(edges, edges[1:], strict=False):
        found.extend(reader.feed(page[start:end]))
    return found


def test_the_links_of_a_remote_page_are_read():
    assert read_in_pieces(REMOTE_PAGE, []) == [
        Link(
            filename="requests-2.30.0.tar.gz",
            version="2.30.0",
            digest=f"sha256={SHA}",
            url=f"{HOST}/ab/cd/requests-2.30.0.tar.gz",
        ),
        Link(
            filename="requests-2.31.0-py3-none-any.whl",
            version="2.31.0",
            digest=f"sha256={'b' * 64}",
            requires_python=">=3.7",
            metadata=f"sha256={'c' * 64}",
            url=f"{HOST}/ef/01/requests-2.31.0-py3-none-any.whl",
        ),
        Link(
            filename="requests-2.31.0.tar.gz",
            version="2.31.0",
            digest=f"sha256={'d' * 64}",
            requires_python=">=3.7",
            yanked="broken & withdrawn",
            url=f"{HOST}/23/45/requests-2.31.0.tar.gz",
        ),
    ]


def test_the_links_read_are_the_same_wherever_the_page_is_cut():
    whole = read_in_pieces(REMOTE_PAGE, [])

    for cut in range(len(REMOTE_PAGE) + 1):
        assert read_in_pieces(REMOTE_PAGE, [cut]) == whole, cut
    for size in (1, 2, 3, 7, 64):
        assert read_in_pieces(REMOTE_PAGE, list(range(size, len(REMOTE_PAGE), size))) == whole


def test_a_link_inside_an_attribute_is_not_a_link_wherever_the_page_is_cut():
    inner = f"<a href='{HOST}/requests-6.6.6.tar.gz'>"
    page = (
        f'<a href="{HOST}/requests-1.0.tar.gz" title="see {inner} for more">x</a>'
        f'<a href="{HOST}/requests-2.0.tar.gz">y</a>'
    ).encode()

    for cut in range(len(page) + 1):
        found = read_in_pieces(page, [cut])
        assert [link.version for link in found] == ["1.0", "2.0"], cut


@pytest.mark.parametrize(
    ("tag", "address", "digest"),
    [
        # Relative links, as devpi, Artifactory and Nexus write them.
        (
            f'<a href="../../packages/ab/requests-1.0.tar.gz#md5={"a" * 32}">',
            "https://index.example/packages/ab/requests-1.0.tar.gz",
            "md5=" + "a" * 32,
        ),
        (
            '<a href="requests-1.0.tar.gz">',
            "https://index.example/simple/requests/requests-1.0.tar.gz",
            "",
        ),
        (
            '<a href="/root/requests-1.0.tar.gz">',
            "https://index.example/root/requests-1.0.tar.gz",
            "",
        ),
        # Other ways of writing a tag.
        (f"<A HREF='{FILE}'>", FILE, ""),
        (f"<a\n  class=x\thref={FILE} >", FILE, ""),
        (f'<a rel="internal" href = "{FILE}">', FILE, ""),
        (
            f'<a href="https://f.example/a%20b/requests-1.0.tar.gz?x=1#sha256={"A" * 64}">',
            "https://f.example/a%20b/requests-1.0.tar.gz?x=1",
            "sha256=" + "a" * 64,
        ),
        (
            '<a href="https://f.example/requests-1.0%2Blocal.tar.gz">',
            "https://f.example/requests-1.0%2Blocal.tar.gz",
            "",
        ),
        # A hash that cannot be checked here is dropped, not the link.
        (f'<a href="{FILE}#sha384={"a" * 96}">', FILE, ""),
        (f'<a href="{FILE}#sha256=nothex">', FILE, ""),
        (f'<a href="{FILE}#egg=requests">', FILE, ""),
    ],
)
def test_links_are_read_however_they_are_written(tag, address, digest):
    found = read_in_pieces(f"<body>{tag}requests-1.0.tar.gz</a></body>".encode(), [])

    assert [(link.url, link.digest) for link in found] == [(address, digest)]


def test_an_unescaped_greater_than_in_an_attribute_does_not_end_the_tag():
    page = f'<a data-requires-python=">=3.7,<4" href="{FILE}">x</a>'.encode()

    found = read_in_pieces(page, [])

    assert [(link.version, link.requires_python) for link in found] == [("1.0", ">=3.7,<4")]


@pytest.mark.parametrize(
    "tag",
    [
        "<a>",
        '<a name="top">',
        '<a href="">',
        '<a href="#sha256=' + "a" * 64 + '">',
        '<a href="https://f.example/urllib3-2.0.0.tar.gz">',  # another project's file
        '<a href="https://f.example/requests-1.0.txt">',
        '<a href="https://f.example/requests/">',
        '<a href="https://f.example/requests-1.0.tar.gz/">',
        '<a href="https://f.example/requests-..tar.gz">',
        '<a href="https://f.example/a/..%2Frequests-1.0.tar.gz">',
        '<a href="https://f.example/requests-1.0%20x.tar.gz">',
        '<a href="ftp://f.example/requests-1.0.tar.gz">',
        '<a href="file:///etc/requests-1.0.tar.gz">',
        '<a href="javascript:requests-1.0.tar.gz">',
        '<abbr href="https://f.example/requests-1.0.tar.gz">',
        '<link href="https://f.example/requests-1.0.tar.gz">',
        f'<a href="{FILE}"',  # never closed
    ],
)
def test_what_is_not_a_link_to_a_file_of_the_project_is_left_out(tag):
    assert read_in_pieces(f"<body>{tag}text</a></body>".encode(), []) == []


@pytest.mark.parametrize(
    ("attributes", "yanked", "metadata"),
    [
        ("", None, None),
        ("data-yanked", "", None),
        ('data-yanked=""', "", None),
        ('data-yanked="a\nreason"', "areason", None),
        ('data-core-metadata="true"', None, "true"),
        ("data-dist-info-metadata=true", None, "true"),
        ('data-core-metadata="false"', None, None),
        ('data-core-metadata=""', None, "true"),
        ('data-core-metadata="sha256=' + "E" * 64 + '"', None, "sha256=" + "e" * 64),
        ('data-core-metadata="sha384=' + "e" * 96 + '"', None, "true"),
        (
            'data-dist-info-metadata="true" data-core-metadata="sha256=' + "e" * 64 + '"',
            None,
            "sha256=" + "e" * 64,
        ),
    ],
)
def test_what_a_remote_says_about_a_file(attributes, yanked, metadata):
    page = f'<a href="{FILE}" {attributes}>x</a>'.encode()

    (link,) = read_in_pieces(page, [])

    assert (link.yanked, link.metadata) == (yanked, metadata)


def test_what_a_remote_declares_is_bounded():
    page = f'<a href="{FILE}" data-requires-python="{"&gt;=3" * 2000}">x</a>'.encode()

    (link,) = read_in_pieces(page, [])

    assert len(link.requires_python) == 1024


def test_a_tag_too_long_to_be_a_link_is_passed_over_and_reading_goes_on():
    endless = f'<a href="{FILE}" title="{"x" * 40_000}">x</a>'
    page = (endless + '<a href="https://f.example/requests-2.0.tar.gz">y</a>').encode()
    whole = read_in_pieces(page, [])

    assert [link.version for link in whole] == ["2.0"]
    for cut in range(0, len(page), 997):
        assert read_in_pieces(page, [cut]) == whole, cut


def test_only_an_unfinished_tag_is_held_back():
    reader = Reader("requests", ADDRESS)

    reader.feed(b"x" * 1_000_000 + b'<a href="https://f.example/requests-1.0')

    assert len(reader._held) == len(b'<a href="https://f.example/requests-1.0')
    assert [link.version for link in reader.feed(b'.tar.gz">x</a>' + b"y" * 1000)] == ["1.0"]
    assert reader._held == b""


def test_text_that_is_not_utf8_does_not_stop_the_reading():
    page = b'<p>\xff\xfe</p><a title="\xff" href="' + FILE.encode() + b'">\xff</a>'

    assert [link.version for link in read_in_pieces(page, [])] == ["1.0"]


def test_a_link_read_from_a_remote_is_written_with_what_it_said():
    (_, wheel, yanked) = read_in_pieces(REMOTE_PAGE, [])

    page = pages.project_page("requests", [wheel, yanked])

    assert HOST.encode() not in page  # where the remote keeps a file is never passed on
    assert read(page).found == [
        (
            {
                "href": "../../packages/requests/2.31.0/requests-2.31.0-py3-none-any.whl"
                f"#sha256={'b' * 64}",
                "data-requires-python": ">=3.7",
                "data-dist-info-metadata": f"sha256={'c' * 64}",
                "data-core-metadata": f"sha256={'c' * 64}",
            },
            "requests-2.31.0-py3-none-any.whl",
        ),
        (
            {
                "href": f"../../packages/requests/2.31.0/requests-2.31.0.tar.gz#sha256={'d' * 64}",
                "data-requires-python": ">=3.7",
                "data-yanked": "broken & withdrawn",
            },
            "requests-2.31.0.tar.gz",
        ),
    ]


def test_a_yanked_file_without_a_reason_is_still_marked():
    page = pages.project_page("pkg", [Link("pkg-1.0.tar.gz", "1.0", yanked="")])

    assert read(page).found[0][0] == {
        "href": "../../packages/pkg/1.0/pkg-1.0.tar.gz",
        "data-yanked": "",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sha256=" + "A" * 64, ("sha256", "a" * 64)),
        ("md5=" + "0" * 32, ("md5", "0" * 32)),
        ("SHA1=" + "f" * 40, ("sha1", "f" * 40)),
        ("sha512=" + "1" * 128, ("sha512", "1" * 128)),
        ("sha256=" + "a" * 63, None),
        ("sha256=" + "g" * 64, None),
        ("sha384=" + "a" * 96, None),
        ("blake2b=" + "a" * 64, None),
        ("true", None),
        ("", None),
    ],
)
def test_a_hash_that_can_be_checked(text, expected):
    assert pages.digest_of(text) == expected


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        (FILE, FILE + ".metadata"),
        (FILE + "?x=1", FILE + ".metadata?x=1"),
        ("http://h.example/a/b.whl", "http://h.example/a/b.whl.metadata"),
    ],
)
def test_a_metadata_file_is_beside_its_file(address, expected):
    assert pages.metadata_address(address) == expected
```

In `backend/tests/repositories/pypi/test_names.py`:

After

```python
    assert classify(names.file_path("requests", "2.31.0", "requests-2.31.0.tar.gz")).kind == "file"
```

add

```python
    assert names.page_path("requests") == "simple/requests"
    assert classify(names.page_path("requests")) == PypiPath("page", project="requests")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi/test_pages.py tests/repositories/pypi/test_names.py -q`
Expected: collection error, `cannot import name 'Reader' from 'megooarti.repositories.pypi.pages'`.

- [ ] **Step 3: Implement**

The page module is replaced whole: what plan 6a wrote is unchanged, and the reader is new.

In `backend/src/megooarti/repositories/pypi/names.py`:

Before

```python
def version_of(project: str, filename: str) -> str | None:
```

add

```python
def page_path(project: str) -> str:
    """Where a proxy keeps the remote's page for a project. `project` is in its normal form."""
    return f"simple/{project}"
```

`backend/src/megooarti/repositories/pypi/pages.py`:

```python
"""PyPI index pages (PEP 503): the list of projects, and the files of one project.

Pure functions. Every link is relative, so a page is the same whatever address the
client used to reach the repository.

A proxy does not serve a remote's page. `Reader` takes the links out of it as it
streams, and the page served is written from them here: nothing a remote wrote reaches a
client but file names, hashes and a few known attributes.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape, unescape
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from megooarti.repositories.pypi import names

CONTENT_TYPE = "text/html; charset=utf-8"
_HEAD = (
    "<!DOCTYPE html>\n<html>\n  <head>\n"
    '    <meta name="pypi:repository-version" content="1.0">\n'
    "    <title>{title}</title>\n  </head>\n  <body>\n    <h1>{title}</h1>\n"
)
_FOOT = "  </body>\n</html>\n"

# The opening tag of a link. A quoted value may contain `>`, so quotes are followed.
_START = re.compile(rb"<a\s", re.IGNORECASE)
_TAG = re.compile(rb"<a\s((?:[^<>\"']|\"[^\"]*\"|'[^']*')*)>", re.IGNORECASE)
_ATTRIBUTE = re.compile(
    rb"([A-Za-z][A-Za-z0-9_:.-]*)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'=<>`]+)))?"
)
# The longest tag that is read. A longer one is passed over.
MAX_TAG = 16 * 1024
# The hashes a blob store computes, with their length in hex: what a download can be
# checked against.
_HASHES = {"sha256": 64, "sha512": 128, "sha1": 40, "md5": 32}
_MAX_DECLARED = 1024


@dataclass(frozen=True)
class Link:
    """One file on a project's page."""

    filename: str
    version: str
    digest: str = ""  # `sha256=<hex>`: what a client checks the download against
    requires_python: str | None = None
    yanked: str | None = None  # the reason given, which may be empty; None if not yanked
    metadata: str | None = None  # `sha256=<hex>` or `true` if the file has a metadata file
    url: str = ""  # where a remote keeps the file; never written to a page


def _segment(text: str) -> str:
    """A version or a file name as it is written in an address. `+` and `!` stay."""
    return quote(text, safe="+!")


def head(title: str) -> bytes:
    return _HEAD.format(title=escape(title)).encode()


def foot() -> bytes:
    return _FOOT.encode()


def link_line(project: str, link: Link) -> bytes:
    """One file's line. `project` is in its normal form; the page is at `simple/<project>/`."""
    address = f"../../packages/{project}/{_segment(link.version)}/{_segment(link.filename)}"
    if link.digest:
        address += f"#{link.digest}"
    attributes = f' href="{escape(address)}"'
    if link.requires_python:
        attributes += f' data-requires-python="{escape(link.requires_python)}"'
    if link.yanked is not None:
        attributes += f' data-yanked="{escape(link.yanked)}"'
    if link.metadata is not None:
        # Under both names: older clients know only the first, newer ones the second.
        value = escape(link.metadata)
        attributes += f' data-dist-info-metadata="{value}" data-core-metadata="{value}"'
    return f"    <a{attributes}>{escape(link.filename)}</a><br>\n".encode()


def project_page(project: str, links: Iterable[Link]) -> bytes:
    """The page of a project that is held whole in memory: a hosted repository's."""
    lines = [link_line(project, link) for link in links]
    return head(f"Links for {project}") + b"".join(lines) + foot()


def root_page(projects: Iterable[str]) -> bytes:
    """The list of projects. The page is at `simple/`."""
    lines = [
        f'    <a href="{escape(project)}/">{escape(project)}</a><br>\n' for project in projects
    ]
    return head("Simple index") + "".join(lines).encode() + foot()


def metadata_address(address: str) -> str:
    """Where the metadata file of a file is: the file's address with `.metadata` added."""
    parts = urlsplit(address)
    return urlunsplit(parts._replace(path=parts.path + ".metadata"))


def digest_of(text: str) -> tuple[str, str] | None:
    """`sha256=<hex>` as (algorithm, lower-case hex), if it is a hash that can be checked."""
    algorithm, _, value = text.strip().partition("=")
    algorithm, value = algorithm.lower(), value.lower()
    if _HASHES.get(algorithm) != len(value) or not value.isalnum() or not value.isascii():
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return algorithm, value


def _declared(value: str | None) -> str | None:
    """Text a remote's page gives for a file, bounded and on one line."""
    if value is None:
        return None
    kept = "".join(character for character in value if character.isprintable())
    return kept.strip()[:_MAX_DECLARED]


class Reader:
    """Reads the links of a remote's project page, fed to it in pieces.

    `feed` returns the links found so far, in the page's order. A link whose file is
    not a file of the project is left out. What is held back between pieces is at most
    one unfinished tag, and a tag is settled before anything after it is looked at, so
    the links found do not depend on where the page is cut.
    """

    def __init__(self, project: str, address: str) -> None:
        """`project` is in its normal form. `address` is the page's own, for its links."""
        self._project = project
        self._address = address
        self._held = b""

    def feed(self, chunk: bytes) -> list[Link]:
        data = self._held + chunk
        found = []
        position = 0
        while True:
            start = _START.search(data, position)
            if start is None:
                # The end may be the beginning of a tag: `<`, or `<a`.
                keep = 2 if data[-2:].lower() == b"<a" else 1 if data.endswith(b"<") else 0
                self._held = data[len(data) - keep :] if keep else b""
                return found
            tag = _TAG.match(data, start.start(), start.start() + MAX_TAG)
            if tag is None:
                if len(data) - start.start() < MAX_TAG:
                    self._held = data[start.start() :]  # it may not have ended yet
                    return found
                position = start.end()  # too long to be a link, or not a tag: passed over
                continue
            position = tag.end()
            link = self._link(tag[1])
            if link is not None:
                found.append(link)

    def _link(self, written: bytes) -> Link | None:
        given: dict[str, str] = {}
        for name, double, single, bare in _ATTRIBUTE.findall(written):
            value = (double or single or bare).decode("utf-8", "replace")
            given.setdefault(name.decode("ascii").lower(), unescape(value))
        href = given.get("href")
        if not href:
            return None
        target, _, fragment = href.partition("#")
        address = urljoin(self._address, target)
        parts = urlsplit(address)
        filename = unquote(parts.path.rpartition("/")[2])
        if parts.scheme not in ("http", "https") or not names.is_valid_segment(filename):
            return None
        version = names.version_of(self._project, filename)
        if version is None:
            return None
        digest = digest_of(fragment)
        described = given.get("data-core-metadata", given.get("data-dist-info-metadata"))
        metadata = None
        if described is not None and described.strip().lower() != "false":
            checked = digest_of(described)
            metadata = "true" if checked is None else "=".join(checked)
        return Link(
            filename=filename,
            version=version,
            digest="" if digest is None else "=".join(digest),
            requires_python=_declared(given.get("data-requires-python")) or None,
            yanked=_declared(given.get("data-yanked")),
            metadata=metadata,
            url=address,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/pypi -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/pypi backend/tests/repositories/pypi
git commit -m "feat(pypi): read the links of a remote's page as it streams"
```

---

### Task 3: PyPI proxy repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/pypi/format.py`
- Modify: `backend/tests/repositories/pypi/conftest.py`
- Test: `backend/tests/repositories/pypi/test_proxy.py`

**Interfaces:**
- Consumes: `proxy.Source`, `proxy.ensure_cached(..., source=)`, `context.open`, `context.respond_stream` (Task 1); `pages.Reader`, `pages.digest_of`, `pages.metadata_address`, `pages.link_line`, `pages.head`, `pages.foot`, `names.page_path` (Task 2); `context.stat`, `context.release`, `context.respond`, `context.package_names`.
- Produces:
  - `await off_loop(function, *arguments)`: the PyPI format's two worker threads.
  - `await _written(context, request, project, sources: Sequence[tuple[RepositoryContext, Stored]]) -> Response`: one page from the cached pages of several proxies.
  - `await _root_index(context, request, within=None)`: the signature gains `within`.
  - `PypiFormat.remote_url`, `PypiFormat.is_metadata`, `PypiFormat.handle_proxy`; `PypiFormat.types` is `{"hosted", "proxy"}`.
  - Test helpers in `tests/repositories/pypi/conftest.py`: `REMOTE`, `FILES_HOST`, `create(db, name, *, type="hosted", hosted=None, proxy=None, group=None)`, `remote_link(filename, *attributes, at=FILES_HOST, data=None)`, `remote_page(project, *links)`, `links(response)`, `link_to(project, version, filename, **attributes)`, and the fixture `upstream` (a proxy of `REMOTE`).

- [ ] **Step 1: Write the test helpers and the failing tests**

The helpers file is replaced: `create` can now make any type of repository, and the helpers for a remote index and for reading a served page are new. The test file is new.

`backend/tests/repositories/pypi/conftest.py`:

```python
import hashlib
from html.parser import HTMLParser

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/pypi"
BOUNDARY = "megooarti-test-boundary-7MA4YWxkTrZu0gW"
CONTENT_TYPE = f"multipart/form-data; boundary={BOUNDARY}"
WHEEL = "megooarti_greeter-1.0.0-py3-none-any.whl"
SDIST = "megooarti_greeter-1.0.0.tar.gz"
# A remote index, and the other host it keeps its files on, as pypi.org does.
REMOTE = "http://remote.test/pypi"
FILES_HOST = "http://files.test"


async def create(
    db,
    name: str,
    *,
    type: str = "hosted",
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: dict | None = None,
) -> Repository:
    """A PyPI repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="pypi",
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


def content_of(filename: str) -> bytes:
    """Stand-in file bytes, different for every file name."""
    return f"PK\x03\x04 contents of {filename}".encode()


def _part(name: str, value, boundary: str) -> bytes:
    disposition = f'Content-Disposition: form-data; name="{name}"'
    if isinstance(value, tuple):  # a file: (file name, bytes)
        filename, value = value
        disposition += f'; filename="{filename}"\r\nContent-Type: application/octet-stream'
    data = value if isinstance(value, bytes) else str(value).encode()
    return f"--{boundary}\r\n{disposition}\r\n\r\n".encode() + data + b"\r\n"


def form_body(
    fields: dict,
    file: tuple[str, bytes] | None,
    *,
    extra: list[tuple[str, object]] | None = None,
    file_first: bool = False,
    boundary: str = BOUNDARY,
) -> bytes:
    """A multipart form as an upload client writes it: the fields, then the file."""
    parts = list(fields.items())
    if file is not None:
        parts.insert(0, ("content", file)) if file_first else parts.append(("content", file))
    parts.extend(extra or [])
    body = b"".join(_part(name, value, boundary) for name, value in parts)
    return body + f"--{boundary}--\r\n".encode()


def upload_fields(name: str, version: str, data: bytes, **changes) -> dict:
    """The fields twine sends with a file."""
    fields = {
        ":action": "file_upload",
        "protocol_version": "1",
        "metadata_version": "2.1",
        "name": name,
        "version": version,
        "filetype": "bdist_wheel",
        "pyversion": "py3",
        "sha256_digest": hashlib.sha256(data).hexdigest(),
        "md5_digest": hashlib.md5(data).hexdigest(),
        "blake2_256_digest": hashlib.blake2b(data, digest_size=32).hexdigest(),
    }
    fields.update(changes)
    return {key: value for key, value in fields.items() if value is not None}


async def upload(client, headers, filename: str, **changes):
    """Upload one file as twine does. The project and version are read from its name.

    `repository`, `data`, `name` and `version` can be given; anything else is a form field.
    """
    repository = changes.pop("repository", "pypi")
    data = changes.pop("data", None) or content_of(filename)
    stem = filename.removesuffix(".whl").removesuffix(".tar.gz").removesuffix(".zip")
    name = changes.pop("name", stem.split("-")[0])
    version = changes.pop("version", stem.split("-")[1])
    body = form_body(upload_fields(name, version, data, **changes), (filename, data))
    return await client.post(
        f"/repository/{repository}/",
        content=body,
        headers={**headers, "Content-Type": CONTENT_TYPE},
    )


def remote_link(
    filename: str, *attributes: str, at: str = FILES_HOST, data: bytes | None = None
) -> str:
    """A link as a remote index writes it, to a file kept at `<at>/packages/<file name>`.

    The hash is that of `content_of(filename)` unless `data` says what the remote holds.
    """
    digest = hashlib.sha256(content_of(filename) if data is None else data).hexdigest()
    written = "".join(f" {attribute}" for attribute in attributes)
    address = f"{at}/packages/{filename}#sha256={digest}"
    return f'<a href="{address}"{written}>{filename}</a><br />\n'


def remote_page(project: str, *links: str) -> bytes:
    """A project page as a remote index serves it. A plain file name is linked as it is."""
    written = "".join(link if "<" in link else remote_link(link) for link in links)
    head = f"<!DOCTYPE html>\n<html><head><title>Links for {project}</title></head>\n<body>\n"
    return f"{head}<h1>Links for {project}</h1>\n{written}</body></html>\n".encode()


class Anchors(HTMLParser):
    """The links of a page, as a browser or an installer would read them."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[dict, str]] = []
        self._open: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._open = dict(attrs)

    def handle_data(self, data):
        if self._open is not None:
            self.found.append((self._open, data))
            self._open = None


def links(response) -> list[tuple[dict, str]]:
    """The links of a page that was served: (attributes, text) for each."""
    parser = Anchors()
    parser.feed(response.text)
    return parser.found


def link_to(project: str, version: str, filename: str, **attributes) -> tuple[dict, str]:
    """What a served page says of a file whose content is `content_of(filename)`."""
    digest = hashlib.sha256(content_of(filename)).hexdigest()
    href = f"../../packages/{project}/{version}/{filename}#sha256={digest}"
    return {"href": href, **attributes}, filename


@pytest.fixture
async def index(db) -> Repository:
    return await create(db, "pypi")


@pytest.fixture
async def upstream(db) -> Repository:
    """A proxy of the fake remote index."""
    return await create(db, "upstream", type="proxy", proxy={"remote_url": REMOTE})


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

`backend/tests/repositories/pypi/test_proxy.py`:

```python
import base64
import hashlib

import pytest
from sqlalchemy import select

from megooarti.repositories.models import Asset, Component
from tests.accounts import error_code
from tests.repositories.pypi.conftest import (
    FILES_HOST,
    REMOTE,
    content_of,
    create,
    link_to,
    links,
    remote_link,
    remote_page,
)

PROXY = "/repository/upstream"
PAGE = f"{PROXY}/simple/requests/"
OLD = "requests-2.30.0.tar.gz"
WHEEL = "requests-2.31.0-py3-none-any.whl"
SDIST = "requests-2.31.0.tar.gz"
WHEEL_URL = f"{PROXY}/packages/requests/2.31.0/{WHEEL}"
METADATA = b"Metadata-Version: 2.1\nName: requests\nVersion: 2.31.0\n"


def asked(remote) -> list[tuple[str, str]]:
    return [(seen["host"], seen["path"]) for seen in remote.requests]


@pytest.fixture
def remote(fake_remote, upstream):
    """The remote index has a page for requests; its files are on another host."""
    described = f'data-core-metadata="sha256={hashlib.sha256(METADATA).hexdigest()}"'
    fake_remote.files["pypi/simple/requests/"] = remote_page(
        "requests",
        OLD,
        remote_link(WHEEL, 'data-requires-python="&gt;=3.7"', described),
        remote_link(SDIST, 'data-requires-python="&gt;=3.7"', 'data-yanked="withdrawn"'),
    )
    for filename in (OLD, WHEEL, SDIST):
        fake_remote.files[f"packages/{filename}"] = content_of(filename)
    fake_remote.files[f"packages/{WHEEL}.metadata"] = METADATA
    return fake_remote


async def test_a_page_is_written_from_the_remotes_links_and_points_here(client, root, remote):
    first = await client.get(PAGE, headers=root)
    second = await client.get(PAGE, headers=root)

    assert first.status_code == 200, first.text
    digest = hashlib.sha256(METADATA).hexdigest()
    assert links(first) == [
        link_to("requests", "2.30.0", OLD),
        link_to(
            "requests",
            "2.31.0",
            WHEEL,
            **{
                "data-requires-python": ">=3.7",
                "data-dist-info-metadata": f"sha256={digest}",
                "data-core-metadata": f"sha256={digest}",
            },
        ),
        link_to(
            "requests",
            "2.31.0",
            SDIST,
            **{"data-requires-python": ">=3.7", "data-yanked": "withdrawn"},
        ),
    ]
    assert "files.test" not in first.text and "remote.test" not in first.text
    assert second.content == first.content
    assert asked(remote) == [("remote.test", "/pypi/simple/requests/")]


async def test_the_page_is_answered_as_content_without_a_length(client, root, remote):
    first = await client.get(PAGE, headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(PAGE, headers={**root, "If-None-Match": etag})
    headed = await client.head(PAGE, headers=root)

    assert first.headers["Content-Type"] == "text/html; charset=utf-8"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert first.headers["Accept-Ranges"] == "none"
    assert "Content-Length" not in first.headers
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (headed.status_code, headed.content, headed.headers["ETag"]) == (200, b"", etag)
    assert "Content-Length" not in headed.headers


async def test_a_file_is_fetched_from_where_the_remote_keeps_it_and_cached(
    client, root, remote, db
):
    first = await client.get(WHEEL_URL, headers=root)
    second = await client.get(WHEEL_URL, headers={**root, "Range": "bytes=0-3"})

    data = content_of(WHEEL)
    assert (first.status_code, first.content) == (200, data)
    assert first.headers["Content-Type"] == "application/octet-stream"
    assert first.headers["ETag"] == f'"{hashlib.sha256(data).hexdigest()}"'
    assert (second.status_code, second.content) == (206, data[:4])
    assert asked(remote) == [
        ("remote.test", "/pypi/simple/requests/"),
        ("files.test", f"/packages/{WHEEL}"),
    ]
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "requests", "2.31.0")


async def test_a_link_on_the_page_leads_to_the_file(client, root, remote):
    page = await client.get(PAGE, headers=root)
    href = links(page)[1][0]["href"]

    fetched = await client.get(str(page.url.join(href)), headers=root)

    assert (fetched.status_code, fetched.content) == (200, content_of(WHEEL))


async def test_a_file_asked_for_by_head_or_by_range_first_is_fetched_whole(client, root, remote):
    headed = await client.head(WHEEL_URL, headers=root)
    part = await client.get(
        f"{PROXY}/packages/requests/2.31.0/{SDIST}", headers={**root, "Range": "bytes=0-3"}
    )

    assert (headed.status_code, headed.content) == (200, b"")
    assert headed.headers["Content-Length"] == str(len(content_of(WHEEL)))
    assert (part.status_code, part.content) == (206, content_of(SDIST)[:4])
    assert [seen["method"] for seen in remote.requests] == ["GET", "GET", "GET"]


async def test_a_file_that_is_not_the_one_the_page_describes_is_not_served(
    client, root, remote, db
):
    remote.files[f"packages/{WHEEL}"] = b"replaced at the remote"

    response = await client.get(WHEEL_URL, headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert list(await db.scalars(select(Asset.path))) == ["simple/requests"]


@pytest.mark.parametrize(
    "path",
    [
        "packages/requests/2.31.0/requests-2.31.1.tar.gz",  # not on the page
        f"packages/requests/9.9.9/{WHEEL}",  # on the page, under another version
        "packages/requests/2.31.0/urllib3-2.0.0.tar.gz",  # another project's file
        f"packages/requests/2.30.0/{OLD}.metadata",  # the remote has no metadata for it
    ],
)
async def test_a_file_the_page_does_not_list_is_not_found(client, root, remote, path):
    response = await client.get(f"{PROXY}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")
    assert asked(remote) == [("remote.test", "/pypi/simple/requests/")]


async def test_a_metadata_file_is_fetched_from_beside_its_file(client, root, remote):
    first = await client.get(f"{WHEEL_URL}.metadata", headers=root)
    second = await client.get(f"{WHEEL_URL}.metadata", headers=root)

    assert (first.status_code, first.content, second.content) == (200, METADATA, METADATA)
    assert first.headers["Content-Type"] == "text/plain; charset=utf-8"
    assert asked(remote) == [
        ("remote.test", "/pypi/simple/requests/"),
        ("files.test", f"/packages/{WHEEL}.metadata"),
    ]


async def test_a_metadata_file_must_match_its_hash_too(client, root, remote):
    remote.files[f"packages/{WHEEL}.metadata"] = b"Name: something-else\n"

    response = await client.get(f"{WHEEL_URL}.metadata", headers=root)

    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")


async def test_the_root_index_lists_what_has_been_cached_and_asks_nobody(client, root, remote):
    before = await client.get(f"{PROXY}/simple/", headers=root)
    await client.get(PAGE, headers=root)  # a page alone is not a project held
    await client.get(WHEEL_URL, headers=root)
    remote.requests.clear()

    after = await client.get(f"{PROXY}/simple/", headers=root)

    assert links(before) == []
    assert links(after) == [({"href": "requests/"}, "requests")]
    assert remote.requests == []


async def test_a_page_is_asked_about_again_and_a_file_never(client, root, db, fake_remote):
    ages = {"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": 0}
    await create(db, "eager", type="proxy", proxy=ages)
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)
    file_url = f"/repository/eager/packages/requests/2.30.0/{OLD}"
    for _ in range(2):
        await client.get("/repository/eager/simple/requests/", headers=root)
        await client.get(file_url, headers=root)
    before = await client.get("/repository/eager/simple/requests/", headers=root)

    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, SDIST)
    after = await client.get(
        "/repository/eager/simple/requests/",
        headers={**root, "If-None-Match": before.headers["ETag"]},
    )

    assert [path for _, path in asked(fake_remote)].count(f"/packages/{OLD}") == 1
    assert (after.status_code, [text for _, text in links(after)]) == (200, [OLD, SDIST])
    assert after.headers["ETag"] != before.headers["ETag"]


async def test_what_the_remote_lacks_is_not_found_and_remembered(client, root, remote):
    first = await client.get(f"{PROXY}/simple/no-such-project/", headers=root)
    again = await client.get(f"{PROXY}/simple/no-such-project/", headers=root)
    its_file = await client.get(
        f"{PROXY}/packages/no-such-project/1.0/no_such_project-1.0.tar.gz", headers=root
    )

    for response in (first, again, its_file):
        assert (response.status_code, error_code(response)) == (404, "not_found")
    assert asked(remote) == [("remote.test", "/pypi/simple/no-such-project/")]


async def test_what_is_cached_is_served_while_the_remote_is_down(client, root, db, fake_remote):
    await create(
        db, "eager", type="proxy", proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0}
    )
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, SDIST)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)
    page = await client.get("/repository/eager/simple/requests/", headers=root)
    await client.get(f"/repository/eager/packages/requests/2.30.0/{OLD}", headers=root)
    fake_remote.down = True

    still = await client.get("/repository/eager/simple/requests/", headers=root)
    cached = await client.get(f"/repository/eager/packages/requests/2.30.0/{OLD}", headers=root)
    not_cached = await client.get(
        f"/repository/eager/packages/requests/2.31.0/{SDIST}", headers=root
    )
    unknown = await client.get("/repository/eager/simple/flask/", headers=root)

    assert (still.status_code, still.content) == (200, page.content)
    assert cached.content == content_of(OLD)
    assert (not_cached.status_code, error_code(not_cached)) == (502, "remote_unavailable")
    assert (unknown.status_code, error_code(unknown)) == (502, "remote_unavailable")


@pytest.mark.parametrize(
    ("asked_for", "location"),
    [
        ("simple", "simple/"),
        ("simple/requests", "requests/"),
        ("simple/Requests/", "../requests/"),
        ("simple/zope.interface", "zope-interface/"),
    ],
)
async def test_a_page_has_one_address_on_a_proxy_too(client, root, remote, asked_for, location):
    moved = await client.get(f"{PROXY}/{asked_for}", headers=root)

    assert (moved.status_code, moved.headers["Location"]) == (301, location)
    assert remote.requests == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", ""),
        ("PUT", "simple/requests/"),
        ("DELETE", f"packages/requests/2.31.0/{WHEEL}"),
        ("PUT", f"packages/requests/2.31.0/{WHEEL}"),
        ("POST", "simple/"),
    ],
)
async def test_a_proxy_cannot_be_written_to(client, root, remote, method, path):
    response = await client.request(method, f"{PROXY}/{path}", content=b"x", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD"
    assert remote.requests == []


@pytest.mark.parametrize("path", ["", "pypi/requests/json", "packages/requests", "simple/a/b/"])
async def test_addresses_that_mean_nothing_on_a_proxy(client, root, remote, path):
    response = await client.get(f"{PROXY}/{path}", headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")
    assert remote.requests == []


@pytest.mark.parametrize(
    ("configured", "page_path"),
    [
        ("http://remote.test/pypi", "/pypi/simple/requests/"),
        ("http://remote.test/pypi/", "/pypi/simple/requests/"),
        ("http://remote.test/pypi/simple", "/pypi/simple/requests/"),
        ("http://remote.test/pypi/simple/", "/pypi/simple/requests/"),
        ("http://remote.test/root/pypi/+simple", "/root/pypi/+simple/requests/"),
        ("http://remote.test", "/simple/requests/"),
    ],
)
async def test_the_remote_is_an_index_or_its_root(
    client, root, db, fake_remote, configured, page_path
):
    await create(db, "other", type="proxy", proxy={"remote_url": configured})
    fake_remote.files[page_path.lstrip("/")] = remote_page("requests", OLD)

    response = await client.get("/repository/other/simple/requests/", headers=root)

    assert [text for _, text in links(response)] == [OLD]
    assert asked(fake_remote) == [("remote.test", page_path)]


async def test_links_relative_to_the_remotes_page_are_followed(client, root, db, fake_remote):
    # As devpi, Artifactory and Nexus write them: the files are on the index's own host.
    await create(
        db, "devpi", type="proxy", proxy={"remote_url": "http://remote.test/root/pypi/+simple"}
    )
    digest = hashlib.sha256(content_of(OLD)).hexdigest()
    link = f'<a href="../../+f/ab/cd/{OLD}#sha256={digest}">{OLD}</a>'
    fake_remote.files["root/pypi/+simple/requests/"] = remote_page("requests", link)
    fake_remote.files[f"root/pypi/+f/ab/cd/{OLD}"] = content_of(OLD)

    response = await client.get(f"/repository/devpi/packages/requests/2.30.0/{OLD}", headers=root)

    assert response.content == content_of(OLD)
    assert asked(fake_remote)[-1] == ("remote.test", f"/root/pypi/+f/ab/cd/{OLD}")


async def test_the_remotes_credential_is_not_sent_to_the_host_of_its_files(
    admin_client, fake_remote
):
    private = {
        "name": "private",
        "format": "pypi",
        "type": "proxy",
        "proxy": {
            "remote_url": REMOTE,
            "remote_auth": {"type": "basic", "username": "robot", "secret": "s3cret"},
        },
    }
    await admin_client.post("/api/v1/repositories", json=private)
    same_host = remote_link("requests-2.29.0.tar.gz", at="http://remote.test/pypi")
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, same_host)
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)
    fake_remote.files["pypi/packages/requests-2.29.0.tar.gz"] = content_of("requests-2.29.0.tar.gz")

    for version, filename in (("2.30.0", OLD), ("2.29.0", "requests-2.29.0.tar.gz")):
        response = await admin_client.get(
            f"/repository/private/packages/requests/{version}/{filename}"
        )
        assert response.status_code == 200, response.text

    expected = "Basic " + base64.b64encode(b"robot:s3cret").decode()
    sent = [(seen["host"], seen["headers"].get("authorization")) for seen in fake_remote.requests]
    assert sent == [("remote.test", expected), ("files.test", None), ("remote.test", expected)]


@pytest.mark.parametrize(
    "address",
    ["http://127.0.0.1:8000", "http://169.254.169.254", "http://10.0.0.5", "http://localhost"],
)
async def test_a_page_cannot_send_the_proxy_to_an_internal_address(
    client, root, upstream, fake_remote, db, address
):
    fake_remote.files["pypi/simple/requests/"] = remote_page(
        "requests", remote_link(OLD, at=address)
    )
    fake_remote.files[f"packages/{OLD}"] = content_of(OLD)

    page = await client.get(PAGE, headers=root)
    response = await client.get(f"{PROXY}/packages/requests/2.30.0/{OLD}", headers=root)

    assert [text for _, text in links(page)] == [OLD]  # listed; fetching it is what is refused
    assert (response.status_code, error_code(response)) == (502, "remote_unavailable")
    assert asked(fake_remote) == [("remote.test", "/pypi/simple/requests/")]
    assert list(await db.scalars(select(Asset.path))) == ["simple/requests"]


async def test_nothing_a_remote_writes_reaches_the_page_but_what_is_read_from_its_links(
    client, root, upstream, fake_remote
):
    hostile = (
        "<script>alert(1)</script><img src=x onerror=alert(2)>"
        + remote_link(OLD, 'data-requires-python="&quot;&gt;&lt;script&gt;alert(3)&lt;/script&gt;"')
        + '<a href="javascript:alert(4)">requests-9.tar.gz</a>'
        + f'<a href="{FILES_HOST}/packages/evil-1.0.tar.gz" onclick="alert(5)">evil-1.0.tar.gz</a>'
    )
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", hostile)

    page = await client.get(PAGE, headers=root)

    assert "<script>" not in page.text and "onerror" not in page.text and "onclick" not in page.text
    assert links(page) == [
        link_to(
            "requests", "2.30.0", OLD, **{"data-requires-python": '"><script>alert(3)</script>'}
        )
    ]


async def test_a_page_read_back_in_several_pieces_lists_every_file(
    client, root, upstream, fake_remote
):
    filenames = [f"requests-1.{minor}.0.tar.gz" for minor in range(16_000)]
    page = remote_page("requests", *filenames)
    assert len(page) > 2 * 1024 * 1024  # over two pieces
    fake_remote.files["pypi/simple/requests/"] = page

    response = await client.get(PAGE, headers=root)

    assert [text for _, text in links(response)] == filenames


async def test_a_file_listed_twice_is_written_once(client, root, upstream, fake_remote):
    fake_remote.files["pypi/simple/requests/"] = remote_page("requests", OLD, SDIST, OLD)

    response = await client.get(PAGE, headers=root)

    assert [text for _, text in links(response)] == [OLD, SDIST]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi -q`
Expected: every test in `test_proxy.py` fails or errors while creating its repository: `proxy repositories are not available for this format`. The tests of plan 6a still pass.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/pypi/format.py`:

Replace

```python
A project's page is generated on each request from the files stored, so it is right
after a delete and after two uploads at once. An upload goes to the blob store as it
arrives: it is never held in memory.
"""

import hashlib
from collections.abc import AsyncIterator

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.pypi import names, pages, upload

_FILE = "application/octet-stream"
```

with

```python
A project's page is generated on each request from the files stored, so it is right
after a delete and after two uploads at once. An upload goes to the blob store as it
arrives: it is never held in memory.

A proxy keeps the remote's page for a project and never serves it. The links are read
out of it as it streams, and the page sent is written from them, pointing here. A file
is fetched from the address the remote's page gives for it, which is often on another
host, and must match the hash on that page. Reading a page is CPU-bound work whose size
a remote decides, so it runs on two worker threads of its own.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext, Stored
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.pypi import names, pages, upload

_FILE = "application/octet-stream"
_METADATA = "text/plain; charset=utf-8"
# Not the default executor: that one also reads and writes blobs and checks passwords.
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pypi-pages")
```

Before

```python
def _not_found(message: str = "Nothing is served at this address.") -> ApiError:
```

add

```python
async def off_loop[T](function: Callable[..., T], *arguments: Any) -> T:
    """Run page work in a worker thread, at most two at a time."""
    return await asyncio.get_running_loop().run_in_executor(_workers, function, *arguments)
```

Replace

```python
async def _root_index(context: RepositoryContext, request: Request) -> Response:
    found, _ = await context.package_names("", limit=ROOT_LIMIT, offset=0)
    await context.release()  # writing the page needs no connection
```

with

```python
async def _root_index(
    context: RepositoryContext,
    request: Request,
    within: Sequence[RepositoryContext] | None = None,
) -> Response:
    """The projects held: by this repository, or by those behind a group."""
    found, _ = await context.package_names("", limit=ROOT_LIMIT, offset=0, within=within)
    await context.release()  # writing the page needs no connection
```

Replace

```python
class PypiFormat(Format):
    name = "pypi"
    # Proxy and group repositories need PyPI's own handling of index pages.
    types = frozenset({"hosted"})
```

with

```python
# --- What a proxy serves -------------------------------------------------------------


def _page_address(member: RepositoryContext, project: str) -> str:
    """Where a proxy's cached page came from. Its links are resolved against this."""
    remote_url = member.repository.config["proxy"]["remote_url"]
    return member.format.remote_url(remote_url, names.page_path(project))


def _lines(reader: pages.Reader, chunk: bytes, project: str, written: set[str]) -> bytes:
    """The lines for the links in one piece of a remote's page that are not written yet."""
    lines = []
    for link in reader.feed(chunk):
        if link.filename not in written:
            written.add(link.filename)
            lines.append(pages.link_line(project, link))
    return b"".join(lines)


async def _written(
    context: RepositoryContext,
    request: Request,
    project: str,
    sources: Sequence[tuple[RepositoryContext, Stored]],
) -> Response:
    """A project's page written from proxies' cached pages, as it is sent.

    `sources` are the proxies that have the remote's page, in the order they are
    tried, each with what `stat` said of it. A file name two of them list is written
    once, from the earlier one. The pages are never held in memory.
    """
    made_from = "\n".join(stored.sha256 for _, stored in sources)
    etag = hashlib.sha256(f"pypi page 1\n{project}\n{made_from}".encode()).hexdigest()
    read_from = [(member, stored, _page_address(member, project)) for member, stored in sources]

    async def body() -> AsyncIterator[bytes]:
        written: set[str] = set()
        yield pages.head(f"Links for {project}")
        for member, stored, address in read_from:
            reader = pages.Reader(project, address)
            async for chunk in member.open(stored):
                lines = await off_loop(_lines, reader, chunk, project, written)
                if lines:
                    yield lines
        yield pages.foot()

    return await context.respond_stream(
        request,
        body,
        etag=etag,
        content_type=pages.CONTENT_TYPE,
        filename="index.html",
        last_modified=max(stored.modified for _, stored in sources),
    )


async def _proxied_page(context: RepositoryContext, request: Request, project: str) -> Response:
    page = names.page_path(project)
    await proxy.ensure_cached(context, page)
    stored = await context.stat(page)
    if stored is None:
        raise _not_found("No such project.")
    return await _written(context, request, project, [(context, stored)])


def _find(reader: pages.Reader, chunk: bytes, filename: str) -> pages.Link | None:
    return next((link for link in reader.feed(chunk) if link.filename == filename), None)


async def _link_to(context: RepositoryContext, parsed: names.PypiPath) -> pages.Link | None:
    """The link a proxy's remote has for a file, from its page, fetched if need be."""
    page = names.page_path(parsed.project)
    await proxy.ensure_cached(context, page)
    stored = await context.stat(page)
    if stored is None:
        return None
    await context.release()  # reading the page needs no connection
    reader = pages.Reader(parsed.project, _page_address(context, parsed.project))
    async for chunk in context.open(stored):
        link = await off_loop(_find, reader, chunk, parsed.filename)
        if link is not None:
            # A file has one address here: under the version in its name.
            return link if link.version == parsed.version else None
    return None


async def _proxied_file(
    context: RepositoryContext, request: Request, parsed: names.PypiPath, path: str
) -> Response:
    """A file, or the metadata file beside it, from the cache or from where the remote keeps it.

    A file on an index never changes once published, so one that is cached is never
    asked about again.
    """
    if await context.stat(path) is None:
        link = await _link_to(context, parsed)
        if link is None or (parsed.kind == "metadata" and link.metadata is None):
            raise _not_found("No such file.")
        if parsed.kind == "metadata":
            address, described = pages.metadata_address(link.url), link.metadata
        else:
            address, described = link.url, link.digest
        checked = pages.digest_of(described)
        source = proxy.Source(address, {} if checked is None else dict([checked]))
        await proxy.ensure_cached(context, path, source=source)
    return await context.respond(path, request)


class PypiFormat(Format):
    name = "pypi"
    # A group needs PyPI's own handling of index pages.
    types = frozenset({"hosted", "proxy"})
```

Replace

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        return _FILE if names.classify(path).kind == "file" else declared
```

with

```python
    def content_type(self, path: str, declared: str | None) -> str | None:
        kind = names.classify(path).kind
        if kind == "file":
            return _FILE
        if kind == "metadata":
            return _METADATA
        return pages.CONTENT_TYPE if kind == "page" else declared

    def remote_url(self, base: str, path: str) -> str:
        """Where a proxy finds a project's page on its remote.

        The remote is an index's root, or the index itself if its address ends in
        `/simple` (or devpi's `/+simple`). Nothing but a page is found by its path: a
        file is fetched from the address its page gives.
        """
        base = base.rstrip("/")
        index = base if base.rpartition("/")[2] in ("simple", "+simple") else f"{base}/simple"
        parsed = names.classify(path)
        if parsed.kind == "page":
            return f"{index}/{parsed.project}/"
        return super().remote_url(base, path)

    def is_metadata(self, path: str) -> bool:
        """A project's page changes with every release. A file never changes."""
        return names.classify(path).kind == "page"
```

After

```python
        if parsed.kind == "file":
            return await _file(context, request, path)
        raise _not_found()
```

add

```python
    async def handle_proxy(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = names.classify(path)
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind in ("index", "page"):
            moved = _canonical(parsed)
            if moved is not None:
                return moved
            if parsed.kind == "index":
                return await _root_index(context, request)
            return await _proxied_page(context, request, parsed.project)
        if parsed.kind in ("file", "metadata"):
            return await _proxied_file(context, request, parsed, path)
        raise _not_found()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/pypi/format.py backend/tests/repositories/pypi
git commit -m "feat(pypi): proxy repositories that write their own pages and fetch files from where the remote keeps them"
```

---

### Task 4: PyPI group repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/pypi/format.py`
- Test: `backend/tests/repositories/pypi/test_group.py`

**Interfaces:**
- Consumes: `group.leaves`, `group.owners`, `group.proxies`, `group.TRY_NEXT` (Task 1); `_written`, `_root_index(..., within)`, `_proxied_file` through the dispatcher, the helpers in `conftest.py` (Task 3); `context.package_files`.
- Produces: `PypiFormat.handle_group`; `PypiFormat.types` is no longer overridden, so the format offers all three types.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/pypi/test_group.py`:

```python
import hashlib

import pytest

from megooarti.repositories import service
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.pypi.conftest import (
    CONTENT_TYPE,
    content_of,
    create,
    form_body,
    link_to,
    links,
    remote_link,
    remote_page,
    upload,
    upload_fields,
)

GROUP = "/repository/everything"
OURS = "internal_tool-1.0.0.tar.gz"
THEIRS = "internal_tool-99.0.0.tar.gz"
PUBLIC = "requests-2.31.0.tar.gz"


@pytest.fixture
async def everything(db, index, upstream):
    """The hosted `pypi` and the proxy `upstream`, in that order."""
    return await create(db, "everything", type="group", group={"members": ["pypi", "upstream"]})


def names_on(response) -> list[str]:
    return [text for _, text in links(response)]


def asked(remote) -> list[tuple[str, str]]:
    return [(seen["host"], seen["path"]) for seen in remote.requests]


async def take_offline(db, name: str) -> None:
    repository = await service.get_repository(db, name)
    repository.online = False
    await db.commit()


def public_project(fake_remote, project: str, *filenames: str, index: str = "pypi") -> None:
    """Put a project on the fake remote: its page, and its files on the other host."""
    fake_remote.files[f"{index}/simple/{project}/"] = remote_page(project, *filenames)
    for filename in filenames:
        fake_remote.files[f"packages/{filename}"] = content_of(filename)


async def test_a_project_we_host_comes_from_us_and_the_remote_is_not_asked(
    client, root, everything, fake_remote
):
    await upload(client, root, OURS, requires_python=">=3.9")

    page = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    fetched = await client.get(str(page.url.join(links(page)[0][0]["href"])), headers=root)

    assert links(page) == [
        link_to("internal-tool", "1.0.0", OURS, **{"data-requires-python": ">=3.9"})
    ]
    assert fetched.url.path == f"{GROUP}/packages/internal-tool/1.0.0/{OURS}"  # through the group
    assert fetched.content == content_of(OURS)
    assert fake_remote.requests == []


async def test_a_project_only_the_remote_has_comes_through_the_proxy(
    client, root, everything, fake_remote
):
    public_project(fake_remote, "requests", PUBLIC)

    page = await client.get(f"{GROUP}/simple/requests/", headers=root)
    fetched = await client.get(str(page.url.join(links(page)[0][0]["href"])), headers=root)

    assert links(page) == [link_to("requests", "2.31.0", PUBLIC)]
    assert "Content-Length" not in page.headers  # written as it is sent
    assert fetched.url.path == f"{GROUP}/packages/requests/2.31.0/{PUBLIC}"
    assert fetched.content == content_of(PUBLIC)
    assert asked(fake_remote) == [
        ("remote.test", "/pypi/simple/requests/"),
        ("files.test", f"/packages/{PUBLIC}"),
    ]


async def test_a_public_project_cannot_add_files_to_a_name_we_host(
    client, root, everything, fake_remote
):
    # Dependency confusion: the same name on the public index, with a higher version.
    await upload(client, root, OURS)
    public_project(fake_remote, "internal-tool", THEIRS)

    page = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    theirs = await client.get(f"{GROUP}/packages/internal-tool/99.0.0/{THEIRS}", headers=root)
    described = await client.get(
        f"{GROUP}/packages/internal-tool/99.0.0/{THEIRS}.metadata", headers=root
    )

    assert names_on(page) == [OURS]
    for response in (theirs, described):
        assert (response.status_code, error_code(response)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_a_public_project_cannot_stand_in_for_a_file_we_host(
    client, root, db, index, upstream, fake_remote
):
    # The proxy is tried first here, and the remote has a file of the very same name.
    await create(db, "remote-first", type="group", group={"members": ["upstream", "pypi"]})
    await upload(client, root, OURS)
    fake_remote.files["pypi/simple/internal-tool/"] = remote_page(
        "internal-tool", remote_link(OURS, data=b"hostile")
    )
    fake_remote.files[f"packages/{OURS}"] = b"hostile"

    page = await client.get("/repository/remote-first/simple/internal-tool/", headers=root)
    fetched = await client.get(
        f"/repository/remote-first/packages/internal-tool/1.0.0/{OURS}", headers=root
    )

    assert links(page) == [link_to("internal-tool", "1.0.0", OURS)]  # with our hash
    assert fetched.content == content_of(OURS)
    assert fake_remote.requests == []


async def test_a_name_an_offline_repository_holds_is_not_answered_by_the_remote(
    client, root, everything, fake_remote, db
):
    await upload(client, root, OURS)
    public_project(fake_remote, "internal-tool", THEIRS)
    public_project(fake_remote, "requests", PUBLIC)
    await take_offline(db, "pypi")

    page = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    theirs = await client.get(f"{GROUP}/packages/internal-tool/99.0.0/{THEIRS}", headers=root)
    public = await client.get(f"{GROUP}/simple/requests/", headers=root)

    for response in (page, theirs):
        assert (response.status_code, error_code(response)) == (503, "repository_offline")
    assert names_on(public) == [PUBLIC]  # a name nobody here holds is still served
    assert asked(fake_remote) == [("remote.test", "/pypi/simple/requests/")]


async def test_a_name_held_behind_an_offline_group_is_not_answered_by_the_remote(
    client, root, db, index, upstream, fake_remote
):
    await create(db, "inner", type="group", group={"members": ["pypi"]})
    await create(db, "outer", type="group", group={"members": ["inner", "upstream"]})
    await upload(client, root, OURS)
    public_project(fake_remote, "internal-tool", THEIRS)
    await take_offline(db, "inner")

    response = await client.get("/repository/outer/simple/internal-tool/", headers=root)

    assert (response.status_code, error_code(response)) == (503, "repository_offline")
    assert fake_remote.requests == []


async def test_an_offline_proxy_is_left_out(client, root, everything, fake_remote, db):
    await upload(client, root, OURS)
    public_project(fake_remote, "requests", PUBLIC)
    await take_offline(db, "upstream")

    ours = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    theirs = await client.get(f"{GROUP}/simple/requests/", headers=root)

    assert names_on(ours) == [OURS]
    assert (theirs.status_code, error_code(theirs)) == (404, "not_found")
    assert fake_remote.requests == []


async def test_hosted_repositories_are_listed_together_and_the_earlier_one_wins(client, root, db):
    await create(db, "pypi")
    await create(db, "team")
    await create(db, "both", type="group", group={"members": ["pypi", "team"]})
    await upload(client, root, OURS)
    await upload(client, root, OURS, repository="team", data=b"the team's build")
    await upload(client, root, "internal_tool-2.0.0.tar.gz", repository="team")

    page = await client.get("/repository/both/simple/internal-tool/", headers=root)
    shared = await client.get(f"/repository/both/packages/internal-tool/1.0.0/{OURS}", headers=root)
    later = await client.get(
        "/repository/both/packages/internal-tool/2.0.0/internal_tool-2.0.0.tar.gz", headers=root
    )

    assert links(page) == [
        link_to("internal-tool", "1.0.0", OURS),  # the hash of the first repository's file
        link_to("internal-tool", "2.0.0", "internal_tool-2.0.0.tar.gz"),
    ]
    assert shared.content == content_of(OURS)
    assert later.content == content_of("internal_tool-2.0.0.tar.gz")


async def test_a_page_from_hosted_repositories_is_answered_like_any_content(
    client, root, everything
):
    await upload(client, root, OURS)
    first = await client.get(f"{GROUP}/simple/internal-tool/", headers=root)
    etag = first.headers["ETag"]

    unchanged = await client.get(
        f"{GROUP}/simple/internal-tool/", headers={**root, "If-None-Match": etag}
    )
    headed = await client.head(f"{GROUP}/simple/internal-tool/", headers=root)

    assert first.headers["Content-Type"] == "text/html; charset=utf-8"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert (unchanged.status_code, headed.status_code, headed.content) == (304, 200, b"")


@pytest.fixture
async def mirrors(db, fake_remote):
    """Proxies `first` and `second` of two indexes that both have requests, in one group."""
    await create(db, "first", type="proxy", proxy={"remote_url": "http://remote.test/a"})
    await create(db, "second", type="proxy", proxy={"remote_url": "http://remote.test/b"})
    shared = "requests-2.30.0.tar.gz"
    fake_remote.files["a/simple/requests/"] = remote_page(
        "requests", "requests-2.29.0.tar.gz", remote_link(shared, at="http://files.test/a")
    )
    fake_remote.files["b/simple/requests/"] = remote_page(
        "requests", remote_link(shared, at="http://files.test/b", data=b"b's build"), PUBLIC
    )
    fake_remote.files[f"a/packages/{shared}"] = content_of(shared)
    fake_remote.files[f"b/packages/{shared}"] = b"b's build"
    fake_remote.files[f"packages/{PUBLIC}"] = content_of(PUBLIC)
    return await create(db, "mirrors", type="group", group={"members": ["first", "second"]})


async def test_two_proxies_that_both_have_a_project_are_listed_together(
    client, root, mirrors, fake_remote
):
    page = await client.get("/repository/mirrors/simple/requests/", headers=root)
    again = await client.get(
        "/repository/mirrors/simple/requests/",
        headers={**root, "If-None-Match": page.headers["ETag"]},
    )
    shared = await client.get(
        "/repository/mirrors/packages/requests/2.30.0/requests-2.30.0.tar.gz", headers=root
    )
    theirs = await client.get(
        f"/repository/mirrors/packages/requests/2.31.0/{PUBLIC}", headers=root
    )

    # A file name both list is written once, as the earlier proxy describes it.
    assert links(page) == [
        link_to("requests", "2.29.0", "requests-2.29.0.tar.gz"),
        link_to("requests", "2.30.0", "requests-2.30.0.tar.gz"),
        link_to("requests", "2.31.0", PUBLIC),
    ]
    assert again.status_code == 304
    assert shared.content == content_of("requests-2.30.0.tar.gz")  # and served by that proxy
    assert theirs.content == content_of(PUBLIC)


async def test_a_proxy_that_cannot_answer_is_left_out(client, root, mirrors, fake_remote):
    del fake_remote.files["a/simple/requests/"]

    page = await client.get("/repository/mirrors/simple/requests/", headers=root)
    before = page.headers["ETag"]
    fake_remote.files["a/simple/flask/"] = remote_page("flask", "flask-3.0.0.tar.gz")
    only_first = await client.get("/repository/mirrors/simple/flask/", headers=root)

    assert names_on(page) == ["requests-2.30.0.tar.gz", PUBLIC]
    assert names_on(only_first) == ["flask-3.0.0.tar.gz"]
    assert only_first.headers["ETag"] != before


async def test_nobody_has_it(client, root, everything, fake_remote):
    missing = await client.get(f"{GROUP}/simple/no-such-project/", headers=root)
    fake_remote.down = True
    unreachable = await client.get(f"{GROUP}/simple/another-project/", headers=root)
    its_file = await client.get(
        f"{GROUP}/packages/another-project/1.0/another_project-1.0.tar.gz", headers=root
    )

    for response in (missing, unreachable, its_file):
        assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_a_group_inside_a_group(client, root, everything, fake_remote, db):
    await create(db, "extra")
    await create(db, "outer", type="group", group={"members": ["everything", "extra"]})
    await upload(client, root, OURS)
    await upload(client, root, "internal_tool-3.0.0.tar.gz", repository="extra")
    public_project(fake_remote, "requests", PUBLIC)

    ours = await client.get("/repository/outer/simple/internal-tool/", headers=root)
    theirs = await client.get("/repository/outer/simple/requests/", headers=root)
    fetched = await client.get(f"/repository/outer/packages/requests/2.31.0/{PUBLIC}", headers=root)

    assert names_on(ours) == [OURS, "internal_tool-3.0.0.tar.gz"]
    assert names_on(theirs) == [PUBLIC]
    assert fetched.content == content_of(PUBLIC)


async def test_a_metadata_file_comes_through_the_group(client, root, everything, fake_remote):
    metadata = b"Metadata-Version: 2.1\nName: requests\n"
    described = f'data-core-metadata="sha256={hashlib.sha256(metadata).hexdigest()}"'
    fake_remote.files["pypi/simple/requests/"] = remote_page(
        "requests", remote_link(PUBLIC, described)
    )
    fake_remote.files[f"packages/{PUBLIC}.metadata"] = metadata

    page = await client.get(f"{GROUP}/simple/requests/", headers=root)
    fetched = await client.get(f"{GROUP}/packages/requests/2.31.0/{PUBLIC}.metadata", headers=root)

    assert "data-core-metadata" in links(page)[0][0]
    assert (fetched.status_code, fetched.content) == (200, metadata)


async def test_reading_through_the_group_needs_read_on_the_group_only(
    client, root, everything, fake_remote, make_user, db
):
    await upload(client, root, OURS)
    public_project(fake_remote, "requests", PUBLIC)
    members = ["repository:pypi:pypi:read", "repository:pypi:upstream:read"]
    await roles.create_role(db, "group-readers", "", ["repository:pypi:everything:read"], [])
    await roles.create_role(db, "member-readers", "", members, [])
    await db.commit()
    await make_user("gina", roles=["group-readers"])
    await make_user("mel", roles=["member-readers"])
    gina, mel = basic("gina", PASSWORD), basic("mel", PASSWORD)

    ours = await client.get(f"{GROUP}/simple/internal-tool/", headers=gina)
    theirs = await client.get(f"{GROUP}/packages/requests/2.31.0/{PUBLIC}", headers=gina)
    refused = await client.get(f"{GROUP}/simple/internal-tool/", headers=mel)

    assert (names_on(ours), theirs.content) == ([OURS], content_of(PUBLIC))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")


async def test_a_group_cannot_be_written_to(client, root, everything):
    data = content_of(OURS)
    body = form_body(upload_fields("internal-tool", "1.0.0", data), (OURS, data))
    await upload(client, root, OURS)

    uploaded = await client.post(
        f"{GROUP}/", content=body, headers={**root, "Content-Type": CONTENT_TYPE}
    )
    removed = await client.delete(f"{GROUP}/packages/internal-tool/1.0.0/{OURS}", headers=root)

    for response in (uploaded, removed):
        assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
        assert response.headers["Allow"] == "GET, HEAD"


async def test_the_root_index_lists_every_project_behind_the_group_once(
    client, root, everything, fake_remote
):
    await upload(client, root, OURS)
    await upload(client, root, "zope.interface-6.0.tar.gz")
    public_project(fake_remote, "requests", PUBLIC)
    public_project(fake_remote, "zope-interface", "zope.interface-5.0.tar.gz")
    await client.get(f"/repository/upstream/packages/requests/2.31.0/{PUBLIC}", headers=root)
    await client.get(
        "/repository/upstream/packages/zope-interface/5.0/zope.interface-5.0.tar.gz", headers=root
    )

    listed = await client.get(f"{GROUP}/simple/", headers=root)
    moved = await client.get(f"{GROUP}/simple", headers=root)

    assert links(listed) == [
        ({"href": "internal-tool/"}, "internal-tool"),
        ({"href": "requests/"}, "requests"),
        ({"href": "zope-interface/"}, "zope-interface"),
    ]
    assert (moved.status_code, moved.headers["Location"]) == (301, "simple/")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/pypi -q`
Expected: every test in `test_group.py` fails or errors: `group repositories are not available for this format`. Everything else passes.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/pypi/format.py`:

Replace

```python
host, and must match the hash on that page. Reading a page is CPU-bound work whose size
a remote decides, so it runs on two worker threads of its own.
"""
```

with

```python
host, and must match the hash on that page. Reading a page is CPU-bound work whose size
a remote decides, so it runs on two worker threads of its own.

A group answers for a project from its hosted members if one of them holds it, and only
otherwise from its proxies: a public project must never add files to a private name.
That holds for the page and for the files alike.
"""
```

Replace

```python
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext, Stored
from megooarti.repositories.formats import ComponentKey, Format, register
```

with

```python
from megooarti.repositories import group, proxy
from megooarti.repositories.content import PackageFile, RepositoryContext, Stored
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
```

Before

```python
def _invalid(reason: object) -> ApiError:
```

add

```python
def _offline() -> ApiError:
    return ApiError(503, "repository_offline", "A repository that holds this project is offline.")
```

Replace

```python
async def _project_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A hosted project's page, from the files stored. `project` is in its normal form."""
    files = await context.package_files("", project)
    if not files:
        raise _not_found("No such project.")
    await context.release()  # writing the page needs no connection
    links = [
        pages.Link(
            filename=held.path.rpartition("/")[2],
            version=held.version,
            digest=f"sha256={held.sha256}",
            requires_python=(held.attributes.get(_DECLARED) or {}).get("requires_python"),
        )
        for held in files
    ]
    return _page(context, request, pages.project_page(project, links))
```

with

```python
def _links(files: Sequence[PackageFile]) -> list[pages.Link]:
    """What a page says of the files a hosted repository holds."""
    return [
        pages.Link(
            filename=held.path.rpartition("/")[2],
            version=held.version,
            digest=f"sha256={held.sha256}",
            requires_python=(held.attributes.get(_DECLARED) or {}).get("requires_python"),
        )
        for held in files
    ]


async def _project_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A hosted project's page, from the files stored. `project` is in its normal form."""
    files = await context.package_files("", project)
    if not files:
        raise _not_found("No such project.")
    await context.release()  # writing the page needs no connection
    return _page(context, request, pages.project_page(project, _links(files)))
```

Replace

```python
class PypiFormat(Format):
    name = "pypi"
    # A group needs PyPI's own handling of index pages.
    types = frozenset({"hosted", "proxy"})
```

with

```python
# --- What a group serves -------------------------------------------------------------


async def _group_page(context: RepositoryContext, request: Request, project: str) -> Response:
    """A project's page from the repositories behind a group that answer for it."""
    leaves = await group.leaves(context)
    owners, offline = await group.owners(leaves, "", project)
    if owners:
        links: dict[str, pages.Link] = {}
        for owner in owners:
            for link in _links(await owner.package_files("", project)):
                links.setdefault(link.filename, link)  # the earlier repository's
        if not links:
            raise _not_found("No such project.")  # its last file went between the two questions
        await context.release()  # writing the page needs no connection
        return _page(context, request, pages.project_page(project, links.values()))
    if offline:
        raise _offline()

    page = names.page_path(project)
    sources = []
    for member in group.proxies(leaves):
        try:
            await proxy.ensure_cached(member, page)
        except ApiError as error:
            # A proxy that cannot answer is left out: the group answers from the others.
            if error.status_code not in group.TRY_NEXT:
                raise
            continue
        stored = await member.stat(page)
        if stored is not None:
            sources.append((member, stored))
    if not sources:
        raise _not_found("No such project.")
    return await _written(context, request, project, sources)


async def _group_file(
    context: RepositoryContext, request: Request, parsed: names.PypiPath, path: str, serve: Serve
) -> Response:
    """A file, from the same repositories that answer for its project's page."""
    leaves = await group.leaves(context)
    owners, offline = await group.owners(leaves, "", parsed.project)
    if not owners and offline:
        raise _offline()
    for member in owners or group.proxies(leaves):
        try:
            return await serve(member, request, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    raise _not_found("No such file.")


class PypiFormat(Format):
    name = "pypi"
```

After

```python
        if parsed.kind in ("file", "metadata"):
            return await _proxied_file(context, request, parsed, path)
        raise _not_found()
```

add

```python
    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        parsed = names.classify(path)
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        if parsed.kind in ("index", "page"):
            moved = _canonical(parsed)
            if moved is not None:
                return moved
            if parsed.kind == "page":
                return await _group_page(context, request, parsed.project)
            online = [leaf.context for leaf in await group.leaves(context) if leaf.online]
            return await _root_index(context, request, online)
        if parsed.kind in ("file", "metadata"):
            return await _group_file(context, request, parsed, path, serve)
        raise _not_found()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/pypi/format.py backend/tests/repositories/pypi/test_group.py
git commit -m "feat(pypi): group repositories in which a public project cannot take a private name"
```

---

### Task 5: pip, uv and Poetry through a group; documentation

**Files:**
- Modify: `backend/tests/test_pypi_client.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-08-pypi-format-design.md`

**Interfaces:**
- Consumes: PyPI hosted, proxy and group repositories; `tests/containers.py` (`HTTP_PORT`, `PROJECT`, `call`); the `stack` and `administrator` fixtures.
- Produces: a Docker-marked test in which the three installers install through a group.

These tests run only with `pytest -m docker`. They need a Docker daemon and internet access: the backend container fetches from `https://pypi.org` and `https://files.pythonhosted.org`.

- [ ] **Step 1: Write the real-client test**

The file is replaced. The test of plan 6a is unchanged but for how it names its package to the script that builds it; a second test is added.

`backend/tests/test_pypi_client.py`:

```python
"""Python's own packaging tools against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to
pull the Python image, to install twine and uv into it from pypi.org for the first
test, and for the proxy of pypi.org that the second test installs everything through.
"""

import subprocess
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "python:3.13-slim"
NETWORK = f"{PROJECT}_default"
HOSTED = "pypi-hosted"
PROXY = "pypi-proxy"
GROUP = "pypi-public"
# What a publishing account gets: everything on PyPI repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "uploads-and-installs-python-packages"
PROJECT_NAME = "megooarti-greeter"
# Uploaded to the hosted repository and installed through the group. It requires PUBLIC.
OURS = "megooarti-grouped"
# A real public package with no dependencies, and the name of another one.
PUBLIC = "six"
TAKEN = "sampleproject"

# Writes a wheel and a source distribution of one small package into dist/, with the
# standard library only: `make_dist.py <name> <version> [<requirement> ...]`.
MAKE_DIST = """
import base64, hashlib, io, sys, tarfile, zipfile
from pathlib import Path

name, version, requirements = sys.argv[1], sys.argv[2], sys.argv[3:]
module = name.replace("-", "_")
metadata = (
    "Metadata-Version: 2.1\\n"
    f"Name: {name}\\nVersion: {version}\\nSummary: Says hello\\nRequires-Python: >=3.9\\n"
    + "".join(f"Requires-Dist: {requirement}\\n" for requirement in requirements)
)
code = f'def hello():\\n    return "hello from {name} {version}"\\n'
dist = Path("dist")
dist.mkdir(exist_ok=True)

info = f"{module}-{version}.dist-info"
files = {
    f"{module}/__init__.py": code,
    f"{info}/METADATA": metadata,
    f"{info}/WHEEL": (
        "Wheel-Version: 1.0\\nGenerator: megooarti\\n"
        "Root-Is-Purelib: true\\nTag: py3-none-any\\n"
    ),
}
record = ""
for path, text in files.items():
    digest = base64.urlsafe_b64encode(hashlib.sha256(text.encode()).digest()).rstrip(b"=")
    record += f"{path},sha256={digest.decode()},{len(text.encode())}\\n"
files[f"{info}/RECORD"] = record + f"{info}/RECORD,,\\n"
with zipfile.ZipFile(dist / f"{module}-{version}-py3-none-any.whl", "w") as wheel:
    for path, text in files.items():
        wheel.writestr(path, text)

project = (
    '[build-system]\\nrequires = ["setuptools"]\\nbuild-backend = "setuptools.build_meta"\\n'
    f'[project]\\nname = "{name}"\\nversion = "{version}"\\n'
)
sources = {"PKG-INFO": metadata, "pyproject.toml": project, f"{module}/__init__.py": code}
with tarfile.open(dist / f"{module}-{version}.tar.gz", "w:gz") as sdist:
    for path, text in sources.items():
        entry = tarfile.TarInfo(f"{module}-{version}/{path}")
        entry.size = len(text.encode())
        sdist.addfile(entry, io.BytesIO(text.encode()))
"""


def inside(repository: str) -> str:
    """A repository's address as a container on the Compose network reaches it."""
    return f"http://backend:8000/repository/{repository}/"


def python(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Python image, in a copy of `directory`, beside the stack.

    Every run is a new container, so every tool starts with an empty cache.
    """
    setup = "cp -r /src /work && cd /work && export PIP_DISABLE_PIP_VERSION_CHECK=1"
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


# A shell function for a script that goes on after a failure: `command; report <step>`
# prints the command's exit code on a line of its own.
REPORT = 'report() { code=$?; printf \'\\n%s=%s\\n\' "$1" "$code"; }'


def exits(result: subprocess.CompletedProcess[str]) -> dict[str, int]:
    """The exit codes a script reported with `report <step>`."""
    lines = (line.partition("=") for line in result.stdout.splitlines())
    return {step: int(code) for step, _, code in lines if code.isdigit() and " " not in step}


def fetch(
    path: str,
    username: str = USERNAME,
    secret: str = PASSWORD,
    *,
    repository: str = HOSTED,
    method: str = "GET",
) -> tuple[int, str]:
    """A request to a repository from outside: (status, body as text)."""
    credentials = b64encode(f"{username}:{secret}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}/repository/{repository}/{path}",
        method=method,
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, ""


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted PyPI repository, a publishing account, and an API token of that account."""
    repository = {
        "name": HOSTED,
        "format": "pypi",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    role = {"name": "pypi-publishers", "permissions": ["repository:pypi"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["pypi-publishers"],
        "must_change_password": False,
    }
    for path, body in (("/repositories", repository), ("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer

    status, headers, session = call(
        "POST", "/auth/login", {"username": USERNAME, "password": PASSWORD}
    )
    assert status == 200, session
    signed_in = {
        "Cookie": headers["Set-Cookie"].split(";")[0],
        "X-CSRF-Token": session["csrf_token"],
    }
    status, _, created = call("POST", "/me/tokens", {"name": "publishing"}, signed_in)
    assert status == 201, created
    return created["token"]


def test_twine_and_uv_publish_and_pip_installs(token, tmp_path):
    work = tmp_path / "pypi"
    work.mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    index = f"http://{USERNAME}:{PASSWORD}@backend:8000/repository/{HOSTED}/simple/"
    token_index = f"http://__token__:{token}@backend:8000/repository/{HOSTED}/simple/"

    # twine uploads a wheel and a source distribution with a user name and a password.
    # A second upload of the same files is refused.
    twine = (
        f"twine upload --non-interactive --disable-progress-bar --repository-url {inside(HOSTED)}"
    )
    account = f"-u {USERNAME} -p {PASSWORD}"
    published = python(
        work,
        f"{REPORT}; pip install --quiet twine && python make_dist.py {PROJECT_NAME} 1.0.0"
        f" && {twine} {account} dist/*; report first"
        f"; {twine} {account} dist/*; report again",
    )
    codes = exits(published)
    assert codes.get("first") == 0, said(published)
    assert codes.get("again") not in (0, None), "uploaded twice despite disable_redeploy"

    # uv publishes the next version with nothing but a token, as the user `__token__`.
    # Told where the index is, it passes over files that are already there. It does not
    # send the token to the index by itself, so the address carries it.
    uv = f"uv publish --publish-url {inside(HOSTED)} --token {token}"
    by_token = python(
        work,
        f"{REPORT}; pip install --quiet uv && python make_dist.py {PROJECT_NAME} 1.1.0"
        f" && {uv} dist/*; report first"
        f"; {uv} dist/*; report again"
        f"; {uv} --check-url {token_index} dist/*; report checked",
    )
    codes = exits(by_token)
    assert codes.get("first") == 0, said(by_token)
    assert codes.get("again") not in (0, None), "uploaded twice despite disable_redeploy"
    assert codes.get("checked") == 0, said(by_token)

    # What the index says now.
    status, root_index = fetch("simple/")
    assert (status, f'<a href="{PROJECT_NAME}/">' in root_index) == (200, True)
    status, page = fetch(f"simple/{PROJECT_NAME}/", "__token__", token)
    assert status == 200
    for version in ("1.0.0", "1.1.0"):
        assert f">megooarti_greeter-{version}-py3-none-any.whl</a>" in page
        assert f">megooarti_greeter-{version}.tar.gz</a>" in page
    assert page.count('data-requires-python="&gt;=3.9"') == 4
    assert page.count("#sha256=") == 4

    # pip installs the newest version from an empty cache, then one it is asked for.
    pip = f"pip install --quiet --index-url {index} --trusted-host backend"
    run_it = 'python -c "import megooarti_greeter; print(megooarti_greeter.hello())"'
    installed = python(
        work, f"{pip} {PROJECT_NAME} && {run_it} && {pip} {PROJECT_NAME}==1.0.0 && {run_it}"
    )
    assert installed.returncode == 0, said(installed)
    assert installed.stdout.splitlines()[-2:] == [
        f"hello from {PROJECT_NAME} 1.1.0",
        f"hello from {PROJECT_NAME} 1.0.0",
    ]

    # uv installs it too, with the token.
    with_uv = python(
        work,
        "pip install --quiet uv"
        f" && uv pip install --system --index-url {token_index} {PROJECT_NAME}==1.1.0"
        f" && {run_it}",
    )
    assert with_uv.returncode == 0, said(with_uv)
    assert with_uv.stdout.splitlines()[-1] == f"hello from {PROJECT_NAME} 1.1.0"


@pytest.fixture(scope="module")
def group_index(token, administrator) -> str:
    """A proxy of pypi.org and a group of the hosted repository and it.

    Returns the group's index address as a container reaches it, with the token in it.
    """
    proxy = {
        "name": PROXY,
        "format": "pypi",
        "type": "proxy",
        "proxy": {"remote_url": "https://pypi.org"},
    }
    public = {
        "name": GROUP,
        "format": "pypi",
        "type": "group",
        "group": {"members": [HOSTED, PROXY]},
    }
    for body in (proxy, public):
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    return f"http://__token__:{token}@backend:8000/repository/{GROUP}/simple/"


def test_pip_uv_and_poetry_install_through_a_group(token, group_index, tmp_path):
    work = tmp_path / "group"
    (work / "consumer").mkdir(parents=True)
    (work / "published").mkdir()
    (work / "make_dist.py").write_text(MAKE_DIST, encoding="utf-8", newline="\n")
    source = f'[[tool.poetry.source]]\nname = "megooarti"\nurl = "{inside(GROUP)}simple/"\n'
    (work / "consumer" / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "consumer"\nversion = "1.0.0"\ndescription = ""\n'
        'authors = ["CI <ci@example.com>"]\npackage-mode = false\n\n'
        f'[tool.poetry.dependencies]\npython = ">=3.9"\n{OURS} = "1.0.0"\n\n'
        f'{source}priority = "primary"\n',
        encoding="utf-8",
        newline="\n",
    )
    (work / "published" / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "megooarti-poetic"\nversion = "1.0.0"\ndescription = "x"\n'
        'authors = ["CI <ci@example.com>"]\npackages = [{include = "megooarti_poetic.py"}]\n\n'
        '[build-system]\nrequires = ["poetry-core"]\nbuild-backend = "poetry.core.masonry.api"\n',
        encoding="utf-8",
        newline="\n",
    )
    (work / "published" / "megooarti_poetic.py").write_text("VALUE = 1\n", encoding="utf-8")
    # Every tool is itself installed through the group: many real packages by the proxy.
    pip = f"pip install --quiet --index-url {group_index} --trusted-host backend"
    twine = (
        "twine upload --non-interactive --disable-progress-bar"
        f" --repository-url {inside(HOSTED)} -u __token__ -p {token}"
    )
    run_it = (
        f'python -c "import megooarti_grouped, {PUBLIC};'
        f' print(megooarti_grouped.hello(), {PUBLIC}.__name__)"'
    )
    expected = f"hello from {OURS} 1.0.0 {PUBLIC}"

    # Our own package, which requires a public one, and our own package under a name
    # the public index has too. twine sends the token as Python tools do.
    published = python(
        work,
        f"{pip} twine && python make_dist.py {OURS} 1.0.0 {PUBLIC}"
        f" && python make_dist.py {TAKEN} 99.0.0 && {twine} dist/*",
    )
    assert published.returncode == 0, said(published)

    # What the group says: the public project from the proxy, with its links here, and
    # under the name we host only what we host.
    status, public = fetch(f"simple/{PUBLIC}/", repository=GROUP)
    assert status == 200
    assert public.count(f'href="../../packages/{PUBLIC}/') > 10
    assert "pythonhosted.org" not in public and "data-core-metadata" in public
    assert fetch(f"simple/{PUBLIC}/", repository=GROUP, method="HEAD")[0] == 200
    status, taken = fetch(f"simple/{TAKEN}/", repository=GROUP)
    assert (status, taken.count("<a ")) == (200, 2)
    assert f">{TAKEN}-99.0.0-py3-none-any.whl</a>" in taken
    status, upstream = fetch(f"simple/{TAKEN}/", repository=PROXY)
    assert status == 200 and "99.0.0" not in upstream and upstream.count("<a ") > 2

    # Each client installs our package, and through it the public one, from an empty cache.
    clients = {
        "pip": f"{pip} {OURS} && {run_it}",
        "uv": f"{pip} uv && uv pip install --system --index-url {group_index} {OURS} && {run_it}",
        "poetry": (
            f"{pip} poetry && export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring"
            f" && poetry config http-basic.megooarti __token__ {token}"
            " && cd consumer && poetry install --no-interaction"
            f" && poetry run {run_it}"
        ),
    }
    for client, script in clients.items():
        installed = python(work, script)
        assert installed.returncode == 0, f"{client}: {said(installed)}"
        assert installed.stdout.splitlines()[-1] == expected, f"{client}: {said(installed)}"

    # What was installed came through the proxy, and is cached there.
    status, cached = fetch("simple/", repository=PROXY)
    assert status == 200 and f'<a href="{PUBLIC}/">' in cached

    # Poetry builds a package of its own and publishes it to the hosted repository.
    by_poetry = python(
        work,
        f"{pip} poetry && export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring"
        f" && cd published && poetry config repositories.hosted {inside(HOSTED)}"
        f" && poetry publish --build --no-interaction -r hosted -u __token__ -p {token}",
    )
    assert by_poetry.returncode == 0, said(by_poetry)
    status, poetic = fetch("simple/megooarti-poetic/")
    assert (status, poetic.count("<a ")) == (200, 2)
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_pypi_client.py -q`
Expected: 2 passed. This builds the image from the working tree, so it is the first run of the three installers against this plan's code. If a tool fails, the assertion message carries the end of its output.

- [ ] **Step 3: Document PyPI proxies and groups**

In `README.md`:

Replace

```markdown
`raw` (arbitrary files by path), `maven`, `npm` and `pypi` (hosted repositories only,
for now).
```

with

```markdown
`raw` (arbitrary files by path), `maven`, `npm` and `pypi`.
```

After

````markdown
pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-hosted/simple/ my-package
```
````

add

````markdown
A proxy caches pypi.org, and a group puts your own packages and the public ones behind
one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-proxy", "format": "pypi", "type": "proxy",
  "proxy": {"remote_url": "https://pypi.org"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-public", "format": "pypi", "type": "group",
  "group": {"members": ["pypi-hosted", "pypi-proxy"]}
}' http://localhost:8000/api/v1/repositories
```

Install through the group, and upload to the hosted repository:

```bash
pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-public/simple/ my-package
uv pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-public/simple/ my-package
```

For Poetry, name the group as the project's primary source and give it the token:

```toml
[[tool.poetry.source]]
name = "megooarti"
url = "https://repo.example.com/repository/pypi-public/simple/"
priority = "primary"
```

```bash
poetry config http-basic.megooarti __token__ "$MEGOOARTI_TOKEN"
```
````

Replace

```markdown
  distributions (`.tar.gz`, `.zip`) are taken; the file's name must fit its project.
  `poetry publish` sends the same request as twine.
```

with

```markdown
  distributions (`.tar.gz`, `.zip`) are taken; the file's name must fit its project.
  `poetry publish` sends the same request as twine, and is tested too.
```

Replace

```markdown
- Signatures sent with an upload are not kept. The JSON index (PEP 691), metadata
  files (PEP 658) and yanking are not available yet; pip, uv and Poetry do not need
  them.
- Proxy and group PyPI repositories are not available yet.
```

with

```markdown
- Signatures sent with an upload are not kept. The JSON index (PEP 691) and yanking a
  release on a hosted repository are not available yet; pip, uv and Poetry do not
  need them.
- **A proxy** keeps the remote's page for each project and writes its own from it,
  with every link pointed at MegooArti, so files are downloaded through it and cached.
  The remote's marks for yanked files, required Python versions and metadata files
  (PEP 658) are passed on, and the metadata files themselves are fetched and cached
  like any file. A project's page is checked again with the remote after
  `metadata_max_age_minutes`; a file, once cached, is never asked about again.
- **The remote address** of a proxy is the index's root (`https://pypi.org`), or the
  index itself if the address ends in `/simple` (or devpi's `/+simple`).
- **A proxy fetches each file from the address the remote's page gives for it**, which
  for pypi.org is another host. The file must match the hash on the page, or it is
  not kept (`502`). The remote's credentials are sent only to the remote's own scheme,
  host and port. A file address on a loopback, link-local or private network is
  refused unless the remote itself is at that host.
- **A group protects the names you upload.** If a hosted member holds a project, only
  hosted members answer for it, for its page and its files alike: a project on the
  public index with the same name as one of yours cannot add a file to it or stand in
  for one (the dependency-confusion attack). While that hosted repository is offline
  the group answers `503` for the project. A name is protected while a hosted
  repository holds a file of it.
- **A group lists a project once**, from all the hosted members that hold it, or from
  all the proxies that have it. A file name two members list is taken from the earlier
  one.
- The root index (`simple/`) of a proxy lists the projects it has cached a file of,
  not the remote's; a group lists those of all its members.
- **Clients.** Installs are tested with pip, uv and Poetry; uploads with twine,
  `uv publish` and `poetry publish`.

Reading through a group needs `read` on the group only, for example
`repository:pypi:pypi-public:read`.
```

- [ ] **Step 4: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-08-pypi-format-design.md`:

Replace

```markdown
**Reading the remote's page.** Links are read out of the page as it streams: each `<a>` with an `href`, its attributes and its text. The page is never held in memory, and nothing else on it is used. From each link:
```

with

```markdown
**Reading the remote's page.** Links are read out of the page as it streams: the opening tag of each `<a>` with an `href`, and its attributes. The page is never held in memory, and nothing else on it is used. A tag is settled before anything after it is looked at, so what is read does not depend on the pieces the page arrives in. Reading is CPU-bound work whose size the remote decides: it runs on two worker threads of its own, as npm's documents do. From each link:
```

Replace

```markdown
  - *Plan 6b:* `pip`, `uv` and Poetry each install a project, from an empty cache, through a group of the hosted repository and a proxy of pypi.org. The project depends on the package uploaded to the hosted repository and on one small public package. A package uploaded under a name pypi.org also has is listed through the group with our files only.
```

with

```markdown
  - *Plan 6b:* `pip`, `uv` and Poetry each install a package uploaded to the hosted repository, and through it one small public package it requires, from an empty cache, through a group of the hosted repository and a proxy of pypi.org. The tools themselves are installed through the group. A package uploaded under a name pypi.org also has is listed through the group with our files only. `poetry publish` uploads a package it built.
```

After

```markdown
| A client asks for the JSON index and gets HTML. | PEP 691 requires clients to accept that, and pip, uv and Poetry do. |
```

add

```markdown
| A remote answers a plain request for a page with the JSON index. | The proxy then finds no links and the project has no files. pypi.org, Artifactory, Nexus and devpi answer with HTML. Asking for HTML by name can be added to the remote client if an index needs it. |
| A proxy's page is read and written again for every request that does not carry its `ETag`. | A page of pypi.org's largest projects (about 2 MiB, four thousand files) takes about 0.15 s of a worker thread. Clients revalidate with `ETag`, which is answered without reading anything. |
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

Run: `uv run pytest -m docker -q`
Expected: 16 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_pypi_client.py README.md docs/superpowers/specs/2026-10-08-pypi-format-design.md
git commit -m "test(pypi): install through a group with pip, uv and Poetry; document PyPI proxies and groups"
```
