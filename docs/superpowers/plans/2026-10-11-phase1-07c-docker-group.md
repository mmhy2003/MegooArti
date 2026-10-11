# Docker Group Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docker pull repo.example.com/<group>/<image>` serves a team's own images and a cache of public registries from one address, and an image on a public registry can never stand in for one the team pushed, or add a tag to it.

**Architecture:** A group stores nothing. For each request it looks at every hosted and proxy repository behind it, nested groups looked through, and decides who answers for the image: the hosted repositories if one of them has it, and only otherwise the proxies. A manifest or a blob then comes from the first of those that has it, through the same dispatcher that serves the member directly; a tag list is the union of theirs; the catalog is the union of what they hold. Everything is in the Docker format, on the group engine's `leaves` and `proxies` and on the hosted and proxy code of plans 7a and 7b.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, pytest + pytest-asyncio, Docker (the daemon and client of the machine, and Docker Hub, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-11-docker-format-design.md](../specs/2026-10-11-docker-format-design.md), section 9, D12 and the plan 7c part of 12. Business requirements: [docs/BRD.md](../../BRD.md) FMT-4 (group), REP-12, NFR-1. Task 2 amends the spec where this plan settles something the spec left open.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | A hosted repository has an image if it has a tag of it. Then hosted repositories alone answer for the image, whatever the order of the members. | D12 and section 9 of the spec. A tag is a component, so this is one indexed lookup for each hosted repository behind the group. |
| P2 | A hosted repository also answers for what it holds under the digest that is asked for, a manifest of that image or a blob, even without a tag of the image. | An image that lost its last tag must still be pulled by its digest through the group, as it is directly (D8). Content named by its digest cannot be another image standing in. It is a lookup by exact path; "has any manifest of the image" would be a scan. |
| P3 | If the only hosted repositories that have the image are offline, or are reached only through an offline group, the answer is `503`. | D12: an offline hosted member still counts. While it is away, a public image must not answer in its place. |
| P4 | If nobody that answers has what is asked for, and one of them answered `502` or `503`, the group answers that; otherwise `404`. | An outage of the only proxy must not be reported as an image that does not exist. The earlier formats answer `404` here. |
| P5 | The catalog lists, for a group, every image with a tag in the online repositories behind it, each once, as `<group>/<image>`. | Section 9. What an offline repository holds cannot be pulled. |
| P6 | A tag list is the union of the hosted repositories' tags if they answer, or of the proxies' lists as their remotes give them. A proxy that cannot give its list is passed over if another can. | Section 9 and REP-12. |
| P7 | The real-client test lists the proxy before the hosted repository in the group, and pushes an image named `busybox`. | The order must not decide whose image a name is, and the name must be one Docker Hub really has. |

**Changed after the whole-branch review.** The task bodies below show the code as first written. The branch differs from them as follows.

| # | Decision | Reason |
| --- | --- | --- |
| P8 | P1 and P2 are replaced. A hosted repository has an image while it holds a manifest of it, tagged or not. A manifest is a component in the namespace `manifests`, with its digest as the version, and `_answering` asks `group.owners` for that namespace. Holding a blob decides nothing. | The review showed two things. With "has a tag", deleting the last tag of an image, or pushing it by digest only, left its name to the proxies: the public image was served under the very tag that had been withdrawn. And with "holds the blob asked for", an offline hosted repository that held a base layer made that layer `503` for the public image it came from. |
| P9 | A hosted repository that has an image and no tag of it adds nothing to the group's tag list; if nobody adds anything, the list is `404 NAME_UNKNOWN`, as on the hosted repository itself. | Follows from P8. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: no ORM relationships; formats do not commit, the route does, and the proxy engine commits what it must; errors under `/v2/` have the registry's shape; only `docker/format.py` touches the repository context; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration, no setting and no dependency, and changes nothing outside the Docker format.**
- **D12 applies to every answer a group gives about an image:** its tags, its manifests, its blobs and its tag list. A remote is not even asked about an image a hosted repository has.
- **Reading through a group needs `read` on the group only.**
- **Everything that changes a repository answers `405` on a group.**
- **A group stores nothing.**
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in Task 1.

