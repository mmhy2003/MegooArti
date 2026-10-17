# NuGet V2 Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A NuGet group serves V2 beside V3, so that Chocolatey given one address installs the packages you push and the community feed's alike; and each protocol is asked only of the members that speak it.

**Architecture:** A new module, `nuget/grouped_v2.py`, answers a group's V2: it asks each member that serves V2 for its first `skip + top + 1` entries of a query, with the group's own address, merges them in the members' order with an id's version once, and cuts the page, writing its own link to the next. What it asks of a member is data, not a response: a hosted member's entries come from `v2.found_of` written by `atom.rendered`; a V2 proxy's from `proxied_v2.listing`, its feed's answer rewritten and split into entries, its feed's next pages followed; a group's from the group's own merge. `feeds.speaks` says which protocol a member serves, and V3's merging leaves V2 proxies out as V2's leaves V3 proxies out.

**Tech Stack:** Python 3.13, FastAPI; pytest with the in-process stand-in remote; Chocolatey 2.7.4 and the community feed for the real-client test.

**Spec:** [docs/superpowers/specs/2026-10-15-nuget-design.md](../specs/2026-10-15-nuget-design.md), sections 7.1 and 7.3, E3 and E5, 10 (`choco` through a group) and the row of plan 13e in section 12, with what plans 13a to 13d settled (W, X, Y and Z in section 4).

## Decisions this plan settles

Task 3 writes these into the spec's section 4, as "Settled while building plan 13e".

| # | Decision | Reason |
| --- | --- | --- |
| G2 | A group's V2 feed is written on each request, as its V3 documents are (Y1). A query is asked of each member for its first `skip + top + 1` entries, with the group's own address: a hosted member writes them, a V2 proxy rewrites its feed's (following the feed's next pages, ten at the most, for as many as are asked), a group merges its own. They are merged in the members' order, an id's version (in lower case, normalized) kept once, the first member's; the page is cut from them, and its next link asks for the same with `$skip` past it (in place of 7.3's `$skiptoken`). | One entry more than the page says whether there is a next one; `$skip` is what the group's own next links need, and what a hosted repository's write (Z3). |
| G3 | A group's count (`/$count`, `$inlinecount=allpages`) is its members' counts less the entries dropped among those it read: a feed is asked its count with `$inlinecount=allpages`, a hosted repository counts its own. | What can be known without reading every member's every entry, as V3's `totalHits` (7.2). |
| G4 | An entry, `Packages(Id='…',Version='…')`, is the first member's that has it, with the group's address; a package at `package/<id>/<version>` is the first member's that has it, as the group engine answers. V2's root and `$metadata` are the group's own. A query that no client sends is refused by the group, before any member is asked. | 7.3, and Y10: a member's own answer would carry its addresses. |
| G5 | A group's V2 order is its members': each member orders what it gives as the query asks, and the group keeps them in the members' order. | 7.3's merging; a group cannot order a feed's entries it has not read. |
| G6 | The Chocolatey test installs, through a group of the hosted repository and the V2 proxy of the community feed, a package pushed to the hosted member and one of the community feed's. | Section 10's `choco` through a group. |"""

## Global Constraints

- **A format never touches a table or a file**: what a group asks of its members is the group engine's (`group.member_contexts`, `group.handle_group`, `group.TRY_NEXT`), and each member's own reading.
- **No address of a member's reaches a client of a group**, and none of a feed's but where the feed's own entries name other places (its gallery's pages).
- **What is asked of a remote goes with its credential**: a V2 proxy asks its feed only for a path of V2's feed (Z12), a next page only if it is under the feed's root and is one.
- **A V2 page is at most 100 versions** (Z3); a group follows at most ten of a feed's pages for one member's entries.
- **Every test of a stack is marked `docker`.** The group's real-client test reaches the community feed.
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **What a feed's entries are like**: namespace prefixes other than `d:` and `m:`, an entry whose `<id>` names no `Packages(Id,Version)`, entries the Gallery writes with other elements, a feed whose next link is relative or on another host.
2. **The newest version through a group**: `IsLatestVersion` of a hosted member's and of a feed's for one id, both in a page, and what `choco install` and `nuget.exe` then take.
3. **Pages far down**: a `$skip` of hundreds, so that each member is asked for hundreds of entries and a feed's next pages run out at ten, and the count against what was read.
4. **Members that fail half-way**: a feed whose first page arrives and whose second does not, a hosted member that counts and a feed that does not, a member taken offline between the entry and its package.
5. **Groups of groups for V2**: a group that is a member of two groups, a V3 proxy inside an inner group, the entries' addresses through two groups.

---

### Task 1: A group's V2 feed

**Files:**
- Create: `backend/src/megooarti/repositories/nuget/grouped_v2.py`
- Modify: `backend/src/megooarti/repositories/nuget/atom.py`, `v2.py`, `proxied_v2.py`, `feeds.py`, `grouped.py`, `format.py`
- Create (tests): `backend/tests/repositories/nuget/test_groups_v2.py`

**Interfaces:**
- Consumes: plan 13d's `odata.parse`, `odata.entry_of` (from its review), `atom.*`, `v2.*`, `proxied_v2.*`; plan 13c's `feeds._members`, `grouped.handle_group`; the group engine's `group.member_contexts`, `group.handle_group`, `group.TRY_NEXT`.
- Produces:
  - `atom.ENTRIES` (an entry of a feed, as text), `atom.rendered(base, held, newest) -> str`, `atom.named(entry) -> (id, version) | None`, `atom.key_of(entry) -> str | None` (`<id in lower case>/<normalized version in lower case>`), `atom.feed_of(base, title, entries, *, updated, count=None, next_address="") -> bytes`, which `atom.feed` now calls.
  - `v2.found_of(context, query) -> (page, more, total | None)` (was `_found`), `v2.next_address(base, path, request, query) -> str` (was `_next`), `v2.entry_of(context, id, version, base) -> bytes | None`, `v2.unsupported(error) -> ApiError` (was `_unsupported`).
  - `proxied_v2.answer_of(context, path, query) -> bytes` (was `_answer`, given the query string), `proxied_v2.entry_document(context, path, base) -> bytes`, `proxied_v2.listing(context, path, arguments, base, wanted, *, counted) -> (list[(key, entry)], total)`, `proxied_v2.PAGES_MOST = 10`.
  - `feeds.speaks(context, protocol) -> bool`; V3's merging asks only the members that speak `v3`.
  - `grouped_v2.merged(context, request, path, query, base, wanted, counted) -> (list[(key, entry)], total)`, `grouped_v2.answer(context, request, path, base)`; `grouped.handle_group` sends V2's paths there, and a package at `package/<id>/<version>` to the group engine; the format's `handle_group` takes off the slashes before a V2 path.

- [ ] **Step 1: Write the failing tests**

The group has a hosted repository, a V2 proxy of a stand-in feed that has a version the hosted repository has too, and a V3 proxy, which serves no V2.

Create `backend/tests/repositories/nuget/test_groups_v2.py`:

```python
"""NuGet's V2 protocol of a group: one feed of its members that serve V2, its hosted
members, V2 proxies and groups (E3, 7.3) — queries merged in the members' order, an id's
version once, the page cut by the group, with the group's own addresses."""

