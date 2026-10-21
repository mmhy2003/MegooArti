# Cleanup Policies: The Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** What the policies attached to a repository select is removed: once a day, and when an administrator asks, by the rules a delete through the API follows, each component checked again as it goes. Plan 16a's policies and preview are built on.

**Architecture:**
- **Deleting with nobody calling.** A repository's context gains `unattended`: its deletes run every format's own effects without a principal or the deployment policy. Only the run builds one.
- **One component.** `cleanup.run.remove` reads it afresh, checks the policies again, deletes its files as `DELETE /content/.../components/{id}` does, takes a proxy's companions with it, and lets the format finish (Docker's manifest).
- **One repository.** `cleanup.run.clean` walks 16a's `selection.selected`, one transaction per component, under a lock of the repository's own, and keeps the run's record.
- **When.** An hourly check in the application's lifespan runs each repository that is due; a route runs one now.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy and Alembic (PostgreSQL advisory locks), asyncio.

**Spec:** [docs/superpowers/specs/2026-10-21-cleanup-policies-design.md](../specs/2026-10-21-cleanup-policies-design.md): sections 3 (E4 to E7, E11, E12), 5, 7, 9, 11, the row of plan 16b in 10; "Settled while building plan 16a" (P1 to P6).

## Decisions this plan settles

Task 6 writes these into the spec, as "Settled while building plan 16b".

| # | Decision | Reason |
| --- | --- | --- |
| R1 | `RepositoryContext.unattended` (keyword-only, False unless given): `delete` and `maintain(removing=True)` then check no principal and no deployment policy. Only `cleanup/run.py` passes it; a test reads the source for any other. | 5.3: every format's effects, and no route of a request can reach that way. |
| R2 | Deleting a file as the content API does is `repositories/removal.delete_file(context, path)` (moved from `content_api._delete_file`), used by the API and the run alike. | 5.3: the run's effects are the API's. |
| R3 | A proxy's companions are its files of no component whose path is a removed file's path followed by `.` and more (`x.jar.sha1`, `x.whl.metadata`, `x.jar.asc`). | 7.2: one rule, true of Maven's checksums and signatures and PyPI's metadata; no format needs a list of its own. |
| R4 | `Format.cleaned_up(context, files)` follows a component's removal by a run, given its files' paths and SHA-256s; the generic format does nothing. Docker drops a removed tag's manifest by its digest when no tag and no manifest names it any more. | 7.3. |
| R5 | A repository's last run is a row of `cleanup_runs` (repository, started, finished, removed, failed, error, by): `by` the user who asked, None for the daily run. `GET /repositories/{name}` shows it as `cleanup`; the audit's record of a repository's change does not (it is not configuration). | 5.1. |
| R6 | A repository's lock is `pg_try_advisory_lock(19779, hashtext(<repository id>))` (`0x4D43`), held on a connection of its own for the run. "Clean up now" takes it in the request, and hands it to the run it starts. | E12; a 409 must be answered before the 202. |
| R7 | "Clean up now" with no policy attached is `409 no_cleanup_policies`. Its record names whoever asked: the run is started from the request, and keeps its context. | 5.1; E11. |
| R8 | `POST /repositories/{name}/cleanup/preview` answers `{"total": n}`. | 5.1. |

## Global Constraints

- **Deleting by cleanup has the effects of deleting through the API (each format's own: npm's dist-tags, NuGet's version, Docker's manifest, the indexes of APT, YUM and apk), but asks no permission of anyone and ignores the deployment policy (a `read_only` repository is cleaned too)** (E4).
- **The run is checked hourly, a repository run when a day has passed since its own last run finished. `MEGOOARTI_CLEANUP_INTERVAL_SECONDS` (86400; `0` turns the daily run off, not running one now)** (E5).
- **Every component is checked again, in the transaction that deletes it, against the policies as they are then** (E6).
- **A run of one repository is recorded in the audit log once (`repository.cleaned_up`, with the count removed and the policies that selected them)** (E11).
- **A repository is cleaned by one run at a time, in any container; other repositories are cleaned meanwhile** (E12).
- **`POST /api/v1/repositories/{name}/cleanup` … with `admin:repositories:write`, answers `202` at once … A run of that repository already under way, here or in another container, answers `409 cleanup_running`. A run now is that repository's last run** (5.1).
- **A component that cannot be deleted is logged with why, and the run goes on; a run that ends with failures says how many. Shutdown stops a run between two components. Each run logs `cleanup_finished` with the repository, the count removed and the time taken** (5.2).
- **A tag removed by a run takes the manifest it named, when no other tag names it and no index manifest refers to it … a tag deleted through the API or the registry still goes alone** (7.3).
- **A table's line under its headings is `| --- | --- |`**. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** as plan 16a's.