1. **A public image with the name of one that was pushed,** by every way in: its tag, another tag only the remote has, its manifest by digest, its blob, its tag list, with the proxy listed first. None may reach the remote's image, and the remote may not be asked.
2. **The hosted repository away:** offline, or behind a nested group that is offline; two hosted repositories that have the image, one of them offline.
3. **An image without a tag:** pushed, its tag deleted, pulled by its digest through the group with its layers.
4. **A proxy that cannot answer:** its remote down with nothing kept, with something kept; two proxies, one of which has the image.
5. **Shapes of groups:** a group in a group, a repository reached twice, a group with no members; a push to a group; a reader with `read` on the group and on nothing behind it.

---

### Task 1: Docker group repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/docker/format.py`
- Modify: `backend/tests/repositories/docker/conftest.py`
- Modify: `backend/tests/repositories/docker/test_registry.py`
- Test: `backend/tests/repositories/docker/test_group.py`

**Interfaces:**
- Consumes: `group.leaves`, `group.proxies`, `group.TRY_NEXT`, `group.Leaf`; `Serve`; `context.names`, `context.stat`, `context.versions`; `_tag_page`, `_refresh_list`, `_is_stale`, `_not_allowed`, `unknown`, `images` from plans 7a and 7b; `FakeRegistry` from plan 7b.
- Produces:
  - `DockerFormat.handle_group`; `DockerFormat.types` is no longer overridden, so the format offers all three types.
  - `await _answering(context, image, wanted: str | None = None) -> list[RepositoryContext]`: who answers for an image. Raises `503`.
  - `await _remote_tags(context, image) -> list[str]`: a proxy's list of an image's tags, renewed if it is old.
  - `await images(context)` answers for a group with what the online repositories behind it hold.
  - In the tests' `conftest.py`, `create(db, name, *, hosted=None, proxy=None, group: list[str] | None = None)`.

- [ ] **Step 1: Write the failing tests**

The helper that creates a repository learns to make a group, and the test that said a Docker repository is hosted or a proxy now says it can be any of the three.

`backend/tests/repositories/docker/test_group.py`:

