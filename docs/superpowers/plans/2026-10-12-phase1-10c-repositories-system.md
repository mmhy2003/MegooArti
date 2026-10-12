# Repository and System Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator sets up the installation in the web UI: creates and changes repositories on one page that grows with the format and the type, sees a proxy's state, rebuilds an index, deletes a repository, keeps the blob stores, and sees what is running and sets the address the server gives out.

**Architecture:** One addition to the API, `GET /api/v1/system/information`, says what is running. Everything else uses the API of plans 3 to 7. The form of a repository is a module with no React in it: what a form starts with, what is wrong with it before the server is asked, and the body that is sent are functions of what the form holds, so that the parts each combination of format and type has are tested as a table of cases. The screens follow the rules plan 10b settled: a form opens on a fresh answer, every press puts the keyboard at what is wrong, a secret is kept nowhere.

**Tech Stack:** FastAPI and SQLAlchemy 2 (one endpoint); Next.js 16.4, React 19.3, TypeScript 5.9, Tailwind CSS 4.3, TanStack Query 5, `next-intl` 4; Vitest 5 with Testing Library and axe, Playwright. No new dependency.

**Spec:** [docs/superpowers/specs/2026-10-12-frontend-design.md](../specs/2026-10-12-frontend-design.md), section 12.4 (decisions R1 to R14 and the table of addresses), with S9 and S13 of 12.1, B11 of 12.2 and A20, A23 to A25 of 12.3. Business requirements: [docs/BRD.md](../../BRD.md) REP-1 to REP-6, PRX rows, GRP rows, BLB-1, BLB-4, SYS-4, UI-1 to UI-6. Task 6 amends the spec where this plan settles something it left open (R15 to R20).

