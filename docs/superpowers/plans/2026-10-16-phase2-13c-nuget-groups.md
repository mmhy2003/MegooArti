# NuGet V3 Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A NuGet group is one V3 feed of its members': a machine whose one source is the group restores the packages pushed to a hosted member and nuget.org's through a proxy, finds both with `dotnet package search`, sees newer versions with `dotnet list package --outdated`, and gets NuGet Audit's warnings, which proxies and groups now pass on.

**Architecture:** What a repository has is asked of it as data in `nuget/feeds.py`: an id's versions, its registration's items, a search, an autocomplete, NuGet Audit's index; a hosted repository reads its database, a proxy its feed (through new functions of `nuget/proxied.py`), and a group asks its members, with the group's own address, and merges what they give. `nuget/grouped.py` writes a group's documents from that data on each request with `documents.py`'s new merging functions, and leaves packages and NuGet Audit's files to the group engine every format shares, which takes the first member that has them. The proxy passes on NuGet Audit's data (`VulnerabilityInfo/6.7.0`) as it keeps registrations: as metadata, gzipped from nuget.org.

**Tech Stack:** Python 3.13, FastAPI; pytest with the in-process stand-in remote; the .NET SDKs 10 and 8 against nuget.org for the real-client tests.

**Spec:** [docs/superpowers/specs/2026-10-15-nuget-design.md](../specs/2026-10-15-nuget-design.md), sections 7.1, 7.2, 9, 10, 11 and the row of plan 13c in section 12, with what plans 13a and 13b settled (W and X in section 4), X11 above all.

## Decisions this plan settles

Task 3 writes these into the spec's section 4, as "Settled while building plan 13c".