from xml.etree import ElementTree

import pytest

from tests.accounts import error_code
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg

GROUP = "/repository/nuget-all"
BASE = "https://test/repository/nuget-all/"
REMOTE = "http://remote.test/api/v2/"
ATOM = "{http://www.w3.org/2005/Atom}"
D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
M = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
PUSHED = "Pushed here."
FETCHED = nupkg("MegooArti.Hello", "3.0.0", description="On the feed.")


def entry(package_id: str, version: str, description: str = "On the feed.") -> str:
    """An entry as the community feed writes one."""
    address = f"{REMOTE}Packages(Id='{package_id}',Version='{version}')"
    return (
        f"<entry><id>{address}</id>"
        f'<link rel="edit" title="V2FeedPackage" href="{address}" />'
        f'<title type="text">{package_id}</title>'
        f'<content type="application/zip" src="{REMOTE}package/{package_id}/{version}" />'
        f"<m:properties><d:Id>{package_id}</d:Id><d:Version>{version}</d:Version>"
        f"<d:NormalizedVersion>{version}</d:NormalizedVersion>"
        f"<d:Description>{description}</d:Description></m:properties></entry>"
    )


def feed(*entries: str, count: int | None = None, next_page: str = "") -> bytes:
    counted = f"<m:count>{count}</m:count>" if count is not None else ""
    following = f'<link rel="next" href="{next_page}" />' if next_page else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<feed xml:base="{REMOTE}" xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        f"{counted}<id>{REMOTE}Packages</id>{''.join(entries)}{following}</feed>"
    ).encode()


def entries(answer) -> list[tuple[str, str, str, str]]:
    """Each entry's id, normalized version, description and package address."""
    assert answer.status_code == 200, answer.text
    root = ElementTree.fromstring(answer.content)
    found = root.findall(f"{ATOM}entry") if root.tag == f"{ATOM}feed" else [root]
    listed = []
    for one in found:
        properties = one.find(f"{M}properties")
        listed.append(
            (
                properties.findtext(f"{D}Id"),
                properties.findtext(f"{D}NormalizedVersion"),
                properties.findtext(f"{D}Description"),
                one.find(f"{ATOM}content").get("src"),
            )
        )
    return listed


def next_link(answer) -> str | None:
    root = ElementTree.fromstring(answer.content)
    links = [link.get("href") for link in root.findall(f"{ATOM}link") if link.get("rel") == "next"]
    return links[0] if links else None


async def make(client, root, **body) -> None:
    answer = await client.post(
        "/api/v1/repositories", json={"format": "nuget", **body}, headers=root
    )
    assert answer.status_code == 201, answer.text


@pytest.fixture
async def group(client, hosted, root, fake_remote):
    """`nuget-all`: a hosted repository with MegooArti.Hello 1.0.0 and 2.0.0; a V2 proxy
    of a feed with its 1.0.0 and 3.0.0, and Choco.Thing 1.0.0; a V3 proxy, which serves
    no V2 and is left out of it."""
    for version in ("1.0.0", "2.0.0"):
        package = nupkg("MegooArti.Hello", version, description=PUSHED)
        assert (await push(client, root, package)).status_code == 201
    await make(
        client,
        root,
        name="choco",
        type="proxy",
        format_config={"protocol": "v2"},
        proxy={"remote_url": REMOTE, "metadata_max_age_minutes": 0},
    )
    await make(
        client,
        root,
        name="nuget-org",
        type="proxy",
        proxy={"remote_url": "http://v3.test/v3/index.json"},
    )
    await make(
        client,
        root,
        name="nuget-all",
        type="group",
        group={"members": ["nuget-hosted", "choco", "nuget-org"]},
    )
    hello = [entry("MegooArti.Hello", "1.0.0"), entry("MegooArti.Hello", "3.0.0")]
    fake_remote.files["api/v2/FindPackagesById()"] = feed(*hello, count=2)
    fake_remote.files["api/v2/Search()"] = feed(*hello, entry("Choco.Thing", "1.0.0"), count=3)
    fake_remote.files["api/v2/Packages(Id='MegooArti.Hello',Version='3.0.0')"] = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<entry xml:base="http://remote.test/api/v2/" xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        + entry("MegooArti.Hello", "3.0.0").removeprefix("<entry>")
    ).encode()
    fake_remote.files["api/v2/package/MegooArti.Hello/3.0.0"] = FETCHED
    return fake_remote


async def get(client, root, path: str, **arguments):
    return await client.get(f"{GROUP}/{path}", params=arguments, headers=root)


def asked(remote, path: str) -> list[str]:
    return [seen["query"] for seen in remote.requests if seen["path"] == f"/api/v2/{path}"]


async def test_the_root_and_metadata_are_the_groups_own(client, root, group):
    service = await get(client, root, "")
    metadata = await get(client, root, "$metadata")

    assert f'xml:base="{BASE}"'.encode() in service.content
    assert b'FunctionImport Name="FindPackagesById"' in metadata.content
    assert group.requests == []


async def test_a_query_is_merged_in_the_members_order_an_ids_version_once(client, root, group):
    answer = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")

    assert [(one[0], one[1], one[2]) for one in entries(answer)] == [
        ("MegooArti.Hello", "1.0.0", PUSHED),  # the first member's
        ("MegooArti.Hello", "2.0.0", PUSHED),
        ("MegooArti.Hello", "3.0.0", "On the feed."),
    ]
    assert [one[3] for one in entries(answer)] == [
        f"{BASE}package/MegooArti.Hello/{version}" for version in ("1.0.0", "2.0.0", "3.0.0")
    ]
    assert "remote.test" not in answer.text
    assert "/repository/nuget-hosted/" not in answer.text
    assert "/repository/choco/" not in answer.text


