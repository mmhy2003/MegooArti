# Cleanup Policies: Policies, Attaching and the Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator makes cleanup policies (a format and criteria), attaches them to hosted and proxy repositories, and sees, for any repository of the format, the components a policy would remove. Nothing is removed yet: that is plan 16b.

**Architecture:**
- **Criteria** are a pure value, `cleanup.criteria.Criteria`, with one function that decides whether a component (`Held`: its version, files, when it was last written and last downloaded) is selected. The database narrows by days first; `Criteria.selects` is the truth, so the preview and the run (16b) can never disagree.
- **Policies** are a table with their own API, permissions and audit records, as content selectors are; attaching is a repository's setting.
- **Selection** (`cleanup.selection`) walks a repository's components in pages of the database, never holding them all, and is what the preview and 16b's run both use.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy and Alembic (PostgreSQL), Python's `re`.

**Spec:** [docs/superpowers/specs/2026-10-21-cleanup-policies-design.md](../specs/2026-10-21-cleanup-policies-design.md): sections 3 (E1 to E3, E8 to E10), 4, 7.1, 7.3's first point, 8, 9, and the row of plan 16a in 10.

## Decisions this plan settles

Task 6 writes these into the spec, as "Settled while building plan 16a".

| # | Decision | Reason |
| --- | --- | --- |
| P1 | Policies are `megooarti/cleanup/`'s: `models.py` (`CleanupPolicy`, `RepositoryCleanupPolicy`), `criteria.py`, `selection.py`, `api.py`. A policy's name is a `NewName`, unique whatever its case (`name_key`, as a repository's). | Section 4.1; one place for what 16b and 16c build on. |
| P2 | The database narrows by the days alone; the pattern and the release type are checked in Python (`Criteria.selects`), on a page of components and their files at a time. | A database's regular expressions are not Python's: the pattern G14 checks must be the one that matches. Spec 5.2 said the pattern was the database's. |
| P3 | A component's `modified` is the latest `updated_at` of its files; its `downloaded` is the latest `last_downloaded_at` of its files, else its `created_at`; and, where a format says it was used later (`Format.last_used`), that. | Section 4.2; 7.3's first point. |
| P4 | The preview orders the selected newest first by `modified`, keeping only the page asked for while it counts them all (a heap of `offset + limit`). | Section 4.4: a page and the total, without holding the repository. |
| P5 | A pattern is checked by `selectors.checked_pattern`, the very check a selector's `=~` has, moved out of the parser. Its refusal is said at `asset_pattern`. | Section 4.2: as a selector's is. |
| P6 | `GET /api/v1/formats` says `has_prereleases` for each format. | Section 4.2 and 16c: the form offers release type by it. |

## Global Constraints

- **What a policy removes is a component, with every file of it. A file that belongs to no component is never selected** (E1). A component in a namespace its format keeps for itself (`unlisted_namespaces`: Docker's `manifests`) is never a candidate.
- **A policy's criteria are all met for a component to be selected. A component is removed when any policy attached to its repository selects it** (E2). **A policy must have at least one criterion** (E3).
- **`updated_days` and `downloaded_days` are 1 to 36500; `release_type` is `release` or `prerelease`; `asset_pattern` matches the whole of a file's path, with its leading `/` (`fullmatch`), at most 1,000 characters, one that repeats a repetition refused** (4.2).
- **A component never downloaded counts from when it was made** (4.2).
- **Release type is offered only for a format that has pre-releases: Maven, npm, PyPI, NuGet, APT, YUM and apk; not Raw, Docker, or a policy of all formats** (4.2).
- **`admin:cleanup:read` and `admin:cleanup:write` for the policies; attaching them is `admin:repositories:write`** (E8). **A policy's format does not change** (E9; `409 immutable`). **Deleting a policy detaches it from every repository, each recorded** (E10).
- **A hosted or proxy repository holds any number of policies of its format or of all formats; a policy of another format, or a group repository, is refused at its field (`422`). Left out of a `PUT`, the repository keeps the ones it has** (4.3).
- **The preview needs `admin:cleanup:read` and lists only what the caller may browse in that repository; the total counts the same** (4.4). **Every new list is paged** (API-5).
- Events: `cleanup_policy.created`, `cleanup_policy.updated`, `cleanup_policy.deleted`; `repository.updated` for a detach (4.5).
- **A table's line under its headings is `| --- | --- |`** (one `---` cell a column). Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directories:** run `uv` and `pytest` commands in `backend/`, with `MEGOOARTI_TEST_DATABASE_URL` set to your test database (or `make db` first); `pnpm` commands in `frontend/`; `git` commands in the repository root.

## Review Focus

1. **A policy with a pattern alone on a large repository.** The preview pages through the components and answers; it never loads the repository into memory. Pinned by Task 5's `test_the_preview_walks_a_repository_in_pages` (a page size of 2 over 5 components).
2. **A component with one file inside the days and one outside.** It is kept: the newest file decides "not updated" and "not downloaded". Pinned by Task 1's `test_the_newest_file_decides` and Task 5's `test_a_component_is_as_old_as_its_newest_file`.
3. **A Docker image pulled by digest only.** Its tag is not "not downloaded". Pinned by Task 5's `test_a_tag_is_used_while_its_manifest_is_pulled`.
4. **A `PUT` of a repository from a client that predates policies.** It keeps them. Pinned by Task 4's `test_a_put_without_policies_keeps_them`, and MCP's `update_repository` by `test_mcp_update_keeps_the_policies`.
5. **A caller who may browse some of a repository through a selector.** The preview lists and counts only that. Pinned by Task 5's `test_the_preview_shows_only_what_the_caller_may_browse`.

---

### Task 1: Criteria, and which formats have pre-releases

**Files:**
- Create: `backend/src/megooarti/cleanup/__init__.py` (empty), `backend/src/megooarti/cleanup/criteria.py`
- Modify: `backend/src/megooarti/security/selectors.py` (move the `=~` checks into `checked_pattern`), `backend/src/megooarti/repositories/formats.py` (`has_prereleases`), the formats `maven`, `npm`, `pypi`, `nuget`, `apt`, `yum`, `apk` (`has_prereleases = True`), `backend/src/megooarti/repositories/formats_api.py` (`FormatOut.has_prereleases`)
- Test: `backend/tests/cleanup/__init__.py`, `backend/tests/cleanup/test_criteria.py`; `backend/tests/repositories/test_formats_api.py` (one assertion)

**Interfaces:**
- Consumes: `Format.is_prerelease(version)`; `selectors.SelectorError`, `selectors.MAX_PATTERN`.
- Produces:
  - `selectors.checked_pattern(text: str) -> re.Pattern[str]`, raising `SelectorError(message, position)` (position from 1, within the pattern) for one too long, one that does not compile, one that repeats a repetition. The parser's `=~` calls it, its positions shifted to the string's.
  - `Format.has_prereleases: bool = False`.
  - `criteria.Held` (frozen dataclass): `id: uuid.UUID`, `namespace: str`, `name: str`, `version: str`, `modified: datetime`, `downloaded: datetime`, `paths: tuple[str, ...]` (as stored, without a leading `/`).
  - `criteria.Criteria` (frozen dataclass): `updated_days: int | None = None`, `downloaded_days: int | None = None`, `release_type: Literal["release", "prerelease"] | None = None`, `asset_pattern: str | None = None`; `selects(held: Held, now: datetime, handler: Format) -> bool`; `cutoffs(now) -> tuple[datetime | None, datetime | None]` (the latest `modified` and `downloaded` a selected component may have).
  - `criteria.problems(format: str, criteria: Criteria) -> list[dict[str, str]]`: the refusals, each `{"field": ..., "message": ...}`, empty when it may be kept. `format` is a registered name or `*`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/cleanup/test_criteria.py`, without a database:

```python
NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)

def held(version="1.0.0", *, modified_days=0, downloaded_days=0, paths=("pkg/a-1.0.0.tgz",)):
    return Held(uuid.uuid4(), "", "a", version, NOW - timedelta(days=modified_days),
                NOW - timedelta(days=downloaded_days), paths)

@pytest.mark.parametrize(("criteria", "component", "selected"), [
    (Criteria(updated_days=30), held(modified_days=31), True),
    (Criteria(updated_days=30), held(modified_days=30), False),   # exactly 30 days: kept
    (Criteria(downloaded_days=7), held(downloaded_days=8), True),
    (Criteria(downloaded_days=7), held(downloaded_days=6), False),
    (Criteria(release_type="prerelease"), held("1.0.0-beta.1"), True),
    (Criteria(release_type="prerelease"), held("1.0.0"), False),
    (Criteria(release_type="release"), held("1.0.0"), True),
    (Criteria(asset_pattern=r"/pkg/.*\.tgz"), held(), True),
    (Criteria(asset_pattern=r"pkg/.*\.tgz"), held(), False),       # the path has its `/`
    (Criteria(asset_pattern=r"/pkg/a"), held(), False),            # the whole path
    (Criteria(updated_days=30, release_type="prerelease"), held("1.0.0", modified_days=90), False),
])
def test_a_component_is_selected_when_every_criterion_is_met(criteria, component, selected):
    assert criteria.selects(component, NOW, get_format("npm")) is selected

def test_one_file_matching_the_pattern_is_enough():
    component = held(paths=("pkg/a-1.0.0.tgz", "pkg/a-1.0.0.tgz.sig"))
    assert Criteria(asset_pattern=r".*\.sig").selects(component, NOW, get_format("npm"))

def test_the_newest_file_decides():  # Held carries the newest; this pins the cutoffs
    assert Criteria(updated_days=30, downloaded_days=7).cutoffs(NOW) == (
        NOW - timedelta(days=30), NOW - timedelta(days=7))

@pytest.mark.parametrize(("format", "version", "pre"), [
    ("maven", "1.0-SNAPSHOT", True), ("maven", "1.0", False), ("npm", "2.0.0-rc.1", True),
    ("pypi", "1.0rc1", True), ("nuget", "1.0.0-preview", True), ("apk", "1.0_rc1-r0", True),
])
def test_release_type_is_each_formats_own(format, version, pre):
    assert Criteria(release_type="prerelease").selects(held(version), NOW, get_format(format)) is pre

@pytest.mark.parametrize(("format", "criteria", "field"), [
    ("npm", Criteria(), "criteria"),                                   # none at all
    ("npm", Criteria(updated_days=0), "updated_days"),
    ("npm", Criteria(downloaded_days=36501), "downloaded_days"),
    ("raw", Criteria(release_type="prerelease"), "release_type"),
    ("docker", Criteria(release_type="release"), "release_type"),
    ("*", Criteria(release_type="release"), "release_type"),
    ("npm", Criteria(asset_pattern="("), "asset_pattern"),
    ("npm", Criteria(asset_pattern="(a+)+"), "asset_pattern"),
    ("npm", Criteria(asset_pattern="a" * 1001), "asset_pattern"),
    ("nothing", Criteria(updated_days=1), "format"),
])
def test_what_cannot_be_a_policy_is_said_at_its_field(format, criteria, field):
    assert [problem["field"] for problem in problems(format, criteria)] == [field]

def test_a_good_policy_has_no_problem():
    assert problems("maven", Criteria(updated_days=14, release_type="prerelease")) == []
    assert problems("*", Criteria(downloaded_days=90, asset_pattern=r"/.*\.tmp")) == []

def test_formats_say_whether_they_have_prereleases():
    assert {name for name in format_names() if get_format(name).has_prereleases} == {
        "maven", "npm", "pypi", "nuget", "apt", "yum", "apk"}
```

Add to `test_formats_api.py`'s listing test: the item for `npm` has `"has_prereleases": True`, for `raw` `False`. The selector tests of `=~` (`tests/security/test_selectors.py`) must still pass unchanged: they pin the moved check's messages and positions.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_criteria.py tests/repositories/test_formats_api.py -q`
Expected: FAIL (`ModuleNotFoundError: megooarti.cleanup`).

- [ ] **Step 3: Implement**

- `checked_pattern`: the length, compile and `_repeats_a_repetition` checks lifted from `_Parser` (selectors.py:310-320), positions relative to the pattern; the parser re-raises with `value.at` as now.
- `selects`: each criterion given must hold; days compare strictly (`modified < now - days`); the pattern is `checked_pattern(...)` (cached by `functools.lru_cache` on the text) `.fullmatch` against `"/" + path` for any path; release type via `handler.is_prerelease(held.version)`.
- `problems`: the format (`*` or `get_format`), at least one criterion (field `criteria`, message "A policy needs at least one criterion."), the day ranges, release type only where `has_prereleases` (message "This format has no pre-releases." or "A policy of every format has no release type."), the pattern through `checked_pattern`.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/cleanup/test_criteria.py tests/repositories/test_formats_api.py tests/security/test_selectors.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/cleanup backend/src/megooarti/security/selectors.py backend/src/megooarti/repositories backend/tests/cleanup backend/tests/repositories/test_formats_api.py
git commit -m "feat(cleanup): criteria of a cleanup policy, and which formats have pre-releases"
```

### Task 2: Policies' records

**Files:**
- Create: `backend/src/megooarti/cleanup/models.py`, `backend/src/megooarti/migrations/versions/0014_add_cleanup_policies.py`
- Modify: `backend/src/megooarti/models.py` (import `megooarti.cleanup.models`)
- Test: `backend/tests/cleanup/test_models.py`; `tests/test_migrations.py` and `uv run python scripts/db.py check` already cover drift

**Interfaces:**
- Produces:
  - `CleanupPolicy` (`cleanup_policies`): `id` uuid, `name` String(64), `name_key` String(64) unique, `description` String(255) default `""`, `format` String(32), `updated_days` int null, `downloaded_days` int null, `release_type` String(16) null, `asset_pattern` Text null, `created_at`, `updated_at` (onupdate); `criteria` property → `Criteria`.
  - `RepositoryCleanupPolicy` (`repository_cleanup_policies`): `repository_id` (FK `repositories.id`, `ON DELETE CASCADE`), `policy_id` (FK `cleanup_policies.id`, `ON DELETE CASCADE`), primary key both; index on `policy_id`.

- [ ] **Step 1: Write the failing test**

`test_models.py`: a policy attached to a repository goes when the repository is deleted (`service.delete_repository`), and its attachment goes when the policy is deleted (`db.delete(policy)`), each leaving the other; two policies whose names differ only in case cannot both be kept (`IntegrityError` on `name_key`); `policy.criteria == Criteria(updated_days=30)` for a policy of `updated_days=30`.

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/cleanup/test_models.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the models and the migration**

Revision `"0014"`, `down_revision = "0013"`, names with `op.f("pk_…")`, `op.f("uq_…")`, `op.f("fk_…")` as 0013 has them; `downgrade()` drops both tables.

- [ ] **Step 4: Run the tests and the drift check**

Run: `uv run pytest tests/cleanup/test_models.py tests/test_migrations.py -q && uv run python scripts/db.py check`
Expected: PASS, and no difference between the models and the migrations.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/cleanup/models.py backend/src/megooarti/models.py backend/src/megooarti/migrations/versions/0014_add_cleanup_policies.py backend/tests/cleanup/test_models.py
git commit -m "feat(cleanup): policies and what they are attached to, kept"
```

### Task 3: The policies' API

**Files:**
- Create: `backend/src/megooarti/cleanup/api.py`
- Modify: `backend/src/megooarti/main.py` (include the router under `API_PREFIX`)
- Test: `backend/tests/cleanup/test_policies_api.py`

**Interfaces:**
- Consumes: Task 1's `Criteria`, `problems`; Task 2's models; `pagination.Page/PageParams/page`; `audit.record/diff`; `require`.
- Produces (router `prefix="/cleanup-policies"`, tag `cleanup policies`):
  - `PolicyContent(BaseModel)`: `description: str = Field("", max_length=255)`, `updated_days: int | None`, `downloaded_days: int | None`, `release_type: Literal["release", "prerelease"] | None`, `asset_pattern: str | None = Field(None, max_length=1000)`; `format: str` (`max_length=32`, accepted on `PUT` only if unchanged).
  - `PolicyCreate(PolicyContent)`: `name: NewName`.
  - `PolicyOut`: `id`, `name`, `description`, `format`, the four criteria, `repositories: list[str]` (by name, in name order), `created_at`, `updated_at`.
  - Routes: `GET ""` (`Page[PolicyOut]`, by name), `POST ""` (201), `GET /{name}`, `PUT /{name}`, `DELETE /{name}` (204); read with `admin:cleanup:read`, change with `admin:cleanup:write`.
  - `cleanup.api._told(policy) -> dict` (what a record says: description, format, criteria).

- [ ] **Step 1: Write the failing tests**

In `test_policies_api.py`, as `tests/security/test_content_selectors_api.py` is laid out (a `root` of the `admin` role, a `reader` holding `admin:cleanup:read`):

- `test_a_policy_is_made_read_listed_changed_and_deleted`: `POST` `{"name": "stale-snapshots", "format": "maven", "updated_days": 14, "release_type": "prerelease"}` → 201 with those values and `repositories == []`; `GET` it; listed in `GET`'s page (`total == 1`); `PUT` with `updated_days: 30` → 200; `DELETE` → 204, then `GET` → 404 `not_found`.
- `test_each_change_is_recorded`: `last(sessionmaker, "cleanup_policy.created")` has target `("cleanup_policy", "stale-snapshots")` and `changes["updated_days"] == {"before": None, "after": 14}`; likewise `updated` and `deleted`.
- `test_a_name_is_taken_whatever_its_case`: a second `STALE-snapshots` → 409 `conflict`.
- `test_the_format_does_not_change`: `PUT` with `format: "npm"` → 409 `immutable`; `GET /api/v1/cleanup-policies/x` with the same format → 200.
- `test_what_cannot_be_a_policy_is_refused_at_its_field`: no criterion → 422 at `criteria`; `release_type` on `raw` → 422 at `release_type`; `(a+)+` → 422 at `asset_pattern`; an unknown format → 422 at `format`.
- `test_reading_needs_cleanup_read_and_changing_cleanup_write`: the reader lists and gets (200), and is refused `POST`, `PUT`, `DELETE` (403 `forbidden`); someone with neither is refused `GET` (403).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_policies_api.py -q`
Expected: FAIL (404 on every route).

- [ ] **Step 3: Implement `cleanup/api.py` and register it**

As `security/api/selectors.py` is: `_load(db, name)` (404 `not_found`, "No such cleanup policy."), `_refused(problems)` raising `ApiError(422, "validation_error", "The request is not valid.", problems)`; `name_key = name.lower()`; flush, `audit.record`, commit, then `log.info("cleanup_policy_created", policy=..., by=principal.user.username)`. `repositories` read by a join of `RepositoryCleanupPolicy` and `Repository`. `test_route_guards.py` covers the new routes' authentication.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/cleanup/test_policies_api.py tests/test_route_guards.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/cleanup/api.py backend/src/megooarti/main.py backend/tests/cleanup/test_policies_api.py
git commit -m "feat(cleanup): cleanup policies made, read, changed and deleted, with admin:cleanup"
```

### Task 4: Attaching policies to repositories

**Files:**
- Modify: `backend/src/megooarti/repositories/service.py` (`RepositoryView.cleanup_policies`, `describe`, `create_repository`, `update_repository`, `_set_policies`), `backend/src/megooarti/repositories/api.py` (`RepositoryOut`, `RepositoryCreate`, `RepositoryUpdate`), `backend/src/megooarti/cleanup/api.py` (delete detaches), `backend/src/megooarti/mcp/operations.py` (only if `_merged` drops the field)
- Test: `backend/tests/cleanup/test_attaching.py`

**Interfaces:**
- Consumes: Task 2's models; Task 3's `_told` and routes.
- Produces:
  - `RepositoryView.cleanup_policies: list[str] = field(default_factory=list)` (names, in name order); `RepositoryOut.cleanup_policies: list[str]`.
  - `RepositoryCreate.cleanup_policies: list[str] = []`; `RepositoryUpdate.cleanup_policies: list[str] | None = None` (None keeps).
  - `service.create_repository(..., cleanup_policies: list[str] | None = None)`, `service.update_repository(..., cleanup_policies: list[str] | None = None)`; `service._set_policies(db, repository, names) -> None` refusing with `_invalid("cleanup_policies", ...)`.

- [ ] **Step 1: Write the failing tests**

`test_attaching.py`, through the API with `root`:

- `test_a_repository_is_made_with_policies_and_shows_them`: policies `old` (raw) and `any` (`*`); `POST /api/v1/repositories` of a raw hosted `files2` with `cleanup_policies: ["old", "any"]` → 201 with `["any", "old"]`; `GET /api/v1/cleanup-policies/old` has `repositories == ["files2"]`.
- `test_a_put_without_policies_keeps_them`: `PUT` without the field keeps `["old"]`; `PUT` with `[]` detaches; the `repository.updated` record's `changes["cleanup_policies"] == {"before": ["old"], "after": []}`.
- `test_what_cannot_be_attached_is_refused_at_its_field` (each 422 at `cleanup_policies`): a policy of `npm` on a raw repository; a name there is none of; any policy on a group (`type: "group"`).
- `test_deleting_a_policy_detaches_it_and_says_so`: `DELETE /api/v1/cleanup-policies/old` → 204; the repository shows `[]`; a `repository.updated` record for `files2` with `cleanup_policies` from `["old"]` to `[]`, beside `cleanup_policy.deleted`.
- `test_mcp_update_keeps_the_policies`: through `mcp.operations.update_repository` (as `tests/mcp/` call it) changing `online` only, the repository keeps `["old"]`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_attaching.py -q`
Expected: FAIL (`cleanup_policies` unknown to the repository's API).

- [ ] **Step 3: Implement**

`_set_policies`: refuses on a group ("A group holds nothing to clean up."), a name not found ("No such cleanup policy: <name>."), a policy whose format is neither the repository's nor `*` ("<name> is a policy of <format>."); replaces the rows. The delete in `cleanup/api.py` describes each attached repository before and after (`service.describe`), recording `repository.updated` with `repositories.api._told`'s shape, before `cleanup_policy.deleted`, in one commit.

- [ ] **Step 4: Run them, and the repository tests that read a repository's whole answer**

Run: `uv run pytest tests/cleanup tests/repositories/test_api.py tests/repositories/test_audit_records.py tests/mcp -q`
Expected: PASS (update any test that compares a repository's whole answer to include `"cleanup_policies": []`).

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories backend/src/megooarti/cleanup/api.py backend/src/megooarti/mcp backend/tests
git commit -m "feat(cleanup): policies attached to hosted and proxy repositories of their format"
```

### Task 5: Selection, and the preview

**Files:**
- Create: `backend/src/megooarti/cleanup/selection.py`
- Modify: `backend/src/megooarti/repositories/formats.py` (`last_used`), `backend/src/megooarti/repositories/docker/format.py` (`last_used`), `backend/src/megooarti/cleanup/api.py` (`POST /preview`)
- Test: `backend/tests/cleanup/test_selection.py`, `backend/tests/cleanup/test_preview_api.py`, `backend/tests/repositories/npm/test_cleanup_selection.py`, `backend/tests/repositories/docker/test_cleanup_use.py`

**Interfaces:**
- Consumes: Task 1's `Criteria`, `Held`; `RepositoryContext`; `access.Reached`.
- Produces:
  - `Format.last_used(context: RepositoryContext, held: Held) -> Awaitable[datetime | None]`: when else a component was used than its files' downloads; the generic format None. Docker: for a tag, the `last_downloaded_at` of `manifests/<image>/sha256:<hex>` (`names.manifest_path`, the tag file's `sha256` by `context.stat`).
  - `selection.selected(context: RepositoryContext, policies: Sequence[Criteria], now: datetime, *, batch: int = 500) -> AsyncIterator[Held]`: every component of the repository any policy selects, by keyset pages of `Component.id`, the database narrowed by the OR of each policy's `cutoffs` (a policy without days narrows nothing), unlisted namespaces left out, then `selects` on each with `downloaded` raised by `last_used`.
  - `selection.held(context, component_id) -> Held | None`: one component, read afresh (16b checks it again with this).
  - `selection.preview(context, criteria: Criteria, now, *, limit: int, offset: int, reached: Reached) -> tuple[list[Held], int]`: P4; a component counts when `reached.allows` one of its paths.
  - `cleanup.api`: `Previewing(BaseModel)`: the policy's `format` and criteria fields, `repository: str`; `Selected(BaseModel)`: `id`, `namespace`, `name`, `version`, `modified`, `last_downloaded: datetime | None`; `POST /cleanup-policies/preview` with `PageParams`, answering `Page[Selected]`.