**Read first:** `frontend/AGENTS.md`. The API these screens call is in `backend/src/megooarti/repositories/api.py` and `service.py` (what a repository's settings may be, and what is refused), `backend/src/megooarti/storage/api.py` and `blob_stores.py`, and `backend/src/megooarti/system/settings_api.py`. The README's sections on proxy and group repositories say what the settings do.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| R15 | The form of a repository is `lib/repository-form.ts`, with no React in it: `draftOf`, `problemsOf`, `createBody`, `updateBody`, `moved`. | The parts a combination has are a table of cases, tested without a screen. |
| R16 | A request that carried a proxy's secret is let go of by the store as soon as it is answered (`gcTime: 0`, and `reset()` after the answer), and the form starts again from the answer. | A20, for the one other secret the UI sends. |
| R17 | When a member of a group is moved, the keyboard stays on the button that moved it, or goes to the one beside it when it can move no further; what happened is said in a line a screen reader hears. | A row that moves takes its buttons with it (B11). |
| R18 | `useAttempts` gets `forget()`: a form that is sent and emptied to take another starts over. | Emptied, a blob store's name is no name, and the form said so at once. |
| R19 | The browser tests that find the navigation's "Repositories" name it exactly. | "Manage repositories" is in the same navigation. |
| R20 | The system page takes the blob stores' state from their own endpoint, for whoever may read them. | R12: another permission. |
| R21 | The texts of every screen of this plan are added to `messages/en.json` in Task 3, with the navigation's items. | One file, typed as a whole. |

## Global Constraints

- **A colour is written in `src/styles/tokens.css` and nowhere else.**
- **Text a person reads or hears is in `messages/en.json`.** A unit test fails on a text that is missing.
- **What comes from the API is text**: a proxy's last error, a name, a path. A name goes into an address through `lib/paths.ts`.
- **A secret is kept nowhere:** not in what was fetched, not in what the store keeps of a request, not in the page after it is saved, not in a log.
- **What a caller may not do is not offered** (UI-2); the server decides. A form whose data may be read and not changed is shown with its fields disabled and without the button that saves.
- **A form opens on an answer that came after its page did** (A23). **Every press of a form's button puts the keyboard at the first field that is wrong, and a list that turns a page takes the keyboard** (A24, `lib/focus.ts`). **When a screen changes under the keyboard, the keyboard is put at what changed** (B11).
- **What takes much with it is deleted only by whoever types its name** (S9): a repository, a blob store.
- **Formatting:** Prettier, 100 columns, LF; ESLint and `tsc` clean after every task. Backend: ruff clean, 100 columns, no test contacts a real network host except those marked `docker`.
- **This plan adds no dependency, no migration and no setting.** It adds one endpoint, which gives away nothing of the configuration.

**Working directories:** run `pnpm` commands in `frontend/`, `uv` and `pytest` commands in `backend/`, and `git` commands in the repository root. Backend tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **A form whose parts depend on two choices:** every combination of format and type; a part that was filled in and then hidden by another choice (a secret typed before "signs in with nothing", members of another format); what is sent for a part that is not there (Tasks 2 and 4).
2. **A proxy's secret:** typed on creation and on change, left empty to keep the stored one, asked for again by the server, in the store of requests, in the page after saving; a remote address with credentials in it (Tasks 2, 4 and 6).
3. **What cannot change, and what cannot be undone:** name, format, type, blob store, version policy; a repository a group presents; a blob store a repository uses; a group that would contain itself; a name that is taken, or is `new`, `.` or `..` (Tasks 2, 4 and 6).
4. **A caller who may read and not change, or one area and not another:** each screen read-only; the form of a new repository without the right to see blob stores; the system page without the right to see blob stores; the address of a form typed by hand (Tasks 3, 4).
5. **What the server says of itself:** a schema that is not the one this version expects, a database never migrated, a blob store whose space is not known, a proxy's last error that is markup (Tasks 1 and 4).

---

### Task 1: The API says what is running

**Files:**
- Create: `backend/src/megooarti/system/information_api.py`
- Modify: `backend/src/megooarti/main.py`
- Modify: `frontend/openapi.json` (written by the backend test), `frontend/src/lib/api/schema.d.ts` (written by `pnpm gen:api`)
- Test: `backend/tests/test_system_information.py`

**Interfaces:**
- Consumes: `require("admin:settings:read")`, `current_revision(connection)`, `app.state.head_revision`, `__version__`, `utcnow()`.
- Produces: `GET /api/v1/system/information` -> `{ version, schema: { revision, expected, current }, runtime: { python, platform, started_at }, database: { version } }`; `app.state.started_at`; in the frontend, `components["schemas"]["Information"]`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_system_information.py`:

```python
import platform
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from megooarti import __version__
from megooarti.db.schema import head_revision
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code

INFORMATION = "/api/v1/system/information"


async def test_reading_needs_the_permission_to_read_settings(client, make_user, db):
    await make_user("dana")
    await roles.create_role(db, "settings-readers", "", ["admin:settings:read"], [])
    await db.commit()
    await make_user("rae", roles=["settings-readers"])

    assert (await client.get(INFORMATION)).status_code == 401
    refused = await client.get(INFORMATION, headers=basic("dana", PASSWORD))
    assert (refused.status_code, error_code(refused)) == (403, "forbidden")
    assert (await client.get(INFORMATION, headers=basic("rae", PASSWORD))).status_code == 200


async def test_it_says_which_version_runs_and_on_what(admin_client):
    before = datetime.now(UTC)

    information = (await admin_client.get(INFORMATION)).json()

    assert information["version"] == __version__
    assert information["runtime"]["python"] == platform.python_version()
    assert information["runtime"]["platform"] == platform.platform()
    started = datetime.fromisoformat(information["runtime"]["started_at"])
    # The application of this test was made a moment ago, and not after it was asked.
    assert before - timedelta(minutes=10) < started <= datetime.now(UTC)
    assert re.match(r"PostgreSQL \d+", information["database"]["version"])
    assert set(information) == {"version", "schema", "runtime", "database"}


async def test_it_says_that_the_schema_is_the_one_this_version_expects(admin_client):
    schema = (await admin_client.get(INFORMATION)).json()["schema"]

    assert schema == {"revision": head_revision(), "expected": head_revision(), "current": True}


async def test_it_says_so_when_the_schema_is_another_one(admin_client, db):
    # As after an upgrade whose migrations were not run, or a downgrade of the image.
    await db.execute(text("UPDATE alembic_version SET version_num = 'an-older-one'"))
    await db.commit()
    try:
        schema = (await admin_client.get(INFORMATION)).json()["schema"]
    finally:
        await db.execute(
            text("UPDATE alembic_version SET version_num = :head"), {"head": head_revision()}
        )
        await db.commit()

    assert schema == {"revision": "an-older-one", "expected": head_revision(), "current": False}


async def test_it_gives_away_nothing_of_the_configuration(admin_client, app):
    response = await admin_client.get(INFORMATION)
    said = response.text

    assert response.status_code == 200
    # Not the address of the database, which has its password in it, nor a path.
    assert app.state.settings.database_url not in said
    assert "megooarti:megooarti" not in said
    assert str(app.state.settings.data_dir) not in said
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_system_information.py -q`
Expected: 5 failed. Each asks an address that is not there: `404`.

- [ ] **Step 3: Implement**

Create `backend/src/megooarti/system/information_api.py`:

```python
"""What is running here: the administrator's system page (SYS-4).

The health endpoints say yes or no to a load balancer. This says what: which version,
which schema, on what, since when. It says nothing of the configuration, which holds
the database's address and with it a password.
"""

import platform
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from megooarti import __version__
from megooarti.db.schema import current_revision
from megooarti.db.session import get_session
from megooarti.security.authentication import Principal, require

router = APIRouter(prefix="/system", tags=["system"])


class SchemaState(BaseModel):
    revision: str | None  # what the database says it is at; None if it was never migrated
    expected: str  # what this version was written for
    current: bool


class Runtime(BaseModel):
    python: str
    platform: str
    started_at: datetime


class Database(BaseModel):
    version: str


class Information(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str
    # `schema` is a name pydantic has a use for itself.
    schema_state: SchemaState = Field(alias="schema")
    runtime: Runtime
    database: Database


@router.get("/information", response_model=Information)
async def information(
    request: Request,
    _: Principal = Depends(require("admin:settings:read")),
    db: AsyncSession = Depends(get_session),
) -> Information:
    revision = await current_revision(await db.connection())
    expected = request.app.state.head_revision
    server = await db.scalar(text("SELECT current_setting('server_version')"))
    return Information(
        version=__version__,
        schema_state=SchemaState(
            revision=revision, expected=expected, current=revision == expected
        ),
        runtime=Runtime(
            python=platform.python_version(),
            platform=platform.platform(),
            started_at=request.app.state.started_at,
        ),
        database=Database(version=f"PostgreSQL {server}"),
    )
```

Change `backend/src/megooarti/main.py`:

```diff
@@ -33,6 +33,7 @@ from megooarti.security.api import users as users_api
 from megooarti.security.bootstrap import ensure_initial_admin_password
 from megooarti.storage import blobs
 from megooarti.storage.api import router as blob_stores_router
+from megooarti.system.information_api import router as information_router
 from megooarti.system.settings_api import router as settings_router
 from megooarti.system.status import router as status_router
 
@@ -129,6 +130,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     )
     app.state.sessionmaker = create_sessionmaker(app.state.engine)
     app.state.head_revision = head_revision()
+    app.state.started_at = utcnow()
     # The one client for requests to proxy remotes. Tests replace it with a fake remote.
     app.state.http = None  # built by remote.client_of on first use: it is slow to create
     register_error_handlers(app)
@@ -138,6 +140,7 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app.include_router(users_api.router, prefix=API_PREFIX)
     app.include_router(roles_api.router, prefix=API_PREFIX)
     app.include_router(settings_router, prefix=API_PREFIX)
+    app.include_router(information_router, prefix=API_PREFIX)
     app.include_router(blob_stores_router, prefix=API_PREFIX)
     app.include_router(repositories_router, prefix=API_PREFIX)
     app.include_router(content_api_router, prefix=API_PREFIX)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_system_information.py tests/test_route_guards.py -q`
Expected: 9 passed. The new route authenticates, so the walk over every route finds nothing unguarded.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check .`
Expected: no finding.

- [ ] **Step 5: Write the copy of the API document, and the types from it**

Run (in `backend/`): `uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 failed: the copy in `frontend/openapi.json` is out of date.

Run (in `backend/`): `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py -q`
Expected: 1 passed.

Run (in `frontend/`): `pnpm gen:api`
Expected: `openapi.json → src/lib/api/schema.d.ts`.

Run (in `frontend/`): `pnpm test`
Expected: 675 passed in 23 files. The test that holds the types to the document passes.

- [ ] **Step 6: Commit**

```bash
git add backend frontend/openapi.json frontend/src/lib/api/schema.d.ts
git commit -m "feat(api): system information: version, schema, runtime and database"
```

---

### Task 2: The form of a repository, and the requests of the screens

**Files:**
- Create: `frontend/src/lib/repository-form.ts`, `frontend/src/lib/administration.ts`
- Modify: `frontend/src/lib/api/types.ts`, `frontend/src/lib/paths.ts`, `frontend/src/lib/security.ts`, `frontend/src/lib/focus.ts`
- Test: `frontend/src/lib/repository-form.test.ts`
- Test (modify): `frontend/src/screens/upload.test.tsx`

**Interfaces:**
- Consumes: `api` of `lib/api/client.ts`; `isAddressable` and `one` of `lib/paths.ts`; the generated types of Task 1.
- Produces:
  - `lib/repository-form.ts`: `FORMATS`, `TYPES`, `RepositoryType`, `DEPLOYMENT_POLICIES`, `AUTH_TYPES`, `VERSION_POLICIES`, `LAYOUT_POLICIES`, `DEFAULT_BLOB_STORE`, `Draft`, `EMPTY`, `draftOf(repository)`, `hasMavenSettings(draft)`, `Problem`, `Problems`, `problemsOf(draft, creating)`, `createBody(draft)`, `updateBody(draft)`, `moved(members, name, by)`.
  - `lib/administration.ts`: `AT_ONCE`, `useManagedRepositories(page)`, `useEveryManagedRepository()`, `useManagedRepository(name | null)`, `useCreateRepository()`, `useUpdateRepository(name)`, `useDeleteRepository()`, `useInvalidateCache(name)`, `useRebuildIndex(name)`, `useBlobStores(page)`, `useEveryBlobStore(enabled?)`, `useCreateBlobStore()`, `useDeleteBlobStore()`, `useInformation()`, `useSetBaseUrl()`.
  - `lib/paths.ts`: `MANAGE_REPOSITORIES`, `NEW_REPOSITORY` (`/admin/repositories/~new`), `BLOB_STORES`, `SYSTEM`, `repositorySettingsHref(name)`, `parseRepositorySettings(pathname) -> { name } | null`.
  - `lib/api/types.ts`: `RepositoryOut`, `RepositoryCreate`, `RepositoryUpdate`, `ProxyStatus`, `IndexRebuilt`, `BlobStoreOut`, `BlobStoreCreate`, `Information`.
  - `lib/security.ts`: `SETTINGS_KEY`. `lib/focus.ts`: `useAttempts(...)` also returns `forget()`.
- The change to `upload.test.tsx` is to a test of plan 10a that failed once on a busy machine: it looked where the keyboard was before the refusal had been drawn. It now waits for it.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/repository-form.test.ts`:

```ts
import { describe, expect, test } from "vitest";

import type { RepositoryOut } from "@/lib/api/types";
import {
  MANAGE_REPOSITORIES,
  NEW_REPOSITORY,
  parseRepositorySettings,
  repositorySettingsHref,
} from "@/lib/paths";

import {
  createBody,
  draftOf,
  EMPTY,
  hasMavenSettings,
  moved,
  problemsOf,
  updateBody,
  type Draft,
} from "./repository-form";

const draft = (change: Partial<Draft>): Draft => ({ ...EMPTY, name: "releases", ...change });
const PROXY = draft({
  name: "central",
  type: "proxy",
  remoteUrl: " https://repo.example.org/maven2/ ",
});

const stored = (change: Partial<RepositoryOut>): RepositoryOut => ({
  name: "releases",
  format: "maven",
  type: "hosted",
  online: true,
  blob_store: "default",
  url_path: "/repository/releases/",
  hosted: { deployment_policy: "disable_redeploy" },
  format_config: { version_policy: "snapshot", layout_policy: "permissive" },
  proxy: null,
  group: null,
  status: null,
  ...change,
});

describe("what is sent to make a repository", () => {
  test("a hosted Maven repository has its policies, and no part of another type", () => {
    expect(createBody(draft({ deploymentPolicy: "read_only", versionPolicy: "mixed" }))).toEqual({
      name: "releases",
      format: "maven",
      type: "hosted",
      online: true,
      blob_store: "default",
      hosted: { deployment_policy: "read_only" },
      proxy: null,
      group: null,
      format_config: { version_policy: "mixed", layout_policy: "strict" },
    });
  });

  test("a proxy has its remote, how long it trusts what it cached, and how it signs in", () => {
    const body = createBody({
      ...PROXY,
      contentMaxAge: "-1",
      metadataMaxAge: " 60 ",
      negativeCache: false,
      negativeCacheTtl: "5",
      authType: "basic",
      authUsername: " robot ",
      authSecret: "the secret ",
      blocked: true,
      autoBlock: false,
    });

    expect(body.hosted).toBeNull();
    expect(body.proxy).toEqual({
      remote_url: "https://repo.example.org/maven2/",
      content_max_age_minutes: -1,
      metadata_max_age_minutes: 60,
      negative_cache: { enabled: false, ttl_minutes: 5 },
      // The secret as it was typed: a space at its end may be part of it.
      remote_auth: { type: "basic", username: "robot", secret: "the secret " },
      blocked: true,
      auto_block: false,
    });
  });

  test("a secret that is not typed is not sent, so that the one that is stored is kept", () => {
    const kept = updateBody({ ...PROXY, authType: "bearer", authSecret: "", hasSecret: true });
    expect(kept.proxy?.remote_auth).toEqual({ type: "bearer", username: "", secret: null });

    // And a proxy that signs in with nothing sends neither a name nor a secret that was
    // typed before the choice was changed.
    const none = updateBody({ ...PROXY, authType: "none", authUsername: "x", authSecret: "y" });
    expect(none.proxy?.remote_auth).toEqual({ type: "none", username: "", secret: null });
  });

  test("a group has its members in order, and neither a blob store nor settings of the format", () => {
    const body = createBody(draft({ name: "all", type: "group", members: ["b", "a"] }));

    expect(body.group).toEqual({ members: ["b", "a"] });
    expect(body.blob_store).toBeNull(); // it stores nothing
    expect(body.format_config).toEqual({}); // a Maven group has no policy of its own
    expect([body.hosted, body.proxy]).toEqual([null, null]);
  });

  test("another format than Maven has no settings of its own", () => {
    expect(createBody(draft({ format: "npm" })).format_config).toEqual({});
    expect(hasMavenSettings({ format: "maven", type: "proxy" })).toBe(true);
    expect(hasMavenSettings({ format: "maven", type: "group" })).toBe(false);
    expect(hasMavenSettings({ format: "raw", type: "hosted" })).toBe(false);
  });

  test("what cannot change is not sent when a repository is changed", () => {
    const body = updateBody(draft({ online: false }));

    expect(Object.keys(body).sort()).toEqual([
      "format_config",
      "group",
      "hosted",
      "online",
      "proxy",
    ]);
    expect(body.online).toBe(false);
  });
});

describe("the form of a repository that is there", () => {
  test("starts from what the server holds", () => {
    const form = draftOf(stored({}));

    expect(form).toMatchObject({
      name: "releases",
      format: "maven",
      type: "hosted",
      deploymentPolicy: "disable_redeploy",
      versionPolicy: "snapshot",
      layoutPolicy: "permissive",
      blobStore: "default",
    });
  });

  test("of a proxy has everything but the secret, and knows that one is stored", () => {
    const form = draftOf(
      stored({
        type: "proxy",
        hosted: null,
        proxy: {
          remote_url: "https://repo.example.org/maven2",
          content_max_age_minutes: -1,
          metadata_max_age_minutes: 30,
          negative_cache: { enabled: false, ttl_minutes: 10 },
          remote_auth: { type: "basic", username: "robot", has_secret: true },
          blocked: true,
          auto_block: false,
        },
      }),
    );

    expect(form).toMatchObject({
      type: "proxy",
      remoteUrl: "https://repo.example.org/maven2",
      contentMaxAge: "-1",
      metadataMaxAge: "30",
      negativeCache: false,
      negativeCacheTtl: "10",
      authType: "basic",
      authUsername: "robot",
      authSecret: "",
      hasSecret: true,
      blocked: true,
      autoBlock: false,
    });
    // Saved as it stands, it keeps the secret and changes nothing.
    expect(updateBody(form).proxy).toMatchObject({
      remote_url: "https://repo.example.org/maven2",
      content_max_age_minutes: -1,
      remote_auth: { type: "basic", username: "robot", secret: null },
    });
  });

  test("of a group has its members, and of a format without settings none", () => {
    const form = draftOf(
      stored({
        type: "group",
        format: "raw",
        hosted: null,
        format_config: {},
        group: { members: ["a", "b"] },
        blob_store: null,
      }),
    );

    expect(form.members).toEqual(["a", "b"]);
    expect(form.layoutPolicy).toBe("strict"); // not shown, and not sent
    expect(updateBody(form)).toMatchObject({ group: { members: ["a", "b"] }, format_config: {} });
  });

  test("takes a type it does not know for what it shows no parts of", () => {
    expect(draftOf(stored({ type: "mirror" })).type).toBe("hosted");
  });
});

describe("what is wrong with a form before the server is asked", () => {
  test("nothing, with a hosted repository that has a name", () => {
    expect(problemsOf(draft({}), true)).toEqual({});
  });

  test.each([
    ["", "nameRule"],
    ["has space", "nameRule"],
    ["a/b", "nameRule"],
    ["x".repeat(65), "nameRule"],
    [".", "nameDots"],
    ["..", "nameDots"],
  ])("a name %j: %s", (name, problem) => {
    expect(problemsOf(draft({ name }), true).name).toBe(problem);
  });

  test("a name is not the form's to check once the repository is there", () => {
    expect(problemsOf(draft({ name: ".." }), false)).toEqual({});
  });

  test("a Docker repository is named as the first part of an image's name", () => {
    const docker = (name: string) => problemsOf(draft({ format: "docker", name }), true).name;

    expect(docker("images")).toBeUndefined();
    expect(docker("team-1.images_x")).toBeUndefined();
    expect(docker("Images")).toBe("dockerNameRule");
    expect(docker("images-")).toBe("dockerNameRule");
    expect(docker("my..images")).toBe("dockerNameRule");
    // The same name is a good one for another format.
    expect(problemsOf(draft({ format: "raw", name: "Images" }), true)).toEqual({});
  });

  test.each([
    "",
    "repo.example.org",
    "ftp://repo.example.org",
    "https://",
    "https://user:secret@repo.example.org",
    "https://repo.example.org/?a=1",
    "https://repo.example.org/#x",
    "javascript:alert(1)",
  ])("a remote address %j is none", (remoteUrl) => {
    expect(problemsOf({ ...PROXY, remoteUrl }, true).remoteUrl).toBe("remoteRule");
  });

  test("how long a proxy trusts what it cached is a whole number, from -1", () => {
    const ages = (contentMaxAge: string, metadataMaxAge: string) =>
      problemsOf({ ...PROXY, contentMaxAge, metadataMaxAge }, true);

    expect(ages("-1", "0")).toEqual({});
    expect(ages("-2", "1.5")).toMatchObject({
      contentMaxAge: "ageRule",
      metadataMaxAge: "ageRule",
    });
    expect(ages("", "ten").contentMaxAge).toBe("ageRule");
    expect(ages("99999999999999999999", "1").contentMaxAge).toBe("ageRule");
  });

  test("how long a missing path is remembered is at least a minute, when it is remembered at all", () => {
    expect(problemsOf({ ...PROXY, negativeCacheTtl: "0" }, true).negativeCacheTtl).toBe("ttlRule");
    expect(problemsOf({ ...PROXY, negativeCache: false, negativeCacheTtl: "0" }, true)).toEqual({});
  });

  test("a proxy that signs in needs what it signs in with, unless a secret is stored", () => {
    const basic = { ...PROXY, authType: "basic" };

    expect(problemsOf(basic, true)).toEqual({
      authUsername: "usernameNeeded",
      authSecret: "secretNeeded",
    });
    expect(problemsOf({ ...basic, authUsername: "robot", hasSecret: true }, false)).toEqual({});
    expect(problemsOf({ ...PROXY, authType: "bearer" }, true)).toEqual({
      authSecret: "secretNeeded",
    });
    expect(problemsOf({ ...PROXY, authType: "bearer", authSecret: "t" }, true)).toEqual({});
  });

  test("what a hosted repository or a group does not have is not checked", () => {
    expect(problemsOf(draft({ remoteUrl: "nonsense", contentMaxAge: "x" }), true)).toEqual({});
    expect(problemsOf(draft({ type: "group", remoteUrl: "" }), true)).toEqual({});
  });
});

describe("the order of a group's members", () => {
  test("a member moves one place up or down", () => {
    expect(moved(["a", "b", "c"], "c", -1)).toEqual(["a", "c", "b"]);
    expect(moved(["a", "b", "c"], "a", 1)).toEqual(["b", "a", "c"]);
  });

  test("the first does not move up, the last not down, and what is no member not at all", () => {
    const members = ["a", "b"];

    expect(moved(members, "a", -1)).toBe(members);
    expect(moved(members, "b", 1)).toBe(members);
    expect(moved(members, "z", 1)).toBe(members);
  });
});

describe("the addresses of a repository's settings", () => {
  test("are under the list, with the name as one segment", () => {
    expect(repositorySettingsHref("releases")).toBe("/admin/repositories/releases");
    expect(repositorySettingsHref("odd name#")).toBe("/admin/repositories/odd%20name%23");
    expect(parseRepositorySettings("/admin/repositories/odd%20name%23")).toEqual({
      name: "odd name#",
    });
    expect(parseRepositorySettings(MANAGE_REPOSITORIES)).toBeNull();
    expect(parseRepositorySettings("/admin/repositories/a/b")).toBeNull();
  });

  test("the form for a new one is where no repository's name can be", () => {
    expect(NEW_REPOSITORY).toBe("/admin/repositories/~new");
    // A repository may be called "new", and its settings are then its own page.
    expect(repositorySettingsHref("new")).toBe("/admin/repositories/new");
  });
});
```

Change `frontend/src/screens/upload.test.tsx`:

```diff
@@ -286,8 +286,9 @@ describe("uploading to a Maven repository", () => {
     );
     expect(screen.queryByRole("alert", { name: /refused/ })).toBeNull();
     // The first field that is wrong gets the keyboard: a screen reader then reads the
-    // field and what is wrong with it. An error that only appears is not heard.
-    expect(screen.getByLabelText(/^Version/)).toHaveFocus();
+    // field and what is wrong with it. An error that only appears is not heard. (It is
+    // given once the refusal is drawn, which on a busy machine is a moment after.)
+    await waitFor(() => expect(screen.getByLabelText(/^Version/)).toHaveFocus());
   });
 });
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import "./repository-form"` from `src/lib/repository-form.test.ts`. The other 675 tests pass.

- [ ] **Step 3: Implement**

Change `frontend/src/lib/api/types.ts`:

```diff
@@ -30,6 +30,16 @@ export type RoleOut = Schemas["RoleOut"];
 export type RoleCreate = Schemas["RoleCreate"];
 export type RoleContent = Schemas["RoleContent"];
 export type SettingsOut = Schemas["SettingsOut"];
+/** A repository as an administrator sees it: how it is set up, and a proxy's state. */
+export type RepositoryOut = Schemas["RepositoryOut"];
+export type RepositoryCreate = Schemas["RepositoryCreate"];
+export type RepositoryUpdate = Schemas["RepositoryUpdate"];
+export type ProxyStatus = Schemas["ProxyStatus"];
+export type IndexRebuilt = Schemas["IndexRebuilt"];
+export type BlobStoreOut = Schemas["BlobStoreOut"];
+export type BlobStoreCreate = Schemas["BlobStoreCreate"];
+/** What is running: version, schema, runtime, database. */
+export type Information = Schemas["Information"];
 
 /** A page of a list, as every list endpoint answers. */
 export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
```

Change `frontend/src/lib/paths.ts`:

```diff
@@ -20,6 +20,11 @@ export const ROLES = "/admin/roles" as Route;
 // Where no role's name can be: a role may be called "new", and has `~` in no name.
 export const NEW_ROLE = "/admin/roles/~new" as Route;
 export const ANONYMOUS_ACCESS = "/admin/anonymous-access" as Route;
+export const MANAGE_REPOSITORIES = "/admin/repositories" as Route;
+// As for a role: a repository may be called "new", and has `~` in no name.
+export const NEW_REPOSITORY = "/admin/repositories/~new" as Route;
+export const BLOB_STORES = "/admin/blob-stores" as Route;
+export const SYSTEM = "/admin/system" as Route;
 
 const segments = (path: string) => path.split("/").filter((segment) => segment !== "");
 const encoded = (path: string) => segments(path).map(encodeURIComponent).join("/");
@@ -141,6 +146,11 @@ export function parseUpload(pathname: string): { repository: string } | null {
   return found?.length === 1 && repository ? { repository } : null;
 }
 
+/** The settings of a repository, as an administrator sees them. */
+export function repositorySettingsHref(name: string): Route {
+  return `${MANAGE_REPOSITORIES}/${encodeURIComponent(name)}` as Route;
+}
+
 /** The one thing an address under a list names: a user's id, a role's name. Null if none. */
 function one(pathname: string, list: string): string | null {
   const found = after(pathname, list);
@@ -158,3 +168,9 @@ export function parseRole(pathname: string): { name: string } | null {
   const name = one(pathname, ROLES);
   return name === null ? null : { name };
 }
+
+/** The repository whose settings an address is about. */
+export function parseRepositorySettings(pathname: string): { name: string } | null {
+  const name = one(pathname, MANAGE_REPOSITORIES);
+  return name === null ? null : { name };
+}
```

Change `frontend/src/lib/security.ts`:

```diff
@@ -33,6 +33,8 @@ const TOKENS = "tokens";
 const USERS = "users";
 const ROLES = "roles";
 const SETTINGS = "settings";
+/** Where the settings are kept among what was fetched: whoever changes one puts the answer there. */
+export const SETTINGS_KEY = [SETTINGS] as const;
 
 const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
 const user = (id: string) => `/users/${encodeURIComponent(id)}`;
```

Change `frontend/src/lib/focus.ts`:

```diff
@@ -24,13 +24,20 @@ export function useAttempts(refused: unknown): {
   form: RefObject<HTMLFormElement | null>;
   tried: boolean;
   attempt: () => void;
+  /** The form starts over, as after it was sent and emptied: nothing is wrong with it yet. */
+  forget: () => void;
 } {
   const form = useRef<HTMLFormElement>(null);
   const [attempts, setAttempts] = useState(0);
   useEffect(() => {
     if (attempts > 0) form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
   }, [attempts, refused]);
-  return { form, tried: attempts > 0, attempt: () => setAttempts((made) => made + 1) };
+  return {
+    form,
+    tried: attempts > 0,
+    attempt: () => setAttempts((made) => made + 1),
+    forget: () => setAttempts(0),
+  };
 }
 
 /**
```

Create `frontend/src/lib/repository-form.ts`:

```ts
/**
 * A repository as a form holds it, and as the API takes it. No React here.
 *
 * The form is one page that grows (S13): what it shows follows from the format and the
 * type. This module says which parts a combination has, what a form starts with, what
 * is wrong with it before the server is asked, and the body that is sent.
 */
import type { RepositoryCreate, RepositoryOut, RepositoryUpdate } from "@/lib/api/types";
import { isAddressable } from "@/lib/paths";

/** The formats the server has. Each can be hosted, a proxy or a group. */
export const FORMATS = ["raw", "maven", "npm", "pypi", "docker"] as const;
export const TYPES = ["hosted", "proxy", "group"] as const;
export type RepositoryType = (typeof TYPES)[number];
export const DEPLOYMENT_POLICIES = ["allow_redeploy", "disable_redeploy", "read_only"] as const;
export const AUTH_TYPES = ["none", "basic", "bearer"] as const;
export const VERSION_POLICIES = ["release", "snapshot", "mixed"] as const;
export const LAYOUT_POLICIES = ["strict", "permissive"] as const;
/** The blob store a repository gets when none is chosen. */
export const DEFAULT_BLOB_STORE = "default";

// The server's rule for a name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
// A Docker repository's name is the first part of its images' names.
const DOCKER_NAME = /^[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*$/;

/** What the form holds. Numbers are text while they are typed. */
export type Draft = {
  name: string;
  format: string;
  type: RepositoryType;
  online: boolean;
  blobStore: string;
  deploymentPolicy: string;
  remoteUrl: string;
  contentMaxAge: string;
  metadataMaxAge: string;
  negativeCache: boolean;
  negativeCacheTtl: string;
  authType: string;
  authUsername: string;
  /** Typed now. Empty keeps the one that is stored, if there is one. */
  authSecret: string;
  /** Whether the server holds a secret for this proxy already. */
  hasSecret: boolean;
  blocked: boolean;
  autoBlock: boolean;
  members: string[];
  versionPolicy: string;
  layoutPolicy: string;
};

/** A form for a repository that is not there yet: the server's own defaults. */
export const EMPTY: Draft = {
  name: "",
  format: "maven",
  type: "hosted",
  online: true,
  blobStore: DEFAULT_BLOB_STORE,
  deploymentPolicy: "allow_redeploy",
  remoteUrl: "",
  contentMaxAge: "1440",
  metadataMaxAge: "1440",
  negativeCache: true,
  negativeCacheTtl: "1440",
  authType: "none",
  authUsername: "",
  authSecret: "",
  hasSecret: false,
  blocked: false,
  autoBlock: true,
  members: [],
  versionPolicy: "release",
  layoutPolicy: "strict",
};

const text = (value: unknown, otherwise: string): string =>
  typeof value === "string" ? value : otherwise;

/** The form of a repository as the server holds it. */
export function draftOf(repository: RepositoryOut): Draft {
  const { proxy, hosted, group, format_config: config } = repository;
  return {
    ...EMPTY,
    name: repository.name,
    format: repository.format,
    type: (TYPES as readonly string[]).includes(repository.type)
      ? (repository.type as RepositoryType)
      : "hosted",
    online: repository.online,
    blobStore: repository.blob_store ?? DEFAULT_BLOB_STORE,
    deploymentPolicy: hosted?.deployment_policy ?? EMPTY.deploymentPolicy,
    remoteUrl: proxy?.remote_url ?? "",
    contentMaxAge: String(proxy?.content_max_age_minutes ?? EMPTY.contentMaxAge),
    metadataMaxAge: String(proxy?.metadata_max_age_minutes ?? EMPTY.metadataMaxAge),
    negativeCache: proxy?.negative_cache.enabled ?? true,
    negativeCacheTtl: String(proxy?.negative_cache.ttl_minutes ?? EMPTY.negativeCacheTtl),
    authType: proxy?.remote_auth.type ?? "none",
    authUsername: proxy?.remote_auth.username ?? "",
    hasSecret: proxy?.remote_auth.has_secret ?? false,
    blocked: proxy?.blocked ?? false,
    autoBlock: proxy?.auto_block ?? true,
    members: group?.members ?? [],
    versionPolicy: text(config.version_policy, EMPTY.versionPolicy),
    layoutPolicy: text(config.layout_policy, EMPTY.layoutPolicy),
  };
}

/** Whether a combination has settings of the format's own: a Maven repository that stores. */
export function hasMavenSettings(draft: Pick<Draft, "format" | "type">): boolean {
  return draft.format === "maven" && draft.type !== "group";
}

/** A whole number of at least `minimum`, or null for what is none. */
function whole(typed: string, minimum: number): number | null {
  if (!/^-?\d{1,9}$/.test(typed.trim())) return null;
  const value = Number(typed.trim());
  return value >= minimum ? value : null;
}

function isRemote(typed: string): boolean {
  try {
    const url = new URL(typed.trim());
    const web = url.protocol === "http:" || url.protocol === "https:";
    return web && url.hostname !== "" && !url.username && !url.password && !url.search && !url.hash;
  } catch {
    return false;
  }
}

/** What can be wrong before the server is asked, by the name of the message that says it. */
export type Problem =
  | "nameRule"
  | "nameDots"
  | "dockerNameRule"
  | "remoteRule"
  | "ageRule"
  | "ttlRule"
  | "usernameNeeded"
  | "secretNeeded";

export type Problems = Partial<
  Record<
    | "name"
    | "remoteUrl"
    | "contentMaxAge"
    | "metadataMaxAge"
    | "negativeCacheTtl"
    | "authUsername"
    | "authSecret",
    Problem
  >
>;

/** `creating` is false for a repository that is there: its name is then not the form's to check. */
export function problemsOf(draft: Draft, creating: boolean): Problems {
  const problems: Problems = {};
  if (creating) {
    if (!NAME.test(draft.name)) problems.name = "nameRule";
    else if (!isAddressable(draft.name)) problems.name = "nameDots";
    else if (draft.format === "docker" && !DOCKER_NAME.test(draft.name)) {
      problems.name = "dockerNameRule";
    }
  }
  if (draft.type === "proxy") {
    if (!isRemote(draft.remoteUrl)) problems.remoteUrl = "remoteRule";
    if (whole(draft.contentMaxAge, -1) === null) problems.contentMaxAge = "ageRule";
    if (whole(draft.metadataMaxAge, -1) === null) problems.metadataMaxAge = "ageRule";
    if (draft.negativeCache && whole(draft.negativeCacheTtl, 1) === null) {
      problems.negativeCacheTtl = "ttlRule";
    }
    if (draft.authType === "basic" && draft.authUsername.trim() === "") {
      problems.authUsername = "usernameNeeded";
    }
    if (draft.authType !== "none" && draft.authSecret === "" && !draft.hasSecret) {
      problems.authSecret = "secretNeeded";
    }
  }
  return problems;
}

/** The parts of a body that follow from the type. The others are null: there are none. */
function parts(draft: Draft) {
  const proxy = draft.type === "proxy";
  return {
    online: draft.online,
    hosted:
      draft.type === "hosted" ? { deployment_policy: draft.deploymentPolicy as "read_only" } : null,
    proxy: proxy
      ? {
          remote_url: draft.remoteUrl.trim(),
          content_max_age_minutes: whole(draft.contentMaxAge, -1) ?? 1440,
          metadata_max_age_minutes: whole(draft.metadataMaxAge, -1) ?? 1440,
          negative_cache: {
            enabled: draft.negativeCache,
            // Kept as it was while the cache is off, so that turning it on again finds it.
            ttl_minutes: whole(draft.negativeCacheTtl, 1) ?? 1440,
          },
          remote_auth:
            draft.authType === "none"
              ? { type: "none" as const, username: "", secret: null }
              : {
                  type: draft.authType as "basic",
                  username: draft.authType === "basic" ? draft.authUsername.trim() : "",
                  // Not sent, the one that is stored is kept.
                  secret: draft.authSecret === "" ? null : draft.authSecret,
                },
          blocked: draft.blocked,
          auto_block: draft.autoBlock,
        }
      : null,
    group: draft.type === "group" ? { members: draft.members } : null,
    format_config: hasMavenSettings(draft)
      ? { version_policy: draft.versionPolicy, layout_policy: draft.layoutPolicy }
      : {},
  };
}

/** What is sent to make a repository. A group stores nothing, and so names no blob store. */
export function createBody(draft: Draft): RepositoryCreate {
  return {
    name: draft.name,
    format: draft.format,
    type: draft.type,
    blob_store: draft.type === "group" ? null : draft.blobStore || DEFAULT_BLOB_STORE,
    ...parts(draft),
  };
}

/** What is sent to change one. What cannot change is not sent. */
export function updateBody(draft: Draft): RepositoryUpdate {
  return parts(draft);
}

/** A member, moved one place up (-1) or down (1). The list as it was if that is nowhere. */
export function moved(members: string[], name: string, by: -1 | 1): string[] {
  const from = members.indexOf(name);
  const to = from + by;
  if (from < 0 || to < 0 || to >= members.length) return members;
  const next = [...members];
  [next[from], next[to]] = [next[to] as string, next[from] as string];
  return next;
}
```

Create `frontend/src/lib/administration.ts`:

```ts
"use client";

/**
 * What an administrator keeps besides people, asked of the API: the repositories as
 * they are set up, the blob stores, and the installation itself.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type {
  BlobStoreCreate,
  BlobStoreOut,
  IndexRebuilt,
  Information,
  Page,
  RepositoryCreate,
  RepositoryOut,
  RepositoryUpdate,
  SettingsOut,
} from "@/lib/api/types";
import { SETTINGS_KEY } from "@/lib/security";

// As many of a list as one page shows.
export const AT_ONCE = 50;
// As many as one request may ask for: the choices of a form.
const EVERY = 200;

const REPOSITORIES = "repositories";
const BLOB_STORES = "blob-stores";
// What the browsing screens fetched (lib/content.ts): a repository that was made,
// changed or deleted is another one there too.
const CONTENT = "content";

const paged = (page: number) => ({ limit: AT_ONCE, offset: (page - 1) * AT_ONCE });
const repository = (name: string) => `/repositories/${encodeURIComponent(name)}`;

function afterRepositoryChange(client: QueryClient): Promise<void> {
  void client.invalidateQueries({ queryKey: [CONTENT] });
  void client.invalidateQueries({ queryKey: ["search"] });
  // A blob store says how much it holds, and who uses it decides whether it can go.
  void client.invalidateQueries({ queryKey: [BLOB_STORES] });
  return client.invalidateQueries({ queryKey: [REPOSITORIES] });
}

// --- Repositories ---------------------------------------------------------------------------

export function useManagedRepositories(page: number) {
  return useQuery({
    queryKey: [REPOSITORIES, "list", page],
    queryFn: () => api.get<Page<RepositoryOut>>("/repositories", { query: paged(page) }),
  });
}

/** The repositories there are, for a group's form to choose its members from. */
export function useEveryManagedRepository() {
  return useQuery({
    queryKey: [REPOSITORIES, "every"],
    queryFn: () => api.get<Page<RepositoryOut>>("/repositories", { query: { limit: EVERY } }),
  });
}

export function useManagedRepository(name: string | null) {
  return useQuery({
    queryKey: [REPOSITORIES, "one", name],
    queryFn: () => api.get<RepositoryOut>(repository(name ?? "")),
    enabled: name !== null,
  });
}

export function useCreateRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: RepositoryCreate) => api.post<RepositoryOut>("/repositories", wanted),
    gcTime: 0, // what was sent may have a remote's secret in it
    onSuccess: () => afterRepositoryChange(client),
  });
}

export function useUpdateRepository(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: RepositoryUpdate) => api.put<RepositoryOut>(repository(name), changes),
    gcTime: 0, // as above
    onSuccess: (saved) => {
      // The answer is the repository as it is now: its page shows it without asking again.
      client.setQueryData([REPOSITORIES, "one", name], saved);
      return afterRepositoryChange(client);
    },
  });
}

export function useDeleteRepository() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(repository(name)),
    onSuccess: (_, name) => {
      client.removeQueries({ queryKey: [REPOSITORIES, "one", name] });
      return afterRepositoryChange(client);
    },
  });
}

/** Makes a proxy check everything it cached with its remote again. */
export function useInvalidateCache(name: string) {
  return useMutation({
    mutationFn: () => api.post<void>(`${repository(name)}/invalidate-cache`),
  });
}

/** Goes through a repository again. The answer says what was found; it can take a while. */
export function useRebuildIndex(name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<IndexRebuilt>(`${repository(name)}/rebuild-index`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [CONTENT] });
      return client.invalidateQueries({ queryKey: ["search"] });
    },
  });
}

// --- Blob stores ----------------------------------------------------------------------------

export function useBlobStores(page: number) {
  return useQuery({
    queryKey: [BLOB_STORES, "list", page],
    queryFn: () => api.get<Page<BlobStoreOut>>("/blob-stores", { query: paged(page) }),
  });
}

/** The blob stores there are, for a form to choose from. `enabled` is false for who may not read them. */
export function useEveryBlobStore(enabled = true) {
  return useQuery({
    queryKey: [BLOB_STORES, "every"],
    queryFn: () => api.get<Page<BlobStoreOut>>("/blob-stores", { query: { limit: EVERY } }),
    enabled,
  });
}

export function useCreateBlobStore() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (wanted: BlobStoreCreate) => api.post<BlobStoreOut>("/blob-stores", wanted),
    onSuccess: () => client.invalidateQueries({ queryKey: [BLOB_STORES] }),
  });
}

export function useDeleteBlobStore() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.delete<void>(`/blob-stores/${encodeURIComponent(name)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: [BLOB_STORES] }),
  });
}