```python
"""A Docker group: hosted and proxy repositories behind one address."""

import pytest
from sqlalchemy import select

from megooarti.repositories import service
from megooarti.repositories.docker.manifests import OCI_INDEX
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic
from tests.repositories.docker.conftest import (
    config_for,
    create,
    digest_of,
    error_code,
    image_manifest,
    index_manifest,
    layer,
    push_image,
)
from tests.repositories.fake_registry import REGISTRY, FakeRegistry

ALL = "/v2/all"
PUBLIC_LAYER = b"\x1f\x8b a layer of the public image"


@pytest.fixture
def registry(app) -> FakeRegistry:
    fake = FakeRegistry()
    app.state.http = fake.client()
    return fake


@pytest.fixture
async def everything(db, registry):
    """A hosted repository and a proxy behind a group, with the proxy listed first."""
    await create(db, "ours")
    await create(db, "hub", proxy={"remote_url": REGISTRY})
    return await create(db, "all", group=["hub", "ours"])


async def take_offline(db, name: str) -> None:
    repository = await service.get_repository(db, name)
    repository.online = False
    await db.commit()


def ours(*texts: str) -> bytes:
    """The manifest `push_image` makes of these layers."""
    return image_manifest(config_for(*texts), *(layer(text) for text in texts))


async def test_an_image_only_the_remote_has_is_pulled_through_the_group(
    client, everything, root, registry, db
):
    manifest = registry.add_image("library/tool", "1.0", PUBLIC_LAYER)

    by_tag = await client.get(f"{ALL}/library/tool/manifests/1.0", headers=root)
    asked = await client.head(f"{ALL}/library/tool/manifests/1.0", headers=root)
    by_digest = await client.get(
        f"{ALL}/library/tool/manifests/{digest_of(manifest)}", headers=root
    )
    blob = await client.get(f"{ALL}/library/tool/blobs/{digest_of(PUBLIC_LAYER)}", headers=root)

    assert by_tag.content == by_digest.content == manifest
    assert asked.headers["Docker-Content-Digest"] == digest_of(manifest)
    assert blob.content == PUBLIC_LAYER
    # It is kept by the proxy, not by the group: a group stores nothing.
    assert f"blobs/{digest_of(PUBLIC_LAYER)}" in set(await db.scalars(select(Asset.path)))


async def test_an_image_that_was_pushed_is_pulled_through_the_group(
    client, everything, root, registry
):
    manifest = await push_image(client, root, "team/app", "1.0", "one", repository="ours")

    by_tag = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    blob = await client.get(f"{ALL}/team/app/blobs/{digest_of(layer('one'))}", headers=root)
    asked = await client.head(f"{ALL}/team/app/blobs/{digest_of(layer('one'))}", headers=root)

    assert by_tag.content == manifest
    assert blob.content == layer("one")
    assert asked.headers["Content-Length"] == str(len(layer("one")))
    assert registry.requests == []  # the remote was not asked about our image


async def test_a_public_image_cannot_stand_in_for_one_that_was_pushed(
    client, everything, root, registry
):
    pushed = await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    theirs = registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    registry.add_image("team/app", "2.0", PUBLIC_LAYER)

    same_tag = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    their_tag = await client.get(f"{ALL}/team/app/manifests/2.0", headers=root)
    their_manifest = await client.get(f"{ALL}/team/app/manifests/{digest_of(theirs)}", headers=root)
    their_blob = await client.get(f"{ALL}/team/app/blobs/{digest_of(PUBLIC_LAYER)}", headers=root)
    tags = await client.get(f"{ALL}/team/app/tags/list", headers=root)

    assert same_tag.content == pushed  # though the proxy is listed first
    assert (their_tag.status_code, error_code(their_tag)) == (404, "MANIFEST_UNKNOWN")
    assert (their_manifest.status_code, error_code(their_manifest)) == (404, "MANIFEST_UNKNOWN")
    assert (their_blob.status_code, error_code(their_blob)) == (404, "BLOB_UNKNOWN")
    assert tags.json() == {"name": "all/team/app", "tags": ["1.0"]}  # no tag is added to it
    assert registry.requests == []  # the remote is not even asked


async def test_while_the_repository_that_has_an_image_is_offline_nothing_answers_for_it(
    client, everything, root, registry, db
):
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    registry.add_image("library/tool", "1.0", PUBLIC_LAYER)
    await take_offline(db, "ours")

    attempts = [
        await client.get(f"{ALL}/team/app/manifests/1.0", headers=root),
        await client.get(f"{ALL}/team/app/manifests/{digest_of(ours('ours'))}", headers=root),
        await client.get(f"{ALL}/team/app/blobs/{digest_of(layer('ours'))}", headers=root),
        await client.get(f"{ALL}/team/app/tags/list", headers=root),
    ]
    other = await client.get(f"{ALL}/library/tool/manifests/1.0", headers=root)

    for response in attempts:
        assert response.status_code == 503, response.text
    assert other.status_code == 200  # what it does not have is still served
    assert all("team/app" not in seen["path"] for seen in registry.requests)


async def test_an_image_two_hosted_repositories_have_is_served_by_the_one_that_is_online(
    client, db, root, registry
):
    await create(db, "first")
    await create(db, "second")
    await create(db, "all", group=["first", "second"])
    await push_image(client, root, "team/app", "1.0", "from first", repository="first")
    second = await push_image(client, root, "team/app", "1.0", "from second", repository="second")
    await push_image(client, root, "team/app", "2.0", "newer", repository="second")
    tags = await client.get(f"{ALL}/team/app/tags/list", headers=root)
    await take_offline(db, "first")

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert tags.json()["tags"] == ["1.0", "2.0"]  # of both, each once
    assert response.content == second


async def test_an_image_that_lost_its_tag_is_still_pulled_by_its_digest(
    client, everything, root, registry
):
    manifest = await push_image(client, root, "team/old", "1.0", "kept", repository="ours")
    deleted = await client.delete("/v2/ours/team/old/manifests/1.0", headers=root)

    pinned = await client.get(f"{ALL}/team/old/manifests/{digest_of(manifest)}", headers=root)
    blob = await client.get(f"{ALL}/team/old/blobs/{digest_of(layer('kept'))}", headers=root)

    assert deleted.status_code == 202
    assert (pinned.content, blob.content) == (manifest, layer("kept"))
    assert registry.requests == []


async def test_an_image_for_several_platforms_is_pulled_through_the_group(
    client, everything, root, registry
):
    platforms = [registry.add_image("library/multi", f"p{n}", bytes([n]) * 50) for n in range(2)]
    index = index_manifest(*platforms)
    registry.add_manifest("library/multi", "1.0", index, OCI_INDEX)

    pulled = await client.get(f"{ALL}/library/multi/manifests/1.0", headers=root)
    one = await client.get(f"{ALL}/library/multi/manifests/{digest_of(platforms[1])}", headers=root)

    assert (pulled.content, pulled.headers["Content-Type"]) == (index, OCI_INDEX)
    assert one.content == platforms[1]


async def test_the_tags_of_a_public_image_are_those_of_every_proxy(client, db, root, registry):
    await create(db, "one", proxy={"remote_url": REGISTRY})
    await create(db, "two", proxy={"remote_url": "https://other.registry.test"})
    await create(db, "all", group=["one", "two"])
    for tag in ("1.0", "1.1", "2.0"):
        registry.add_image("library/tool", tag, PUBLIC_LAYER)

    listed = await client.get(f"{ALL}/library/tool/tags/list", headers=root)
    page = await client.get(f"{ALL}/library/tool/tags/list?n=2", headers=root)
    nothing = await client.get(f"{ALL}/library/none/tags/list", headers=root)

    assert listed.json() == {"name": "all/library/tool", "tags": ["1.0", "1.1", "2.0"]}
    assert page.json()["tags"] == ["1.0", "1.1"]
    assert page.headers["Link"] == f'<{ALL}/library/tool/tags/list?n=2&last=1.1>; rel="next"'
    assert (nothing.status_code, error_code(nothing)) == (404, "NAME_UNKNOWN")


async def test_the_catalog_lists_what_the_repositories_behind_a_group_hold(
    client, everything, root, registry, make_user, db
):
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("library/tool", "1.0", PUBLIC_LAYER)
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    await client.get("/v2/hub/library/tool/manifests/1.0", headers=root)
    await client.get("/v2/hub/team/app/manifests/1.0", headers=root)  # directly, not by the group
    await roles.create_role(db, "pullers", "", ["repository:docker:all:read"], [])
    await db.commit()
    await make_user("puller", roles=["pullers"])

    catalog = await client.get("/v2/_catalog", headers=basic("puller", PASSWORD))

    assert catalog.json() == {"repositories": ["all/library/tool", "all/team/app"]}


async def test_reading_through_a_group_needs_read_on_the_group_only(
    client, everything, root, registry, make_user, db
):
    manifest = await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    await roles.create_role(db, "pullers", "", ["repository:docker:all:read"], [])
    await roles.create_role(db, "others", "", ["repository:docker:ours:read"], [])
    await db.commit()
    await make_user("puller", roles=["pullers"])
    await make_user("other", roles=["others"])

    allowed = await client.get(f"{ALL}/team/app/manifests/1.0", headers=basic("puller", PASSWORD))
    directly = await client.get(
        "/v2/ours/team/app/manifests/1.0", headers=basic("puller", PASSWORD)
    )
    denied = await client.get(f"{ALL}/team/app/manifests/1.0", headers=basic("other", PASSWORD))

    assert allowed.content == manifest
    assert (directly.status_code, error_code(directly)) == (403, "DENIED")
    assert (denied.status_code, error_code(denied)) == (403, "DENIED")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "team/app/blobs/uploads/"),
        ("PUT", "team/app/manifests/1.0"),
        ("DELETE", "team/app/manifests/1.0"),
        ("PATCH", "team/app/blobs/uploads/" + "0" * 32),
    ],
)
async def test_nothing_is_pushed_to_a_group_or_deleted_from_it(
    client, everything, root, registry, method, path
):
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")

    response = await client.request(method, f"{ALL}/{path}", content=b"{}", headers=root)
    still = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert (response.status_code, error_code(response)) == (405, "UNSUPPORTED")
    assert response.headers["Allow"] == "GET, HEAD"
    assert still.status_code == 200


async def test_a_remote_that_is_down_is_an_outage_not_a_missing_image(client, db, root, registry):
    await create(db, "one", proxy={"remote_url": REGISTRY})
    await create(db, "all", group=["one"])
    manifest = registry.add_image("library/tool", "1.0", PUBLIC_LAYER)
    await client.get(f"{ALL}/library/tool/manifests/1.0", headers=root)
    registry.down = True

    kept = await client.get(f"{ALL}/library/tool/manifests/{digest_of(manifest)}", headers=root)
    never = await client.get(f"{ALL}/library/other/manifests/1.0", headers=root)
    blob = await client.get(f"{ALL}/library/tool/blobs/{digest_of(PUBLIC_LAYER)}", headers=root)
    tags = await client.get(f"{ALL}/library/other/tags/list", headers=root)

    assert kept.content == manifest
    for response in (never, blob, tags):
        assert (response.status_code, error_code(response)) == (502, "UNKNOWN")


async def test_what_no_repository_has_is_unknown(client, everything, root, registry):
    absent = "sha256:" + "0" * 64

    tag = await client.get(f"{ALL}/library/none/manifests/1.0", headers=root)
    blob = await client.get(f"{ALL}/library/none/blobs/{absent}", headers=root)
    referrers = await client.get(f"{ALL}/library/none/referrers/{absent}", headers=root)
    nonsense = await client.get(f"{ALL}/library/none/something", headers=root)

    assert (tag.status_code, error_code(tag)) == (404, "MANIFEST_UNKNOWN")
    assert (blob.status_code, error_code(blob)) == (404, "BLOB_UNKNOWN")
    assert referrers.status_code == nonsense.status_code == 404


async def test_groups_within_groups_are_looked_through(client, db, root, registry):
    await create(db, "ours")
    await create(db, "hub", proxy={"remote_url": REGISTRY})
    await create(db, "inner", group=["ours"])
    await create(db, "all", group=["hub", "inner", "ours"])
    pushed = await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    await take_offline(db, "inner")
    still = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert response.content == still.content == pushed  # it is also reached directly
    assert registry.requests == []


async def test_a_hosted_repository_behind_an_offline_group_still_keeps_its_names(
    client, db, root, registry
):
    await create(db, "ours")
    await create(db, "hub", proxy={"remote_url": REGISTRY})
    await create(db, "inner", group=["ours"])
    await create(db, "all", group=["hub", "inner"])
    await push_image(client, root, "team/app", "1.0", "ours", repository="ours")
    registry.add_image("team/app", "1.0", PUBLIC_LAYER)
    await take_offline(db, "inner")

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)

    assert response.status_code == 503
    assert registry.requests == []


async def test_a_group_with_nothing_behind_it_has_nothing(client, db, root, registry):
    await create(db, "all", group=[])

    response = await client.get(f"{ALL}/team/app/manifests/1.0", headers=root)
    catalog = await client.get("/v2/_catalog", headers=root)

    assert (response.status_code, error_code(response)) == (404, "MANIFEST_UNKNOWN")
    assert catalog.json() == {"repositories": []}
```