## Review Focus

1. **A component downloaded after the run picked it, before it is deleted.** It stays. Pinned by Task 3's `test_a_component_used_since_it_was_picked_is_kept`.
2. **A policy changed or detached while a run is under way.** What follows is decided by the policies as they are then. Pinned by Task 3's `test_a_policy_detached_meanwhile_removes_no_more`.
3. **A Docker image with two tags, one old.** Only the old tag goes; the image stays for the other. Pinned by Task 3's `test_an_image_another_tag_names_is_kept`.
4. **A container stopped in the middle of a run.** What was removed stays removed, its record says the run did not finish, and the next check runs it again. Pinned by Task 4's `test_a_run_cut_short_is_run_again`.
5. **Two "Clean up now" at once, or one during the daily run.** One runs; the other is `409 cleanup_running`. Pinned by Task 5's `test_a_repository_is_cleaned_by_one_run_at_a_time`.

---

### Task 1: Deleting with nobody calling

**Files:**
- Create: `backend/src/megooarti/repositories/removal.py`
- Modify: `backend/src/megooarti/repositories/content.py` (`RepositoryContext.__init__`, `build_context`, `delete`, `maintain`), `backend/src/megooarti/repositories/content_api.py` (use `removal.delete_file`)
- Test: `backend/tests/repositories/test_unattended.py`

**Interfaces:**
- Produces:
  - `RepositoryContext(..., unattended: bool = False)`; `build_context(db, settings, repository, principal, outbound=None, asked=None, *, unattended: bool = False)`.
  - `removal.delete_file(context: RepositoryContext, path: str) -> bool`: a proxy's file by `context.delete`, a hosted one by its format's `delete_asset`; False if there was none.

- [ ] **Step 1: Write the failing tests**