// --- The installation -----------------------------------------------------------------------

export function useInformation() {
  return useQuery({
    queryKey: ["system", "information"],
    queryFn: () => api.get<Information>("/system/information"),
  });
}

/** Sets the address the server gives out as its own, or clears it with null. */
export function useSetBaseUrl() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (baseUrl: string | null) =>
      api.put<SettingsOut>("/settings/base-url", { base_url: baseUrl }),
    onSuccess: (settings) => {
      client.setQueryData(SETTINGS_KEY, settings);
      // Every address the server gives out is built from it.
      return client.invalidateQueries({ queryKey: [CONTENT] });
    },
  });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 710 passed in 24 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): the form of a repository, and the requests of its administration"
```

---

### Task 3: The members of a group, the texts, and the navigation

**Files:**
- Create: `frontend/src/components/member-list.tsx`
- Modify: `frontend/messages/en.json`, `frontend/src/lib/navigation.ts`
- Test: `frontend/src/components/member-list.test.tsx`
- Test (modify): `frontend/src/components/shell.test.tsx`, `frontend/src/lib/navigation.test.ts`

**Interfaces:**
- Consumes: `moved` of Task 2; `SelectField`, `Button`; the address constants of Task 2.
- Produces:
  - `MemberList({ legend, hint?, members, onChange(members), candidates, error?, disabled? })`. Each member's row is a list item with `data-member`; its buttons are named "Move <name> up", "Move <name> down", "Take <name> out"; the list to add from is labelled "A repository to add", with the button "Add it"; a `role="status"` line says what was done.
  - `NAVIGATION`'s administration area gains `manageRepositories`, `blobStores`, `system`.
  - `messages/en.json`: the groups `members`, `manage`, `blobStores`, `system`; `nav.items.manageRepositories`, `blobStores`, `system`; `browse.settings`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/member-list.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test } from "vitest";

import { expectAccessible } from "@/test/axe";
import { renderUi } from "@/test/render";

import { MemberList } from "./member-list";

function Group({
  initial,
  candidates = ["releases", "snapshots", "central", "thirdparty"],
  error,
  disabled,
}: {
  initial: string[];
  candidates?: string[];
  error?: string;
  disabled?: boolean;
}) {
  const [members, setMembers] = useState(initial);
  return (
    <MemberList
      legend="Members"
      hint="The first that has it answers."
      members={members}
      onChange={setMembers}
      candidates={candidates}
      error={error}
      disabled={disabled}
    />
  );
}

const order = () => screen.getAllByRole("listitem").map((item) => item.getAttribute("data-member"));
const button = (name: string) => screen.getByRole("button", { name });

describe("the members of a group (R5)", () => {
  test("are listed in the order they are asked, each with its place", async () => {
    renderUi(<Group initial={["releases", "central"]} />);
    const group = screen.getByRole("group", { name: "Members" });

    expect(order()).toEqual(["releases", "central"]);
    expect(group).toHaveAccessibleDescription("The first that has it answers.");
    expect(within(group).getAllByRole("listitem")[0]).toHaveTextContent("1releases");
    // The first cannot go further up, nor the last further down.
    expect(button("Move releases up")).toBeDisabled();
    expect(button("Move central down")).toBeDisabled();
    await expectAccessible();
  });

  test("are moved by buttons, which keep the keyboard and say where the member now is", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={["releases", "snapshots", "central"]} />);

    await user.click(button("Move central up"));
    expect(order()).toEqual(["releases", "central", "snapshots"]);
    expect(button("Move central up")).toHaveFocus(); // to be pressed again
    expect(screen.getByRole("status")).toHaveTextContent("central is now number 2 of 3.");

    await user.keyboard("{Enter}");
    expect(order()).toEqual(["central", "releases", "snapshots"]);
    // At the top the button can do no more, and a button that is disabled cannot keep
    // the keyboard: it goes to the one beside it.
    expect(button("Move central up")).toBeDisabled();
    expect(button("Move central down")).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("central is now number 1 of 3.");

    await user.click(button("Move releases down"));
    expect(order()).toEqual(["central", "snapshots", "releases"]);
    expect(button("Move releases up")).toHaveFocus();
  });

  test("are taken out one by one, and the keyboard goes to the list to add from", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={["releases", "central"]} />);

    await user.click(button("Take releases out"));

    expect(order()).toEqual(["central"]);
    expect(screen.getByLabelText("A repository to add")).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("releases was taken out.");
  });

  test("are added from those that are not members yet, at the end", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={["central"]} />);
    const choices = () =>
      within(screen.getByLabelText("A repository to add"))
        .getAllByRole("option")
        .map((option) => option.textContent);

    expect(choices()).toEqual(["releases", "snapshots", "thirdparty"]);
    await user.selectOptions(screen.getByLabelText("A repository to add"), "snapshots");
    await user.click(button("Add it"));

    expect(order()).toEqual(["central", "snapshots"]);
    expect(choices()).toEqual(["releases", "thirdparty"]);
    expect(screen.getByRole("status")).toHaveTextContent("snapshots was added as number 2.");
    // The list to add from shows the next that can be added, and has the keyboard.
    expect(screen.getByLabelText("A repository to add")).toHaveValue("releases");
    expect(screen.getByLabelText("A repository to add")).toHaveFocus();
  });

  test("say so when there is none, and when there is nothing left to add", async () => {
    const user = userEvent.setup();
    renderUi(<Group initial={[]} candidates={["releases"]} />);
    expect(screen.getByText("It has no member yet, and so answers nothing.")).toBeVisible();

    await user.click(button("Add it"));

    expect(order()).toEqual(["releases"]);
    expect(screen.getByText("There is no other repository of this format to add.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add it" })).toBeNull();
    await expectAccessible();
  });

  test("keep a member that is not among the repositories that could be added", () => {
    // One the caller may not see, or that is beyond what one request brings.
    renderUi(<Group initial={["hidden", "releases"]} candidates={["releases", "central"]} />);

    expect(order()).toEqual(["hidden", "releases"]);
  });

  test("say what the server refused of them, and cannot be changed by whoever may only look", () => {
    const { unmount } = renderUi(
      <Group initial={["releases"]} error="releases is not a maven repository." />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("releases is not a maven repository.");
    unmount();

    renderUi(<Group initial={["releases", "central"]} disabled />);
    expect(button("Move central up")).toBeDisabled();
    expect(button("Take releases out")).toBeDisabled();
    expect(button("Add it")).toBeDisabled();
  });
});
```

Change `frontend/src/components/shell.test.tsx`:

```diff
@@ -63,7 +63,7 @@ describe("the shell", () => {
     expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
   });
 
-  test("leads an administrator to the users, the roles and anonymous access", () => {
+  test("leads an administrator to everything there is to administer", () => {
     navigation.at("/admin/users/0190-aa");
     renderUi(<AppShell session={ADMIN}>Content</AppShell>, { session: ADMIN });
     const [wide] = screen.getAllByRole("navigation", { name: "Main" });
@@ -76,9 +76,20 @@ describe("the shell", () => {
       ["Users", "/admin/users"],
       ["Roles", "/admin/roles"],
       ["Anonymous access", "/admin/anonymous-access"],
+      // Not "Repositories": that is the list for browsing, in the same navigation (R14).
+      ["Manage repositories", "/admin/repositories"],
+      ["Blob stores", "/admin/blob-stores"],
+      ["System", "/admin/system"],
     ]);
     // One user's page is among the users.
-    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual(["page", null, null]);
+    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([
+      "page",
+      null,
+      null,
+      null,
+      null,
+      null,
+    ]);
   });
 
   test("has the navigation in a row of its own, which wraps where it does not fit", () => {
```

Change `frontend/src/lib/navigation.test.ts`:

```diff
@@ -82,12 +82,23 @@ describe("the navigation as it is", () => {
       ["users", "/admin/users"],
       ["roles", "/admin/roles"],
       ["anonymousAccess", "/admin/anonymous-access"],
+      ["manageRepositories", "/admin/repositories"],
+      ["blobStores", "/admin/blob-stores"],
+      ["system", "/admin/system"],
     ]);
     expect(administration({ ...ADMIN, permissions: ["admin:roles:read"] })).toEqual([
       ["roles", "/admin/roles"],
     ]);
+    // Anonymous access and the system page are both settings.
     expect(administration({ ...ADMIN, permissions: ["admin:settings"] })).toEqual([
       ["anonymousAccess", "/admin/anonymous-access"],
+      ["system", "/admin/system"],
+    ]);
+    expect(administration({ ...ADMIN, permissions: ["admin:repositories:read"] })).toEqual([
+      ["manageRepositories", "/admin/repositories"],
+    ]);
+    expect(administration({ ...ADMIN, permissions: ["admin:blobstores:*"] })).toEqual([
+      ["blobStores", "/admin/blob-stores"],
     ]);
     expect(administration({ ...ADMIN, permissions: ["repository:*:*:*"] })).toEqual([]);
     // Whatever the anonymous user holds, nobody administers without signing in.
@@ -104,6 +115,11 @@ describe("the navigation as it is", () => {
     expect(current("/admin/users/new")).toEqual(["users"]);
     expect(current("/admin/roles/deployers")).toEqual(["roles"]);
     expect(current("/admin/anonymous-access")).toEqual(["anonymousAccess"]);
+    // The settings of a repository are among those that are managed, not those that are browsed.
+    expect(current("/admin/repositories/releases")).toEqual(["manageRepositories"]);
+    expect(current("/admin/repositories/~new")).toEqual(["manageRepositories"]);
+    expect(current("/admin/blob-stores")).toEqual(["blobStores"]);
+    expect(current("/admin/system")).toEqual(["system"]);
     expect(current("/account/tokens")).toEqual([]);
   });
 
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 3 tests fail and 1 file does not load. In `navigation.test.ts`: "shows each part of the administration to whoever may read it (UI-2)" and "marks an administration item for everything under it". In `shell.test.tsx`: "leads an administrator to everything there is to administer". `member-list.test.tsx` fails with `Failed to resolve import "./member-list"`.

- [ ] **Step 3: Implement**

Change `frontend/messages/en.json`:

```diff
@@ -20,7 +20,10 @@
       "upload": "Upload",
       "users": "Users",
       "roles": "Roles",
-      "anonymousAccess": "Anonymous access"
+      "anonymousAccess": "Anonymous access",
+      "manageRepositories": "Manage repositories",
+      "blobStores": "Blob stores",
+      "system": "System"
     }
   },
   "theme": {
@@ -194,7 +197,8 @@
     "deleteFolderBody": "Every file under {folder} is deleted. It cannot be brought back.",
     "deletedSoFar": "{deleted, plural, one {# file deleted so far} other {# files deleted so far}}…",
     "folderDeleted": "Deleted {deleted, plural, one {# file} other {# files}} under {name}.{skipped, plural, =0 {} one { # file is kept by the format.} other { # files are kept by the format.}}",
-    "folderStopped": "Stopped. {deleted, plural, one {# file} other {# files}} under {name} had been deleted."
+    "folderStopped": "Stopped. {deleted, plural, one {# file} other {# files}} under {name} had been deleted.",
+    "settings": "Settings"
   },
   "component": {
     "path": "Path",
@@ -608,5 +612,228 @@
     "grantsNothing": "Its roles grant nothing in any repository.",
     "onlyRepositories": "Whatever its roles say, a visitor is never allowed anything but what concerns repositories.",
     "userDisabled": "The anonymous user is disabled, so nothing is given without signing in, though the switch is on. Enable the user to let visitors in."
+  },
+  "members": {
+    "none": "It has no member yet, and so answers nothing.",
+    "up": "Move {name} up",
+    "down": "Move {name} down",
+    "remove": "Take {name} out",
+    "candidate": "A repository to add",
+    "add": "Add it",
+    "nothingToAdd": "There is no other repository of this format to add.",
+    "nowAt": "{name} is now number {place} of {of}.",
+    "added": "{name} was added as number {place}.",
+    "removed": "{name} was taken out."
+  },
+  "manage": {
+    "title": "Manage repositories",
+    "titleOf": "Settings of {repository}",
+    "newTitle": "New repository",
+    "intro": "Every repository as it is set up. To use one, browse it.",
+    "newIntro": "The format and the type decide what else there is to set. Neither can be changed later.",
+    "settingsOf": "How this repository is set up.",
+    "path": "Path",
+    "new": "New repository",
+    "emptyTitle": "No repository yet",
+    "empty": "A repository is where packages are stored, fetched through, or presented from.",
+    "columns": {
+      "name": "Name",
+      "format": "Format",
+      "type": "Type",
+      "state": "State",
+      "blobStore": "Blob store"
+    },
+    "online": "Online",
+    "offline": "Offline",
+    "browse": "Browse it",
+    "fields": {
+      "format": "Format",
+      "name": "Name",
+      "type": "Type",
+      "online": "Online",
+      "blobStore": "Blob store",
+      "address": "Address",
+      "deploymentPolicy": "Deployment policy",
+      "remoteUrl": "Remote address",
+      "authType": "Signs in to the remote with",
+      "authUsername": "User name",
+      "password": "Password",
+      "token": "Token",
+      "contentMaxAge": "Trust a cached file for (minutes)",
+      "metadataMaxAge": "Trust cached metadata for (minutes)",
+      "negativeCache": "Remember what the remote does not have",
+      "negativeCacheTtl": "Remember it for (minutes)",
+      "autoBlock": "Leave the remote alone after it fails",
+      "blocked": "Blocked: do not contact the remote at all",
+      "members": "Members, in the order they are asked",
+      "versionPolicy": "Version policy",
+      "layoutPolicy": "Layout policy"
+    },
+    "hints": {
+      "name": "Letters, digits and . _ - , up to 64. It is part of every address, and cannot be changed later.",
+      "online": "Offline, package clients are refused. It can still be browsed and set up here.",
+      "blobStore": "Where its files are kept. It cannot be changed later.",
+      "blobStoreUnreadable": "You may not see the blob stores, so the default one is used.",
+      "remoteUrl": "An http or https address, without a user name, a password, a query or a fragment.",
+      "secret": "It is sealed before it is stored, and shown to nobody again.",
+      "secretStored": "One is stored. Leave this empty to keep it, or type another to replace it.",
+      "maxAge": "After that it is checked with the remote again. 0 checks every time, -1 never again.",
+      "metadataMaxAge": "Indexes and listings: what says which versions there are. 0 checks every time, -1 never again.",
+      "negativeCache": "A path the remote did not have is not asked for again for a while.",
+      "autoBlock": "A minute at first, doubling with each further failure up to an hour. Meanwhile what is cached is served.",
+      "blocked": "Only what is cached is served, until this is unticked.",
+      "members": "The first that has what is asked for answers. Offline members, and proxies whose remote is unavailable, are passed over."
+    },
+    "sections": {
+      "hosted": "What it takes",
+      "remote": "The remote",
+      "cache": "What it cached",
+      "blocking": "When the remote fails",
+      "maven": "Maven"
+    },
+    "types": {
+      "hosted": "Hosted",
+      "proxy": "Proxy",
+      "group": "Group"
+    },
+    "typesHints": {
+      "hosted": "Stores what is uploaded or deployed to it.",
+      "proxy": "Fetches from a remote repository, and keeps what it fetched.",
+      "group": "Presents several repositories at one address. It stores nothing of its own."
+    },
+    "policies": {
+      "allow_redeploy": "Allow redeploy",
+      "disable_redeploy": "Disable redeploy",
+      "read_only": "Read only"
+    },
+    "policiesHints": {
+      "allow_redeploy": "A version that is there can be stored again, replacing it.",
+      "disable_redeploy": "A version that is there is refused. What is new is taken.",
+      "read_only": "Nothing is taken and nothing is deleted."
+    },
+    "auth": {
+      "none": "Nothing",
+      "basic": "A user name and a password",
+      "bearer": "A token"
+    },
+    "versions": {
+      "release": "Release",
+      "snapshot": "Snapshot",
+      "mixed": "Mixed"
+    },
+    "versionsHints": {
+      "release": "Only versions that are not snapshots.",
+      "snapshot": "Only versions that end in -SNAPSHOT.",
+      "mixed": "Both."
+    },
+    "layouts": {
+      "strict": "Strict",
+      "permissive": "Permissive"
+    },
+    "layoutsHints": {
+      "strict": "Only paths that are laid out as Maven lays them out.",
+      "permissive": "Any path."
+    },
+    "problems": {
+      "nameRule": "A repository's name is 1 to 64 letters, digits or . _ -",
+      "nameDots": "A repository cannot be called . or .. : it would have no address.",
+      "dockerNameRule": "A Docker repository's name is the first part of its images' names: lower-case letters and digits, with single . _ __ or - between them.",
+      "remoteRule": "Give an http or https address with a host, and without credentials, a query or a fragment.",
+      "ageRule": "A whole number of minutes, -1 or more.",
+      "ttlRule": "A whole number of minutes, 1 or more.",
+      "usernameNeeded": "Give the user name.",
+      "secretNeeded": "Give it: none is stored."
+    },
+    "mayNotCreate": "You may not create repositories.",
+    "create": "Create repository",
+    "created": "Created the repository {name}.",
+    "save": "Save",
+    "saved": "Saved the repository {name}.",
+    "stateTitle": "The remote",
+    "state": {
+      "remote": "State",
+      "reachable": "In use",
+      "blocked": "Blocked",
+      "waiting": "Left alone after a failure",
+      "until": "Asked again",
+      "failures": "Failures in a row",
+      "lastError": "Last error"
+    },
+    "checkAgainIntro": "What was cached is served without asking the remote until its time is up. This makes all of it be checked again at its next use.",
+    "checkAgain": "Check everything again",
+    "checkedAgain": "{name} will check everything with its remote again.",
+    "rebuildTitle": "Rebuild the index",
+    "rebuildIntro": "Goes through every file again: which component it belongs to, and the words it is found by. It repairs what an older version stored differently, and can take a while.",
+    "rebuild": "Rebuild the index",
+    "rebuilt": "The index is rebuilt",
+    "rebuiltFound": "{files, plural, one {# file} other {# files}} looked at, {moved} given to another component. {components, plural, one {# component} other {# components}} looked at, {removed} removed for having no file left.",
+    "deleteTitle": "Delete this repository",
+    "deleteIntro": "Everything stored in it is deleted with it.",
+    "deleteIntroGroup": "Its members stay as they are: a group stores nothing of its own.",
+    "delete": "Delete repository",
+    "deleteAsk": "Delete the repository {name}?",
+    "deleteBody": "Every component and file in it is deleted, and every client that uses its address is refused. This cannot be undone.",
+    "deleteBodyGroup": "Every client that uses its address is refused. Its members are not touched. This cannot be undone.",
+    "deleted": "Deleted the repository {name}."
+  },
+  "blobStores": {
+    "title": "Blob stores",
+    "intro": "Where the files of the repositories are kept.",
+    "columns": {
+      "name": "Name",
+      "directory": "Directory",
+      "blobs": "Blobs",
+      "size": "Size",
+      "available": "Space left",
+      "actions": "Delete"
+    },
+    "unknown": "Not known",
+    "createTitle": "New blob store",
+    "fields": {
+      "name": "Name",
+      "directory": "Directory"
+    },
+    "hints": {
+      "name": "Letters, digits and . _ - , up to 64.",
+      "directory": "Optional. Under the data directory unless it starts at the root. Without one, the store's name is used."
+    },
+    "nameRule": "A blob store's name is 1 to 64 letters, digits or . _ -",
+    "create": "Create blob store",
+    "created": "Created the blob store {name}.",
+    "delete": "Delete",
+    "deleteNamed": "Delete {name}",
+    "deleteStore": "Delete blob store",
+    "deleteAsk": "Delete the blob store {name}?",
+    "deleteBody": "The server forgets the store. Its files stay on the disk, for you to remove. A store that a repository uses is not deleted.",
+    "deleted": "Deleted the blob store {name}."
+  },
+  "system": {
+    "title": "System",
+    "intro": "What is running here, and the address it gives out as its own.",
+    "runningTitle": "What is running",
+    "facts": {
+      "version": "Version",
+      "schema": "Schema",
+      "started": "Started",
+      "python": "Python",
+      "platform": "Runs on",
+      "database": "Database"
+    },
+    "neverMigrated": "Never migrated",
+    "schemaCurrent": "As this version expects",
+    "schemaOther": "This version expects {expected}",
+    "baseUrlTitle": "Base URL",
+    "fields": {
+      "baseUrl": "The address of this server, as its clients reach it"
+    },
+    "hints": {
+      "baseUrl": "Used in every address the server gives out. Leave it empty to use the address each request came to. Set it when the server is behind a proxy that does not pass the address on."
+    },
+    "baseUrlRule": "Give an http or https address, without a query or a fragment.",
+    "saveBaseUrl": "Save",
+    "baseUrlSaved": "The base URL is saved.",
+    "baseUrlCleared": "The base URL is cleared.",
+    "storesTitle": "Blob stores",
+    "toStores": "Manage the blob stores"
   }
 }
```

Create `frontend/src/components/member-list.tsx`:

```tsx
"use client";

import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { SelectField } from "@/components/ui/inputs";
import { moved } from "@/lib/repository-form";

type Asked = { name: string; button: "up" | "down" } | { add: true };

/**
 * The members of a group, in the order they are tried (R5): the first that has what is
 * asked for answers, so the order is part of the setting. Each member can be moved up,
 * moved down and taken out by a button, which a keyboard can press where it could not
 * drag; one is added from the list of those that are not members yet.
 */
