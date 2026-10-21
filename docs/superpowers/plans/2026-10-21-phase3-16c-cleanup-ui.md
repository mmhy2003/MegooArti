# Cleanup Policies: The Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An administrator makes, changes and deletes cleanup policies on screens of their own, trying each against a repository as it is typed, and attaches them to a repository, sees its last run and cleans it now from its settings. Plans 16a and 16b are what it shows.

**Architecture:**
- **Data:** `lib/cleanup.ts` holds the React Query hooks of the policies, their preview, a repository's count and "Clean up now", as `lib/selectors.ts` does for selectors.
- **Screens:** `screens/cleanup-policies.tsx` holds the list, the new one and one policy, laid out as `screens/content-selectors.tsx`. The policy form and its preview stand side by side.
- **A repository's Cleanup section** lives in `screens/repository-settings.tsx`, its policies part of the repository's draft (`lib/repository-form.ts`).
- **Text** lives in `messages/en.json`, under `cleanup` and `manage.cleanup`.

**Tech Stack:** Next.js 16, React 19, TanStack Query 5, next-intl, Tailwind 4, Vitest with Testing Library and axe.

**Spec:** [docs/superpowers/specs/2026-10-21-cleanup-policies-design.md](../specs/2026-10-21-cleanup-policies-design.md): section 6, 4.2 (what each criterion says), the row of plan 16c in 10; "Settled while building plan 16a" (P1 to P6) and "16b" (R1 to R8). Read `frontend/AGENTS.md` and, for any Next.js API, `frontend/node_modules/next/dist/docs/`.

## Decisions this plan settles

Task 4 writes these into the spec, as "Settled while building plan 16c".

| # | Decision | Reason |
| --- | --- | --- |
| W1 | The screens are Administration, Cleanup policies, after Content selectors, with `admin:cleanup:read`: `/admin/cleanup-policies`, `/admin/cleanup-policies/~new`, `/admin/cleanup-policies/<name>`. Whoever may only read sees each, and its preview. | Section 6; as selectors' screens (U1). |
| W2 | A criterion is a checkbox with its value beside it: days as a number, release type as a choice of two, the pattern as text. Each is said in words in the list ("Not updated in 14 days, pre-releases"). | Section 6; 4.2. |
| W3 | The preview asks again half a second after the form last changed, with what the form holds, while the form has no problem of its own; it shows the first 50, a pager, and the total. Its repository is chosen among those of the policy's format (hosted and proxy), the first by name unless chosen. | Section 6: refreshed as the form changes; API-5. |
| W4 | The Cleanup section of a repository is shown for a hosted or proxy repository; its policies are checkboxes of the policies of its format and of all formats, to whoever holds `admin:cleanup:read`; to others, the names attached, as text, kept as they are when the form is saved. | Section 6; U3. |
| W5 | "Clean up now" asks first, saying the count `cleanup/preview` gives ("This removes 12 components from npm-proxy now. It cannot be undone."), then starts the run and asks the repository again every 2 seconds until its `cleanup.finished_at` is later than when it started, then says what was removed. `409 cleanup_running` is said as "A cleanup of this repository is already running." | Section 6; 5.1. |

## Global Constraints

- **Administration, Cleanup policies, after Content selectors, with `admin:cleanup:read`: the list (name, format, criteria in words, the repositories attached), a new one at `/admin/cleanup-policies/~new`, one at `/admin/cleanup-policies/<name>`, deleted after a question that names the repositories it will be detached from** (6).
- **The form: name, description, format (chosen once), and each criterion turned on with its value; release type only for a format that has one** (6; `FormatOut.has_prereleases`, P6).
- **The preview: a repository of the format chosen, and the components the policy would remove from it, a page at a time, with the total, refreshed as the form changes** (6).
- **A repository's settings: a Cleanup section with the policies attached, the last run (when, how many removed, or the error), and "Clean up now", which asks first, saying how many components it would remove** (6).
- **The role editor's administration areas gain `cleanup`** (6).
- Text is in `messages/en.json` (ESLint refuses text in markup); a colour only from `src/styles/tokens.css`; every screen passes `expectAccessible()`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Working directory:** `frontend/` for `pnpm`; the repository root for `git`.