async def test_a_page_is_cut_by_the_group_and_leads_to_the_next(client, root, group):
    first = await get(client, root, "Search()", searchTerm="''", **{"$top": "2"})
    following = await client.get(next_link(first).removeprefix("https://test"), headers=root)
    counted = await get(client, root, "Search()/$count", searchTerm="''")

    assert [(one[0], one[1]) for one in entries(first)] == [
        ("MegooArti.Hello", "1.0.0"),
        ("MegooArti.Hello", "2.0.0"),
    ]
    assert next_link(first) == f"{BASE}Search()?searchTerm=''&$top=2&$skip=2"
    assert [(one[0], one[1]) for one in entries(following)] == [
        ("MegooArti.Hello", "3.0.0"),
        ("Choco.Thing", "1.0.0"),
    ]
    assert next_link(following) is None
    # Each member is asked for the page's end and one more, from the first.
    assert asked(group, "Search()")[0] == "searchTerm=''&$skip=0&$top=3"
    # Two of the hosted repository's, three of the feed's, less the one both have.
    assert counted.text == "4"


async def test_an_entry_is_the_first_members_that_has_it(client, root, group):
    pushed = await get(client, root, "Packages(Id='megooarti.hello',Version='1.0.0')")
    fetched = await get(client, root, "Packages(Id='MegooArti.Hello',Version='3.0.0')")
    missing = await get(client, root, "Packages(Id='MegooArti.Hello',Version='9.0.0')")

    assert entries(pushed)[0][2] == PUSHED
    assert entries(fetched)[0][3] == f"{BASE}package/MegooArti.Hello/3.0.0"
    assert missing.status_code == 404


async def test_a_package_is_the_first_members_that_has_it(client, root, group):
    pushed = await get(client, root, "package/MegooArti.Hello/1.0.0")
    fetched = await get(client, root, "package/MegooArti.Hello/3.0.0")

    assert pushed.content == nupkg("MegooArti.Hello", "1.0.0", description=PUSHED)
    assert fetched.content == FETCHED


async def test_each_protocol_is_asked_of_the_members_that_serve_it(client, root, group):
    await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")
    await get(client, root, "v3/package/megooarti.hello/index.json")

    hosts = {seen["host"] for seen in group.requests}
    # The V2 proxy is asked V2's query, and not V3's; the V3 proxy V3's, and not V2's.
    assert asked(group, "FindPackagesById()")
    assert not [seen for seen in group.requests if seen["path"].startswith("/api/v2/v3")]
    assert not [
        seen for seen in group.requests if seen["host"] == "v3.test" and "Packages" in seen["path"]
    ]
    assert "v3.test" in hosts


async def test_a_member_that_cannot_be_asked_is_passed_over(client, root, group):
    group.down = True

    answer = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")

    assert [(one[0], one[1]) for one in entries(answer)] == [
        ("MegooArti.Hello", "1.0.0"),
        ("MegooArti.Hello", "2.0.0"),
    ]


async def test_a_feeds_next_page_is_followed_for_the_entries_asked_for(client, root, group):
    group.files["api/v2/FindPackagesById()"] = feed(
        entry("MegooArti.Hello", "3.0.0"),
        next_page=f"{REMOTE}FindPackagesById?id='MegooArti.Hello'&$skiptoken='3.0.0'",
    )
    group.files["api/v2/FindPackagesById"] = feed(entry("MegooArti.Hello", "4.0.0"))

    answer = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")

    assert [one[1] for one in entries(answer)] == ["1.0.0", "2.0.0", "3.0.0", "4.0.0"]
    assert asked(group, "FindPackagesById") == ["id='MegooArti.Hello'&$skiptoken='3.0.0'"]


async def test_a_group_in_a_group_is_one_feed_too(client, root, group):
    await make(client, root, name="nuget-outer", type="group", group={"members": ["nuget-all"]})

    inner = await get(client, root, "FindPackagesById()", id="'MegooArti.Hello'")
    outer = await client.get(
        "/repository/nuget-outer/FindPackagesById()",
        params={"id": "'MegooArti.Hello'"},
        headers=root,
    )

    assert [one[:3] for one in entries(outer)] == [one[:3] for one in entries(inner)]
    assert {one[3] for one in entries(outer)} == {
        f"https://test/repository/nuget-outer/package/MegooArti.Hello/{version}"
        for version in ("1.0.0", "2.0.0", "3.0.0")
    }


async def test_a_query_no_client_sends_is_refused_by_the_group(client, root, group):
    answer = await get(client, root, "Packages()", **{"$filter": "Title eq 'x'"})

    assert (answer.status_code, error_code(answer)) == (400, "unsupported_query")
    assert group.requests == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/nuget -q`
Expected: 10 failed, 235 passed: every test of `test_groups_v2.py` fails, a group answering V2's paths with `404` (and so a query no client sends with `404`, not `400`).

- [ ] **Step 3: Write the code**

`atom.py` writes an entry as text, and reads one; `proxied_v2.py` reads entries with it. `v2.py` and `proxied_v2.py` give a group what it asks of a member as data, with the group's address. `feeds.py` leaves a V2 proxy out of V3.

Change `backend/src/megooarti/repositories/nuget/atom.py`:

```diff
@@ -7,11 +7,13 @@ properties NuGet's clients read, as nuget.org's V2 feed has them.
 """
 
 import base64
+import html
+import re
 from collections.abc import Sequence
 from datetime import UTC, datetime
 from xml.sax.saxutils import escape, quoteattr
 
-from megooarti.repositories.nuget import versions
+from megooarti.repositories.nuget import odata, versions
 from megooarti.repositories.nuget.documents import Published
 
 ATOM = "application/atom+xml;type=feed;charset=utf-8"
@@ -25,6 +27,9 @@ _NAMESPACES = (
 )
 _SCHEME = "http://schemas.microsoft.com/ado/2007/08/dataservices/scheme"
 _TYPE = "NuGetGallery.OData.V2FeedPackage"
+# An entry of a feed, as text; the address of the version it is of, by its id.
+ENTRIES = re.compile(r"<entry\b.*?</entry>", re.DOTALL)
+_ENTRY_ID = re.compile(r"<id>[^<]*/(Packages\([^<]*\))</id>")
 
 # Of each id: the normalized versions, in lower case, of its newest stable version and
 # of its newest version, prereleases too ("" for none).
@@ -152,6 +157,25 @@ def _entry(base: str, held: Published, newest: Latest, *, alone: bool = False) -
     )
 
 
+def rendered(base: str, held: Published, newest: Latest) -> str:
+    """A version as an entry of a feed, as text."""
+    return _entry(base, held, newest)
+
+
+def named(entry: str) -> tuple[str, str] | None:
+    """The id and the version an entry's id names, as written; None if it names none."""
+    found = _ENTRY_ID.search(entry)
+    return None if found is None else odata.entry_of(html.unescape(found[1]))
+
+
+def key_of(entry: str) -> str | None:
+    """What an entry is of, an id and a version as NuGet matches them: in lower case, the
+    version normalized. None for an entry of what is not one."""
+    found = named(entry)
+    version = None if found is None else versions.normalize(found[1])
+    return None if version is None else f"{found[0].lower()}/{version.lower()}"  # type: ignore[index]
+
+
 def entry(base: str, held: Published, newest: Latest) -> bytes:
     """`Packages(Id='…',Version='…')`: one version, as an entry of its own."""
     return (_DECLARATION + _entry(base, held, newest, alone=True)).encode()
