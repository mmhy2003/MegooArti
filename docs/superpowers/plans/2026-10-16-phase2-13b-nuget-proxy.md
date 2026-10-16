# NuGet V3 Proxies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A NuGet proxy caches nuget.org, or any V3 feed, so that .NET builds restore through MegooArti, find packages with `dotnet package search`, and see newer versions with `dotnet list package --outdated`, without reaching the feed themselves.

**Architecture:** Three changes to the proxy engine every format shares: a small document may come gzipped where the remote is known to send one so (nuget.org's registrations), `proxy.document` keeps such a document as metadata, and a format may read a file its proxy fetched (`Format.describe_fetched`) so that a cached package is described as a pushed one is. Then the NuGet proxy, in `nuget/proxied.py`: it reads the feed's service index (`nuget/remotes.py`), serves one of its own, keeps packages as every proxy keeps files, keeps registrations as metadata and passes them on with the feed's addresses made its own, and passes searches on. The three things plan 13a's review left are mended on the way.

**Tech Stack:** Python 3.13, FastAPI, httpx; pytest with the in-process stand-in remote; the .NET SDKs 10 and 8 against nuget.org for the real-client tests.

**Spec:** [docs/superpowers/specs/2026-10-15-nuget-design.md](../specs/2026-10-15-nuget-design.md), sections 6, 9, 10 and the row of plan 13b in section 12, with what plan 13a settled (W in section 4).

## Decisions this plan settles

Task 4 writes these into the spec's section 4, as "Settled while building plan 13b".

| # | Decision | Reason |
| --- | --- | --- |
| X1 | A proxy's remote is a feed's service index, kept as metadata under `.remote/index.json`, a path no client asks for. Of it the proxy uses `PackageBaseAddress/3.0.0`, one registration (`3.6.0` first: SemVer 2.0.0), and search and autocomplete (`3.5.0` first); a feed without a package address or a registration is refused with `502`. The proxy's own `index.json` offers no place to push to, and no search where the feed has none. | 6: where the feed serves each resource is the feed's to say, as it is for NuGet's clients. |
| X2 | A registration the feed sends gzipped whatever it is asked for is inflated, to 32 MiB; no other document is taken gzipped. | nuget.org's registrations are stored gzipped and served so, `Accept-Encoding: identity` or not. |
| X3 | What is kept of a registration is what the feed sent; the addresses in it are made the proxy's as it is sent: each of the feed's registrations, of whatever kind, becomes the proxy's one registration, and its package address the proxy's. A page or a version's document is asked of the feed's registration by the same path. The catalog's addresses are left as they are. | A search or a dependency names any of the feed's registrations; restore never reads the catalog. |
| X4 | A package and its `.nuspec` fetched through a proxy are read as pushed ones are (`Format.describe_fetched`, a member every format has), and their version is a component spelled as its package spells its id. They are kept for the proxy's content age, as every proxy's files are: `-1` keeps them for good, as 6 says, and a package asked about again costs the feed a `304`. | One way of describing a package, however it arrives; the proxy settings are every proxy's. |
| X5 | A search and an autocomplete are passed on with the client's query as it came, and their answers are not kept: a feed that cannot be reached answers `502`. | D5: a search is the feed's. |
| X6 | `format_config.protocol` is `v3` until plan 13d (a V2 feed is refused with `422`), fixed once the proxy is made; `format_config.symbol_url` is checked as a remote's address is, and kept without its last slash. | D2, and plan 13f's symbol server. |
| X7 | Over plain HTTP, the setup's `dotnet` command marks the source with `--allow-insecure-connections`, which the .NET SDK 9 and later take, and says that .NET 8 leaves it out (in place of W16). | The .NET SDK 9 has the option; 8 does not. |
| X8 | A hosted registration with no version left to show is `404`. | Its last version may go between its two reads. |

## Global Constraints

- **A format never touches a table or a file**: what the NuGet proxy needs of the cache is the proxy engine's (`proxy.ensure_cached`, `proxy.document`, `proxy.ask`, `proxy.refuse`) and the context's.
- **What is read of a remote is bounded**: the service index at 1 MiB, a registration document at 32 MiB (inflated), a search's answer at 8 MiB.
- **The remote's credential goes to the remote's own origin only**: a resource on another host (nuget.org's search) is asked without it, as the engine does for any address a remote's content names (`proxy.Source`).
- **Every test of a stack is marked `docker`.** The proxy's real-client tests reach nuget.org.
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **Feeds that are not nuget.org**: Azure Artifacts, GitHub Packages, a MyGet or ProGet feed, another MegooArti; a service index with relative addresses, two entries of one type, or a registration at the same host as the index; a feed that wants credentials on its search host.
2. **A registration the feed changes between its index and its pages**: a page fetched after a new version was published, a page address that the index no longer names, a page the proxy kept from an older index.
3. **Very large registrations**: an id whose pages run to tens of megabytes, and the 32 MiB bound that turns it into a `502`.
4. **What a cached package says**: a package from the feed whose `.nuspec` cannot be read, an id whose case differs between the feed's addresses and its `.nuspec`, a version normalized differently by the feed.
5. **A feed that is down or slow**: the service index kept from before, a search with nothing kept to fall back on, the proxy's blocking after failures, and a group (plan 13c) behind it.

---

### Task 1: What the proxy engine keeps of a remote's documents, and reads of its files

**Files:**
- Modify: `backend/src/megooarti/repositories/remote.py`, `proxy.py`, `content.py`, `formats.py`; `docs/adding-a-format.md`
- Modify (tests): `backend/tests/repositories/fake_remote.py`
- Create (tests): `backend/tests/repositories/test_proxy_documents.py`

**Interfaces:**
- Consumes: `remote.fetch`, `proxy.ask`, `proxy._refresh`, `RepositoryContext.cache`, `RepositoryContext.stage_bytes`, `RepositoryContext.read`.
- Produces: `remote.fetch(..., gzipped=False)`; `proxy.Source.gzipped: bool = False`; `proxy.document(context, path, source, *, limit, content_type) -> bytes` (raises 404 or 502, commits); `Format.describe_fetched(context, path, staged) -> dict[str, Any]` (nothing for the generic format), whose result the engine keeps with a fetched file and as its component's attributes; `RepositoryContext.cache(..., component_attributes=None)`. In the tests, `FakeRemote.encodings` (a Content-Encoding for one path) and each request's `query`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/fake_remote.py`:

```diff
@@ -49,6 +49,8 @@ class FakeRemote:
         self.delay = 0.0
         self.set_cookie: str | None = None
         self.content_encoding: str | None = None
+        # A Content-Encoding for one path only, as nuget.org gzips its registrations alone.
+        self.encodings: dict[str, str] = {}
         self.app = Starlette(routes=[Route("/{path:path}", self._serve, methods=["GET"])])
 
     def client(self) -> httpx.AsyncClient:
@@ -63,6 +65,7 @@ class FakeRemote:
                 "method": request.method,
                 "host": request.url.hostname,
                 "path": request.url.path,
+                "query": request.url.query,
                 # As it was written in the request, before any escape was decoded.
                 "raw_path": request.scope["raw_path"].decode("ascii"),
                 "headers": dict(request.headers),
@@ -88,6 +91,7 @@ class FakeRemote:
         }
         if self.set_cookie:
             headers["Set-Cookie"] = self.set_cookie
-        if self.content_encoding:
-            headers["Content-Encoding"] = self.content_encoding
+        encoding = self.encodings.get(request.url.path.lstrip("/"), self.content_encoding)
+        if encoding:
+            headers["Content-Encoding"] = encoding
         return Response(b"" if request.method == "HEAD" else content, headers=headers)
```

Create `backend/tests/repositories/test_proxy_documents.py`:

```python
"""A remote's small documents kept as metadata, gzipped ones among them, and what a format
reads of a file its proxy fetched."""

import gzip

import pytest

from megooarti.errors import ApiError
from megooarti.repositories import proxy, service
from megooarti.repositories.proxy import Answer, Source, Unavailable
from megooarti.repositories.raw import RawFormat
from tests.repositories.conftest import someone

REMOTE = "http://remote.test/files"
DOCUMENT = b'{"versions": ["1.0.0"]}'


@pytest.fixture
async def documents(db):
    """A proxy that asks its remote about a document every time it is asked for one."""
    repository = await service.create_repository(
        db,
        name="documents",
        format="raw",
        type="proxy",
        online=True,
        blob_store=None,
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0, "content_max_age_minutes": 0},
    )
    await db.commit()
    return repository


@pytest.fixture
async def context(documents, context_for, fake_remote, app):
    return await context_for(documents, someone("repository:*"), outbound=lambda: app.state.http)


async def test_a_gzipped_document_is_inflated_where_the_remote_is_known_to_send_one(
    context, fake_remote
):
    fake_remote.files["files/index.json"] = gzip.compress(DOCUMENT)
    fake_remote.content_encoding = "gzip"

    inflated = await proxy.ask(
        context, "index.json", Source(f"{REMOTE}/index.json", gzipped=True), limit=1000
    )
    refused = await proxy.ask(context, "index.json", Source(f"{REMOTE}/index.json"), limit=1000)

    assert isinstance(inflated, Answer) and inflated.body == DOCUMENT
    assert isinstance(refused, Unavailable)


async def test_a_gzipped_document_is_held_to_its_bound_once_inflated(context, fake_remote):
    fake_remote.files["files/index.json"] = gzip.compress(b"x" * 5000)
    fake_remote.content_encoding = "gzip"

    answer = await proxy.ask(
        context, "index.json", Source(f"{REMOTE}/index.json", gzipped=True), limit=1000
    )

    assert isinstance(answer, Unavailable)


