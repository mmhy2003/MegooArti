# MA-11 plan: verify that `test_the_administrators_sessions_end` passes, and close

## Goal

Prove that `backend/tests/security/test_reset_admin.py::test_the_administrators_sessions_end` passes on the task branch (based on `f985803`, current `origin/develop`), so it is no longer a known baseline failure. No repository change is expected.

## Architecture

Nothing changes. The test (lines 59-66 of `backend/tests/security/test_reset_admin.py`) signs in as `admin`, checks `GET /api/v1/auth/session` reports `authenticated: true`, runs `reset_admin`, and checks it then reports `authenticated: false`. `reset_admin` → `users.set_password` → `sessions.delete_user_sessions` ends the session. The backend tests need PostgreSQL, provided by the `db` service in `megoocolab.toml` (it sets `MEGOOARTI_TEST_DATABASE_URL`).

## File map

No files are created or modified. For reference only:
- `backend/tests/security/test_reset_admin.py`: the test, already fixed by `d40b0cc`.
- `backend/src/megooarti/security/reset_admin.py`, `security/users.py`, `security/sessions.py`, `security/api/auth.py`: the code it exercises.

## Steps

### Step 1: Run the test, the backend suite and the linters, and record the results

All commands from the repository root (the worktree), on the task branch, with a clean `git status`.

1. Confirm the start point: `git log --oneline -1` shows `f985803` (or a descendant with no change under `backend/`), and `git status` is clean.
2. Run the test file three separate times, to rule out flakiness (the original report used reruns x2):
   `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/security/test_reset_admin.py -v'`
   Expected: every test in the file passes, including `test_the_administrators_sessions_end`, in all three runs.
3. Full backend suite: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest'`. Expected: no failure (about 4,500 tests); in particular no failure of `test_the_administrators_sessions_end`.
4. Linters as CI does, from `backend/`: `uv run ruff check .` and `uv run ruff format --check .`. Expected: clean.
5. Record each run with `record_tests` (command, passed, totals, failing names).

**If the test fails:** do not weaken the assertion. Diagnose from the output. If the test asks the wrong thing, fix the test; if a session of `admin` really survives the reset, fix `reset_admin`/session code (security bug). Keep the fix to that test and the code it exercises, commit as `fix(security): the administrator's sessions end on reset (MA-11)`, and report that the design's "no change" outcome was not met.
**If it passes only sometimes:** report it as flaky with the runs; do not close.
**If other tests fail:** report them; do not fix them here.

**Commit:** none when everything passes. No pull request.

## Final verification

- `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/security/test_reset_admin.py -v'` passes (three runs).
- `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest'` passes.
- From `backend/`: `uv run ruff check .` and `uv run ruff format --check .` are clean.
- `git status` is clean and `git diff origin/develop --stat` shows nothing.