export function MemberList({
  legend,
  hint,
  members,
  onChange,
  candidates,
  error,
  disabled = false,
}: {
  legend: string;
  hint?: string;
  members: string[];
  onChange: (members: string[]) => void;
  /** The repositories that could be added: of the group's format, the group itself left out. */
  candidates: string[];
  error?: string | null;
  disabled?: boolean;
}) {
  const t = useTranslations("members");
  const id = useId();
  const list = useRef<HTMLDivElement>(null);
  const free = candidates.filter((name) => !members.includes(name));
  // The one that the list to add from shows. It follows what there is to add.
  const [chosen, setChosen] = useState("");
  const adding = free.includes(chosen) ? chosen : (free[0] ?? "");
  // What was done last, for a screen reader, which does not see a row move.
  const [said, setSaid] = useState("");
  // Where the keyboard goes once the list is drawn again: a row that moved takes its
  // buttons with it, and a button that can do no more (at an end) cannot keep the
  // keyboard. Asked for by what was pressed, and done once, after the next drawing.
  const asked = useRef<Asked | null>(null);
  useEffect(() => {
    const wanted = asked.current;
    if (wanted === null) return;
    asked.current = null;
    const within = list.current;
    if ("add" in wanted) {
      within?.querySelector<HTMLElement>("select, [data-add]")?.focus();
      return;
    }
    const row = Array.from(within?.querySelectorAll<HTMLElement>("li") ?? []).find(
      (item) => item.dataset.member === wanted.name,
    );
    const same = row?.querySelector<HTMLButtonElement>(`[data-button="${wanted.button}"]`);
    const other = row?.querySelector<HTMLButtonElement>(
      `[data-button="${wanted.button === "up" ? "down" : "up"}"]`,
    );
    (same && !same.disabled ? same : other)?.focus();
  });

  function move(name: string, by: -1 | 1) {
    const next = moved(members, name, by);
    onChange(next);
    setSaid(t("nowAt", { name, place: next.indexOf(name) + 1, of: next.length }));
    asked.current = { name, button: by < 0 ? "up" : "down" };
  }

  return (
    <fieldset
      disabled={disabled}
      aria-describedby={hint ? `${id}-hint` : undefined}
      className="flex min-w-0 flex-col gap-3 border-0 p-0"
    >
      <legend className="label-caps mb-1 p-0 text-fg-muted">{legend}</legend>
      {hint ? (
        <p id={`${id}-hint`} className="text-sm text-fg-subtle">
          {hint}
        </p>
      ) : null}
      <div ref={list} className="flex flex-col gap-3">
        {members.length === 0 ? <p className="text-sm text-fg-subtle">{t("none")}</p> : null}
        <ol className="flex flex-col gap-2">
          {members.map((name, index) => (
            <li
              key={name}
              data-member={name}
              className="flex items-center gap-2 rounded-sm border border-line bg-field px-3 py-1.5"
            >
              <span aria-hidden="true" className="w-6 shrink-0 font-mono text-sm text-fg-subtle">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 font-mono text-sm break-all text-fg">{name}</span>
              <Button
                size="sm"
                variant="ghost"
                data-button="up"
                disabled={index === 0}
                aria-label={t("up", { name })}
                onClick={() => move(name, -1)}
              >
                <ArrowUp aria-hidden="true" className="size-4" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                data-button="down"
                disabled={index === members.length - 1}
                aria-label={t("down", { name })}
                onClick={() => move(name, 1)}
              >
                <ArrowDown aria-hidden="true" className="size-4" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                aria-label={t("remove", { name })}
                onClick={() => {
                  onChange(members.filter((member) => member !== name));
                  setSaid(t("removed", { name }));
                  asked.current = { add: true };
                }}
              >
                <X aria-hidden="true" className="size-4" />
              </Button>
            </li>
          ))}
        </ol>
        {free.length === 0 ? (
          <p className="text-sm text-fg-subtle">{t("nothingToAdd")}</p>
        ) : (
          <div className="flex flex-wrap items-end gap-3">
            <SelectField
              label={t("candidate")}
              value={adding}
              onChange={(event) => setChosen(event.target.value)}
              choices={free.map((name) => ({ value: name, label: name }))}
            />
            <Button
              data-add
              onClick={() => {
                onChange([...members, adding]);
                setSaid(t("added", { name: adding, place: members.length + 1 }));
                asked.current = { add: true };
              }}
            >
              <Plus aria-hidden="true" className="size-4" />
              {t("add")}
            </Button>
          </div>
        )}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-ink-bad">
          {error}
        </p>
      ) : null}
      <p role="status" className="sr-only">
        {said}
      </p>
    </fieldset>
  );
}
```

Change `frontend/src/lib/navigation.ts`:

```diff
@@ -2,15 +2,42 @@
  * The navigation, as data. A screen is put into the navigation by adding an item here,
  * with the permission its API needs: the item is then shown only to those who hold it.
  */
-import { Boxes, Search, ShieldCheck, Unlock, Upload, Users, type LucideIcon } from "lucide-react";
+import {
+  Boxes,
+  HardDrive,
+  Search,
+  Server,
+  ShieldCheck,
+  Unlock,
+  Upload,
+  Users,
+  Wrench,
+  type LucideIcon,
+} from "lucide-react";
 import type { Route } from "next";
 
 import type { SessionInfo } from "@/lib/api/types";
-import { ANONYMOUS_ACCESS, ROLES, USERS } from "@/lib/paths";
+import {
+  ANONYMOUS_ACCESS,
+  BLOB_STORES,
+  MANAGE_REPOSITORIES,
+  ROLES,
+  SYSTEM,
+  USERS,
+} from "@/lib/paths";
 import { allows, allowsSome } from "@/lib/session/rules";
 
 export type AreaKey = "browse" | "administration";