| # | Decision | Reason |
| --- | --- | --- |
| Y1 | A group writes its version lists, registrations, searches and autocompletes on each request from what its members have, and keeps none of them (in place of 7.2's caching). Each member keeps what it keeps: a proxy its feed's documents as metadata, a hosted repository nothing (W1). Measured through a group of a hosted repository and a proxy of nuget.org, over AWSSDK.S3 (1,570 versions): its registration took 8 s the first time, while the proxy fetched the feed's 25 pages, and 0.2 to 0.25 s after; its version list 0.04 s. | What a group keeps would change with every member's push, delete and fetch; written on request, it is right after each of them, and costs little once its members have what they keep. |
| Y2 | A group asks each member for data, not documents (`nuget/feeds.py`), with the group's own address: a hosted member writes its items with it, a proxy rewrites its feed's with it, and a group in a group is asked the same way. | No address of a member's, or of a feed's registration or packages, reaches a client of the group. The catalog's addresses are left as the feed wrote them (X3). |
| Y3 | A group's registration has every version any member has, a version several have taken from the first (by its normalized version), inlined up to 128 versions and in pages of 64 at their own addresses beyond (W14); a version's leaf is written from its item. A proxy's registration pages that its feed lists by address are fetched, if they are under the feed's registration, and kept. | 7.2 and W14; a page elsewhere is not the feed's to have the proxy ask for. |
| Y4 | A search or an autocomplete is merged as 7.2 says, each member asked for its first `skip + take` results at most 1,000 at a time; an autocomplete of an id's versions is every member's together, a prerelease only if asked for, the oldest first. | Members, nuget.org among them, take at most 1,000 results at a time, and a group may be asked for up to the 3,000th. |
| Y5 | A member that is offline, or answers `404`, `502` or `503`, gives nothing to what the group merges, as the group engine passes over it; any other error is the group's. Members are listed once for each request. | As every format's groups do. |
| Y6 | NuGet Audit's data (`VulnerabilityInfo/6.7.0`; in place of X11): a proxy offers it where its feed does, keeping the feed's index (inflated, at most 1 MiB) and each file it names (at most 64 MiB) as metadata, served at `v3/vulnerabilities/<name>.json`; a name the feed's index does not list is `404`, and the feed is not asked. A group offers the first member's index that has one, with the group's addresses, and each file from the first member that has it. A hosted repository has none. | A machine whose one source is a proxy or a group gets NuGet Audit's warnings (`NU1901` to `NU1904`) without naming nuget.org; nuget.org's files are gzipped whatever is asked, and its base file is some megabytes. |
| Y7 | A hosted repository's search over an id of 1,600 versions took 0.1 s, its registration's index 0.05 s and a page 0.1 s (measured in the unit tests' database); nuget.org's search for `awssdk` takes 2.4 to 3.5 s through a proxy or a group, its answer being 3.6 MB. | 11's risk of an id with thousands of versions, measured. |

## Global Constraints

- **A format never touches a table or a file**: what a NuGet group needs of its members is the group engine's (`group.member_contexts`, `group.handle_group`, `group.TRY_NEXT`) and each member's context; what a proxy keeps is the proxy engine's (`proxy.document`, `proxy.ensure_cached`, `proxy.ask`).
- **What is read of a remote is bounded**: the service index and NuGet Audit's index at 1 MiB, a registration document at 32 MiB (inflated), a search's answer at 8 MiB, a NuGet Audit file at 64 MiB (inflated).
- **No address of a member's reaches a client of a group**, and none of a feed's but the catalog's (X3).
- **A V3 search takes at most 1,000 results, and `skip + take` is at most 3,000** (section 9); a member is asked for at most 1,000 at a time.
- **Every test of a stack is marked `docker`.** The real-client tests reach nuget.org.
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; set `MEGOOARTI_TEST_DATABASE_URL` as `docs/development.md` describes.

## Review Focus

What the tests of this plan do not reach, most likely first. The reviewer reads for these.

1. **Members that disagree**: an id spelled differently by two members, a version one member normalizes differently from another, a version listed by one member and unlisted by another, a registration item with no `catalogEntry` or a version NuGet does not take.
2. **A member that fails half-way**: a proxy whose registration index arrives but one of whose pages does not, a feed that answers a search but not its next 1,000, a member taken offline between two reads of one request.
3. **Groups of groups**: a group that is a member of two groups, a group in a group with a proxy whose feed is slow, and what a group lists once per request.
4. **NuGet Audit's data that changes**: a feed's index that names a new file, a file asked for by a name the kept index no longer has, a feed that drops `VulnerabilityInfo` from its service index, a member before the proxy that has data of its own.
5. **What a client follows**: an address in a merged document that leads to a member, to the feed, or to nowhere the group serves; a leaf, a page or a package address that the group answers with `404`.

---

### Task 1: NuGet V3 groups, and NuGet Audit's data passed on

**Files:**
- Create: `backend/src/megooarti/repositories/nuget/records.py`, `feeds.py`, `grouped.py`
- Modify: `backend/src/megooarti/repositories/nuget/paths.py`, `remotes.py`, `responses.py`, `documents.py`, `proxied.py`, `format.py`
- Create (tests): `backend/tests/repositories/nuget/test_groups.py`
- Modify (tests): `backend/tests/repositories/nuget/test_proxy.py`, `test_content.py`

**Interfaces:**
- Consumes: plan 13b's `proxied.resources`, `proxied._parsed`, `proxied._replacements`, `proxied._a_registration_path`, `proxied._a_package_path`, `proxied._PART`, `proxy.document`, `proxy.ensure_cached`, `proxy.ask`, `proxy.Source(gzipped=, remember_missing=, blocks=)`, `remotes.rewrite`, `responses.base`, `responses.respond_json`; plan 13a's `documents.*`, `queries.parse`, `queries.shown`, `versions.normalize`, `versions.parse`, `versions.ordered`, `context.package_page`, `context.components_of`, `context.spelling`, `context.versions`, `context.components`; the group engine's `group.member_contexts(context, request)`, `group.handle_group(context, request, path, serve)`, `group.TRY_NEXT`; `formats.Serve`.
- Produces:
  - `paths.VULNERABILITIES = "v3/vulnerabilities/"`, `paths.VULNERABILITY_INDEX`; `remotes.Resources.vulnerabilities: str` (the feed's `VulnerabilityInfo/6.7.0`, or `""`); `responses.respond_data(context, request, data: bytes)`.
  - `documents.service_index(base, *, publish=True, search=True, autocomplete=True, vulnerabilities=False)`; `documents.item(base, held)` (was `_item`); `documents.version_of(written) -> str | None`; `documents.merged_items(members) -> list[dict]`; `documents.merged_registration(base, package_id, items)`; `documents.merged_page(base, package_id, items, lower, upper) -> dict | None`; `documents.merged_leaf(base, package_id, written)`.
  - `records.DECLARED`, `records.nuspec_of(attributes)`, `records.published(held) -> list[Published]` (moved out of `format.py`).
  - `proxied.registration_document(context, path, relative, base)`, `proxied.items_of(context, package_id, base) -> list`, `proxied.versions_of(context, package_id) -> list[str]`, `proxied.passed_on(context, path, query, base)`, `proxied.vulnerability_index(context, base) -> list[dict]`, `proxied.vulnerability_name(path) -> str | None`, `proxied.VULNERABILITIES_MOST`.
  - `feeds.versions_of(context, request, package_id)`, `feeds.items_of(context, request, package_id, base)`, `feeds.search(context, request, arguments, base) -> (list[dict], int)`, `feeds.hosted_search(context, query, base)`, `feeds.completed_ids(context, request, arguments) -> (list[str], int)`, `feeds.completed_versions(context, request, package_id, prerelease) -> list[str]`, `feeds.vulnerability_index(context, request, base) -> list[dict] | None`.
  - `grouped.handle_group(context, request, path, serve)`; the format's `types` with `group`, `handle_group`, and `is_metadata` true of `v3/vulnerabilities/…`.

- [ ] **Step 1: Write the failing tests**

`test_groups.py` makes a group of the hosted repository and a proxy of a stand-in feed, which both have `MegooArti.Hello` 1.0.0, so that which member's item a version takes shows. `test_proxy.py` gains NuGet Audit's data, gzipped as nuget.org sends it, and `test_content.py` loses its test that a group is not made yet.

Change `backend/tests/repositories/nuget/test_proxy.py`:

```diff
@@ -19,7 +19,7 @@ PACKAGE = nupkg("Newtonsoft.Json", "13.0.3", description="Json.NET is a JSON fra
 FLAT = "nuget/v3-flatcontainer/newtonsoft.json"
 
 
-def service_index(*, search: bool = True) -> bytes:
+def service_index(*, search: bool = True, vulnerabilities: bool = False) -> bytes:
     """The remote's service index, as nuget.org's lays it out: search on another host."""
     resources = [
         {"@id": f"{REMOTE}/v3-flatcontainer/", "@type": "PackageBaseAddress/3.0.0"},
@@ -31,6 +31,10 @@ def service_index(*, search: bool = True) -> bytes:
             {"@id": f"{SEARCH}/query", "@type": "SearchQueryService/3.5.0"},
             {"@id": f"{SEARCH}/autocomplete", "@type": "SearchAutocompleteService/3.5.0"},
         ]
+    if vulnerabilities:
+        resources.append(
+            {"@id": f"{REMOTE}/v3/vulnerabilities/index.json", "@type": "VulnerabilityInfo/6.7.0"}
+        )
     return json.dumps({"version": "3.0.0", "resources": resources}).encode()
 
 
@@ -254,6 +258,8 @@ async def test_a_search_is_passed_on_as_it_came_every_time_with_the_proxys_addre
         ("v3/registration/newtonsoft.json/page/1.0.0/12.0.3.json", True),
         ("v3/package/newtonsoft.json/13.0.3/newtonsoft.json.13.0.3.nupkg", False),
         ("v3/package/newtonsoft.json/13.0.3/newtonsoft.json.nuspec", False),
+        ("v3/vulnerabilities/index.json", True),
+        ("v3/vulnerabilities/update.json", True),
     ],
 )
 def test_an_ids_versions_and_its_registration_are_metadata_and_a_package_is_not(path, metadata):
@@ -335,3 +341,78 @@ async def test_a_failed_search_leaves_the_proxy_to_restore(client, root, remote)
     assert searched.status_code == 502
     # Recorded, and not counted towards leaving the feed alone.
     assert fetched.status_code == 200
+
+
+AUDIT = {
+    "system.text.json": [
+        {"severity": 2, "url": "https://github.com/advisories/GHSA-1", "versions": "[8.0.0, 8.0.4]"}
+    ]
+}
+
+
+def audit_feed(remote) -> None:
+    """NuGet Audit's data on the feed, gzipped whatever is asked, as nuget.org's is."""
+    remote.files["nuget/v3/index.json"] = service_index(vulnerabilities=True)
+    listed = [
+        {
+            "@name": "base",
+            "@id": f"{REMOTE}/v3-vulnerabilities/2026.10.01/vulnerability.base.json",
+            "@updated": "2026-10-01T00:00:00Z",
+            "comment": "The base data for vulnerability update periodically",
+        },
+        {
+            "@name": "update",
+            "@id": f"{REMOTE}/v3-vulnerabilities/2026.10.01/2026.10.15/vulnerability.update.json",
+            "@updated": "2026-10-15T00:00:00Z",
+            "comment": "The patch data for the vulnerability information",
+        },
+    ]
+    for path, document in [
+        ("nuget/v3/vulnerabilities/index.json", listed),
+        ("nuget/v3-vulnerabilities/2026.10.01/vulnerability.base.json", AUDIT),
+        ("nuget/v3-vulnerabilities/2026.10.01/2026.10.15/vulnerability.update.json", {}),
+    ]:
+        remote.files[path] = gzip.compress(json.dumps(document).encode())
+        remote.encodings[path] = "gzip"
+
+
+async def test_nuget_audits_data_is_passed_on_with_the_proxys_addresses_and_kept(
+    client, root, remote
+):
+    audit_feed(remote)
+
+    resources = (await client.get(f"{PROXY}/index.json", headers=root)).json()["resources"]
+    listed = await client.get(f"{PROXY}/v3/vulnerabilities/index.json", headers=root)
+    fetched = await client.get(f"{PROXY}/v3/vulnerabilities/base.json", headers=root)
+    remote.down = True
+    kept = await client.get(f"{PROXY}/v3/vulnerabilities/base.json", headers=root)
+
+    offered = {item["@type"]: item["@id"] for item in resources}
+    assert offered["VulnerabilityInfo/6.7.0"] == f"{BASE}v3/vulnerabilities/index.json"
+    assert [(item["@name"], item["@id"], item["@updated"]) for item in listed.json()] == [
+        ("base", f"{BASE}v3/vulnerabilities/base.json", "2026-10-01T00:00:00Z"),
+        ("update", f"{BASE}v3/vulnerabilities/update.json", "2026-10-15T00:00:00Z"),
+    ]
+    assert fetched.status_code == 200, fetched.text
+    assert fetched.json() == AUDIT
+    assert kept.json() == AUDIT
+
+
+async def test_a_proxy_offers_audit_data_only_where_its_remote_does(client, root, remote):
+    resources = (await client.get(f"{PROXY}/index.json", headers=root)).json()["resources"]
+    listed = await client.get(f"{PROXY}/v3/vulnerabilities/index.json", headers=root)
+
+    assert "VulnerabilityInfo/6.7.0" not in {item["@type"] for item in resources}
+    assert listed.status_code == 404
+
+
+@pytest.mark.parametrize("name", ["other", "index.json/x", "..", "base.json.json"])
+async def test_an_audit_file_the_feeds_index_does_not_name_is_not_asked_of_it(
+    client, root, remote, name
+):
+    audit_feed(remote)
+
+    answer = await client.get(f"{PROXY}/v3/vulnerabilities/{name}.json", headers=root)
+
+    assert answer.status_code == 404
+    assert not [seen for seen in remote.requests if "v3-vulnerabilities" in seen["path"]]
```

Create `backend/tests/repositories/nuget/test_groups.py`:

```python
"""A group of NuGet repositories: one V3 feed of its members' (spec 7.1, 7.2) — an id's
versions together, its registration written by the group from its members' items, a
search merged in the members' order, a package from the first member that has it."""

import gzip
import json

import pytest

from megooarti.repositories.nuget import documents
from tests.repositories.nuget.conftest import push
from tests.repositories.nuget.packages import nupkg

GROUP = "/repository/nuget-all"
BASE = "https://test/repository/nuget-all/"
REMOTE = "http://remote.test/nuget"
PUSHED = "Pushed here."
FETCHED = nupkg("MegooArti.Hello", "3.0.0", description="On the feed.")


def service_index(*, vulnerabilities: bool = False) -> bytes:
    resources = [
        {"@id": f"{REMOTE}/v3-flatcontainer/", "@type": "PackageBaseAddress/3.0.0"},
        {"@id": f"{REMOTE}/registration/", "@type": "RegistrationsBaseUrl/3.6.0"},
        {"@id": f"{REMOTE}/query", "@type": "SearchQueryService/3.5.0"},
        {"@id": f"{REMOTE}/autocomplete", "@type": "SearchAutocompleteService/3.5.0"},
    ]
    if vulnerabilities:
        resources.append(
            {"@id": f"{REMOTE}/v3/vulnerabilities/index.json", "@type": "VulnerabilityInfo/6.7.0"}
        )
    return json.dumps({"version": "3.0.0", "resources": resources}).encode()


def remote_item(package_id: str, version: str, description: str = "On the feed.") -> dict:
    """A version as the feed's registration lists it, at the feed's addresses."""
    lower = package_id.lower()
    return {
        "@id": f"{REMOTE}/registration/{lower}/{version}.json",
        "@type": "Package",
        "packageContent": f"{REMOTE}/v3-flatcontainer/{lower}/{version}/{lower}.{version}.nupkg",
        "registration": f"{REMOTE}/registration/{lower}/index.json",
        "catalogEntry": {
            "@id": f"{REMOTE}/catalog/{lower}.{version}.json",
            "id": package_id,
            "version": version,
            "description": description,
            "listed": True,
            "published": "2026-01-01T00:00:00+00:00",
        },
    }


def remote_registration(remote, package_id: str, items: list[dict]) -> None:
    """The feed's registration of an id, its versions inlined in one page, gzipped."""
    path = f"nuget/registration/{package_id.lower()}/index.json"
    index = f"{REMOTE}/registration/{package_id.lower()}/index.json"
    listed = [item["catalogEntry"]["version"] for item in items]
    page = {
        "@id": f"{index}#page/{listed[0]}/{listed[-1]}",
        "count": len(items),
        "lower": listed[0],
        "upper": listed[-1],
        "items": items,
    }
    document = {"@id": index, "count": 1, "items": [page]}
    remote.files[path] = gzip.compress(json.dumps(document).encode())
    remote.encodings[path] = "gzip"


@pytest.fixture
async def group(client, hosted, root, fake_remote):
    """`nuget-all`: a hosted repository with MegooArti.Hello 1.0.0 and 2.0.0, then a proxy
    of a feed with its 1.0.0 and 3.0.0 and with Newtonsoft.Json 13.0.3."""
    for version in ("1.0.0", "2.0.0"):
        package = nupkg("MegooArti.Hello", version, description=PUSHED)
        assert (await push(client, root, package)).status_code == 201
    for made in [
        {
            "name": "nuget-org",
            "format": "nuget",
            "type": "proxy",
            "proxy": {"remote_url": f"{REMOTE}/v3/index.json", "metadata_max_age_minutes": 0},
        },
        {
            "name": "nuget-all",
            "format": "nuget",
            "type": "group",
            "group": {"members": ["nuget-hosted", "nuget-org"]},
        },
    ]:
        answer = await client.post("/api/v1/repositories", json=made, headers=root)
        assert answer.status_code == 201, answer.text
    fake_remote.files["nuget/v3/index.json"] = service_index()
    flat = "nuget/v3-flatcontainer/megooarti.hello"
    fake_remote.files[f"{flat}/index.json"] = b'{"versions":["1.0.0","3.0.0"]}'
    fake_remote.files[f"{flat}/3.0.0/megooarti.hello.3.0.0.nupkg"] = FETCHED
    fake_remote.files[f"{flat}/1.0.0/megooarti.hello.1.0.0.nupkg"] = b"never asked for"
    remote_registration(
        fake_remote,
        "MegooArti.Hello",
        [remote_item("MegooArti.Hello", "1.0.0"), remote_item("MegooArti.Hello", "3.0.0")],
    )
    remote_registration(fake_remote, "Newtonsoft.Json", [remote_item("Newtonsoft.Json", "13.0.3")])
    return fake_remote


async def get(client, root, path: str, **arguments):
    return await client.get(f"{GROUP}/{path}", params=arguments, headers=root)


async def test_a_group_has_a_service_index_of_its_own_and_takes_no_push(client, root, group):
    answer = await get(client, root, "index.json")

    resources = {item["@type"]: item["@id"] for item in answer.json()["resources"]}
    assert resources["PackageBaseAddress/3.0.0"] == f"{BASE}v3/package/"
    assert resources["RegistrationsBaseUrl/3.6.0"] == f"{BASE}v3/registration/"
    assert resources["SearchQueryService/3.5.0"] == f"{BASE}v3/search"
    assert "PackagePublish/2.0.0" not in resources
    assert "VulnerabilityInfo/6.7.0" not in resources  # no member has NuGet Audit's data
    pushed = await push(client, root, nupkg("Brand.New", "1.0.0"), repository="nuget-all")
    assert pushed.status_code == 405


async def test_an_ids_versions_are_its_members_together(client, root, group):
    nested = await client.post(
        "/api/v1/repositories",
        json={
            "name": "nuget-outer",
            "format": "nuget",
            "type": "group",
            "group": {"members": ["nuget-all"]},
        },
        headers=root,
    )
    assert nested.status_code == 201, nested.text

    listed = await get(client, root, "v3/package/megooarti.hello/index.json")
    outer = await client.get(
        "/repository/nuget-outer/v3/package/megooarti.hello/index.json", headers=root
    )
    unknown = await get(client, root, "v3/package/nothing.here/index.json")

    assert listed.json() == {"versions": ["1.0.0", "2.0.0", "3.0.0"]}
    assert outer.json() == listed.json()
    assert unknown.status_code == 404


async def test_a_registration_is_the_groups_own_with_the_first_members_item_of_a_version(
    client, root, group
):
    answer = await get(client, root, "v3/registration/megooarti.hello/index.json")

    document = answer.json()
    assert answer.status_code == 200, answer.text
    assert document["@id"] == f"{BASE}v3/registration/megooarti.hello/index.json"
    (page,) = document["items"]
    assert (page["count"], page["lower"], page["upper"]) == (3, "1.0.0", "3.0.0")
    shown = {item["catalogEntry"]["version"]: item for item in page["items"]}
    assert list(shown) == ["1.0.0", "2.0.0", "3.0.0"]
    assert shown["1.0.0"]["catalogEntry"]["description"] == PUSHED  # the first member's
    assert shown["3.0.0"]["catalogEntry"]["description"] == "On the feed."
    assert shown["3.0.0"]["packageContent"] == (
        f"{BASE}v3/package/megooarti.hello/3.0.0/megooarti.hello.3.0.0.nupkg"
    )
    # Every address a client follows is the group's: none of a member's, none of the feed's.
    assert "/repository/nuget-hosted/" not in answer.text
    assert "/repository/nuget-org/" not in answer.text
    assert f"{REMOTE}/registration/" not in answer.text
    assert f"{REMOTE}/v3-flatcontainer/" not in answer.text


async def test_a_versions_leaf_is_written_from_its_item(client, root, group):
    leaf = await get(client, root, "v3/registration/megooarti.hello/3.0.0.json")
    unknown = await get(client, root, "v3/registration/megooarti.hello/9.0.0.json")

    assert leaf.status_code == 200, leaf.text
    assert leaf.json()["@id"] == f"{BASE}v3/registration/megooarti.hello/3.0.0.json"
    assert leaf.json()["packageContent"] == (
        f"{BASE}v3/package/megooarti.hello/3.0.0/megooarti.hello.3.0.0.nupkg"
    )
    assert leaf.json()["registration"] == f"{BASE}v3/registration/megooarti.hello/index.json"
    assert unknown.status_code == 404


async def test_a_registration_of_more_than_128_versions_is_paged_by_the_group(client, root, group):
    many = [remote_item("Many.Versions", f"1.{minor}.0") for minor in range(129)]
    remote_registration(group, "Many.Versions", many)

    index = (await get(client, root, "v3/registration/many.versions/index.json")).json()
    second = await get(client, root, "v3/registration/many.versions/page/1.64.0/1.127.0.json")
    unknown = await get(client, root, "v3/registration/many.versions/page/1.0.0/1.62.0.json")

    assert [(page["count"], page["lower"], page["upper"]) for page in index["items"]] == [
        (64, "1.0.0", "1.63.0"),
        (64, "1.64.0", "1.127.0"),
        (1, "1.128.0", "1.128.0"),
    ]
    assert all("items" not in page for page in index["items"])
    assert second.json()["@id"] == f"{BASE}v3/registration/many.versions/page/1.64.0/1.127.0.json"
    assert [item["catalogEntry"]["version"] for item in second.json()["items"]] == [
        f"1.{minor}.0" for minor in range(64, 128)
    ]
    assert unknown.status_code == 404


async def test_a_package_comes_from_the_first_member_that_has_it(client, root, group):
    folder = "v3/package/megooarti.hello"
    pushed = await get(client, root, f"{folder}/1.0.0/megooarti.hello.1.0.0.nupkg")
    fetched = await get(client, root, f"{folder}/3.0.0/megooarti.hello.3.0.0.nupkg")

    assert pushed.content == nupkg("MegooArti.Hello", "1.0.0", description=PUSHED)
    assert fetched.content == FETCHED
    assert "/nuget/v3-flatcontainer/megooarti.hello/1.0.0/" not in str(group.paths())


async def test_a_member_that_cannot_be_asked_is_passed_over(client, root, group):
    group.down = True

    listed = await get(client, root, "v3/package/megooarti.hello/index.json")
    registration = await get(client, root, "v3/registration/megooarti.hello/index.json")

    assert listed.json() == {"versions": ["1.0.0", "2.0.0"]}
    (page,) = registration.json()["items"]
    assert [item["catalogEntry"]["version"] for item in page["items"]] == ["1.0.0", "2.0.0"]


async def test_a_search_is_merged_in_the_members_order(client, root, group):
    found = [
        {"id": "MegooArti.Hello", "version": "3.0.0", "description": "On the feed."},
        {
            "id": "Newtonsoft.Json",
            "version": "13.0.3",
            "registration": f"{REMOTE}/registration/newtonsoft.json/index.json",
        },
    ]
    group.files["nuget/query"] = json.dumps({"totalHits": 2, "data": found}).encode()

    everything = (await get(client, root, "v3/search", q="")).json()
    second = (await get(client, root, "v3/search", q="", skip="1", take="1")).json()

    assert [item["id"] for item in everything["data"]] == ["MegooArti.Hello", "Newtonsoft.Json"]
    assert everything["data"][0]["description"] == PUSHED  # the first member's
    assert everything["data"][1]["registration"] == (
        f"{BASE}v3/registration/newtonsoft.json/index.json"
    )
    assert everything["totalHits"] == 2  # one, and two, less the one both have
    assert [item["id"] for item in second["data"]] == ["Newtonsoft.Json"]
    asked = [seen["query"] for seen in group.requests if seen["path"] == "/nuget/query"]
    # Each member is asked for the results up to the end of the page.
    assert "skip=0" in asked[-1] and "take=2" in asked[-1]


async def test_autocomplete_is_merged_in_the_members_order(client, root, group):
    group.files["nuget/autocomplete"] = b'{"totalHits":2,"data":["megooarti.hello","Other"]}'
    ids = (await get(client, root, "v3/autocomplete", q="o")).json()
    group.files["nuget/autocomplete"] = b'{"totalHits":3,"data":["1.0.0","3.0.0","4.0.0-beta"]}'
    shown = (await get(client, root, "v3/autocomplete", id="MegooArti.Hello")).json()

    assert ids == {"totalHits": 2, "data": ["MegooArti.Hello", "Other"]}
    assert shown == {"totalHits": 3, "data": ["1.0.0", "2.0.0", "3.0.0"]}


async def test_nuget_audits_data_comes_from_the_first_member_that_has_it(client, root, group):
    group.files["nuget/v3/index.json"] = service_index(vulnerabilities=True)
    listed = [{"@name": "base", "@id": f"{REMOTE}/v3-vulnerabilities/base.json"}]
    audit = {"system.text.json": [{"severity": 2, "url": "u", "versions": "[8.0.0, 8.0.4]"}]}
    for path, document in [
        ("nuget/v3/vulnerabilities/index.json", listed),
        ("nuget/v3-vulnerabilities/base.json", audit),
    ]:
        group.files[path] = gzip.compress(json.dumps(document).encode())
        group.encodings[path] = "gzip"

    resources = (await get(client, root, "index.json")).json()["resources"]
    index = await get(client, root, "v3/vulnerabilities/index.json")
    fetched = await get(client, root, "v3/vulnerabilities/base.json")

    offered = {item["@type"]: item["@id"] for item in resources}
    assert offered["VulnerabilityInfo/6.7.0"] == f"{BASE}v3/vulnerabilities/index.json"
    assert [(item["@name"], item["@id"]) for item in index.json()] == [
        ("base", f"{BASE}v3/vulnerabilities/base.json")
    ]
    assert fetched.json() == audit


async def test_a_group_without_audit_data_has_no_index_of_it(client, root, group):
    answer = await get(client, root, "v3/vulnerabilities/index.json")

    assert answer.status_code == 404


def test_a_groups_items_are_the_first_members_for_a_version_the_oldest_first():
    first = [{"catalogEntry": {"version": "2.0.0", "from": "first"}}]
    second = [
        {"catalogEntry": {"version": "2.0"}},
        {"catalogEntry": {"version": "1.0.0-Beta"}},
        {"catalogEntry": {"version": "not one"}},
        {"catalogEntry": {}},
    ]

    merged = documents.merged_items([first, second])

    assert [documents.version_of(item) for item in merged] == ["1.0.0-beta", "2.0.0"]
    assert merged[1]["catalogEntry"]["from"] == "first"


@pytest.mark.parametrize(
    ("path", "remote_path"),
    [("v3/search", "/nuget/query"), ("v3/autocomplete", "/nuget/autocomplete")],
)
async def test_a_page_far_down_is_asked_of_each_member_a_thousand_at_a_time(
    client, root, group, path, remote_path
):
    answer = await get(client, root, path, q="", skip="2990", take="10")

    assert answer.status_code == 200, answer.text
    asked = [seen["query"] for seen in group.requests if seen["path"] == remote_path]
    # The feed takes at most 1,000 at a time, as nuget.org does; it had fewer.
    assert asked == ["q=&skip=0&take=1000"]
```

Change `backend/tests/repositories/nuget/test_content.py`:

```diff
@@ -117,16 +117,6 @@ async def test_a_hosted_repository_refuses_redeploy_unless_told_otherwise(client
     assert made.json()["hosted"] == {"deployment_policy": "disable_redeploy"}
 
 
-async def test_a_proxy_or_a_group_is_not_made_yet(client, root):
-    for kind in ("proxy", "group"):
-        answer = await client.post(
-            "/api/v1/repositories",
-            json={"name": f"nuget-{kind}", "format": "nuget", "type": kind},
-            headers=root,
-        )
-        assert answer.status_code == 422, answer.text
-
-
 async def test_a_refused_upload_leaves_no_file_of_a_package_it_stored_before(
     client, hosted, root, settings
 ):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/nuget -q`
Expected: 4 failed, 148 passed, 13 errors: each test of `test_groups.py` that makes a group errors at its setup, as a NuGet group cannot be made yet (`422`); `documents` has no `merged_items`; the proxy offers no `VulnerabilityInfo/6.7.0`; and `v3/vulnerabilities/…` is not metadata.

- [ ] **Step 3: Write the code**

`records.py` takes from `format.py` what reads a hosted repository's versions, as `feeds.py` reads them too. In `documents.py`, a page is now made from items, so that a hosted registration and a group's are written by one function. The end of `proxied.py`, from `_registration` on, is written again: what it served as documents it now also gives as data.

Change `backend/src/megooarti/repositories/nuget/paths.py`:

```diff
@@ -13,6 +13,9 @@ PACKAGES = "v3/package/"
 REGISTRATION = "v3/registration/"
 SEARCH = "v3/search"
 AUTOCOMPLETE = "v3/autocomplete"
+# NuGet Audit's data: an index of files, each by its name, as nuget.org serves it.
+VULNERABILITIES = "v3/vulnerabilities/"
+VULNERABILITY_INDEX = f"{VULNERABILITIES}index.json"
 PUBLISH = "api/v2/package"
 SYMBOL_PUBLISH = "api/v2/symbolpackage"
 
```

Change `backend/src/megooarti/repositories/nuget/remotes.py`:

```diff
@@ -26,6 +26,7 @@ _SEARCH = (
     "SearchQueryService/3.0.0-beta",
     "SearchQueryService",
 )
+_VULNERABILITIES = ("VulnerabilityInfo/6.7.0",)
 _AUTOCOMPLETE = (
     "SearchAutocompleteService/3.5.0",
     "SearchAutocompleteService/3.0.0-rc",
@@ -49,6 +50,8 @@ class Resources:
     registrations: tuple[str, ...]
     search: str = ""
     autocomplete: str = ""
+    # Where NuGet Audit's index of vulnerability files is, "" where the remote has none.
+    vulnerabilities: str = ""
 
 
 def _slashed(address: str) -> str:
@@ -87,6 +90,7 @@ def read_index(data: bytes) -> Resources:
         registrations=tuple(dict.fromkeys(registrations)),
         search=_first(found, _SEARCH),
         autocomplete=_first(found, _AUTOCOMPLETE),
+        vulnerabilities=_first(found, _VULNERABILITIES),
     )
 
 
```

Change `backend/src/megooarti/repositories/nuget/responses.py`:

```diff
@@ -19,6 +19,11 @@ async def base(context: RepositoryContext, request: Request) -> str:
 async def respond_json(context: RepositoryContext, request: Request, document: Any) -> Response:
     """A document written for this request, as JSON."""
     data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
+    return await respond_data(context, request, data)
+
+
+async def respond_data(context: RepositoryContext, request: Request, data: bytes) -> Response:
+    """JSON that is passed on as it is: what a remote sent, kept."""
     _, changed = await context.revision()
     return context.respond_with(
         data,
```

Change `backend/src/megooarti/repositories/nuget/documents.py`:

```diff
@@ -28,11 +28,17 @@ class Published:
 
 
 def service_index(
-    base: str, *, publish: bool = True, search: bool = True, autocomplete: bool = True
+    base: str,
+    *,
+    publish: bool = True,
+    search: bool = True,
+    autocomplete: bool = True,
+    vulnerabilities: bool = False,
 ) -> dict[str, Any]:
     """`index.json`: where a client finds each of the protocol's resources.
 
-    A proxy offers no place to push to, and searches only where its remote does.
+    A proxy offers no place to push to, and searches only where its remote does; it
+    offers NuGet Audit's data where its remote does, and a group where a member does.
     """
     resources = [
         (paths.PACKAGES, ["PackageBaseAddress/3.0.0"]),
@@ -58,6 +64,7 @@ def service_index(
                 "SearchQueryService/3.5.0",
             ],
         ),
+        (paths.VULNERABILITY_INDEX, ["VulnerabilityInfo/6.7.0"]),
         (
             paths.AUTOCOMPLETE,
             [
@@ -73,6 +80,7 @@ def service_index(
         paths.SYMBOL_PUBLISH: not publish,
         paths.SEARCH: not search,
         paths.AUTOCOMPLETE: not autocomplete,
+        paths.VULNERABILITY_INDEX: not vulnerabilities,
     }
     return {
         "version": "3.0.0",
@@ -152,7 +160,8 @@ def _catalog_entry(base: str, held: Published) -> dict[str, Any]:
     return entry
 
 
-def _item(base: str, held: Published) -> dict[str, Any]:
+def item(base: str, held: Published) -> dict[str, Any]:
+    """A version as a registration lists it: its details, and where its package is."""
     return {
         "@id": _leaf(base, held.nuspec),
         "@type": "Package",
@@ -181,14 +190,14 @@ def _bounds(listed: Sequence[str]) -> list[tuple[str, str, int]]:
 
 
 def _page(
-    base: str, index: str, address: str, held: Sequence[Published], lower: str, upper: str
+    index: str, address: str, items: Sequence[dict[str, Any]], lower: str, upper: str
 ) -> dict[str, Any]:
-    """A page, with its versions' items, `held` being exactly its versions."""
+    """A page, with its versions' items, `items` being exactly its versions'."""
     return {
         "@id": address,
         "@type": "catalog:CatalogPage",
-        "count": len(held),
-        "items": [_item(base, one) for one in held],
+        "count": len(items),
+        "items": list(items),
         "lower": lower,
         "upper": upper,
         "parent": index,
@@ -213,7 +222,8 @@ def registration(base: str, held: Sequence[Published]) -> dict[str, Any]:
     for start in range(0, len(ordered), PAGE):
         page = ordered[start : start + PAGE]
         lower, upper = page[0].nuspec.version.lower(), page[-1].nuspec.version.lower()
-        pages.append(_page(base, index, f"{index}#page/{lower}/{upper}", page, lower, upper))
+        items = [item(base, one) for one in page]
+        pages.append(_page(index, f"{index}#page/{lower}/{upper}", items, lower, upper))
     return _root(index, pages)
 
 
@@ -252,7 +262,7 @@ def registration_page(
     `held` is exactly the page's versions."""
     index = _registration(base, package_id)
     address = f"{base}{paths.page_path(package_id, lower, upper)}"
-    return _page(base, index, address, _ordered(held), lower, upper)
+    return _page(index, address, [item(base, one) for one in _ordered(held)], lower, upper)
 
 
 def leaf(base: str, held: Published) -> dict[str, Any]:
@@ -268,6 +278,78 @@ def leaf(base: str, held: Published) -> dict[str, Any]:
     }
 
 
+# --- What a group writes of its members' registrations ----------------------------------
+
+
+def version_of(written: dict[str, Any]) -> str | None:
+    """The version a registration's item is of, normalized in lower case; None if the
+    item has none NuGet takes."""
+    entry = written.get("catalogEntry")
+    said = entry.get("version") if isinstance(entry, dict) else None
+    normalized = versions.normalize(said) if isinstance(said, str) else None
+    return None if normalized is None else normalized.lower()
+
+
+def merged_items(members: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
+    """Every version's item of members' registrations, the first member's for a version
+    several have, the oldest version first. An item without a version is left out."""
+    chosen: dict[str, dict[str, Any]] = {}
+    for items in members:
+        for written in items:
+            version = version_of(written)
+            if version is not None:
+                chosen.setdefault(version, written)
+    return [chosen[version] for version in versions.ordered(list(chosen))]
+
+
+def merged_registration(
+    base: str, package_id: str, items: Sequence[dict[str, Any]]
+) -> dict[str, Any]:
+    """A group's `v3/registration/<id>/index.json` from its items (`merged_items`): them
+    inlined in pages of 64 if there are at most `INLINED_MOST`, else its pages by their
+    bounds, each at its own address."""
+    listed = [version for written in items if (version := version_of(written))]
+    if len(listed) > INLINED_MOST:
+        return registration_pages(base, package_id, listed)
+    index = _registration(base, package_id)
+    pages = []
+    for start in range(0, len(items), PAGE):
+        page = items[start : start + PAGE]
+        lower, upper = listed[start], listed[start + len(page) - 1]
+        pages.append(_page(index, f"{index}#page/{lower}/{upper}", page, lower, upper))
+    return _root(index, pages)
+
+
+def merged_page(
+    base: str, package_id: str, items: Sequence[dict[str, Any]], lower: str, upper: str
+) -> dict[str, Any] | None:
+    """A page of a group's registration with more than `INLINED_MOST` versions, or None
+    if it has no page with these bounds."""
+    listed = [version for written in items if (version := version_of(written))]
+    wanted = page_of(listed, lower, upper)
+    if wanted is None or len(listed) <= INLINED_MOST:
+        return None
+    start = listed.index(wanted[0])
+    index = _registration(base, package_id)
+    address = f"{base}{paths.page_path(package_id, lower, upper)}"
+    return _page(index, address, items[start : start + len(wanted)], lower, upper)
+
+
+def merged_leaf(base: str, package_id: str, written: dict[str, Any]) -> dict[str, Any]:
+    """A group's `v3/registration/<id>/<version>.json`, from its item."""
+    entry = written.get("catalogEntry")
+    entry = entry if isinstance(entry, dict) else {}
+    return {
+        "@id": written.get("@id", ""),
+        "@type": ["Package", "http://schema.nuget.org/catalog#Permalink"],
+        "catalogEntry": entry.get("@id", ""),
+        "listed": entry.get("listed", True),
+        "packageContent": written.get("packageContent", ""),
+        "published": entry.get("published", ""),
+        "registration": _registration(base, package_id),
+    }
+
+
 def search_result(base: str, found: Sequence[Sequence[Published]], total: int) -> dict[str, Any]:
     """`v3/search`: each id found, with its versions, the newest's details in front."""
     data = []
```

Create `backend/src/megooarti/repositories/nuget/records.py`:

```python
"""What is kept of a NuGet package's `.nuspec`, and the versions it describes."""

from collections.abc import Sequence
from typing import Any

from megooarti.repositories.content import ComponentInfo
from megooarti.repositories.nuget import packages
from megooarti.repositories.nuget.documents import Published

# Where what a package said of itself is kept, among a file's attributes and among its
# version's component's.
DECLARED = "nuget"


def nuspec_of(attributes: dict[str, Any] | None) -> packages.Nuspec | None:
    said = (attributes or {}).get(DECLARED)
    return packages.Nuspec.from_json(said) if isinstance(said, dict) else None


def published(held: Sequence[ComponentInfo]) -> list[Published]:
    """The versions held that a package's `.nuspec` describes, with when each was pushed."""
    return [
        Published(nuspec, one.created)
        for one in held
        if (nuspec := nuspec_of(one.attributes)) is not None
    ]
```

Change `backend/src/megooarti/repositories/nuget/proxied.py`:

```diff
@@ -31,6 +31,8 @@ REMOTE_INDEX = ".remote/index.json"
 INDEX_MOST = 1024 * 1024
 REGISTRATION_MOST = 32 * 1024 * 1024
 SEARCH_MOST = 8 * 1024 * 1024
+# NuGet Audit's files: nuget.org's base file is some megabytes once inflated.
+VULNERABILITIES_MOST = 64 * 1024 * 1024
 
 
 def _not_found() -> ApiError:
@@ -108,9 +110,11 @@ async def _parsed(context: RepositoryContext, path: str, data: bytes) -> Any:
         raise await proxy.refuse(context, path, "it sent a document that is not JSON") from None
 
 
-async def _registration(
-    context: RepositoryContext, request: Request, path: str, relative: str
-) -> Response:
+async def registration_document(
+    context: RepositoryContext, path: str, relative: str, base: str
+) -> Any:
+    """A registration's document as the feed sent it, kept, with its addresses made those
+    under `base`: the proxy's, or a group's in front of it."""
     found = await resources(context)
     data = await proxy.document(
         context,
@@ -119,18 +123,71 @@ async def _registration(
         limit=REGISTRATION_MOST,
         content_type=responses.JSON,
     )
-    base = await responses.base(context, request)
-    document = remotes.rewrite(await _parsed(context, path, data), _replacements(found, base))
-    return await responses.respond_json(context, request, document)
+    return remotes.rewrite(await _parsed(context, path, data), _replacements(found, base))
+
+
+def _items(document: Any) -> list[Any]:
+    items = document.get("items") if isinstance(document, dict) else None
+    return items if isinstance(items, list) else []
 
 
-async def _passed_on(context: RepositoryContext, request: Request, path: str) -> Response:
-    """A search or an autocomplete, passed on as it came, its answer not kept."""
+async def items_of(context: RepositoryContext, package_id: str, base: str) -> list[Any]:
+    """Every version's item of an id's registration on the feed, its pages fetched where
+    the feed lists them by their addresses, with the addresses under `base`. Raises 404
+    or 502 as the feed's registration does."""
+    relative = f"{package_id}/index.json"
+    if not _a_registration_path(relative):
+        raise _not_found()
+    index = await registration_document(
+        context, f"{paths.REGISTRATION}{relative}", quote(relative, safe="/"), base
+    )
+    found: list[Any] = []
+    prefix = f"{base}{paths.REGISTRATION}"
+    for page in _items(index):
+        if not isinstance(page, dict):
+            continue
+        if "items" in page:
+            found += _items(page)
+            continue
+        address = page.get("@id")
+        if not isinstance(address, str) or not address.startswith(prefix):
+            continue  # a page elsewhere than the feed's registration: not asked for
+        page_relative = address[len(prefix) :]
+        if not _a_registration_path(page_relative):
+            continue
+        document = await registration_document(
+            context,
+            f"{paths.REGISTRATION}{page_relative}",
+            quote(page_relative, safe="/"),
+            base,
+        )
+        found += _items(document)
+    return found
+
+
+async def versions_of(context: RepositoryContext, package_id: str) -> list[str]:
+    """An id's versions on the feed, kept as metadata. Raises 404 or 502 as the feed does."""
+    relative = f"{package_id}/index.json"
+    if not _a_package_path(relative):
+        raise _not_found()
+    path = f"{paths.PACKAGES}{relative}"
+    found = await resources(context)
+    escaped = quote(relative, safe="/")
+    await proxy.ensure_cached(context, path, source=Source(f"{found.packages}{escaped}"))
+    data = await context.read(path, limit=REGISTRATION_MOST)
+    document = await _parsed(context, path, data or b"{}")
+    listed = document.get("versions") if isinstance(document, dict) else None
+    return [one for one in listed if isinstance(one, str)] if isinstance(listed, list) else []
+
+
+async def passed_on(context: RepositoryContext, path: str, query: str, base: str) -> Any:
+    """A search or an autocomplete, passed on with `query`, its answer not kept, with its
+    addresses under `base`. Raises 404 where the feed has no such service, 502 where it
+    cannot be asked."""
     found = await resources(context)
     address = found.search if path == paths.SEARCH else found.autocomplete
     if not address:
         raise _not_found()
-    query = request.url.query
     source = Source(
         f"{address}?{query}" if query else address, remember_missing=False, blocks=False
     )
@@ -139,11 +196,64 @@ async def _passed_on(context: RepositoryContext, request: Request, path: str) ->
         raise _not_found()
     if not isinstance(answer, Answer):
         raise answer.error
-    base = await responses.base(context, request)
-    document = remotes.rewrite(
-        await _parsed(context, path, answer.body), _replacements(found, base)
+    return remotes.rewrite(await _parsed(context, path, answer.body), _replacements(found, base))
+
+
+# --- NuGet Audit's data -------------------------------------------------------------
+
+
+async def _vulnerability_entries(context: RepositoryContext) -> list[dict[str, Any]]:
+    """The feed's index of its vulnerability files, kept: each with its `@name` and its
+    address on the feed. Raises 404 where the feed has none."""
+    found = await resources(context)
+    if not found.vulnerabilities:
+        raise _not_found()
+    data = await proxy.document(
+        context,
+        paths.VULNERABILITY_INDEX,
+        Source(found.vulnerabilities, gzipped=True),
+        limit=INDEX_MOST,
+        content_type=responses.JSON,
     )
-    return await responses.respond_json(context, request, document)
+    listed = await _parsed(context, paths.VULNERABILITY_INDEX, data)
+    return [
+        entry
+        for entry in (listed if isinstance(listed, list) else [])
+        if isinstance(entry, dict)
+        and isinstance(entry.get("@name"), str)
+        and _PART.fullmatch(entry["@name"])
+        and isinstance(entry.get("@id"), str)
+    ]
+
+
+async def vulnerability_index(context: RepositoryContext, base: str) -> list[dict[str, Any]]:
+    """NuGet Audit's index, each file at `<base>v3/vulnerabilities/<name>.json`."""
+    return [
+        {**entry, "@id": f"{base}{paths.VULNERABILITIES}{entry['@name']}.json"}
+        for entry in await _vulnerability_entries(context)
+    ]
+
+
+async def _vulnerability_file(context: RepositoryContext, path: str, name: str) -> bytes:
+    """One of NuGet Audit's files, by its name in the feed's index, kept as metadata."""
+    entries = await _vulnerability_entries(context)
+    entry = next((one for one in entries if one["@name"] == name), None)
+    if entry is None:
+        raise _not_found()
+    return await proxy.document(
+        context,
+        path,
+        Source(entry["@id"], gzipped=True),
+        limit=VULNERABILITIES_MOST,
+        content_type=responses.JSON,
+    )
+
+
+def vulnerability_name(path: str) -> str | None:
+    """The name of one of NuGet Audit's files a path is of, or None."""
+    name = path.removeprefix(paths.VULNERABILITIES).removesuffix(".json")
+    shaped = path.startswith(paths.VULNERABILITIES) and path.endswith(".json")
+    return name if shaped and name != "index" and _PART.fullmatch(name) else None
 
 
 async def handle_proxy(context: RepositoryContext, request: Request, path: str) -> Response:
@@ -155,13 +265,15 @@ async def handle_proxy(context: RepositoryContext, request: Request, path: str)
             "A proxy repository accepts GET and HEAD.",
             headers={"Allow": "GET, HEAD"},
         )
+    base = await responses.base(context, request)
     if path == paths.SERVICE_INDEX:
         found = await resources(context)
         index = documents.service_index(
-            await responses.base(context, request),
+            base,
             publish=False,
             search=bool(found.search),
             autocomplete=bool(found.autocomplete),
+            vulnerabilities=bool(found.vulnerabilities),
         )
         return await responses.respond_json(context, request, index)
     if (relative := _relative(path, paths.PACKAGES, _a_package_path)) is not None:
@@ -169,7 +281,15 @@ async def handle_proxy(context: RepositoryContext, request: Request, path: str)
         await proxy.ensure_cached(context, path, source=Source(f"{found.packages}{relative}"))
         return await context.respond(path, request)
     if (relative := _relative(path, paths.REGISTRATION, _a_registration_path)) is not None:
-        return await _registration(context, request, path, relative)
+        document = await registration_document(context, path, relative, base)
+        return await responses.respond_json(context, request, document)
     if path in (paths.SEARCH, paths.AUTOCOMPLETE):
-        return await _passed_on(context, request, path)
+        document = await passed_on(context, path, request.url.query, base)
+        return await responses.respond_json(context, request, document)
+    if path == paths.VULNERABILITY_INDEX:
+        listed = await vulnerability_index(context, base)
+        return await responses.respond_json(context, request, listed)
+    if (name := vulnerability_name(path)) is not None:
+        data = await _vulnerability_file(context, path, name)
+        return await responses.respond_data(context, request, data)
     raise _not_found()
```

Create `backend/src/megooarti/repositories/nuget/feeds.py`:

```python
"""What a NuGet repository has, as data a group merges: of a hosted repository, of a
proxy, and of a group, which merges its own members'.

Each function is given the address its documents are to name (`base`): a group asks
its members for theirs with its own, so that what it merges names only the group. A
member that does not have something, or cannot be asked, gives nothing to the group
(as the generic group engine passes over it); anything else it raises is raised.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.repositories import group
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.nuget import documents, paths, proxied, queries, records, versions


async def _members[T](
    context: RepositoryContext, request: Request, ask: Callable[[RepositoryContext], Awaitable[T]]
) -> list[T]:
    """What each online member gives, in order; nothing of one that has nothing."""
    given = []
    for member in await group.member_contexts(context, request):
        try:
            given.append(await ask(member))
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
    return given


# --- An id's versions -----------------------------------------------------------------


async def versions_of(context: RepositoryContext, request: Request, package_id: str) -> list[str]:
    """An id's versions, normalized in lower case, the oldest first. None, an empty list."""
    kind = context.repository.type
    if kind == "hosted":
        spelling = await context.spelling("", package_id)
        listed = [] if spelling is None else list(await context.versions("", spelling))
    elif kind == "proxy":
        listed = await proxied.versions_of(context, package_id)
    else:
        given = await _members(context, request, lambda one: versions_of(one, request, package_id))
        listed = [version for found in given for version in found]
    normalized = {
        version.lower() for one in listed if (version := versions.normalize(one)) is not None
    }
    return versions.ordered(list(normalized))


# --- An id's registration ---------------------------------------------------------------


async def items_of(
    context: RepositoryContext, request: Request, package_id: str, base: str
) -> list[dict[str, Any]]:
    """Every version's item of an id's registration, with addresses under `base`, the
    oldest first; of a group, the first member's for a version several have."""
    kind = context.repository.type
    if kind == "hosted":
        spelling = await context.spelling("", package_id)
        held = [] if spelling is None else records.published(await context.components("", spelling))
        return documents.merged_items([[documents.item(base, one) for one in held]])
    if kind == "proxy":
        found = await proxied.items_of(context, package_id, base)
        return documents.merged_items([[one for one in found if isinstance(one, dict)]])
    given = await _members(context, request, lambda one: items_of(one, request, package_id, base))
    return documents.merged_items(given)


# --- Search -----------------------------------------------------------------------------


async def _leading[T](
    ask: Callable[[dict[str, str]], Awaitable[tuple[list[T], int]]],
    arguments: Mapping[str, str],
    query: queries.Query,
) -> tuple[list[T], int]:
    """A member's first `skip + take` results, and how many it has: asked for at most
    `TAKE_MOST` at a time, as a member takes them (nuget.org too)."""
    wanted = query.skip + query.take
    found: list[T] = []
    start = 0
    while True:
        take = min(queries.TAKE_MOST, wanted - start)
        listed, total = await ask({**arguments, "skip": str(start), "take": str(take)})
        found += listed
        start += take
        if start >= wanted or len(listed) < take:
            return found, total


def _merged[T](
    given: Sequence[tuple[list[T], int]], key: Callable[[T], str], query: queries.Query
) -> tuple[list[T], int]:
    """Members' results in their order, each key's first, and the page asked for cut
    from them; how many there are is the members' counts less the results dropped."""
    merged: dict[str, T] = {}
    total = dropped = 0
    for found, counted in given:
        total += counted
        for one in found:
            if key(one) in merged:
                dropped += 1
            else:
                merged[key(one)] = one
    listed = list(merged.values())
    return listed[query.skip : query.skip + query.take], max(total - dropped, len(listed))


async def search(
    context: RepositoryContext, request: Request, arguments: Mapping[str, str], base: str
) -> tuple[list[dict[str, Any]], int]:
    """The ids a search finds, as V3's search lists them, and how many there are.

    A group asks each member for its first `skip + take` results, keeps an id's first,
    and cuts the page asked for from them; of the total, it takes off the ids it dropped.
    """
    query = queries.parse(arguments)
    kind = context.repository.type
    if kind == "hosted":
        return await hosted_search(context, query, base)
    if kind == "proxy":
        answer = await proxied.passed_on(context, paths.SEARCH, urlencode(dict(arguments)), base)
        data = answer.get("data") if isinstance(answer, dict) else None
        total = answer.get("totalHits") if isinstance(answer, dict) else None
        found = [one for one in data if isinstance(one, dict)] if isinstance(data, list) else []
        return found, total if isinstance(total, int) else len(found)
    given = await _members(
        context,
        request,
        lambda one: _leading(lambda page: search(one, request, page, base), arguments, query),
    )
    return _merged(given, lambda one: str(one.get("id", "")).lower(), query)


async def hosted_search(
    context: RepositoryContext, query: queries.Query, base: str
) -> tuple[list[dict[str, Any]], int]:
    """A hosted repository's search: its page of ids chosen in the database (W1)."""
    names, total = await context.package_page(
        "",
        query.words,
        exact=query.exact_id,
        containing=query.id_contains,
        ranked_by=" ".join(query.words),
        stable_only=not query.prerelease,
        limit=query.take,
        offset=query.skip,
    )
    held = await context.components_of("", names)
    found = queries.shown(
        query, names, {name: records.published(infos) for name, infos in held.items()}
    )
    return documents.search_result(base, found, total)["data"], total


# --- Autocomplete -------------------------------------------------------------------------


async def completed_ids(
    context: RepositoryContext, request: Request, arguments: Mapping[str, str]
) -> tuple[list[str], int]:
    """The ids that contain what was typed (`q`), as autocomplete lists them, and how
    many there are; of a group, each id once, in its members' order."""
    query = queries.parse({**arguments, "q": ""})
    typed = arguments.get("q", "").strip().lower()
    prerelease = arguments.get("prerelease", "").lower() == "true"
    kind = context.repository.type
    if kind == "hosted":
        return await context.package_page(
            "",
            [],
            containing=typed,
            ranked_by=typed,
            stable_only=not prerelease,
            limit=query.take,
            offset=query.skip,
        )
    if kind == "proxy":
        answer = await proxied.passed_on(
            context, paths.AUTOCOMPLETE, urlencode(dict(arguments)), ""
        )
        data = answer.get("data") if isinstance(answer, dict) else None
        total = answer.get("totalHits") if isinstance(answer, dict) else None
        found = [one for one in data if isinstance(one, str)] if isinstance(data, list) else []
        return found, total if isinstance(total, int) else len(found)
    given = await _members(
        context,
        request,
        lambda one: _leading(lambda page: completed_ids(one, request, page), arguments, query),
    )
    return _merged(given, str.lower, query)


async def completed_versions(
    context: RepositoryContext, request: Request, package_id: str, prerelease: bool
) -> list[str]:
    """An id's versions, as autocomplete lists them given an `id`: a prerelease only if
    asked for, each once, the oldest first."""
    kind = context.repository.type
    if kind == "hosted":
        spelling = await context.spelling("", package_id)
        held = [] if spelling is None else records.published(await context.components("", spelling))
        listed = [one.nuspec.version for one in held]
    elif kind == "proxy":
        arguments = {"id": package_id, "prerelease": "true" if prerelease else "false"}
        answer = await proxied.passed_on(context, paths.AUTOCOMPLETE, urlencode(arguments), "")
        data = answer.get("data") if isinstance(answer, dict) else None
        listed = [one for one in data if isinstance(one, str)] if isinstance(data, list) else []
    else:
        given = await _members(
            context, request, lambda one: completed_versions(one, request, package_id, prerelease)
        )
        listed = [version for found in given for version in found]
    shown: dict[str, str] = {}
    for one in listed:
        parsed = versions.parse(one)
        if parsed is not None and (prerelease or not parsed.is_prerelease):
            shown.setdefault(parsed.normalized.lower(), parsed.normalized)
    return [shown[key] for key in versions.ordered(list(shown))]


# --- NuGet Audit's data -----------------------------------------------------------------


async def vulnerability_index(
    context: RepositoryContext, request: Request, base: str
) -> list[dict[str, Any]] | None:
    """NuGet Audit's index, its files under `base`; of a group, its first member's that
    has one. None where there is none."""
    kind = context.repository.type
    if kind == "hosted":
        return None
    if kind == "proxy":
        try:
            return await proxied.vulnerability_index(context, base)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            return None
    for found in await _members(
        context, request, lambda one: vulnerability_index(one, request, base)
    ):
        if found is not None:
            return found
    return None
```

Create `backend/src/megooarti/repositories/nuget/grouped.py`:

```python
"""A group of NuGet repositories: one V3 feed of its members' (spec 7.1, 7.2).

An id's versions are the union of its members'; its registration is the group's own,
written from its members' items, the first member's for a version several have; a
search and an autocomplete are merged in the members' order. Each is written on each
request from what the members have, each member keeping what it keeps (W1). A package,
its `.nuspec` and a file of NuGet Audit's come from the first member that has them, as
the generic group engine answers. A group signs and checks nothing (E4).
"""

from starlette.requests import Request
from starlette.responses import Response

from megooarti.errors import ApiError
from megooarti.repositories import group
from megooarti.repositories.content import RepositoryContext
from megooarti.repositories.formats import Serve
from megooarti.repositories.nuget import documents, feeds, paths, responses


def _not_found(message: str = "No member of this group has it.") -> ApiError:
    return ApiError(404, "not_found", message)


async def _registration(
    context: RepositoryContext, request: Request, parsed: paths.NuGetPath, base: str
) -> Response:
    items = await feeds.items_of(context, request, parsed.id, base)
    if not items:
        raise _not_found()
    if parsed.kind == "registration":
        document = documents.merged_registration(base, parsed.id, items)
    elif parsed.kind == "page":
        document = documents.merged_page(base, parsed.id, items, parsed.lower, parsed.upper)
    else:
        chosen = [one for one in items if documents.version_of(one) == parsed.version]
        document = documents.merged_leaf(base, parsed.id, chosen[0]) if chosen else None
    if document is None:
        raise _not_found()
    return await responses.respond_json(context, request, document)


async def _autocomplete(context: RepositoryContext, request: Request) -> Response:
    arguments = request.query_params
    if "id" in arguments:
        prerelease = arguments.get("prerelease", "").lower() == "true"
        shown = await feeds.completed_versions(context, request, arguments["id"], prerelease)
        return await responses.respond_json(
            context, request, documents.autocomplete(shown, len(shown))
        )
    ids, total = await feeds.completed_ids(context, request, arguments)
    return await responses.respond_json(context, request, documents.autocomplete(ids, total))


async def handle_group(
    context: RepositoryContext, request: Request, path: str, serve: Serve
) -> Response:
    """Answer a request to a NuGet group. The route has checked `read`."""
    if request.method not in ("GET", "HEAD"):
        # The generic engine says what a group takes.
        return await group.handle_group(context, request, path, serve)
    base = await responses.base(context, request)
    if path == paths.SERVICE_INDEX:
        audit = await feeds.vulnerability_index(context, request, base)
        index = documents.service_index(base, publish=False, vulnerabilities=audit is not None)
        return await responses.respond_json(context, request, index)
    parsed = paths.classify(path)
    if parsed.kind == "versions":
        listed = await feeds.versions_of(context, request, parsed.id)
        if not listed:
            raise _not_found()
        return await responses.respond_json(context, request, documents.version_list(listed))
    if parsed.kind in ("registration", "page", "leaf"):
        return await _registration(context, request, parsed, base)
    if parsed.kind == "search":
        found, total = await feeds.search(context, request, request.query_params, base)
        return await responses.respond_json(context, request, {"totalHits": total, "data": found})
    if parsed.kind == "autocomplete":
        return await _autocomplete(context, request)
    if path == paths.VULNERABILITY_INDEX:
        audit = await feeds.vulnerability_index(context, request, base)
        if audit is None:
            raise _not_found()
        return await responses.respond_json(context, request, audit)
    # A package, its `.nuspec`, a file of NuGet Audit's: the first member that has it.
    return await group.handle_group(context, request, path, serve)
```

Change `backend/src/megooarti/repositories/nuget/format.py`:

```diff
@@ -27,10 +27,11 @@ from starlette.responses import Response
 
 from megooarti.errors import ApiError
 from megooarti.repositories import forms, service
-from megooarti.repositories.content import ComponentInfo, RepositoryContext
+from megooarti.repositories.content import RepositoryContext
 from megooarti.repositories.formats import (
     ComponentKey,
     Format,
+    Serve,
     Usage,
     invalid_upload,
     managed_by_format,
@@ -41,19 +42,19 @@ from megooarti.repositories.formats import (
 from megooarti.repositories.models import Repository
 from megooarti.repositories.nuget import (
     documents,
+    feeds,
+    grouped,
     packages,
     paths,
     proxied,
     queries,
+    records,
     responses,
     versions,
 )
 from megooarti.repositories.nuget.documents import Published
 from megooarti.storage.backends import StagedBlob
 
-# Where what a package said of itself is kept, among a file's attributes and among its
-# version's component's.
-_DECLARED = "nuget"
 _PACKAGE = "application/octet-stream"
 _NUSPEC = "application/xml"
 _PLAIN_HTTP = (
@@ -76,20 +77,6 @@ def _not_allowed(allowed: str) -> ApiError:
     )
 
 
-def _nuspec_of(attributes: dict[str, Any] | None) -> packages.Nuspec | None:
-    said = (attributes or {}).get(_DECLARED)
-    return packages.Nuspec.from_json(said) if isinstance(said, dict) else None
-
-
-def _published(held: Sequence[ComponentInfo]) -> list[Published]:
-    """The versions held that a package's `.nuspec` describes, with when each was pushed."""
-    return [
-        Published(nuspec, one.created)
-        for one in held
-        if (nuspec := _nuspec_of(one.attributes)) is not None
-    ]
-
-
 # --- Pushing ------------------------------------------------------------------------
 
 
@@ -156,7 +143,7 @@ async def _keep_package(
 ) -> bool:
     """A package and its `.nuspec`, each at its path. Returns whether the version is new."""
     nuspec = await _spelled(context, package.nuspec)
-    said = {_DECLARED: nuspec.as_json()}
+    said = {records.DECLARED: nuspec.as_json()}
     _, created = await context.store(
         paths.package_path(nuspec.id, nuspec.version),
         staged,
@@ -185,7 +172,7 @@ async def _keep_symbols(
         paths.symbols_path(nuspec.id, nuspec.version),
         staged,
         content_type=_PACKAGE,
-        attributes={_DECLARED: nuspec.as_json()},
+        attributes={records.DECLARED: nuspec.as_json()},
     )
     return created
 
@@ -226,7 +213,7 @@ async def _delete_version(context: RepositoryContext, package_id: str, version:
 async def _held(context: RepositoryContext, package_id: str) -> list[Published]:
     """Every version of an id this repository holds. Raises 404 for none."""
     spelling = await context.spelling("", package_id)
-    held = [] if spelling is None else _published(await context.components("", spelling))
+    held = [] if spelling is None else records.published(await context.components("", spelling))
     if not held:
         raise _not_found(f"This repository has no package {package_id}.")
     return held
@@ -244,7 +231,7 @@ async def _registration(context: RepositoryContext, request: Request, package_id
         return await responses.respond_json(
             context, request, documents.registration_pages(base, package_id, listed)
         )
-    held = _published(await context.components("", spelling))
+    held = records.published(await context.components("", spelling))
     if not held:
         # Its last version went between the two reads.
         raise _not_found(f"This repository has no package {package_id}.")
@@ -262,7 +249,7 @@ async def _registration_page(
         raise _not_found(f"This repository has no such page of {parsed.id}.")
     held = [
         one
-        for one in _published(await context.components("", spelling))
+        for one in records.published(await context.components("", spelling))
         if one.nuspec.version.lower() in set(wanted)
     ]
     base = await responses.base(context, request)
@@ -271,24 +258,9 @@ async def _registration_page(
 
 
 async def _search(context: RepositoryContext, request: Request) -> Response:
-    query = queries.parse(request.query_params)
-    names, total = await context.package_page(
-        "",
-        query.words,
-        exact=query.exact_id,
-        containing=query.id_contains,
-        ranked_by=" ".join(query.words),
-        stable_only=not query.prerelease,
-        limit=query.take,
-        offset=query.skip,
-    )
-    held = await context.components_of("", names)
-    found = queries.shown(query, names, {name: _published(infos) for name, infos in held.items()})
-    return await responses.respond_json(
-        context,
-        request,
-        documents.search_result(await responses.base(context, request), found, total),
-    )
+    base = await responses.base(context, request)
+    found, total = await feeds.hosted_search(context, queries.parse(request.query_params), base)
+    return await responses.respond_json(context, request, {"totalHits": total, "data": found})
 
 
 async def _autocomplete(context: RepositoryContext, request: Request) -> Response:
@@ -297,7 +269,7 @@ async def _autocomplete(context: RepositoryContext, request: Request) -> Respons
     prerelease = arguments.get("prerelease", "").lower() == "true"
     if "id" in arguments:
         spelling = await context.spelling("", arguments["id"])
-        held = [] if spelling is None else _published(await context.components("", spelling))
+        held = [] if spelling is None else records.published(await context.components("", spelling))
         shown = versions.ordered(
             [one.nuspec.version for one in held if prerelease or not one.nuspec.is_prerelease]
         )
@@ -455,12 +427,12 @@ async def describe_fetched(
             return {}
     except packages.InvalidPackage:
         return {}
-    return {_DECLARED: nuspec.as_json()}
+    return {records.DECLARED: nuspec.as_json()}
 
 
 class NuGetFormat(Format):
     name = "nuget"
-    types = frozenset({"hosted", "proxy"})
+    types = frozenset({"hosted", "proxy", "group"})
     derives_indexes = True
 
     def validate_config(
@@ -477,10 +449,12 @@ class NuGetFormat(Format):
         return await describe_fetched(context, path, staged)
 
     def is_metadata(self, path: str) -> bool:
-        """An id's versions, its registration and the remote's service index change as
-        packages are published; packages and their `.nuspec` do not."""
+        """An id's versions, its registration, NuGet Audit's data and the remote's service
+        index change as packages are published; packages and their `.nuspec` do not."""
         if path == proxied.REMOTE_INDEX or path.startswith(paths.REGISTRATION):
             return True
+        if path.startswith(paths.VULNERABILITIES):
+            return True
         return path.startswith(paths.PACKAGES) and path.endswith("/index.json")
 
     async def handle_proxy(
@@ -488,6 +462,11 @@ class NuGetFormat(Format):
     ) -> Response:
         return await proxied.handle_proxy(context, request, path)
 
+    async def handle_group(
+        self, context: RepositoryContext, request: Request, path: str, serve: Serve
+    ) -> Response:
+        return await grouped.handle_group(context, request, path, serve)
+
     def default_deployment_policy(self, config: dict[str, Any]) -> str:
         """A version is pushed once, as nuget.org takes it: a second push is `409`."""
         return "disable_redeploy"
@@ -496,7 +475,7 @@ class NuGetFormat(Format):
         self, path: str, attributes: dict[str, Any] | None = None
     ) -> ComponentKey | None:
         """A package's files belong to its id and version: as its `.nuspec` said, or its path."""
-        nuspec = _nuspec_of(attributes)
+        nuspec = records.nuspec_of(attributes)
         if nuspec is not None:
             return ComponentKey("", nuspec.id, nuspec.version.lower())
         parsed = paths.classify(path)
@@ -506,7 +485,7 @@ class NuGetFormat(Format):
 
     def search_text(self, key: ComponentKey, attributes: dict[str, Any]) -> str:
         """Its id and version, and the words of its `.nuspec` that NuGet's search reads."""
-        nuspec = _nuspec_of(attributes)
+        nuspec = records.nuspec_of(attributes)
         words = [super().search_text(key, attributes)]
         if nuspec is not None:
             words += [nuspec.title, nuspec.description, nuspec.summary, nuspec.tags, nuspec.authors]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/nuget -q`
Expected: 165 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src backend/tests
git commit -m "feat: NuGet groups of V3 feeds, and NuGet Audit's data passed on by proxies and groups"
```

---

### Task 2: dotnet through a group, NuGet Audit's warnings, and the guide

**Files:**
- Modify (tests): `backend/tests/test_nuget_client.py`
- Modify: `docs/formats/nuget.md`, `README.md`

**Interfaces:**
- Consumes: Task 1's groups and NuGet Audit's data, through the built image; the client test's `config`, `dotnet`, `said`, `work`, `through`, `token`, `package_id`, `JSON_NET`, `VERSION`.
- Produces: in the client test, `GROUP`, `VULNERABLE`, `AUDITED`, `GROUPED`, the `grouped` fixture.

- [ ] **Step 1: Write the tests**

They are of what Task 1 made, through the built image and nuget.org itself: a project restores the SDK's package from the hosted member and Json.NET from nuget.org through the group, and runs; `dotnet package search` finds both, and `dotnet list package --outdated` reads Json.NET's newer versions from the registration the group writes; and Json.NET 12.0.3, which has a known high-severity vulnerability, is restored with NuGet Audit's warning `NU1903`, through the proxy and through the group. The `grouped` fixture pushes each SDK's package again with `--skip-duplicate`, as the hosted tests delete it.

Change `backend/tests/test_nuget_client.py`:

```diff
@@ -23,6 +23,7 @@ IMAGES = {"10": "mcr.microsoft.com/dotnet/sdk:10.0", "8": "mcr.microsoft.com/dot
 NETWORK = f"{PROJECT}_default"
 HOSTED = "nuget-hosted"
 PROXY = "nuget-org"
+GROUP = "nuget-public"
 # What an account that pushes and restores gets: everything on NuGet repositories.
 USERNAME = "ci"
 PASSWORD = "restores-dotnet-packages"
@@ -64,6 +65,34 @@ CODE
 dotnet run
 """
 
+# A version of Json.NET with a known vulnerability, of which NuGet Audit warns: NU1903.
+VULNERABLE = "12.0.3"
+# A project that restores it.
+AUDITED = f"""
+set -e
+cd /work
+dotnet new console -n Old -o old --force > /dev/null
+cd old
+dotnet add package Newtonsoft.Json --version {VULNERABLE} > /dev/null
+dotnet restore --force
+"""
+
+# A project that restores a package of the hosted repository's and one of nuget.org's
+# through the group, and runs.
+GROUPED = f"""
+set -e
+cd /work
+dotnet new console -n App -o app --force > /dev/null
+cd app
+dotnet add package "$1" --version {VERSION}
+dotnet add package Newtonsoft.Json --version {JSON_NET}
+cat > Program.cs <<CODE
+var through = Newtonsoft.Json.JsonConvert.SerializeObject(new {{ through = "group" }});
+System.Console.WriteLine(MegooArti.Greeting.Say() + " " + through);
+CODE
+dotnet run
+"""
+
 # Builds `/work/out/<id>.1.0.0.nupkg` and its `.snupkg`: a library that says hello.
 PACK = f"""
 set -e
@@ -301,3 +330,71 @@ def test_dotnet_searches_and_finds_newer_versions_through_the_proxy(through, sdk
     requested, resolved, latest = line.split()[-3:]
     assert (requested, resolved) == (JSON_NET, JSON_NET)
     assert latest != JSON_NET
+
+
+@pytest.fixture(scope="module")
+def grouped(work, token, administrator, tmp_path_factory) -> dict[str, Path]:
+    """A group of the hosted repository and the proxy, each SDK's package pushed to the
+    hosted one (again, if it was deleted), and each SDK's own folder whose one source is
+    the group."""
+    group = {"name": GROUP, "format": "nuget", "type": "group"}
+    group["group"] = {"members": [HOSTED, PROXY]}
+    status, _, answer = call("POST", "/repositories", group, administrator)
+    assert status == 201, answer
+    folders = {}
+    for sdk in IMAGES:
+        pushed = dotnet(
+            sdk,
+            work[sdk],
+            f'cd /work && dotnet nuget push "out/$1.{VERSION}.nupkg" --source megooarti '
+            '--api-key "$2" --skip-duplicate',
+            package_id(sdk),
+            token,
+        )
+        assert pushed.returncode == 0, said(pushed)
+        folder = tmp_path_factory.mktemp(f"group{sdk}")
+        written = config(GROUP, GROUP)
+        (folder / "nuget.config").write_text(written, encoding="utf-8", newline="\n")
+        folders[sdk] = folder
+    return folders
+
+
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+def test_dotnet_restores_a_pushed_package_and_one_of_nuget_org_through_a_group(grouped, sdk):
+    restored = dotnet(sdk, grouped[sdk], GROUPED, package_id(sdk))
+
+    assert restored.returncode == 0, said(restored)
+    last = restored.stdout.splitlines()[-1]
+    assert last == f'hello from {package_id(sdk)} {{"through":"group"}}'
+
+
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+def test_dotnet_searches_and_finds_newer_versions_through_a_group(grouped, sdk):
+    found = dotnet(
+        sdk,
+        grouped[sdk],
+        f'cd /work && dotnet package search "$1" --source {GROUP} '
+        f"&& dotnet package search Newtonsoft.Json --source {GROUP}",
+        package_id(sdk),
+    )
+    # Read from the registration the group writes from its members'.
+    outdated = dotnet(sdk, grouped[sdk], "cd /work/app && dotnet list package --outdated")
+
+    assert found.returncode == 0, said(found)
+    assert package_id(sdk) in found.stdout
+    assert "Newtonsoft.Json" in found.stdout
+    assert outdated.returncode == 0, said(outdated)
+    (line,) = [line for line in outdated.stdout.splitlines() if "Newtonsoft.Json" in line]
+    assert line.split()[-1] != JSON_NET
+
+
+@pytest.mark.parametrize("sdk", sorted(IMAGES))
+@pytest.mark.parametrize("source", ["through", "grouped"], ids=["proxy", "group"])
+def test_nuget_audit_warns_of_a_vulnerable_package_with_the_data_passed_on(request, source, sdk):
+    restored = dotnet(sdk, request.getfixturevalue(source)[sdk], AUDITED)
+
+    assert restored.returncode == 0, said(restored)
+    warned = [line for line in restored.stdout.splitlines() if "NU1903" in line]
+    assert warned, said(restored)
+    assert "Newtonsoft.Json" in warned[0]
+    assert "NU1905" not in restored.stdout  # the source had the data
```

- [ ] **Step 2: Write the guide**

It gains the group, says what a group's feed is written from, and in place of the advice to name nuget.org as the audit's source, says what passes NuGet Audit's data on. The README says NuGet has all three types.

Change `docs/formats/nuget.md`:

````diff
@@ -67,6 +67,16 @@ dotnet nuget add source https://repo.example.com/repository/nuget-org/index.json
   --store-password-in-clear-text
 ```
 
+A group is one feed of its members': a machine whose one source is the group restores
+the packages you push and nuget.org's alike. Push to a hosted member, not to the group.
+
+```bash
+curl -u admin -H 'Content-Type: application/json' -d '{
+  "name": "nuget-public", "format": "nuget", "type": "group",
+  "group": {"members": ["nuget-hosted", "nuget-org"]}
+}' http://localhost:8000/api/v1/repositories
+```
+
 - **Credentials.** A push's API key is an API token (`--api-key`, sent as
   `X-NuGet-ApiKey`); so is the password of a source's credentials. A user name and a
   password work for a source too. NuGet's clients refuse a plain-HTTP source unless it
@@ -113,16 +123,21 @@ dotnet nuget add source https://repo.example.com/repository/nuget-org/index.json
   `format_config.symbol_url` names a symbol server to proxy, which a later version
   serves. A search that fails is said to have failed, and does not stop the proxy
   fetching packages.
+- **A group's feed is written from its members'** on each request, in the order they
+  are listed: an id's versions are every member's together, and its registration is
+  the group's own, with the first member's details of a version that several members
+  have (inlined up to 128 versions, then in pages of 64). A search, and autocomplete,
+  ask each member and list an id once, as the first member that found it has it. A
+  package, its `.nuspec` and its symbol package come from the first member that has
+  them. A member that is offline, or whose feed cannot be reached, is passed over.
+  Every address in what a group serves is its own.
 - **NuGet Audit** (the warnings `dotnet restore` gives for a package with a known
-  vulnerability) reads its data from nuget.org, which a proxy does not pass on yet. To
-  keep the warnings when the proxy is a machine's only source, name nuget.org as the
-  audit's source in `nuget.config`:
-
-  ```xml
-  <auditSources>
-    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
-  </auditSources>
-  ```
+  vulnerability, such as `NU1903`) reads its data from a source's `index.json`. A proxy
+  passes on its feed's data, nuget.org's for a proxy of nuget.org, kept and checked
+  again after `metadata_max_age_minutes`; a group passes on its first member's that has
+  any. A hosted repository has none: a machine whose only source is a hosted repository
+  warns `NU1905`, unless `nuget.config` names a source of the data in
+  `<auditSources>`.
 
 ## Clients
 
@@ -131,4 +146,7 @@ with `dotnet pack`, pushed with an API key, pushed again with `--skip-duplicate`
 found with `dotnet package search`, restored into a project, and deleted; and, through
 a proxy of nuget.org, a package restored into a project that runs, found with
 `dotnet package search`, and its newer versions listed by `dotnet list package
---outdated`.
+--outdated`; through a group of the two, a project that restores a pushed package and
+one of nuget.org's and runs, both found with `dotnet package search`, and newer versions
+listed; and through the proxy and through the group, NuGet Audit's warning of a package
+with a known vulnerability.
````

Change `README.md`:

```diff
@@ -1,9 +1,9 @@
 # MegooArti
 
 An open-source repository and artifact proxy and manager. It keeps Maven, npm, PyPI,
-Docker, APT, YUM, apk and Raw repositories, each of them hosted, a proxy of a remote
-one, or a group of several behind one address, and hosted NuGet repositories, with a
-web UI and a REST API. See the
+Docker, APT, YUM, apk, NuGet and Raw repositories, each of them hosted, a proxy of a
+remote one, or a group of several behind one address, with a web UI and a REST API.
+See the
 [business requirements](docs/BRD.md) for scope and roadmap, and the
 [changelog](CHANGELOG.md) for what this version has and what is known of it.
 
```

- [ ] **Step 3: Run the tests**

Run (in `backend/`): `uv run pytest tests/test_documents.py -q`
Expected: 140 passed.

Run (in `backend/`): `uv run pytest -m docker tests/test_nuget_client.py -q`
Expected: 20 passed: Task 2's four tests for each SDK, beside plans 13a's and 13b's twelve.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_nuget_client.py docs/formats/nuget.md README.md
git commit -m "test: dotnet 10 and 8 restore, search and audit through a NuGet group; docs: NuGet groups and NuGet Audit"
```

---

### Task 3: The spec, and every suite

**Files:**
- Modify: `docs/superpowers/specs/2026-10-15-nuget-design.md`

- [ ] **Step 1: Write what this plan settled into the spec, and mend section 7.2's caching, section 11's risk and section 12's row**

Change `docs/superpowers/specs/2026-10-15-nuget-design.md`:

```diff
@@ -130,6 +130,18 @@ A package client signs in with an API token: as the `X-NuGet-ApiKey` header (wha
 | X10 | A search's or an autocomplete's failure is recorded and does not count towards leaving the feed alone (`proxy.Source.blocks`). | nuget.org searches on another host: its failing blocked the proxy, and every restore of a package not yet kept failed with it. |
 | X11 | NuGet Audit's vulnerability data (`VulnerabilityInfo/6.7.0`) is not passed on yet; the guide says how to keep it, with nuget.org as an audit source. Plan 13c passes it on, beside groups. | A machine whose one source is the proxy gets no audit warnings without it. |
 
+### Settled while building plan 13c
+
+| # | What | Why |
+| --- | --- | --- |
+| Y1 | A group writes its version lists, registrations, searches and autocompletes on each request from what its members have, and keeps none of them (in place of 7.2's caching). Each member keeps what it keeps: a proxy its feed's documents as metadata, a hosted repository nothing (W1). Measured through a group of a hosted repository and a proxy of nuget.org, over AWSSDK.S3 (1,570 versions): its registration took 8 s the first time, while the proxy fetched the feed's 25 pages, and 0.2 to 0.25 s after; its version list 0.04 s. | What a group keeps would change with every member's push, delete and fetch; written on request, it is right after each of them, and costs little once its members have what they keep. |
+| Y2 | A group asks each member for data, not documents (`nuget/feeds.py`), with the group's own address: a hosted member writes its items with it, a proxy rewrites its feed's with it, and a group in a group is asked the same way. | No address of a member's, or of a feed's registration or packages, reaches a client of the group. The catalog's addresses are left as the feed wrote them (X3). |
+| Y3 | A group's registration has every version any member has, a version several have taken from the first (by its normalized version), inlined up to 128 versions and in pages of 64 at their own addresses beyond (W14); a version's leaf is written from its item. A proxy's registration pages that its feed lists by address are fetched, if they are under the feed's registration, and kept. | 7.2 and W14; a page elsewhere is not the feed's to have the proxy ask for. |
+| Y4 | A search or an autocomplete is merged as 7.2 says, each member asked for its first `skip + take` results at most 1,000 at a time; an autocomplete of an id's versions is every member's together, a prerelease only if asked for, the oldest first. | Members, nuget.org among them, take at most 1,000 results at a time, and a group may be asked for up to the 3,000th. |
+| Y5 | A member that is offline, or answers `404`, `502` or `503`, gives nothing to what the group merges, as the group engine passes over it; any other error is the group's. Members are listed once for each request. | As every format's groups do. |
+| Y6 | NuGet Audit's data (`VulnerabilityInfo/6.7.0`; in place of X11): a proxy offers it where its feed does, keeping the feed's index (inflated, at most 1 MiB) and each file it names (at most 64 MiB) as metadata, served at `v3/vulnerabilities/<name>.json`; a name the feed's index does not list is `404`, and the feed is not asked. A group offers the first member's index that has one, with the group's addresses, and each file from the first member that has it. A hosted repository has none. | A machine whose one source is a proxy or a group gets NuGet Audit's warnings (`NU1901` to `NU1904`) without naming nuget.org; nuget.org's files are gzipped whatever is asked, and its base file is some megabytes. |
+| Y7 | A hosted repository's search over an id of 1,600 versions took 0.1 s, its registration's index 0.05 s and a page 0.1 s (measured in the unit tests' database); nuget.org's search for `awssdk` takes 2.4 to 3.5 s through a proxy or a group, its answer being 3.6 MB. | 11's risk of an id with thousands of versions, measured. |
+
 ## 5. Hosted repositories
 
 - **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
@@ -163,7 +175,7 @@ A group's members are in order. It serves V3 from those that speak V3, and V2 fr
 - **A package, its `.nuspec` or `.snupkg`:** fetched from the first member that has it.
 - **Registration:** written by the group (E5): for an id, every version any member has, a version several members have taken from the first; in pages of 64, with the group's addresses.
 - **Search and autocomplete:** each member is asked for its first `skip + take` results; the answers are merged in member order, the first result for an id kept, and the page asked for is cut from them. `totalHits` is the sum of the members' less the ids dropped, which is what can be known. `skip + take` is at most 3,000 (section 9).
-- **Caching:** a version list and a registration are kept by the members' revisions and the proxies' kept metadata, as the Linux formats' groups are, written behind the requests one at a time (the S10 to S12 of that spec). Search is merged on each request.
+- **Caching:** none of the group's own: a version list, a registration and a search are written on each request from what the members keep (Y1).
 
 ### 7.3 V2
 
@@ -204,7 +216,7 @@ A group's members are in order. It serves V3 from those that speak V3, and V2 fr
 | --- | --- |
 | V2's queries differ from client to client, and from version to version of one client. | The plans record what each client of D7 sends (7.3), and the real-client tests keep them honest; anything else is refused with a message, not answered wrongly. |
 | nuget.org's search and registration are on other hosts than its service index, and change their addresses. | A V3 proxy reads them from the remote's service index (6), as clients do, and never assumes a host. |
-| A popular id has thousands of versions (registration pages, a group's merge). | Pages of 64 beyond 128 versions, each written from its own versions (W14); a version list from the versions alone (W13). A search still reads every version of each id on its page: measured in plan 13c against nuget.org's largest ids. |
+| A popular id has thousands of versions (registration pages, a group's merge). | Pages of 64 beyond 128 versions, each written from its own versions (W14); a version list from the versions alone (W13). A search still reads every version of each id on its page: measured in plan 13c (Y1, Y7). |
 | `nuget.exe` under Mono, and Chocolatey on Linux, are less maintained than their Windows builds. | The tests pin images that work; if one stops being published, the plan says so and the test is replaced by the nearest client that is. |
 | The PowerShell Gallery and the Chocolatey community feed rate-limit, or are slow. | The tests fetch a few small packages, as the Linux formats' tests do of their mirrors. |
 | A portable PDB's checksum is not what the debugger sends. | Plan 13f checks it against `dotnet-symbol` and a PDB built by `dotnet pack`. |
@@ -215,7 +227,7 @@ A group's members are in order. It serves V3 from those that speak V3, and V2 fr
 | --- | --- |
 | 13a | The `nuget` format: reading packages, hosted repositories over V3 (service index, package contents, registration, search, push, delete), `X-NuGet-ApiKey`, the deployment policy's default, its `dotnet` tests and `docs/formats/nuget.md`. |
 | 13b | V3 proxies (6). |
-| 13c | V3 groups (7.2), search merged. |
+| 13c | V3 groups (7.2), search merged, and NuGet Audit's data passed on (Y6). |
 | 13d | V2: served by hosted repositories, and V2 proxies (`protocol`); the `nuget.exe`, Chocolatey and PowerShell tests. |
 | 13e | V2 in groups (7.3). |
 | 13f | The symbol server (8), `symbol_url`, and `dotnet-symbol` in the tests. |
```

- [ ] **Step 2: Run every suite**

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: All checks passed; 3781 passed, 2 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: each passes; this plan changes nothing there.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: every container test passes, Task 2's eight among them.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs
git commit -m "docs: what plan 13c settled"
```
