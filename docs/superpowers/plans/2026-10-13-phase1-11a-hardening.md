# Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close what the reviews of plans 8 to 10 set aside as the server's own behaviour: a released Maven version that could be overwritten by default, one's own password set without the present one, names that are folders to a browser, a base URL that carries credentials, a sign-in made from another site, a documentation page that runs a third party's script, a blob store every repository falls back on that could be deleted, and a test failure nobody has seen the text of.

**Architecture:** Seven small changes to the API, each a rule in the place that already owns its subject (the format interface says what policy a repository starts with; the name of a new thing is one type; the guard every other request has is put before sign-in), and the UI's side of the three it offers. The documentation page gets a router of its own that serves Swagger UI's files from the package. Nothing is migrated: what exists keeps what it has.

**Tech Stack:** FastAPI, pydantic 2, SQLAlchemy 2, pytest; Next.js 16.4, React 19.3, TypeScript 5.9, Vitest 5, Playwright. No new dependency. Swagger UI 5.33.2 (Apache-2.0) is kept in the repository as files.

**Spec:** [docs/superpowers/specs/2026-10-13-release-readiness-design.md](../specs/2026-10-13-release-readiness-design.md), section 4 (H1 to H8, the table of API changes in 4.1 and the tests in 4.2), with D3 of section 3. Task 6 amends it where this plan settles something it left open (H9 to H16). The rules the UI keeps are those of [the frontend design](../specs/2026-10-12-frontend-design.md), sections 3 to 12.