-export type ItemKey = "repositories" | "search" | "upload" | "users" | "roles" | "anonymousAccess";
+export type ItemKey =
+  | "repositories"
+  | "search"
+  | "upload"
+  | "users"
+  | "roles"
+  | "anonymousAccess"
+  | "manageRepositories"
+  | "blobStores"
+  | "system";
 
 export type NavItem = {
   /** Its name is the message `nav.items.<key>`. */
@@ -61,6 +88,19 @@ export const NAVIGATION: readonly NavArea[] = [
         icon: Unlock,
         permission: "admin:settings:read",
       },
+      {
+        key: "manageRepositories",
+        href: MANAGE_REPOSITORIES,
+        icon: Wrench,
+        permission: "admin:repositories:read",
+      },
+      {
+        key: "blobStores",
+        href: BLOB_STORES,
+        icon: HardDrive,
+        permission: "admin:blobstores:read",
+      },
+      { key: "system", href: SYSTEM, icon: Server, permission: "admin:settings:read" },
     ],
   },
 ];
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 717 passed in 25 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(frontend): a group's members in order, and the administration's navigation"
```

---

### Task 4: The screens: repositories, blob stores and the system

**Files:**
- Create: `frontend/src/screens/manage-repositories.tsx`, `repository-settings.tsx`, `blob-stores.tsx`, `system.tsx` (all in `frontend/src/screens/`)
- Modify: `frontend/src/screens/browse.tsx`
- Test: `frontend/src/screens/administration.test.tsx`
- Test (modify): `frontend/src/screens/browse.test.tsx`

**Interfaces:**
- Consumes: everything Tasks 2 and 3 produce; `useAttempts`, `usePageFocus`, `useWithinPages`; `refusalsOf`; `useSettings`; `ConfirmDialog` with `mustType`; `ChoiceGroup`, `CheckboxField`, `SelectField`, `TextField`; `Facts`, `Fact`, `Time`, `Pager`; `useNotify`; `NothingHere`.
- Produces: `ManageRepositoriesScreen()` at `/admin/repositories`; `NewRepositoryScreen()` at `/admin/repositories/~new` and `RepositorySettingsScreen()` at `/admin/repositories/<name>`, both in `repository-settings.tsx`; `BlobStoresScreen()` at `/admin/blob-stores` and `BlobStoreTable({ caption, stores, onDelete? })` in `blob-stores.tsx`; `SystemScreen()` at `/admin/system`. The browse screen has a "Settings" link for whoever holds `admin:repositories:read`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/screens/administration.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import type { SessionInfo } from "@/lib/api/types";
import { failure, mockApi, type Call, type Routes } from "@/test/api";
import { expectAccessible } from "@/test/axe";
import { navigation } from "@/test/navigation";
import { ADMIN, renderUi } from "@/test/render";

import { BlobStoresScreen } from "./blob-stores";
import { ManageRepositoriesScreen } from "./manage-repositories";
import { NewRepositoryScreen, RepositorySettingsScreen } from "./repository-settings";
import { SystemScreen } from "./system";

const page = (items: unknown[], total = items.length) => ({ items, total, limit: 50, offset: 0 });
const holding = (...permissions: string[]): SessionInfo => ({ ...ADMIN, permissions });
const of = (calls: Call[], method: string) => calls.filter((call) => call.method === method);
const notices = () => screen.getByRole("region", { name: "Notifications" });
/** The members a group's form shows, in their order. */
const members = () =>
  within(screen.getByRole("group", { name: "Members, in the order they are asked" }))
    .queryAllByRole("listitem")
    .map((item) => item.getAttribute("data-member"));

const repository = (name: string, more: Record<string, unknown> = {}) => ({
  name,
  format: "maven",
  type: "hosted",
  online: true,
  blob_store: "default",
  url_path: `/repository/${name}/`,
  hosted: { deployment_policy: "allow_redeploy" },
  format_config: { version_policy: "release", layout_policy: "strict" },
  proxy: null,
  group: null,
  status: null,
  ...more,
});
const proxy = (name: string, more: Record<string, unknown> = {}, status: object = {}) =>
  repository(name, {
    type: "proxy",
    hosted: null,
    proxy: {
      remote_url: "https://repo.example.org/maven2",
      content_max_age_minutes: 1440,
      metadata_max_age_minutes: 1440,
      negative_cache: { enabled: true, ttl_minutes: 1440 },
      remote_auth: { type: "basic", username: "robot", has_secret: true },
      blocked: false,
      auto_block: true,
      ...more,
    },
    status: { blocked: false, auto_blocked_until: null, failures: 0, last_error: null, ...status },
  });
const RELEASES = repository("releases");
const CENTRAL = proxy("central");
const ALL = repository("all", {
  type: "group",
  blob_store: null,
  hosted: null,
  format_config: {},
  group: { members: ["releases", "central"] },
});
const NPM = repository("npm-own", { format: "npm", format_config: {} });
const store = (name: string, more: Record<string, unknown> = {}) => ({
  name,
  type: "file",
  path: name,
  blob_count: 3,
  total_bytes: 2516582,
  available_bytes: 906238099456,
  ...more,
});
const STORES = [store("default"), store("fast", { path: "/mnt/fast", available_bytes: null })];

describe("the repositories as they are set up (R1)", () => {
  function list(more: Routes = {}, session = ADMIN, address = "/admin/repositories") {
    const api = mockApi({
      "GET /repositories": { json: page([ALL, CENTRAL, RELEASES]) },
      ...more,
    });
    navigation.at(address);
    return { ...renderUi(<ManageRepositoriesScreen />, { session }), ...api };
  }

  test("are listed with their format, type, state and blob store", async () => {
    const { calls } = list({
      "GET /repositories": {
        json: page([
          ALL,
          proxy("central", {}, { blocked: true }),
          proxy("mirror", {}, { auto_blocked_until: "2099-01-01T00:00:00Z", failures: 3 }),
          repository("releases", { online: false }),
        ]),
      },
    });

    const table = await screen.findByRole("table", { name: "Manage repositories" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(calls[0]?.path).toBe("/repositories?limit=50&offset=0");
    expect(within(rows[3] as HTMLElement).getByRole("link", { name: "releases" })).toHaveAttribute(
      "href",
      "/admin/repositories/releases",
    );
    expect(rows[0]).toHaveTextContent("Group");
    expect(rows[0]).toHaveTextContent("Online");
    expect(rows[1]).toHaveTextContent("Proxy");
    expect(rows[1]).toHaveTextContent("Blocked");
    expect(rows[2]).toHaveTextContent("Left alone after a failure");
    expect(rows[3]).toHaveTextContent("Offline");
    expect(rows[3]).toHaveTextContent("default");
    // The form for a new one is where no repository's name can be (R13).
    expect(screen.getByRole("link", { name: "New repository" })).toHaveAttribute(
      "href",
      "/admin/repositories/~new",
    );
    await expectAccessible();
  });

  test("say so when there is none, and offer no new one to whoever may only read", async () => {
    const first = list({ "GET /repositories": { json: page([]) } });
    expect(await screen.findByRole("heading", { name: "No repository yet" })).toBeVisible();
    first.unmount();

    list({}, holding("admin:repositories:read"));
    await screen.findByRole("table", { name: "Manage repositories" });
    expect(screen.queryByRole("link", { name: "New repository" })).toBeNull();
  });

  test("come a page at a time, with the keyboard at the list when a page is turned", async () => {
    const { rerender, calls } = list({ "GET /repositories": { json: page([RELEASES], 120) } });
    await screen.findByRole("table", { name: "Manage repositories" });

    navigation.at("/admin/repositories?page=2");
    rerender(<ManageRepositoriesScreen />);

    await waitFor(() =>
      expect(screen.getByRole("group", { name: "Manage repositories" })).toHaveFocus(),
    );
    expect(calls.map((call) => call.path)).toContain("/repositories?limit=50&offset=50");
    expect(screen.getByRole("navigation", { name: "Pages" })).toHaveTextContent("Page 2 of 3");
  });

  test("say what went wrong when they may not be seen", async () => {
    list({ "GET /repositories": failure(403, "forbidden", "No.") });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to do this.",
    );
  });
});

describe("a new repository (R2)", () => {
  function fresh(more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /repositories": { json: page([ALL, CENTRAL, NPM, RELEASES]) },
      "GET /blob-stores": { json: page(STORES) },
      "POST /repositories": (call) => ({
        status: 201,
        json: repository((call.body as { name: string }).name),
      }),
      ...more,
    });
    navigation.at("/admin/repositories/~new");
    return { ...renderUi(<NewRepositoryScreen />, { session }), ...api };
  }
  const create = () => screen.getByRole("button", { name: "Create repository" });
  const sent = (calls: Call[]) => of(calls, "POST")[0]?.body as Record<string, unknown>;

  test("is a hosted Maven one unless said otherwise, with the server's own defaults", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "snapshots");
    await user.click(screen.getByRole("radio", { name: "Snapshot" }));
    await user.click(create());

    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith("/admin/repositories/snapshots"),
    );
    expect(sent(calls)).toEqual({
      name: "snapshots",
      format: "maven",
      type: "hosted",
      online: true,
      blob_store: "default",
      hosted: { deployment_policy: "allow_redeploy" },
      proxy: null,
      group: null,
      format_config: { version_policy: "snapshot", layout_policy: "strict" },
    });
    expect(notices()).toHaveTextContent("Created the repository snapshots.");
  });

  test("grows with what the type has, and shows nothing of another type", async () => {
    const user = userEvent.setup();
    fresh();

    expect(screen.getByRole("group", { name: "Deployment policy" })).toBeVisible();
    expect(screen.queryByLabelText("Remote address")).toBeNull();
    expect(
      screen.queryByRole("group", { name: "Members, in the order they are asked" }),
    ).toBeNull();

    await user.click(screen.getByRole("radio", { name: "Proxy" }));
    expect(screen.getByLabelText("Remote address")).toBeVisible();
    expect(screen.getByLabelText("Trust a cached file for (minutes)")).toHaveValue("1440");
    expect(screen.queryByRole("group", { name: "Deployment policy" })).toBeNull();
    expect(screen.getByRole("group", { name: "Layout policy" })).toBeVisible(); // Maven's own

    await user.click(screen.getByRole("radio", { name: "Group" }));
    expect(
      screen.getByRole("group", { name: "Members, in the order they are asked" }),
    ).toBeVisible();
    expect(screen.queryByLabelText("Remote address")).toBeNull();
    // A group stores nothing, and has no policy of its own.
    expect(screen.queryByLabelText("Blob store")).toBeNull();
    expect(screen.queryByRole("group", { name: "Layout policy" })).toBeNull();
    await expectAccessible();
  });

  test("has Maven's settings for Maven only", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "npm");
    expect(screen.queryByRole("group", { name: "Version policy" })).toBeNull();
    await user.type(screen.getByLabelText("Name"), "npm-team");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({ format: "npm", format_config: {} });
  });

  test("a proxy is made with its remote and how it signs in there", async () => {
    const user = userEvent.setup();
    const { calls, client } = fresh();

    await user.type(screen.getByLabelText("Name"), "mirror");
    await user.click(screen.getByRole("radio", { name: "Proxy" }));
    await user.type(screen.getByLabelText("Remote address"), "https://repo.example.org/maven2/");
    await user.selectOptions(screen.getByLabelText("Signs in to the remote with"), "basic");
    await user.type(screen.getByLabelText("User name"), "robot");
    const secret = screen.getByLabelText("Password");
    // Never shown as it is typed, and the browser is not to fill in one of its own.
    expect(secret).toHaveAttribute("type", "password");
    expect(secret).toHaveAttribute("autocomplete", "new-password");
    await user.type(secret, "the-remote-secret");
    await user.clear(screen.getByLabelText("Trust a cached file for (minutes)"));
    await user.type(screen.getByLabelText("Trust a cached file for (minutes)"), "-1");
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      type: "proxy",
      hosted: null,
      proxy: {
        remote_url: "https://repo.example.org/maven2/",
        content_max_age_minutes: -1,
        metadata_max_age_minutes: 1440,
        negative_cache: { enabled: true, ttl_minutes: 1440 },
        remote_auth: { type: "basic", username: "robot", secret: "the-remote-secret" },
        blocked: false,
        auto_block: true,
      },
    });
    // The secret went to the server and is kept nowhere here: the store lets go of the
    // request that carried it as soon as it is answered.
    await waitFor(() => expect(navigation.router.push).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        JSON.stringify(
          client
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state.variables),
        ),
      ).not.toContain("the-remote-secret"),
    );
  });

  test("a group is made of repositories of its own format, in the order they are put", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();

    await user.type(screen.getByLabelText("Name"), "public");
    await user.click(screen.getByRole("radio", { name: "Group" }));
    const candidates = () =>
      within(screen.getByLabelText("A repository to add"))
        .getAllByRole("option")
        .map((option) => option.textContent);
    // Not the npm one: a group is of one format. Another group can be a member.
    await waitFor(() => expect(candidates()).toEqual(["all", "central", "releases"]));
    await user.selectOptions(screen.getByLabelText("A repository to add"), "releases");
    await user.click(screen.getByRole("button", { name: "Add it" }));
    await user.selectOptions(screen.getByLabelText("A repository to add"), "central");
    await user.click(screen.getByRole("button", { name: "Add it" }));
    await user.click(screen.getByRole("button", { name: "Move central up" }));
    await user.click(create());

    await waitFor(() => expect(of(calls, "POST")).toHaveLength(1));
    expect(sent(calls)).toMatchObject({
      type: "group",
      blob_store: null,
      group: { members: ["central", "releases"] },
      format_config: {},
    });
  });

  test("members of one format are none of another: changing the format empties them", async () => {
    const user = userEvent.setup();
    fresh();
    await user.click(screen.getByRole("radio", { name: "Group" }));
    await waitFor(() => expect(screen.getByLabelText("A repository to add")).toBeVisible());
    await user.click(screen.getByRole("button", { name: "Add it" }));
    expect(members()).toHaveLength(1);

    await user.selectOptions(screen.getByLabelText("Format"), "npm");

    expect(members()).toHaveLength(0);
    expect(
      within(screen.getByLabelText("A repository to add")).getAllByRole("option"),
    ).toHaveLength(1); // npm-own
  });

  test("says what is wrong with what was typed, at each press at the first field that is wrong", async () => {
    const user = userEvent.setup();
    const { calls } = fresh();
    await user.click(screen.getByRole("radio", { name: "Proxy" }));

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A repository's name is 1 to 64 letters, digits or . _ -",
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();

    await user.type(screen.getByLabelText("Name"), "mirror");
    await user.type(screen.getByLabelText("Remote address"), "repo.example.org");
    await user.click(create());
    expect(screen.getByLabelText("Remote address")).toHaveFocus();
    expect(screen.getByLabelText("Remote address")).toHaveAccessibleDescription(
      expect.stringContaining("Give an http or https address"),
    );
    expect(of(calls, "POST")).toHaveLength(0);
  });

  test("a Docker repository is named as images are, and one called . is none", async () => {
    const user = userEvent.setup();
    fresh();

    await user.selectOptions(screen.getByLabelText("Format"), "docker");
    await user.type(screen.getByLabelText("Name"), "Images");
    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      expect.stringContaining("the first part of its images' names"),
    );

    await user.clear(screen.getByLabelText("Name"));
    await user.type(screen.getByLabelText("Name"), "..");
    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A repository cannot be called . or .. : it would have no address.",
    );
  });

  test("says what the server refuses where it belongs, or whole", async () => {
    const user = userEvent.setup();
    const attempt = async () => {
      await user.type(screen.getByLabelText("Name"), "mirror");
      await user.click(screen.getByRole("radio", { name: "Proxy" }));
      await user.type(screen.getByLabelText("Remote address"), "https://repo.example.org");
      await user.click(create());
    };
    const first = fresh({
      "POST /repositories": failure(409, "conflict", "A repository named mirror already exists."),
    });
    await attempt();
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A repository named mirror already exists.",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    first.unmount();

    const second = fresh({
      "POST /repositories": failure(422, "validation_error", "The request is not valid.", [
        { field: "proxy.remote_url", message: "Must be an http or https URL with a host." },
      ]),
    });
    await attempt();
    await waitFor(() =>
      expect(screen.getByLabelText("Remote address")).toHaveAccessibleDescription(
        "Must be an http or https URL with a host.",
      ),
    );
    second.unmount();

    fresh({
      "POST /repositories": failure(
        409,
        "repository_cycle",
        "A group cannot contain itself, directly or indirectly.",
      ),
    });
    await attempt();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A group cannot contain itself, directly or indirectly.",
    );
    expect(navigation.router.push).not.toHaveBeenCalled();
  });

  test("offers the blob stores there are, or the default one where they may not be seen", async () => {
    const first = fresh();
    const choices = () =>
      within(screen.getByLabelText("Blob store"))
        .getAllByRole("option")
        .map((option) => option.textContent);
    await waitFor(() => expect(choices()).toEqual(["default", "fast"]));
    first.unmount();

    const { calls } = fresh({}, holding("admin:repositories:read", "admin:repositories:write"));
    expect(choices()).toEqual(["default"]);
    expect(
      screen.getByText("You may not see the blob stores, so the default one is used."),
    ).toBeVisible();
    expect(calls.some((call) => call.path.startsWith("/blob-stores"))).toBe(false);
  });

  test("is not offered to whoever may not create one, though the address be typed", () => {
    fresh({}, holding("admin:repositories:read"));

    expect(screen.getByRole("alert")).toHaveTextContent("You may not create repositories.");
    expect(screen.queryByRole("button", { name: "Create repository" })).toBeNull();
  });
});

describe("the settings of a repository", () => {
  function settings(which = RELEASES, more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      [`GET /repositories/${which.name}`]: { json: which },
      "GET /repositories": { json: page([ALL, CENTRAL, NPM, RELEASES]) },
      ...more,
    });
    navigation.at(`/admin/repositories/${which.name}`);
    return { ...renderUi(<RepositorySettingsScreen />, { session }), ...api };
  }
  const save = () => screen.getByRole("button", { name: "Save" });

  test("show what cannot change as facts, and the rest as it is set (R3)", async () => {
    settings(repository("releases", { hosted: { deployment_policy: "read_only" } }));

    expect(await screen.findByRole("heading", { level: 1, name: "releases" })).toBeVisible();
    for (const fact of ["maven", "Hosted", "default", "release", "/repository/releases/"]) {
      expect(screen.getAllByText(fact)[0]).toBeVisible();
    }
    // Not fields: a field that cannot be changed is one that will be tried.
    expect(screen.queryByLabelText("Name")).toBeNull();
    expect(screen.queryByLabelText("Format")).toBeNull();
    expect(screen.queryByRole("radio", { name: "Proxy" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Version policy" })).toBeNull();
    expect(screen.queryByLabelText("Blob store")).toBeNull();
    expect(screen.getByRole("radio", { name: "Read only" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Online" })).toBeChecked();
    expect(screen.getByRole("link", { name: "Browse it" })).toHaveAttribute(
      "href",
      "/browse/releases",
    );
    await expectAccessible();
  });

  test("are saved as they stand, and say so", async () => {
    const user = userEvent.setup();
    const { calls } = settings(RELEASES, {
      "PUT /repositories/releases": { json: repository("releases", { online: false }) },
    });
    await screen.findByRole("radio", { name: "Allow redeploy" });

    await user.click(screen.getByRole("checkbox", { name: "Online" }));
    await user.click(screen.getByRole("radio", { name: "Disable redeploy" }));
    await user.click(screen.getByRole("radio", { name: "Permissive" }));
    await user.click(save());

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the repository releases."));
    expect(of(calls, "PUT")[0]?.body).toEqual({
      online: false,
      hosted: { deployment_policy: "disable_redeploy" },
      proxy: null,
      group: null,
      format_config: { version_policy: "release", layout_policy: "permissive" },
    });
    expect(save()).toHaveFocus();
  });

  test("of a proxy keep the secret that is stored, which is shown to nobody (R4)", async () => {
    const user = userEvent.setup();
    const { calls } = settings(CENTRAL, { "PUT /repositories/central": { json: CENTRAL } });
    const secret = await screen.findByLabelText("Password");

    expect(secret).toHaveValue("");
    expect(secret).toHaveAccessibleDescription(
      "One is stored. Leave this empty to keep it, or type another to replace it.",
    );
    expect(screen.getByLabelText("Remote address")).toHaveValue("https://repo.example.org/maven2");
    expect(screen.getByLabelText("User name")).toHaveValue("robot");
    await user.click(save());

    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
    expect(
      (of(calls, "PUT")[0]?.body as { proxy: { remote_auth: unknown } }).proxy.remote_auth,
    ).toEqual({ type: "basic", username: "robot", secret: null });
  });

  test("of a proxy send a secret that is typed, and then keep it nowhere", async () => {
    const user = userEvent.setup();
    const { calls, client } = settings(CENTRAL, {
      "PUT /repositories/central": { json: CENTRAL },
    });

    await user.type(await screen.findByLabelText("Password"), "another-secret");
    await user.click(save());

    await waitFor(() => expect(notices()).toHaveTextContent("Saved the repository central."));
    expect(JSON.stringify(of(calls, "PUT")[0]?.body)).toContain("another-secret");
    // The field starts again from what the server holds, and the store lets go of what was sent.
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await waitFor(() =>
      expect(
        JSON.stringify([
          client
            .getMutationCache()
            .getAll()
            .map((mutation) => mutation.state.variables),
          client
            .getQueryCache()
            .getAll()
            .map((query) => query.state.data),
        ]),
      ).not.toContain("another-secret"),
    );
  });

  test("say where the server wants the secret again", async () => {
    const user = userEvent.setup();
    settings(CENTRAL, {
      "PUT /repositories/central": failure(422, "validation_error", "The request is not valid.", [
        { field: "proxy.remote_auth.secret", message: "A secret is required." },
      ]),
    });
    const remote = await screen.findByLabelText("Remote address");

    await user.clear(remote);
    await user.type(remote, "https://other.example.org");
    await user.click(save());

    // The remote changed, so the server keeps the secret it was given for the old one to itself.
    await waitFor(() =>
      expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
        "A secret is required.",
      ),
    );
    expect(screen.getByLabelText("Password")).toHaveFocus();
  });

  test("of a proxy show what it last met at its remote, as text (R7)", async () => {
    const hostile = '<img src=x onerror="alert(1)"> 503 from https://repo.example.org';
    const { container } = settings(
      proxy(
        "central",
        {},
        { auto_blocked_until: "2099-01-01T00:00:00Z", failures: 4, last_error: hostile },
      ),
    );

    expect(await screen.findByText("Left alone after a failure")).toBeVisible();
    expect(screen.getByText(hostile)).toBeVisible();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("4")).toBeVisible();
    await expectAccessible();
  });

  test("of a proxy have everything checked again when asked", async () => {
    const user = userEvent.setup();
    const { calls } = settings(proxy("central", { blocked: true }, { blocked: true }), {
      "POST /repositories/central/invalidate-cache": { status: 204 },
    });

    expect(await screen.findByText("Blocked")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Check everything again" }));

    await waitFor(() =>
      expect(notices()).toHaveTextContent("central will check everything with its remote again."),
    );
    expect(of(calls, "POST").map((call) => call.path)).toEqual([
      "/repositories/central/invalidate-cache",
    ]);
  });

  test("rebuild the index and say what was found (R8)", async () => {
    const user = userEvent.setup();
    settings(RELEASES, {
      "POST /repositories/releases/rebuild-index": {
        json: { files: 120, moved: 2, components: 40, removed: 1 },
      },
    });

    await user.click(await screen.findByRole("button", { name: "Rebuild the index" }));

    expect(await screen.findByText("The index is rebuilt")).toBeVisible();
    expect(
      screen.getByText(
        "120 files looked at, 2 given to another component. 40 components looked at, 1 removed for having no file left.",
      ),
    ).toBeVisible();
  });

  test("of a group are its members, and it has no index and no remote", async () => {
    const user = userEvent.setup();
    const { calls } = settings(ALL, { "PUT /repositories/all": { json: ALL } });

    await screen.findByRole("group", { name: "Members, in the order they are asked" });
    expect(members()).toEqual(["releases", "central"]);
    expect(screen.queryByRole("heading", { name: "Rebuild the index" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "The remote" })).toBeNull();
    // Itself is not offered as a member of itself.
    expect(screen.queryByLabelText("A repository to add")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Move central up" }));
    await user.click(save());
    await waitFor(() => expect(of(calls, "PUT")).toHaveLength(1));
    expect(of(calls, "PUT")[0]?.body).toMatchObject({
      group: { members: ["central", "releases"] },
      format_config: {},
    });
  });

  test("open with what the server holds now, and not with what was fetched before (A23)", async () => {
    let policy = "allow_redeploy";
    const held = () => repository("releases", { hosted: { deployment_policy: policy } });
    const { rerender } = settings(RELEASES, {
      "GET /repositories/releases": () => ({ json: held() }),
    });
    expect(await screen.findByRole("radio", { name: "Allow redeploy" })).toBeChecked();

    rerender(<p>Elsewhere</p>);
    policy = "read_only";
    rerender(<RepositorySettingsScreen />);

    await waitFor(() => expect(screen.getByRole("radio", { name: "Read only" })).toBeChecked());
  });

  test("are shown, and not changed, by whoever may only read them", async () => {
    settings(CENTRAL, {}, holding("admin:repositories:read"));

    expect(await screen.findByLabelText("Remote address")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Check everything again" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Rebuild the index" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete repository" })).toBeNull();
    expect(screen.getByRole("heading", { name: "The remote" })).toBeVisible(); // its state can be seen
  });

  test("delete the repository only for whoever types its name, and say what goes with it (R9)", async () => {
    const user = userEvent.setup();
    const { calls } = settings(RELEASES, { "DELETE /repositories/releases": { status: 204 } });

    await user.click(await screen.findByRole("button", { name: "Delete repository" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the repository releases?" });
    expect(dialog).toHaveTextContent("Every component and file in it is deleted");
    const confirm = within(dialog).getByRole("button", { name: "Delete repository" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type releases to go on"), "releases");
    await user.click(confirm);

    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/admin/repositories"),
    );
    expect(notices()).toHaveTextContent("Deleted the repository releases.");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const since = calls.slice(calls.findIndex((call) => call.method === "DELETE") + 1);
    expect(since.filter((call) => call.path === "/repositories/releases")).toEqual([]);
  });

  test("say why when it could not be deleted, or is not there", async () => {
    const user = userEvent.setup();
    const first = settings(RELEASES, {
      "DELETE /repositories/releases": failure(
        409,
        "in_use",
        "The group all presents this repository.",
      ),
    });
    await user.click(await screen.findByRole("button", { name: "Delete repository" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type releases to go on"), "releases");
    await user.click(within(dialog).getByRole("button", { name: "Delete repository" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The group all presents this repository.",
    );
    first.unmount();

    settings(RELEASES, {
      "GET /repositories/releases": failure(404, "not_found", "No such repository."),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("This was not found.");
  });
});

describe("the blob stores (R10)", () => {
  function stores(more: Routes = {}, session = ADMIN) {
    const api = mockApi({ "GET /blob-stores": { json: page(STORES) }, ...more });
    navigation.at("/admin/blob-stores");
    return { ...renderUi(<BlobStoresScreen />, { session }), ...api };
  }
  const create = () => screen.getByRole("button", { name: "Create blob store" });

  test("are listed with what they hold and the space that is left", async () => {
    stores();

    const table = await screen.findByRole("table", { name: "Blob stores" });
    const rows = within(table).getAllByRole("row").slice(1);

    expect(rows[0]).toHaveTextContent("default");
    expect(rows[0]).toHaveTextContent("2.4 MiB");
    expect(rows[0]).toHaveTextContent("844 GiB");
    expect(rows[1]).toHaveTextContent("/mnt/fast");
    expect(rows[1]).toHaveTextContent("Not known"); // where the server cannot say
    await expectAccessible();
  });

  test("a new one needs a name, and a directory only if it is to be elsewhere", async () => {
    const user = userEvent.setup();
    const { calls } = stores({
      "POST /blob-stores": (call) => ({
        status: 201,
        json: store((call.body as { name: string }).name),
      }),
    });
    await screen.findByRole("table", { name: "Blob stores" });

    await user.click(create());
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "A blob store's name is 1 to 64 letters, digits or . _ -",
    );
    expect(screen.getByLabelText("Name")).toHaveFocus();
    expect(of(calls, "POST")).toHaveLength(0);

    await user.type(screen.getByLabelText("Name"), "second");
    await user.click(create());
    await waitFor(() => expect(notices()).toHaveTextContent("Created the blob store second."));
    expect(of(calls, "POST")[0]?.body).toEqual({ name: "second", type: "file", path: null });
    // Ready for another: empty, with nothing said to be wrong with it.
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-invalid");

    await user.type(screen.getByLabelText("Name"), "third");
    await user.type(screen.getByLabelText("Directory"), " /mnt/third ");
    await user.click(create());
    await waitFor(() => expect(of(calls, "POST")).toHaveLength(2));
    expect(of(calls, "POST")[1]?.body).toEqual({ name: "third", type: "file", path: "/mnt/third" });
  });

  test("says what the server refuses of a new one where it belongs", async () => {
    const user = userEvent.setup();
    const first = stores({
      "POST /blob-stores": failure(409, "conflict", "A blob store named fast already exists."),
    });
    await user.type(await screen.findByLabelText("Name"), "fast");
    await user.click(create());
    await waitFor(() =>
      expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
        "A blob store named fast already exists.",
      ),
    );
    first.unmount();

    stores({
      "POST /blob-stores": failure(422, "validation_error", "The request is not valid.", [
        { field: "path", message: "The directory overlaps the blob store default." },
      ]),
    });
    await user.type(await screen.findByLabelText("Name"), "inside");
    await user.type(screen.getByLabelText("Directory"), "default/inside");
    await user.click(create());
    await waitFor(() =>
      expect(screen.getByLabelText("Directory")).toHaveAccessibleDescription(
        "The directory overlaps the blob store default.",
      ),
    );
    expect(screen.getByLabelText("Directory")).toHaveFocus();
  });

  test("is deleted only by whoever types its name, and the keyboard is then at the list (R9)", async () => {
    const user = userEvent.setup();
    let held = STORES;
    const { calls } = stores({
      "GET /blob-stores": () => ({ json: page(held) }),
      "DELETE /blob-stores/fast": () => {
        held = [STORES[0] as (typeof STORES)[number]];
        return { status: 204 };
      },
    });

    await user.click(await screen.findByRole("button", { name: "Delete fast" }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete the blob store fast?" });
    expect(dialog).toHaveTextContent("Its files stay on the disk");
    const confirm = within(dialog).getByRole("button", { name: "Delete blob store" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Type fast to go on"), "fast");
    await user.click(confirm);

    await waitFor(() => expect(notices()).toHaveTextContent("Deleted the blob store fast."));
    expect(of(calls, "DELETE")).toHaveLength(1);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Delete fast" })).toBeNull());
    await waitFor(() => expect(screen.getByRole("group", { name: "Blob stores" })).toHaveFocus());
  });

  test("is not deleted while a repository uses it, and the screen says which", async () => {
    const user = userEvent.setup();
    stores({
      "DELETE /blob-stores/default": failure(
        409,
        "in_use",
        "The repository releases uses this blob store.",
      ),
    });

    await user.click(await screen.findByRole("button", { name: "Delete default" }));
    const dialog = screen.getByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Type default to go on"), "default");
    await user.click(within(dialog).getByRole("button", { name: "Delete blob store" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The repository releases uses this blob store.",
    );
  });

  test("are shown, and neither made nor deleted, by whoever may only read them", async () => {
    stores({}, holding("admin:blobstores:read"));

    await screen.findByRole("table", { name: "Blob stores" });

    expect(screen.queryByRole("button", { name: "Create blob store" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Delete/ })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Delete" })).toBeNull();
  });
});

describe("the system (R11)", () => {
  const INFORMATION = {
    version: "0.1.0",
    schema: { revision: "0007", expected: "0007", current: true },
    runtime: {
      python: "3.13.1",
      platform: "Linux-6.6-x86_64-with-glibc2.41",
      started_at: "2026-10-12T08:00:00Z",
    },
    database: { version: "PostgreSQL 17.2" },
  };
  function system(more: Routes = {}, session = ADMIN) {
    const api = mockApi({
      "GET /system/information": { json: INFORMATION },
      "GET /settings": { json: { base_url: null, anonymous_access: { enabled: false } } },
      "GET /blob-stores": { json: page(STORES) },
      "GET /content": { json: page([]) },
      ...more,
    });
    navigation.at("/admin/system");
    return { ...renderUi(<SystemScreen />, { session }), ...api };
  }
  const field = () => screen.getByLabelText("The address of this server, as its clients reach it");

  test("says what is running, and that the schema is the one this version expects", async () => {
    system();

    expect(await screen.findByText("As this version expects")).toBeVisible();
    for (const said of [
      "0.1.0",
      "0007",
      "3.13.1",
      "Linux-6.6-x86_64-with-glibc2.41",
      "PostgreSQL 17.2",
    ]) {
      expect(screen.getByText(said)).toBeVisible();
    }
    // And the blob stores' state, for whoever may see them.
    const table = await screen.findByRole("table", { name: "Blob stores" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).queryByRole("button")).toBeNull(); // they are managed on their own page
    expect(screen.getByRole("link", { name: "Manage the blob stores" })).toHaveAttribute(
      "href",
      "/admin/blob-stores",
    );
    await expectAccessible();
  });

  test("says so when the schema is another one, and which this version expects", async () => {
    system({
      "GET /system/information": {
        json: { ...INFORMATION, schema: { revision: "0005", expected: "0007", current: false } },
      },
    });

    expect(await screen.findByText("This version expects 0007")).toBeVisible();
    expect(screen.getByText("0005")).toBeVisible();
    expect(screen.queryByText("As this version expects")).toBeNull();
  });

  test("sets the base URL, as the server then keeps it", async () => {
    const user = userEvent.setup();
    const { calls } = system({
      "PUT /settings/base-url": {
        json: { base_url: "https://repo.example.org", anonymous_access: { enabled: false } },
      },
    });
    await waitFor(() => expect(field()).toHaveValue(""));

    await user.type(field(), "repo.example.org");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(field()).toHaveAccessibleDescription(
      "Give an http or https address, without a query or a fragment.",
    );
    expect(field()).toHaveFocus();
    expect(of(calls, "PUT")).toHaveLength(0);

    await user.clear(field());
    await user.type(field(), " https://repo.example.org/ ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("The base URL is saved."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ base_url: "https://repo.example.org/" });
    expect(field()).toHaveValue("https://repo.example.org"); // without the slash, as it is kept
  });

  test("clears the base URL when the field is emptied", async () => {
    const user = userEvent.setup();
    const { calls } = system({
      "GET /settings": {
        json: { base_url: "https://repo.example.org", anonymous_access: { enabled: false } },
      },
      "PUT /settings/base-url": {
        json: { base_url: null, anonymous_access: { enabled: false } },
      },
    });
    await waitFor(() => expect(field()).toHaveValue("https://repo.example.org"));

    await user.clear(field());
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(notices()).toHaveTextContent("The base URL is cleared."));
    expect(of(calls, "PUT")[0]?.body).toEqual({ base_url: null });
  });

  test("says what the server refuses of the base URL at its field", async () => {
    const user = userEvent.setup();
    system({
      "PUT /settings/base-url": failure(422, "validation_error", "The request is not valid.", [
        { field: "body.base_url", message: "Value error, must be an http or https URL" },
      ]),
    });
    await waitFor(() => expect(field()).toHaveValue(""));

    await user.type(field(), "https://repo.example.org");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(field()).toHaveAccessibleDescription("Value error, must be an http or https URL"),
    );
  });

  test("shows the base URL, and not the blob stores, to whoever may only read the settings", async () => {
    const { calls } = system({}, holding("admin:settings:read"));

    await waitFor(() => expect(field()).toBeDisabled());

    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("table", { name: "Blob stores" })).toBeNull();
    expect(calls.some((call) => call.path.startsWith("/blob-stores"))).toBe(false);
  });

  test("says what went wrong when the information cannot be had", async () => {
    system({ "GET /system/information": failure(500, "internal_error", "Oops.") });

    expect(await screen.findByRole("alert")).toHaveTextContent("The server met a fault.");
  });
});
```

Change `frontend/src/screens/browse.test.tsx`:

```diff
@@ -270,6 +270,20 @@ describe("a group", () => {
     await expectAccessible();
   });
 
+  test("leads to its settings for whoever may see them, and for nobody else (R1)", async () => {
+    server();
+    const administrator = at("/browse/releases");
+    expect(await screen.findByRole("link", { name: "Settings" })).toHaveAttribute(
+      "href",
+      "/admin/repositories/releases",
+    );
+    administrator.unmount();
+
+    at("/browse/releases", READER);
+    await screen.findByRole("heading", { level: 1, name: "releases" });
+    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
+  });
+
   test("of any other kind offers a search in it", async () => {
     server();
     at("/browse/releases");
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pnpm test`
Expected: 1 test fails and 1 file does not load. In `browse.test.tsx`: "leads to its settings for whoever may see them, and for nobody else (R1)". `administration.test.tsx` fails with `Failed to resolve import` of one of the four screens.

- [ ] **Step 3: Implement**

Create `frontend/src/screens/manage-repositories.tsx`:

