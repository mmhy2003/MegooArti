# MA-12 implementation plan: the APT signing-key browser test waits long enough for an RSA-4096 key

**Goal:** `frontend/e2e/ui.spec.ts:1520` stops timing out on a slow machine while it waits for the notice that the new RSA-4096 key exists.

**Architecture:** this is a test-only change to one test. `test.slow()` raises that test's limit from 60 s to 180 s, and the single notice assertion gets `{ timeout: 90_000 }`. The other tests keep the suite defaults in `frontend/playwright.config.ts` (`timeout: 60_000`, `expect: { timeout: 15_000 }`), which do not change.

## File map

| File | Change |
|---|---|
| `frontend/e2e/ui.spec.ts` | Modify only the test at line 1520: call `test.slow()` first, and give the notice assertion at lines 1553 to 1555 its own timeout. |

Nothing else changes. That covers `playwright.config.ts`, `scripts/ui-e2e.sh`, `megoocolab.toml`, the backend source and the frontend source. The next test (line 1570) generates no key, so it is left as it is.

## Conventions

- Work on branch `megoo/MA-12-flaky-test-chromium-e2e-ui-spec-ts-1520` and make one commit. The subject follows the repository's style, `type(area): what changed`. The commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never commit `.megoocolab/`.
- Frontend checks run from `frontend/` with `pnpm lint` (this runs eslint and `prettier --check`) and `pnpm typecheck`. Run `pnpm install --frozen-lockfile` first if `node_modules` is missing.
- Run the browser suite from the repository root with `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh`. Its tests are serial and depend on each other, so run the whole file, never this one test alone.
- About TDD: the flake depends on random timing, so no test can be written that fails on demand. The design's proof is the margin instead: 90 s against the roughly 13 s measured. For that reason the step runs the full suite before and after the change, and reports how long the test took each time.

## Step 1: Let the APT signing-key test wait 90 s for its RSA-4096 key

1. Baseline: from the repository root, run `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh` once. Write down the result and the time the list reporter prints for `an APT repository is made with its suite, signs with a key replaced only after asking, and says how a machine uses it`. The run may fail on exactly this notice (the flake). Any other failure goes in the report as it is and is not fixed here.
2. Edit `frontend/e2e/ui.spec.ts`.

   The first line of the test body (line 1520) becomes:
   ```ts
   test("an APT repository is made with its suite, signs with a key replaced only after asking, and says how a machine uses it", async () => {
     test.slow();
     await page.goto("/admin/repositories/~new");
   ```

   Replace lines 1553 to 1555:
   ```ts
     await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
       `${DEBS} signs with a new key.`,
     );
   ```
   with:
   ```ts
     // An RSA key of 4096 bits takes a slow machine many seconds to make.
     await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
       `${DEBS} signs with a new key.`,
       { timeout: 90_000 },
     );
   ```
   Change nothing else in the file.
3. From `frontend/`, run `pnpm lint` and then `pnpm typecheck`. Both must pass, and prettier must accept the formatting. If prettier objects, apply `pnpm exec prettier --write e2e/ui.spec.ts` and check that the diff touches only these lines.
4. From the repository root, run `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh` twice. Both runs must pass. Report the time of the APT test in each run. If either run fails, report it as flaky with the output from both runs, as the MA rule requires, and do not claim it is fixed.
5. `git diff` must show only `frontend/e2e/ui.spec.ts`, with one `test.slow();` line, one comment line and one `{ timeout: 90_000 },` line. Commit with:
   ```
   test(e2e): give the APT test's RSA-4096 key 90 s to be made (MA-12)

   Making an OpenPGP RSA-4096 key takes a random time that depends on the CPU,
   about 13 s here, so a busy stack sometimes went past the 15 s default wait
   for the "signs with a new key" notice. Only this assertion waits longer, and
   test.slow() makes room for it in the test's limit.

   Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
   ```

## Final verification

- From `frontend/`, `pnpm lint` and `pnpm typecheck` pass.
- From the repository root, `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh` passes on two runs in a row. Report the APT test's time for each run.
- `git diff main --stat` shows only `frontend/e2e/ui.spec.ts`.