## Review Focus

1. **A form with a problem.** The preview is not asked with it, and says why it shows nothing ("Correct the policy to see what it would remove."). Pinned by Task 2's `test("a policy with a problem is not previewed")`.
2. **Typing fast in the form.** One request after the typing stops, not one a key. Pinned by Task 2's `test("the preview waits for the typing to stop")` (fake timers: five changes, one `POST /cleanup-policies/preview`).
3. **A format without pre-releases chosen after release type was set.** Release type goes, and is not sent. Pinned by Task 2's `test("release type goes with a format that has none")`.
4. **A repository administrator who may not read policies.** Saving the repository keeps its policies. Pinned by Task 3's `test("whoever may not read policies keeps them when saving")`.
5. **"Clean up now" pressed twice, or while the daily run is on.** The second says the run is under way, and nothing breaks. Pinned by Task 3's `test("a run already under way is said")`.

---

### Task 1: Data, paths, navigation and the role editor's area

**Files:**
- Create: `frontend/src/lib/cleanup.ts`, `frontend/src/lib/cleanup.test.ts`
- Modify: `frontend/src/lib/paths.ts` (`CLEANUP_POLICIES`, `NEW_CLEANUP_POLICY`, `cleanupPolicyHref`, `parseCleanupPolicy`), `frontend/src/lib/navigation.ts` (item `cleanupPolicies`, icon `Eraser`, after `contentSelectors`), `frontend/src/lib/navigation.test.ts`, `frontend/src/lib/patterns.ts` (`ADMIN_AREAS` gains `"cleanup"`), `frontend/messages/en.json` (`nav.items.cleanupPolicies`, the areas' `cleanup` labels)

**Interfaces:**
- Consumes: 16a's and 16b's types in `lib/api/types.ts` (`PolicyOut`, `PolicyCreate`, `PolicyContent`, `Previewing`, `Selected`, `CleanupRunOut`, `CleanupCount`, `FormatOut`).
- Produces (`lib/cleanup.ts`):
  - `usePolicies(page: number)`, `useEveryPolicy(enabled: boolean)`, `usePolicy(name: string | null)`, `useCreatePolicy()`, `useUpdatePolicy(name)`, `useDeletePolicy(name)`. Each change also invalidates `["repositories"]`'s queries, which show the policies attached.
  - `usePolicyPreview(wanted: Previewing | null, page: number)`: no request while `wanted` is null.
  - `useCleanupCount(repository: string, enabled: boolean)` (`POST /repositories/{name}/cleanup/preview`), `useCleanUpNow(repository: string)` (`POST /repositories/{name}/cleanup`).
  - `criteriaInWords(policy: Pick<PolicyOut, "updated_days" | "downloaded_days" | "release_type" | "asset_pattern">, t) -> string` (W2).
  - `AT_ONCE = 50`.

- [ ] **Step 1: Write the failing tests**

`cleanup.test.ts`: `criteriaInWords` of `{updated_days: 14, release_type: "prerelease"}` is `"Not updated in 14 days, pre-releases"`; of all four, `"Not updated in 14 days, not downloaded in 90 days, releases, a file matching /.*\.tmp"`; one day says `"1 day"`. `navigation.test.ts`: the item is shown to a holder of `admin:cleanup:read` only, after Content selectors, and `/admin/cleanup-policies/x` is under it. `paths`: `cleanupPolicyHref("a b")` is `/admin/cleanup-policies/a%20b`; `parseCleanupPolicy` of it is `{ name: "a b" }`; of `/admin/cleanup-policies/~new`, null.

- [ ] **Step 2: Run them to see them fail**

Run: `pnpm test src/lib/cleanup.test.ts src/lib/navigation.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

As `lib/selectors.ts`, `lib/paths.ts` and `lib/navigation.ts` have their selectors' counterparts.

- [ ] **Step 4: Run them, and the role editor's tests**

Run: `pnpm test src/lib src/components/permission-rows` then `pnpm lint && pnpm typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib frontend/messages/en.json
git commit -m "feat(ui): cleanup policies' data, addresses and place in the navigation"
```

### Task 2: The Cleanup policies screens

**Files:**
- Create: `frontend/src/screens/cleanup-policies.tsx`, `frontend/src/screens/cleanup-policies.test.tsx`, `frontend/src/app/(shell)/admin/cleanup-policies/page.tsx`, `.../cleanup-policies/~new/page.tsx`, `.../cleanup-policies/[name]/page.tsx`
- Modify: `frontend/messages/en.json` (the `cleanup` section)

**Interfaces:**
- Consumes: Task 1's hooks, paths and `criteriaInWords`; `useFormats` (or what `screens/repository-settings.tsx` reads `FormatOut` with); `useEveryManagedRepository`; `ConfirmDialog`, `Pager`.
- Produces: `PoliciesScreen`, `NewPolicyScreen`, `PolicyScreen` (named exports); `PolicyForm` and `PolicyPreview` (internal).

- [ ] **Step 1: Write the failing tests**

`cleanup-policies.test.tsx`, as `content-selectors.test.tsx` is (`mockApi`, `renderUi`, `navigation.at`, `expectAccessible`); a policy `STALE = {name: "stale", format: "npm", updated_days: 30, release_type: "prerelease", repositories: ["npm-hosted"], ...}`:
- `test("are listed with their format, criteria in words and repositories")`: the table "Cleanup policies" has a row with a link `stale` to `/admin/cleanup-policies/stale`, `npm`, `Not updated in 30 days, pre-releases`, `npm-hosted`; a link "New cleanup policy"; accessible.
- `test("say so when there is none, and offer no new one to whoever may only read")`.
- `test("a policy is made, then shown at its own address")`: fill name, choose format `npm`, check "Not updated" and type 14 → `POST /cleanup-policies` with `{name, description: "", format: "npm", updated_days: 14, downloaded_days: null, release_type: null, asset_pattern: null}`; the address becomes `/admin/cleanup-policies/<name>`.
- `test("what the server refuses is said at its field")`: `422` at `asset_pattern` is shown under the pattern.
- `test("release type goes with a format that has none")`: `npm` with release type, then `raw` → the choice is gone, and the body has `release_type: null`.
- `test("the format is not offered again once made")`: on a policy's page the format is text, not a choice.
- `test("the preview lists what the policy would remove, with the total")`: `POST /cleanup-policies/preview` answers two of a total of 51 → a table "Would be removed" with two rows (name, version, modified, last downloaded, or "Never"), "51 components", and a pager.
- `test("the preview waits for the typing to stop")` and `test("a policy with a problem is not previewed")` (Review Focus 1 and 2).
- `test("deleting asks first, naming the repositories it is detached from")`: the question says `npm-hosted`; confirmed → `DELETE /cleanup-policies/stale`, back to the list.
- `test("whoever may only read sees the policy and its preview, and changes nothing")`: every field disabled, no Save or Delete; the preview shown.

- [ ] **Step 2: Run them to see them fail**

Run: `pnpm test src/screens/cleanup-policies.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement the screens, their pages and their text**

W1 to W3. The pages set their titles from `messages.cleanup.title`, `newTitle` and `titleOf`, as the selectors' pages do.

- [ ] **Step 4: Run them to see them pass, and the checks**

Run: `pnpm test src/screens/cleanup-policies.test.tsx src/screens/screens.test.tsx` then `pnpm lint && pnpm typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/messages/en.json
git commit -m "feat(ui): Cleanup policies: listed, made, changed and deleted, previewed against a repository as they are typed"
```

### Task 3: A repository's Cleanup section

**Files:**
- Modify: `frontend/src/lib/repository-form.ts` (`Draft.cleanupPolicies: string[]`, `draftOf`, `parts`), `frontend/src/lib/repository-form.test.ts`, `frontend/src/screens/repository-settings.tsx` (a `cleanup` fieldset and a `CleanUpNow` panel beside `RebuildIndex`; `REFUSED_AT` gains `cleanup_policies`), `frontend/src/screens/administration.test.tsx`, `frontend/messages/en.json` (`manage.sections.cleanup`, `manage.cleanup.*`)

**Interfaces:**
- Consumes: Task 1's `useEveryPolicy`, `useCleanupCount`, `useCleanUpNow`; `RepositoryOut.cleanup_policies` and `.cleanup`.
- Produces: `parts(draft)` sends `cleanup_policies` for a hosted or proxy repository only when the caller may read policies (`createBody` and `updateBody` take `mayReadPolicies: boolean`); otherwise leaves it out, which keeps them (16a's 4.3).

- [ ] **Step 1: Write the failing tests**

`repository-form.test.ts`: `draftOf` carries `cleanup_policies`; `updateBody(draft, true)` has them, `updateBody(draft, false)` has no `cleanup_policies` key; a group's body never has them.

`administration.test.tsx`, beside the repository settings' tests:
- `test("a repository's cleanup policies are chosen among those of its format")`: an npm hosted repository; `GET /cleanup-policies` gives `stale` (npm), `tmp` (`*`) and `old-jars` (maven) → checkboxes `stale` and `tmp` only; checking `tmp` and saving sends `cleanup_policies: ["stale", "tmp"]`.
- `test("whoever may not read policies keeps them when saving")` (Review Focus 4): no `admin:cleanup:read` → `stale` shown as text, no request to `/cleanup-policies`, the `PUT` has no `cleanup_policies`.
- `test("the last run is said")`: `cleanup: {finished_at: ..., removed: 12, failed: 0, by: "root"}` → "Last cleaned up … by root: 12 components removed."; with `error` → the error; with `finished_at: null` → "Running, or cut short".
- `test("clean up now asks first with the count, then says what it removed")`: `POST .../cleanup/preview` gives `{total: 12}` → the question says 12; confirmed → `POST .../cleanup` (202), then `GET /repositories/npm-hosted` answers a finished run → "12 components removed." announced.
- `test("a run already under way is said")` (Review Focus 5): `409 cleanup_running` → "A cleanup of this repository is already running."
- `test("a group has no cleanup section")`.

- [ ] **Step 2: Run them to see them fail**

Run: `pnpm test src/lib/repository-form.test.ts src/screens/administration.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

W4, W5. "Clean up now" is offered to `admin:repositories:write` with policies attached, and disabled while the form has unsaved changes to them ("Save the policies first.").

- [ ] **Step 4: Run them to see them pass, and every frontend check**

Run: `pnpm test && pnpm lint && pnpm typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src frontend/messages/en.json
git commit -m "feat(ui): a repository's cleanup policies, its last run, and cleaning it up now"
```

### Task 4: The guide of the screens, and what this plan settled

**Files:**
- Modify: `docs/web-ui.md` (Cleanup policies after Content selectors; the repository settings' Cleanup section), `docs/administration.md` (the role editor's `cleanup` area if areas are listed there), `docs/superpowers/specs/2026-10-21-cleanup-policies-design.md` ("Settled while building plan 16c": W1 to W5)
- Test: `backend/tests/test_documents.py`

- [ ] **Step 1: Write the guide**

- [ ] **Step 2: Check it**

Run (in `backend/`): `uv run pytest tests/test_documents.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: the screens of cleanup policies, and what plan 16c settled"
```