```tsx
"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Pager } from "@/components/ui/details";
import { AppLink } from "@/components/ui/link";
import { PageHeader, Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import { AT_ONCE, useManagedRepositories } from "@/lib/administration";
import type { RepositoryOut } from "@/lib/api/types";
import { usePageFocus, useWithinPages } from "@/lib/focus";
import {
  isAddressable,
  MANAGE_REPOSITORIES,
  NEW_REPOSITORY,
  pageHref,
  pageOf,
  repositorySettingsHref,
} from "@/lib/paths";
import { TYPES, type RepositoryType } from "@/lib/repository-form";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

/** Whether a repository answers, in a word or two, each with its own mark. */
function State({ repository, now }: { repository: RepositoryOut; now: number }) {
  const t = useTranslations("manage");
  const until = repository.status?.auto_blocked_until ?? null;
  return (
    <div className="flex flex-wrap gap-1.5">
      <StatusTag tone={repository.online ? "success" : "warning"}>
        {repository.online ? t("online") : t("offline")}
      </StatusTag>
      {repository.status?.blocked ? (
        <StatusTag tone="warning">{t("state.blocked")}</StatusTag>
      ) : until !== null && new Date(until).getTime() > now ? (
        <StatusTag tone="warning">{t("state.waiting")}</StatusTag>
      ) : null}
    </div>
  );
}

/**
 * Every repository as it is set up (R1): the administrator's list, beside the one for
 * browsing. From here a repository's settings are opened, and a new one is made.
 */
export function ManageRepositoriesScreen() {
  const t = useTranslations("manage");
  const session = useSession();
  const page = pageOf(useSearchParams());
  const repositories = useManagedRepositories(page);
  const mayWrite = session.data !== undefined && allows(session.data, "admin:repositories:write");
  const pages =
    repositories.data === undefined ? undefined : Math.ceil(repositories.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(MANAGE_REPOSITORIES, target);
  const top = usePageFocus<HTMLDivElement>(page, repositories.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);
  // Read once, when the list is shown: whether a proxy is still left alone.
  const [now] = useState(() => Date.now());
  const create = (
    <Button asChild variant="primary" size="sm">
      <AppLink href={NEW_REPOSITORY}>
        <Plus aria-hidden="true" className="size-4" />
        {t("new")}
      </AppLink>
    </Button>
  );

  return (
    <>
      <PageHeader title={t("title")} intro={t("intro")}>
        {mayWrite ? create : null}
      </PageHeader>
      {repositories.isError ? (
        <ErrorState error={repositories.error} onRetry={() => void repositories.refetch()} />
      ) : !repositories.data || beyond ? (
        <Panel>
          <LoadingState />
        </Panel>
      ) : repositories.data.total === 0 ? (
        <Panel>
          <EmptyState title={t("emptyTitle")} action={mayWrite ? create : undefined}>
            {t("empty")}
          </EmptyState>
        </Panel>
      ) : (
        <Panel>
          {/* Named, and able to take the keyboard: it is put here when a page is turned. */}
          <div
            ref={top}
            tabIndex={-1}
            role="group"
            aria-label={t("title")}
            className="outline-none"
          >
            <Table caption={t("title")}>
              <thead>
                <tr>
                  <Th>{t("columns.name")}</Th>
                  <Th>{t("columns.format")}</Th>
                  <Th>{t("columns.type")}</Th>
                  <Th>{t("columns.state")}</Th>
                  <Th>{t("columns.blobStore")}</Th>
                </tr>
              </thead>
              <tbody>
                {repositories.data.items.map((repository) => (
                  <tr key={repository.name} className="hover:bg-raised">
                    <Td>
                      {isAddressable(repository.name) ? (
                        <AppLink
                          href={repositorySettingsHref(repository.name)}
                          className="font-mono font-medium break-all text-ink-cyan underline-offset-4 hover:underline"
                        >
                          {repository.name}
                        </AppLink>
                      ) : (
                        <span className="font-mono font-medium text-fg">{repository.name}</span>
                      )}
                    </Td>
                    <Td>{repository.format}</Td>
                    <Td>
                      {(TYPES as readonly string[]).includes(repository.type)
                        ? t(`types.${repository.type as RepositoryType}`)
                        : repository.type}
                    </Td>
                    <Td>
                      <State repository={repository} now={now} />
                    </Td>
                    <Td className="font-mono text-xs break-all text-fg-muted">
                      {repository.blob_store}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
          <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
        </Panel>
      )}
    </>
  );
}
```

Create `frontend/src/screens/repository-settings.tsx`:

```tsx
"use client";

import { FolderOpen, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { MemberList } from "@/components/member-list";
import { Alert, StatusTag } from "@/components/ui/alert";
import { Breadcrumbs } from "@/components/ui/breadcrumbs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Fact, Facts, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { CheckboxField, ChoiceGroup, SelectField } from "@/components/ui/inputs";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import {
  useCreateRepository,
  useDeleteRepository,
  useEveryBlobStore,
  useEveryManagedRepository,
  useInvalidateCache,
  useManagedRepository,
  useRebuildIndex,
  useUpdateRepository,
} from "@/lib/administration";
import { isApiError } from "@/lib/api/client";
import type { RepositoryOut } from "@/lib/api/types";
import { useAttempts } from "@/lib/focus";
import {
  browseHref,
  MANAGE_REPOSITORIES,
  NEW_REPOSITORY,
  parseRepositorySettings,
  repositorySettingsHref,
} from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import {
  AUTH_TYPES,
  createBody,
  DEFAULT_BLOB_STORE,
  DEPLOYMENT_POLICIES,
  draftOf,
  EMPTY,
  FORMATS,
  hasMavenSettings,
  LAYOUT_POLICIES,
  problemsOf,
  TYPES,
  updateBody,
  VERSION_POLICIES,
  type Draft,
  type RepositoryType,
} from "@/lib/repository-form";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { NothingHere } from "@/screens/not-found";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";
const SECTION = "flex min-w-0 flex-col gap-4 rounded-sm border border-line p-4";
const LEGEND = "label-caps px-1 text-fg-muted";

// The server's own names for what it refuses, the closest first: a refusal is put at
// the first of these it is about, or under.
const REFUSED_AT = [
  "name",
  "blob_store",
  "hosted.deployment_policy",
  "proxy.remote_url",
  "proxy.content_max_age_minutes",
  "proxy.metadata_max_age_minutes",
  "proxy.negative_cache.ttl_minutes",
  "proxy.remote_auth.username",
  "proxy.remote_auth.secret",
  "group.members",
  "format_config.version_policy",
  "format_config.layout_policy",
] as const;

function useMay(): (permission: string) => boolean {
  const session = useSession();
  return (permission) => session.data !== undefined && allows(session.data, permission);
}

/**
 * The form of a repository, new or not: one page that grows (R2). The format and the
 * type decide which parts it has. `repository` is the one that is there, or null for a
 * new one, which also has what can be chosen only once. `onSave` is given what the
 * form holds once nothing is wrong with it, and answers with the repository as the
 * server then has it, from which the form starts again.
 */
function RepositoryForm({
  repository,
  saving,
  error,
  onSave,
  saveLabel,
  mayWrite,
}: {
  repository: RepositoryOut | null;
  saving: boolean;
  error: unknown;
  onSave: (draft: Draft) => Promise<RepositoryOut | null>;
  saveLabel: string;
  mayWrite: boolean;
}) {
  const t = useTranslations("manage");
  const may = useMay();
  const creating = repository === null;
  const [draft, setDraft] = useState<Draft>(() => (repository ? draftOf(repository) : EMPTY));
  const set = (change: Partial<Draft>) => setDraft((held) => ({ ...held, ...change }));
  const { form, tried, attempt } = useAttempts(error);
  const storesReadable = may("admin:blobstores:read");
  const stores = useEveryBlobStore(creating && storesReadable);
  const others = useEveryManagedRepository();

  const own = problemsOf(draft, creating);
  const refused = refusalsOf(error, REFUSED_AT);
  // A name another repository has: said at the name.
  const taken = isApiError(error) && error.code === "conflict" ? error.message : null;
  const wrong = (field: keyof typeof own, server?: string) =>
    tried ? (own[field] ? t(`problems.${own[field]}`) : server) : undefined;

  async function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    if (Object.keys(own).length > 0) return;
    const saved = await onSave(draft);
    // What the server holds now: its own spelling of the remote, and no secret typed.
    if (saved !== null) setDraft(draftOf(saved));
  }

  const { type } = draft;
  const storeNames = Array.from(
    new Set([DEFAULT_BLOB_STORE, ...(stores.data?.items.map((store) => store.name) ?? [])]),
  );
  const candidates = (others.data?.items ?? [])
    .filter((other) => other.format === draft.format && other.name !== repository?.name)
    .map((other) => other.name);
  const option = <Value extends string>(group: string, values: readonly Value[]) =>
    values.map((value) => ({
      value,
      label: t(`${group}.${value}` as "types.hosted"),
      hint: t(`${group}Hints.${value}` as "typesHints.hosted"),
    }));

  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <fieldset disabled={!mayWrite} className="flex min-w-0 flex-col gap-6 border-0 p-0">
        {creating ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                label={t("fields.format")}
                value={draft.format}
                // The members of a group are of its format: those of another are none.
                onChange={(event) => set({ format: event.target.value, members: [] })}
                choices={FORMATS.map((format) => ({ value: format, label: format }))}
              />
              <TextField
                label={t("fields.name")}
                hint={t("hints.name")}
                required
                spellCheck={false}
                autoComplete="off"
                value={draft.name}
                error={wrong("name", taken ?? refused.at.name)}
                onChange={(event) => set({ name: event.target.value })}
              />
            </div>
            <ChoiceGroup
              legend={t("fields.type")}
              value={type}
              onChange={(value) => set({ type: value as RepositoryType })}
              options={option("types", TYPES)}
            />
          </>
        ) : null}
        <CheckboxField
          label={t("fields.online")}
          hint={t("hints.online")}
          checked={draft.online}
          onChange={(event) => set({ online: event.target.checked })}
        />
        {creating && type !== "group" ? (
          <div className="flex flex-col gap-1.5">
            <SelectField
              label={t("fields.blobStore")}
              value={draft.blobStore}
              onChange={(event) => set({ blobStore: event.target.value })}
              choices={storeNames.map((name) => ({ value: name, label: name }))}
            />
            <p className="text-sm text-fg-subtle">
              {storesReadable ? t("hints.blobStore") : t("hints.blobStoreUnreadable")}
            </p>
            {refused.at.blob_store ? <Alert tone="danger">{refused.at.blob_store}</Alert> : null}
          </div>
        ) : null}

        {type === "hosted" ? (
          <fieldset className={SECTION}>
            <legend className={LEGEND}>{t("sections.hosted")}</legend>
            <ChoiceGroup
              legend={t("fields.deploymentPolicy")}
              value={draft.deploymentPolicy}
              onChange={(value) => set({ deploymentPolicy: value })}
              options={option("policies", DEPLOYMENT_POLICIES)}
            />
            {refused.at["hosted.deployment_policy"] ? (
              <Alert tone="danger">{refused.at["hosted.deployment_policy"]}</Alert>
            ) : null}
          </fieldset>
        ) : null}

        {type === "proxy" ? (
          <>
            <fieldset className={SECTION}>
              <legend className={LEGEND}>{t("sections.remote")}</legend>
              <TextField
                label={t("fields.remoteUrl")}
                hint={t("hints.remoteUrl")}
                type="url"
                required
                spellCheck={false}
                autoComplete="off"
                value={draft.remoteUrl}
                error={wrong("remoteUrl", refused.at["proxy.remote_url"])}
                onChange={(event) => set({ remoteUrl: event.target.value })}
              />
              <SelectField
                label={t("fields.authType")}
                value={draft.authType}
                onChange={(event) => set({ authType: event.target.value })}
                choices={AUTH_TYPES.map((kind) => ({ value: kind, label: t(`auth.${kind}`) }))}
              />
              {draft.authType === "basic" ? (
                <TextField
                  label={t("fields.authUsername")}
                  spellCheck={false}
                  autoComplete="off"
                  value={draft.authUsername}
                  error={wrong("authUsername", refused.at["proxy.remote_auth.username"])}
                  onChange={(event) => set({ authUsername: event.target.value })}
                />
              ) : null}
              {draft.authType !== "none" ? (
                <TextField
                  label={draft.authType === "basic" ? t("fields.password") : t("fields.token")}
                  // Never shown: the server gives it back to nobody (R4).
                  hint={draft.hasSecret ? t("hints.secretStored") : t("hints.secret")}
                  type="password"
                  autoComplete="new-password"
                  spellCheck={false}
                  value={draft.authSecret}
                  error={wrong("authSecret", refused.at["proxy.remote_auth.secret"])}
                  onChange={(event) => set({ authSecret: event.target.value })}
                />
              ) : null}
            </fieldset>
            <fieldset className={SECTION}>
              <legend className={LEGEND}>{t("sections.cache")}</legend>
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField
                  label={t("fields.contentMaxAge")}
                  hint={t("hints.maxAge")}
                  inputMode="numeric"
                  value={draft.contentMaxAge}
                  error={wrong("contentMaxAge", refused.at["proxy.content_max_age_minutes"])}
                  onChange={(event) => set({ contentMaxAge: event.target.value })}
                />
                <TextField
                  label={t("fields.metadataMaxAge")}
                  hint={t("hints.metadataMaxAge")}
                  inputMode="numeric"
                  value={draft.metadataMaxAge}
                  error={wrong("metadataMaxAge", refused.at["proxy.metadata_max_age_minutes"])}
                  onChange={(event) => set({ metadataMaxAge: event.target.value })}
                />
              </div>
              <CheckboxField
                label={t("fields.negativeCache")}
                hint={t("hints.negativeCache")}
                checked={draft.negativeCache}
                onChange={(event) => set({ negativeCache: event.target.checked })}
              />
              {draft.negativeCache ? (
                <TextField
                  label={t("fields.negativeCacheTtl")}
                  inputMode="numeric"
                  value={draft.negativeCacheTtl}
                  error={wrong("negativeCacheTtl", refused.at["proxy.negative_cache.ttl_minutes"])}
                  onChange={(event) => set({ negativeCacheTtl: event.target.value })}
                />
              ) : null}
            </fieldset>
            <fieldset className={SECTION}>
              <legend className={LEGEND}>{t("sections.blocking")}</legend>
              <CheckboxField
                label={t("fields.autoBlock")}
                hint={t("hints.autoBlock")}
                checked={draft.autoBlock}
                onChange={(event) => set({ autoBlock: event.target.checked })}
              />
              <CheckboxField
                label={t("fields.blocked")}
                hint={t("hints.blocked")}
                checked={draft.blocked}
                onChange={(event) => set({ blocked: event.target.checked })}
              />
            </fieldset>
          </>
        ) : null}

        {type === "group" ? (
          <div className="rounded-sm border border-line p-4">
            <MemberList
              legend={t("fields.members")}
              hint={t("hints.members")}
              members={draft.members}
              onChange={(members) => set({ members })}
              candidates={candidates}
              error={refused.at["group.members"]}
            />
          </div>
        ) : null}

        {hasMavenSettings(draft) ? (
          <fieldset className={SECTION}>
            <legend className={LEGEND}>{t("sections.maven")}</legend>
            {creating ? (
              <ChoiceGroup
                legend={t("fields.versionPolicy")}
                value={draft.versionPolicy}
                onChange={(value) => set({ versionPolicy: value })}
                options={option("versions", VERSION_POLICIES)}
              />
            ) : null}
            <ChoiceGroup
              legend={t("fields.layoutPolicy")}
              value={draft.layoutPolicy}
              onChange={(value) => set({ layoutPolicy: value })}
              options={option("layouts", LAYOUT_POLICIES)}
            />
            {refused.at["format_config.layout_policy"] ? (
              <Alert tone="danger">{refused.at["format_config.layout_policy"]}</Alert>
            ) : null}
          </fieldset>
        ) : null}
      </fieldset>
      {error && taken === null && refused.elsewhere ? <ErrorState error={error} /> : null}
      {mayWrite ? (
        <div>
          <Button type="submit" variant="primary" busy={saving}>
            {saveLabel}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

/** A new repository (R2, R13). */
export function NewRepositoryScreen() {
  const t = useTranslations("manage");
  const router = useRouter();
  const notify = useNotify();
  const may = useMay();
  const create = useCreateRepository();
  const mayCreate = may("admin:repositories:write");
  return (
    <div className="mx-auto max-w-4xl">
      <Breadcrumbs
        label={t("path")}
        crumbs={[
          { name: t("title"), href: MANAGE_REPOSITORIES },
          { name: t("newTitle"), href: NEW_REPOSITORY },
        ]}
      />
      <PageHeader title={t("newTitle")} intro={t("newIntro")} />
      {mayCreate ? (
        <Panel className="p-6">
          <RepositoryForm
            repository={null}
            mayWrite
            saving={create.isPending}
            error={create.error}
            saveLabel={t("create")}
            onSave={async (draft) => {
              try {
                const made = await create.mutateAsync(createBody(draft));
                // What was sent may have had a secret in it: the store lets go of it.
                create.reset();
                notify(t("created", { name: made.name }));
                router.push(repositorySettingsHref(made.name));
              } catch {
                // Said by the form, from the request's own state.
              }
              return null;
            }}
          />
        </Panel>
      ) : (
        // The address can be typed by anybody. The server would refuse what was filled in.
        <Alert tone="warning">{t("mayNotCreate")}</Alert>
      )}
    </div>
  );
}

/** What a proxy last met at its remote (R7), and a way to have everything checked again. */
function ProxyState({ repository, mayWrite }: { repository: RepositoryOut; mayWrite: boolean }) {
  const t = useTranslations("manage");
  const notify = useNotify();
  const invalidate = useInvalidateCache(repository.name);
  const status = repository.status;
  // Read once, when the state is shown: a block that ends while the page is open is
  // seen to have ended the next time the page is.
  const [now] = useState(() => Date.now());
  const until = status?.auto_blocked_until ?? null;
  const waiting = until !== null && new Date(until).getTime() > now;
  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("stateTitle")}</h2>
      <Facts className="mb-5">
        <Fact name={t("state.remote")}>
          {status?.blocked ? (
            <StatusTag tone="warning">{t("state.blocked")}</StatusTag>
          ) : waiting ? (
            <StatusTag tone="warning">{t("state.waiting")}</StatusTag>
          ) : (
            <StatusTag tone="success">{t("state.reachable")}</StatusTag>
          )}
        </Fact>
        {waiting ? (
          <Fact name={t("state.until")}>
            <Time value={until} />
          </Fact>
        ) : null}
        <Fact name={t("state.failures")}>{status?.failures ?? 0}</Fact>
        {status?.last_error ? (
          <Fact name={t("state.lastError")} mono>
            {status.last_error}
          </Fact>
        ) : null}
      </Facts>
      {invalidate.isError ? <ErrorState error={invalidate.error} className="mb-4" /> : null}
      {mayWrite ? (
        <>
          <p className="mb-3 text-fg-muted">{t("checkAgainIntro")}</p>
          <Button
            busy={invalidate.isPending}
            onClick={() =>
              invalidate.mutate(undefined, {
                onSuccess: () => notify(t("checkedAgain", { name: repository.name })),
              })
            }
          >
            <RefreshCw aria-hidden="true" className="size-4" />
            {t("checkAgain")}
          </Button>
        </>
      ) : null}
    </Panel>
  );
}

/** Going through a repository again (R8). It is done in the request: the button waits for it. */
function RebuildIndex({ repository }: { repository: RepositoryOut }) {
  const t = useTranslations("manage");
  const rebuild = useRebuildIndex(repository.name);
  return (
    <Panel className="p-6">
      <h2 className={H2}>{t("rebuildTitle")}</h2>
      <p className="mb-4 text-fg-muted">{t("rebuildIntro")}</p>
      {rebuild.isError ? <ErrorState error={rebuild.error} className="mb-4" /> : null}
      {rebuild.data ? (
        <Alert tone="success" title={t("rebuilt")} className="mb-4">
          {t("rebuiltFound", rebuild.data)}
        </Alert>
      ) : null}
      <Button busy={rebuild.isPending} onClick={() => rebuild.mutate()}>
        <RefreshCw aria-hidden="true" className="size-4" />
        {t("rebuild")}
      </Button>
    </Panel>
  );
}

/** One repository as an administrator sees it: its settings, its state, and deleting it. */
export function RepositorySettingsScreen() {
  const t = useTranslations("manage");
  const router = useRouter();
  const notify = useNotify();
  const may = useMay();
  const where = parseRepositorySettings(usePathname());
  const remove = useDeleteRepository();
  // Once deleted, the repository is not asked for again: there is none to answer with.
  const repository = useManagedRepository(remove.isSuccess ? null : (where?.name ?? null));
  const update = useUpdateRepository(where?.name ?? "");
  const [asking, setAsking] = useState(false);

  if (where === null) return <NothingHere />;
  if (repository.isError) {
    return <ErrorState error={repository.error} onRetry={() => void repository.refetch()} />;
  }
  // The form is filled once, when it opens, so it opens on an answer that came after
  // the page did (A23).
  if (!repository.data || !repository.isFetchedAfterMount) return <LoadingState />;

  const found = repository.data;
  const mayWrite = may("admin:repositories:write");
  const typeName = (TYPES as readonly string[]).includes(found.type)
    ? t(`types.${found.type as RepositoryType}`)
    : found.type;
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <div>
        <Breadcrumbs
          label={t("path")}
          crumbs={[
            { name: t("title"), href: MANAGE_REPOSITORIES },
            { name: found.name, href: repositorySettingsHref(found.name) },
          ]}
        />
        <PageHeader named title={found.name} intro={t("settingsOf")}>
          <Button asChild size="sm" variant="ghost">
            <AppLink href={browseHref(found.name)}>
              <FolderOpen aria-hidden="true" className="size-4" />
              {t("browse")}
            </AppLink>
          </Button>
        </PageHeader>
      </div>
      <Panel className="p-6">
        {/* What cannot change is a fact, not a field (R3). */}
        <Facts className="mb-6">
          <Fact name={t("fields.format")}>{found.format}</Fact>
          <Fact name={t("fields.type")}>{typeName}</Fact>
          {found.blob_store ? (
            <Fact name={t("fields.blobStore")} mono>
              {found.blob_store}
            </Fact>
          ) : null}
          {hasMavenSettings(draftOf(found)) ? (
            <Fact name={t("fields.versionPolicy")}>
              {String(found.format_config.version_policy ?? "")}
            </Fact>
          ) : null}
          <Fact name={t("fields.address")} copy={found.url_path} mono>
            {found.url_path}
          </Fact>
        </Facts>
        <RepositoryForm
          repository={found}
          mayWrite={mayWrite}
          saving={update.isPending}
          error={update.error}
          saveLabel={t("save")}
          onSave={async (draft) => {
            try {
              const saved = await update.mutateAsync(updateBody(draft));
              notify(t("saved", { name: saved.name }));
              // What was sent may have had a secret in it: the store lets go of it.
              update.reset();
              return saved;
            } catch {
              return null; // said by the form, from the request's own state
            }
          }}
        />
      </Panel>
      {found.type === "proxy" ? <ProxyState repository={found} mayWrite={mayWrite} /> : null}
      {mayWrite && found.type !== "group" ? <RebuildIndex repository={found} /> : null}
      {mayWrite ? (
        <Panel className="p-6">
          <h2 className={H2}>{t("deleteTitle")}</h2>
          <p className="mb-4 text-fg-muted">
            {found.type === "group" ? t("deleteIntroGroup") : t("deleteIntro")}
          </p>
          {remove.isError ? <ErrorState error={remove.error} className="mb-4" /> : null}
          <Button
            variant="danger"
            onClick={() => {
              remove.reset();
              setAsking(true);
            }}
          >
            <Trash2 aria-hidden="true" className="size-4" />
            {t("delete")}
          </Button>
          <ConfirmDialog
            open={asking}
            onOpenChange={setAsking}
            title={t("deleteAsk", { name: found.name })}
            confirmLabel={t("delete")}
            mustType={found.name}
            busy={remove.isPending}
            onConfirm={() =>
              remove.mutate(found.name, {
                onSuccess: () => {
                  notify(t("deleted", { name: found.name }));
                  router.replace(MANAGE_REPOSITORIES);
                },
                onSettled: () => setAsking(false),
              })
            }
          >
            {found.type === "group" ? t("deleteBodyGroup") : t("deleteBody")}
          </ConfirmDialog>
        </Panel>
      ) : null}
    </div>
  );
}
```