`test_unattended.py`:
- `test_an_unattended_delete_runs_the_formats_effects`: in npm's `registry` (its conftest's `publish`), versions 1.0.0 and 2.0.0 published; `removal.delete_file` of 2.0.0's tarball with `build_context(..., None, unattended=True)` returns True, and the dist-tags document no longer says `latest` is 2.0.0 (as `tests/repositories/npm/test_content_delete.py` checks it after an API delete).
- `test_an_unattended_delete_ignores_read_only`: a raw hosted repository made `read_only`, a file in it: deleted.
- `test_a_context_with_nobody_calling_still_deletes_nothing`: the same without `unattended`: `ApiError` 401.
- `test_only_the_run_deletes_unattended`: every `.py` under `src/megooarti` that contains `unattended=True` is `cleanup/run.py` (the file need not exist yet: the set is a subset of it).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/repositories/test_unattended.py -q`
Expected: FAIL (`unexpected keyword argument 'unattended'`).

- [ ] **Step 3: Implement**

In `delete` and in `maintain`'s `removing` branch, the `access.require` and `_check_policy` calls run only when not `self.unattended`. `content_api` imports `delete_file` in place of `_delete_file`.

- [ ] **Step 4: Run them, and the delete tests of every format**

Run: `uv run pytest tests/repositories/test_unattended.py tests/repositories/test_content_delete.py tests/repositories/test_content_api.py tests/repositories/npm tests/repositories/nuget tests/repositories/docker -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/tests/repositories/test_unattended.py
git commit -m "feat(repositories): a context that deletes as the format does with nobody calling, for maintenance"
```

### Task 2: A repository's last run, kept

**Files:**
- Create: `backend/src/megooarti/migrations/versions/0015_add_cleanup_runs.py`
- Modify: `backend/src/megooarti/cleanup/models.py` (`CleanupRun`), `backend/src/megooarti/repositories/service.py` (`RepositoryView.cleanup`, `describe`), `backend/src/megooarti/repositories/api.py` (`CleanupRunOut`, `RepositoryOut.cleanup`, `_told` leaves `cleanup` out as it does `status`)
- Test: `backend/tests/cleanup/test_runs_kept.py`

**Interfaces:**
- Produces:
  - `CleanupRun` (`cleanup_runs`): `repository_id` (primary key, FK `repositories.id`, `ON DELETE CASCADE`), `started_at`, `finished_at` (null while under way, or cut short), `removed` int default 0, `failed` int default 0, `error` Text null, `by` String(64) null.
  - `RepositoryView.cleanup: dict[str, Any] | None = None`; `CleanupRunOut`: `started_at`, `finished_at: datetime | None`, `removed: int`, `failed: int`, `error: str | None`, `by: str | None`.

- [ ] **Step 1: Write the failing test**

`test_runs_kept.py`: a repository with no run shows `"cleanup": None`; with a `CleanupRun` row added, `GET /api/v1/repositories/files` shows it; a `PUT` of the repository records `repository.updated` without a `cleanup` change; deleting the repository deletes its row.

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/cleanup/test_runs_kept.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement the model, the migration (`"0015"`, down `"0014"`) and the view**

- [ ] **Step 4: Run it, the drift check and the repository API's tests**

Run: `uv run pytest tests/cleanup/test_runs_kept.py tests/test_migrations.py tests/repositories/test_api.py -q && uv run python scripts/db.py check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/cleanup/test_runs_kept.py
git commit -m "feat(cleanup): a repository's last cleanup run, kept and shown"
```

### Task 3: Removing one component

**Files:**
- Create: `backend/src/megooarti/cleanup/run.py` (`remove`)
- Modify: `backend/src/megooarti/repositories/formats.py` (`cleaned_up`), `backend/src/megooarti/repositories/docker/format.py` (`cleaned_up`)
- Test: `backend/tests/cleanup/test_remove.py`; `backend/tests/repositories/npm/test_cleanup.py`, `nuget/test_cleanup.py`, `apt/test_cleanup.py`, `docker/test_cleanup.py`, `maven/test_cleanup.py`

**Interfaces:**
- Consumes: Task 1's `unattended`, `removal.delete_file`; 16a's `selection.held(context, component_id)`, `Criteria.selects`, `Format.last_used`.
- Produces:
  - `Format.cleaned_up(context: RepositoryContext, files: Sequence[tuple[str, str]]) -> Awaitable[None]` (path, SHA-256): the generic format nothing.
  - `run.policies_of(db, repository) -> list[tuple[str, Criteria]]`: those attached now, by name, in name order.
  - `run.remove(context: RepositoryContext, component_id: uuid.UUID, now: datetime) -> str | None`: the name of the first policy that selected the component, which it then removed; None when it is gone or no policy attached now selects it. Does not commit. The context is unattended.
  - `run.unattended_context(db, settings, repository) -> RepositoryContext`: the one place `unattended=True` is passed.

- [ ] **Step 1: Write the failing tests**

`test_remove.py` (raw hosted `files`, a policy `old` of `updated_days=30` attached, files aged as 16a's tests age them):
- `test_a_selected_component_goes_with_every_file`: `remove` answers `"old"`; its files `404` at `/repository/files/...`, its component gone from `GET /api/v1/content/files/components`.
- `test_a_component_used_since_it_was_picked_is_kept`: its `last_downloaded_at` set to `now` after the policy was changed to `downloaded_days=30` → `remove` is None, the file is there.
- `test_a_policy_detached_meanwhile_removes_no_more`: detached before `remove` → None.
- `test_a_read_only_repository_is_cleaned`: the repository `read_only` → `"old"`, and the file is gone.

Per format, each with its conftest's helpers and a policy of `updated_days=30`, the component's files aged:
- `npm/test_cleanup.py::test_a_removed_version_leaves_the_dist_tags_without_it`: 1.0.0 and 2.0.0, 2.0.0 aged → removed; the package document lists only 1.0.0, and `latest` is 1.0.0 (as an API delete leaves it).
- `nuget/test_cleanup.py::test_a_removed_version_takes_its_symbols`: a package with its `.snupkg` → both gone, the PDB not served.
- `apt/test_cleanup.py::test_a_removed_package_leaves_the_index`: the `Packages` index no longer names it.
- `maven/test_cleanup.py::test_a_proxys_removed_jar_takes_its_checksums`: a Maven proxy that cached `x-1.0.jar` and `x-1.0.jar.sha1` (no component) → both gone; a `x-1.0.pom` of the same component goes as part of it.
- `docker/test_cleanup.py`:
  - `test_a_removed_tag_takes_its_image`: one tag of one image, aged → the tag, its manifest and (after `upkeep.run` past a day) its layers gone.
  - `test_an_image_another_tag_names_is_kept`: `old` and `new` naming one manifest, `old` aged → `old` goes, the manifest and `new` stay.
  - `test_a_platform_image_of_an_index_is_kept`: a platform manifest an index manifest refers to, its own tag aged → the tag goes, the platform manifest stays.
  - `test_deleting_a_tag_through_the_api_still_leaves_its_image`: `DELETE /api/v1/content/images/components/{tag's id}` → the manifest stays (7.3: the run's alone).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_remove.py tests/repositories/npm/test_cleanup.py tests/repositories/nuget/test_cleanup.py tests/repositories/apt/test_cleanup.py tests/repositories/maven/test_cleanup.py tests/repositories/docker/test_cleanup.py -q`
Expected: FAIL (`megooarti.cleanup.run` has no `remove`).

- [ ] **Step 3: Implement**

`remove`: `held = await selection.held(context, component_id)`; None → None; the first of `policies_of` whose criteria select `held` (its `downloaded` raised by `last_used`), else None; the files' `(path, sha256)` read before deleting; each path through `removal.delete_file` (False for one an earlier one took, as NuGet's version takes its symbols); for a proxy, R3's companions by `Asset.component_id IS NULL AND Asset.path LIKE <escaped path> || '.%'`, each through `context.delete`; then `handler.cleaned_up(context, files)`. Docker's `cleaned_up`: for each tag path (`names.tag_of`), digest `sha256:<hex>`; when `_tags_naming(context, image, digest)` is empty and `context.referenced([names.manifest_path(image, digest)])` is empty, `_drop(context, image, digest)` under `context.lock(_REFERENCES)`.

- [ ] **Step 4: Run them to see them pass**

Run: the command of Step 2.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests
git commit -m "feat(cleanup): a component removed as the API deletes it, checked again first; a proxy's companions and Docker's image with it"
```