@@ -168,6 +192,20 @@ def feed(
 ) -> bytes:
     """A page of versions: each with what is newest of its id. `count` is written for
     `$inlinecount=allpages`; `next_address` leads to the next page, if there is one."""
+    entries = [_entry(base, held, newest) for held, newest in found]
+    return feed_of(base, title, entries, updated=updated, count=count, next_address=next_address)
+
+
+def feed_of(
+    base: str,
+    title: str,
+    entries: Sequence[str],
+    *,
+    updated: datetime,
+    count: int | None = None,
+    next_address: str = "",
+) -> bytes:
+    """A page of entries, each as text written with `base`, as `feed` writes them."""
     parts = [
         f"{_DECLARATION}<feed xml:base={quoteattr(base)} {_NAMESPACES}>",
         f"<m:count>{count}</m:count>" if count is not None else "",
@@ -175,7 +213,7 @@ def feed(
         f'<title type="text">{escape(title)}</title>',
         f"<updated>{_atom_time(updated)}</updated>",
         f'<link rel="self" title="{escape(title)}" href="{escape(title)}"/>',
-        *(_entry(base, held, newest) for held, newest in found),
+        *entries,
         f'<link rel="next" href={quoteattr(next_address)}/>' if next_address else "",
         "</feed>",
     ]
```

Change `backend/src/megooarti/repositories/nuget/v2.py`:

```diff
@@ -28,7 +28,7 @@ NAMES_MOST = 10_000
 Found = tuple[Published, atom.Latest]
 
 
-def _unsupported(error: odata.UnsupportedQuery) -> ApiError:
+def unsupported(error: odata.UnsupportedQuery) -> ApiError:
     return ApiError(
         400, "unsupported_query", f"This feed does not answer that query: {error}.", None
     )
@@ -163,7 +163,7 @@ def _in_name_order(order: Sequence[tuple[str, bool]]) -> bool:
     )
 
 