async def test_a_document_is_kept_and_given_again_when_the_remote_cannot_be_asked(
    context, fake_remote
):
    fake_remote.files["files/index.json"] = DOCUMENT
    source = Source(f"{REMOTE}/index.json")

    first = await proxy.document(
        context, "index.json", source, limit=1000, content_type="application/json"
    )
    fake_remote.files["files/index.json"] = b'{"versions": ["1.0.0", "2.0.0"]}'
    second = await proxy.document(
        context, "index.json", source, limit=1000, content_type="application/json"
    )
    fake_remote.down = True
    third = await proxy.document(
        context, "index.json", source, limit=1000, content_type="application/json"
    )

    assert first == DOCUMENT
    assert second == third == b'{"versions": ["1.0.0", "2.0.0"]}'  # asked again: its age is 0
    assert (await context.stat("index.json")).content_type == "application/json"


async def test_a_document_the_remote_never_had_is_not_found(context, fake_remote):
    with pytest.raises(ApiError) as missing:
        await proxy.document(
            context,
            "absent.json",
            Source(f"{REMOTE}/absent.json"),
            limit=1000,
            content_type="application/json",
        )

    assert missing.value.status_code == 404


async def test_what_a_format_reads_of_a_fetched_file_is_kept_with_it_and_its_component(
    context, fake_remote, monkeypatch
):
    async def describe(self, context, path, staged):
        return {"read": {"title": "Hello"}}

    monkeypatch.setattr(RawFormat, "describe_fetched", describe)
    fake_remote.files["files/docs/hello.txt"] = b"hello"

    await proxy.ensure_cached(context, "docs/hello.txt")

    asset = await context.get("docs/hello.txt")
    assert asset.attributes["read"] == {"title": "Hello"}
    assert "remote_etag" in asset.attributes  # beside what the engine keeps
    (component,) = await context.components("docs", "hello.txt")
    assert component.attributes == {"read": {"title": "Hello"}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_proxy_documents.py -q`
Expected: 5 failed: `proxy` has no `document`, `Source` takes no `gzipped`, and `RawFormat` has no `describe_fetched`.

- [ ] **Step 3: Write the code**

`adding-a-format.md` names every member of the format interface, and `tests/test_documents.py` holds it to that: `describe_fetched` gets its row.

Change `backend/src/megooarti/repositories/remote.py`:

```diff
@@ -13,6 +13,7 @@ import re
 import socket
 import time
 import weakref
+import zlib
 from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
 from dataclasses import dataclass, field
 from http.cookiejar import CookieJar
@@ -388,6 +389,16 @@ async def _token(
     return token, min(seconds, _TOKEN_MOST_SECONDS) - _TOKEN_MARGIN_SECONDS
 
 
+def _gunzip(data: bytes, limit: int) -> bytes | None:
+    """A gzipped body inflated, or None if it is longer than `limit` or not gzip."""
+    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
+    try:
+        inflated = inflater.decompress(data, limit + 1)
+    except zlib.error:
+        return None
+    return None if len(inflated) > limit or not inflater.eof else inflated
+
+
 async def _read(response: httpx.Response, limit: int) -> bytes | None:
     """The body, or None if it is longer than `limit`."""
     received = bytearray()
@@ -528,8 +539,13 @@ async def fetch(
     limit: int,
     accept: str | None = None,
     sign_in: SignIn | None = None,
+    gzipped: bool = False,
 ) -> Document | Missing | Failed:
-    """Fetch a small document into memory. One longer than `limit` is a failure."""
+    """Fetch a small document into memory. One longer than `limit` is a failure.
+
+    With `gzipped`, a body the remote sends gzipped whatever it is asked for (as
+    nuget.org sends its registrations) is inflated, to the same `limit`.
+    """
     try:
         response = await _open(
             client,
@@ -545,9 +561,11 @@ async def fetch(
             if response.status_code != 200:
                 return _unexpected(response.status_code)
             encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
-            if encoding != "identity":
+            if encoding not in ("identity", "gzip") or (encoding == "gzip" and not gzipped):
                 return Failed("the remote sent an encoded body", blockable=False)
             body = await _read(response, limit)
+            if body is not None and encoding == "gzip":
+                body = _gunzip(body, limit)
             if body is None:
                 return Failed("the remote sent more than a document may hold", blockable=False)
             return Document(body=body, headers=response.headers)
```

Change `backend/src/megooarti/repositories/proxy.py`:

```diff
@@ -50,6 +50,9 @@ class Source:
     # Whether a miss is remembered under the path. Not if the same path can be found
     # at another address, as a blob that several images share can.
     remember_missing: bool = True
+    # Whether the remote may send the document gzipped whatever it is asked for, as
+    # nuget.org sends its registrations: it is then inflated. For `ask` and `document`.
+    gzipped: bool = False
 
 
 @dataclass(frozen=True)
@@ -180,7 +183,13 @@ async def _consult(
         )
     else:
         outcome = await remote.fetch(
-            http, url, authorization=credential, limit=limit, accept=source.accept, sign_in=sign_in
+            http,
+            url,
+            authorization=credential,
+            limit=limit,
+            accept=source.accept,
+            sign_in=sign_in,
+            gzipped=source.gzipped,
         )
     now = utcnow()
     if isinstance(outcome, remote.Exists | remote.Document):
@@ -224,6 +233,34 @@ async def probe(
     return await _consult(context, normalise_path(path), source, None)
 
 
+async def document(
+    context: RepositoryContext, path: str, source: Source, *, limit: int, content_type: str
+) -> bytes:
+    """A small document of the remote, kept under `path` as metadata, for a format that
+    reads it: what is kept while it is fresh, else what the remote has now.
+
+    Where the remote cannot be asked, or no longer has it, what is kept is given, as for
+    any cached file; with nothing kept, this raises 404 or 502. This commits.
+    """
+    path = normalise_path(path)
+    asset = await context.get(path)
+    if asset is None or not _fresh(context, asset, path):
+        answer = await ask(context, path, source, limit=limit)
+        if isinstance(answer, Answer):
+            staged = await context.stage_bytes(answer.body)
+            await context.cache(
+                path, staged, content_type=content_type, attributes={}, now=utcnow()
+            )
+            await context.db.commit()
+            return answer.body
+        if asset is None:
+            raise _not_found() if isinstance(answer, Absent) else answer.error
+    kept = await context.read(path, limit=limit)
+    if kept is None:
+        raise _not_found()
+    return kept
+
+
 async def still_current(context: RepositoryContext, path: str) -> None:
     """Record that the remote was asked just now, and what is held is still what it has."""
     asset = await context.get(normalise_path(path))
@@ -294,11 +331,13 @@ async def _refresh(
 
     if isinstance(outcome, remote.Fetched):
         origin = {"remote_etag": outcome.etag, "remote_last_modified": outcome.last_modified}
+        described = await context.format.describe_fetched(context, path, outcome.staged)
         await context.cache(
             path,
             outcome.staged,
             content_type=context.format.content_type(path, outcome.content_type),
-            attributes={name: value for name, value in origin.items() if value},
+            attributes={**{name: value for name, value in origin.items() if value}, **described},
+            component_attributes=described or None,
             now=now,
         )
         await proxy_state.record_success(db, repository, now)
```

Change `backend/src/megooarti/repositories/content.py`:

```diff
@@ -1000,13 +1000,14 @@ class RepositoryContext:
         attributes: dict[str, Any],
         now: datetime,
         references: Collection[str] | None = None,
+        component_attributes: dict[str, Any] | None = None,
     ) -> Asset:
         """Record content a proxy repository fetched from its remote.
 
         No permission or policy check: a reader triggered this, and their `read` on the
         proxy (or on the group in front of it) has already been checked. For that reason
-        it works only on a proxy repository. `references` are as for `store`; what they
-        name need not have been fetched yet.
+        it works only on a proxy repository. `references` and `component_attributes` are
+        as for `store`; what references name need not have been fetched yet.
         """
         if self.repository.type != "proxy":
             await self.backend.discard(staged)
@@ -1020,6 +1021,7 @@ class RepositoryContext:
             created_by=PROXY_CREATOR,
             attributes=attributes,
             verified_at=now,
+            component_attributes=component_attributes,
         )
         await self._refer(asset, references)
         return asset
```

Change `backend/src/megooarti/repositories/formats.py`:

```diff
@@ -22,6 +22,7 @@ if TYPE_CHECKING:
     from megooarti.repositories.content import RepositoryContext
     from megooarti.repositories.forms import UploadForm
     from megooarti.repositories.models import Repository
+    from megooarti.storage.backends import StagedBlob
 
 # The dispatcher, as an engine sees it: answer this request from that repository.
 Serve = Callable[["RepositoryContext", Request, str], Awaitable[Response]]
@@ -218,6 +219,18 @@ class Format:
             await context.store(path, file.staged, content_type=self.content_type(path, None))
         return targets
 
+    async def describe_fetched(
+        self, context: "RepositoryContext", path: str, staged: "StagedBlob"
+    ) -> dict[str, Any]:
+        """What a proxy of this format reads of a file it fetched, before it keeps it.
+
+        Kept as the file's attributes, besides what the engine keeps, and as its
+        component's, so that a cached package is described as an uploaded one is. The
+        file is the remote's: a format that cannot read it gives nothing. The generic
+        format reads nothing.
+        """
+        return {}
+
     def usage(self, address: str, key: ComponentKey, files: Sequence[str]) -> list[Usage]:
         """How a component is used from a repository, as text to copy. The generic format: none.
 
```

Change `docs/adding-a-format.md`:

```diff
@@ -69,6 +69,7 @@ raises.
 | `search_text` | The words a component is found by | namespace, name and version |
 | `delete_asset` | Delete a file as the format's own client would, with what goes with it; refuse one the format keeps itself | removes the file |
 | `upload` | Store what an upload form carries, as the format's own client's upload would | a `directory`, and each `file` in it |
+| `describe_fetched` | What a proxy reads of a file it fetched, kept with it and its component | nothing |
 | `usage` | How a component is used, as text a person copies | nothing |
 | `setup` | How a machine is set up to use a repository, as text a person copies: its key, its address, its credentials | nothing |
 | `download_path` | Where a stored file is fetched | `/repository/<name>/<path>` |
```

- [ ] **Step 4: Run the tests to verify they pass**

The engine's other tests, and the documents' test, are run as well, unchanged.

Run (in `backend/`): `uv run pytest tests/repositories/test_proxy_documents.py tests/repositories/test_proxy.py tests/repositories/test_proxy_asking.py tests/repositories/test_remote.py tests/test_documents.py -q`
Expected: 303 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests docs/adding-a-format.md
git commit -m "feat: a proxy keeps a remote's small documents, gzipped ones among them, and a format reads what its proxy fetched"
```

---

### Task 2: NuGet V3 proxies

**Files:**
- Create: `backend/src/megooarti/repositories/nuget/responses.py`, `remotes.py`, `proxied.py`
- Modify: `backend/src/megooarti/repositories/nuget/documents.py`, `format.py`; `backend/src/megooarti/repositories/service.py`
- Create (tests): `backend/tests/repositories/nuget/test_proxy.py`
- Modify (tests): `backend/tests/repositories/nuget/test_hosted.py`, `test_content.py`

**Interfaces:**
- Consumes: Task 1's `proxy.document`, `proxy.Source(gzipped=True)`, `Format.describe_fetched`, `FakeRemote.encodings`; plan 13a's `packages.read`, `packages.parse_nuspec`, `documents.*`, `paths.*`.
- Produces: `responses.JSON`, `responses.base(context, request)`, `responses.respond_json(context, request, document)` (moved out of `format.py`, which uses them now); `remotes.Resources`, `remotes.InvalidIndex`, `remotes.read_index(data)`, `remotes.rewrite(document, replacements)`; `proxied.REMOTE_INDEX`, `proxied.resources(context)`, `proxied.handle_proxy(context, request, path)`; `documents.service_index(base, *, publish=True, search=True, autocomplete=True)`; in `format.py`, `PROTOCOLS`, `proxy_settings(config, current)`, `describe_fetched(context, path, staged)`, and the format's `types` with `proxy`, `validate_config`, `describe_fetched`, `is_metadata`, `handle_proxy`; `service.remote_origin` (was `_remote_origin`).

- [ ] **Step 1: Write the failing tests**

`test_proxy.py` stands a feed laid out as nuget.org's in for the remote: its search on another host, its registration gzipped. `test_hosted.py` gains the registration with nothing left to show (plan 13a's review), and `test_content.py`'s setup over plain HTTP now marks the source.

Create `backend/tests/repositories/nuget/test_proxy.py`:

```python
"""A proxy of a V3 feed, as nuget.org is one: its documents passed on with the proxy's own
addresses, its packages kept and read as pushed ones are, its search passed on."""

import gzip
import json

import pytest

from megooarti.repositories.nuget.format import NuGetFormat
from tests.accounts import error_code
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg, nuspec

PROXY = "/repository/nuget-org"
BASE = "https://test/repository/nuget-org/"
REMOTE = "http://remote.test/nuget"
SEARCH = "http://search.test"
PACKAGE = nupkg("Newtonsoft.Json", "13.0.3", description="Json.NET is a JSON framework.")
FLAT = "nuget/v3-flatcontainer/newtonsoft.json"


def service_index(*, search: bool = True) -> bytes:
    """The remote's service index, as nuget.org's lays it out: search on another host."""
    resources = [
        {"@id": f"{REMOTE}/v3-flatcontainer/", "@type": "PackageBaseAddress/3.0.0"},
        {"@id": f"{REMOTE}/registration-gz-semver2/", "@type": "RegistrationsBaseUrl/3.6.0"},
        {"@id": f"{REMOTE}/registration-semver1/", "@type": "RegistrationsBaseUrl"},
    ]
    if search:
        resources += [
            {"@id": f"{SEARCH}/query", "@type": "SearchQueryService/3.5.0"},
            {"@id": f"{SEARCH}/autocomplete", "@type": "SearchAutocompleteService/3.5.0"},
        ]
    return json.dumps({"version": "3.0.0", "resources": resources}).encode()


def registration() -> dict:
    """nuget.org's registration of one id, with a page elsewhere and a dependency."""
    index = f"{REMOTE}/registration-gz-semver2/newtonsoft.json/index.json"
    return {
        "@id": index,
        "count": 2,
        "items": [
            {
                "@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/page/1.0.0/12.0.3.json",
                "count": 64,
                "lower": "1.0.0",
                "upper": "12.0.3",
            },
            {
                "@id": f"{index}#page/13.0.1/13.0.3",
                "count": 1,
                "lower": "13.0.3",
                "upper": "13.0.3",
                "items": [
                    {
                        "@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/13.0.3.json",
                        "packageContent": (
                            f"{REMOTE}/v3-flatcontainer/newtonsoft.json/13.0.3/"
                            "newtonsoft.json.13.0.3.nupkg"
                        ),
                        "catalogEntry": {
                            "id": "Newtonsoft.Json",
                            "version": "13.0.3",
                            "dependencyGroups": [
                                {
                                    "dependencies": [
                                        {
                                            "id": "Other",
                                            "range": "[1.0.0, )",
                                            "registration": (
                                                f"{REMOTE}/registration-semver1/other/index.json"
                                            ),
                                        }
                                    ]
                                }
                            ],
                        },
                    }
                ],
            },
        ],
    }


@pytest.fixture
async def nuget_org(client, root):
    """A proxy of the stand-in feed that asks about metadata every time it is asked."""
    made = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-org",
            "format": "nuget",
            "type": "proxy",
            "proxy": {"remote_url": f"{REMOTE}/v3/index.json", "metadata_max_age_minutes": 0},
        },
        headers=root,
    )
    assert made.status_code == 201, made.text
    return made.json()


@pytest.fixture
def remote(fake_remote, nuget_org):
    fake_remote.files["nuget/v3/index.json"] = service_index()
    fake_remote.files[f"{FLAT}/index.json"] = b'{"versions":["12.0.3","13.0.3"]}'
    fake_remote.files[f"{FLAT}/13.0.3/newtonsoft.json.13.0.3.nupkg"] = PACKAGE
    fake_remote.files[f"{FLAT}/13.0.3/newtonsoft.json.nuspec"] = nuspec(
        "Newtonsoft.Json", "13.0.3", description="Json.NET is a JSON framework."
    )
    page = "nuget/registration-gz-semver2/newtonsoft.json"
    fake_remote.files[f"{page}/index.json"] = gzip.compress(json.dumps(registration()).encode())
    fake_remote.encodings[f"{page}/index.json"] = "gzip"  # as nuget.org's are, asked or not
    fake_remote.files[f"{page}/page/1.0.0/12.0.3.json"] = json.dumps(
        {"@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/page/1.0.0/12.0.3.json"}
    ).encode()
    found = {
        "totalHits": 1,
        "data": [
            {
                "@id": f"{REMOTE}/registration-gz-semver2/newtonsoft.json/index.json",
                "id": "Newtonsoft.Json",
                "version": "13.0.3",
                "registration": f"{REMOTE}/registration-semver1/newtonsoft.json/index.json",
            }
        ],
    }
    fake_remote.files["query"] = json.dumps(found).encode()
    fake_remote.files["autocomplete"] = b'{"totalHits":1,"data":["Newtonsoft.Json"]}'
    return fake_remote


async def test_a_proxy_has_a_service_index_of_its_own_and_takes_no_push(client, root, remote):
    answer = await client.get(f"{PROXY}/index.json", headers=root)

    resources = {item["@type"]: item["@id"] for item in answer.json()["resources"]}
    assert resources["PackageBaseAddress/3.0.0"] == f"{BASE}v3/package/"
    assert resources["RegistrationsBaseUrl/3.6.0"] == f"{BASE}v3/registration/"
    assert resources["SearchQueryService/3.5.0"] == f"{BASE}v3/search"
    assert "PackagePublish/2.0.0" not in resources
    pushed = await push(client, root, PACKAGE, repository="nuget-org")
    assert pushed.status_code == 405


async def test_a_proxy_searches_only_where_its_remote_does(client, root, remote):
    remote.files["nuget/v3/index.json"] = service_index(search=False)

    resources = (await client.get(f"{PROXY}/index.json", headers=root)).json()["resources"]

    assert not [item for item in resources if item["@type"].startswith("Search")]
    assert (await client.get(f"{PROXY}/v3/search", headers=root)).status_code == 404


async def test_a_service_index_that_cannot_be_used_is_said_to_be_so(client, root, remote):
    remote.files["nuget/v3/index.json"] = b'{"resources": []}'

    answer = await client.get(f"{PROXY}/index.json", headers=root)

    assert (answer.status_code, error_code(answer)) == (502, "remote_unavailable")
    assert "PackageBaseAddress" in answer.json()["error"]["message"]


async def test_a_package_is_kept_and_its_versions_are_asked_about_again(client, root, remote):
    folder = "v3/package/newtonsoft.json"
    for _ in range(2):
        listed = await client.get(f"{PROXY}/{folder}/index.json", headers=root)
        fetched = await client.get(
            f"{PROXY}/{folder}/13.0.3/newtonsoft.json.13.0.3.nupkg", headers=root
        )

    assert listed.json() == {"versions": ["12.0.3", "13.0.3"]}
    assert fetched.content == PACKAGE
    assert remote.paths().count(f"/{FLAT}/index.json") == 2  # metadata: its age is 0
    assert remote.paths().count(f"/{FLAT}/13.0.3/newtonsoft.json.13.0.3.nupkg") == 1


async def test_a_kept_package_is_read_as_a_pushed_one_is(client, root, remote):
    folder = "v3/package/newtonsoft.json/13.0.3"
    await client.get(f"{PROXY}/{folder}/newtonsoft.json.13.0.3.nupkg", headers=root)
    await client.get(f"{PROXY}/{folder}/newtonsoft.json.nuspec", headers=root)

    components = (await client.get("/api/v1/content/nuget-org/components", headers=root)).json()
    found = await client.get("/api/v1/search", params={"q": "framework"}, headers=root)

    # Its .nupkg and .nuspec are one version, spelled as the package spells its id.
    assert [(item["name"], item["version"]) for item in components["items"]] == [
        ("Newtonsoft.Json", "13.0.3")
    ]
    assert [item["name"] for item in found.json()["items"]] == ["Newtonsoft.Json"]


async def test_a_registration_is_passed_on_with_the_proxys_addresses(client, root, remote):
    answer = await client.get(f"{PROXY}/v3/registration/newtonsoft.json/index.json", headers=root)

    document = answer.json()
    assert answer.status_code == 200, answer.text
    assert document["@id"] == f"{BASE}v3/registration/newtonsoft.json/index.json"
    paged, inlined = document["items"]
    assert paged["@id"] == f"{BASE}v3/registration/newtonsoft.json/page/1.0.0/12.0.3.json"
    (item,) = inlined["items"]
    assert item["packageContent"] == (
        f"{BASE}v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg"
    )
    (dependency,) = item["catalogEntry"]["dependencyGroups"][0]["dependencies"]
    # A registration of another kind of the remote's is the proxy's one registration.
    assert dependency["registration"] == f"{BASE}v3/registration/other/index.json"
    page = await client.get(paged["@id"].removeprefix("https://test"), headers=root)
    assert page.json()["@id"] == paged["@id"]


async def test_what_the_remote_sent_is_kept_and_given_while_it_cannot_be_reached(
    client, root, remote
):
    registration_path = f"{PROXY}/v3/registration/newtonsoft.json/index.json"
    package_path = f"{PROXY}/v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg"
    await client.get(registration_path, headers=root)
    await client.get(package_path, headers=root)
    remote.down = True

    registration_answer = await client.get(registration_path, headers=root)
    package_answer = await client.get(package_path, headers=root)

    assert registration_answer.status_code == 200
    assert registration_answer.json()["@id"].startswith(BASE)
    assert package_answer.content == PACKAGE


async def test_a_search_is_passed_on_as_it_came_every_time_with_the_proxys_addresses(
    client, root, remote
):
    for _ in range(2):
        answer = await client.get(
            f"{PROXY}/v3/search",
            params={"q": "json", "prerelease": "true", "semVerLevel": "2.0.0"},
            headers=root,
        )

    (found,) = answer.json()["data"]
    assert found["registration"] == f"{BASE}v3/registration/newtonsoft.json/index.json"
    asked = [seen for seen in remote.requests if seen["path"] == "/query"]
    assert len(asked) == 2  # not kept
    assert asked[-1]["host"] == "search.test"
    assert asked[-1]["query"] == "q=json&prerelease=true&semVerLevel=2.0.0"
    completed = await client.get(f"{PROXY}/v3/autocomplete", params={"q": "newt"}, headers=root)
    assert completed.json() == {"totalHits": 1, "data": ["Newtonsoft.Json"]}


@pytest.mark.parametrize(
    ("path", "metadata"),
    [
        (".remote/index.json", True),
        ("v3/package/newtonsoft.json/index.json", True),
        ("v3/registration/newtonsoft.json/index.json", True),
        ("v3/registration/newtonsoft.json/page/1.0.0/12.0.3.json", True),
        ("v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg", False),
        ("v3/package/newtonsoft.json/13.0.3/newtonsoft.json.nuspec", False),
    ],
)
def test_an_ids_versions_and_its_registration_are_metadata_and_a_package_is_not(path, metadata):
    assert NuGetFormat().is_metadata(path) is metadata


async def test_a_proxys_settings_are_its_protocol_and_a_symbol_server(client, root):
    def made(name: str, format_config: dict):
        return client.post(
            "/api/v1/repositories",
            json={
                "name": name,
                "format": "nuget",
                "type": "proxy",
                "proxy": {"remote_url": "https://api.nuget.org/v3/index.json"},
                "format_config": format_config,
            },
            headers=root,
        )

    plain = await made("plain", {})
    symbols = await made(
        "symbols", {"protocol": "v3", "symbol_url": "https://symbols.nuget.org/download/symbols/"}
    )
    v2 = await made("v2", {"protocol": "v2"})
    wrong = await made("wrong", {"symbol_url": "ftp://symbols.test"})
    unknown = await made("unknown", {"suite": "stable"})

    assert plain.json()["format_config"] == {"protocol": "v3"}
    assert symbols.json()["format_config"] == {
        "protocol": "v3",
        "symbol_url": "https://symbols.nuget.org/download/symbols",
    }
    for refused, field in ((v2, "protocol"), (wrong, "symbol_url"), (unknown, "suite")):
        assert refused.status_code == 422
        assert refused.json()["error"]["details"][0]["field"] == f"format_config.{field}"
```

Change `backend/tests/repositories/nuget/test_hosted.py`:

```diff
@@ -288,6 +288,17 @@ async def test_a_version_list_is_written_from_the_versions_alone(client, db, hos
     assert listed.json() == {"versions": ["1.0.0", "2.0.0"]}
 
 
+async def test_a_registration_with_nothing_left_to_show_is_not_found(client, db, hosted, root):
+    await push(client, root, nupkg(version="1.0.0"))
+    # As when its last version goes between the two reads a registration makes.
+    await db.execute(update(Component).values(attributes=None))
+    await db.commit()
+
+    answer = await client.get(f"{URL}/v3/registration/megooarti.hello/index.json", headers=root)
+
+    assert answer.status_code == 404
+
+
 @pytest.mark.parametrize(
     "path",
     [
```

Change `backend/tests/repositories/nuget/test_content.py`:

```diff
@@ -95,9 +95,10 @@ async def test_a_source_over_plain_http_is_allowed_so_and_a_name_is_made_an_elem
 
     dotnet, config = (usage["text"] for usage in view["setup"])
     assert dotnet.startswith(
-        "# Over plain HTTP, .NET 9 and later take a source only from a nuget.config that "
-        "allows it: use the nuget.config below.\ndotnet nuget add source"
+        "# Over plain HTTP: --allow-insecure-connections is the .NET SDK 9's and later's;"
+        " with .NET 8, leave it out.\ndotnet nuget add source"
     )
+    assert dotnet.endswith("--store-password-in-clear-text \\\n  --allow-insecure-connections")
     assert (
         'value="http://plain.test/repository/1nuget/index.json" allowInsecureConnections="true"'
         in config
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/nuget -q`
Expected: 7 failed, 120 passed, 8 errors: a NuGet proxy cannot be made yet (`422`), so every proxy test fails at its setup or its first request; a registration with nothing to show answers `500`; the setup over plain HTTP does not mark the source.

- [ ] **Step 3: Write the code**

`_remote_origin` in `service.py` becomes `remote_origin`, as the NuGet format checks a symbol server's address with it.

Change `backend/src/megooarti/repositories/service.py`:

```diff
@@ -101,7 +101,7 @@ def _remote_auth(
     return {"type": kind, "username": username if kind == "basic" else "", "secret": str(secret)}
 
 
-def _remote_origin(url: str) -> tuple[str, str, int] | None:
+def remote_origin(url: str) -> tuple[str, str, int] | None:
     """Scheme, host and port of an acceptable remote URL, or None if it is not one."""
     try:
         parts = urlsplit(url)
@@ -121,7 +121,7 @@ def _remote_origin(url: str) -> tuple[str, str, int] | None:
 def _proxy_settings(proxy: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any]:
     proxy = proxy or {}
     url = str(proxy.get("remote_url") or "").strip()
-    origin = _remote_origin(url)
+    origin = remote_origin(url)
     if origin is None:
         # The message never repeats the URL: it may be the one with a password in it.
         raise _invalid(
@@ -130,7 +130,7 @@ def _proxy_settings(proxy: dict[str, Any] | None, current: dict[str, Any] | None
             "a fragment. Credentials belong in remote_auth.",
         )
     previous = (current or {}).get("remote_url")
-    same_remote = previous is not None and _remote_origin(previous) == origin
+    same_remote = previous is not None and remote_origin(previous) == origin
     negative = proxy.get("negative_cache") or {}
     return {
         "remote_url": url.rstrip("/"),
```

Create `backend/src/megooarti/repositories/nuget/responses.py`:

```python
"""How a NuGet repository answers with a document it wrote: hosted or a proxy alike."""

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.repositories.content import RepositoryContext

JSON = "application/json"


async def base(context: RepositoryContext, request: Request) -> str:
    """The repository's address as a client is given it, ending in a slash."""
    return f"{await context.public_url(request)}/"


async def respond_json(context: RepositoryContext, request: Request, document: Any) -> Response:
    """A document written for this request, as JSON."""
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    _, changed = await context.revision()
    return context.respond_with(
        data,
        request,
        filename="index.json",
        content_type=JSON,
        last_modified=changed,
        # Two changes can be made within one second: only the bytes say which a client has.
        dated=False,
    )
```

Create `backend/src/megooarti/repositories/nuget/remotes.py`:

```python
"""What a V3 proxy reads of its remote: the remote's service index, and its documents
with the remote's addresses made the proxy's own.

Pure functions.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# The kinds of each resource a proxy uses, the one it prefers first. A registration of
# SemVer 2.0.0 is preferred: the others leave out the versions only it can list.
_PACKAGES = ("PackageBaseAddress/3.0.0",)
_REGISTRATIONS = (
    "RegistrationsBaseUrl/3.6.0",
    "RegistrationsBaseUrl/Versioned",
    "RegistrationsBaseUrl/3.4.0",
    "RegistrationsBaseUrl/3.0.0-rc",
    "RegistrationsBaseUrl/3.0.0-beta",
    "RegistrationsBaseUrl",
)
_SEARCH = (
    "SearchQueryService/3.5.0",
    "SearchQueryService/3.0.0-rc",
    "SearchQueryService/3.0.0-beta",
    "SearchQueryService",
)
_AUTOCOMPLETE = (
    "SearchAutocompleteService/3.5.0",
    "SearchAutocompleteService/3.0.0-rc",
    "SearchAutocompleteService/3.0.0-beta",
    "SearchAutocompleteService",
)


class InvalidIndex(Exception):
    """A remote's service index that a proxy cannot use. The message says why."""


@dataclass(frozen=True)
class Resources:
    """Where a remote serves what a proxy passes on. Each address ends in a slash but
    search's and autocomplete's, which are "" where the remote has none."""

    packages: str
    registration: str
    # Every registration the remote has, of whatever kind: a search names any of them.
    registrations: tuple[str, ...]
    search: str = ""
    autocomplete: str = ""


def _slashed(address: str) -> str:
    return address if address.endswith("/") else f"{address}/"


def _first(found: dict[str, str], kinds: Sequence[str]) -> str:
    return next((found[kind] for kind in kinds if kind in found), "")


def read_index(data: bytes) -> Resources:
    """What a remote's `index.json` says. Raises InvalidIndex."""
    try:
        listed = json.loads(data)["resources"]
    except (ValueError, KeyError, TypeError):
        raise InvalidIndex("its service index is not one NuGet's clients read") from None
    found: dict[str, str] = {}
    registrations: list[str] = []
    for resource in listed if isinstance(listed, list) else []:
        if not isinstance(resource, dict):
            continue
        kind, address = resource.get("@type"), resource.get("@id")
        if not isinstance(kind, str) or not isinstance(address, str):
            continue
        found.setdefault(kind, address)
        if kind.startswith("RegistrationsBaseUrl"):
            registrations.append(_slashed(address))
    packages, registration = _first(found, _PACKAGES), _first(found, _REGISTRATIONS)
    if not packages:
        raise InvalidIndex("its service index names no PackageBaseAddress/3.0.0")
    if not registration:
        raise InvalidIndex("its service index names no RegistrationsBaseUrl")
    return Resources(
        packages=_slashed(packages),
        registration=_slashed(registration),
        registrations=tuple(dict.fromkeys(registrations)),
        search=_first(found, _SEARCH),
        autocomplete=_first(found, _AUTOCOMPLETE),
    )


def rewrite(document: Any, replacements: Sequence[tuple[str, str]]) -> Any:
    """A document with each text that begins with one of the remote's addresses begun
    with the proxy's instead: the first replacement that fits."""
    if isinstance(document, str):
        for remote, own in replacements:
            if document.startswith(remote):
                return own + document[len(remote) :]
        return document
    if isinstance(document, list):
        return [rewrite(item, replacements) for item in document]
    if isinstance(document, dict):
        return {key: rewrite(value, replacements) for key, value in document.items()}
    return document
```

Change `backend/src/megooarti/repositories/nuget/documents.py`:

```diff
@@ -27,8 +27,13 @@ class Published:
     published: datetime
 
 
-def service_index(base: str) -> dict[str, Any]:
-    """`index.json`: where a client finds each of the protocol's resources."""
+def service_index(
+    base: str, *, publish: bool = True, search: bool = True, autocomplete: bool = True
+) -> dict[str, Any]:
+    """`index.json`: where a client finds each of the protocol's resources.
+
+    A proxy offers no place to push to, and searches only where its remote does.
+    """
     resources = [
         (paths.PACKAGES, ["PackageBaseAddress/3.0.0"]),
         (paths.PUBLISH, ["PackagePublish/2.0.0"]),
@@ -63,10 +68,19 @@ def service_index(base: str) -> dict[str, Any]:
             ],
         ),
     ]
+    left_out = {
+        paths.PUBLISH: not publish,
+        paths.SYMBOL_PUBLISH: not publish,
+        paths.SEARCH: not search,
+        paths.AUTOCOMPLETE: not autocomplete,
+    }
     return {
         "version": "3.0.0",
         "resources": [
-            {"@id": f"{base}{path}", "@type": kind} for path, kinds in resources for kind in kinds
+            {"@id": f"{base}{path}", "@type": kind}
+            for path, kinds in resources
+            if not left_out.get(path, False)
+            for kind in kinds
         ],
     }
 
```

Create `backend/src/megooarti/repositories/nuget/proxied.py`:

```python
"""A proxy of a V3 feed: nuget.org, or any feed that serves NuGet's V3 protocol.

The remote's service index says where it serves each resource, often on other hosts
(nuget.org searches elsewhere). It is kept as metadata, under a path no client asks
for. The proxy serves a service index of its own, with its own addresses.

A package and its `.nuspec` are cached files, kept as every proxy keeps its files; an
id's versions and its registration are metadata, kept and asked about again after the
proxy's metadata age; search and autocomplete are passed on every time. What the proxy
passes on of a registration or a search has the remote's addresses made its own, as it
is sent: what is kept is what the remote sent.
"""

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import proxy
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import documents, paths, remotes, responses
from megooarti.repositories.proxy import Absent, Answer, Source

# Where the remote's service index is kept: a path no client asks for.
REMOTE_INDEX = ".remote/index.json"
# What is read of the remote's documents, at the most.
INDEX_MOST = 1024 * 1024
REGISTRATION_MOST = 32 * 1024 * 1024
SEARCH_MOST = 8 * 1024 * 1024


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Nothing is served at this address.")


async def resources(context: RepositoryContext) -> remotes.Resources:
    """Where the remote serves what the proxy passes on. Raises 502 for an index that
    cannot be used, as for a remote that cannot be reached."""
    remote_url = context.repository.config["proxy"]["remote_url"]
    data = await proxy.document(
        context, REMOTE_INDEX, Source(remote_url), limit=INDEX_MOST, content_type=responses.JSON
    )
    try:
        return remotes.read_index(data)
    except remotes.InvalidIndex as error:
        raise await proxy.refuse(context, REMOTE_INDEX, str(error)) from None


def _replacements(found: remotes.Resources, base: str) -> list[tuple[str, str]]:
    """The remote's addresses and the proxy's for them, the longest first."""
    pairs = [(registration, f"{base}{paths.REGISTRATION}") for registration in found.registrations]
    pairs.append((found.packages, f"{base}{paths.PACKAGES}"))
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _relative(path: str, prefix: str) -> str | None:
    """What follows a resource's address in a path, or None if nothing does."""
    rest = path[len(prefix) :] if path.startswith(prefix) else ""
    return rest or None


async def _parsed(context: RepositoryContext, path: str, data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        raise await proxy.refuse(context, path, "it sent a document that is not JSON") from None


async def _registration(
    context: RepositoryContext, request: Request, path: str, relative: str
) -> Response:
    found = await resources(context)
    data = await proxy.document(
        context,
        path,
        Source(f"{found.registration}{relative}", gzipped=True),
        limit=REGISTRATION_MOST,
        content_type=responses.JSON,
    )
    base = await responses.base(context, request)
    document = remotes.rewrite(await _parsed(context, path, data), _replacements(found, base))
    return await responses.respond_json(context, request, document)


async def _passed_on(context: RepositoryContext, request: Request, path: str) -> Response:
    """A search or an autocomplete, passed on as it came, its answer not kept."""
    found = await resources(context)
    address = found.search if path == paths.SEARCH else found.autocomplete
    if not address:
        raise _not_found()
    query = request.url.query
    source = Source(f"{address}?{query}" if query else address, remember_missing=False)
    answer = await proxy.ask(context, path, source, limit=SEARCH_MOST)
    if isinstance(answer, Absent):
        raise _not_found()
    if not isinstance(answer, Answer):
        raise answer.error
    base = await responses.base(context, request)
    document = remotes.rewrite(
        await _parsed(context, path, answer.body), _replacements(found, base)
    )
    return await responses.respond_json(context, request, document)


async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
    """Answer a request to a V3 proxy. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        raise ApiError(
            405,
            "method_not_allowed",
            "A proxy repository accepts GET and HEAD.",
            headers={"Allow": "GET, HEAD"},
        )
    if path == paths.SERVICE_INDEX:
        found = await resources(context)
        index = documents.service_index(
            await responses.base(context, request),
            publish=False,
            search=bool(found.search),
            autocomplete=bool(found.autocomplete),
        )
        return await responses.respond_json(context, request, index)
    if (relative := _relative(path, paths.PACKAGES)) is not None:
        found = await resources(context)
        await proxy.ensure_cached(context, path, source=Source(f"{found.packages}{relative}"))
        return await context.respond(path, request)
    if (relative := _relative(path, paths.REGISTRATION)) is not None and path.endswith(".json"):
        return await _registration(context, request, path, relative)
    if path in (paths.SEARCH, paths.AUTOCOMPLETE):
        return await _passed_on(context, request, path)
    raise _not_found()
```

Change `backend/src/megooarti/repositories/nuget/format.py`:

```diff
@@ -16,7 +16,6 @@ normalized and in lower case, as it is in every address; what its package wrote
 its `.nuspec`.
 """
 
-import json
 import xml.sax.saxutils
 from collections.abc import Sequence
 from contextlib import aclosing
@@ -27,7 +26,7 @@ from starlette.requests import Request
 from starlette.responses import Response
 
 from megooarti.errors import ApiError
-from megooarti.repositories import forms
+from megooarti.repositories import forms, service
 from megooarti.repositories.content import ComponentInfo, RepositoryContext
 from megooarti.repositories.formats import (
     ComponentKey,
@@ -40,7 +39,15 @@ from megooarti.repositories.formats import (
     register,
 )
 from megooarti.repositories.models import Repository
-from megooarti.repositories.nuget import documents, packages, paths, queries, versions
+from megooarti.repositories.nuget import (
+    documents,
+    packages,
+    paths,
+    proxied,
+    queries,
+    responses,
+    versions,
+)
 from megooarti.repositories.nuget.documents import Published
 from megooarti.storage.backends import StagedBlob
 
@@ -49,10 +56,9 @@ from megooarti.storage.backends import StagedBlob
 _DECLARED = "nuget"
 _PACKAGE = "application/octet-stream"
 _NUSPEC = "application/xml"
-_JSON = "application/json"
 _PLAIN_HTTP = (
-    "# Over plain HTTP, .NET 9 and later take a source only from a nuget.config that "
-    "allows it: use the nuget.config below."
+    "# Over plain HTTP: --allow-insecure-connections is the .NET SDK 9's and later's;"
+    " with .NET 8, leave it out."
 )
 
 
@@ -217,25 +223,6 @@ async def _delete_version(context: RepositoryContext, package_id: str, version:
 # --- Reading ------------------------------------------------------------------------
 
 
-async def _base(context: RepositoryContext, request: Request) -> str:
-    return f"{await context.public_url(request)}/"
-
-
-async def _respond(context: RepositoryContext, request: Request, document: Any) -> Response:
-    """A document written for this request, as JSON."""
-    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
-    _, changed = await context.revision()
-    return context.respond_with(
-        data,
-        request,
-        filename="index.json",
-        content_type=_JSON,
-        last_modified=changed,
-        # Two changes can be made within one second: only the bytes say which a client has.
-        dated=False,
-    )
-
-
 async def _held(context: RepositoryContext, package_id: str) -> list[Published]:
     """Every version of an id this repository holds. Raises 404 for none."""
     spelling = await context.spelling("", package_id)
@@ -252,13 +239,16 @@ async def _registration(context: RepositoryContext, request: Request, package_id
     listed = [] if spelling is None else list(await context.versions("", spelling))
     if not listed:
         raise _not_found(f"This repository has no package {package_id}.")
-    base = await _base(context, request)
+    base = await responses.base(context, request)
     if len(listed) > documents.INLINED_MOST:
-        return await _respond(
+        return await responses.respond_json(
             context, request, documents.registration_pages(base, package_id, listed)
         )
     held = _published(await context.components("", spelling))
-    return await _respond(context, request, documents.registration(base, held))
+    if not held:
+        # Its last version went between the two reads.
+        raise _not_found(f"This repository has no package {package_id}.")
+    return await responses.respond_json(context, request, documents.registration(base, held))
 
 
 async def _registration_page(
@@ -275,9 +265,9 @@ async def _registration_page(
         for one in _published(await context.components("", spelling))
         if one.nuspec.version.lower() in set(wanted)
     ]
-    base = await _base(context, request)
+    base = await responses.base(context, request)
     page = documents.registration_page(base, parsed.id, held, parsed.lower, parsed.upper)
-    return await _respond(context, request, page)
+    return await responses.respond_json(context, request, page)
 
 
 async def _search(context: RepositoryContext, request: Request) -> Response:
@@ -294,8 +284,10 @@ async def _search(context: RepositoryContext, request: Request) -> Response:
     )
     held = await context.components_of("", names)
     found = queries.shown(query, names, {name: _published(infos) for name, infos in held.items()})
-    return await _respond(
-        context, request, documents.search_result(await _base(context, request), found, total)
+    return await responses.respond_json(
+        context,
+        request,
+        documents.search_result(await responses.base(context, request), found, total),
     )
 
 
@@ -309,7 +301,9 @@ async def _autocomplete(context: RepositoryContext, request: Request) -> Respons
         shown = versions.ordered(
             [one.nuspec.version for one in held if prerelease or not one.nuspec.is_prerelease]
         )
-        return await _respond(context, request, documents.autocomplete(shown, len(shown)))
+        return await responses.respond_json(
+            context, request, documents.autocomplete(shown, len(shown))
+        )
     query = queries.parse({**arguments, "q": ""})
     typed = arguments.get("q", "").strip().lower()
     ids, total = await context.package_page(
@@ -321,15 +315,15 @@ async def _autocomplete(context: RepositoryContext, request: Request) -> Respons
         limit=query.take,
         offset=query.skip,
     )
-    return await _respond(context, request, documents.autocomplete(ids, total))
+    return await responses.respond_json(context, request, documents.autocomplete(ids, total))
 
 
 async def _read_request(
     context: RepositoryContext, request: Request, path: str, parsed: paths.NuGetPath
 ) -> Response:
     if parsed.kind == "service-index":
-        return await _respond(
-            context, request, documents.service_index(await _base(context, request))
+        return await responses.respond_json(
+            context, request, documents.service_index(await responses.base(context, request))
         )
     if parsed.kind in ("package", "nuspec", "symbols"):
         return await context.respond(path, request)
@@ -339,7 +333,7 @@ async def _read_request(
         listed = [] if spelling is None else list(await context.versions("", spelling))
         if not listed:
             raise _not_found(f"This repository has no package {parsed.id}.")
-        return await _respond(context, request, documents.version_list(listed))
+        return await responses.respond_json(context, request, documents.version_list(listed))
     if parsed.kind == "registration":
         return await _registration(context, request, parsed.id)
     if parsed.kind == "page":
@@ -352,8 +346,8 @@ async def _read_request(
         ]
         if not held:
             raise _not_found(f"This repository has no {parsed.id} {parsed.version}.")
-        return await _respond(
-            context, request, documents.leaf(await _base(context, request), held[0])
+        return await responses.respond_json(
+            context, request, documents.leaf(await responses.base(context, request), held[0])
         )
     if parsed.kind == "search":
         return await _search(context, request)
@@ -383,7 +377,8 @@ def setup_of(address: str, name: str) -> list[Usage]:
     )
     plain_http = source.startswith("http://")
     if plain_http:
-        command = _PLAIN_HTTP + "\n" + command
+        # NuGet refuses a plain-HTTP source that is not marked so (NU1302).
+        command = f"{_PLAIN_HTTP}\n{command} \\\n  --allow-insecure-connections"
     insecure = ' allowInsecureConnections="true"' if plain_http else ""
     escaped = xml.sax.saxutils.quoteattr(source)
     element = _element(name)
@@ -404,11 +399,95 @@ def setup_of(address: str, name: str) -> list[Usage]:
     return [Usage("dotnet", "shell", command), Usage("nuget.config", "xml", config)]
 
 
+# The protocols a proxy may speak to its remote. V2 comes with a later version.
+PROTOCOLS = ("v3",)
+
+
+def _invalid_setting(field: str, message: str) -> ApiError:
+    details = [{"field": field, "message": message}]
+    return ApiError(422, "validation_error", "The request is not valid.", details)
+
+
+def proxy_settings(config: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
+    """A proxy's protocol, fixed once it is made, and the symbol server it may proxy."""
+    unknown = sorted(set(config) - {"protocol", "symbol_url"})
+    if unknown:
+        raise _invalid_setting(f"format_config.{unknown[0]}", "This is not a setting of NuGet.")
+    stored = "v3" if current is None else current.get("protocol", "v3")
+    protocol = config.get("protocol", stored)
+    if protocol not in PROTOCOLS:
+        raise _invalid_setting(
+            "format_config.protocol",
+            "A NuGet proxy speaks v3 to its remote: a V2 feed is not proxied yet.",
+        )
+    if current is not None and protocol != stored:
+        raise _invalid_setting(
+            "format_config.protocol", "The protocol cannot change once the proxy is made."
+        )
+    settings: dict[str, Any] = {"protocol": protocol}
+    symbol_url = config.get("symbol_url")
+    if symbol_url:
+        if not isinstance(symbol_url, str) or service.remote_origin(symbol_url.strip()) is None:
+            raise _invalid_setting(
+                "format_config.symbol_url",
+                "Give an http or https address with a host, and without credentials, a "
+                "query or a fragment.",
+            )
+        settings["symbol_url"] = symbol_url.strip().rstrip("/")
+    return settings
+
+
+async def describe_fetched(
+    context: RepositoryContext, path: str, staged: StagedBlob
+) -> dict[str, Any]:
+    """A package or a `.nuspec` a proxy fetched, read as a pushed one is: what its
+    `.nuspec` says. Nothing for what cannot be read: it is the remote's."""
+    kind = paths.classify(path).kind
+    try:
+        if kind == "package":
+            nuspec = (await packages.read(_ranges(context, staged), staged.size)).nuspec
+        elif kind == "nuspec":
+            spec = await context.read_staged(staged, limit=packages.NUSPEC_MOST)
+            if spec is None:
+                return {}
+            nuspec = packages.parse_nuspec(spec)
+        else:
+            return {}
+    except packages.InvalidPackage:
+        return {}
+    return {_DECLARED: nuspec.as_json()}
+
+
 class NuGetFormat(Format):
     name = "nuget"
-    types = frozenset({"hosted"})
+    types = frozenset({"hosted", "proxy"})
     derives_indexes = True
 
+    def validate_config(
+        self, repository_type: str, config: dict[str, Any], current: dict[str, Any] | None = None
+    ) -> dict[str, Any]:
+        """A proxy's settings; a hosted repository has none."""
+        if repository_type == "proxy":
+            return proxy_settings(config, current)
+        return super().validate_config(repository_type, config, current)
+
+    async def describe_fetched(
+        self, context: RepositoryContext, path: str, staged: StagedBlob
+    ) -> dict[str, Any]:
+        return await describe_fetched(context, path, staged)
+
+    def is_metadata(self, path: str) -> bool:
+        """An id's versions, its registration and the remote's service index change as
+        packages are published; packages and their `.nuspec` do not."""
+        if path == proxied.REMOTE_INDEX or path.startswith(paths.REGISTRATION):
+            return True
+        return path.startswith(paths.PACKAGES) and path.endswith("/index.json")
+
+    async def handle_proxy(
+        self, context: RepositoryContext, request: Request, path: str
+    ) -> Response:
+        return await proxied.handle_proxy(context, request, path)
+
     def default_deployment_policy(self, config: dict[str, Any]) -> str:
         """A version is pushed once, as nuget.org takes it: a second push is `409`."""
         return "disable_redeploy"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/nuget tests/repositories/test_service.py -q`
Expected: 186 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "feat: NuGet proxies of V3 feeds, nuget.org's among them"
```

---

### Task 3: dotnet through a proxy of nuget.org, and the guide

**Files:**
- Modify (tests): `backend/tests/test_nuget_client.py`
- Modify: `docs/formats/nuget.md`

**Interfaces:**
- Consumes: Task 2's proxy, through the built image; `tests.containers.call`.
- Produces: in the client test, `config(repository, name)` in place of `CONFIG`, `PROXY`, `JSON_NET`, `THROUGH_PROXY`, the `through` fixture; `fetch(path, repository=HOSTED)`.

- [ ] **Step 1: Write the tests**

They are of what Task 2 made, through the built image and nuget.org itself: a project restores Json.NET through the proxy and runs, the package is kept, `dotnet package search` finds it, and `dotnet list package --outdated` reads its newer versions from the registration the proxy passes on.

Change `backend/tests/test_nuget_client.py`:

```diff
@@ -1,8 +1,9 @@
 """dotnet, of the .NET SDKs 10 and 8, against the built image.
 
-Run with `pytest -m docker`. Besides a Docker daemon this needs internet access to pull
-the two images. Each run of dotnet is a new container beside the stack, whose
-`nuget.config` has no source but the stack's: nothing is fetched from nuget.org.
+Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
+the two images, and for the proxy of nuget.org. Each run of dotnet is a new container
+beside the stack, whose `nuget.config` has no source but one of the stack's: dotnet
+reaches nuget.org only through the proxy.
 """
 
 import base64
@@ -21,29 +22,48 @@ pytestmark = pytest.mark.docker
 IMAGES = {"10": "mcr.microsoft.com/dotnet/sdk:10.0", "8": "mcr.microsoft.com/dotnet/sdk:8.0"}
 NETWORK = f"{PROJECT}_default"
 HOSTED = "nuget-hosted"
-SOURCE = f"http://gateway/repository/{HOSTED}/index.json"
+PROXY = "nuget-org"
 # What an account that pushes and restores gets: everything on NuGet repositories.
 USERNAME = "ci"
 PASSWORD = "restores-dotnet-packages"
 VERSION = "1.0.0"
 
-# The stack as the one source, with the account dotnet signs in with. Plain HTTP, which
-# NuGet allows only to a source marked so.
-CONFIG = f"""<?xml version="1.0" encoding="utf-8"?>
+
+def config(repository: str, name: str = "megooarti") -> str:
+    """A repository of the stack as the one source, with the account dotnet signs in
+    with. Plain HTTP, which NuGet allows only to a source marked so."""
+    return f"""<?xml version="1.0" encoding="utf-8"?>
 <configuration>
   <packageSources>
     <clear />
-    <add key="megooarti" value="{SOURCE}" allowInsecureConnections="true" />
+    <add key="{name}" value="http://gateway/repository/{repository}/index.json"
+         allowInsecureConnections="true" />
   </packageSources>
   <packageSourceCredentials>
-    <megooarti>
+    <{name}>
       <add key="Username" value="{USERNAME}" />
       <add key="ClearTextPassword" value="{PASSWORD}" />
-    </megooarti>
+    </{name}>
   </packageSourceCredentials>
 </configuration>
 """
 
+
+# The version of nuget.org's Json.NET the proxy's tests restore: not its newest.
+JSON_NET = "13.0.1"
+# A project that restores Json.NET through the proxy, and runs.
+THROUGH_PROXY = f"""
+set -e
+cd /work
+dotnet new console -n App -o app --force > /dev/null
+cd app
+dotnet add package Newtonsoft.Json --version {JSON_NET}
+cat > Program.cs <<CODE
+System.Console.WriteLine(Newtonsoft.Json.JsonConvert.SerializeObject(new {{ through = "proxy" }}));
+CODE
+dotnet run
+"""
+
 # Builds `/work/out/<id>.1.0.0.nupkg` and its `.snupkg`: a library that says hello.
 PACK = f"""
 set -e
@@ -111,11 +131,11 @@ def said(result: subprocess.CompletedProcess[str]) -> str:
     return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
 
 
-def fetch(path: str) -> int:
-    """The status of a read of the repository from outside, as `ci`."""
+def fetch(path: str, repository: str = HOSTED) -> int:
+    """The status of a read of a repository from outside, as `ci`."""
     credentials = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
     request = urllib.request.Request(
-        f"http://127.0.0.1:{HTTP_PORT}/repository/{HOSTED}/{path}",
+        f"http://127.0.0.1:{HTTP_PORT}/repository/{repository}/{path}",
         headers={"Authorization": f"Basic {credentials}"},
     )
     try:
@@ -127,14 +147,18 @@ def fetch(path: str) -> int:
 
 @pytest.fixture(scope="module")
 def token(administrator) -> str:
-    """A hosted NuGet repository, the account `ci`, and an API token of it to push with."""
-    status, _, answer = call(
-        "POST",
-        "/repositories",
-        {"name": HOSTED, "format": "nuget", "type": "hosted"},
-        administrator,
-    )
-    assert status == 201, answer
+    """A hosted NuGet repository, a proxy of nuget.org, the account `ci`, and an API token
+    of it to push with."""
+    proxy = {
+        "name": PROXY,
+        "format": "nuget",
+        "type": "proxy",
+        # Not left alone after one failure: the internet may be slow once.
+        "proxy": {"remote_url": "https://api.nuget.org/v3/index.json", "auto_block": False},
+    }
+    for body in ({"name": HOSTED, "format": "nuget", "type": "hosted"}, proxy):
+        status, _, answer = call("POST", "/repositories", body, administrator)
+        assert status == 201, answer
     role = {"name": "nuget-users", "permissions": ["repository:nuget"]}
     user = {
         "username": USERNAME,
@@ -166,7 +190,7 @@ def work(token, tmp_path_factory) -> dict[str, Path]:
     folders = {}
     for sdk in IMAGES:
         folder = tmp_path_factory.mktemp(f"dotnet{sdk}")
-        (folder / "nuget.config").write_text(CONFIG, encoding="utf-8", newline="\n")
+        (folder / "nuget.config").write_text(config(HOSTED), encoding="utf-8", newline="\n")
         packed = dotnet(sdk, folder, PACK, package_id(sdk))
         assert packed.returncode == 0, said(packed)
         folders[sdk] = folder
@@ -238,3 +262,42 @@ def test_dotnet_deletes_a_version(work, token, sdk):
 
     assert deleted.returncode == 0, said(deleted)
     assert fetch(f"v3/package/{lower(sdk)}/index.json") == 404
+
+
+@pytest.fixture(scope="module")
+def through(token, tmp_path_factory) -> dict[str, Path]:
+    """Each SDK's own folder whose one source is the proxy of nuget.org."""
+    folders = {}
+    for sdk in IMAGES:
+        folder = tmp_path_factory.mktemp(f"proxy{sdk}")
+        written = config(PROXY, "nuget-org")
+        (folder / "nuget.config").write_text(written, encoding="utf-8", newline="\n")
+        folders[sdk] = folder
+    return folders
+
+
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+def test_dotnet_restores_a_package_of_nuget_org_through_the_proxy(through, sdk):
+    restored = dotnet(sdk, through[sdk], THROUGH_PROXY)
+
+    assert restored.returncode == 0, said(restored)
+    assert restored.stdout.splitlines()[-1] == '{"through":"proxy"}'
+    folder = f"v3/package/newtonsoft.json/{JSON_NET}"
+    assert fetch(f"{folder}/newtonsoft.json.{JSON_NET}.nupkg", PROXY) == 200  # kept
+
+
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+def test_dotnet_searches_and_finds_newer_versions_through_the_proxy(through, sdk):
+    found = dotnet(
+        sdk, through[sdk], "cd /work && dotnet package search Newtonsoft.Json --source nuget-org"
+    )
+    # Read from the registration the proxy passes on, with its own addresses in it.
+    outdated = dotnet(sdk, through[sdk], "cd /work/app && dotnet list package --outdated")
+
+    assert found.returncode == 0, said(found)
+    assert "Newtonsoft.Json" in found.stdout
+    assert outdated.returncode == 0, said(outdated)
+    (line,) = [line for line in outdated.stdout.splitlines() if "Newtonsoft.Json" in line]
+    requested, resolved, latest = line.split()[-3:]
+    assert (requested, resolved) == (JSON_NET, JSON_NET)
+    assert latest != JSON_NET
```

- [ ] **Step 2: Write the guide**

It gains the proxy, says which SDK takes `--allow-insecure-connections`, gets back the line breaks of its commands, and names the proxy's tests.

Change `docs/formats/nuget.md`:

````diff
@@ -18,7 +18,9 @@ the account `dotnet` signs in with. The repository's page in the web UI gives th
 with its own address, under "Set up a machine".
 
 ```bash
-dotnet nuget add source https://repo.example.com/repository/nuget-hosted/index.json   --name megooarti --username ci --password "$MEGOOARTI_TOKEN"   --store-password-in-clear-text
+dotnet nuget add source https://repo.example.com/repository/nuget-hosted/index.json \
+  --name megooarti --username ci --password "$MEGOOARTI_TOKEN" \
+  --store-password-in-clear-text
 ```
 
 Then push to the source by its name, not by its address: `dotnet` reads the
@@ -27,7 +29,8 @@ the API key with the push alone.
 
 ```bash
 dotnet pack -c Release
-dotnet nuget push bin/Release/MegooArti.Hello.1.0.0.nupkg   --source megooarti --api-key "$MEGOOARTI_TOKEN"
+dotnet nuget push bin/Release/MegooArti.Hello.1.0.0.nupkg \
+  --source megooarti --api-key "$MEGOOARTI_TOKEN"
 
 dotnet add package MegooArti.Hello --version 1.0.0
 ```
@@ -50,11 +53,26 @@ puts the values of environment variables in place of `%NAME%`:
 </configuration>
 ```
 
+A proxy caches a feed of V3: nuget.org, or any feed that serves NuGet's V3 protocol.
+Its remote is the feed's service index:
+
+```bash
+curl -u admin -H 'Content-Type: application/json' -d '{
+  "name": "nuget-org", "format": "nuget", "type": "proxy",
+  "proxy": {"remote_url": "https://api.nuget.org/v3/index.json"}
+}' http://localhost:8000/api/v1/repositories
+
+dotnet nuget add source https://repo.example.com/repository/nuget-org/index.json \
+  --name nuget-org --username ci --password "$MEGOOARTI_TOKEN" \
+  --store-password-in-clear-text
+```
+
 - **Credentials.** A push's API key is an API token (`--api-key`, sent as
   `X-NuGet-ApiKey`); so is the password of a source's credentials. A user name and a
-  password work for a source too. NuGet's clients refuse a plain-HTTP source unless
-  `nuget.config` marks it `allowInsecureConnections="true"` (the `dotnet nuget add
-  source` command cannot, and .NET 8 warns): use HTTPS.
+  password work for a source too. NuGet's clients refuse a plain-HTTP source unless it
+  is marked so: `allowInsecureConnections="true"` on its line of `nuget.config`, or
+  `--allow-insecure-connections` to `dotnet nuget add source` of the .NET SDK 9 and
+  later (.NET 8 only warns). Use HTTPS.
 - **A push** is `dotnet nuget push`, or the web UI or [the API](../api.md#uploading)
   with one or more `file` fields. What is read of a package is its `.nuspec`, at most
   1 MiB, from a zip of at most 10,000 files: the zip is never unpacked. A file that is
@@ -75,17 +93,31 @@ puts the values of environment variables in place of `%NAME%`:
 - **Deleting** a version (`dotnet nuget delete <id> <version>`, which needs the
   `delete` permission, or the web UI) removes it and its every file: its package, its
   `.nuspec` and its symbol package. A package's `.nuspec` cannot be deleted on its own.
-- **The feed is written from the packages** on each request: an id's versions, its
-  registration (inlined up to 128 versions, then in pages of 64) and search. Nothing is stored but the
-  packages, so the feed is right after every push and delete.
+- **A hosted repository's feed is written from its packages** on each request: an id's
+  versions, its registration (inlined up to 128 versions, then in pages of 64) and
+  search. Nothing is stored but the packages, so the feed is right after every push and
+  delete.
 - **Search** (`dotnet package search`, and Visual Studio's Browse tab) finds an id by
   the words of its id, title, description, tags and authors; `packageid:<id>` finds one
   id exactly, and `id:<text>` the ids that contain it. Prereleases are found when they
   are asked for. A search takes at most 1,000 results, and none past the 3,000th.
   MegooArti counts no downloads.
+- **A proxy's remote** is a feed's `index.json`. The proxy reads in it where the feed
+  serves its packages, its registrations and its search (nuget.org searches on another
+  host), and serves an `index.json` of its own, with its own addresses and no place to
+  push to. A package and its `.nuspec` are kept, and read as a pushed one is, so that
+  the web UI and MegooArti's search find them. An id's versions and its registration are
+  checked again with the remote after `metadata_max_age_minutes`; what the proxy passes
+  on of them has the feed's addresses made its own. A search is passed on to the feed
+  every time, and not kept. A proxy's `format_config.protocol` is `v3`, the default;
+  `format_config.symbol_url` names a symbol server to proxy, which a later version
+  serves.
 
 ## Clients
 
 Tested with `dotnet` of the .NET SDKs 10 and 8: a package and its symbol package built
 with `dotnet pack`, pushed with an API key, pushed again with `--skip-duplicate`,
-found with `dotnet package search`, restored into a project, and deleted.
+found with `dotnet package search`, restored into a project, and deleted; and, through
+a proxy of nuget.org, a package restored into a project that runs, found with
+`dotnet package search`, and its newer versions listed by `dotnet list package
+--outdated`.
````

- [ ] **Step 3: Run the tests**

Run (in `backend/`): `uv run pytest tests/test_documents.py -q`
Expected: 140 passed.

Run (in `backend/`): `uv run pytest -m docker tests/test_nuget_client.py -q`
Expected: 12 passed: Task 3's four tests for each SDK, beside plan 13a's eight.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_nuget_client.py docs/formats/nuget.md
git commit -m "test: dotnet 10 and 8 restore, search and list outdated packages through a proxy of nuget.org; docs: the NuGet proxy"
```

---

### Task 4: The spec, and every suite

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-nuget-design.md`

- [ ] **Step 1: Write what this plan settled into the spec, and mend section 5's sentence on registrations**

Change `docs/superpowers/specs/2026-10-15-nuget-design.md`:

```diff
@@ -109,13 +109,26 @@ A package client signs in with an API token: as the `X-NuGet-ApiKey` header (wha
 | W16 | Over plain HTTP, the setup's `dotnet` command says to use the `nuget.config`, which marks the source `allowInsecureConnections`. | .NET 9 and later refuse a plain-HTTP source that is not marked so (NU1302). |
 | W17 | The first push of an id holds a lock on the id while it reads how the repository spells it. | Two first pushes in two spellings made two components, one of which the feed no longer showed. |
 
+### Settled while building plan 13b
+
+| # | What | Why |
+| --- | --- | --- |
+| X1 | A proxy's remote is a feed's service index, kept as metadata under `.remote/index.json`, a path no client asks for. Of it the proxy uses `PackageBaseAddress/3.0.0`, one registration (`3.6.0` first: SemVer 2.0.0), and search and autocomplete (`3.5.0` first); a feed without a package address or a registration is refused with `502`. The proxy's own `index.json` offers no place to push to, and no search where the feed has none. | 6: where the feed serves each resource is the feed's to say, as it is for NuGet's clients. |
+| X2 | A registration the feed sends gzipped whatever it is asked for is inflated, to 32 MiB; no other document is taken gzipped. | nuget.org's registrations are stored gzipped and served so, `Accept-Encoding: identity` or not. |
+| X3 | What is kept of a registration is what the feed sent; the addresses in it are made the proxy's as it is sent: each of the feed's registrations, of whatever kind, becomes the proxy's one registration, and its package address the proxy's. A page or a version's document is asked of the feed's registration by the same path. The catalog's addresses are left as they are. | A search or a dependency names any of the feed's registrations; restore never reads the catalog. |
+| X4 | A package and its `.nuspec` fetched through a proxy are read as pushed ones are (`Format.describe_fetched`, a member every format has), and their version is a component spelled as its package spells its id. They are kept for the proxy's content age, as every proxy's files are: `-1` keeps them for good, as 6 says, and a package asked about again costs the feed a `304`. | One way of describing a package, however it arrives; the proxy settings are every proxy's. |
+| X5 | A search and an autocomplete are passed on with the client's query as it came, and their answers are not kept: a feed that cannot be reached answers `502`. | D5: a search is the feed's. |
+| X6 | `format_config.protocol` is `v3` until plan 13d (a V2 feed is refused with `422`), fixed once the proxy is made; `format_config.symbol_url` is checked as a remote's address is, and kept without its last slash. | D2, and plan 13f's symbol server. |
+| X7 | Over plain HTTP, the setup's `dotnet` command marks the source with `--allow-insecure-connections`, which the .NET SDK 9 and later take, and says that .NET 8 leaves it out (in place of W16). | The .NET SDK 9 has the option; 8 does not. |
+| X8 | A hosted registration with no version left to show is `404`. | Its last version may go between its two reads. |
+
 ## 5. Hosted repositories
 
 - **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
 - **Push of a version that is there:** `409` under `disable_redeploy`, the default (D6); `allow_redeploy` replaces it; `read_only` refuses every push.
 - **Push of a `.snupkg`:** `PUT api/v2/symbolpackage`, or `api/v2/package` (as older clients do). Its `.nuspec` must name a package version the repository has (`404` otherwise); it is stored beside it, and section 8 says what is read of it.
 - **Delete:** `DELETE api/v2/package/<id>/<version>`, the web UI or the API removes the version and every asset of it (D4). A version that is not there is `404`.
-- **V3:** the version list, registration and search are written from the records of 5's push (E1), as the repository's revision has them, and kept by revision as the Linux formats' indexes are. Registration has every version of an id inlined in pages of 64, as nuget.org's; a version's entry has its `.nuspec`'s fields, its dependency groups, `packageContent`, `published` (the time it was pushed) and `listed: true`.
+- **V3:** the version list, registration and search are written from the records of 5's push (E1), as the repository's revision has them, and written on each request (W1). Registration has every version of an id, inlined up to 128 versions and in pages of 64 beyond (W14); a version's entry has its `.nuspec`'s fields, its dependency groups, `packageContent`, `published` (the time it was pushed) and `listed: true`.
 - **V2:** `Packages()`, `FindPackagesById()`, `Search()` and `Packages(Id,Version)` are answered from the same records, as Atom feeds of `m:properties` with the properties the clients read (`Id`, `Version`, `NormalizedVersion`, `Title`, `Description`, `Authors`, `Tags`, `Dependencies`, `IsLatestVersion`, `IsAbsoluteLatestVersion`, `IsPrerelease`, `Published`, `PackageHash`, `PackageHashAlgorithm`, `PackageSize`, `DownloadCount` and the others of nuget.org's `$metadata`). The queries a hosted repository answers are those of 7.3.
 - **Search:** over id, title, description, tags and authors, as `q` says (`id:` and `packageid:` as nuget.org reads them), with `prerelease` and `semVerLevel`; ranked with an exact id first, then the id's beginning, then the rest; `totalHits` as asked. MegooArti counts no downloads: a hosted package's download count is 0, and an order by downloads keeps the order by relevance.
 - **Usage:** `dotnet add package <id> --version <version>`, `<PackageReference Include="<id>" Version="<version>" />`, `Install-Package <id> -Version <version>`, `choco install <id> --version <version>`, `Install-PSResource <id> -Version <version>`.
```

- [ ] **Step 2: Run every suite**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3751 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; this plan changes nothing there.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, Task 3's twelve among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 13b settled"
```