### Task 4: The run of one repository

**Files:**
- Modify: `backend/src/megooarti/cleanup/run.py` (`claim`, `release`, `clean`)
- Test: `backend/tests/cleanup/test_clean.py`

**Interfaces:**
- Consumes: Task 3's `remove`, `unattended_context`; Task 2's `CleanupRun`; 16a's `selection.selected`.
- Produces:
  - `LOCK_CLASS = 0x4D43`.
  - `run.claim(engine: AsyncEngine, repository_id: uuid.UUID) -> AsyncConnection | None`: an autocommit connection holding R6's lock, or None if another holds it.
  - `run.release(connection: AsyncConnection, repository_id: uuid.UUID) -> Awaitable[None]`: unlocks and closes.
  - `run.clean(sessionmaker, settings, repository_id: uuid.UUID, *, by: str | None = None, now: Callable[[], datetime] = utcnow, batch: int = 500) -> CleanupRun`: the caller holds the claim.

- [ ] **Step 1: Write the failing tests**

`test_clean.py` (raw hosted `files`, policy `old` attached, five components aged and two new):
- `test_a_run_removes_what_the_policies_select_and_says_so`: `clean(..., batch=2)` → five removed, two kept; the `CleanupRun` has `removed == 5`, `failed == 0`, `finished_at` set, `by is None`; `last(sessionmaker, "repository.cleaned_up")` has `changes == {"removed": {"before": None, "after": 5}, "policies": {"before": None, "after": ["old"]}}` (the policies that selected something) and method `system`; a `cleanup_finished` log line with `repository`, `removed` and `seconds` (`structlog.testing.capture_logs`).
- `test_one_component_that_fails_does_not_stop_the_others`: `Format.cleaned_up` of `raw` patched to raise for one path → four removed, `failed == 1`, `cleanup_component_failed` logged with the component.
- `test_a_run_cut_short_is_run_again`: `remove` patched to raise `asyncio.CancelledError` after two → the error goes on up; two removed and committed; the row has `finished_at is None`; a second `clean` removes the other three.
- `test_the_preview_says_what_the_run_removes` (spec 9): for each attached policy, 16a's `POST /api/v1/cleanup-policies/preview` with `root` gives ids; their union is exactly the components `clean` then removes.
- `test_a_repository_is_claimed_once`: `claim` twice → a connection, then None; after `release`, a connection again; the claim of another repository meanwhile → a connection.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_clean.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `claim`, `release` and `clean`**