- [ ] **Step 1: Write the failing tests**

`test_selection.py`, with the hosted raw `files` and files stored through `PUT /repository/files/<path>`, then aged by updating their `Asset` rows (`updated_at`, `last_downloaded_at`) and their `Component.created_at`:

- `test_a_component_is_as_old_as_its_newest_file`: a component of two files, one written 40 days ago and one 10; `Criteria(updated_days=30)` selects nothing; with both 40, it is selected.
- `test_never_downloaded_counts_from_when_it_was_made`: no download, made 100 days ago → selected by `downloaded_days=90`; made 10 days ago → not.
- `test_any_policy_selects`: `[Criteria(updated_days=30), Criteria(asset_pattern=r"/tmp/.*")]` selects both the old file and the new `tmp/x`, each once.
- `test_the_preview_walks_a_repository_in_pages`: 5 old components, `batch=2` → all 5, each once, ordered as the preview orders them.

`tests/repositories/npm/test_cleanup_selection.py` (with the `registry` fixture and `publish` of its `conftest.py`):

- `test_files_of_no_component_are_never_selected`: after publishing `left-pad` 1.0.0, `selected` with `Criteria(asset_pattern=r".*")` yields the version's component alone; the dist-tags document (no component) never.

`test_cleanup_use.py` (Docker, with `push_image` of `tests/repositories/docker/conftest.py`):