In `backend/tests/repositories/docker/conftest.py`:

Replace

```python
async def create(
    db, name: str, *, hosted: dict | None = None, proxy: dict | None = None
) -> Repository:
    """A Docker repository, committed: hosted, or a proxy if its settings are given."""
    repository = await service.create_repository(
        db,
        name=name,
        format="docker",
        type="hosted" if proxy is None else "proxy",
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        format_config={},
    )
```

with

```python
async def create(
    db,
    name: str,
    *,
    hosted: dict | None = None,
    proxy: dict | None = None,
    group: list[str] | None = None,
) -> Repository:
    """A Docker repository, committed: hosted, or a proxy or a group if that is given."""
    kind = "proxy" if proxy is not None else "hosted" if group is None else "group"
    repository = await service.create_repository(
        db,
        name=name,
        format="docker",
        type=kind,
        online=True,
        blob_store="default",
        hosted=hosted,
        proxy=proxy,
        group=None if group is None else {"members": group},
        format_config={},
    )
```

In `backend/tests/repositories/docker/test_registry.py`:

Replace

```python
async def test_a_repository_is_hosted_or_a_proxy_for_now(admin_client):
    proxy = {"proxy": {"remote_url": "https://registry-1.docker.io"}}
    group = {"group": {"members": []}}
    for kind, extra, status in (("proxy", proxy, 201), ("group", group, 422)):
        body = {"name": f"docker-{kind}", "format": "docker", "type": kind, **extra}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == status, kind
```