`clean`: the row upserted at start (`started_at = now()`, counts zero, `finished_at`, `error` null, `by`) and committed; ids of `selection.selected` gathered a page at a time in one session (ids only), each removed in a session and transaction of its own (`remove`, then commit, the policy it names gathered for the record; an exception other than `CancelledError` rolled back, logged `cleanup_component_failed` with `repository`, `component` and `exc_info`, and counted); at the end the row's counts and `finished_at` committed, with `audit.record(db, "repository.cleaned_up", ("repository", name), audit.diff(None, {"removed": n, "policies": [...]}))`; `error` set (and logged `cleanup_failed`) if the walk itself fails.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/cleanup -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/cleanup/run.py backend/tests/cleanup/test_clean.py
git commit -m "feat(cleanup): a repository cleaned by one run at a time, a transaction for each component, its run kept and recorded"
```

### Task 5: When it runs: daily, and now

**Files:**
- Modify: `backend/src/megooarti/config.py` (`cleanup_interval_seconds: int = 86400`), `backend/src/megooarti/cleanup/run.py` (`CHECK_SECONDS`, `due`, `daily`, `start_now`), `backend/src/megooarti/main.py` (the hourly check in `_lifespan`, `app.state.cleanups` cancelled at shutdown), `backend/src/megooarti/cleanup/api.py` (a router under `/repositories`: `POST /{name}/cleanup`, `POST /{name}/cleanup/preview`)
- Test: `backend/tests/cleanup/test_when.py`, `backend/tests/cleanup/test_run_now_api.py`; `backend/tests/test_config.py` (the default)

**Interfaces:**
- Consumes: Task 4's `claim`, `release`, `clean`; 16a's `selection.selected`.
- Produces:
  - `run.CHECK_SECONDS = 3600`.
  - `run.due(db, now: datetime, interval_seconds: int) -> list[uuid.UUID]`: hosted and proxy repositories with a policy attached whose run never finished more recently than `now - interval` (no row, or `finished_at` null and `started_at` older than that, or `finished_at` older), by name.
  - `run.daily(app: FastAPI) -> int`: claims and cleans each due repository in turn, passing over one claimed elsewhere; the number cleaned.
  - `run.start_now(app: FastAPI, repository: Repository, by: str) -> bool`: False if claimed; else starts `clean` as an `asyncio.Task` kept in `app.state.cleanups` (removed when done), releasing the claim at its end.
  - `CleanupCount(BaseModel)`: `total: int`.

- [ ] **Step 1: Write the failing tests**

`test_when.py`:
- `test_a_repository_is_due_a_day_after_its_last_run`: no run → due; finished 2 hours ago → not; 25 hours ago → due; a group or a repository without policies → never; with `interval_seconds=3600`, the run 2 hours ago → due.
- `test_the_daily_check_cleans_what_is_due`: `daily(app)` → 1, the aged component gone, a row for the repository.
- `test_a_restart_does_not_push_the_run_back`: a row finished 25 hours ago, then `create_app` and its lifespan with `CHECK_SECONDS` patched to 0.05 → cleaned within a second.
- `test_an_interval_of_nought_turns_the_daily_run_off`: `cleanup_interval_seconds=0` → no `cleanup` task among the lifespan's (patch `run_periodically` to record the names it is given).

`test_run_now_api.py` (`root`, `files` with `old` attached and an aged component):
- `test_clean_up_now_answers_at_once_and_cleans`: `POST /api/v1/repositories/files/cleanup` → 202 with no body; after awaiting `app.state.cleanups`, the component is gone; `GET /api/v1/repositories/files` → `cleanup.removed == 1`, `cleanup.by == "root"`; the `repository.cleaned_up` record's actor is `root`.
- `test_a_repository_is_cleaned_by_one_run_at_a_time`: the repository claimed (`run.claim`) → 409 `cleanup_running`; another repository meanwhile → 202.
- `test_clean_up_now_needs_policies_and_a_repository_that_holds`: none attached → 409 `no_cleanup_policies`; a group → 409 `no_cleanup_policies`; no such repository → 404.
- `test_how_many_it_would_remove_is_counted_once`: two attached policies that both select the aged component → `POST /api/v1/repositories/files/cleanup/preview` → `{"total": 1}`; nothing removed.
- `test_running_and_counting_need_repositories_write`: a holder of `admin:repositories:read` → 403 for both.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_when.py tests/cleanup/test_run_now_api.py tests/test_config.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `_lifespan`, when `settings.cleanup_interval_seconds > 0`: `run_periodically("cleanup", run.CHECK_SECONDS, lambda: run.daily(app))`. The task `start_now` makes is created in the request, so it keeps the request's audit context (R7). At shutdown, `app.state.cleanups` are cancelled and awaited with the other background tasks.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/cleanup tests/test_config.py tests/test_app.py tests/test_route_guards.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests
git commit -m "feat(cleanup): repositories cleaned daily and on demand, one run each at a time"
```