Create `frontend/src/screens/blob-stores.tsx`:

```tsx
"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Pager } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { Table, Td, Th } from "@/components/ui/table";
import {
  AT_ONCE,
  useBlobStores,
  useCreateBlobStore,
  useDeleteBlobStore,
} from "@/lib/administration";
import { isApiError } from "@/lib/api/client";
import type { BlobStoreOut } from "@/lib/api/types";
import { useAttempts, usePageFocus, useWithinPages } from "@/lib/focus";
import { formatBytes } from "@/lib/format";
import { BLOB_STORES, pageHref, pageOf } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";

// The server's rule for a name, said before the request is made.
const NAME = /^[A-Za-z0-9_.-]{1,64}$/;
const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

/** What a blob store holds, as columns. Used by the system page as well. */
export function BlobStoreTable({
  caption,
  stores,
  onDelete,
}: {
  caption: string;
  stores: BlobStoreOut[];
  /** Without it, the stores can be seen and not deleted. */
  onDelete?: (store: BlobStoreOut) => void;
}) {
  const t = useTranslations("blobStores");
  return (
    <Table caption={caption}>
      <thead>
        <tr>
          <Th>{t("columns.name")}</Th>
          <Th>{t("columns.directory")}</Th>
          <Th className="text-right">{t("columns.blobs")}</Th>
          <Th className="text-right">{t("columns.size")}</Th>
          <Th className="text-right">{t("columns.available")}</Th>
          {onDelete ? <Th className="text-right">{t("columns.actions")}</Th> : null}
        </tr>
      </thead>
      <tbody>
        {stores.map((store) => (
          <tr key={store.name} className="hover:bg-raised">
            <Td className="font-mono font-medium break-all">{store.name}</Td>
            <Td className="font-mono text-xs break-all text-fg-muted">{store.path}</Td>
            <Td className="text-right font-mono whitespace-nowrap">{store.blob_count}</Td>
            <Td className="text-right font-mono whitespace-nowrap">
              {formatBytes(store.total_bytes)}
            </Td>
            <Td className="text-right font-mono whitespace-nowrap text-fg-muted">
              {store.available_bytes === null ? t("unknown") : formatBytes(store.available_bytes)}
            </Td>
            {onDelete ? (
              <Td className="text-right">
                <Button
                  size="sm"
                  aria-label={t("deleteNamed", { name: store.name })}
                  onClick={() => onDelete(store)}
                >
                  {t("delete")}
                </Button>
              </Td>
            ) : null}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Create() {
  const t = useTranslations("blobStores");
  const notify = useNotify();
  const create = useCreateBlobStore();
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const { form, tried, attempt, forget } = useAttempts(create.error);
  const refused = refusalsOf(create.error, ["name", "path", "type"]);
  // A name another store has: said at the name.
  const taken =
    isApiError(create.error) && create.error.code === "conflict" ? create.error.message : null;
  const ownName = NAME.test(name) ? undefined : t("nameRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    create.reset();
    if (ownName) return;
    create.mutate(
      // Without a directory, the server gives it one of its own name.
      { name, type: "file", path: path.trim() === "" ? null : path.trim() },
      {
        onSuccess: (made) => {
          notify(t("created", { name: made.name }));
          // Ready for another: empty, and with nothing said to be wrong with it.
          setName("");
          setPath("");
          forget();
        },
      },
    );
  }

  return (
    <Panel className="mb-6 p-6">
      <h2 className={H2}>{t("createTitle")}</h2>
      <form ref={form} onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("fields.name")}
            hint={t("hints.name")}
            required
            spellCheck={false}
            autoComplete="off"
            value={name}
            error={tried ? (ownName ?? taken ?? refused.at.name) : undefined}
            onChange={(event) => setName(event.target.value)}
          />
          <TextField
            label={t("fields.directory")}
            hint={t("hints.directory")}
            spellCheck={false}
            autoComplete="off"
            value={path}
            error={tried ? refused.at.path : undefined}
            onChange={(event) => setPath(event.target.value)}
          />
        </div>
        {create.isError && taken === null && refused.elsewhere ? (
          <ErrorState error={create.error} />
        ) : null}
        <div>
          <Button type="submit" variant="primary" busy={create.isPending}>
            <Plus aria-hidden="true" className="size-4" />
            {t("create")}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/** The blob stores (R10): what each holds, a new one, and deleting one that nothing uses. */
export function BlobStoresScreen() {
  const t = useTranslations("blobStores");
  const session = useSession();
  const notify = useNotify();
  const page = pageOf(useSearchParams());
  const stores = useBlobStores(page);
  const remove = useDeleteBlobStore();
  const mayWrite = session.data !== undefined && allows(session.data, "admin:blobstores:write");
  const pages = stores.data === undefined ? undefined : Math.ceil(stores.data.total / AT_ONCE);
  const hrefFor = (target: number) => pageHref(BLOB_STORES, target);
  const top = usePageFocus<HTMLDivElement>(page, stores.data !== undefined);
  const beyond = useWithinPages(page, pages, hrefFor);
  const [asked, setAsked] = useState<BlobStoreOut | null>(null);
  // The button that was pressed goes with its row: once the dialog is closed, the
  // keyboard is put at the list.
  const deleted = useRef(false);
  useEffect(() => {
    if (asked !== null || !deleted.current) return;
    deleted.current = false;
    top.current?.focus();
  }, [asked, top]);

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title={t("title")} intro={t("intro")} />
      {mayWrite ? <Create /> : null}
      <Panel>
        {stores.isError ? (
          <ErrorState error={stores.error} onRetry={() => void stores.refetch()} className="m-4" />
        ) : !stores.data || beyond ? (
          <LoadingState />
        ) : (
          <>
            <div
              ref={top}
              tabIndex={-1}
              role="group"
              aria-label={t("title")}
              className="outline-none"
            >
              <BlobStoreTable
                caption={t("title")}
                stores={stores.data.items}
                onDelete={
                  mayWrite
                    ? (store) => {
                        remove.reset();
                        setAsked(store);
                      }
                    : undefined
                }
              />
            </div>
            {remove.isError ? <ErrorState error={remove.error} className="m-4" /> : null}
            <Pager page={page} pages={pages ?? 1} hrefFor={hrefFor} />
          </>
        )}
      </Panel>
      <ConfirmDialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
        title={t("deleteAsk", { name: asked?.name ?? "" })}
        confirmLabel={t("deleteStore")}
        mustType={asked?.name}
        busy={remove.isPending}
        onConfirm={() => {
          if (asked === null) return;
          remove.mutate(asked.name, {
            onSuccess: () => {
              notify(t("deleted", { name: asked.name }));
              deleted.current = true;
            },
            onSettled: () => setAsked(null),
          });
        }}
      >
        {t("deleteBody")}
      </ConfirmDialog>
    </div>
  );
}
```

Create `frontend/src/screens/system.tsx`:

```tsx
"use client";

import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { StatusTag } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Fact, Facts, Time } from "@/components/ui/details";
import { TextField } from "@/components/ui/field";
import { AppLink } from "@/components/ui/link";
import { useNotify } from "@/components/ui/notifications";
import { PageHeader, Panel } from "@/components/ui/panel";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useEveryBlobStore, useInformation, useSetBaseUrl } from "@/lib/administration";
import type { SettingsOut } from "@/lib/api/types";
import { useAttempts } from "@/lib/focus";
import { BLOB_STORES } from "@/lib/paths";
import { refusalsOf } from "@/lib/refusals";
import { useSettings } from "@/lib/security";
import { allows } from "@/lib/session/rules";
import { useSession } from "@/lib/session/session";
import { BlobStoreTable } from "@/screens/blob-stores";

const H2 = "mb-4 text-lg font-semibold text-fg uppercase";

/** Whether what was typed is an address the server takes for its own: http or https, and no more than a path. */
function isBaseUrl(typed: string): boolean {
  try {
    const url = new URL(typed);
    const web = url.protocol === "http:" || url.protocol === "https:";
    return web && url.hostname !== "" && !url.search && !url.hash;
  } catch {
    return false;
  }
}

/** What is running (R11, R12). */
function Running() {
  const t = useTranslations("system");
  const information = useInformation();
  if (information.isError) {
    return <ErrorState error={information.error} onRetry={() => void information.refetch()} />;
  }
  if (!information.data) return <LoadingState className="p-4" />;
  const { version, schema, runtime, database } = information.data;
  return (
    <Facts>
      <Fact name={t("facts.version")} copy={version} mono>
        {version}
      </Fact>
      <Fact name={t("facts.schema")}>
        <span className="flex flex-wrap items-center gap-2">
          <code className="font-mono text-xs">{schema.revision ?? t("neverMigrated")}</code>
          {schema.current ? (
            <StatusTag tone="success">{t("schemaCurrent")}</StatusTag>
          ) : (
            <StatusTag tone="danger">{t("schemaOther", { expected: schema.expected })}</StatusTag>
          )}
        </span>
      </Fact>
      <Fact name={t("facts.started")}>
        <Time value={runtime.started_at} />
      </Fact>
      <Fact name={t("facts.python")} mono>
        {runtime.python}
      </Fact>
      <Fact name={t("facts.platform")} mono>
        {runtime.platform}
      </Fact>
      <Fact name={t("facts.database")} mono>
        {database.version}
      </Fact>
    </Facts>
  );
}

/** The address the server gives out as its own. Empty, it is the address of each request. */
function BaseUrl({ settings, mayWrite }: { settings: SettingsOut; mayWrite: boolean }) {
  const t = useTranslations("system");
  const notify = useNotify();
  const change = useSetBaseUrl();
  const [typed, setTyped] = useState(settings.base_url ?? "");
  const { form, tried, attempt } = useAttempts(change.error);
  const refused = refusalsOf(change.error, ["base_url"]);
  const wanted = typed.trim();
  const own = wanted === "" || isBaseUrl(wanted) ? undefined : t("baseUrlRule");

  function submit(event: FormEvent) {
    event.preventDefault();
    attempt();
    change.reset();
    if (own) return;
    change.mutate(wanted === "" ? null : wanted, {
      onSuccess: (saved) => {
        // As the server keeps it: without a slash at its end.
        setTyped(saved.base_url ?? "");
        notify(saved.base_url === null ? t("baseUrlCleared") : t("baseUrlSaved"));
      },
    });
  }

  return (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <TextField
        label={t("fields.baseUrl")}
        hint={t("hints.baseUrl")}
        type="url"
        spellCheck={false}
        autoComplete="off"
        disabled={!mayWrite}
        value={typed}
        error={tried ? (own ?? refused.at.base_url) : undefined}
        onChange={(event) => setTyped(event.target.value)}
      />
      {change.isError && refused.elsewhere ? <ErrorState error={change.error} /> : null}
      {mayWrite ? (
        <div>
          <Button type="submit" variant="primary" busy={change.isPending}>
            {t("saveBaseUrl")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

/** The installation itself (R11): what runs, the address it gives out, and its blob stores. */
export function SystemScreen() {
  const t = useTranslations("system");
  const session = useSession();
  const may = (permission: string) =>
    session.data !== undefined && allows(session.data, permission);
  const settings = useSettings();
  const storesReadable = may("admin:blobstores:read");
  const stores = useEveryBlobStore(storesReadable);

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <PageHeader title={t("title")} intro={t("intro")} />
      <Panel className="p-6">
        <h2 className={H2}>{t("runningTitle")}</h2>
        <Running />
      </Panel>
      <Panel className="p-6">
        <h2 className={H2}>{t("baseUrlTitle")}</h2>
        {settings.isError ? (
          <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
        ) : !settings.data || !settings.isFetchedAfterMount ? (
          <LoadingState className="p-4" />
        ) : (
          <BaseUrl settings={settings.data} mayWrite={may("admin:settings:write")} />
        )}
      </Panel>
      {storesReadable ? (
        <Panel>
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 pt-6">
            <h2 className="text-lg font-semibold text-fg uppercase">{t("storesTitle")}</h2>
            <AppLink
              href={BLOB_STORES}
              className="text-sm text-ink-cyan underline-offset-4 hover:underline"
            >
              {t("toStores")}
            </AppLink>
          </div>
          {stores.isError ? (
            <ErrorState
              error={stores.error}
              onRetry={() => void stores.refetch()}
              className="m-6"
            />
          ) : !stores.data ? (
            <LoadingState />
          ) : (
            <BlobStoreTable caption={t("storesTitle")} stores={stores.data.items} />
          )}
        </Panel>
      ) : null}
    </div>
  );
}
```

Change `frontend/src/screens/browse.tsx`:

```diff
@@ -1,6 +1,6 @@
 "use client";
 
-import { Download, File, Folder, Search, Trash2, Upload, X } from "lucide-react";
+import { Download, File, Folder, Search, Trash2, Upload, Wrench, X } from "lucide-react";
 import { useQueryClient } from "@tanstack/react-query";
 import { useTranslations } from "next-intl";
 import { usePathname, useRouter, useSearchParams } from "next/navigation";
@@ -38,10 +38,12 @@ import {
   httpAddress,
   parentOf,
   parseBrowse,
+  repositorySettingsHref,
   searchHref,
   split,
   uploadHref,
 } from "@/lib/paths";
+import { allows } from "@/lib/session/rules";
 import { askAgainIfChanged, useSession } from "@/lib/session/session";
 import { NothingHere } from "@/screens/not-found";
 
@@ -508,6 +510,7 @@ export function BrowseScreen() {
   const typeName = useTypeName();
   const where = parseBrowse(usePathname());
   const file = useSearchParams().get("file");
+  const session = useSession();
   const repository = useRepository(where?.repository ?? "");
 
   // Entering a folder replaces the list the link that was followed was in, and what had
@@ -548,6 +551,14 @@ export function BrowseScreen() {
           type: typeName(found.type),
         })}
       >
+        {session.data !== undefined && allows(session.data, "admin:repositories:read") ? (
+          <Button asChild size="sm" variant="ghost">
+            <AppLink href={repositorySettingsHref(found.name)}>
+              <Wrench aria-hidden="true" className="size-4" />
+              {t("settings")}
+            </AppLink>
+          </Button>
+        ) : null}
         {/* Not for a group: search looks in what holds components, and a group holds none. */}
         {found.type === "group" ? null : (
           <Button asChild size="sm" variant="ghost">
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 759 passed in 26 files.

Run: `pnpm exec eslint . && pnpm exec prettier --check . && pnpm exec tsc --noEmit`
Expected: no finding.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): managing repositories, blob stores and the system"
```

---

### Task 5: The routes

**Files:**
- Create: `page.tsx` in each of `admin/repositories`, `admin/repositories/~new`, `admin/repositories/[repository]`, `admin/blob-stores` and `admin/system`, under `frontend/src/app/(shell)/`
- Test (modify): `frontend/src/app/titles.test.ts`

**Interfaces:**
- Consumes: the screens of Task 4; `namedByRepository(wording)` of `app/titles.ts`.
- Produces: the five addresses, each with a title. A repository's settings are titled "Settings of <name>".

- [ ] **Step 1: Write the failing test**

Change `frontend/src/app/titles.test.ts`:

```diff
@@ -4,11 +4,16 @@ import { metadata as password } from "./(shell)/account/password/page";
 import { metadata as preferences } from "./(shell)/account/preferences/page";
 import { metadata as tokens } from "./(shell)/account/tokens/page";
 import { metadata as anonymousAccess } from "./(shell)/admin/anonymous-access/page";
+import { metadata as blobStores } from "./(shell)/admin/blob-stores/page";
+import { generateMetadata as repositorySettings } from "./(shell)/admin/repositories/[repository]/page";
+import { metadata as manageRepositories } from "./(shell)/admin/repositories/page";
+import { metadata as newRepository } from "./(shell)/admin/repositories/~new/page";
 import { metadata as role } from "./(shell)/admin/roles/[name]/page";
 import { metadata as newRole } from "./(shell)/admin/roles/~new/page";
 import { metadata as roles } from "./(shell)/admin/roles/page";
 import { metadata as user } from "./(shell)/admin/users/[id]/page";
 import { metadata as newUser } from "./(shell)/admin/users/new/page";
+import { metadata as system } from "./(shell)/admin/system/page";
 import { metadata as users } from "./(shell)/admin/users/page";
 import { generateMetadata as browse } from "./(shell)/browse/[repository]/[[...path]]/page";
 import { generateMetadata as component } from "./(shell)/components/[repository]/[id]/page";
@@ -47,6 +52,18 @@ test("the screens of the account and of the administration have titles of their
   expect(anonymousAccess.title).toBe("Anonymous access");
 });
 
+test("the screens of the repositories' and the system's administration have titles", async () => {
+  expect([manageRepositories.title, newRepository.title]).toEqual([
+    "Manage repositories",
+    "New repository",
+  ]);
+  expect([blobStores.title, system.title]).toEqual(["Blob stores", "System"]);
+  // A repository's settings are titled by it, and so told from its folders.
+  expect(await repositorySettings({ params: Promise.resolve({ repository: "releases" }) })).toEqual(
+    { title: "Settings of releases" },
+  );
+});
+
 test("a screen about one repository is titled by it, as the address names it", async () => {
   const at = (repository: string) => ({ params: Promise.resolve({ repository }) });
 
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm test`
Expected: 1 file does not load: `Failed to resolve import` of one of the new routes, from `src/app/titles.test.ts`. The other tests pass.

- [ ] **Step 3: Implement**

Create `frontend/src/app/(shell)/admin/repositories/page.tsx`:

```tsx
import type { Metadata } from "next";

import { ManageRepositoriesScreen } from "@/screens/manage-repositories";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.manage.title };

export default function Page() {
  return <ManageRepositoriesScreen />;
}
```

Create `frontend/src/app/(shell)/admin/repositories/~new/page.tsx`:

```tsx
import type { Metadata } from "next";

import { NewRepositoryScreen } from "@/screens/repository-settings";

import messages from "../../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.manage.newTitle };

export default function Page() {
  return <NewRepositoryScreen />;
}
```

Create `frontend/src/app/(shell)/admin/repositories/[repository]/page.tsx`:

```tsx
import { namedByRepository } from "@/app/titles";
import { RepositorySettingsScreen } from "@/screens/repository-settings";

import messages from "../../../../../../messages/en.json";

export const generateMetadata = namedByRepository(messages.manage.titleOf);

export default function Page() {
  return <RepositorySettingsScreen />;
}
```

Create `frontend/src/app/(shell)/admin/blob-stores/page.tsx`:

```tsx
import type { Metadata } from "next";

import { BlobStoresScreen } from "@/screens/blob-stores";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.blobStores.title };

export default function Page() {
  return <BlobStoresScreen />;
}
```

Create `frontend/src/app/(shell)/admin/system/page.tsx`:

```tsx
import type { Metadata } from "next";

import { SystemScreen } from "@/screens/system";

import messages from "../../../../../messages/en.json";

export const metadata: Metadata = { title: messages.system.title };

export default function Page() {
  return <SystemScreen />;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pnpm test`
Expected: 760 passed in 26 files.

Run: `pnpm lint && pnpm typecheck`
Expected: no finding.

Run: `pnpm build`
Expected: `Compiled successfully`, and the five routes in the list, each rendered for its request (`ƒ`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): the routes of the repository and system screens"
```

---

### Task 6: The screens in a real browser, and the documents

**Files:**
- Modify: `frontend/e2e/ui.spec.ts`, `backend/tests/test_ui_client.py`
- Modify: `README.md`, `docs/superpowers/specs/2026-10-12-frontend-design.md`

**Interfaces:**
- Consumes: the whole stack of `docker-compose.yml`, started by the `stack` fixture of `backend/tests/conftest.py`.
- Produces: 10 more browser tests, between "the anonymous access screen meets WCAG 2.1 AA in both modes" and "an upload refused because the session was replaced in another tab": 64 in all, which the docker suite expects.

- [ ] **Step 1: Write the browser tests**

They make a repository of each type through the forms and then use it as a client would: a file is taken once and refused the second time by the policy that was chosen, and is fetched through the group that was put together. The three places where older tests find the navigation's "Repositories" now name it exactly (R19).

Change `frontend/e2e/ui.spec.ts`:

```diff
@@ -16,6 +16,11 @@ const TOKEN = "browser-test-build";
 const ROLE = "browser-test-deployers";
 const ALICE = "browser-test-alice";
 const HER_PASSWORD = "chosen-by-alice-herself";
+const MADE = "browser-test-made";
+const MIRROR = "browser-test-mirror";
+const TOGETHER = "browser-test-together";
+const STORE = "browser-test-store";
+const REMOTE_SECRET = "the-remote-s-own-secret";
 // A name with what an address gives a meaning to: a space, a fragment, an escape.
 const ODD = "a b#c%.txt";
 const UPLOADS = "**/api/v1/content/*/upload";
@@ -223,7 +228,9 @@ test("choosing a password leads on to the repositories, of which there are none
   await expect(page).toHaveTitle("Repositories · MegooArti");
   await expect(page.getByRole("heading", { name: "No repositories" })).toBeVisible();
   await expect(
-    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
+    page
+      .getByRole("navigation", { name: "Main" })
+      .getByRole("link", { name: "Repositories", exact: true }),
   ).toHaveAttribute("aria-current", "page");
 });
 