-async def _found(
+async def found_of(
     context: RepositoryContext, query: odata.Query
 ) -> tuple[list[Found], bool, int | None]:
     """The page a query asks for, whether there is more, and how many there are if the
@@ -182,7 +182,7 @@ async def _found(
     return found[query.skip : wanted], len(found) > wanted, total
 
 
-def _next(base: str, path: str, request: Request, query: odata.Query) -> str:
+def next_address(base: str, path: str, request: Request, query: odata.Query) -> str:
     """The address of the page after this one: the same query, `$skip` past it."""
     arguments = [
         (name, value) for name, value in request.query_params.multi_items() if name != "$skip"
@@ -197,14 +197,22 @@ async def _respond(
     return await responses.respond(context, request, data, content_type, "feed.xml")
 
 
-async def _entry(context: RepositoryContext, request: Request, query: odata.Query) -> Response:
-    spelling = await context.spelling("", query.id)
+async def entry_of(
+    context: RepositoryContext, package_id: str, version: str, base: str
+) -> bytes | None:
+    """`Packages(Id='…',Version='…')`, `version` normalized in lower case, with the
+    addresses under `base`; None if this repository has no such version."""
+    spelling = await context.spelling("", package_id)
     held = [] if spelling is None else records.published(await context.components("", spelling))
-    chosen = [one for one in held if one.nuspec.version.lower() == query.version]
-    if not chosen:
-        raise ApiError(404, "not_found", f"This repository has no {query.id} {query.version}.")
+    chosen = [one for one in held if one.nuspec.version.lower() == version]
+    return atom.entry(base, chosen[0], atom.latest(held)) if chosen else None
+
+
+async def _entry(context: RepositoryContext, request: Request, query: odata.Query) -> Response:
     base = await responses.base(context, request)
-    document = atom.entry(base, chosen[0], atom.latest(held))
+    document = await entry_of(context, query.id, query.version, base)
+    if document is None:
+        raise ApiError(404, "not_found", f"This repository has no {query.id} {query.version}.")
     return await _respond(context, request, document, atom.ATOM_ENTRY)
 
 
@@ -228,10 +236,10 @@ async def answer(context: RepositoryContext, request: Request, path: str) -> Res
     try:
         query = odata.parse(path, request.query_params)
     except odata.UnsupportedQuery as error:
-        raise _unsupported(error) from None
+        raise unsupported(error) from None
     if query.function == odata.ENTRY:
         return await _entry(context, request, query)
-    page, more, total = await _found(context, query)
+    page, more, total = await found_of(context, query)
     if query.count:
         count = str(total).encode()
         return await responses.respond(context, request, count, "text/plain", "count")
@@ -242,6 +250,6 @@ async def answer(context: RepositoryContext, request: Request, path: str) -> Res
         page,
         updated=datetime.now(UTC),
         count=total if query.inline_count else None,
-        next_address=_next(base, path, request, query) if more else "",
+        next_address=next_address(base, path, request, query) if more else "",
     )
     return await _respond(context, request, document, atom.ATOM)
```

Change `backend/src/megooarti/repositories/nuget/proxied_v2.py`:

```diff
@@ -15,7 +15,8 @@ names the one collection, is the proxy's own.
 import hashlib
 import html
 import re
-from urllib.parse import quote, urljoin
+from collections.abc import Sequence
+from urllib.parse import quote, urlencode, urljoin
 
 from starlette.requests import Request
 from starlette.responses import Response
@@ -40,10 +41,14 @@ METADATA_MOST = 1024 * 1024
 _SAFE = "()'=,$/"
 _ADDRESS = re.compile(r'(xml:base|href|src)="([^"]*)"')
 _ID = re.compile(r"<id>([^<]*)</id>")
-_ENTRY = re.compile(r"<entry\b.*?</entry>", re.DOTALL)
-_ENTRY_ID = re.compile(r"<id>[^<]*/(Packages\([^<]*\))</id>")
 _CONTENT = re.compile(r'(<content\b[^>]*\bsrc=")([^"]*)(")')
 _BASE = re.compile(r'xml:base="([^"]*)"')
+_NEXT = re.compile(
+    r'<link\b[^>]*\brel="next"[^>]*\bhref="([^"]*)"|<link\b[^>]*\bhref="([^"]*)"[^>]*\brel="next"'
+)
+_COUNT = re.compile(r"<m:count>([0-9]+)</m:count>")
+# The pages of a feed's answer a group follows, at the most, for the entries it asks for.
+PAGES_MOST = 10
 
 
 def _not_found() -> ApiError:
@@ -77,14 +82,13 @@ def rewrite(data: bytes, feed: str, base: str) -> bytes:
 
     text = _ADDRESS.sub(lambda found: f'{found[1]}="{swap(found[2])}"', text)
     text = _ID.sub(lambda found: f"<id>{swap(found[1])}</id>", text)
-    return _ENTRY.sub(lambda found: _packaged(found[0], target), text).encode("utf-8")
+    return atom.ENTRIES.sub(lambda found: _packaged(found[0], target), text).encode("utf-8")
 
 
 def _packaged(entry: str, target: str) -> str:
     """An entry whose package is at the proxy's `package/<id>/<version>`, as its id says,
     wherever the feed has it."""
-    named = _ENTRY_ID.search(entry)
-    found = None if named is None else odata.entry_of(html.unescape(named[1]))
+    found = atom.named(entry)
     if found is None:
         return entry
     package_id, version = (quote(part, safe="") for part in found)
@@ -111,9 +115,9 @@ def _content_type(path: str) -> str:
     return atom.ATOM
 
 
-async def _answer(context: RepositoryContext, request: Request, path: str) -> bytes:
-    """What the feed answers a query: kept, or for a search, asked each time."""
-    query = request.url.query
+async def answer_of(context: RepositoryContext, path: str, query: str) -> bytes:
+    """What the feed answers a query, `path` a function's and `query` its string as the
+    feed is to be sent it: kept, or for a search, asked each time."""
     address = f"{root(context)}{quote(path, safe=_SAFE)}" + (f"?{query}" if query else "")
     if path.split("/")[0].removesuffix("()") != "Search":
         return await proxy.document(
@@ -157,7 +161,7 @@ async def handle_proxy(context: RepositoryContext, request: Request, path: str)
         return await responses.respond(context, request, data, atom.XML, "metadata.xml")
     parsed = paths.classify(path)
     if parsed.kind == "v2" and _a_feed_path(path):
-        data = await _answer(context, request, path)
+        data = await answer_of(context, path, request.url.query)
         content_type = _content_type(path)
         if content_type != "text/plain":
             try:
@@ -176,6 +180,75 @@ async def handle_proxy(context: RepositoryContext, request: Request, path: str)
     raise _not_found()
 
 
+def _prefixes(context: RepositoryContext, text: str) -> list[str]:
+    """The feed's roots, as the proxy is given it and as an answer names it."""
+    declared = _BASE.search(text)
+    found = {root(context).rstrip("/")} | ({declared[1].rstrip("/")} if declared else set())
+    return sorted((prefix for prefix in found if prefix), key=len, reverse=True)
+
+
+def _next_of(context: RepositoryContext, text: str) -> tuple[str, str] | None:
+    """The path and the query of an answer's next page, if it has one under the feed's
+    root and it is a path of V2's feed."""
+    found = _NEXT.search(text)
+    if found is None:
+        return None
+    address = html.unescape(found[1] or found[2])
+    prefixes = _prefixes(context, text)
+    if "://" not in address:
+        address = f"{prefixes[0]}/{address}" if prefixes else address
+    for prefix in prefixes:
+        if address.startswith(prefix + "/"):
+            path, _, query = address[len(prefix) + 1 :].partition("?")
+            if paths.classify(path).kind == "v2" and path and _a_feed_path(path):
+                return path, query
+    return None
+
+
+async def entry_document(context: RepositoryContext, path: str, base: str) -> bytes:
+    """An entry the feed has, `path` its `Packages(Id='…',Version='…')`, kept, with the
+    addresses under `base`. Raises 404 for one the feed does not have, or is not asked."""
+    if not _a_feed_path(path):
+        raise _not_found()
+    return rewrite(await answer_of(context, path, ""), root(context), base)
+
+
+async def listing(
+    context: RepositoryContext,
+    path: str,
+    arguments: Sequence[tuple[str, str]],
+    base: str,
+    wanted: int,
+    *,
+    counted: bool,
+) -> tuple[list[tuple[str, str]], int]:
+    """The feed's first `wanted` entries of a query, each as its key and its text with
+    the addresses under `base`, and how many there are: the feed's count if `counted`,
+    else as many as were read. The feed's next pages are followed for them."""
+    kept = [
+        (name, value) for name, value in arguments if name not in ("$skip", "$top", "$inlinecount")
+    ]
+    kept += [("$skip", "0"), ("$top", str(wanted))]
+    if counted:
+        kept.append(("$inlinecount", "allpages"))
+    asked: tuple[str, str] | None = (path, urlencode(kept, quote_via=quote, safe="'$(),"))
+    entries: list[tuple[str, str]] = []
+    total = None
+    for _ in range(PAGES_MOST):
+        if asked is None or len(entries) >= wanted:
+            break
+        raw = (await answer_of(context, *asked)).decode("utf-8", errors="replace")
+        if total is None and (count := _COUNT.search(raw)) is not None:
+            total = int(count[1])
+        text = rewrite(raw.encode(), root(context), base).decode()
+        for found in atom.ENTRIES.findall(text):
+            if (key := atom.key_of(found)) is not None:
+                entries.append((key, found))
+        asked = _next_of(context, raw)
+    entries = entries[:wanted]
+    return entries, total if counted and total is not None else len(entries)
+
+
 async def _package_address(context: RepositoryContext, package_id: str, version: str) -> str:
     """Where the feed has a version's package: as its entry says, the entry kept as any
     answer is. Raises 404 if the feed has no such entry, or one without a package."""
```

Change `backend/src/megooarti/repositories/nuget/feeds.py`:

```diff
@@ -20,12 +20,23 @@ from megooarti.repositories.content import RepositoryContext
 from megooarti.repositories.nuget import documents, paths, proxied, queries, records, versions
 
 
+def speaks(context: RepositoryContext, protocol: str) -> bool:
+    """Whether a repository serves a protocol, `v3` or `v2`: a hosted repository and a
+    group serve both, a proxy the one it speaks to its remote (E3)."""
+    if context.repository.type != "proxy":
+        return True
+    return context.repository.config.get("format_config", {}).get("protocol", "v3") == protocol
+
+
 async def _members[T](
     context: RepositoryContext, request: Request, ask: Callable[[RepositoryContext], Awaitable[T]]
 ) -> list[T]:
-    """What each online member gives, in order; nothing of one that has nothing."""
+    """What each online member that serves V3 gives, in order; nothing of one that has
+    nothing."""
     given = []
     for member in await group.member_contexts(context, request):
+        if not speaks(member, "v3"):
+            continue
         try:
             given.append(await ask(member))
         except ApiError as error:
```

Create `backend/src/megooarti/repositories/nuget/grouped_v2.py`:

```python
"""NuGet's V2 protocol of a group: one feed of the members that serve V2, its hosted
members, its V2 proxies and its groups (E3, 7.3 of the spec).

A query is asked of each member for its first `skip + top` entries, with the group's own
address, so that what each gives names the group alone; the answers are merged in the
members' order, the first entry of an id and a version kept, and the page asked for cut
from them, with the group's own link to the next (E5). An entry is the first member's
that has it. A package at V2's address is the first member's that has it, as the group
engine answers; the root and `$metadata` are the group's own.
"""

from dataclasses import replace
from datetime import UTC, datetime

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import group
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import atom, feeds, odata, proxied_v2, responses, v2

# An entry as text, and its key: its id and its version as NuGet matches them.
Keyed = tuple[str, str]


def _not_found(message: str = "No member of this group has it.") -> ApiError:
    return ApiError(404, "not_found", message)


async def _listing(
    member: RepositoryContext,
    request: Request,
    path: str,
    query: odata.Query,
    base: str,
    wanted: int,
    counted: bool,
) -> tuple[list[Keyed], int]:
    """A member's first `wanted` entries of a query, and how many it has: its count if
    `counted`, else as many as it gave."""
    kind = member.repository.type
    if kind == "hosted":
        asked = replace(query, skip=0, top=wanted, inline_count=counted, count=False)
        page, _, total = await v2.found_of(member, asked)
        listed = []
        for held, newest in page:
            written = atom.rendered(base, held, newest)
            listed.append((atom.key_of(written) or "", written))
        return listed, total if total is not None else len(listed)
    if kind == "proxy":
        # A count is asked of the feed as its query, counted.
        function = path.removesuffix("/$count")
        arguments = request.query_params.multi_items()
        return await proxied_v2.listing(member, function, arguments, base, wanted, counted=counted)
    return await merged(member, request, path, query, base, wanted, counted)


async def merged(
    context: RepositoryContext,
    request: Request,
    path: str,
    query: odata.Query,
    base: str,
    wanted: int,
    counted: bool,
) -> tuple[list[Keyed], int]:
    """The first `wanted` entries of a query of a group's members that serve V2, in their
    order, an id's version once, and how many there are: the members' counts less the
    entries dropped. A member that is offline or cannot be asked gives nothing."""
    given = []
    for member in await group.member_contexts(context, request):
        if not feeds.speaks(member, "v2"):
            continue
        try:
            given.append(await _listing(member, request, path, query, base, wanted, counted))
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    entries: list[Keyed] = []
    seen: set[str] = set()
    total = dropped = 0
    for listed, counted_total in given:
        total += counted_total
        for key, written in listed:
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            entries.append((key, written))
    return entries[:wanted], max(total - dropped, len(entries))


async def _entry_of(
    context: RepositoryContext, request: Request, path: str, query: odata.Query, base: str
) -> bytes | None:
    """An entry of a group's: the first member's that has it, with the group's address."""
    for member in await group.member_contexts(context, request):
        if not feeds.speaks(member, "v2"):
            continue
        try:
            if member.repository.type == "hosted":
                found = await v2.entry_of(member, query.id, query.version, base)
            elif member.repository.type == "proxy":
                found = await proxied_v2.entry_document(member, path, base)
            else:
                found = await _entry_of(member, request, path, query, base)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            continue
        if found is not None:
            return found
    return None


async def answer(context: RepositoryContext, request: Request, path: str, base: str) -> Response:
    """A request of a group's V2 feed: its root, `$metadata`, an entry, or a query."""
    if path == "":
        document = atom.service_document(base)
        return await responses.respond(context, request, document, atom.XML, "feed.xml")
    if path == "$metadata":
        return await responses.respond(context, request, atom.METADATA, atom.XML, "metadata.xml")
    try:
        query = odata.parse(path, request.query_params)
    except odata.UnsupportedQuery as error:
        raise v2.unsupported(error) from None
    if query.function == odata.ENTRY:
        found = await _entry_of(context, request, path, query, base)
        if found is None:
            raise _not_found()
        return await responses.respond(context, request, found, atom.ATOM_ENTRY, "feed.xml")
    counted = query.count or query.inline_count
    end = query.skip + query.top
    # One more than the page asked for: whether there is a next page.
    entries, total = await merged(context, request, path, query, base, end + 1, counted)
    if query.count:
        return await responses.respond(context, request, str(total).encode(), "text/plain", "count")
    page = [written for _, written in entries[query.skip : end]]
    more = len(entries) > end
    document = atom.feed_of(
        base,
        path.removesuffix("()"),
        page,
        updated=datetime.now(UTC),
        count=total if query.inline_count else None,
        next_address=v2.next_address(base, path, request, query) if more else "",
    )
    return await responses.respond(context, request, document, atom.ATOM, "feed.xml")
```

Change `backend/src/megooarti/repositories/nuget/grouped.py`:

```diff
@@ -15,7 +15,14 @@ from megooarti.errors import ApiError
 from megooarti.repositories import group
 from megooarti.repositories.content import RepositoryContext
 from megooarti.repositories.formats import Serve
-from megooarti.repositories.nuget import documents, feeds, paths, proxied, responses
+from megooarti.repositories.nuget import (
+    documents,
+    feeds,
+    grouped_v2,
+    paths,
+    proxied,
+    responses,
+)
 
 
 def _not_found(message: str = "No member of this group has it.") -> ApiError:
@@ -60,11 +67,13 @@ async def handle_group(
         # The generic engine says what a group takes.
         return await group.handle_group(context, request, path, serve)
     base = await responses.base(context, request)
+    parsed = paths.classify(path)
+    if parsed.kind == "v2":
+        return await grouped_v2.answer(context, request, path, base)
     if path == paths.SERVICE_INDEX:
         audit = await feeds.vulnerability_index(context, request, base)
         index = documents.service_index(base, publish=False, vulnerabilities=audit is not None)
         return await responses.respond_json(context, request, index)
-    parsed = paths.classify(path)
     if parsed.kind == "versions":
         listed = await feeds.versions_of(context, request, parsed.id)
         if not listed:
@@ -82,8 +91,11 @@ async def handle_group(
         if audit is None:
             raise _not_found()
         return await responses.respond_json(context, request, audit)
-    # A package, its `.nuspec`, a file of NuGet Audit's: the first member that has it.
-    # Nothing else is asked of the members: what they would answer has their addresses.
-    if path.startswith(paths.PACKAGES) or proxied.vulnerability_name(path) is not None:
+    # A package, its `.nuspec`, a file of NuGet Audit's, a package at V2's address: the
+    # first member that has it. Nothing else is asked of the members: what they would
+    # answer has their addresses.
+    if parsed.kind == "download" or path.startswith(paths.PACKAGES):
+        return await group.handle_group(context, request, path, serve)
+    if proxied.vulnerability_name(path) is not None:
         return await group.handle_group(context, request, path, serve)
     raise _not_found()
```

Change `backend/src/megooarti/repositories/nuget/format.py`:

```diff
@@ -495,7 +495,7 @@ class NuGetFormat(Format):
     async def handle_group(
         self, context: RepositoryContext, request: Request, path: str, serve: Serve
     ) -> Response:
-        return await grouped.handle_group(context, request, path, serve)
+        return await grouped.handle_group(context, request, paths.v2_path(path), serve)
 
     def default_deployment_policy(self, config: dict[str, Any]) -> str:
         """A version is pushed once, as nuget.org takes it: a second push is `409`."""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/nuget -q`
Expected: 245 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "feat: NuGet groups serve V2, from their hosted members, V2 proxies and groups"
```

---

### Task 2: choco through a group, and the guide

**Files:**
- Modify (tests): `backend/tests/test_chocolatey_client.py`
- Modify: `docs/formats/nuget.md`

**Interfaces:**
- Consumes: Task 1's group through the built image; plan 13d's `tests.nuget_stack.prepare`, `hosted`, `proxy`, `run`, `said`, and the Chocolatey test's `choco`, `work`, `PACKAGE`, `FROM_COMMUNITY`.
- Produces: in the Chocolatey test, `GROUP` and the group in the `work` fixture.

- [ ] **Step 1: Write the test**

Through a group of the hosted repository and the proxy of the community feed, `choco` pushes a version to the hosted member, finds it and installs it, and installs a package of the community feed's.

Change `backend/tests/test_chocolatey_client.py`:

```diff
@@ -1,5 +1,5 @@
 """Chocolatey's `choco`, of its Linux image, against the built image: over V2 and over V3,
-and through a V2 proxy of the Chocolatey community feed.
+through a V2 proxy of the Chocolatey community feed, and through a group of both.
 
 Run with `pytest -m docker`. Besides a Docker daemon this needs internet access: to pull
 the image, and for the proxy of the community feed. Each run of `choco` is a new
@@ -19,6 +19,7 @@ pytestmark = pytest.mark.docker
 IMAGE = "chocolatey/choco:v2.7.4-linux"
 HOSTED = "nuget-hosted"
 COMMUNITY = "choco-community"
+GROUP = "choco-public"
 PACKAGE = "megooarti-choco"
 # A package of the community feed with nothing to run: Chocolatey's own extension.
 FROM_COMMUNITY = "chocolatey-compatibility.extension"
@@ -43,11 +44,17 @@ NUSPEC = f"""<?xml version="1.0" encoding="utf-8"?>
 @pytest.fixture(scope="module")
 def work(administrator, tmp_path_factory) -> tuple[Path, str]:
     """The folder `choco` works in, with the package's `.nuspec`; and the token to push
-    with. A hosted repository, and a V2 proxy of the community feed."""
+    with. A hosted repository, a V2 proxy of the community feed, and a group of both."""
     token = prepare(
         administrator,
         hosted(HOSTED),
         proxy(COMMUNITY, "https://community.chocolatey.org/api/v2/", protocol="v2"),
+        {
+            "name": GROUP,
+            "format": "nuget",
+            "type": "group",
+            "group": {"members": [HOSTED, COMMUNITY]},
+        },
     )
     folder = tmp_path_factory.mktemp("choco")
     (folder / f"{PACKAGE}.nuspec").write_text(NUSPEC, encoding="utf-8", newline="\n")
@@ -101,3 +108,22 @@ def test_choco_installs_from_a_proxy_of_the_community_feed(work, administrator):
     status, _, components = call("GET", f"/content/{COMMUNITY}/components", None, administrator)
     assert status == 200, components
     assert [item["name"] for item in components["items"]] == [FROM_COMMUNITY]
+
+
+def test_choco_finds_and_installs_through_a_group_of_both(work):
+    _, token = work
+    # Pushed to the hosted member; found and installed, with a package of the community
+    # feed's, through the group.
+    script = (
+        f"choco pack {PACKAGE}.nuspec --version 3.0.0 --outputdirectory out && "
+        f'choco push out/{PACKAGE}.3.0.0.nupkg --source "$1" --api-key "$2" --force && '
+        f"choco search {PACKAGE} --exact && "
+        f"choco install {PACKAGE} --version 3.0.0 --yes && "
+        f"choco install {FROM_COMMUNITY} --yes"
+    )
+
+    done = choco(work, f"{ADDRESS}/{GROUP}/", script, f"{ADDRESS}/{HOSTED}/", token)
+
+    assert done.returncode == 0, said(done)
+    assert f"{PACKAGE} 3.0.0" in done.stdout
+    assert done.stdout.count("Chocolatey installed 1/1 packages.") == 2
```

- [ ] **Step 2: Write the guide**

Change `docs/formats/nuget.md`:

```diff
@@ -192,6 +192,13 @@ curl -u admin -H 'Content-Type: application/json' -d '{
   package, its `.nuspec` and its symbol package come from the first member that has
   them. A member that is offline, or whose feed cannot be reached, is passed over.
   Every address in what a group serves is its own.
+- **A group serves V2 too**, at its own address, from its hosted members, its V2
+  proxies and its groups; V3 comes from its hosted members, its V3 proxies and its
+  groups. Chocolatey given a group of a hosted repository and a proxy of the community
+  feed installs what you push and the feed's packages alike. A V2 query is asked of
+  each member, the answers listed in the members' order, an id's version once, as the
+  first member that has it has it; the group writes its own pages, and its own links
+  to the next.
 - **An id is every member's in a group.** A public package with the id of one you push
   adds its versions beside yours: a floating version (`1.*`) or `dotnet add package`
   without a version can take a version of nuget.org's. Give your packages a prefix
@@ -221,8 +228,10 @@ with a known vulnerability.
 Tested with `nuget.exe` 6.14 under Mono 6.12, over V2 and over V3: a package built
 with `nuget pack`, pushed, installed at a version and at its newest, listed (over V2),
 and deleted. With Chocolatey's `choco` 2.7.4 of its Linux image, over V2 and over V3: a
-package built with `choco pack`, pushed, found with `choco search` and installed; and,
-through a V2 proxy of the community feed, a package installed. With PowerShell 7.5's
+package built with `choco pack`, pushed, found with `choco search` and installed;
+through a V2 proxy of the community feed, a package installed; and through a group of
+the two, a pushed package found and installed, and one of the community feed's
+installed. With PowerShell 7.5's
 PSResourceGet 1.1, over V2 and over V3: a module published, found by a range of
 versions, installed and imported; and, through a V2 proxy of the PowerShell Gallery, a
 module installed.
```

- [ ] **Step 3: Run the tests**

Run (in `backend/`): `uv run pytest tests/test_documents.py -q`
Expected: 140 passed.

Run (in `backend/`): `uv run pytest -m docker tests/test_nuget_client.py tests/test_chocolatey_client.py -q`
Expected: 24 passed: `dotnet`'s twenty, and `choco`'s four, the group's among them.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_chocolatey_client.py docs/formats/nuget.md
git commit -m "test: choco through a NuGet group of a hosted repository and a proxy of the community feed; docs: V2 in groups"
```

---

### Task 3: The spec, and every suite

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-nuget-design.md`

- [ ] **Step 1: Write what this plan settled into the spec**

Change `docs/superpowers/specs/2026-10-15-nuget-design.md`:

```diff
@@ -176,6 +176,17 @@ A package client signs in with an API token: as the `X-NuGet-ApiKey` header (wha
 | Z14 | A V2 proxy reads a search's answer to 64 MiB, a kept answer to 16 MiB. | A search is not kept, and the Gallery answers PSResourceGet's `$top=6000` with tens of megabytes: 49 MB for all its modules. |
 | Z15 | An order by download counts orders nothing, each being 0: the ids of a query of many are taken in the order of what comes after it, by id if that is the id. | Ordered by `DownloadCount desc,Id`, the ids were taken as V3's search ranks them, and a page of the order by id was cut from those read. |
 
+### Settled while building plan 13e
+
+| # | What | Why |
+| --- | --- | --- |
+| G1 | A group serves V2 from its hosted members, its V2 proxies and its groups, and V3 from its hosted members, its V3 proxies and its groups: a proxy is left out of the protocol it does not speak, and is not asked it (E3). | A V2 feed cannot be asked V3's questions, nor a V3 feed V2's. |
+| G2 | A group's V2 feed is written on each request, as its V3 documents are (Y1). A query is asked of each member for its first `skip + top + 1` entries, with the group's own address: a hosted member writes them, a V2 proxy rewrites its feed's (following the feed's next pages, ten at the most, for as many as are asked), a group merges its own. They are merged in the members' order, an id's version (in lower case, normalized) kept once, the first member's; the page is cut from them, and its next link asks for the same with `$skip` past it (in place of 7.3's `$skiptoken`). | One entry more than the page says whether there is a next one; `$skip` is what the group's own next links need, and what a hosted repository's write (Z3). |
+| G3 | A group's count (`/$count`, `$inlinecount=allpages`) is its members' counts less the entries dropped among those it read: a feed is asked its count with `$inlinecount=allpages`, a hosted repository counts its own. | What can be known without reading every member's every entry, as V3's `totalHits` (7.2). |
+| G4 | An entry, `Packages(Id='…',Version='…')`, is the first member's that has it, with the group's address; a package at `package/<id>/<version>` is the first member's that has it, as the group engine answers. V2's root and `$metadata` are the group's own. A query that no client sends is refused by the group, before any member is asked. | 7.3, and Y10: a member's own answer would carry its addresses. |
+| G5 | A group's V2 order is its members': each member orders what it gives as the query asks, and the group keeps them in the members' order. | 7.3's merging; a group cannot order a feed's entries it has not read. |
+| G6 | The Chocolatey test installs, through a group of the hosted repository and the V2 proxy of the community feed, a package pushed to the hosted member and one of the community feed's. | Section 10's `choco` through a group. |
+
 ## 5. Hosted repositories
 
 - **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
```

- [ ] **Step 2: Run every suite**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3861 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; this plan changes nothing there.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, Task 2's among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 13e settled"
```