**Read first:** `backend/src/megooarti/repositories/service.py` and `formats.py` (how a repository's settings are checked and what a format decides), `backend/src/megooarti/security/authentication.py` (`_refuse_cross_site`, and the dependencies every route gets), `backend/tests/test_route_guards.py` (why a mounted folder is not used), `frontend/src/lib/repository-form.ts`.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| H9 | The policy of a repository that is given none is its format's to say: `Format.default_deployment_policy(config)`, asked by `service._settings`. | Every way a repository is made gets it, not only the API. |
| H10 | The form sends the policy it shows (`policyOf(draft)` in `lib/repository-form.ts`), and the same table of cases is tested on each side. | A person should not send "whatever the server chooses" while looking at a choice. |
| H11 | One's own password is refused at the administrator's endpoint for a token too. | The endpoint asks nobody who they are, however they came. |
| H12 | A sign-in from another site is refused before the password is looked at, and so is not counted as a failed attempt. | Counted, a page elsewhere could lock anybody's account by trying. |
| H13 | Swagger UI's files are in `backend/src/megooarti/static/swagger-ui`, byte for byte, with their licence, notice and version. The page loads three of them by name through a route (`/api/docs/assets/{name}`); no folder is mounted. `validatorUrl` is null. | The test of route guards cannot see into a mount. Swagger UI asks swagger.io to validate the document of any server that is not on localhost. |
| H14 | In the list of blob stores, `default` has the words "Always kept" where the others have their button. | No button that the server would refuse (UI-2). |
| H15 | A setup or a teardown that fails leaves what it said in `backend/.test-failures/` (the newest fifty), and a Compose command that fails says what Docker said (`containers.ComposeFailed`). | H8 was not caught in 25 runs of the security tests. The next time it has a text. The files caught another failure while this plan was built: `docker compose build` failing once for a whole module, of which `subprocess` said only that the exit status was 1. |
| H16 | The browser tests become 66. The blob store test makes a repository in a store of its own to be refused. | `default` is no longer offered for deletion. |

**Changed after the whole-branch review.** The task bodies below show the code as the tasks made it. The branch differs from them as follows; each change to the code was made test-first, and the spec's section 4 records what they settle as H17 to H20.

| # | Change | Reason |
| --- | --- | --- |
| F1 | `service._settings` gives a repository its format's policy only when it is made (`current is None`). Replaced without one, it keeps the policy stored, or `service.NO_POLICY` (`allow_redeploy`) where none is stored. `HostedSettings.deployment_policy` has that default again, so a row without a policy is answered and not a 500. `test_replacing_a_repository_without_a_policy_gives_it_its_formats_own` is replaced by `..._keeps_the_one_it_has` (four ways of leaving it out, three repositories). | The review: taking a Maven release repository offline changed what could be deployed to it. |
| F2 | `ChoiceGroup` tells of a press on the choice that is checked (`onClick`), and `RepositoryForm` shows `manage.hints.policyFollows` under the deployment policy while `draft.deploymentPolicy` is null. | The review: the policy a person had confirmed changed above the field they were at. |
| F3 | The comment at the refusal of one's own password, the spec's first section and its row H2 say what the refusal is for and what it is not. | The review made the claim untrue with two requests. |
| F4 | `tests/failures.py`: `keep_broken_setup` answers `None` where the file cannot be written; `say_where(write_line, kept)` is the end-of-run line, called from `pytest_terminal_summary` in `conftest.py`, which keeps the paths of this run. | The review stopped a session with a file in the folder's place. |
| F5 | `frontend/openapi.json` and `schema.d.ts` were written again: `HostedSettings` is as it was before this plan, and `HostedIn` is what is sent. The README says that a replaced repository keeps its policy, and where a failed setup's text is. | F1, F4. |

## Global Constraints

- **Nothing that exists is changed by this plan:** no migration. A repository keeps the policy it has, and a repository, a role or a blob store that is called `.` or `..` is still found.
- **The API's version stays `v1`,** and an error is the envelope every other one is: `{"error": {"code", "message", "details", "request_id"}}`, with `422 validation_error` and the field's name for what a body may not hold.
- **No new dependency, no setting.** Swagger UI's files are the only thing added that this project did not write; they are not edited.
- **Backend:** Python 3.13, ruff clean (`uv run ruff check . && uv run ruff format --check .`), 100 columns. No test contacts a real network host except those marked `docker`.
- **Frontend:** text a person reads is in `messages/en.json`; what a caller may not do is not offered (UI-2); Prettier, ESLint and `tsc` clean after Task 5.
- **`frontend/openapi.json` and `frontend/src/lib/api/schema.d.ts` are written by commands,** never by hand (Task 1, Step 5).

**Working directories:** run `uv` and `pytest` commands in `backend/`, `pnpm` commands in `frontend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A repository made by another way than the form:** a script that sends no policy, `"hosted": {}` or a policy of `null`; a `PUT` that leaves the policy out of a repository that had one; a proxy and a group, which have none; a policy that is sent, and must be kept whatever the format would choose (Task 1).
2. **A name at the edge of the rule:** `...`, `.a`, `a.`, `-`; a role called `..` that is already there (Task 1).
3. **A sign-in that says nothing of where it is from** (curl, a package client), one that names the site itself, one through a proxy that sets a base URL, and a wrong password sent from another site again and again (Task 2).
4. **One's own password by a token; another user's password, which is still set; a base URL with a port and a path, and one that is only `@`** (Task 2).
5. **The documentation page on a server that is not on localhost, and a file of its folder that the page does not load:** the licence, a name that leads out of the folder (Task 3).

---

### Task 1: What a repository starts with, and what a new thing may be called

**Files:**
- Create: `backend/src/megooarti/names.py`
- Modify: `backend/src/megooarti/repositories/api.py`, `repositories/formats.py`, `repositories/maven/format.py`, `repositories/service.py`, `security/api/roles.py`, `storage/api.py`, `storage/blob_stores.py`
- Modify: `frontend/openapi.json` (written by the backend test), `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`)
- Test: `backend/tests/repositories/test_api.py`, `backend/tests/repositories/maven/test_hosted_files.py`, `backend/tests/security/test_roles_api.py`, `backend/tests/storage/test_api.py`

**Interfaces:**
- Consumes: `Format.validate_config(type, config, current)`, `service.create_repository`, `service.update_repository`, `blob_stores.delete_blob_store`.
- Produces: `megooarti.names.NewName` (a `str` of the name pattern that is not `.` or `..`); `Format.default_deployment_policy(config: dict) -> str`; `HostedIn` (the policy optional) for what is sent and `HostedSettings` (the policy always there) for what is answered; `blob_stores.DEFAULT_BLOB_STORE = "default"`; `409 default_blob_store`. In the frontend, `components["schemas"]["HostedIn"]`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/test_api.py`:

```diff
@@ -59,6 +59,8 @@ async def test_create_with_explicit_settings(admin_client):
         {"name": "has space"},
         {"name": "a:b"},
         {"name": "star*"},
+        {"name": "."},
+        {"name": ".."},
         {"format": "cobol"},
         {"type": "proxy", "proxy": {"remote_url": "ftp://remote.example"}},
         {"type": "nonsense"},
@@ -229,3 +231,80 @@ async def test_group_mistakes_are_reported(admin_client):
     assert (unknown.status_code, error_code(unknown)) == (422, "validation_error")
     assert (cycle.status_code, error_code(cycle)) == (409, "repository_cycle")
     assert (in_use.status_code, error_code(in_use)) == (409, "in_use")
+
+
+@pytest.mark.parametrize("name", ["...", ".a", "a.", "a..b", "-"])
+async def test_a_name_with_dots_in_it_is_a_name(admin_client, name):
+    # Only . and .. themselves are folders to a browser and a proxy.
+    assert (await admin_client.post(REPOSITORIES, json={**FILES, "name": name})).status_code == 201
+
+
+@pytest.mark.parametrize(
+    ("wanted", "policy"),
+    [
+        # A Maven repository takes releases unless it says otherwise, and a release is
+        # deployed once.
+        ({"format": "maven"}, "disable_redeploy"),
+        ({"format": "maven", "format_config": {"version_policy": "release"}}, "disable_redeploy"),
+        ({"format": "maven", "hosted": {}}, "disable_redeploy"),
+        ({"format": "maven", "hosted": {"deployment_policy": None}}, "disable_redeploy"),
+        # A snapshot is replaced by its nature, and a mixed repository takes snapshots.
+        ({"format": "maven", "format_config": {"version_policy": "snapshot"}}, "allow_redeploy"),
+        ({"format": "maven", "format_config": {"version_policy": "mixed"}}, "allow_redeploy"),
+        ({"format": "raw"}, "allow_redeploy"),
+        ({"format": "npm"}, "allow_redeploy"),
+        ({"format": "pypi", "hosted": {}}, "allow_redeploy"),
+        # What is said is kept, whatever the format would have chosen.
+        ({"format": "maven", "hosted": {"deployment_policy": "allow_redeploy"}}, "allow_redeploy"),
+        ({"format": "maven", "hosted": {"deployment_policy": "read_only"}}, "read_only"),
+        (
+            {"format": "raw", "hosted": {"deployment_policy": "disable_redeploy"}},
+            "disable_redeploy",
+        ),
+    ],
+)
+async def test_a_hosted_repository_given_no_policy_gets_its_formats_own(
+    admin_client, wanted, policy
+):
+    created = await admin_client.post(
+        REPOSITORIES, json={"name": "made", "type": "hosted", **wanted}
+    )
+
+    assert created.status_code == 201, created.text
+    assert created.json()["hosted"] == {"deployment_policy": policy}
+    assert (await admin_client.get(f"{REPOSITORIES}/made")).json()["hosted"] == {
+        "deployment_policy": policy
+    }
+
+
+async def test_replacing_a_repository_without_a_policy_gives_it_its_formats_own(admin_client):
+    for name, format in (("releases", "maven"), ("files", "raw")):
+        wanted = {"name": name, "format": format, "type": "hosted"}
+        await admin_client.post(
+            REPOSITORIES, json={**wanted, "hosted": {"deployment_policy": "read_only"}}
+        )
+
+    releases = await admin_client.put(f"{REPOSITORIES}/releases", json={"online": True})
+    files = await admin_client.put(f"{REPOSITORIES}/files", json={"online": True})
+    kept = await admin_client.put(
+        f"{REPOSITORIES}/releases",
+        json={"online": True, "hosted": {"deployment_policy": "allow_redeploy"}},
+    )
+
+    assert releases.json()["hosted"] == {"deployment_policy": "disable_redeploy"}
+    assert files.json()["hosted"] == {"deployment_policy": "allow_redeploy"}
+    assert kept.json()["hosted"] == {"deployment_policy": "allow_redeploy"}
+
+
+async def test_a_proxy_and_a_group_have_no_deployment_policy(admin_client):
+    proxy = {"name": "central", "format": "maven", "type": "proxy"}
+    made = await admin_client.post(
+        REPOSITORIES, json={**proxy, "proxy": {"remote_url": "https://repo.example.org/maven2"}}
+    )
+    group = await admin_client.post(
+        REPOSITORIES,
+        json={"name": "all", "format": "maven", "type": "group", "group": {"members": []}},
+    )
+
+    assert (made.status_code, made.json()["hosted"]) == (201, None)
+    assert (group.status_code, group.json()["hosted"]) == (201, None)
```

Change `backend/tests/repositories/maven/test_hosted_files.py`:

```diff
@@ -161,3 +161,20 @@ async def test_other_methods_are_not_allowed(client, releases, root, method):
     response = await client.request(method, JAR, content=BYTES, headers=root)
 
     assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
+
+
+async def test_a_release_is_deployed_once_to_a_repository_that_was_given_no_policy(
+    client, releases, snapshots, root
+):
+    # `releases` and `snapshots` are made with nothing said of redeploying (H1).
+    await client.put(JAR, content=BYTES, headers=root)
+    snapshot = f"{SNAPSHOTS}/app-1.0-SNAPSHOT.jar"
+    await client.put(snapshot, content=BYTES, headers=root)
+
+    again = await client.put(JAR, content=b"another build", headers=root)
+    snapshot_again = await client.put(snapshot, content=b"another build", headers=root)
+
+    assert (again.status_code, error_code(again)) == (409, "redeploy_disabled")
+    assert (await client.get(JAR, headers=root)).content == BYTES
+    assert snapshot_again.status_code in (200, 201, 204)
+    assert (await client.get(snapshot, headers=root)).content == b"another build"
```

Change `backend/tests/security/test_roles_api.py`:

```diff
@@ -41,6 +41,8 @@ async def test_create_get_and_list(admin_client):
     [
         {"name": "has space"},
         {"name": ""},
+        {"name": "."},
+        {"name": ".."},
         {"permissions": ["not a pattern"]},
         {"description": "x" * 256},
         {"roles": ["ghost"]},
@@ -129,3 +131,15 @@ async def test_a_permission_granted_through_a_role_takes_effect(
     assert (await other_client.get(ROLES, headers=headers)).status_code == 200
     refused = await other_client.post(ROLES, json=READERS, headers=headers)
     assert (refused.status_code, error_code(refused)) == (403, "forbidden")
+
+
+async def test_a_role_that_is_called_dots_already_is_still_listed(admin_client, db):
+    # Made before the rule, or by another way than this API (H3).
+    await role_service.create_role(db, "..", "", [], [])
+    await db.commit()
+
+    listed = (await admin_client.get(ROLES)).json()["items"]
+
+    assert ".." in [item["name"] for item in listed]
+    # And a name that only has dots in it is a name.
+    assert (await admin_client.post(ROLES, json={**READERS, "name": "..."})).status_code == 201
```

Change `backend/tests/storage/test_api.py`:

```diff
@@ -39,6 +39,8 @@ async def test_create_and_get(admin_client):
     [
         {"name": "has space"},
         {"name": ""},
+        {"name": "."},
+        {"name": ".."},
         {"name": "s3-store", "type": "s3"},
         {"name": "escape", "path": "../outside"},
     ],
@@ -76,3 +78,15 @@ async def test_a_store_in_use_cannot_be_deleted(admin_client, db, default_store)
     response = await admin_client.delete(f"{STORES}/default")
 
     assert (response.status_code, error_code(response)) == (409, "in_use")
+
+
+async def test_the_default_store_cannot_be_deleted(admin_client):
+    # A repository made without naming a blob store is put in it (H7).
+    response = await admin_client.delete(f"{STORES}/default")
+
+    assert (response.status_code, error_code(response)) == (409, "default_blob_store")
+    assert (await admin_client.get(f"{STORES}/default")).status_code == 200
+    made = await admin_client.post(
+        "/api/v1/repositories", json={"name": "files", "format": "raw", "type": "hosted"}
+    )
+    assert (made.status_code, made.json()["blob_store"]) == (201, "default")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_api.py tests/repositories/maven/test_hosted_files.py tests/security/test_roles_api.py tests/storage/test_api.py -q`
Expected: 11 failed, 89 passed. A Maven repository given no policy gets `allow_redeploy`, a policy of `null` is refused, `.` and `..` are taken as names, and `default` is deleted.

- [ ] **Step 3: Implement**

Create `backend/src/megooarti/names.py`:

```python
"""The name of something that has an address: a repository, a role, a blob store."""

from typing import Annotated

from pydantic import AfterValidator, Field

# The same characters as a permission segment, so a name can never shift a permission.
NAME_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"


def _not_a_folder(name: str) -> str:
    # A browser, a proxy and most clients take these for folders, however they are
    # written: what is so named cannot be reached at its own address.
    if name in (".", ".."):
        raise ValueError("must not be . or ..")
    return name


# For what is being made. What is already there, and so named, is still found.
NewName = Annotated[str, Field(pattern=NAME_PATTERN), AfterValidator(_not_a_folder)]
```

Change `backend/src/megooarti/repositories/api.py`:

```diff
@@ -12,6 +12,7 @@ from megooarti.clock import utcnow
 from megooarti.config import Settings
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
+from megooarti.names import NewName
 from megooarti.pagination import Page, PageParams, page
 from megooarti.repositories import service
 from megooarti.repositories.content import build_context
@@ -24,12 +25,17 @@ log = structlog.get_logger(__name__)
 
 router = APIRouter(prefix="/repositories", tags=["repositories"])
 
-# The same characters as a permission segment, so a name can never shift a permission.
-_NAME = r"^[A-Za-z0-9_.-]{1,64}$"
+DeploymentPolicy = Literal["allow_redeploy", "disable_redeploy", "read_only"]
 
 
 class HostedSettings(BaseModel):
-    deployment_policy: Literal["allow_redeploy", "disable_redeploy", "read_only"] = "allow_redeploy"
+    deployment_policy: DeploymentPolicy
+
+
+class HostedIn(BaseModel):
+    # Left out, the server chooses: a Maven repository for releases refuses to replace
+    # what was deployed, and every other one allows it.
+    deployment_policy: DeploymentPolicy | None = None
 
 
 class NegativeCache(BaseModel):
@@ -96,12 +102,12 @@ class RepositoryOut(BaseModel):
 
 
 class RepositoryCreate(BaseModel):
-    name: str = Field(pattern=_NAME)
+    name: NewName
     format: str
     type: Literal["hosted", "proxy", "group"]
     online: bool = True
     blob_store: str | None = None
-    hosted: HostedSettings | None = None
+    hosted: HostedIn | None = None
     proxy: ProxyIn | None = None
     group: GroupSettings | None = None
     format_config: dict[str, Any] = {}
@@ -109,7 +115,7 @@ class RepositoryCreate(BaseModel):
 
 class RepositoryUpdate(BaseModel):
     online: bool = True
-    hosted: HostedSettings | None = None
+    hosted: HostedIn | None = None
     proxy: ProxyIn | None = None
     group: GroupSettings | None = None
     format_config: dict[str, Any] = {}
```

Change `backend/src/megooarti/repositories/formats.py`:

```diff
@@ -135,6 +135,14 @@ class Format:
             raise ApiError(422, "validation_error", "The request is not valid.", details)
         return {}
 
+    def default_deployment_policy(self, config: dict[str, Any]) -> str:
+        """The deployment policy of a hosted repository that was given none.
+
+        `config` is this format's own settings, as `validate_config` returned them.
+        The generic format lets a file be replaced.
+        """
+        return "allow_redeploy"
+
     def describe_component(self, path: str) -> ComponentKey | None:
         """Which component a stored path belongs to: the file, in its directory.
 
```

Change `backend/src/megooarti/repositories/maven/format.py`:

```diff
@@ -416,6 +416,15 @@ class MavenFormat(Format):
             "layout_policy": _choice(config, "layout_policy", paths.LAYOUT_POLICIES, "strict"),
         }
 
+    def default_deployment_policy(self, config: dict[str, Any]) -> str:
+        """A release is deployed once: replaced, a build that used it cannot be repeated.
+
+        A snapshot is replaced by its nature, and a mixed repository takes snapshots.
+        """
+        if config.get("version_policy") == "release":
+            return "disable_redeploy"
+        return "allow_redeploy"
+
     def describe_component(self, path: str) -> ComponentKey | None:
         """An artifact file belongs to its group, artifact and version. Nothing else does."""
         parsed = paths.classify(path)
```

Change `backend/src/megooarti/repositories/service.py`:

```diff
@@ -13,7 +13,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.clock import utcnow
 from megooarti.errors import ApiError
-from megooarti.repositories.formats import format_names, get_format
+from megooarti.repositories.formats import Format, format_names, get_format
 from megooarti.repositories.models import (
     Asset,
     NegativeCacheEntry,
@@ -23,7 +23,7 @@ from megooarti.repositories.models import (
 )
 from megooarti.secrets_box import Sealed
 from megooarti.storage import blobs
-from megooarti.storage.blob_stores import get_blob_store
+from megooarti.storage.blob_stores import DEFAULT_BLOB_STORE, get_blob_store
 from megooarti.storage.models import BlobStore
 
 DEPLOYMENT_POLICIES = ("allow_redeploy", "disable_redeploy", "read_only")
@@ -50,8 +50,9 @@ def _invalid(field: str, message: str) -> ApiError:
     return ApiError(422, "validation_error", "The request is not valid.", details)
 
 
-def _hosted_settings(hosted: dict[str, Any] | None) -> dict[str, Any]:
-    policy = (hosted or {}).get("deployment_policy", "allow_redeploy")
+def _hosted_settings(hosted: dict[str, Any] | None, default: str) -> dict[str, Any]:
+    """`default` is the policy of a repository that is given none: its format's to say."""
+    policy = (hosted or {}).get("deployment_policy") or default
     if policy not in DEPLOYMENT_POLICIES:
         choices = ", ".join(DEPLOYMENT_POLICIES)
         raise _invalid("hosted.deployment_policy", f"Must be one of: {choices}.")
@@ -282,17 +283,25 @@ async def list_repositories(
     return [await describe(db, repository) for repository in page], total or 0
 
 
-def _type_settings(
+def _settings(
+    handler: Format,
     type: str,
     hosted: dict[str, Any] | None,
     proxy: dict[str, Any] | None,
+    format_config: dict[str, Any] | None,
     current: dict[str, Any] | None,
 ) -> dict[str, Any]:
+    """What a repository's `config` holds: its type's settings and its format's."""
+    config = handler.validate_config(
+        type, format_config or {}, (current or {}).get("format_config")
+    )
+    settings: dict[str, Any] = {}
     if type == "hosted":
-        return {"hosted": _hosted_settings(hosted)}
+        default = handler.default_deployment_policy(config)
+        settings["hosted"] = _hosted_settings(hosted, default)
     if type == "proxy":
-        return {"proxy": _proxy_settings(proxy, (current or {}).get("proxy"))}
-    return {}
+        settings["proxy"] = _proxy_settings(proxy, (current or {}).get("proxy"))
+    return {**settings, "format_config": config}
 
 
 async def create_repository(
@@ -315,13 +324,10 @@ async def create_repository(
     if type not in handler.types:
         raise _invalid("type", f"{type} repositories are not available for this format.")
     handler.validate_name(name)
-    settings = {
-        **_type_settings(type, hosted, proxy, None),
-        "format_config": handler.validate_config(type, format_config or {}),
-    }
+    settings = _settings(handler, type, hosted, proxy, format_config, None)
     store_id = None
     if type != "group":  # a group stores nothing of its own
-        store = await get_blob_store(db, blob_store or "default")
+        store = await get_blob_store(db, blob_store or DEFAULT_BLOB_STORE)
         if store is None:
             raise _invalid("blob_store", f"Unknown blob store: {blob_store}.")
         store_id = store.id
@@ -360,12 +366,9 @@ async def update_repository(
         # Leaving the members out must not quietly empty the group.
         raise _invalid("group", "A group's members must be given.")
     before = repository.config.get("proxy")
-    repository.config = {
-        **_type_settings(repository.type, hosted, proxy, repository.config),
-        "format_config": handler.validate_config(
-            repository.type, format_config or {}, repository.config.get("format_config")
-        ),
-    }
+    repository.config = _settings(
+        handler, repository.type, hosted, proxy, format_config, repository.config
+    )
     repository.online = online
     await db.flush()
     if repository.type == "group":
```

Change `backend/src/megooarti/security/api/roles.py`:

```diff
@@ -7,6 +7,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
+from megooarti.names import NewName
 from megooarti.pagination import Page, PageParams, page
 from megooarti.security import roles
 from megooarti.security.api.schemas import Pattern
@@ -35,7 +36,7 @@ class RoleContent(BaseModel):
 
 
 class RoleCreate(RoleContent):
-    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
+    name: NewName
 
 
 async def _load(db: AsyncSession, name: str) -> Role:
```

Change `backend/src/megooarti/storage/api.py`:

```diff
@@ -7,6 +7,7 @@ from sqlalchemy.ext.asyncio import AsyncSession
 
 from megooarti.db.session import get_session
 from megooarti.errors import ApiError
+from megooarti.names import NewName
 from megooarti.pagination import Page, PageParams, page
 from megooarti.security.authentication import Principal, require
 from megooarti.storage import blob_stores
@@ -28,7 +29,7 @@ class BlobStoreOut(BaseModel):
 
 
 class BlobStoreCreate(BaseModel):
-    name: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
+    name: NewName
     type: str = "file"
     path: str | None = Field(default=None, max_length=1024)
 
```

Change `backend/src/megooarti/storage/blob_stores.py`:

```diff
@@ -13,6 +13,9 @@ from megooarti.repositories.models import Repository
 from megooarti.storage.backends import BlobBackend, FileBlobBackend
 from megooarti.storage.models import Blob, BlobStore
 
+# The one a migration made, and where a repository is put that names none.
+DEFAULT_BLOB_STORE = "default"
+
 
 @dataclass(frozen=True)
 class BlobStoreView:
@@ -118,6 +121,13 @@ async def delete_blob_store(db: AsyncSession, store: BlobStore) -> None:
     )
     if user is not None:
         raise ApiError(409, "in_use", f"The repository {user} uses this blob store.")
+    if store.name == DEFAULT_BLOB_STORE:
+        raise ApiError(
+            409,
+            "default_blob_store",
+            "The default blob store cannot be deleted: "
+            "a repository made without naming one is put in it.",
+        )
     # With no repository there is no asset, so every remaining blob is unreferenced.
     await db.execute(delete(Blob).where(Blob.blob_store_id == store.id))
     await db.delete(store)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/test_api.py tests/repositories/maven/test_hosted_files.py tests/security/test_roles_api.py tests/storage/test_api.py -q`
Expected: 100 passed.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check .`
Expected: no finding.

- [ ] **Step 5: Write the copy of the API document, and the types from it**

Run (in `backend/`): `uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 failed: the copy in `frontend/openapi.json` is out of date (`HostedIn` is new).

Run (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 passed.

Run (in `frontend/`): `pnpm gen:api`
Expected: `openapi.json → src/lib/api/schema.d.ts`.

Run (in `frontend/`): `pnpm test && pnpm typecheck`
Expected: 771 passed in 26 files, and no type error: what the form sends still fits `HostedIn`.

- [ ] **Step 6: Commit**

```bash
git add backend frontend/openapi.json frontend/src/lib/api/schema.d.ts
git commit -m "feat(api): a Maven release repository refuses redeploy by default; no name is . or ..; the default blob store is kept"
```

---

### Task 2: Who is asked who they are, and what the base URL carries

**Files:**
- Modify: `backend/src/megooarti/security/api/users.py`, `security/authentication.py`, `security/api/auth.py`, `system/settings_api.py`
- Test: `backend/tests/security/test_users_api.py`, `backend/tests/security/test_cross_site.py`, `backend/tests/test_settings_api.py`

**Interfaces:**
- Consumes: `_refuse_cross_site(request, db)` and `ApiError` as they are; `PUT /me/password`, which asks for `current_password`.
- Produces: `authentication.refuse_cross_site` (a dependency for a route that identifies nobody and changes something); `409 own_password` from `PUT /users/{id}/password` for the caller's own id; `422` at `base_url` for an address with `@` before its host.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/security/test_users_api.py`:

```diff
@@ -215,3 +215,37 @@ async def test_text_the_database_cannot_store_is_a_validation_error(admin_client
     response = await admin_client.patch(f"{USERS}/{dana.id}", json={"display_name": "D\x00"})
 
     assert (response.status_code, error_code(response)) == (422, "validation_error")
+
+
+async def test_ones_own_password_is_not_set_here(admin_client, other_client):
+    # Nobody is asked who they are here: an open session would be enough to keep the
+    # account (H2). It is changed at /me/password, which asks for the present one.
+    root_id = await id_of(admin_client, "root")
+
+    response = await admin_client.put(
+        f"{USERS}/{root_id}/password", json={"password": "a password of the thief's"}
+    )
+
+    assert (response.status_code, error_code(response)) == (409, "own_password")
+    assert "/api/v1/me/password" in response.json()["error"]["message"]
+    # Nothing changed: the session is alive, and the password is the one it was.
+    assert (await admin_client.get(SESSION)).json()["authenticated"] is True
+    assert (await sign_in(other_client, "root"))["must_change_password"] is False
+    changed = await admin_client.put(
+        "/api/v1/me/password",
+        json={"current_password": PASSWORD, "new_password": "a password of my own"},
+    )
+    assert changed.status_code == 204
+
+
+async def test_ones_own_password_is_not_set_here_with_a_token_either(client, make_user, make_token):
+    root = await make_user("root", roles=["admin"])
+    token = await make_token(root)
+
+    response = await client.put(
+        f"{USERS}/{root.id}/password",
+        json={"password": "a password of the thief's"},
+        headers={"Authorization": f"Bearer {token}"},
+    )
+
+    assert (response.status_code, error_code(response)) == (409, "own_password")
```

Change `backend/tests/security/test_cross_site.py`:

```diff
@@ -67,3 +67,61 @@ async def test_the_configured_base_url_counts_as_the_sites_own_origin(client, ro
     proxied = {**root, "Origin": "https://repo.example.org", "Host": "backend:8000"}
 
     assert (await client.post(ROLES, json=ROLE, headers=proxied)).status_code == 201
+
+
+LOGIN = "/api/v1/auth/login"
+LOGOUT = "/api/v1/auth/logout"
+SESSION = "/api/v1/auth/session"
+CREDENTIALS = {"username": "root", "password": PASSWORD}
+
+
+@pytest.mark.parametrize(
+    "said",
+    [
+        {"Sec-Fetch-Site": "cross-site"},
+        # Without fetch metadata (plain HTTP), where the page is from is all there is.
+        {"Origin": "http://evil.example", "Host": "arti.example"},
+    ],
+)
+async def test_nobody_is_signed_in_from_another_site(client, root, said):
+    # A page elsewhere could sign its visitor in to an account of its own (H5).
+    response = await client.post(LOGIN, json=CREDENTIALS, headers=said)
+
+    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
+    assert "set-cookie" not in response.headers
+    assert (await client.get(SESSION)).json()["authenticated"] is False
+
+
+@pytest.mark.parametrize(
+    "said",
+    [
+        {},  # curl, a script: they say nothing of where they are from
+        {"Sec-Fetch-Site": "same-origin"},
+        {"Sec-Fetch-Site": "none"},
+        {"Origin": "http://arti.example", "Host": "arti.example"},
+    ],
+)
+async def test_signing_in_from_the_site_itself_or_from_no_site_goes_on(client, root, said):
+    response = await client.post(LOGIN, json=CREDENTIALS, headers=said)
+
+    assert response.status_code == 200
+    assert (await client.get(SESSION)).json()["authenticated"] is True
+
+
+async def test_a_wrong_password_from_another_site_is_not_counted_as_an_attempt(client, root):
+    wrong = {"username": "root", "password": "not the password"}
+    for _ in range(10):  # more than the failures that lock an account for a while
+        refused = await client.post(LOGIN, json=wrong, headers={"Sec-Fetch-Site": "cross-site"})
+        assert refused.status_code == 403
+
+    assert (await client.post(LOGIN, json=CREDENTIALS)).status_code == 200
+
+
+async def test_nobody_is_signed_out_from_another_site(client, root):
+    signed_in = (await client.post(LOGIN, json=CREDENTIALS)).json()
+    token = {"X-CSRF-Token": signed_in["csrf_token"]}
+
+    response = await client.post(LOGOUT, headers={**token, "Sec-Fetch-Site": "cross-site"})
+
+    assert (response.status_code, error_code(response)) == (403, "cross_site_request")
+    assert (await client.get(SESSION)).json()["authenticated"] is True
```

Change `backend/tests/test_settings_api.py`:

```diff
@@ -33,7 +33,17 @@ async def test_base_url_is_stored_without_a_trailing_slash_and_can_be_cleared(ad
 
 
 @pytest.mark.parametrize(
-    "value", ["ftp://repo.example.org", "repo.example.org", "https://", "https://x.example/?a=1"]
+    "value",
+    [
+        "ftp://repo.example.org",
+        "repo.example.org",
+        "https://",
+        "https://x.example/?a=1",
+        # Every address the server gives out would carry them (H4).
+        "https://robot:secret@repo.example.org",
+        "https://robot@repo.example.org",
+        "https://@repo.example.org",
+    ],
 )
 async def test_an_invalid_base_url_is_rejected(admin_client, value):
     response = await admin_client.put(f"{SETTINGS}/base-url", json={"base_url": value})
@@ -67,3 +77,12 @@ async def test_reading_settings_does_not_allow_changing_them(client, make_user,
 
     assert read.status_code == 200
     assert (write.status_code, error_code(write)) == (403, "forbidden")
+
+
+async def test_a_base_url_may_have_a_port_and_a_path(admin_client):
+    response = await admin_client.put(
+        f"{SETTINGS}/base-url", json={"base_url": "http://repo.example.org:8081/megooarti"}
+    )
+
+    assert response.status_code == 200
+    assert response.json()["base_url"] == "http://repo.example.org:8081/megooarti"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/security/test_users_api.py tests/security/test_cross_site.py tests/test_settings_api.py -q`
Expected: 8 failed, 48 passed. One's own password is set, the sign-in from another site is taken (and ten wrong passwords from there lock the account), and the three addresses with `@` are stored.

- [ ] **Step 3: Implement**

Change `backend/src/megooarti/security/api/users.py`:

```diff
@@ -157,13 +157,16 @@ async def reset_password(
     db: AsyncSession = Depends(get_session),
 ) -> None:
     user = await _load(db, user_id)
-    own_session = principal.session if user.id == principal.user.id else None
+    if user.id == principal.user.id:
+        # Here nobody is asked who they are: a session left open, or a stolen cookie,
+        # would be enough to keep the account.
+        raise ApiError(
+            409,
+            "own_password",
+            "Change your own password at PUT /api/v1/me/password, which asks for the present one.",
+        )
     await users.set_password(
-        db,
-        user,
-        body.password,
-        must_change_password=body.must_change_password,
-        keep_session_id=None if own_session is None else own_session.id,
+        db, user, body.password, must_change_password=body.must_change_password
     )
     await db.commit()
     discard_initial_password(request.app.state.settings, user)
```

Change `backend/src/megooarti/security/authentication.py`:

```diff
@@ -385,6 +385,15 @@ async def _refuse_cross_site(request: Request, db: AsyncSession) -> None:
         raise refusal
 
 
+async def refuse_cross_site(request: Request, db: AsyncSession = Depends(get_session)) -> None:
+    """For a route that identifies nobody and still changes something: signing in.
+
+    A page on another site could otherwise sign its visitor in to an account of its
+    own choosing, and what the visitor then did would be done as that account.
+    """
+    await _refuse_cross_site(request, db)
+
+
 async def _identify(
     request: Request, db: AsyncSession, scheme: Scheme, *, registry: bool = False
 ) -> Principal | None:
```

Change `backend/src/megooarti/security/api/auth.py`:

```diff
@@ -17,6 +17,7 @@ from megooarti.security.authentication import (
     build_principal,
     client_ip,
     current_principal,
+    refuse_cross_site,
 )
 
 log = structlog.get_logger(__name__)
@@ -70,7 +71,7 @@ def session_info(principal: Principal | None) -> SessionInfo:
     )
 
 
-@router.post("/login", response_model=SessionInfo)
+@router.post("/login", response_model=SessionInfo, dependencies=[Depends(refuse_cross_site)])
 async def login(
     body: LoginRequest,
     request: Request,
```

Change `backend/src/megooarti/system/settings_api.py`:

```diff
@@ -37,6 +37,9 @@ class BaseUrl(BaseModel):
         parts = urlsplit(value)
         if parts.scheme not in ("http", "https") or not parts.netloc:
             raise ValueError("must be an http or https URL")
+        if "@" in parts.netloc:
+            # Every address the server gives out is built from it, and would carry them.
+            raise ValueError("must not contain a user name or a password")
         if parts.query or parts.fragment:
             raise ValueError("must not contain a query or a fragment")
         return value.rstrip("/")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/security/test_users_api.py tests/security/test_cross_site.py tests/test_settings_api.py tests/security/test_auth_api.py -q`
Expected: 75 passed. `test_auth_api.py` is run with them: signing in as before still works.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check .`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "fix(security): no sign-in from another site, one's own password only with the present one, no credentials in the base URL"
```

---

### Task 3: The documentation page asks nothing of another host

**Files:**
- Create: `backend/src/megooarti/api_docs.py`
- Create: `backend/src/megooarti/static/swagger-ui/` (seven files of Swagger UI 5.33.2: Step 3)
- Modify: `backend/src/megooarti/main.py`, `.gitattributes`
- Test: `backend/tests/test_api_docs.py`, `backend/tests/test_route_guards.py`

**Interfaces:**
- Consumes: `fastapi.openapi.docs.get_swagger_ui_html`, `API_PREFIX`.
- Produces: `api_docs.docs_router(openapi_url, title) -> APIRouter` with `GET /api/docs` and `GET /api/docs/assets/{name}`; `api_docs.ASSETS` (the folder). The application has no `docs_url` of FastAPI's own, and so no `/docs/oauth2-redirect`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api_docs.py`:

```python
"""The API's documentation page asks nothing of another host (H6)."""

import re

import pytest

from megooarti.api_docs import ASSETS

DOCS = "/api/docs"


async def test_the_page_loads_its_script_and_its_stylesheet_from_this_server(client):
    response = await client.get(DOCS)
    page = response.text

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/html")
    loaded = re.findall(r"""(?:src|href)=["']([^"']+)["']""", page)
    assert sorted(loaded) == [
        "/api/docs/assets/favicon-32x32.png",
        "/api/docs/assets/swagger-ui-bundle.js",
        "/api/docs/assets/swagger-ui.css",
    ]
    # No address of another host anywhere in it: not a CDN, not a favicon.
    assert re.findall(r"""https?://[^\s"']+""", page) == []
    assert "/api/v1/openapi.json" in page
    # Swagger UI would ask swagger.io to validate the document of a server that is not
    # on localhost: it is told not to.
    assert '"validatorUrl": null' in page


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("swagger-ui-bundle.js", "text/javascript"),
        ("swagger-ui.css", "text/css"),
        ("favicon-32x32.png", "image/png"),
    ],
)
async def test_what_the_page_loads_is_served(client, name, kind):
    response = await client.get(f"{DOCS}/assets/{name}")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith(kind)
    assert response.content == (ASSETS / name).read_bytes()


@pytest.mark.parametrize("name", ["LICENSE", "VERSION", "nothing.js", "..%2Fnames.py"])
async def test_nothing_else_of_the_folder_is_served(client, name):
    response = await client.get(f"{DOCS}/assets/{name}")

    assert response.status_code == 404


def test_the_files_are_the_version_they_are_said_to_be_and_have_their_licence():
    version = (ASSETS / "VERSION").read_text(encoding="utf-8").strip()

    assert re.fullmatch(r"5\.\d+\.\d+", version)
    # The bundle says which Swagger UI it is.
    assert f'"{version}"'.encode() in (ASSETS / "swagger-ui-bundle.js").read_bytes()
    assert "Apache License" in (ASSETS / "LICENSE").read_text(encoding="utf-8")
    assert (ASSETS / "NOTICE").is_file()


async def test_the_api_document_is_where_the_page_says(client):
    document = (await client.get("/api/v1/openapi.json")).json()

    assert document["info"]["title"] == "MegooArti"
    # The page and its files are not operations of the API.
    assert not [path for path in document["paths"] if path.startswith(DOCS)]
```

Change `backend/tests/test_route_guards.py`:

```diff
@@ -17,9 +17,9 @@ OPEN = {
     "/api/v1/status/ready",
     "/api/v1/auth/login",  # this is where credentials are presented
 }
-# The API description and its viewer, which FastAPI adds itself. They describe the
+# The API description, its viewer and the files the viewer loads. They describe the
 # API's shape, not its data, and are left open by design.
-DOCUMENTATION = {"/api/v1/openapi.json", "/api/docs", "/docs/oauth2-redirect"}
+DOCUMENTATION = {"/api/v1/openapi.json", "/api/docs", "/api/docs/assets/{name}"}
 
 
 def dependency_calls(dependant) -> set:
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_api_docs.py tests/test_route_guards.py -q`
Expected: an error while collecting `tests/test_api_docs.py`: there is no module `megooarti.api_docs`.

- [ ] **Step 3: Put Swagger UI's files in the package**

They are the files of the npm package `swagger-ui-dist` at version 5.33.2, unchanged. `.gitattributes` (below) keeps Git from changing a byte of them, so change it first.

Change `.gitattributes`:

```diff
@@ -19,3 +19,6 @@
 Dockerfile text eol=lf
 .dockerignore text eol=lf
 *.woff2 binary
+*.png binary
+# Another project's files, kept byte for byte.
+backend/src/megooarti/static/** -text
```

```bash
mkdir -p /tmp/swagger && cd /tmp/swagger
npm pack swagger-ui-dist@5.33.2 && tar -xzf swagger-ui-dist-5.33.2.tgz
D=<repository>/backend/src/megooarti/static/swagger-ui
mkdir -p "$D"
cp package/swagger-ui-bundle.js package/swagger-ui.css package/favicon-32x32.png \
   package/LICENSE package/NOTICE package/swagger-ui-bundle.js.LICENSE.txt "$D/"
printf '5.33.2\n' > "$D/VERSION"
```

Run (in `backend/src/megooarti/static/swagger-ui/`): `sha256sum *`
Expected:

```text
cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30 *LICENSE
0d20d1adef18aee3f40dd258172155521ce702ac445cb5f7b7d60ed32dad2fb2 *NOTICE
37241d10235f1ae313335a1ddcf39b4f169ec50d9b8aa2c16bf2cbc1bdba4f24 *VERSION
3ed612f41e050ca5e7000cad6f1cbe7e7da39f65fca99c02e99e6591056e5837 *favicon-32x32.png
6b3bfcaff3fc82c0e6992ca4b370c4f22970dec35fff60d229302b3ee7688715 *swagger-ui-bundle.js
e5a4792feaa5332dfba37f1d7adf84308b93b4f2d8da0569a9f48a3cb61c969b *swagger-ui-bundle.js.LICENSE.txt
1ac324f7dcd27e4b9386b4bd6421271ec147e922a22c05ba24b11515e9aa6321 *swagger-ui.css
```

- [ ] **Step 4: Implement**

Create `backend/src/megooarti/api_docs.py`:

```python
"""The API's documentation page, served with its own script and stylesheet.

FastAPI's own page loads Swagger UI from a public CDN: an installation without the
internet then has no page, and one with it runs a third party's script on its own
origin. The files are kept in `static/swagger-ui`, with their licence and the version
they are. They are those of the npm package `swagger-ui-dist`, unchanged: to replace
them, unpack another version of it (`npm pack swagger-ui-dist@<version>`), copy the
same six files, and write the version to `VERSION`.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse

from megooarti.errors import ApiError

DOCS_PATH = "/api/docs"
ASSETS = Path(__file__).parent / "static" / "swagger-ui"
# What the page loads, by the name it asks for. Nothing else in the folder is served.
_SERVED = {
    "swagger-ui-bundle.js": "text/javascript",
    "swagger-ui.css": "text/css",
    "favicon-32x32.png": "image/png",
}


def docs_router(openapi_url: str, title: str) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get(DOCS_PATH, response_class=HTMLResponse)
    async def docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=openapi_url,
            title=title,
            swagger_js_url=f"{DOCS_PATH}/assets/swagger-ui-bundle.js",
            swagger_css_url=f"{DOCS_PATH}/assets/swagger-ui.css",
            swagger_favicon_url=f"{DOCS_PATH}/assets/favicon-32x32.png",
            oauth2_redirect_url=None,
            # Swagger UI asks swagger.io to validate the document of a server that is
            # not on localhost, unless it is told not to.
            swagger_ui_parameters={"validatorUrl": None},
        )

    @router.get(f"{DOCS_PATH}/assets/{{name}}")
    async def asset(name: str) -> FileResponse:
        media_type = _SERVED.get(name)
        if media_type is None:
            raise ApiError(404, "not_found", "No such file.")
        return FileResponse(ASSETS / name, media_type=media_type)

    return router
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -9,6 +9,7 @@ from fastapi import FastAPI
 from sqlalchemy.ext.asyncio import create_async_engine
 
 from megooarti import __version__
+from megooarti.api_docs import docs_router
 from megooarti.clock import utcnow
 from megooarti.config import Settings, get_settings
 from megooarti.db.schema import head_revision
@@ -117,7 +118,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
         title="MegooArti",
         version=__version__,
         openapi_url=f"{API_PREFIX}/openapi.json",
-        docs_url="/api/docs",
+        docs_url=None,  # served by api_docs, with its own files
         redoc_url=None,
         lifespan=_lifespan,
         responses=ERROR_RESPONSES,
@@ -134,6 +135,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     # The one client for requests to proxy remotes. Tests replace it with a fake remote.
     app.state.http = None  # built by remote.client_of on first use: it is slow to create
     register_error_handlers(app)
+    app.include_router(docs_router(f"{API_PREFIX}/openapi.json", "MegooArti API"))
     app.include_router(status_router, prefix=API_PREFIX)
     app.include_router(auth_api.router, prefix=API_PREFIX)
     app.include_router(me_api.router, prefix=API_PREFIX)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_api_docs.py tests/test_route_guards.py tests/test_openapi_snapshot.py -q`
Expected: 15 passed. The page and its files are not operations of the API, so its document is as it was.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check .`
Expected: no finding.

- [ ] **Step 6: Commit**

```bash
git add .gitattributes backend
git commit -m "feat(api): the documentation page is served with its own files"
```

Run: `git ls-files --eol backend/src/megooarti/static/swagger-ui`
Expected: every line has `attr/-text`: Git changes no byte of them. `sha256sum` in the folder still gives the sums of Step 3.

---

### Task 4: What a failed setup said is kept, and what Docker said

**Files:**
- Create: `backend/tests/failures.py`
- Modify: `backend/tests/conftest.py`, `backend/tests/containers.py`, `.gitignore`
- Test: `backend/tests/test_support.py`

**Interfaces:**
- Consumes: pytest's `pytest_runtest_logreport(report)` hook and its `pytester` fixture.
- Produces: `tests.failures.keep_failure(directory, nodeid, when, text, now=None) -> Path`, `keep_broken_setup(report, directory=DIRECTORY) -> Path | None`, `DIRECTORY` (`backend/.test-failures`), `KEPT = 50`; `containers.ComposeFailed` (a `RuntimeError` with `returncode`, `stdout`, `stderr`), raised by `containers.compose(...)` in place of `subprocess.CalledProcessError`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/test_support.py`:

```diff
@@ -1,13 +1,17 @@
 """Tests of the test support code that every later test relies on."""
 
+import subprocess
 from collections.abc import AsyncIterator
 from contextlib import asynccontextmanager
+from datetime import UTC, datetime, timedelta
 
 import pytest
 from fastapi import FastAPI
 
+from tests import containers
 from tests.clients import client_for
 from tests.databases import reset_schema
+from tests.failures import KEPT, keep_failure
 
 
 async def test_client_for_runs_the_application_lifespan():
@@ -33,3 +37,96 @@ def test_reset_schema_refuses_a_database_not_named_for_tests(name):
 
     with pytest.raises(ValueError, match="_test"):
         reset_schema(url)
+
+
+def test_what_a_failed_setup_said_is_kept_in_a_file_of_its_own(tmp_path):
+    kept = keep_failure(
+        tmp_path / "failures",
+        "tests/security/test_roles.py::test_a_role[a/b c]",
+        "setup",
+        "OSError: [WinError 64] The specified network name is no longer available",
+        now=datetime(2026, 10, 13, 8, 30, tzinfo=UTC),
+    )
+
+    assert kept.parent == tmp_path / "failures"
+    assert kept.name == (
+        "20261013T083000000000-setup-tests_security_test_roles.py_test_a_role_a_b_c_.txt"
+    )
+    said = kept.read_text(encoding="utf-8")
+    assert said.startswith("tests/security/test_roles.py::test_a_role[a/b c] (setup)\n")
+    assert "WinError 64" in said
+
+
+def test_only_the_newest_failures_are_kept(tmp_path):
+    start = datetime(2026, 10, 13, tzinfo=UTC)
+    for minute in range(KEPT + 3):
+        keep_failure(
+            tmp_path, f"test_{minute}", "setup", "x", now=start + timedelta(minutes=minute)
+        )
+
+    names = sorted(path.name for path in tmp_path.iterdir())
+
+    assert len(names) == KEPT
+    assert names[0].endswith("-setup-test_3.txt")
+    assert names[-1].endswith(f"-setup-test_{KEPT + 2}.txt")
+
+
+def test_a_setup_that_fails_is_kept_and_a_test_that_fails_is_not(pytester):
+    pytester.makeconftest(
+        """
+        from pathlib import Path
+        from tests.failures import keep_broken_setup
+
+        def pytest_runtest_logreport(report):
+            keep_broken_setup(report, Path("kept"))
+        """
+    )
+    pytester.makepyfile(
+        """
+        import pytest
+
+        @pytest.fixture
+        def broken():
+            raise OSError("the database went away")
+
+        def test_needs_it(broken):
+            pass
+
+        def test_fails_by_itself():
+            assert 1 == 2
+        """
+    )
+
+    result = pytester.runpytest_inprocess("-p", "no:cacheprovider", "-p", "no:asyncio")
+
+    result.assert_outcomes(errors=1, failed=1)
+    (kept,) = (pytester.path / "kept").iterdir()
+    assert "-setup-" in kept.name
+    assert "the database went away" in kept.read_text(encoding="utf-8")
+
+
+def _docker_answers(monkeypatch, returncode: int, stderr: str) -> None:
+    def run(command, **_):
+        return subprocess.CompletedProcess(command, returncode, stdout="", stderr=stderr)
+
+    monkeypatch.setattr(containers.subprocess, "run", run)
+
+
+def test_a_compose_command_that_fails_says_what_docker_said(monkeypatch):
+    refusal = "failed to solve: python:3.13-slim: failed to resolve source metadata: timeout"
+    _docker_answers(monkeypatch, 1, f"#1 [internal] load build definition\n{refusal}\n")
+
+    with pytest.raises(containers.ComposeFailed) as caught:
+        containers.compose("build")
+
+    assert str(caught.value).startswith("docker compose build exited with 1:")
+    assert refusal in str(caught.value)
+    assert caught.value.returncode == 1
+
+
+def test_a_compose_command_that_may_fail_is_answered_as_it_ended(monkeypatch):
+    _docker_answers(monkeypatch, 1, "no such service")
+
+    result = containers.compose("down", "--volumes", check=False)
+
+    assert (result.returncode, result.stderr) == (1, "no such service")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_support.py -q`
Expected: an error while collecting: there is no module `tests.failures`.

- [ ] **Step 3: Implement**

Change `.gitignore`:

```diff
@@ -8,3 +8,4 @@ requirements.txt
 node_modules/
 .next/
 backend/data/
+backend/.test-failures/
```

Create `backend/tests/failures.py`:

```python
"""What a test said when it could not be set up, kept where it is found afterwards.

A test that fails says why in the run's own output. A setup that fails once in many
runs says it into an output that was piped through `tail`, or scrolled away, and the
suite is then run again and passes. So the text is also written to a file.
"""

import re
from datetime import UTC, datetime
from pathlib import Path

# Beside the tests, and not in the repository (.gitignore).
DIRECTORY = Path(__file__).parent.parent / ".test-failures"
KEPT = 50


def keep_failure(
    directory: Path, nodeid: str, when: str, text: str, now: datetime | None = None
) -> Path:
    """Write one failure to a file of its own, and let go of all but the newest."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%f")
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid)[-120:]
    path = directory / f"{stamp}-{when}-{name}.txt"
    path.write_text(f"{nodeid} ({when})\n\n{text}\n", encoding="utf-8")
    for old in sorted(directory.glob("*.txt"))[:-KEPT]:
        old.unlink(missing_ok=True)
    return path


def keep_broken_setup(report, directory: Path = DIRECTORY) -> Path | None:
    """For pytest's `pytest_runtest_logreport`: keep a setup or a teardown that failed.

    Not a test that failed: that is what a test is run to see.
    """
    if not report.failed or report.when == "call":
        return None
    return keep_failure(directory, report.nodeid, report.when, report.longreprtext)
```

Change `backend/tests/conftest.py`:

```diff
@@ -28,10 +28,20 @@ from tests.accounts import PASSWORD, sign_in
 from tests.clients import client_for
 from tests.containers import DATA_FILE, call, compose
 from tests.databases import ensure_database, reset_schema
+from tests.failures import keep_broken_setup
 
 DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"
 
 
+# For the tests of the tests' own support code.
+pytest_plugins = ["pytester"]
+
+
+def pytest_runtest_logreport(report: pytest.TestReport) -> None:
+    """Keep what a failed setup said, whatever becomes of the run's own output."""
+    keep_broken_setup(report)
+
+
 def _configured_test_database_url() -> str:
     raw = os.environ.get("MEGOOARTI_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
     return Settings(_env_file=None, database_url=raw).database_url
```

Change `backend/tests/containers.py`:

```diff
@@ -15,8 +15,22 @@ ENVIRONMENT = {**os.environ, "MEGOOARTI_HTTP_PORT": HTTP_PORT, "MEGOOARTI_DB_POR
 DATA_FILE = "/var/lib/megooarti/admin.password"
 
 
+class ComposeFailed(RuntimeError):
+    """A Compose command that did not succeed, with what Docker said.
+
+    `subprocess` says only that the exit status was not zero, which is no reason: a
+    build that could not reach a registry and one that could not compile look alike.
+    """
+
+    def __init__(self, arguments: tuple[str, ...], result: subprocess.CompletedProcess[str]):
+        self.returncode, self.stdout, self.stderr = result.returncode, result.stdout, result.stderr
+        said = (result.stderr or result.stdout or "").strip()[-4000:]
+        command = " ".join(arguments)
+        super().__init__(f"docker compose {command} exited with {result.returncode}:\n{said}")
+
+
 def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
-    return subprocess.run(
+    result = subprocess.run(
         ["docker", "compose", "--project-name", PROJECT, *arguments],
         cwd=REPOSITORY_ROOT,
         env=ENVIRONMENT,
@@ -24,8 +38,11 @@ def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[
         text=True,
         encoding="utf-8",
         errors="replace",
-        check=check,
+        check=False,
     )
+    if check and result.returncode != 0:
+        raise ComposeFailed(arguments, result)
+    return result
 
 
 def run_in_backend(*arguments: str) -> subprocess.CompletedProcess[str]:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_support.py -q`
Expected: 9 passed.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: no finding, and 2819 passed, 1 skipped. `backend/.test-failures/` is there only if a setup failed, and Git does not see it.

- [ ] **Step 5: Commit**

```bash
git add .gitignore backend
git commit -m "test: what a failed setup said is kept, and a failed Compose command says why"
```

---

### Task 5: The UI follows

**Files:**
- Modify: `frontend/src/lib/repository-form.ts`, `frontend/src/screens/repository-settings.tsx`, `frontend/src/screens/system.tsx`, `frontend/src/screens/blob-stores.tsx`, `frontend/messages/en.json`
- Test: `frontend/src/lib/repository-form.test.ts`, `frontend/src/screens/administration.test.tsx`

**Interfaces:**
- Consumes: `components["schemas"]["HostedIn"]` (Task 1); `DEFAULT_BLOB_STORE` of `lib/repository-form.ts`.
- Produces: `Draft.deploymentPolicy: string | null` (null until one is chosen); `policyOf(draft: Pick<Draft, "format" | "versionPolicy" | "deploymentPolicy">): string`; the texts `system.baseUrlRule` (changed) and `blobStores.alwaysKept`.

- [ ] **Step 1: Write the failing tests**

Change `frontend/src/lib/repository-form.test.ts`:

```diff
@@ -14,6 +14,7 @@ import {
   EMPTY,
   hasMavenSettings,
   moved,
+  policyOf,
   problemsOf,
   updateBody,
   type Draft,
@@ -41,6 +42,40 @@ const stored = (change: Partial<RepositoryOut>): RepositoryOut => ({
   ...change,
 });
 
+describe("the deployment policy of a hosted repository (H1)", () => {
+  test.each([
+    // A release is deployed once: a Maven repository for releases refuses a second time.
+    [{ format: "maven", versionPolicy: "release" }, "disable_redeploy"],
+    // A snapshot is replaced by its nature, and a mixed repository takes snapshots.
+    [{ format: "maven", versionPolicy: "snapshot" }, "allow_redeploy"],
+    [{ format: "maven", versionPolicy: "mixed" }, "allow_redeploy"],
+    // The version policy is Maven's: of another format it says nothing.
+    [{ format: "npm", versionPolicy: "release" }, "allow_redeploy"],
+    [{ format: "raw", versionPolicy: "release" }, "allow_redeploy"],
+    [{ format: "docker", versionPolicy: "release" }, "allow_redeploy"],
+  ])("is the server's own until one is chosen: %o", (combination, policy) => {
+    expect(policyOf(draft(combination))).toBe(policy);
+    expect(createBody(draft(combination)).hosted).toEqual({ deployment_policy: policy });
+  });
+
+  test("is the one that was chosen, whatever the server would have given", () => {
+    const chosen = draft({ deploymentPolicy: "allow_redeploy" });
+
+    expect(policyOf(chosen)).toBe("allow_redeploy");
+    expect(policyOf({ ...chosen, versionPolicy: "snapshot" })).toBe("allow_redeploy");
+    expect(policyOf(draft({ format: "raw", deploymentPolicy: "read_only" }))).toBe("read_only");
+  });
+
+  test("of a repository that is there is the one the server holds", () => {
+    // Made before the rule, or by somebody who chose: it is not the form's to change.
+    const held = draftOf(stored({ hosted: { deployment_policy: "allow_redeploy" } }));
+
+    expect(held.deploymentPolicy).toBe("allow_redeploy");
+    expect(policyOf({ ...held, format: "maven", versionPolicy: "release" })).toBe("allow_redeploy");
+    expect(updateBody(held).hosted).toEqual({ deployment_policy: "allow_redeploy" });
+  });
+});
+
 describe("what is sent to make a repository", () => {
   test("a hosted Maven repository has its policies, and no part of another type", () => {
     expect(createBody(draft({ deploymentPolicy: "read_only", versionPolicy: "mixed" }))).toEqual({
```

Change `frontend/src/screens/administration.test.tsx`:

```diff
@@ -203,6 +203,46 @@ describe("a new repository (R2)", () => {
     expect(notices()).toHaveTextContent("Created the repository snapshots.");
   });
 
+  test("starts with the policy the server gives it, and follows the form until one is chosen (H1)", async () => {
+    const user = userEvent.setup();
+    const { calls } = fresh();
+    const policy = (name: string) => screen.getByRole("radio", { name });
+
+    // A Maven repository for releases: a release is deployed once.
+    expect(policy("Disable redeploy")).toBeChecked();
+    await user.click(screen.getByRole("radio", { name: "Snapshot" }));
+    expect(policy("Allow redeploy")).toBeChecked();
+    await user.click(screen.getByRole("radio", { name: "Release" }));
+    expect(policy("Disable redeploy")).toBeChecked();
+    await user.selectOptions(screen.getByLabelText("Format"), "npm");
+    expect(policy("Allow redeploy")).toBeChecked();
+
+    // Once chosen it is the person's, whatever the form then becomes.
+    await user.click(policy("Read only"));
+    await user.selectOptions(screen.getByLabelText("Format"), "maven");
+    expect(policy("Read only")).toBeChecked();
+
+    await user.type(screen.getByLabelText("Name"), "frozen");
+    await user.click(create());
+    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
+    expect(sent(calls).hosted).toEqual({ deployment_policy: "read_only" });
+  });
+
+  test("a Maven repository for releases is made refusing redeploy when nothing is chosen (H1)", async () => {
+    const user = userEvent.setup();
+    const { calls } = fresh();
+
+    await user.type(screen.getByLabelText("Name"), "releases");
+    await user.click(create());
+
+    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
+    expect(sent(calls)).toMatchObject({
+      format: "maven",
+      hosted: { deployment_policy: "disable_redeploy" },
+      format_config: { version_policy: "release", layout_policy: "strict" },
+    });
+  });
+
   test("grows with what the type has, and shows nothing of another type", async () => {
     const user = userEvent.setup();
     fresh();
@@ -940,19 +980,34 @@ describe("the blob stores (R10)", () => {
     await waitFor(() => expect(screen.getByRole("group", { name: "Blob stores" })).toHaveFocus());
   });
 
+  test("the default one is always kept, and is offered no button that would be refused (H7)", async () => {
+    stores();
+
+    const table = await screen.findByRole("table", { name: "Blob stores" });
+    const rows = within(table).getAllByRole("row").slice(1);
+
+    expect(within(rows[0] as HTMLElement).queryByRole("button")).toBeNull();
+    expect(rows[0]).toHaveTextContent("Always kept");
+    expect(
+      within(rows[1] as HTMLElement).getByRole("button", { name: "Delete fast" }),
+    ).toBeVisible();
+    expect(rows[1]).not.toHaveTextContent("Always kept");
+    await expectAccessible();
+  });
+
   test("is not deleted while a repository uses it, and the screen says which", async () => {
     const user = userEvent.setup();
     stores({
-      "DELETE /blob-stores/default": failure(
+      "DELETE /blob-stores/fast": failure(
         409,
         "in_use",
         "The repository releases uses this blob store.",
       ),
     });
 
-    await user.click(await screen.findByRole("button", { name: "Delete default" }));
+    await user.click(await screen.findByRole("button", { name: "Delete fast" }));
     const dialog = screen.getByRole("alertdialog");
-    await user.type(within(dialog).getByLabelText("Type default to go on"), "default");
+    await user.type(within(dialog).getByLabelText("Type fast to go on"), "fast");
     await user.click(within(dialog).getByRole("button", { name: "Delete blob store" }));
 
     expect(await screen.findByRole("alert")).toHaveTextContent(
@@ -1065,12 +1120,21 @@ describe("the system (R11)", () => {
     });
     await waitFor(() => expect(field()).toHaveValue(""));
 
-    await user.type(field(), "repo.example.org");
-    await user.click(screen.getByRole("button", { name: "Save" }));
-    expect(field()).toHaveAccessibleDescription(
-      "Give an http or https address, without a query or a fragment.",
-    );
-    expect(field()).toHaveFocus();
+    // No address, and addresses that would carry somebody's name to every client (H4).
+    for (const none of [
+      "repo.example.org",
+      "https://robot:secret@repo.example.org",
+      "https://robot@repo.example.org",
+      "https://@repo.example.org",
+    ]) {
+      await user.clear(field());
+      await user.type(field(), none);
+      await user.click(screen.getByRole("button", { name: "Save" }));
+      expect(field()).toHaveAccessibleDescription(
+        "Give an http or https address, without a user name, a password, a query or a fragment.",
+      );
+      expect(field()).toHaveFocus();
+    }
     expect(of(calls, "PUT")).toHaveLength(0);
 
     await user.clear(field());
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `frontend/`): `pnpm test`
Expected: 12 failed, 770 passed. `policyOf` is not there, the form starts as "Allow redeploy", `default` has a button, and the old rule is said of the base URL.

- [ ] **Step 3: Implement**

Change `frontend/messages/en.json`:

```diff
@@ -803,6 +803,7 @@
     "created": "Created the blob store {name}.",
     "delete": "Delete",
     "deleteNamed": "Delete {name}",
+    "alwaysKept": "Always kept",
     "deleteStore": "Delete blob store",
     "deleteAsk": "Delete the blob store {name}?",
     "deleteBody": "The server forgets the store. Its files stay on the disk, for you to remove. A store that a repository uses is not deleted.",
@@ -830,7 +831,7 @@
     "hints": {
       "baseUrl": "Used in every address the server gives out. Leave it empty to use the address each request came to. Set it when the server is behind a proxy that does not pass the address on."
     },
-    "baseUrlRule": "Give an http or https address, without a query or a fragment.",
+    "baseUrlRule": "Give an http or https address, without a user name, a password, a query or a fragment.",
     "saveBaseUrl": "Save",
     "baseUrlSaved": "The base URL is saved.",
     "baseUrlCleared": "The base URL is cleared.",
```

Change `frontend/src/lib/repository-form.ts`:

```diff
@@ -31,7 +31,8 @@ export type Draft = {
   type: RepositoryType;
   online: boolean;
   blobStore: string;
-  deploymentPolicy: string;
+  /** Null until one is chosen: the form then shows, and sends, the server's own (H1). */
+  deploymentPolicy: string | null;
   remoteUrl: string;
   contentMaxAge: string;
   metadataMaxAge: string;
@@ -57,7 +58,7 @@ export const EMPTY: Draft = {
   type: "hosted",
   online: true,
   blobStore: DEFAULT_BLOB_STORE,
-  deploymentPolicy: "allow_redeploy",
+  deploymentPolicy: null,
   remoteUrl: "",
   contentMaxAge: "1440",
   metadataMaxAge: "1440",
@@ -89,7 +90,7 @@ export function draftOf(repository: RepositoryOut): Draft {
       : "hosted",
     online: repository.online,
     blobStore: repository.blob_store ?? DEFAULT_BLOB_STORE,
-    deploymentPolicy: hosted?.deployment_policy ?? EMPTY.deploymentPolicy,
+    deploymentPolicy: hosted?.deployment_policy ?? null,
     remoteUrl: proxy?.remote_url ?? "",
     contentMaxAge: String(proxy?.content_max_age_minutes ?? EMPTY.contentMaxAge),
     metadataMaxAge: String(proxy?.metadata_max_age_minutes ?? EMPTY.metadataMaxAge),
@@ -106,6 +107,19 @@ export function draftOf(repository: RepositoryOut): Draft {
   };
 }
 
+/**
+ * The deployment policy of a hosted repository: the one that was chosen, or the one the
+ * server gives a repository that names none. A Maven repository for releases refuses to
+ * replace what was deployed (a release is deployed once); every other one allows it.
+ */
+export function policyOf(
+  draft: Pick<Draft, "format" | "versionPolicy" | "deploymentPolicy">,
+): string {
+  if (draft.deploymentPolicy !== null) return draft.deploymentPolicy;
+  const releases = draft.format === "maven" && draft.versionPolicy === "release";
+  return releases ? "disable_redeploy" : "allow_redeploy";
+}
+
 /** Whether a combination has settings of the format's own: a Maven repository that stores. */
 export function hasMavenSettings(draft: Pick<Draft, "format" | "type">): boolean {
   return draft.format === "maven" && draft.type !== "group";
@@ -184,8 +198,8 @@ function parts(draft: Draft) {
   const proxy = draft.type === "proxy";
   return {
     online: draft.online,
-    hosted:
-      draft.type === "hosted" ? { deployment_policy: draft.deploymentPolicy as "read_only" } : null,
+    // What the form shows is what is sent: the server is not left to choose again.
+    hosted: draft.type === "hosted" ? { deployment_policy: policyOf(draft) as "read_only" } : null,
     proxy: proxy
       ? {
           remote_url: draft.remoteUrl.trim(),
```

Change `frontend/src/screens/repository-settings.tsx`:

```diff
@@ -49,6 +49,7 @@ import {
   FORMATS,
   hasMavenSettings,
   LAYOUT_POLICIES,
+  policyOf,
   problemsOf,
   TYPES,
   updateBody,
@@ -212,7 +213,8 @@ function RepositoryForm({
             <legend className={LEGEND}>{t("sections.hosted")}</legend>
             <ChoiceGroup
               legend={t("fields.deploymentPolicy")}
-              value={draft.deploymentPolicy}
+              // Until one is chosen it follows the format and the version policy (H1).
+              value={policyOf(draft)}
               onChange={(value) => set({ deploymentPolicy: value })}
               options={option("policies", DEPLOYMENT_POLICIES)}
             />
```

Change `frontend/src/screens/system.tsx`:

```diff
@@ -23,12 +23,18 @@ import { BlobStoreTable } from "@/screens/blob-stores";
 
 const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
 
-/** Whether what was typed is an address the server takes for its own: http or https, and no more than a path. */
+/**
+ * Whether what was typed is an address the server takes for its own: http or https, no
+ * more than a path, and nobody's name or password, which every address the server
+ * gives out would then carry (H4).
+ */
 function isBaseUrl(typed: string): boolean {
   try {
     const url = new URL(typed);
     const web = url.protocol === "http:" || url.protocol === "https:";
-    return web && url.hostname !== "" && !url.search && !url.hash;
+    // The part between the slashes and the path: "user:password@host", or "@host".
+    const named = (typed.split("/")[2] ?? "").includes("@");
+    return web && url.hostname !== "" && !named && !url.search && !url.hash;
   } catch {
     return false;
   }
```

Change `frontend/src/screens/blob-stores.tsx`:

```diff
@@ -24,6 +24,7 @@ import type { BlobStoreOut } from "@/lib/api/types";
 import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
 import { formatBytes } from "@/lib/format";
 import { BLOB_STORES, isAddressable, pageHref, pageOf } from "@/lib/paths";
+import { DEFAULT_BLOB_STORE } from "@/lib/repository-form";
 import { refusalsOf } from "@/lib/refusals";
 import { allows } from "@/lib/session/rules";
 import { useSession } from "@/lib/session/session";
@@ -70,13 +71,18 @@ export function BlobStoreTable({
             </Td>
             {onDelete ? (
               <Td className="text-right">
-                <Button
-                  size="sm"
-                  aria-label={t("deleteNamed", { name: store.name })}
-                  onClick={() => onDelete(store)}
-                >
-                  {t("delete")}
-                </Button>
+                {store.name === DEFAULT_BLOB_STORE ? (
+                  // A repository that names no blob store is put in it: the server keeps it (H7).
+                  <span className="text-xs text-fg-subtle">{t("alwaysKept")}</span>
+                ) : (
+                  <Button
+                    size="sm"
+                    aria-label={t("deleteNamed", { name: store.name })}
+                    onClick={() => onDelete(store)}
+                  >
+                    {t("delete")}
+                  </Button>
+                )}
               </Td>
             ) : null}
           </tr>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `frontend/`): `pnpm test`
Expected: 782 passed in 26 files

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm build`
Expected: no finding, no type error, `Compiled successfully`.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): the policy a repository starts with, a base URL without credentials, the default blob store kept"
```

---

### Task 6: In a real browser, and the documents

**Files:**
- Modify: `frontend/e2e/ui.spec.ts`, `backend/tests/test_ui_client.py`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-13-release-readiness-design.md`

**Interfaces:**
- Consumes: everything Tasks 1 to 5 made, through the gateway of the Compose stack.
- Produces: 66 browser tests; `test_ui_client.py` expects all 66 and asks the gateway for one of the documentation page's files.

- [ ] **Step 1: Write the browser tests**

They make a Maven repository through the form with nothing chosen and deploy the same version to it twice, as a build would; they open the documentation page, whose every request the last test of the file looks at; and the blob store test no longer deletes `default`, which the list no longer offers.

Change `frontend/e2e/ui.spec.ts`:

```diff
@@ -20,6 +20,8 @@ const MADE = "browser-test-made";
 const MIRROR = "browser-test-mirror";
 const TOGETHER = "browser-test-together";
 const STORE = "browser-test-store";
+const ONCE = "browser-test-once";
+const STORED = "browser-test-stored";
 const REMOTE_SECRET = "the-remote-s-own-secret";
 // A name with what an address gives a meaning to: a space, a fragment, an escape.
 const ODD = "a b#c%.txt";
@@ -1364,12 +1366,25 @@ test("a blob store is made, listed with what it holds, and deleted when nothing
   await expect(list.getByRole("row", { name: new RegExp(STORE) })).toContainText("0 B");
   await expect(page.getByLabel("Name", { exact: true })).toHaveValue("");
 
-  // The one every repository uses is not deleted, and the screen says who uses it.
-  await page.getByRole("button", { name: "Delete default" }).click();
-  const refused = page.getByRole("alertdialog", { name: "Delete the blob store default?" });
-  await refused.getByLabel("Type default to go on").fill("default");
+  // The default one is always kept: a repository that names no blob store is put in it.
+  await expect(list.getByRole("row", { name: /default/ })).toContainText("Always kept");
+  await expect(page.getByRole("button", { name: "Delete default" })).toHaveCount(0);
+  const session = await (await page.request.get("/api/v1/auth/session")).json();
+  const token = { "X-CSRF-Token": session.csrf_token };
+  const kept = await page.request.delete("/api/v1/blob-stores/default", { headers: token });
+  expect(kept.status()).toBe(409);
+
+  // One that a repository uses is not deleted, and the screen says who uses it.
+  await createRepository({ name: STORED, format: "raw", type: "hosted", blob_store: STORE });
+  await page.getByRole("button", { name: `Delete ${STORE}` }).click();
+  const refused = page.getByRole("alertdialog", { name: `Delete the blob store ${STORE}?` });
+  await refused.getByLabel(`Type ${STORE} to go on`).fill(STORE);
   await refused.getByRole("button", { name: "Delete blob store" }).click();
-  await expect(page.getByRole("main").getByRole("alert")).toContainText("uses this blob store.");
+  await expect(page.getByRole("main").getByRole("alert")).toContainText(
+    `The repository ${STORED} uses this blob store.`,
+  );
+  const gone = await page.request.delete(`/api/v1/repositories/${STORED}`, { headers: token });
+  expect(gone.status()).toBe(204);
 
   await page.getByRole("button", { name: `Delete ${STORE}` }).click();
   const dialog = page.getByRole("alertdialog", { name: `Delete the blob store ${STORE}?` });
@@ -1434,6 +1449,54 @@ test("the system screen meets WCAG 2.1 AA in both modes", async () => {
   });
 });
 
+test("a Maven repository made for releases, with nothing chosen, takes a version once", async () => {
+  await page.goto("/admin/repositories/~new");
+  // The form starts as a hosted Maven repository for releases, and shows what the
+  // server gives one: a release is deployed once.
+  await expect(page.getByRole("radio", { name: "Disable redeploy" })).toBeChecked();
+  await page.getByRole("radio", { name: "Snapshot", exact: true }).check();
+  await expect(page.getByRole("radio", { name: "Allow redeploy" })).toBeChecked();
+  await page.getByRole("radio", { name: "Release", exact: true }).check();
+  await expect(page.getByRole("radio", { name: "Disable redeploy" })).toBeChecked();
+  await page.getByLabel("Name", { exact: true }).fill(ONCE);
+  await page.getByRole("button", { name: "Create repository" }).click();
+
+  await expect(page).toHaveURL(new RegExp(`/admin/repositories/${ONCE}$`));
+  await expect(page.getByRole("radio", { name: "Disable redeploy" })).toBeChecked();
+
+  // As a build would: the version is taken, and the same version is not taken again.
+  const session = await (await page.request.get("/api/v1/auth/session")).json();
+  const jar = `/repository/${ONCE}/org/example/app/1.0/app-1.0.jar`;
+  const deploy = (built: string) =>
+    page.request.put(jar, {
+      headers: { "X-CSRF-Token": session.csrf_token },
+      data: Buffer.from(built),
+    });
+  expect((await deploy("the release")).status()).toBe(201);
+  expect((await deploy("another build")).status()).toBe(409);
+  expect(await (await page.request.get(jar)).text()).toBe("the release");
+});
+
+test("the API's documentation is drawn from this server's own files", async () => {
+  // Every request of every test is looked at by the last one: none may go elsewhere.
+  const loaded: string[] = [];
+  const listen = (response: { url(): string }) => loaded.push(new URL(response.url()).pathname);
+  page.on("response", listen);
+  await page.goto("/api/docs");
+
+  await expect(page).toHaveTitle("MegooArti API");
+  // Drawn by its script from the API's own document: an operation of the API is there.
+  await expect(page.getByText("/api/v1/auth/session", { exact: true }).first()).toBeVisible();
+  page.off("response", listen);
+  expect(loaded).toEqual(
+    expect.arrayContaining([
+      "/api/docs/assets/swagger-ui-bundle.js",
+      "/api/docs/assets/swagger-ui.css",
+      "/api/v1/openapi.json",
+    ]),
+  );
+});
+
 test("an upload refused because the session was replaced in another tab goes through at the next try", async () => {
   await page.goto(`/upload/${REPOSITORY}`);
   await page.getByLabel("Files", { exact: true }).setInputFiles({
```

Change `backend/tests/test_ui_client.py`:

```diff
@@ -44,6 +44,7 @@ def get(path: str) -> tuple[int, str, str]:
     [
         ("/api/v1/status/ready", 200, "application/json", '"status":"ok"'),
         ("/api/docs", 200, "text/html", "swagger"),
+        ("/api/docs/assets/swagger-ui.css", 200, "text/css", ".swagger-ui"),
         ("/repository/no-such-repository/file", 404, "application/json", "not_found"),
         ("/v2/", 401, "application/json", "UNAUTHORIZED"),
         ("/login", 200, "text/html", "<html"),
@@ -51,7 +52,17 @@ def get(path: str) -> tuple[int, str, str]:
         ("/healthz", 200, "text/plain", "ok"),
         ("/no/such/screen", 404, "text/html", "<html"),
     ],
-    ids=["api", "api-docs", "repository", "registry", "sign-in", "home", "health", "nothing"],
+    ids=[
+        "api",
+        "api-docs",
+        "api-docs-files",
+        "repository",
+        "registry",
+        "sign-in",
+        "home",
+        "health",
+        "nothing",
+    ],
 )
 def test_the_gateway_sends_each_kind_of_address_to_its_place(stack, path, status, kind, said):
     answered, content_type, body = get(path)
@@ -99,7 +110,7 @@ def test_the_ui_in_a_real_browser(stack):
     assert result.returncode == 0, said
     passed = re.search(r"(\d+) passed", result.stdout)
     # As many as the file has: fewer would mean that some were left out without a word.
-    assert passed is not None and int(passed[1]) >= 64, said
+    assert passed is not None and int(passed[1]) >= 66, said
     assert not re.search(r"\d+ (failed|skipped|did not run)", result.stdout), said
 
 
```

- [ ] **Step 2: Run them against the Compose stack**

Run (in `backend/`): `uv run pytest -m docker tests/test_ui_client.py -q`
Expected: 12 passed. The stack is built from the working tree, so the backend's image has Swagger UI's files, and the 66 browser tests are among the twelve.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e backend/tests/test_ui_client.py
git commit -m "test: a release deployed once, and the documentation page, in a real browser"
```

- [ ] **Step 4: The documents**

Change `README.md`:

```diff
@@ -109,8 +109,12 @@ Users, roles, your own API tokens and anonymous access are managed in the web UI
   make only some repositories public, replace that role on the `anonymous` user with
   one of your own.
 - A request from a web page on another site that would change something is refused
-  with `403 cross_site_request`. If the server sits behind a reverse proxy on plain
-  HTTP, set the base URL under `/api/v1/settings` so its own pages are recognised.
+  with `403 cross_site_request`, signing in included. If the server sits behind a
+  reverse proxy on plain HTTP, set the base URL under `/api/v1/settings` so its own
+  pages are recognised.
+- **Your own password** is changed at `PUT /api/v1/me/password`, which asks for the
+  present one. `PUT /api/v1/users/{id}/password` sets another user's, and refuses
+  your own with `409 own_password`.
 - Five failed sign-ins for one username, or from one address, within 15 minutes block
   further attempts until the window ends. A valid API token is never refused by this
   limit. Behind a reverse proxy, set `MEGOOARTI_FORWARDED_ALLOW_IPS` to the proxy's
@@ -118,7 +122,8 @@ Users, roles, your own API tokens and anonymous access are managed in the web UI
 - Requests without credentials can only ever be allowed `repository:` permissions,
   whatever roles the `anonymous` user holds.
 
-The full API is described at `/api/docs`.
+The full API is described at `/api/docs`. The page is served with its own script and
+stylesheet, and asks nothing of another host.
 
 ## Repositories
 
@@ -146,8 +151,11 @@ In place of a password, use an API token as the password, or send it as
   (see what is there), `read` (download), `add` (a new path), `edit` (replace a path) or
   `delete`. For example `repository:raw:files:read`, or `repository:raw` for everything
   on every Raw repository.
-- **Deployment policy** per repository: `allow_redeploy` (default), `disable_redeploy`
-  (a path can be written once) or `read_only`.
+- **Deployment policy** per hosted repository: `allow_redeploy`, `disable_redeploy`
+  (a path can be written once) or `read_only`. A repository that is given none allows
+  redeploy, except a Maven repository for releases, which refuses it: a release is
+  deployed once.
+- **A name** is 1 to 64 letters, digits, `.`, `_` or `-`, and not `.` or `..`.
 - **Uploads are verified.** If the client sends `Content-Length`, or an
   `X-Checksum-Md5`, `X-Checksum-Sha1` or `X-Checksum-Sha256` header, the received bytes
   must match or nothing is stored. Downloads carry the same checksum headers.
@@ -936,7 +944,8 @@ repositories, blob stores and the installation's own settings.
     deletes the repository after you type its name.
   - **Blob stores** lists the stores with how many blobs each holds, their size and
     the space left, makes a new one, and deletes one that no repository uses. Its
-    files stay on the disk.
+    files stay on the disk. The store called `default` is always kept: a repository
+    that names no blob store is put in it.
   - **System** shows the version, the schema's revision and whether it is the one this
     version expects, when the server started and what it runs on, the database's
     version, and the blob stores. The base URL is set there.
```

Change `docs/superpowers/specs/2026-10-13-release-readiness-design.md`:

```diff
@@ -71,6 +71,19 @@ Each row is something a review found and set aside because it was the server's t
 - **Rebuilding an index is done in the request**, and the gateway waits ten minutes. It can be repeated: each piece is committed.
 - **What the gateway itself refuses is answered with nginx's own page.** In an installation the operator's proxy stands there.
 
+### Settled while building plan 11a
+
+| # | What | Why |
+| --- | --- | --- |
+| H9 | The policy of a repository that is given none is its format's to say (`Format.default_deployment_policy`), and the service asks it. | Every way a repository is made then gets it, not only the API. |
+| H10 | The form sends the policy it shows. It knows the server's rule (`policyOf`), and a table of the same cases is tested on each side. | A person should not send "whatever the server chooses" while looking at a choice. |
+| H11 | One's own password is refused at the administrator's endpoint for a token too. | The endpoint asks nobody who they are, however they came. |
+| H12 | A sign-in from another site is refused before the password is looked at, so it is not counted as a failed attempt. Signing out was refused already, by the guard every session has: a test now says so. | Counted, a page elsewhere could lock anybody's account by trying. |
+| H13 | Swagger UI 5.33.2 is kept in `backend/src/megooarti/static/swagger-ui` with its licence, its notice and its version, byte for byte (`.gitattributes`). The page loads three files by name through a route of the API; no folder is mounted. Swagger UI is told not to ask swagger.io to validate the document. | A mounted folder is one the test of route guards cannot see into. The validator is asked for any server that is not on localhost. |
+| H14 | In the list of blob stores, `default` has the words "Always kept" where the others have their button. | No button that the server would refuse (UI-2). |
+| H15 | H8 was not caught where it was looked for: 25 runs of the security tests passed. A setup or a teardown that fails now leaves what it said in `backend/.test-failures/` (the newest fifty are kept), whatever becomes of the run's output; and a Compose command that fails says what Docker said, where it said only that the exit status was not zero. | The next time it happens it has a text. While this plan was built the files caught the other failure nobody had read: `docker compose build` failing once for a whole module of client tests, with no reason given. |
+| H16 | The browser tests are 66: a Maven repository made by the form with nothing chosen refuses the second deploy, and the documentation page draws. The blob store test makes a repository in its own store to be refused, since `default` is no longer offered. | Section 4.2. |
+
 ### 4.1 API changes
 
 | Endpoint | Change |
@@ -90,7 +103,7 @@ The API's version does not change: nothing that worked for a client that did wha
 - Each row of 4.1 at the API, with the case just inside the rule and the one just outside it: a snapshot Maven repository and an npm one left as "allow redeploy"; a policy that is sent and kept; another user's password still set; a repository called `...` or `.a` still made; a base URL with a port and a path still taken; a sign-in from the same site, and one from a client that says nothing of where it is from (curl, a package client), still taken.
 - The UI: the default policy that follows the form and stops following once chosen; the base URL refused in the form; no delete button for `default`.
 - The browser suite: a Maven release repository made through the form refuses a second deploy of the same file.
-- The documentation page in a real browser, with every request to another host refused: it draws.
+- The documentation page in a real browser: it draws, and of every request the browser made, none went to another host.
 
 ## 5. Release mechanics (plan 11b)
 
```

- [ ] **Step 5: Everything, once more**

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: no finding, 782 passed in 26 files, `Compiled successfully`.

Run (in `backend/`): `uv run ruff check . && uv run pytest -q`
Expected: no finding, and 2819 passed, 1 skipped.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 36 passed. The Maven, npm, PyPI and Docker clients run against repositories made without a policy: none of them deploys a released version twice.

- [ ] **Step 6: Commit**

```bash
git add README.md docs
git commit -m "docs: what plan 11a changed in the API, and what it settled"
```