@@ -280,7 +287,9 @@ test("on a narrow screen the navigation is behind a button, and nothing overflow
   await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
   await open.click();
   await expect(
-    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
+    page
+      .getByRole("navigation", { name: "Main" })
+      .getByRole("link", { name: "Repositories", exact: true }),
   ).toBeVisible();
   await page.getByRole("button", { name: "Close the navigation" }).click();
 
@@ -316,7 +325,9 @@ test("a repository is entered from the list, and is empty to begin with", async
   await expect(page.getByRole("heading", { name: "Nothing here yet" })).toBeVisible();
   // Browsing a repository is being among the repositories.
   await expect(
-    page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Repositories" }),
+    page
+      .getByRole("navigation", { name: "Main" })
+      .getByRole("link", { name: "Repositories", exact: true }),
   ).toHaveAttribute("aria-current", "page");
 });
 
@@ -1141,6 +1152,278 @@ test("the anonymous access screen meets WCAG 2.1 AA in both modes", async () =>
   });
 });
 
+test("a hosted repository is made on a page that grows, and then takes what its policy lets it", async () => {
+  await page
+    .getByRole("navigation", { name: "Main" })
+    .getByRole("link", { name: "Manage repositories" })
+    .click();
+  await expect(page.getByRole("heading", { level: 1, name: "Manage repositories" })).toBeVisible();
+  await expect(page).toHaveTitle("Manage repositories · MegooArti");
+  await page.getByRole("link", { name: "New repository" }).click();
+  await expect(page).toHaveURL(/\/admin\/repositories\/~new$/);
+
+  // It starts as a hosted Maven repository, with Maven's own settings.
+  await expect(page.getByRole("group", { name: "Version policy" })).toBeVisible();
+  await page.getByLabel("Format").selectOption("raw");
+  await expect(page.getByRole("group", { name: "Version policy" })).toHaveCount(0);
+  await expect(page.getByLabel("Remote address")).toHaveCount(0);
+  await page.getByRole("button", { name: "Create repository" }).click();
+  // Nothing is sent without a name: the keyboard is at the field that wants one.
+  await expect(page.getByLabel("Name", { exact: true })).toBeFocused();
+  await page.getByLabel("Name", { exact: true }).fill(MADE);
+  await page.getByRole("radio", { name: "Disable redeploy" }).check();
+  await page.getByRole("button", { name: "Create repository" }).click();
+
+  await expect(page).toHaveURL(new RegExp(`/admin/repositories/${MADE}$`));
+  await expect(page.getByRole("heading", { level: 1, name: MADE })).toBeVisible();
+  await expect(page).toHaveTitle(`Settings of ${MADE} · MegooArti`);
+  await expect(page.getByRole("radio", { name: "Disable redeploy" })).toBeChecked();
+  // What cannot change is a fact, and not a field that would be tried.
+  await expect(page.getByLabel("Format")).toHaveCount(0);
+  await expect(page.getByLabel("Name", { exact: true })).toHaveCount(0);
+
+  // The policy is the server's from now on: a file is taken once, and not a second time.
+  const session = await (await page.request.get("/api/v1/auth/session")).json();
+  const put = () =>
+    page.request.post(`/api/v1/content/${MADE}/upload`, {
+      headers: { "X-CSRF-Token": session.csrf_token },
+      multipart: {
+        directory: "d",
+        file: { name: "made.txt", mimeType: "text/plain", buffer: Buffer.from("made here") },
+      },
+    });
+  expect((await put()).status()).toBe(201);
+  expect((await put()).status()).toBeGreaterThanOrEqual(400);
+
+  await page.getByRole("link", { name: "Browse it" }).click();
+  await expect(page).toHaveURL(new RegExp(`/browse/${MADE}$`));
+  await expect(page.getByRole("link", { name: "Folder d" })).toBeVisible();
+  // And back, from a repository's folders to its settings.
+  await page.getByRole("link", { name: "Settings" }).click();
+  await expect(page).toHaveURL(new RegExp(`/admin/repositories/${MADE}$`));
+});
+
+test("a proxy is set up with its remote, and its secret is shown to nobody again", async () => {
+  await page.goto("/admin/repositories/~new");
+  await page.getByLabel("Name", { exact: true }).fill(MIRROR);
+  await page.getByRole("radio", { name: "Proxy" }).check();
+  await expect(page.getByRole("group", { name: "Deployment policy" })).toHaveCount(0);
+  await page.getByLabel("Remote address").fill("repo.example.org");
+  await page.getByRole("button", { name: "Create repository" }).click();
+  await expect(page.getByLabel("Remote address")).toBeFocused();
+  await expect(page.getByLabel("Remote address")).toHaveAttribute("aria-invalid", "true");
+
+  await page.getByLabel("Remote address").fill("https://repo.example.org/maven2/");
+  await page.getByLabel("Signs in to the remote with").selectOption("basic");
+  await page.getByLabel("User name").fill("robot");
+  await page.getByLabel("Password").fill(REMOTE_SECRET);
+  await page.getByRole("button", { name: "Create repository" }).click();
+
+  await expect(page.getByRole("heading", { level: 1, name: MIRROR })).toBeVisible();
+  // As the server keeps it, and with a field that is empty where the secret was typed.
+  await expect(page.getByLabel("Remote address")).toHaveValue("https://repo.example.org/maven2");
+  await expect(page.getByLabel("Password")).toHaveValue("");
+  await expect(page.getByText("One is stored. Leave this empty to keep it")).toBeVisible();
+  await expect(page.getByRole("main")).not.toContainText(REMOTE_SECRET);
+  const stored = await (await page.request.get(`/api/v1/repositories/${MIRROR}`)).json();
+  expect(JSON.stringify(stored)).not.toContain(REMOTE_SECRET);
+  expect(stored.proxy.remote_auth).toEqual({ type: "basic", username: "robot", has_secret: true });
+
+  // Its state, and having everything checked again.
+  await expect(page.getByText("In use")).toBeVisible();
+  await page.getByRole("button", { name: "Check everything again" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `${MIRROR} will check everything with its remote again.`,
+  );
+
+  // Blocked by hand, and saved with the secret left as it is.
+  await page.getByRole("checkbox", { name: "Blocked: do not contact the remote at all" }).check();
+  await page.getByRole("button", { name: "Save" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Saved the repository ${MIRROR}.`,
+  );
+  await expect(page.getByRole("button", { name: "Save" })).toBeFocused();
+  await expect(page.getByText("Blocked", { exact: true })).toBeVisible();
+  const saved = await (await page.request.get(`/api/v1/repositories/${MIRROR}`)).json();
+  expect(saved.proxy.blocked).toBe(true);
+  expect(saved.proxy.remote_auth.has_secret).toBe(true);
+});
+
+test("the repository settings screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByLabel("Remote address")).toHaveValue("https://repo.example.org/maven2");
+  });
+});
+
+test("a group is made of members in an order set by keyboard, and answers through them", async () => {
+  await page.goto("/admin/repositories/~new");
+  await page.getByLabel("Format").selectOption("raw");
+  await page.getByLabel("Name", { exact: true }).fill(TOGETHER);
+  await page.getByRole("radio", { name: "Group" }).check();
+  const members = page.getByRole("group", { name: "Members, in the order they are asked" });
+  await members.getByLabel("A repository to add").selectOption(REPOSITORY);
+  await members.getByRole("button", { name: "Add it" }).click();
+  await members.getByLabel("A repository to add").selectOption(MADE);
+  await members.getByRole("button", { name: "Add it" }).click();
+  await expect(members.getByRole("listitem")).toHaveText([
+    new RegExp(REPOSITORY),
+    new RegExp(MADE),
+  ]);
+
+  // Moved by its button, which keeps the keyboard for as long as it can move further.
+  await members.getByRole("button", { name: `Move ${MADE} up` }).focus();
+  await page.keyboard.press("Enter");
+  await expect(members.getByRole("listitem")).toHaveText([
+    new RegExp(MADE),
+    new RegExp(REPOSITORY),
+  ]);
+  await expect(members.getByRole("status")).toHaveText(`${MADE} is now number 1 of 2.`);
+  // At the top it can go no further up: the keyboard is at the button beside it.
+  await expect(members.getByRole("button", { name: `Move ${MADE} down` })).toBeFocused();
+  await page.getByRole("button", { name: "Create repository" }).click();
+
+  await expect(page.getByRole("heading", { level: 1, name: TOGETHER })).toBeVisible();
+  // Asked of the server again, the order is the one that was set.
+  await page.reload();
+  await expect(
+    page.getByRole("group", { name: "Members, in the order they are asked" }).getByRole("listitem"),
+  ).toHaveText([new RegExp(MADE), new RegExp(REPOSITORY)]);
+  // What a member holds is had at the group's address.
+  const through = await page.request.get(`/repository/${TOGETHER}/d/made.txt`);
+  expect(through.status()).toBe(200);
+  expect(await through.text()).toBe("made here");
+});
+
+test("the screens that list and make repositories meet WCAG 2.1 AA in both modes", async () => {
+  await page.goto("/admin/repositories");
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByRole("link", { name: MIRROR, exact: true })).toBeVisible();
+  });
+  await expect(page.getByRole("row", { name: new RegExp(MIRROR) })).toContainText("Blocked");
+  await page.goto("/admin/repositories/~new");
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByRole("radio", { name: "Hosted" })).toBeChecked();
+  });
+});
+
+test("a repository is deleted only by whoever types its name, and not while a group presents it", async () => {
+  await page.goto(`/admin/repositories/${MADE}`);
+  const remove = page.getByRole("button", { name: "Delete repository" });
+  await remove.click();
+  const dialog = page.getByRole("alertdialog", { name: `Delete the repository ${MADE}?` });
+  await expect(dialog).toContainText("Every component and file in it is deleted");
+  await expect(dialog.getByRole("button", { name: "Delete repository" })).toBeDisabled();
+  await dialog.getByLabel(`Type ${MADE} to go on`).fill(MADE);
+  await dialog.getByRole("button", { name: "Delete repository" }).click();
+  // The group stands in the way, and the screen says which.
+  await expect(page.getByRole("main").getByRole("alert")).toContainText(
+    `The group ${TOGETHER} presents this repository.`,
+  );
+
+  for (const name of [TOGETHER, MADE, MIRROR]) {
+    await page.goto(`/admin/repositories/${name}`);
+    await page.getByRole("button", { name: "Delete repository" }).click();
+    const asked = page.getByRole("alertdialog", { name: `Delete the repository ${name}?` });
+    await asked.getByLabel(`Type ${name} to go on`).fill(name);
+    await asked.getByRole("button", { name: "Delete repository" }).click();
+    await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+      `Deleted the repository ${name}.`,
+    );
+    await expect(page).toHaveURL(/\/admin\/repositories$/);
+    await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
+  }
+  // Gone for its clients too.
+  expect((await page.request.get(`/repository/${MADE}/d/made.txt`)).status()).toBe(404);
+});
+
+test("a blob store is made, listed with what it holds, and deleted when nothing uses it", async () => {
+  await page
+    .getByRole("navigation", { name: "Main" })
+    .getByRole("link", { name: "Blob stores" })
+    .click();
+  await expect(page.getByRole("heading", { level: 1, name: "Blob stores" })).toBeVisible();
+  await expect(page).toHaveTitle("Blob stores · MegooArti");
+  const list = page.getByRole("table", { name: "Blob stores" });
+  await expect(list.getByRole("row", { name: /default/ })).toBeVisible();
+
+  await page.getByLabel("Name", { exact: true }).fill(STORE);
+  await page.getByRole("button", { name: "Create blob store" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Created the blob store ${STORE}.`,
+  );
+  await expect(list.getByRole("row", { name: new RegExp(STORE) })).toContainText("0 B");
+  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("");
+
+  // The one every repository uses is not deleted, and the screen says who uses it.
+  await page.getByRole("button", { name: "Delete default" }).click();
+  const refused = page.getByRole("alertdialog", { name: "Delete the blob store default?" });
+  await refused.getByLabel("Type default to go on").fill("default");
+  await refused.getByRole("button", { name: "Delete blob store" }).click();
+  await expect(page.getByRole("main").getByRole("alert")).toContainText("uses this blob store.");
+
+  await page.getByRole("button", { name: `Delete ${STORE}` }).click();
+  const dialog = page.getByRole("alertdialog", { name: `Delete the blob store ${STORE}?` });
+  await expect(dialog).toContainText("Its files stay on the disk");
+  await dialog.getByLabel(`Type ${STORE} to go on`).fill(STORE);
+  await dialog.getByRole("button", { name: "Delete blob store" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    `Deleted the blob store ${STORE}.`,
+  );
+  await expect(list.getByRole("row", { name: new RegExp(STORE) })).toHaveCount(0);
+  // The button that was pressed went with its row: the keyboard is at the list.
+  await expect(page.getByRole("group", { name: "Blob stores" })).toBeFocused();
+});
+
+test("the blob stores screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByRole("table", { name: "Blob stores" })).toBeVisible();
+  });
+});
+
+test("the system page says what is running, and sets the address the server gives out", async ({
+  baseURL,
+}) => {
+  await page
+    .getByRole("navigation", { name: "Main" })
+    .getByRole("link", { name: "System" })
+    .click();
+  await expect(page.getByRole("heading", { level: 1, name: "System" })).toBeVisible();
+  await expect(page).toHaveTitle("System · MegooArti");
+  await expect(page.getByText("As this version expects")).toBeVisible();
+  await expect(page.getByText(/^PostgreSQL \d+/)).toBeVisible();
+  await expect(page.getByText(/^\d+\.\d+\.\d+$/).first()).toBeVisible(); // the version
+  await expect(page.getByRole("table", { name: "Blob stores" })).toBeVisible();
+
+  const address = page.getByLabel("The address of this server, as its clients reach it");
+  await address.fill("not an address");
+  await page.getByRole("button", { name: "Save" }).click();
+  await expect(address).toBeFocused();
+  await expect(address).toHaveAttribute("aria-invalid", "true");
+
+  // Its own address, as this browser reaches it: nothing changes for what follows.
+  const origin = new URL(baseURL ?? "").origin;
+  await address.fill(`${origin}/`);
+  await page.getByRole("button", { name: "Save" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "The base URL is saved.",
+  );
+  await expect(address).toHaveValue(origin); // as the server keeps it
+  expect((await (await page.request.get("/api/v1/settings")).json()).base_url).toBe(origin);
+
+  await address.fill("");
+  await page.getByRole("button", { name: "Save" }).click();
+  await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
+    "The base URL is cleared.",
+  );
+  expect((await (await page.request.get("/api/v1/settings")).json()).base_url).toBeNull();
+});
+
+test("the system screen meets WCAG 2.1 AA in both modes", async () => {
+  await expectAccessibleInBothModes(async () => {
+    await expect(page.getByText("As this version expects")).toBeVisible();
+  });
+});
+
 test("an upload refused because the session was replaced in another tab goes through at the next try", async () => {
   await page.goto(`/upload/${REPOSITORY}`);
   await page.getByLabel("Files", { exact: true }).setInputFiles({
@@ -1222,9 +1505,10 @@ test("through all of it, nothing was asked of another host, and the browser had
   expect(elsewhere).toEqual([]);
   // The complaints there should be: the browser itself logs the sign-in that was refused
   // (401), the upload with the token of a session that had been replaced (403), the
-  // address and the folder that had nothing at them (404), and the upload of a snapshot
+  // address and the folder that had nothing at them (404), the repository and the blob
+  // store that were in use when they were to be deleted (409), and the upload of a snapshot
   // (422). Anything else, such as something the content security policy stopped, fails this.
-  const unexpected = complaints.filter((text) => !/status of (401|403|404|422)/.test(text));
+  const unexpected = complaints.filter((text) => !/status of (401|403|404|409|422)/.test(text));
   // In particular not of the site the return paths named. (Its name is in the query of
   // addresses that were asked for, which is as far as it got.)
   expect(requested.filter((address) => new URL(address).hostname.includes("evil"))).toEqual([]);
```

Change `backend/tests/test_ui_client.py`:

```diff
@@ -99,7 +99,7 @@ def test_the_ui_in_a_real_browser(stack):
     assert result.returncode == 0, said
     passed = re.search(r"(\d+) passed", result.stdout)
     # As many as the file has: fewer would mean that some were left out without a word.
-    assert passed is not None and int(passed[1]) >= 54, said
+    assert passed is not None and int(passed[1]) >= 64, said
     assert not re.search(r"\d+ (failed|skipped|did not run)", result.stdout), said
 
 
```

- [ ] **Step 2: Run them**

Run (in `backend/`): `uv run pytest -m docker tests/test_ui_client.py -q`
Expected: 11 passed.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e backend/tests/test_ui_client.py
git commit -m "test(frontend): managing repositories, blob stores and the system in a real browser"
```

- [ ] **Step 4: Bring the documents up to date**

Change `README.md`:

````diff
@@ -868,8 +868,8 @@ curl -u alice 'https://repo.example.com/api/v1/search?sha1=2ef7bde608ce5404e97d5
 
 The UI is at the root of the installation's address. It has what a person who uses
 the repositories needs (browsing them, search, upload and delete), a person's own
-account, and the administration of users, roles and anonymous access. Repositories
-and blob stores are created through the API for now, and their screens follow.
+account, and everything an administrator keeps: users, roles, anonymous access,
+repositories, blob stores and the installation's own settings.
 
 - **Browsing.** A repository opens one folder at a time, with the way there as a path
   above it. Choosing a file shows everything known of it beside the folder: its size,
@@ -922,6 +922,23 @@ and blob stores are created through the API for now, and their screens follow.
   - **Anonymous access** is one switch, which asks before it is turned on, and shows
     what someone who is not signed in may then do. If the `anonymous` user is
     disabled, nothing is given though the switch is on, and the page says so.
+  - **Manage repositories** lists every repository as it is set up. A new one is made
+    on one page: choose the format and the type, and the page shows what that
+    combination has. A hosted repository has a deployment policy; a proxy has its
+    remote, how it signs in there, how long it trusts what it cached, and what it
+    does when the remote fails; a group has its members, put in order with buttons;
+    a Maven repository has a version policy and a layout policy. What cannot change
+    later (name, format, type, blob store, version policy) is shown as it is and not
+    as a field. A proxy's secret is typed and never shown: leave the field empty to
+    keep the one that is stored. A repository's page also shows a proxy's state and
+    last error, has it check everything with its remote again, rebuilds the index,
+    and deletes the repository after you type its name.
+  - **Blob stores** lists the stores with how many blobs each holds, their size and
+    the space left, makes a new one, and deletes one that no repository uses. Its
+    files stay on the disk.
+  - **System** shows the version, the schema's revision and whether it is the one this
+    version expects, when the server started and what it runs on, the database's
+    version, and the blob stores. The base URL is set there.
 - **Signing in** uses the session cookie the API sets. It is marked `Secure`, so a
   browser keeps it over HTTPS, and over plain HTTP only on the machine itself
   (`localhost`). If you reach the UI over plain HTTP at another name or address,
@@ -991,6 +1008,29 @@ and the content security policy assume one origin.
 | `GET /api/v1/status/ready` | The database is reachable and its schema matches this version; `503` otherwise |
 | `GET /healthz` | The frontend is running (it answers `ok`) |
 
+What is running is told to whoever may read the settings (`admin:settings:read`):
+
+```bash
+curl -u admin http://localhost:8000/api/v1/system/information
+```
+
+```json
+{
+  "version": "0.1.0",
+  "schema": {"revision": "0007", "expected": "0007", "current": true},
+  "runtime": {
+    "python": "3.13.1",
+    "platform": "Linux-6.6-x86_64-with-glibc2.41",
+    "started_at": "2026-10-12T08:00:00Z"
+  },
+  "database": {"version": "PostgreSQL 17.2"}
+}
+```
+
+`schema.current` is false when the database is at another revision than this version
+was written for, which is also when `/api/v1/status/ready` answers `503`. Nothing of the
+configuration is in it.
+
 ## Database migrations
 
 The schema is managed only by [Alembic](https://alembic.sqlalchemy.org/). Migration
````

Change `docs/superpowers/specs/2026-10-12-frontend-design.md`:

```diff
@@ -372,6 +372,17 @@ What an administrator keeps besides people: the repositories, the blob stores th
 - **What the server refuses** is put at the field it names (`proxy.remote_url`, `group.members`, `format_config.layout_policy`, `name` for a Docker repository's name) or said whole (`repository_cycle`, `in_use`, `immutable`).
 - **The navigation's Administration area** becomes: Users, Roles, Anonymous access, Manage repositories, Blob stores, System.
 
+#### Settled while building plan 10c
+
+| # | What | Why |
+| --- | --- | --- |
+| R15 | The form of a repository is one module with no React in it (`lib/repository-form.ts`): what a form starts with, what is wrong with it before the server is asked, and the body that is sent, each a function of what the form holds. | The parts a combination has are then a table of cases, tested without a screen. |
+| R16 | A request that carried a proxy's secret is let go of by the store as soon as it is answered (`gcTime: 0`, and `reset()` after the answer), and the form starts again from the answer, whose secret field is empty. | A20, for the one other secret the UI sends. |
+| R17 | When a member of a group is moved, the keyboard stays on the button that moved it, or goes to the one beside it when it can move no further that way; what happened is said in a line a screen reader hears. | A row that moves takes its buttons with it, and a button that is disabled cannot keep the keyboard (B11). |
+| R18 | A form that is sent and emptied to take another (a new blob store) starts over: nothing is said to be wrong with it until it is sent again. | Emptied, its name is no name, and it said so at once. |
+| R19 | The browser tests that find the navigation's "Repositories" name it exactly. | "Manage repositories" is in the same navigation. |
+| R20 | The system page takes the blob stores' state from the blob stores' own endpoint, and shows it to whoever may read them. | R12: it is another permission. |
+
 ## 13. Requirement coverage
 
 | Requirement | Where |
```

- [ ] **Step 5: Run everything**

Run: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: no finding, 760 passed, `Compiled successfully`.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: no finding; 2761 passed, 1 skipped.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 35 passed.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/superpowers/specs/2026-10-12-frontend-design.md
git commit -m "docs: the repository and system screens, and system information in the API"
```