with

```python
async def test_a_repository_is_hosted_a_proxy_or_a_group(admin_client):
    proxy = {"proxy": {"remote_url": "https://registry-1.docker.io"}}
    group = {"group": {"members": ["docker-hosted", "docker-proxy"]}}
    for kind, extra in (("hosted", {}), ("proxy", proxy), ("group", group)):
        body = {"name": f"docker-{kind}", "format": "docker", "type": kind, **extra}
        response = await admin_client.post("/api/v1/repositories", json=body)
        assert response.status_code == 201, kind
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/docker/test_group.py tests/repositories/docker/test_registry.py -q`
Expected: 7 failed, 13 errors, with 36 passed: every test in `test_group.py` and the changed test in `test_registry.py`, because `group repositories are not available for this format`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/docker/format.py`:

Replace

```python
says which manifest the tag names, and that is fetched only if it is another one.
"""
```

with

```python
says which manifest the tag names, and that is fetched only if it is another one.

A group answers for an image from the hosted repositories behind it if one of them has
the image, and only otherwise from its proxies: an image on a public registry must not
stand in for one that was pushed here, nor add tags to it.
"""
```

Replace

```python
from megooarti.repositories import proxy, uploads
```

with

```python
from megooarti.repositories import group, proxy, uploads
```

Replace

```python
from megooarti.repositories.formats import ComponentKey, Format, register
```

with

```python
from megooarti.repositories.formats import ComponentKey, Format, Serve, register
```

Replace

```python
async def images(context: RepositoryContext) -> list[str]:
    """The images of a repository that have a tag, in order."""
    found, _ = await context.package_names("", limit=_CATALOG_MOST, offset=0)
    return [name for _, name in found]
