# Compose Restart Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every service in `docker-compose.yml` comes back after a crash or a reboot of the host, unless it was stopped on purpose.

**Architecture:** `restart: unless-stopped` on each of the four services, pinned by a test in `backend/tests/test_compose.py` (the Compose checks that need no Docker daemon), and one sentence in `docs/installation.md`.

**Tech Stack:** Docker Compose, pytest with PyYAML (already used by `test_compose.py`).

**Spec:** `docs/superpowers/specs/2026-11-15-compose-restart-design.md`

## Global Constraints

- The policy is exactly `unless-stopped`, on `db`, `backend`, `frontend` and `gateway`: not `always`, not `on-failure`.
- Nothing else in `docker-compose.yml` changes.

## Review Focus

- **A service added later without a policy:** the test asserts over every service in the file, not a fixed list of four, so a fifth service without `restart` fails it.
- **The frontend's allow-list of keys:** `test_the_frontend_is_given_no_secret_and_no_way_to_the_data` asserts its keys are exactly `{"image", "build", "healthcheck"}`; it must now include `"restart"` and still nothing that gives it a secret or data.
- **A reboot where the Docker service does not start at boot:** nothing restarts; the guide says so (Task 1, Step 5).

---

### Task 1: Restart every service unless it was stopped

**Files:**
- Modify: `docker-compose.yml` (each of the four services)
- Modify: `backend/tests/test_compose.py:53-57` and a new test after it
- Modify: `docs/installation.md:63-64`

**Interfaces:**
- Consumes: `services()` in `backend/tests/test_compose.py`.
- Produces: nothing later tasks use.

- [ ] **Step 1: Write the failing test, and widen the frontend's allow-list**

In `backend/tests/test_compose.py`, after `test_the_frontend_is_given_no_secret_and_no_way_to_the_data`:

```python
def test_every_service_comes_back_unless_it_was_stopped():
    # After a crash, and when the Docker daemon starts again after a reboot. A
    # container stopped on purpose stays stopped: `always` would start it again.
    assert {name: service.get("restart") for name, service in services().items()} == {
        name: "unless-stopped" for name in services()
    }
    assert set(services()) == {"db", "backend", "frontend", "gateway"}
```

And in `test_the_frontend_is_given_no_secret_and_no_way_to_the_data`, the allow-list becomes `{"image", "build", "restart", "healthcheck"}`.

- [ ] **Step 2: Run them to verify they fail**

Run (from `backend/`): `uv run pytest tests/test_compose.py -q`
Expected: FAIL in `test_every_service_comes_back_unless_it_was_stopped` (every value is `None`) and in the frontend test (`restart` missing).

- [ ] **Step 3: Add `restart: unless-stopped` to each service in `docker-compose.yml`**

Right after `image` (and after `build` where there is one), the same place in each service. No comment is needed on each. If one is added, a single line above the first explains `unless-stopped` over `always`.

- [ ] **Step 4: Run the Compose and document tests to verify they pass**

Run (from `backend/`): `uv run pytest tests/test_compose.py tests/test_documents.py -q`
Expected: PASS.

- [ ] **Step 5: Say it in the guide**

In `docs/installation.md`, after the two `docker compose down` lines (63-64), one paragraph: the containers start again after a crash, and after a reboot of the host when the Docker service starts at boot, unless they were stopped with `docker compose stop`. Name no `MEGOOARTI_` variable: `test_a_guide_names_no_variable_that_nothing_reads` checks the guide.

Run (from `backend/`): `uv run pytest tests/test_documents.py -q`
Expected: PASS.

- [ ] **Step 6: Check that Compose accepts the file**

Run (from the repository root): `docker compose --env-file backend/tests/compose.env config --quiet`, with `MEGOOARTI_DB_PASSWORD=x` set in the environment for that command.
Expected: exits 0 with no output. If no Docker CLI is available, say so and skip.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml backend/tests/test_compose.py docs/installation.md
git commit -m "feat(compose): every service comes back after a crash or a reboot unless it was stopped"
```