- `test_a_tag_is_used_while_its_manifest_is_pulled`: tag and manifest aged 100 days with no download; the manifest's `last_downloaded_at` set to yesterday → `Criteria(downloaded_days=30)` does not select the tag; unset → it does. Manifests themselves (namespace `manifests`) are never yielded.

`test_preview_api.py`, with `root`:

- `test_the_preview_lists_what_a_policy_would_remove`: three files, two aged 40 days; `POST /api/v1/cleanup-policies/preview` `{"format": "raw", "updated_days": 30, "repository": "files"}` → `total == 2`, items newest first by `modified`, each with `version`, `modified`, `last_downloaded`; nothing removed (`GET /repository/files/<path>` still 200).
- `test_the_preview_takes_a_policy_not_yet_kept`: the same with no policy saved; and its refusals: a policy problem at its field (422), a group or a repository of another format at `repository` (422), no such repository (404 `not_found`).
- `test_the_preview_shows_only_what_the_caller_may_browse`: a role with `admin:cleanup:read` and `selector:mine:raw:files:browse` (a selector `path =^ "/mine/"`) → the preview counts and lists only `mine/` components.
- `test_the_preview_needs_cleanup_read`: without it, 403.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/cleanup/test_selection.py tests/cleanup/test_preview_api.py tests/repositories/npm/test_cleanup_selection.py tests/repositories/docker/test_cleanup_use.py -q`
Expected: FAIL (`ModuleNotFoundError: megooarti.cleanup.selection`).

- [ ] **Step 3: Implement**

The page query (one statement per batch): `Component` joined to a grouped subquery of its `Asset`s (`max(updated_at)`, `max(last_downloaded_at)`, `array_agg(path)`), where `Component.repository_id`, `Component.id > last`, namespace not unlisted, and the OR of the policies' cutoffs (`modified < cutoff`, `coalesce(downloaded, Component.created_at) < cutoff`), ordered by `Component.id`, limited to `batch`. A repository's context comes from `build_context(db, settings, repository, None)`; the preview's route builds it with the caller and `access.reach(caller, repository, "browse")`.

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/cleanup tests/repositories/docker tests/repositories/npm -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/cleanup backend/src/megooarti/repositories backend/tests
git commit -m "feat(cleanup): what a policy selects in a repository, previewed a page at a time"
```