```

with

```python
async def images(context: RepositoryContext) -> list[str]:
    """The images of a repository that have a tag, in order.

    A group has those of the repositories behind it that are online, each once.
    """
    if context.repository.type == "group":
        behind: set[str] = set()
        for leaf in await group.leaves(context):
            if leaf.online:
                behind.update(await images(leaf.context))
        return sorted(behind)[:_CATALOG_MOST]
    found, _ = await context.package_names("", limit=_CATALOG_MOST, offset=0)
    return [name for _, name in found]
```

Replace

```python
async def _proxied_tags(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    path = names.list_path(parsed.image)
    asset = await context.get(path)
    if _is_stale(context, asset, path):
        await _refresh_list(context, parsed.image, held=asset is not None)
    raw = await context.read(path, limit=_LIST_BYTES_MOST)
    held = json.loads(raw)["tags"] if raw is not None else []
    return _tag_page(context, request, parsed.image, held)
```

with

```python
async def _remote_tags(context: RepositoryContext, image: str) -> list[str]:
    """The tags of an image as a proxy's remote lists them, renewed if the list is old."""
    path = names.list_path(image)
    asset = await context.get(path)
    if _is_stale(context, asset, path):
        await _refresh_list(context, image, held=asset is not None)
    raw = await context.read(path, limit=_LIST_BYTES_MOST)
    return json.loads(raw)["tags"] if raw is not None else []


async def _proxied_tags(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    held = await _remote_tags(context, parsed.image)
    return _tag_page(context, request, parsed.image, held)


# --- A group: the repositories behind it, as one --------------------------------------


async def _answering(
    context: RepositoryContext, image: str, wanted: str | None = None
) -> list[RepositoryContext]:
    """The repositories behind a group that answer for an image, in the order to try them.

    If a hosted repository has the image, hosted ones alone answer for it, whatever a
    proxy's remote has under the same name. A hosted repository has an image if it has
    a tag of it. It also answers if it holds `wanted`, the stored path of what is asked
    for by its digest: an image that lost its last tag is still pulled by its digest,
    and content named by its digest cannot be anything else.

    If the only hosted repositories that have the image are offline, the answer is
    `503`: while they are away, nothing else may answer in their place.
    """
    leaves = await group.leaves(context)
    holders, away = [], False
    for leaf in leaves:
        member = leaf.context
        if member.repository.type != "hosted":
            continue
        has = bool(await member.names("", [image]))
        if not has and wanted is not None:
            has = await member.stat(wanted) is not None
        if has and leaf.online:
            holders.append(member)
        elif has:
            away = True
    if holders:
        return holders
    if away:
        message = "The repository that holds this image is offline."
        raise ApiError(503, "repository_offline", message)
    return group.proxies(leaves)


async def _grouped(
    context: RepositoryContext,
    request: Request,
    parsed: names.DockerPath,
    path: str,
    serve: Serve,
) -> Response:
    """A manifest or a blob, from the first repository that has it among those that answer."""
    wanted = None
    if parsed.kind == "blob":
        wanted = names.blob_path(parsed.reference)
    elif names.is_digest(parsed.reference):
        wanted = names.manifest_path(parsed.image, parsed.reference)
    unavailable = None
    for member in await _answering(context, parsed.image, wanted):
        try:
            return await serve(member, request, path)
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            if error.status_code != 404 and unavailable is None:
                unavailable = error
    if unavailable is not None:
        # Nobody had it, and somebody could not say. That is not "there is no such thing".
        raise unavailable
    if parsed.kind == "blob":
        raise unknown("BLOB_UNKNOWN", "No such blob.")
    raise unknown("MANIFEST_UNKNOWN", "No such manifest.")


async def _grouped_tags(
    context: RepositoryContext, request: Request, parsed: names.DockerPath
) -> Response:
    """The tags of an image in every repository that answers for it, each once."""
    image = parsed.image
    tags: set[str] = set()
    known, unavailable = False, None
    for member in await _answering(context, image):
        try:
            if member.repository.type == "hosted":
                tags.update(await member.versions("", image))
            else:
                tags.update(await _remote_tags(member, image))
        except ApiError as error:
            if error.status_code not in group.TRY_NEXT:
                raise
            if error.status_code != 404 and unavailable is None:
                unavailable = error
            continue
        known = True
    if not known:
        raise unavailable or unknown("NAME_UNKNOWN", "No such image.")
    return _tag_page(context, request, image, sorted(tags))
```

Replace

```python
    # A group needs the registry's own handling, which is not written yet.
    types = frozenset({"hosted", "proxy"})
    remote_signs_in = True
```

with

```python
    remote_signs_in = True
```

After

```python
        if parsed.kind == "tags":
            return await _proxied_tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")
```

add

```python
    async def handle_group(
        self, context: RepositoryContext, request: Request, path: str, serve: Serve
    ) -> Response:
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        parsed = names.classify(path)
        if parsed.kind in ("blob", "manifest"):
            return await _grouped(context, request, parsed, path, serve)
        if parsed.kind == "tags":
            return await _grouped_tags(context, request, parsed)
        if parsed.kind == "referrers":
            raise RegistryError(404, "UNSUPPORTED", "The referrers API is not available.")
        raise RegistryError(404, "NAME_UNKNOWN", "Nothing is served at this address.")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/docker -q`
Expected: 293 passed.

- [ ] **Step 5: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2309 passed, 1 skipped; no findings.

- [ ] **Step 6: Commit**

```bash
git add backend/src/megooarti/repositories/docker/format.py backend/tests/repositories/docker
git commit -m "feat(docker): group repositories in which a public image cannot take the name of one that was pushed"
```

---

### Task 2: Real clients and documentation

**Files:**
- Modify: `backend/tests/test_docker_client.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-10-11-docker-format-design.md`

**Interfaces:**
- Consumes: Docker hosted, proxy and group repositories; the helpers and fixtures of `tests/test_docker_client.py` (`docker`, `registry`, `build`, `file_in`, `said`, `call`, `signed_in`, `administrator`, `REGISTRY`).
- Produces: a Docker-marked test in which the Docker client pulls its own and a public image through a group.

This test runs only with `pytest -m docker`. It needs internet access: the backend container fetches from Docker Hub.

- [ ] **Step 1: Write the real-client test**

In `backend/tests/test_docker_client.py`:

Before

```python
def layer_holding(text: str) -> tuple[bytes, str]:
```

add

```python
def test_a_group_serves_what_was_pushed_and_what_is_public_and_what_was_pushed_wins(
    signed_in, administrator, tmp_path
):
    config = signed_in
    hub = {"remote_url": "https://registry-1.docker.io"}
    repositories = [
        {"name": "team-images", "format": "docker", "type": "hosted"},
        {"name": "hub-mirror", "format": "docker", "type": "proxy", "proxy": hub},
        # The proxy first: the order must not decide whose image a name is.
        {
            "name": "everything",
            "format": "docker",
            "type": "group",
            "group": {"members": ["hub-mirror", "team-images"]},
        },
    ]
    for body in repositories:
        status, _, answer = call("POST", "/repositories", body, administrator)
        assert status == 201, answer
    group = f"{REGISTRY}/everything"

    # A public image comes through the group from Docker Hub.
    pulled = docker(config, "pull", f"{group}/hello-world:latest")
    assert pulled.returncode == 0, said(pulled)
    ran = docker(config, "run", "--rm", f"{group}/hello-world:latest")
    assert ran.returncode == 0 and "Hello from Docker!" in ran.stdout, said(ran)

    # Our own image, under a name Docker Hub has too, is the one the group serves.
    mine = f"{REGISTRY}/team-images/busybox:latest"
    build(config, tmp_path / "ours", mine, "this is ours, not the public busybox")
    pushed = docker(config, "push", mine)
    assert pushed.returncode == 0, said(pushed)
    assert docker(config, "rmi", mine).returncode == 0
    through = docker(config, "pull", f"{group}/busybox:latest")
    assert through.returncode == 0, said(through)
    text = file_in(config, f"{group}/busybox:latest", tmp_path / "out")
    assert text == "this is ours, not the public busybox"

    # Nothing of the public image of that name is offered: not its tags, not a pull.
    status, _, tags = registry("GET", "everything/busybox/tags/list")
    assert (status, json.loads(tags)["tags"]) == (200, ["latest"])
    theirs = docker(config, "pull", f"{group}/busybox:stable")
    assert theirs.returncode != 0, "pulled a public tag of a name that is ours"
    status, _, catalog = registry("GET", "_catalog")
    assert {"everything/busybox", "everything/hello-world"} <= set(
        json.loads(catalog)["repositories"]
    )

    # Nothing is pushed to a group.
    assert docker(config, "tag", f"{group}/busybox:latest", f"{group}/mine:1.0").returncode == 0
    refused = docker(config, "push", f"{group}/mine:1.0")
    assert refused.returncode != 0, "pushed to a group"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_docker_client.py -q`
Expected: 5 passed. This builds the image from the working tree, so it is the first run of a real client against this plan's code. If a client fails, the assertion message carries the end of its output.

- [ ] **Step 3: Document Docker groups**

In `README.md`:

Replace

```markdown
  another repository (it is uploaded instead), and deleting a single layer. Group
  Docker repositories are not available yet.
```

with

```markdown
  another repository (it is uploaded instead), and deleting a single layer.
```

After

```markdown
- Nothing can be pushed to a proxy or deleted from it through the registry API (`405`).
```

add

````markdown
A group puts your own images and the public ones behind one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-all", "format": "docker", "type": "group",
  "group": {"members": ["docker-hosted", "docker-hub"]}
}' http://localhost:8000/api/v1/repositories

docker pull repo.example.com/docker-all/team/my-app:1.0
docker pull repo.example.com/docker-all/alpine:3
```

- **A group protects the images you push.** If a hosted repository behind the group
  has a tag of an image, only hosted repositories answer for that image: its tags,
  its manifests and its layers. An image on a public registry with the same name
  cannot stand in for yours or add a tag to it (the dependency-confusion attack),
  whatever the order of the members. While that hosted repository is offline the
  group answers `503` for the image.
- **An image that lost its last tag** is still pulled through the group by its digest,
  from the hosted repository that holds it.
- **Everything else** comes from the proxies behind the group, the first that has it.
  If none has it and one of them could not ask its remote, the answer is `502`, not
  `404`.
- **Tags** (`tags/list`) are those of every repository that answers for the image,
  each once. The catalog lists every image the repositories behind the group hold as
  `<group>/<image>`.
- Push to the hosted repository, not to the group: a group takes no pushes (`405`).
  Groups can contain groups.

Reading through a group needs `read` on the group only, for example
`repository:docker:docker-all:read`.
````

- [ ] **Step 4: Bring the spec in line with what was built**

In `docs/superpowers/specs/2026-10-11-docker-format-design.md`:

After

```markdown
**Who answers for an image** follows D12, by the rule in the group engine: the repositories behind the group in the order they are tried, nested groups replaced by their members. If a hosted repository has a tag of the image, hosted repositories alone answer for it; if every one that has it is offline, the answer is `503`. Otherwise the online proxies answer.
```

add

```markdown
A hosted repository also answers for what it holds under the digest that is asked for, a manifest of that image or a blob, even if it has no tag of the image: an image that lost its last tag is still pulled by its digest, and content named by its digest cannot be another image standing in.

If nobody that answers has what is asked for and one of them could not ask its remote, the answer is that repository's `502`, not `404`: an outage must not look like an image that does not exist.
```

Replace

```markdown
| Catalog | Every image the repositories behind the group hold, each once |
```

with

```markdown
| Catalog | Every image the online repositories behind the group hold, each once, as `<group>/<image>` |
```

Replace

```markdown
  - *Plan 7c:* images are pulled through a group, and an image pushed under a name the public registry also has is the one served.
```

with

```markdown
  - *Plan 7c:* a public image is pulled through a group and run; an image pushed under a name the public registry also has is the one the group serves, with the proxy listed first; the public image's tags are not offered under that name; a push to the group is refused.
```

- [ ] **Step 5: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: 2309 passed, 1 skipped; no findings.

Run: `uv run pytest -m docker -q`
Expected: 21 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_docker_client.py README.md docs/superpowers/specs/2026-10-11-docker-format-design.md
git commit -m "test(docker): pull through a group with Docker; document Docker groups"
```