### Task 6: The API's document, the guides, a real client, and what this plan settled

**Files:**
- Modify: `frontend/openapi.json`, `frontend/src/lib/api/schema.d.ts` (generated), `frontend/src/lib/api/types.ts` (`CleanupRunOut`, `CleanupCount`), `docs/configuration.md` (the row of `MEGOOARTI_CLEANUP_INTERVAL_SECONDS` after `MEGOOARTI_BLOB_GRACE_SECONDS`), `docs/repositories.md` ("Cleanup policies": when they run, clean up now, the last run, that space comes back after `MEGOOARTI_BLOB_GRACE_SECONDS`, read-only repositories cleaned), `docs/formats/docker.md` (7.3's points, and that "not downloaded" keeps what is pulled by digest), `docs/administration.md` ("What is running": the hourly check), `docs/superpowers/specs/2026-10-21-cleanup-policies-design.md` ("Settled while building plan 16b": R1 to R8)
- Test: `backend/tests/test_npm_client.py` (a test marked `docker`), `backend/tests/test_openapi_snapshot.py`, `backend/tests/test_documents.py`

- [ ] **Step 1: Write the container test**

In `test_npm_client.py`, beside its proxy tests: `test_a_cleaned_proxy_is_fetched_again`: install a package through the npm proxy with the npm client; attach a policy `downloaded_days=1` to the proxy; age its files' downloads and creation in the stack's database (as the file's other tests reach it); `POST /api/v1/repositories/<proxy>/cleanup`, then poll `GET /api/v1/repositories/<proxy>` until `cleanup.finished_at`; `cleanup.removed >= 1`; a fresh install resolves again (from the remote).

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_npm_client.py -k cleaned -q`
Expected: PASS.

- [ ] **Step 3: Bring the API's document and the guides up to date**

Run: `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py -q`, `pnpm gen:api`, then write the guides; replace 16a's "nothing is removed yet" in `docs/repositories.md`.

- [ ] **Step 4: Check them**

Run: `uv run pytest tests/test_documents.py tests/test_openapi_snapshot.py -q` and `pnpm typecheck`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_npm_client.py frontend docs
git commit -m "docs: when cleanup runs, what it removes and when the space comes back; what plan 16b settled"
```