### Task 6: The API's document, the guides, and what this plan settled

**Files:**
- Modify: `frontend/openapi.json`, `frontend/src/lib/api/schema.d.ts` (generated), `frontend/src/lib/api/types.ts` (`PolicyOut`, `PolicyCreate`, `PolicyContent`, `Previewing`, `Selected`, `FormatOut` if not there), `docs/repositories.md` (a "Cleanup policies" section after "Group repositories"), `docs/administration.md` (rows `admin:cleanup:read` and `admin:cleanup:write` in "What an administrator may be given"), `docs/api.md` (the new routes where routes are listed), `docs/superpowers/specs/2026-10-21-cleanup-policies-design.md` ("Settled while building plan 16a": P1 to P6; and section 5.2's first point corrected by P2)
- Test: `backend/tests/test_openapi_snapshot.py`, `backend/tests/test_documents.py` (both existing)

- [ ] **Step 1: Bring the API's document up to date**

Run: `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py -q` (in `backend/`), then `pnpm gen:api` (in `frontend/`).
Expected: PASS; `git diff --stat frontend/` shows `openapi.json` and `schema.d.ts`.

- [ ] **Step 2: Write the guides**

`docs/repositories.md`, "Cleanup policies": what a policy is (E1, E2), each criterion as section 4.2's table says it, that a component never downloaded counts from when it was made and downloads are noted to the hour, release type by format, attaching (hosted and proxy, its format or all, `PUT` keeping them), the preview with a `curl` example of `POST /api/v1/cleanup-policies/preview`, and that removing them comes with plan 16b (say "Policies are run daily; see below" only once 16b lands: here, say that nothing is removed yet by this version's policies).

- [ ] **Step 3: Check the documents and the frontend's types**

Run: `uv run pytest tests/test_documents.py tests/test_openapi_snapshot.py -q` (backend) and `pnpm typecheck` (frontend).
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/openapi.json frontend/src/lib/api docs
git commit -m "docs: cleanup policies, their preview, and what plan 16a settled"
```
