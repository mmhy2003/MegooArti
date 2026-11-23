# MA-12: the APT signing-key browser test waits long enough for an RSA-4096 key

## Goal

The browser test `e2e/ui.spec.ts:1520` ("an APT repository is made with its suite, signs with a key replaced only after asking, and says how a machine uses it") stops failing on a slow or busy machine. Nothing changes for users: this is a test-only fix.

## Cause

- The test chooses `rsa4096` in "Algorithm of a new key", confirms the dialog, and waits for the notice `browser-test-debs signs with a new key.` (lines 1546 to 1555).
- That wait uses the default of `frontend/playwright.config.ts`: `expect: { timeout: 15_000 }`.
- The server makes an OpenPGP RSA-4096 key (`signing.generate_openpgp` with `pysequoia.CipherSuite.RSA4k`: a primary key and its subkeys). The time to find RSA primes is random and depends on the CPU. An earlier run (MA-10) measured about 13 s on this machine, so a busy stack sometimes passes 15 s. The failure seen at the finish of MA-1 was a timeout on exactly this notice, and the test passed when run again.
- The product code is correct: the key is made in a worker thread (`asyncio.to_thread` in `signing.generate`), the gateway allows 600 s (`gateway/Caddyfile`), the frontend's API client has no timeout of its own, and the screen shows the notice when the answer comes (`frontend/src/screens/signing-key.tsx`).

## Decisions

- **Chosen (your answer): keep `rsa4096` and wait longer for this one notice.** The browser test keeps proving that the algorithm chosen in the form reaches the server.
- Rejected: wait for the POST response first (`page.waitForResponse`). More lines for a small gain in the failure message.
- Rejected: generate an `ed25519` key. It is the default, so the browser test would no longer show that the choice reaches the server.
- Rejected: raise `expect.timeout` for the whole suite. Every real failure would take longer to show.

## Change

One file: `frontend/e2e/ui.spec.ts`, inside the test at line 1520.

1. At the start of the test body, call `test.slow()`. It triples this test's limit from 60 s to 180 s (the limit in `playwright.config.ts` stays 60 s for every other test). Without it, a 90 s wait could not fit in the test.
2. Give the notice assertion its own timeout:
   ```ts
   // An RSA key of 4096 bits takes a slow machine many seconds to make.
   await expect(page.getByRole("region", { name: "Notifications" })).toContainText(
     `${DEBS} signs with a new key.`,
     { timeout: 90_000 },
   );
   ```
   The comment's wording follows the file's style (what happens and why, in one line).

Numbers: 90 s is about seven times the 13 s measured, and the rest of the test (about ten assertions that normally take a few seconds together) fits in the remaining 90 s of the 180 s limit. A passing run is not slower: the assertion returns as soon as the notice shows.

Nothing else changes: not `playwright.config.ts`, not `scripts/ui-e2e.sh`, not backend or frontend source. The next test (line 1570) uses the same repository but generates no key, so it needs no change.

## Edge cases

- If the server really fails to make the key, the test still fails, after 90 s instead of 15 s, with the same message.
- The retained trace (`trace: "retain-on-failure"`) still shows whether the request was pending or answered.

## Testing

From `frontend/`:
- `pnpm lint` and `pnpm typecheck` pass.

From the repository root:
- `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh` passes. The tests are serial and depend on each other, so the whole file is run, not this test alone.
- Run it a second time. The flakiness is random, so two green runs do not prove it is gone; the proof is the margin (90 s against about 13 s). Report the time the line `an APT repository is made with its suite…` shows in the list reporter in both runs.

## Out of scope

- Making RSA-4096 key generation faster, or changing the key size.
- Showing progress in the UI while a key is made.
- Timeouts of other tests.
