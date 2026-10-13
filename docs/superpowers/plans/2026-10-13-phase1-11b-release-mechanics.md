# Release Mechanics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** What plans 1 to 11a built can be installed by somebody else and kept: it has a licence, a Compose file that starts nothing with a password everybody knows, images that say what they are, a backup that a test restores, the two other clients of a Maven repository, a measurement of how long answers take, and client tests that say why when they fail.

**Architecture:** Almost nothing of the product changes. The Compose file asks the environment for the database's password and names the images; the backend takes that password apart from the database's address, so that it may hold any character; and a connection to a proxy's remote that could not be made is tried again before it counts as a failure. The rest is scripts and tests: `scripts/backup.sh` and `scripts/restore.sh` are the procedure and are what the test runs; Gradle and sbt run in their own images against the stack, beside Maven; `backend/scripts/latency.py` sets up what is asked for and has a load generator do the asking; and a test of the stack that fails leaves the stack's logs behind.

**Tech Stack:** Docker Compose, POSIX `sh`, PostgreSQL 17 (`pg_dump`, `pg_restore`), pytest, httpx; the images `gradle:8-jdk21`, `sbtscala/scala-sbt` and `ghcr.io/hatoo/oha:1.16.0` for tests and measurement. No new dependency of the backend or the frontend.

**Spec:** [docs/superpowers/specs/2026-10-13-release-readiness-design.md](../specs/2026-10-13-release-readiness-design.md), section 5 (L1 to L8), with D1 and D2 of section 3 and section 7. Task 6 amends it where this plan settles something it left open (L9 to L18).

**Read first:** `docker-compose.yml`; `backend/tests/containers.py` and the `stack` and `administrator` fixtures of `backend/tests/conftest.py` (how the tests marked `docker` build and start a stack of their own); `backend/tests/test_maven_client.py` (how a client runs in its own image beside the stack); `backend/src/megooarti/repositories/remote.py` (`_open`, and how a failure of the remote is told from an answer); `backend/src/megooarti/secrets_box.py` (where the key is).

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| L9 | The copyright line of `LICENSE` names "The MegooArti Authors". | Whose name stands there is the owner's to say. |
| L10 | The tests' stack has a password and an image tag (`test`) of its own, given in the environment. | The images are now named for everybody: tests that built `megooarti/backend:0.1.0` would replace the one an installation on the same machine runs. |
| L11 | Backup and restore are `scripts/backup.sh` and `scripts/restore.sh`, and the test runs those. The database is dumped before the files are copied; restore refuses an installation that is not empty; the backup names the blob stores it cannot have. | A procedure that is a script is the same every time. The order is what makes the two halves fit while the installation runs. |
| L12 | A connection to a remote that could not be made is tried twice more (after 0.2 s and 1 s). One that timed out, and a request that was sent, are not. | The kept logs showed `ConnectError` to Maven Central on a request whose neighbours succeeded; behind a group that was "not there" to the client. |
| L13 | Of a test marked `docker` that fails, what the backend and the gateway said is kept beside the failed setups. | The stack is gone when its module ends. |
| L14 | Gradle and sbt run as Maven does, in their own images, in `test_maven_client.py`. Nothing of the Maven format had to change for them. | L5. |
| L15 | The latency script runs a load generator (`oha`) in a container to do the asking. | Written in Python it measured itself. |
| L16 | NFR-4 is measured and not met; the numbers and their machine are in the spec. | L6 measures; it does not mend. |
| L17 | The dependency scans are commands in the README, run once in Task 6; what they found is in the spec. | L8, without CI. |
| L18 | `MEGOOARTI_DATABASE_PASSWORD`: the backend takes the database's password apart from its address, and Compose gives it that way. | In the address, a password a password manager made is read as a host or a path. |

**Changed after the whole-branch review.** The task bodies below show the code as the tasks made it. The branch differs from them as follows; each change to the code was made test-first, and the spec's section 5 records what they settle as L19 to L26.

| # | Change | Reason |
| --- | --- | --- |
| F1 | `scripts/backup.sh` is written again: `umask 077`; the directory made whole before the script changes its own; `docker compose exec -T db true` and `... backend true` first; tar run through `sh -c` so that it prints `tar-status:<n>` to stderr; the three files written as `*.part` and renamed at the end; `fail()` ends with status 1, "NOT done", and the parts removed; no `--exclude`; the blob stores asked for are those outside `/var/lib/megooarti`. | The review (Critical): an empty archive written over a good one, and "done". |
| F2 | `scripts/restore.sh` is written again: both files must be there and not empty; `pg_restore --list` and `tar --list` before anything is written (exit 2, "Nothing was restored"); `pg_restore --single-transaction`; `half()` for a stop between the halves; psql or the image failing is exit 1 and not "is not empty"; the backup's version is said. | The review: a database restored and then a stop, with nothing said. |
| F3 | `test_backup_restore.py` has a stand-in for `docker` (a shell script put first on the `PATH`, answering as `FAKE_*` variables say) and twenty tests of the scripts' own decisions that need no daemon. The test of a real stack also stops the backend before a backup, keeps a blob store at `cache/tmp`, and restores from a copy whose archive is no archive. | The scripts' failures could not be met by a test that needs everything to work. |
| F4 | `backend/scripts/latency.py`: `NAMES` (the six repositories), `clean_up` removes those, `claim(client, replace=)` refuses to begin where one is there, `--replace`. | The review: it removed `latency-dashboards`. |
| F5 | `tests/failures.py`: `mark_of_the_stack(item, report)`, called from a `pytest_runtest_makereport` wrapper in `conftest.py`; `keep_stack_logs` looks at what it left on the report. | The review: the keyword `docker` is also a folder's name. |
| F6 | `docker-compose.yml`: `pull_policy: build` for both images. `db/wait.py`: the words for a refused password. `test_docker_client.py`: the two proxies of the test of public registries have `auto_block` off, as the others. `remote.py`: the comment says what is asked again across a redirect. | The review. |
| F7 | `tests/databases.py`: `connected(engine, tries=3)`, used by the `db_connection` fixture. | The suite's own run caught H8: Windows dropping a connection to the test database. |
| F8 | The README says what a backup needs and leaves behind, what a restore does when it stops, and whose the typefaces are; `.env.example` says how a single quote is written. | The review. |

## Global Constraints

- **Nothing an installation holds is changed:** no migration. A database made with the old Compose file has the password `megooarti`, and keeps it: put that in `.env`.
- **The unit and integration tests (`uv run pytest`) need no Docker daemon and contact no real network host.** What needs either is marked `docker`.
- **A test of the stack uses the tests' own stack** (`tests/containers.py`: project `megooarti-test`, ports 18000 and 15432, images tagged `test`) and never the one an installation or a developer runs.
- **Scripts are POSIX `sh`, with LF line endings,** and say what they do as they do it. They set `MSYS_NO_PATHCONV=1`, without which Git Bash on Windows rewrites the paths meant for a container.
- **Backend:** ruff clean, 100 columns. **No new dependency** of the backend or the frontend: the lock files do not change.
- **The spec's sections 6 and 8 are plan 11c's:** this plan writes into the README what it changes, and no guide.

**Working directories:** run `uv` and `pytest` commands in `backend/`, `pnpm` commands in `frontend/`, and `git` and `docker compose` commands in the repository root. Backend tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes. The tests marked `docker` take about twenty-five minutes together and need the internet.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **An installation started the easy way:** no `.env`, an empty password, a password with `@`, `/`, `#`, `?`, `%`, `&` and `$` in it, a password both in the address and apart (Task 1).
2. **A restore that would destroy something:** a database or a data directory that is not empty, a directory that holds no backup, a blob store whose files are outside the data directory, a file stored after the backup was made (Task 3).
3. **What must still open after a restore:** a session, an API token, a proxy's stored secret, an artifact of every format fetched as its client fetches it (Task 3).
4. **A remote that fails in different ways:** a connection refused once or twice and then taken, refused every time, timed out, answered with an error; each of the three ways the remote is asked (Task 2).
5. **A test's own help that fails:** Docker not there when the logs are asked for, a stack that says nothing, a test that is not of the stack (Task 2).

---

### Task 1: The licence, a Compose file for an installation, and images that say what they are

**Files:**
- Create: `LICENSE`, `.env.example`, `backend/tests/test_release.py`
- Modify: `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `backend/pyproject.toml`, `frontend/package.json`, `backend/src/megooarti/config.py`, `docs/BRD.md`, `backend/tests/containers.py`
- Test: `backend/tests/test_release.py`, `backend/tests/test_compose.py`, `backend/tests/test_config.py`, `backend/tests/test_container.py`

**Interfaces:**
- Consumes: `Settings` of `megooarti.config`; `megooarti.__version__`; `megooarti.api_docs.ASSETS`.
- Produces: `Settings.database_password` (`MEGOOARTI_DATABASE_PASSWORD`), put into `database_url` when it is set; in Compose, `MEGOOARTI_DB_PASSWORD` (required), `MEGOOARTI_VERSION` (default: the version), `MEGOOARTI_SECRET_KEY` (passed on if set), the images `megooarti/backend:<version>` and `megooarti/frontend:<version>` with the build argument `VERSION`; in `tests/containers.py`, `VERSION = "test"` and an `ENVIRONMENT` that has the tests' password and tag.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_release.py`:

```python
"""What a release says of itself: its licence and its version, the same everywhere."""

import json
import re
import tomllib
from pathlib import Path

import pytest

from megooarti import __version__
from megooarti.api_docs import ASSETS

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]
PACKAGE = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))


def test_the_licence_is_mit_and_both_packages_say_so():
    licence = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert licence.startswith("MIT License\n")
    assert "Permission is hereby granted, free of charge" in licence
    assert re.search(r"^Copyright \(c\) \d{4} .+$", licence, flags=re.MULTILINE)
    assert PROJECT["license"] == "MIT"
    assert PACKAGE["license"] == "MIT"


@pytest.mark.parametrize("image", ["backend", "frontend"])
def test_each_image_is_labelled_with_what_it_is(image):
    dockerfile = (ROOT / image / "Dockerfile").read_text(encoding="utf-8")
    labels = dict(re.findall(r'org\.opencontainers\.image\.(\w+)="([^"]*)"', dockerfile))

    assert labels["licenses"] == "MIT"
    assert labels["title"] == f"MegooArti {image}"
    # Whatever tag the image is built under: Compose says which (test_compose.py).
    assert labels["version"] == "${VERSION}"
    assert labels["source"].startswith("https://")
    # After everything else, so that a new version builds no other layer again.
    assert dockerfile.rstrip().endswith(f'source="{labels["source"]}"')


def test_what_is_not_ours_keeps_its_own_licence():
    assert "Apache License" in (ASSETS / "LICENSE").read_text(encoding="utf-8")


def test_one_version_is_said_everywhere():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert PROJECT["version"] == PACKAGE["version"] == __version__
    assert f"#MEGOOARTI_VERSION={__version__}\n" in example
```

Change `backend/tests/test_compose.py`:

```diff
@@ -6,6 +6,7 @@ from pathlib import Path
 import pytest
 import yaml
 
+from megooarti import __version__
 from megooarti.config import Settings
 
 COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
@@ -53,7 +54,7 @@ def test_the_frontend_is_given_no_secret_and_no_way_to_the_data():
     frontend = services()["frontend"]
 
     # It renders the shell. The browser, not this container, calls the backend.
-    assert set(frontend) == {"build", "healthcheck"}
+    assert set(frontend) == {"image", "build", "healthcheck"}
 
 
 def test_the_backend_takes_the_gateways_word_for_who_is_calling():
@@ -98,3 +99,50 @@ def test_the_gateway_passes_a_path_on_exactly_as_it_was_sent():
 )
 def test_the_gateway_does_what_artifacts_and_package_clients_need(directive):
     assert directive in GATEWAY
+
+
+def test_nothing_starts_with_a_password_everybody_knows():
+    whole = COMPOSE_FILE.read_text(encoding="utf-8")
+    password = services()["db"]["environment"]["POSTGRES_PASSWORD"]
+    address = services()["backend"]["environment"]["MEGOOARTI_DATABASE_URL"]
+
+    # `:?` stops Compose, with these words, where the variable is not set or is empty.
+    assert password.startswith("${MEGOOARTI_DB_PASSWORD:?Set MEGOOARTI_DB_PASSWORD.")
+    assert ".env.example" in password
+    # Apart from the address: in it, a password with an @ or a / would be read as a host
+    # or a path.
+    assert address == "postgresql://megooarti@db:5432/megooarti"
+    assert services()["backend"]["environment"]["MEGOOARTI_DATABASE_PASSWORD"] == password
+    assert "megooarti:megooarti" not in whole
+
+
+@pytest.mark.parametrize("name", ["backend", "frontend"])
+def test_the_images_are_named_as_a_registry_would_hold_them(name):
+    service = services()[name]
+    tag = f"${{MEGOOARTI_VERSION:-{__version__}}}"
+
+    assert service["image"] == f"megooarti/{name}:{tag}"
+    # The image is told the version it is built as, for its label.
+    assert service["build"] == {"context": f"./{name}", "args": {"VERSION": tag}}
+
+
+def test_the_secret_key_is_passed_on_only_if_it_is_set():
+    environment = services()["backend"]["environment"]
+
+    # No value: Compose passes on what its own environment has, and nothing otherwise.
+    assert "MEGOOARTI_SECRET_KEY" in environment
+    assert environment["MEGOOARTI_SECRET_KEY"] is None
+
+
+def test_the_example_names_everything_the_compose_file_asks_of_the_environment():
+    whole = COMPOSE_FILE.read_text(encoding="utf-8")
+    example = (COMPOSE_FILE.parent / ".env.example").read_text(encoding="utf-8")
+    asked = set(re.findall(r"\$\{(MEGOOARTI_[A-Z_]+)", whole))
+    asked |= {name for name, value in services()["backend"]["environment"].items() if value is None}
+
+    named = set(re.findall(r"^#?(MEGOOARTI_[A-Z_]+)=", example, flags=re.MULTILINE))
+
+    assert named == asked
+    # The one thing that must be chosen is chosen for nobody.
+    assert re.search(r"^MEGOOARTI_DB_PASSWORD=$", example, flags=re.MULTILINE)
+    assert len(re.findall(r"^MEGOOARTI_", example, flags=re.MULTILINE)) == 1
```

Change `backend/tests/test_container.py`:

```diff
@@ -3,11 +3,22 @@
 import hashlib
 import json
 import os
+import subprocess
 import urllib.request
 
 import pytest
 
-from tests.containers import BACKEND_DIR, DATA_FILE, HTTP_PORT, call, compose, run_in_backend
+from tests.containers import (
+    BACKEND_DIR,
+    DATA_FILE,
+    ENVIRONMENT,
+    HTTP_PORT,
+    REPOSITORY_ROOT,
+    VERSION,
+    call,
+    compose,
+    run_in_backend,
+)
 
 UNREACHABLE = "MEGOOARTI_DATABASE_URL=postgresql://megooarti:megooarti@nowhere.invalid:5432/m"
 
@@ -59,6 +70,49 @@ def test_container_does_not_run_as_root(stack):
     assert result.stdout.strip() == "10001"
 
 
+@pytest.mark.docker
+@pytest.mark.parametrize("name", ["backend", "frontend"])
+def test_the_images_are_built_under_their_names_and_say_what_they_are(stack, name):
+    inspected = subprocess.run(
+        ["docker", "image", "inspect", f"megooarti/{name}:{VERSION}"],
+        capture_output=True,
+        text=True,
+        encoding="utf-8",
+        check=False,
+    )
+    assert inspected.returncode == 0, inspected.stderr
+    labels = json.loads(inspected.stdout)[0]["Config"]["Labels"]
+
+    assert labels["org.opencontainers.image.title"] == f"MegooArti {name}"
+    assert labels["org.opencontainers.image.version"] == VERSION
+    assert labels["org.opencontainers.image.licenses"] == "MIT"
+    assert labels["org.opencontainers.image.source"].startswith("https://")
+
+
+@pytest.mark.docker
+def test_nothing_starts_without_the_databases_password(tmp_path):
+    # Neither in the environment nor in a file: as a checkout that was started at once.
+    (tmp_path / "empty.env").write_text("", encoding="utf-8")
+    environment = {
+        name: value for name, value in ENVIRONMENT.items() if name != "MEGOOARTI_DB_PASSWORD"
+    }
+
+    result = subprocess.run(
+        ["docker", "compose", "--env-file", str(tmp_path / "empty.env"), "config"],
+        cwd=REPOSITORY_ROOT,
+        env=environment,
+        capture_output=True,
+        text=True,
+        encoding="utf-8",
+        errors="replace",
+        check=False,
+    )
+
+    assert result.returncode != 0
+    assert "MEGOOARTI_DB_PASSWORD" in result.stderr
+    assert ".env.example" in result.stderr
+
+
 @pytest.mark.docker
 def test_the_first_start_administrator_can_sign_in_and_change_the_password(administrator):
     status, _, listed = call("GET", "/users", headers=administrator)
```

Change `backend/tests/test_config.py`:

```diff
@@ -1,5 +1,6 @@
 import pytest
 from pydantic import ValidationError
+from sqlalchemy.engine import make_url
 
 from megooarti.config import ConfigurationError, Settings, get_settings, load_settings
 
@@ -128,3 +129,50 @@ def test_the_npm_publish_limit(monkeypatch):
     monkeypatch.setenv("MEGOOARTI_NPM_MAX_PUBLISH_BYTES", "2048")
 
     assert Settings(_env_file=None).npm_max_publish_bytes == 2048
+
+
+ANY = "p@ss/w:rd#1 ?%&$"
+
+
+def test_a_password_given_apart_is_put_into_the_address_whatever_is_in_it():
+    settings = Settings(
+        _env_file=None,
+        database_url="postgresql://megooarti@db:5432/megooarti",
+        database_password=ANY,
+    )
+    address = make_url(settings.database_url)
+
+    assert (address.username, address.password, address.host) == ("megooarti", ANY, "db")
+    assert (address.port, address.database) == (5432, "megooarti")
+    assert address.drivername == "postgresql+asyncpg"
+    # As it is written, no character of it stands for anything but itself.
+    assert ANY not in settings.database_url
+
+
+def test_a_password_given_apart_goes_before_one_in_the_address():
+    settings = Settings(
+        _env_file=None,
+        database_url="postgresql://megooarti:old@db:5432/megooarti?sslmode=require",
+        database_password="new",
+    )
+    address = make_url(settings.database_url)
+
+    assert address.password == "new"
+    assert address.query == {"ssl": "require"}
+
+
+@pytest.mark.parametrize("apart", [None, ""])
+def test_without_a_password_apart_the_address_is_as_it_was_given(apart):
+    given = "postgresql://megooarti:megooarti@db:5432/megooarti"
+
+    settings = Settings(_env_file=None, database_url=given, database_password=apart)
+
+    assert settings.database_url == "postgresql+asyncpg://megooarti:megooarti@db:5432/megooarti"
+
+
+def test_the_password_apart_comes_from_the_environment(monkeypatch, tmp_path):
+    monkeypatch.chdir(tmp_path)
+    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", "postgresql://megooarti@db/megooarti")
+    monkeypatch.setenv("MEGOOARTI_DATABASE_PASSWORD", ANY)
+
+    assert make_url(load_settings().database_url).password == ANY
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_release.py tests/test_compose.py tests/test_config.py tests/test_container.py -q`
Expected: an error while collecting `tests/test_container.py`: `tests.containers` has no `VERSION` yet. Without that file among them, `test_release.py`, `test_compose.py` and `test_config.py` fail on what is not there: the licence, the image names, the password apart from the address.

- [ ] **Step 3: Implement**

Create `LICENSE`:

```text
MIT License

Copyright (c) 2026 The MegooArti Authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Create `.env.example`:

```text
# What an installation chooses. Copy this file to .env, beside docker-compose.yml:
# Docker Compose reads it from there.

# The database's password. Nothing starts without it. Any characters; put it in
# single quotes if it has a $, a # or a space in it. For example the output of:
#   openssl rand -base64 24
# It is set when the database is first made: changing it here later changes nothing
# in a database that exists.
MEGOOARTI_DB_PASSWORD=

# The port the gateway is published on.
#MEGOOARTI_HTTP_PORT=8000

# The database is published on this machine only (127.0.0.1), for backups and tools.
#MEGOOARTI_DB_PORT=5432

# The session cookie is kept by a browser over HTTPS only. Over plain HTTP from another
# machine nobody can sign in unless this is false: put TLS in front instead.
#MEGOOARTI_SESSION_COOKIE_SECURE=true

# The key that stored secrets (a proxy's password) are sealed with. Without it the
# backend makes one in its data directory, where a backup of that directory has it.
#MEGOOARTI_SECRET_KEY=

# The tag the images are built and run under. The default is this release's version.
#MEGOOARTI_VERSION=0.1.0
```

Change `docker-compose.yml`:

```diff
@@ -1,3 +1,6 @@
+# A complete installation: the database, the backend, the web UI and a gateway.
+# What an installation must choose is in .env (copy .env.example): without the
+# database's password nothing starts.
 name: megooarti
 
 services:
@@ -5,7 +8,7 @@ services:
     image: postgres:17-alpine
     environment:
       POSTGRES_USER: megooarti
-      POSTGRES_PASSWORD: megooarti
+      POSTGRES_PASSWORD: ${MEGOOARTI_DB_PASSWORD:?Set MEGOOARTI_DB_PASSWORD. Copy .env.example to .env and choose one}
       POSTGRES_DB: megooarti
     ports:
       # Loopback only: the database is published for development tools, not for the network.
@@ -20,9 +23,18 @@ services:
 
   # The API, the repositories and the registry. It is reached through the gateway only.
   backend:
-    build: ./backend
+    # `docker compose build` makes the image under the name a registry would hold it by.
+    image: megooarti/backend:${MEGOOARTI_VERSION:-0.1.0}
+    build:
+      context: ./backend
+      args:
+        VERSION: ${MEGOOARTI_VERSION:-0.1.0}
     environment:
-      MEGOOARTI_DATABASE_URL: postgresql://megooarti:megooarti@db:5432/megooarti
+      MEGOOARTI_DATABASE_URL: postgresql://megooarti@db:5432/megooarti
+      # Apart from the address, so that it may hold any character.
+      MEGOOARTI_DATABASE_PASSWORD: ${MEGOOARTI_DB_PASSWORD:?Set MEGOOARTI_DB_PASSWORD. Copy .env.example to .env and choose one}
+      # Passed on if it is set. Without it the backend makes a key in its data directory.
+      MEGOOARTI_SECRET_KEY:
       # This container is not published: requests from outside come through the
       # gateway, which says who is calling and overwrites what a client says of itself.
       MEGOOARTI_FORWARDED_ALLOW_IPS: "*"
@@ -49,7 +61,11 @@ services:
   # The web UI. It holds no data and no secret, and never calls the backend: the
   # browser does.
   frontend:
-    build: ./frontend
+    image: megooarti/frontend:${MEGOOARTI_VERSION:-0.1.0}
+    build:
+      context: ./frontend
+      args:
+        VERSION: ${MEGOOARTI_VERSION:-0.1.0}
     healthcheck:
       test:
         - CMD
```

Change `backend/Dockerfile`:

```diff
@@ -30,3 +30,11 @@ EXPOSE 8000
 
 ENTRYPOINT ["/app/docker-entrypoint.sh"]
 CMD ["python", "-m", "megooarti"]
+
+# What the image is. Last, so that a new version does not build the layers above again.
+ARG VERSION=0.0.0
+LABEL org.opencontainers.image.title="MegooArti backend" \
+      org.opencontainers.image.description="The API, the repositories and the registry of MegooArti" \
+      org.opencontainers.image.version="${VERSION}" \
+      org.opencontainers.image.licenses="MIT" \
+      org.opencontainers.image.source="https://github.com/mmhy2003/MegooArti"
```

Change `frontend/Dockerfile`:

```diff
@@ -34,3 +34,11 @@ USER node
 EXPOSE 3000
 
 CMD ["node", "server.js"]
+
+# What the image is. Last, so that a new version does not build the layers above again.
+ARG VERSION=0.0.0
+LABEL org.opencontainers.image.title="MegooArti frontend" \
+      org.opencontainers.image.description="The web UI of MegooArti" \
+      org.opencontainers.image.version="${VERSION}" \
+      org.opencontainers.image.licenses="MIT" \
+      org.opencontainers.image.source="https://github.com/mmhy2003/MegooArti"
```

Change `backend/pyproject.toml`:

```diff
@@ -2,6 +2,7 @@
 name = "megooarti"
 version = "0.1.0"
 description = "MegooArti repository and artifact manager (backend)"
+license = "MIT"
 requires-python = ">=3.13"
 dependencies = [
     "alembic>=1.20.0",
```

Change `backend/src/megooarti/config.py`:

```diff
@@ -5,8 +5,9 @@ from pathlib import Path
 from typing import Literal
 from urllib.parse import parse_qsl, urlencode
 
-from pydantic import ValidationError, field_validator
+from pydantic import ValidationError, field_validator, model_validator
 from pydantic_settings import BaseSettings, SettingsConfigDict
+from sqlalchemy.engine import make_url
 
 ENV_PREFIX = "MEGOOARTI_"
 _POSTGRES_SCHEMES = {"postgres", "postgresql", "postgresql+asyncpg"}
@@ -25,6 +26,9 @@ class Settings(BaseSettings):
     )
 
     database_url: str
+    # The password of that address, when it is kept apart from it. An address gives
+    # a meaning to some characters (@ / # ? %); apart, a password may hold any.
+    database_password: str | None = None
     log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
     host: str = "0.0.0.0"
     port: int = 8000
@@ -60,6 +64,13 @@ class Settings(BaseSettings):
             rest = f"{location}?{urlencode(options)}"
         return f"postgresql+asyncpg://{rest}"
 
+    @model_validator(mode="after")
+    def _put_the_password_into_the_address(self) -> "Settings":
+        if self.database_password:
+            address = make_url(self.database_url).set(password=self.database_password)
+            self.database_url = address.render_as_string(hide_password=False)
+        return self
+
     @field_validator("log_level", mode="before")
     @classmethod
     def _upper_case_the_level(cls, value: object) -> object:
```

Change `frontend/package.json`:

```diff
@@ -2,6 +2,7 @@
   "name": "megooarti-frontend",
   "version": "0.1.0",
   "private": true,
+  "license": "MIT",
   "scripts": {
     "dev": "next dev",
     "build": "next build",
```

Change `docs/BRD.md`:

```diff
@@ -352,7 +352,7 @@ These are decisions already made. Designs must conform to them.
 
 | ID | Assumption |
 | --- | --- |
-| A-1 | The licence is Apache-2.0. This is a placeholder pending the owner's confirmation. |
+| A-1 | The licence is MIT, as the owner chose (release readiness design, D1). |
 | A-2 | "Nexus OSS parity" means the feature set of Nexus Repository OSS 3.x as summarised in Appendix A. Formats added to Nexus after this baseline are considered release by release. |
 | A-3 | Operators provide TLS termination, backups of the database volume and blob storage, and monitoring infrastructure. |
 | A-4 | A deployment is a single logical instance serving one organisation. |
```

Change `backend/tests/containers.py`:

```diff
@@ -11,7 +11,16 @@ BACKEND_DIR = Path(__file__).resolve().parents[1]
 REPOSITORY_ROOT = BACKEND_DIR.parent
 PROJECT = "megooarti-test"
 HTTP_PORT = "18000"
-ENVIRONMENT = {**os.environ, "MEGOOARTI_HTTP_PORT": HTTP_PORT, "MEGOOARTI_DB_PORT": "15432"}
+# The tag the tests' images are built under: not the one an installation runs.
+VERSION = "test"
+ENVIRONMENT = {
+    **os.environ,
+    "MEGOOARTI_HTTP_PORT": HTTP_PORT,
+    "MEGOOARTI_DB_PORT": "15432",
+    # With what an address would take for something else: it is given apart from it.
+    "MEGOOARTI_DB_PASSWORD": "only for these tests: @/#?%&$",
+    "MEGOOARTI_VERSION": VERSION,
+}
 DATA_FILE = "/var/lib/megooarti/admin.password"
 
 
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_release.py tests/test_compose.py tests/test_config.py tests/test_container.py -q`
Expected: 51 passed, 11 deselected (those of `test_container.py` that need a Docker daemon).

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv lock --check`
Expected: no finding, and the lock file is as it was: naming the licence adds no dependency.

Run (in `backend/`): `uv run pytest -m docker tests/test_container.py -q`
Expected: 11 passed, 1 deselected. The stack starts with a password that has `@`, `/`, `#`, `?`, `%`, `&` and `$` in it; both images are found under their names with their labels; and Compose refuses to start anything where the password is not set.

- [ ] **Step 5: Commit**

```bash
git add LICENSE .env.example docker-compose.yml backend frontend/Dockerfile frontend/package.json docs/BRD.md
git commit -m "feat: the MIT licence, a Compose file that asks for the database's password, and images that say what they are"
```

---

### Task 2: A connection that could not be made is tried again, and a failed test of the stack keeps its logs

**Files:**
- Modify: `backend/src/megooarti/repositories/remote.py`
- Modify: `backend/tests/repositories/fake_remote.py`, `backend/tests/failures.py`, `backend/tests/conftest.py`
- Test: `backend/tests/repositories/test_remote.py`, `backend/tests/test_support.py`

**Interfaces:**
- Consumes: `remote._open`, `remote._token`; `failures.keep_failure`, `containers.compose`.
- Produces: `remote.CONNECT_WAITS = (0.2, 1.0)` and `remote._send(client, build)`; `FakeRemote.refuses` and `FakeRemote.connections`; an autouse fixture that makes the waits nothing in tests; `failures.keep_stack_logs(report, logs, directory=DIRECTORY) -> Path | None`; `failures.say_where(write_line, kept, one="failed setup", many="failed setups")`.

- [ ] **Step 1: Write the failing tests**

Change `backend/tests/repositories/test_remote.py`:

```diff
@@ -124,6 +124,77 @@ async def test_an_unreachable_remote_is_a_blockable_failure(fake, stage):
     assert outcome == remote.Failed("ConnectError", blockable=True)
 
 
+async def test_a_connection_that_could_not_be_made_is_tried_again(fake, stage):
+    # A network that drops one connection, or two, is not a remote that is down.
+    fake.refuses = 2
+
+    outcome = await fetch(fake, stage)
+
+    assert isinstance(outcome, remote.Fetched)
+    assert (fake.connections, len(fake.requests)) == (3, 1)
+
+
+async def test_a_remote_that_takes_no_connection_is_a_failure_after_three_tries(
+    fake, stage, monkeypatch
+):
+    waited: list[float] = []
+
+    async def wait(seconds: float) -> None:
+        waited.append(seconds)
+
+    monkeypatch.setattr(remote, "CONNECT_WAITS", (0.2, 1.0))
+    monkeypatch.setattr(remote.asyncio, "sleep", wait)
+    fake.down = True
+
+    outcome = await fetch(fake, stage)
+
+    assert outcome == remote.Failed("ConnectError", blockable=True)
+    assert fake.connections == 3
+    assert waited == [0.2, 1.0]  # a little longer before each further try
+
+
+@pytest.mark.parametrize("ask", ["download", "fetch", "head"])
+async def test_every_way_of_asking_tries_a_connection_again(fake, stage, ask):
+    fake.refuses = 1
+    async with fake.client() as client:
+        if ask == "download":
+            outcome = await remote.download(client, URL, authorization=None, stage=stage)
+        elif ask == "fetch":
+            outcome = await remote.fetch(client, URL, authorization=None, limit=1000)
+        else:
+            outcome = await remote.head(client, URL, authorization=None)
+
+    assert not isinstance(outcome, remote.Failed)
+    assert fake.connections == 2
+
+
+async def test_a_request_that_was_answered_is_not_sent_again(fake, stage):
+    # 503 is an answer: the remote saw the request. Only what was never sent is repeated.
+    fake.status = 503
+
+    outcome = await fetch(fake, stage)
+
+    assert isinstance(outcome, remote.Failed)
+    assert (fake.connections, len(fake.requests)) == (1, 1)
+
+
+async def test_a_connection_that_took_too_long_is_not_tried_again(stage):
+    connections = 0
+
+    class Slow(httpx.AsyncBaseTransport):
+        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
+            nonlocal connections
+            connections += 1
+            raise httpx.ConnectTimeout("timed out", request=request)
+
+    async with remote.new_client(transport=Slow()) as client:
+        outcome = await remote.download(client, URL, authorization=None, stage=stage)
+
+    # It has waited as long as a connection may take: three times that is no help.
+    assert outcome == remote.Failed("ConnectTimeout", blockable=True)
+    assert connections == 1
+
+
 async def test_a_file_shorter_than_declared_is_a_failure_and_leaves_nothing(fake, stage, tmp_path):
     fake.declared_extra = 5
 
```

Change `backend/tests/test_support.py`:

```diff
@@ -11,7 +11,13 @@ from fastapi import FastAPI
 from tests import containers
 from tests.clients import client_for
 from tests.databases import reset_schema
-from tests.failures import KEPT, keep_broken_setup, keep_failure, say_where
+from tests.failures import (
+    KEPT,
+    keep_broken_setup,
+    keep_failure,
+    keep_stack_logs,
+    say_where,
+)
 
 
 async def test_client_for_runs_the_application_lifespan():
@@ -153,3 +159,53 @@ def test_a_compose_command_that_may_fail_is_answered_as_it_ended(monkeypatch):
     result = containers.compose("down", "--volumes", check=False)
 
     assert (result.returncode, result.stderr) == (1, "no such service")
+
+
+class _Report:
+    """What pytest reports of one phase of one test, as far as the hooks look at it."""
+
+    def __init__(self, *, failed: bool, when: str = "call", docker: bool = True) -> None:
+        self.failed, self.when = failed, when
+        self.nodeid = "tests/test_pypi_client.py::test_pip_installs"
+        self.longreprtext = "AssertionError: pip: exit 1"
+        self.keywords = {"docker": 1} if docker else {}
+
+
+def test_what_the_stack_said_is_kept_when_a_test_of_it_fails(tmp_path):
+    said = "backend-1  | remote_failed repository=pypi-proxy reason=it did not answer in time\n"
+
+    kept = keep_stack_logs(_Report(failed=True), lambda: said, tmp_path)
+
+    assert kept is not None and "-call-logs-" in kept.name
+    assert "remote_failed repository=pypi-proxy" in kept.read_text(encoding="utf-8")
+
+
+def test_the_stack_is_not_asked_when_nothing_failed_or_the_test_is_not_of_it(tmp_path):
+    def asked() -> str:
+        raise AssertionError("the stack was asked")
+
+    assert keep_stack_logs(_Report(failed=False), asked, tmp_path) is None
+    assert keep_stack_logs(_Report(failed=True, docker=False), asked, tmp_path) is None
+    assert list(tmp_path.iterdir()) == []
+
+
+def test_a_stack_that_says_nothing_or_cannot_be_asked_does_not_cost_the_run(tmp_path):
+    def gone() -> str:
+        raise FileNotFoundError("docker")
+
+    assert keep_stack_logs(_Report(failed=True, when="setup"), lambda: "  \n", tmp_path) is None
+    assert keep_stack_logs(_Report(failed=True), gone, tmp_path) is None
+    assert list(tmp_path.iterdir()) == []
+
+
+def test_the_end_of_the_run_says_how_many_of_each_were_kept(tmp_path):
+    said: list[str] = []
+    one, two = tmp_path / "a.txt", tmp_path / "b.txt"
+
+    say_where(said.append, [one])
+    say_where(said.append, [one, two], "log of the stack", "logs of the stack")
+
+    assert said == [
+        f"1 failed setup kept in {tmp_path}",
+        f"2 logs of the stack kept in {tmp_path}",
+    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/repositories/test_remote.py tests/test_support.py -q`
Expected: an error while collecting `tests/test_support.py`: `tests.failures` has no `keep_stack_logs`. Run alone, the new tests of `test_remote.py` fail: the fake remote counts no connections, and one refused connection is a failure at once.

- [ ] **Step 3: Implement**

Change `backend/src/megooarti/repositories/remote.py`:

```diff
@@ -4,6 +4,7 @@ Every outcome is a value, not an exception, so the proxy engine decides what a f
 means: serve a cached copy, answer 404, or count it towards blocking the remote.
 """
 
+import asyncio
 import base64
 import hashlib
 import ipaddress
@@ -31,6 +32,12 @@ Stage = Callable[[AsyncIterator[bytes], int | None], Awaitable[StagedBlob]]
 # What a HEAD answer passes on to the client.
 _HEAD_HEADERS = ("Content-Length", "Content-Type", "Last-Modified", "ETag")
 
+# A connection that could not be made is tried again before it is called a failure, and
+# this is how long is waited before each further try. Nothing was sent, so nothing is
+# repeated; and one connection that a network dropped is not an outage, though behind
+# a group it would be answered as "not there".
+CONNECT_WAITS = (0.2, 1.0)
+
 
 @dataclass(frozen=True)
 class Fetched:
@@ -340,13 +347,15 @@ async def _token(
     if authorization and authorization.startswith("Basic "):
         # The remote named this address as the place its users sign in.
         headers["Authorization"] = authorization
-    request = client.build_request(
-        "GET",
-        challenge.realm,
-        params={name: value for name, value in wanted.items() if value},
-        headers=headers,
+    response = await _send(
+        client,
+        lambda: client.build_request(
+            "GET",
+            challenge.realm,
+            params={name: value for name, value in wanted.items() if value},
+            headers=headers,
+        ),
     )
-    response = await client.send(request, stream=True)
     try:
         if response.status_code in (401, 403):
             # No status: this is not the remote's answer about what was asked for, and
@@ -389,6 +398,23 @@ async def _read(response: httpx.Response, limit: int) -> bytes | None:
     return bytes(received)
 
 
+async def _send(client: httpx.AsyncClient, build: Callable[[], httpx.Request]) -> httpx.Response:
+    """Send a request and return the answer with its body unread.
+
+    A connection that could not be made is tried again (CONNECT_WAITS). Not one that
+    took too long to make: that has waited already. And not a request that was sent:
+    whatever became of it, the remote may have seen it.
+    """
+    for wait in (*CONNECT_WAITS, None):
+        try:
+            return await client.send(build(), stream=True)
+        except httpx.ConnectError:
+            if wait is None:
+                raise
+            await asyncio.sleep(wait)
+    raise AssertionError("the last try answers or raises")
+
+
 async def _open(
     client: httpx.AsyncClient,
     method: str,
@@ -407,7 +433,7 @@ async def _open(
 
     async def send(credential: str | None) -> httpx.Response:
         sent = {**headers, "Authorization": credential} if credential else headers
-        return await client.send(client.build_request(method, url, headers=sent), stream=True)
+        return await _send(client, lambda: client.build_request(method, url, headers=sent))
 
     if sign_in is None:
         return await send(authorization)
```

Change `backend/tests/repositories/fake_remote.py`:

```diff
@@ -25,8 +25,12 @@ class _Transport(httpx.AsyncBaseTransport):
         self._inner = httpx.ASGITransport(app=remote.app)
 
     async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
+        self._remote.connections += 1
         if self._remote.down:
             raise httpx.ConnectError("connection refused", request=request)
+        if self._remote.refuses > 0:
+            self._remote.refuses -= 1
+            raise httpx.ConnectError("connection reset", request=request)
         return await self._inner.handle_async_request(request)
 
 
@@ -38,6 +42,10 @@ class FakeRemote:
         self.declared_extra = 0
         self.redirect_to: str | None = None
         self.down = False
+        # How many connections are still refused before one is taken, and how many
+        # were tried at all.
+        self.refuses = 0
+        self.connections = 0
         self.delay = 0.0
         self.set_cookie: str | None = None
         self.content_encoding: str | None = None
```

Change `backend/tests/failures.py`:

```diff
@@ -43,8 +43,28 @@ def keep_broken_setup(report, directory: Path = DIRECTORY) -> Path | None:
         return None
 
 
-def say_where(write_line, kept: list[Path]) -> None:
+def keep_stack_logs(report, logs, directory: Path = DIRECTORY) -> Path | None:
+    """For a test of the running stack that failed: keep what the stack said.
+
+    `logs` asks the stack, and answers its text. The stack is gone when its module of
+    tests ends, and with it the one place that says why a client was refused. The text
+    has what the backend logs once on its first start, the administrator's first
+    password: of a stack that these tests made and remove.
+    """
+    if not report.failed or "docker" not in report.keywords:
+        return None
+    try:
+        said = logs()
+        if not said.strip():
+            return None  # no stack: its build failed, and that is in the setup's own text
+        return keep_failure(directory, report.nodeid, f"{report.when}-logs", said)
+    except Exception:  # noqa: BLE001 (whatever Docker does, the run goes on)
+        return None
+
+
+def say_where(
+    write_line, kept: list[Path], one: str = "failed setup", many: str = "failed setups"
+) -> None:
     """For pytest's `pytest_terminal_summary`: a file nobody knows of is read by nobody."""
     if kept:
-        setups = "setup" if len(kept) == 1 else "setups"
-        write_line(f"{len(kept)} failed {setups} kept in {kept[0].parent}")
+        write_line(f"{len(kept)} {one if len(kept) == 1 else many} kept in {kept[0].parent}")
```

Change `backend/tests/conftest.py`:

```diff
@@ -20,7 +20,7 @@ from sqlalchemy.pool import NullPool
 from megooarti.config import Settings, get_settings
 from megooarti.db.schema import alembic_config
 from megooarti.main import create_app
-from megooarti.repositories import service
+from megooarti.repositories import remote, service
 from megooarti.repositories.models import Repository
 from megooarti.security import passwords, tokens, users
 from megooarti.security.models import User
@@ -28,7 +28,7 @@ from tests.accounts import PASSWORD, sign_in
 from tests.clients import client_for
 from tests.containers import DATA_FILE, call, compose
 from tests.databases import ensure_database, reset_schema
-from tests.failures import keep_broken_setup, say_where
+from tests.failures import keep_broken_setup, keep_stack_logs, say_where
 
 DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://megooarti:megooarti@localhost:5432/megooarti_test"
 
@@ -38,17 +38,30 @@ pytest_plugins = ["pytester"]
 
 
 _kept: list[Path] = []
+_logs: list[Path] = []
+
+
+def _stack_logs() -> str:
+    said = compose("logs", "--no-color", "--tail", "4000", "backend", "gateway", check=False)
+    return said.stdout
 
 
 def pytest_runtest_logreport(report: pytest.TestReport) -> None:
-    """Keep what a failed setup said, whatever becomes of the run's own output."""
+    """Keep what a failed setup said, whatever becomes of the run's own output.
+
+    And of a test of the running stack that failed, what the stack said.
+    """
     path = keep_broken_setup(report)
     if path is not None:
         _kept.append(path)
+    logs = keep_stack_logs(report, _stack_logs)
+    if logs is not None:
+        _logs.append(logs)
 
 
 def pytest_terminal_summary(terminalreporter) -> None:
     say_where(terminalreporter.write_line, _kept)
+    say_where(terminalreporter.write_line, _logs, "log of the stack", "logs of the stack")
 
 
 def _configured_test_database_url() -> str:
@@ -63,6 +76,12 @@ def _fresh_settings_cache():
     get_settings.cache_clear()
 
 
+@pytest.fixture(autouse=True)
+def _no_waiting_for_remotes(monkeypatch):
+    """A remote that refuses a connection is asked again after a wait: in tests, at once."""
+    monkeypatch.setattr(remote, "CONNECT_WAITS", (0.0, 0.0))
+
+
 @pytest.fixture(scope="session")
 def database_url() -> str:
     """A database migrated to head, shared by the whole test session."""
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/repositories/test_remote.py tests/repositories/test_proxy.py tests/repositories/test_remote_sign_in.py tests/test_support.py -q`
Expected: 187 passed. (The files of one directory are named together: pytest loses the fixtures of `tests/repositories` when a file from elsewhere is named between two of its own.) A remote that is down is still one failure of the proxy, counted once.

Run (in `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
Expected: no finding, and 2851 passed, 1 skipped. With the waits made nothing by the fixture, the suite takes as long as it did.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "fix(proxy): a connection to the remote that could not be made is tried again; test: a failed test of the stack keeps its logs"
```

---

### Task 3: Backup and restore

**Files:**
- Create: `scripts/backup.sh`, `scripts/restore.sh`
- Test: `backend/tests/test_backup_restore.py`

**Interfaces:**
- Consumes: the Compose services `db` and `backend`; `tests/containers.py` (`ENVIRONMENT`, `PROJECT`, `compose`, `call`, `upload`); the helpers of the unit tests that make a package of each format (`tests/repositories/{npm,pypi,docker}/conftest.py`).
- Produces: `scripts/backup.sh <directory>` (writes `database.dump`, `data.tar`, `VERSION`; exit 0, or tar's status above 1); `scripts/restore.sh <directory>` (exit 2: no backup there; exit 3: the installation is not empty).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_backup_restore.py`:

```python
"""Backup and restore, done with the scripts an operator is given (NFR-12).

The one that runs them needs a Docker daemon and a POSIX shell (`sh`): on Windows, Git's.
"""

import base64
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import pytest

from megooarti import __version__
from tests.containers import ENVIRONMENT, HTTP_PORT, PROJECT, REPOSITORY_ROOT, call, compose, upload
from tests.repositories.docker.conftest import config_for, digest_of, image_manifest, layer
from tests.repositories.npm.conftest import publish_body, tarball_of
from tests.repositories.pypi.conftest import content_of

SCRIPTS = REPOSITORY_ROOT / "scripts"
SHELL = shutil.which("sh")
HOST = f"http://127.0.0.1:{HTTP_PORT}"
WHEEL = "megooarti_kept-1.0.0-py3-none-any.whl"
JAR = "releases/com/acme/app/1.0/app-1.0.jar"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def script(name: str, *arguments: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    """Run one of the scripts as an operator would, against the tests' own stack."""
    assert SHELL, "sh is not on the PATH: the scripts are shell scripts (on Windows, Git has one)"
    return subprocess.run(
        [SHELL, (SCRIPTS / name).as_posix(), *arguments],
        env={**ENVIRONMENT, "COMPOSE_PROJECT_NAME": PROJECT},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


@pytest.mark.parametrize("name", ["backup.sh", "restore.sh"])
def test_the_scripts_are_shell_scripts_with_unix_line_endings(name):
    text = (SCRIPTS / name).read_bytes()

    assert text.startswith(b"#!/bin/sh\n")
    assert b"\r" not in text
    assert b"set -eu\n" in text


@pytest.mark.skipif(SHELL is None, reason="needs a POSIX shell")
@pytest.mark.parametrize("name", ["backup.sh", "restore.sh"])
def test_a_script_given_nothing_says_how_it_is_used(name):
    result = script(name, timeout=30)

    assert result.returncode != 0
    assert f"usage: {name} <directory>" in result.stderr


@pytest.mark.skipif(SHELL is None, reason="needs a POSIX shell")
def test_restoring_from_a_directory_that_holds_no_backup_touches_nothing(tmp_path):
    result = script("restore.sh", tmp_path.as_posix(), timeout=30)

    assert result.returncode == 2
    assert "has no database.dump and data.tar" in result.stderr


def send(method: str, address: str, data: bytes | None = None, headers: dict | None = None):
    """One request to the published gateway: (status, headers, body)."""
    request = urllib.request.Request(
        urllib.parse.urljoin(HOST, address), method=method, data=data, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def push_image(headers: dict, tag: str, *texts: str) -> bytes:
    """An image pushed to `images/app` as a registry client pushes it. Returns its manifest."""
    config = config_for(*texts)
    layers = [layer(text) for text in texts]
    for data in (config, *layers):
        status, begun, _ = send("POST", "/v2/images/app/blobs/uploads/", headers=headers)
        assert status == 202
        status, sent, _ = send("PATCH", begun["Location"], data, headers)
        assert status == 202
        status, _, body = send("PUT", f"{sent['Location']}?digest={digest_of(data)}", None, headers)
        assert status == 201, body
    manifest = image_manifest(config, *layers)
    status, _, body = send(
        "PUT",
        f"/v2/images/app/manifests/{tag}",
        manifest,
        {**headers, "Content-Type": OCI_MANIFEST},
    )
    assert status == 201, body
    return manifest


@pytest.mark.docker
def test_a_backup_restored_into_a_new_installation_has_everything(administrator, tmp_path):
    status, _, created = call("POST", "/me/tokens", {"name": "backup-test"}, administrator)
    assert status == 201, created
    token = created["token"]
    basic = base64.b64encode(f"__token__:{token}".encode()).decode()
    client = {"Authorization": f"Basic {basic}"}

    # A blob store whose files are not under the data directory: the backup cannot have them.
    status, _, body = call(
        "POST", "/blob-stores", {"name": "elsewhere", "path": "/tmp/elsewhere"}, administrator
    )
    assert status == 201, body
    repositories = [
        {"name": "files", "format": "raw", "type": "hosted"},
        {"name": "releases", "format": "maven", "type": "hosted"},
        {"name": "packages", "format": "npm", "type": "hosted"},
        {"name": "wheels", "format": "pypi", "type": "hosted"},
        {"name": "images", "format": "docker", "type": "hosted"},
        {
            # A proxy of this installation's own repository, which it reaches with a
            # secret: sealed with the key that is in the data directory.
            "name": "mirror",
            "format": "raw",
            "type": "proxy",
            "proxy": {
                "remote_url": "http://gateway/repository/files",
                "remote_auth": {"type": "bearer", "secret": token},
            },
        },
    ]
    for repository in repositories:
        status, _, body = call("POST", "/repositories", repository, administrator)
        assert status == 201, body

    # Something of every format, each put there as its own clients put it.
    for path in ("docs/cached.txt", "docs/never-fetched.txt"):
        assert send("PUT", f"/repository/files/{path}", path.encode(), client)[0] == 201
    assert send("PUT", f"/repository/{JAR}", b"PK the jar", client)[0] == 201
    published = json.dumps(publish_body("megooarti-kept", "1.0.0")).encode()
    status, _, body = send(
        "PUT",
        "/repository/packages/megooarti-kept",
        published,
        {**client, "Content-Type": "application/json"},
    )
    assert status in (200, 201), body
    status, stored = upload("wheels", {}, [("file", WHEEL, content_of(WHEEL))], client)
    assert status == 201, stored
    manifest = push_image(client, "1.0", "one layer", "another")
    # The proxy has fetched one of the two files, and not the other.
    assert send("GET", "/repository/mirror/docs/cached.txt", headers=client)[0] == 200

    target = tmp_path / "backup"
    backed_up = script("backup.sh", target.as_posix())
    assert backed_up.returncode == 0, backed_up.stderr
    assert (target / "database.dump").stat().st_size > 10_000
    assert (target / "data.tar").stat().st_size > 10_000
    assert (target / "VERSION").read_text(encoding="utf-8").strip() == __version__
    assert "the blob store elsewhere at /tmp/elsewhere" in backed_up.stderr
    assert "NOT in this backup" in backed_up.stderr

    # What comes after the backup is not in it.
    assert send("PUT", "/repository/files/docs/after.txt", b"after", client)[0] == 201

    compose("down", "--volumes")
    restored = script("restore.sh", target.as_posix())
    assert restored.returncode == 0, restored.stderr + restored.stdout[-2000:]

    # The session that was open and the token that was made are those of the backup.
    status, _, session = call("GET", "/auth/session", headers=administrator)
    assert (status, session["authenticated"]) == (200, True)
    for path in ("docs/cached.txt", "docs/never-fetched.txt"):
        status, _, body = send("GET", f"/repository/files/{path}", headers=client)
        assert (status, body) == (200, path.encode())
    assert send("GET", "/repository/files/docs/after.txt", headers=client)[0] == 404
    assert send("GET", f"/repository/{JAR}", headers=client)[2] == b"PK the jar"
    status, _, document = send("GET", "/repository/packages/megooarti-kept", headers=client)
    assert list(json.loads(document)["versions"]) == ["1.0.0"]
    status, _, tarball = send(
        "GET", "/repository/packages/megooarti-kept/-/megooarti-kept-1.0.0.tgz", headers=client
    )
    assert (status, tarball) == (200, tarball_of("megooarti-kept", "1.0.0"))
    status, _, page = send("GET", "/repository/wheels/simple/megooarti-kept/", headers=client)
    assert status == 200 and WHEEL.encode() in page
    status, _, wheel = send(
        "GET", f"/repository/wheels/packages/megooarti-kept/1.0.0/{WHEEL}", headers=client
    )
    assert (status, wheel) == (200, content_of(WHEEL))
    status, _, pulled = send(
        "GET", "/v2/images/app/manifests/1.0", headers={**client, "Accept": OCI_MANIFEST}
    )
    assert (status, pulled) == (200, manifest)
    for data in (layer("one layer"), layer("another")):
        status, _, blob = send("GET", f"/v2/images/app/blobs/{digest_of(data)}", headers=client)
        assert (status, blob) == (200, data)
    # The proxy's secret is read with the key that came back with the data directory:
    # what it had not fetched before is fetched now.
    status, _, body = send("GET", "/repository/mirror/docs/never-fetched.txt", headers=client)
    assert (status, body) == (200, b"docs/never-fetched.txt")
    status, _, shown = call("GET", "/repositories/mirror", headers=administrator)
    assert shown["status"]["last_error"] is None

    # And an installation that has something in it is not written over.
    again = script("restore.sh", target.as_posix())
    assert again.returncode == 3
    assert "is not empty" in again.stderr
    assert send("GET", "/repository/files/docs/cached.txt", headers=client)[0] == 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_backup_restore.py -q`
Expected: 5 failed, 1 deselected: the scripts are not there.

- [ ] **Step 3: Implement**

Create `scripts/backup.sh`:

```text
#!/bin/sh
# Back up a running installation into a directory: the database, then the data directory.
#
#   scripts/backup.sh <directory>
#
# Run it where docker-compose.yml and .env are. Nothing is stopped. The order is what
# makes the two halves fit: a file is on the disk before the database names it, and is
# kept there for a day after nothing names it any more. So a copy of the files made
# after the database was dumped has every file that dump names.
set -eu

target=${1:?usage: backup.sh <directory>}
cd "$(dirname "$0")/.."
# Git Bash on Windows would rewrite the paths meant for the containers.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
mkdir -p "$target"

echo "backup: the database"
docker compose exec -T db pg_dump --username megooarti --format custom megooarti \
    > "$target/database.dump"

echo "backup: the data directory"
status=0
docker compose exec -T backend tar --create --file - --directory /var/lib/megooarti \
    --exclude './blobs/*/tmp' . > "$target/data.tar" || status=$?
# 1 is tar's "a file changed while it was read": an upload that was going on. What the
# database names does not change once it is there.
if [ "$status" -gt 1 ]; then
    echo "backup: the data directory could not be read (tar ended with $status)" >&2
    exit "$status"
fi

docker compose exec -T backend python -c 'import megooarti; print(megooarti.__version__)' \
    | tr -d '\r' > "$target/VERSION"

# A blob store may keep its files anywhere. Those under the data directory are in the
# copy; the others are not this script's to find.
outside=$(docker compose exec -T db psql --username megooarti --dbname megooarti --no-align \
    --tuples-only --command \
    "select name || ' at ' || (config->>'path') from blob_stores where config->>'path' like '/%'" \
    | tr -d '\r')
if [ -n "$outside" ]; then
    echo "backup: NOT in this backup, because they are outside the data directory:" >&2
    echo "$outside" | sed 's/^/backup:   the blob store /' >&2
fi

echo "backup: done, version $(cat "$target/VERSION"), in $target"
```

Create `scripts/restore.sh`:

```text
#!/bin/sh
# Restore what scripts/backup.sh wrote, into an installation that has nothing in it yet.
#
#   scripts/restore.sh <directory>
#
# Run it where docker-compose.yml and .env are, with the same MEGOOARTI_DB_PASSWORD or
# another: the password is this installation's, not the backup's. It refuses a database
# or a data directory that is not empty. `docker compose down --volumes` empties both.
# A backup of an older version is brought up to this one when the backend starts.
set -eu

source=${1:?usage: restore.sh <directory>}
if [ ! -f "$source/database.dump" ] || [ ! -f "$source/data.tar" ]; then
    echo "restore: $source has no database.dump and data.tar" >&2
    exit 2
fi
source=$(cd "$source" && pwd)
cd "$(dirname "$0")/.."
# Git Bash on Windows would rewrite the paths meant for the containers.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

echo "restore: starting the database"
docker compose up --detach --wait db

tables=$(docker compose exec -T db psql --username megooarti --dbname megooarti --no-align \
    --tuples-only --command \
    "select count(*) from information_schema.tables where table_schema = 'public'" | tr -d '\r')
if [ "$tables" != 0 ]; then
    echo "restore: the database is not empty. Restore into a new installation." >&2
    exit 3
fi
if ! docker compose run --rm --no-deps -T --entrypoint sh backend \
    -c 'test -z "$(ls -A /var/lib/megooarti)"'; then
    echo "restore: the data directory is not empty. Restore into a new installation." >&2
    exit 3
fi

echo "restore: the database"
docker compose exec -T db pg_restore --username megooarti --dbname megooarti --no-owner \
    --exit-on-error < "$source/database.dump"

echo "restore: the data directory"
docker compose run --rm --no-deps -T --entrypoint tar backend --extract --file - \
    --directory /var/lib/megooarti < "$source/data.tar"

echo "restore: starting everything"
docker compose up --detach --wait
echo "restore: done"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_backup_restore.py -q`
Expected: 5 passed, 1 deselected.

Run (in `backend/`): `uv run pytest -m docker tests/test_backup_restore.py -q`
Expected: 1 passed, in about two minutes. Something of every format is stored; the backup is made while the stack runs; the stack is removed with its volumes; and after the restore every file is fetched again as its client fetches it, the session and the token of before still work, and the proxy reads its secret.

- [ ] **Step 5: Commit**

The scripts are run with `sh`, and are also marked as programs for whoever runs them by name.

```bash
git add backend/tests/test_backup_restore.py scripts
git update-index --chmod=+x scripts/backup.sh scripts/restore.sh
git commit -m "feat: backup and restore, as scripts that a test runs"
```

---

### Task 4: Gradle and sbt, and public registries that are asked again

**Files:**
- Test: `backend/tests/test_maven_client.py`, `backend/tests/test_npm_client.py`, `backend/tests/test_pypi_client.py`, `backend/tests/test_docker_client.py`

**Interfaces:**
- Consumes: the `repositories` fixture of `test_maven_client.py` (`releases`, `snapshots`, `central`, `maven-public`, and the account `ci`, which may add and read).
- Produces: `client(image, cache, project, script)`, of which `maven`, `gradle` and `sbt` are uses; `said(result)`.

This task has no code of the product: both clients were run against the Maven format as it is, and it took what they sent. The tests are what the task leaves.

- [ ] **Step 1: Write the tests**

Change `backend/tests/test_maven_client.py`:

```diff
@@ -1,11 +1,13 @@
-"""Maven's own client against the built image.
+"""The clients of a Maven repository against the built image: Maven, Gradle and sbt.
 
-Run with `pytest -m docker`. Besides a Docker daemon these need internet access: Maven
-fetches its plugins from Maven Central.
+Run with `pytest -m docker`. Besides a Docker daemon these need internet access: each
+client fetches its plugins, and what the test libraries depend on, from Maven Central,
+through the proxy the tests make.
 """
 
 import base64
 import hashlib
+import json
 import random
 import re
 import subprocess
@@ -114,6 +116,146 @@ CONSUMER_POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
 </project>
 """
 
+# Gradle. It publishes what Maven does and a file of its own beside the POM (the
+# "module"), with four checksums of each, and prefers the module when it resolves.
+GRADLE_IMAGE = "gradle:8-jdk21"
+GRADLE_CACHE = f"{PROJECT}-gradle-cache"
+GRADLE = "gradle --no-daemon --console=plain"
+GRADLE_LIBRARY = "io/megooarti/test/gradle-library"
+# One repository of the installation, as a Gradle build names it. Plain HTTP must be
+# allowed by name: the stack has no TLS.
+GRADLE_REPOSITORY = """{{
+        url = uri('{server}/{name}')
+        allowInsecureProtocol = true
+        credentials {{
+            username = '{username}'
+            password = '{password}'
+        }}
+    }}"""
+
+GRADLE_LIBRARY_BUILD = """plugins {{
+    id 'java-library'
+    id 'maven-publish'
+}}
+
+group = 'io.megooarti.test'
+version = '{version}'
+
+java {{
+    sourceCompatibility = JavaVersion.VERSION_17
+    targetCompatibility = JavaVersion.VERSION_17
+}}
+
+repositories {{
+    maven {everything}
+}}
+
+dependencies {{
+    api 'org.apache.commons:commons-lang3:3.14.0'
+}}
+
+publishing {{
+    publications {{
+        library(MavenPublication) {{
+            from components.java
+        }}
+    }}
+    repositories {{
+        maven {target}
+    }}
+}}
+"""
+
+GRADLE_LIBRARY_SOURCE = """package io.megooarti.test;
+
+import org.apache.commons.lang3.StringUtils;
+
+public class GradleLibrary {
+    public static String greeting() {
+        return StringUtils.capitalize("hello");
+    }
+}
+"""
+
+GRADLE_CONSUMER_BUILD = """plugins {{
+    id 'java'
+}}
+
+repositories {{
+    maven {everything}
+}}
+
+dependencies {{
+    implementation 'io.megooarti.test:gradle-library:{version}'
+}}
+"""
+
+GRADLE_CONSUMER_SOURCE = """package io.megooarti.test.consumer;
+
+import io.megooarti.test.GradleLibrary;
+
+public class Consumer {
+    public static String greeting() {
+        return GradleLibrary.greeting();
+    }
+}
+"""
+
+# sbt. It resolves with Coursier and publishes with Ivy, in Maven's layout. The image
+# is the one that has this sbt and this Scala in it, so that only what the build
+# depends on is fetched.
+SBT_IMAGE = "sbtscala/scala-sbt:eclipse-temurin-21.0.12_8_1.13.0_2.13.18"
+SBT = "sbt -batch -Dsbt.color=false -Dsbt.supershell=false"
+SBT_LIBRARY = "io/megooarti/test/sbt-library"
+# What every sbt build of these tests says of the installation: where everything comes
+# from, and who asks. The realm is the one the server names when it asks who is there.
+SBT_SERVER = """ThisBuild / scalaVersion := "2.13.18"
+ThisBuild / organization := "io.megooarti.test"
+ThisBuild / crossPaths := false
+ThisBuild / autoScalaLibrary := false
+ThisBuild / credentials += Credentials("MegooArti", "gateway", "{username}", "{password}")
+ThisBuild / externalResolvers := Seq(
+  ("megooarti" at "{server}/maven-public").withAllowInsecureProtocol(true)
+)
+"""
+
+SBT_LIBRARY_BUILD = """name := "sbt-library"
+version := "{version}"
+libraryDependencies += "org.apache.commons" % "commons-text" % "1.12.0"
+publishMavenStyle := true
+publishTo := {{
+  val name = if (isSnapshot.value) "snapshots" else "releases"
+  Some(("megooarti-" + name at "{server}/" + name).withAllowInsecureProtocol(true))
+}}
+"""
+
+SBT_LIBRARY_SOURCE = """package io.megooarti.test;
+
+import org.apache.commons.text.WordUtils;
+
+public class SbtLibrary {
+    public static String greeting() {
+        return WordUtils.capitalize("hello");
+    }
+}
+"""
+
+SBT_CONSUMER_BUILD = """name := "sbt-consumer"
+version := "1"
+libraryDependencies += "io.megooarti.test" % "sbt-library" % "{version}"
+"""
+
+SBT_CONSUMER_SOURCE = """package io.megooarti.test.consumer;
+
+import io.megooarti.test.SbtLibrary;
+
+public class Consumer {
+    public static String greeting() {
+        return SbtLibrary.greeting();
+    }
+}
+"""
+
 CONSUMER_SOURCE = """package io.megooarti.test.consumer;
 
 import io.megooarti.test.Library;
@@ -195,19 +337,23 @@ def consumers(directory: Path, versions: dict[str, str]) -> Path:
     return write(directory, files)
 
 
-def maven(project: Path, script: str) -> subprocess.CompletedProcess[str]:
-    """Run a shell script in the Maven image, in a copy of `project`, beside the stack."""
+def client(
+    image: str, cache: str | None, project: Path, script: str
+) -> subprocess.CompletedProcess[str]:
+    """Run a shell script in a client's image, in a copy of `project`, beside the stack.
+
+    `cache` is a volume and where the client keeps what it fetched, as `name:/path`.
+    """
     command = [
         "docker",
         "run",
         "--rm",
         "--network",
         NETWORK,
-        "--volume",
-        f"{CACHE}:/root/.m2",
+        *(["--volume", cache] if cache else []),
         "--volume",
         f"{project}:/src:ro",
-        IMAGE,
+        image,
         "sh",
         "-c",
         f"cp -r /src /work && cd /work && {script}",
@@ -223,6 +369,19 @@ def maven(project: Path, script: str) -> subprocess.CompletedProcess[str]:
     )
 
 
+def maven(project: Path, script: str) -> subprocess.CompletedProcess[str]:
+    return client(IMAGE, f"{CACHE}:/root/.m2", project, script)
+
+
+def gradle(project: Path, script: str) -> subprocess.CompletedProcess[str]:
+    return client(GRADLE_IMAGE, f"{GRADLE_CACHE}:/home/gradle/.gradle", project, script)
+
+
+def sbt(project: Path, script: str) -> subprocess.CompletedProcess[str]:
+    # No volume: the image has sbt and the compiler it names, and the rest is fetched.
+    return client(SBT_IMAGE, None, project, script)
+
+
 def fetch(path: str) -> bytes:
     basic = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
     request = urllib.request.Request(
@@ -252,7 +411,8 @@ def repositories(administrator) -> Iterator[None]:
         "name": "central",
         "format": "maven",
         "type": "proxy",
-        "proxy": {"remote_url": "https://repo1.maven.org/maven2"},
+        # Not left alone after one failure: the internet may be slow once (L7).
+        "proxy": {"remote_url": "https://repo1.maven.org/maven2", "auto_block": False},
     }
     everything = {
         "name": "maven-public",
@@ -279,7 +439,10 @@ def repositories(administrator) -> Iterator[None]:
     status, _, body = call("POST", "/users", user, administrator)
     assert status == 201, body
     yield
-    subprocess.run(["docker", "volume", "rm", "--force", CACHE], capture_output=True, check=False)
+    for volume in (CACHE, GRADLE_CACHE):
+        subprocess.run(
+            ["docker", "volume", "rm", "--force", volume], capture_output=True, check=False
+        )
 
 
 def test_maven_deploys_a_release_and_two_snapshot_builds_and_resolves_them(repositories, tmp_path):
@@ -519,3 +682,142 @@ def test_a_jar_uploaded_through_the_api_is_resolved_by_a_build(repositories, tmp
         )
         assert downloaded in resolved.stdout, resolved.stdout[-4000:]
     assert "The POM for io.megooarti.test:library:jar:3.0 is" not in resolved.stdout
+
+
+def gradle_repository(name: str) -> str:
+    return GRADLE_REPOSITORY.format(server=INSIDE, name=name, username=USERNAME, password=PASSWORD)
+
+
+def gradle_library(directory: Path, version: str) -> Path:
+    target = "snapshots" if version.endswith("-SNAPSHOT") else "releases"
+    files = {
+        "settings.gradle": "rootProject.name = 'gradle-library'\n",
+        "build.gradle": GRADLE_LIBRARY_BUILD.format(
+            version=version,
+            everything=gradle_repository("maven-public"),
+            target=gradle_repository(target),
+        ),
+        "src/main/java/io/megooarti/test/GradleLibrary.java": GRADLE_LIBRARY_SOURCE,
+    }
+    return write(directory, files)
+
+
+def gradle_consumer(directory: Path, version: str) -> Path:
+    files = {
+        "settings.gradle": "rootProject.name = 'gradle-consumer'\n",
+        "build.gradle": GRADLE_CONSUMER_BUILD.format(
+            version=version, everything=gradle_repository("maven-public")
+        ),
+        "src/main/java/io/megooarti/test/consumer/Consumer.java": GRADLE_CONSUMER_SOURCE,
+    }
+    return write(directory, files)
+
+
+def test_gradle_publishes_a_release_and_snapshots_and_resolves_them_through_the_group(
+    repositories, tmp_path
+):
+    release = gradle_library(tmp_path / "release", "3.0")
+    snapshot = gradle_library(tmp_path / "snapshot", "3.1-SNAPSHOT")
+
+    # The library needs a library of Maven Central's, which comes through the group.
+    published = gradle(release, f"{GRADLE} publish")
+    assert published.returncode == 0, said(published)
+    again = gradle(release, f"{GRADLE} publish")
+    assert again.returncode != 0, "a release was published twice"
+    assert "status code 403" in again.stdout + again.stderr, said(again)
+    for _ in range(2):
+        built = gradle(snapshot, f"{GRADLE} publish")
+        assert built.returncode == 0, said(built)
+
+    # What Gradle published is there as Gradle left it: the module beside the POM, and
+    # each with the checksums a client checks it by.
+    directory = f"releases/{GRADLE_LIBRARY}/3.0"
+    jar = fetch(f"{directory}/gradle-library-3.0.jar")
+    module = fetch(f"{directory}/gradle-library-3.0.module")
+    assert jar.startswith(b"PK")
+    assert json.loads(module)["component"]["version"] == "3.0"
+    assert b"published-with-gradle-metadata" in fetch(f"{directory}/gradle-library-3.0.pom")
+    for name, content in (("gradle-library-3.0.jar", jar), ("gradle-library-3.0.module", module)):
+        assert fetch(f"{directory}/{name}.sha1").decode() == hashlib.sha1(content).hexdigest()
+        assert fetch(f"{directory}/{name}.sha256").decode() == hashlib.sha256(content).hexdigest()
+        assert fetch(f"{directory}/{name}.sha512").decode() == hashlib.sha512(content).hexdigest()
+    listed = metadata.parse(fetch(f"releases/{GRADLE_LIBRARY}/maven-metadata.xml"))
+    assert (listed.versions, listed.release) == (("3.0",), "3.0")
+
+    builds = metadata.parse(fetch(f"snapshots/{GRADLE_LIBRARY}/3.1-SNAPSHOT/maven-metadata.xml"))
+    newest = {entry.extension: entry.value for entry in builds.snapshot_versions}
+    assert builds.snapshot_build == 2
+    assert {"jar", "pom", "module"} <= set(newest)
+    assert newest["jar"].endswith("-2")
+
+    # A Gradle that has never seen either: everything comes from the server, the public
+    # library through the proxy, and Gradle reads its own module file to find it.
+    for version in ("3.0", "3.1-SNAPSHOT"):
+        project = gradle_consumer(tmp_path / f"consumer-{version}", version)
+        resolved = gradle(
+            project, f"{GRADLE} --gradle-user-home /tmp/never-used --info compileJava"
+        )
+        assert resolved.returncode == 0, said(resolved)
+        assert "BUILD SUCCESSFUL" in resolved.stdout
+        assert f"{INSIDE}/maven-public/{GRADLE_LIBRARY}/{version}/" in resolved.stdout
+        assert "commons-lang3-3.14.0.jar" in resolved.stdout
+
+
+def said(result: subprocess.CompletedProcess[str]) -> str:
+    """The end of what a client printed, for when it failed."""
+    return (result.stdout + result.stderr)[-6000:]
+
+
+def sbt_project(directory: Path, build: str, sources: dict[str, str]) -> Path:
+    server = SBT_SERVER.format(server=INSIDE, username=USERNAME, password=PASSWORD)
+    files = {
+        "project/build.properties": "sbt.version=1.13.0\n",
+        "build.sbt": server + build,
+        **sources,
+    }
+    return write(directory, files)
+
+
+def sbt_library(directory: Path, version: str) -> Path:
+    build = SBT_LIBRARY_BUILD.format(version=version, server=INSIDE)
+    source = {"src/main/java/io/megooarti/test/SbtLibrary.java": SBT_LIBRARY_SOURCE}
+    return sbt_project(directory, build, source)
+
+
+def sbt_consumer(directory: Path, version: str) -> Path:
+    build = SBT_CONSUMER_BUILD.format(version=version)
+    source = {"src/main/java/io/megooarti/test/consumer/Consumer.java": SBT_CONSUMER_SOURCE}
+    return sbt_project(directory, build, source)
+
+
+def test_sbt_publishes_a_release_and_a_snapshot_and_resolves_them_through_the_group(
+    repositories, tmp_path
+):
+    release = sbt_library(tmp_path / "release", "4.0")
+    snapshot = sbt_library(tmp_path / "snapshot", "4.1-SNAPSHOT")
+
+    # The library needs one of Maven Central's, which Coursier fetches through the group.
+    published = sbt(release, f"{SBT} publish")
+    assert published.returncode == 0, said(published)
+    again = sbt(release, f"{SBT} publish")
+    assert again.returncode != 0, "a release was published twice"
+    built = sbt(snapshot, f"{SBT} publish")
+    assert built.returncode == 0, said(built)
+
+    directory = f"releases/{SBT_LIBRARY}/4.0"
+    jar = fetch(f"{directory}/sbt-library-4.0.jar")
+    assert jar.startswith(b"PK")
+    assert fetch(f"{directory}/sbt-library-4.0.jar.sha1").decode() == hashlib.sha1(jar).hexdigest()
+    pom = fetch(f"{directory}/sbt-library-4.0.pom")
+    assert b"<artifactId>sbt-library</artifactId>" in pom and b"commons-text" in pom
+    # sbt also publishes the sources and the documentation, each as a jar of its own.
+    for classifier in ("sources", "javadoc"):
+        assert fetch(f"{directory}/sbt-library-4.0-{classifier}.jar").startswith(b"PK")
+    listed = metadata.parse(fetch(f"releases/{SBT_LIBRARY}/maven-metadata.xml"))
+    assert (listed.versions, listed.release) == (("4.0",), "4.0")
+
+    for version in ("4.0", "4.1-SNAPSHOT"):
+        project = sbt_consumer(tmp_path / f"consumer-{version}", version)
+        resolved = sbt(project, f"{SBT} compile")
+        assert resolved.returncode == 0, said(resolved)
+        assert "[success]" in resolved.stdout
```

Change `backend/tests/test_npm_client.py`:

```diff
@@ -263,7 +263,8 @@ def group_token(token, administrator) -> str:
         "name": PROXY,
         "format": "npm",
         "type": "proxy",
-        "proxy": {"remote_url": "https://registry.npmjs.org"},
+        # Not left alone after one failure: the internet may be slow once (L7).
+        "proxy": {"remote_url": "https://registry.npmjs.org", "auto_block": False},
     }
     public = {
         "name": GROUP,
```

Change `backend/tests/test_pypi_client.py`:

```diff
@@ -269,7 +269,8 @@ def group_index(token, administrator) -> str:
         "name": PROXY,
         "format": "pypi",
         "type": "proxy",
-        "proxy": {"remote_url": "https://pypi.org"},
+        # Not left alone after one failure: the internet may be slow once (L7).
+        "proxy": {"remote_url": "https://pypi.org", "auto_block": False},
     }
     public = {
         "name": GROUP,
```

Change `backend/tests/test_docker_client.py`:

```diff
@@ -327,7 +327,8 @@ def test_a_group_serves_what_was_pushed_and_what_is_public_and_what_was_pushed_w
     signed_in, administrator, tmp_path
 ):
     config = signed_in
-    hub = {"remote_url": "https://registry-1.docker.io"}
+    # Not left alone after one failure: the internet may be slow once (L7).
+    hub = {"remote_url": "https://registry-1.docker.io", "auto_block": False}
     repositories = [
         {"name": "team-images", "format": "docker", "type": "hosted"},
         {"name": "hub-mirror", "format": "docker", "type": "proxy", "proxy": hub},
```

- [ ] **Step 2: Run them**

Run (in `backend/`): `uv run pytest -m docker tests/test_maven_client.py -q`
Expected: 6 passed, in about six minutes the first time (the two images are fetched). Gradle publishes a release, is refused the second time, publishes two snapshot builds, and a Gradle that has seen neither resolves both through the group, with the library of Maven Central's they depend on. sbt does the same with one snapshot.

- [ ] **Step 3: Commit**

```bash
git add backend/tests
git commit -m "test: Gradle and sbt publish to and resolve from a Maven repository"
```

---

### Task 5: How long answers take

**Files:**
- Create: `backend/scripts/latency.py`
- Test: `backend/tests/test_latency_script.py`

**Interfaces:**
- Consumes: the API (`/api/v1/repositories`, `/api/v1/content/{repository}/upload`), the repositories' own addresses, and `docker run`.
- Produces: `latency.command(url, *, clients, total, headers, network) -> list[str]`; `latency.read(name, total, report) -> Measured`; `Measured.line()`; `HEADING`; `GENERATOR = "ghcr.io/hatoo/oha:1.16.0"`. Exit status 1 if any request failed.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_latency_script.py`:

```python
"""The script that measures how long answers take (NFR-4): what it asks of the load
generator, and how it reads what the generator reports."""

import importlib.util
import subprocess
import sys

import pytest

from tests.containers import BACKEND_DIR, HTTP_PORT, PROJECT, call

SCRIPT = BACKEND_DIR / "scripts" / "latency.py"


def load_script():
    spec = importlib.util.spec_from_file_location("megooarti_latency_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


latency = load_script()

# What oha 1.16 reports, cut to what is read. Times are in seconds.
REPORT = {
    "summary": {"successRate": 1.0, "slowest": 0.5846, "requestsPerSec": 201.34},
    "latencyPercentiles": {"p50": 0.4919, "p95": 0.5576, "p99": 0.5847},
    "statusCodeDistribution": {"200": 2000},
    "errorDistribution": {},
}


def test_the_generator_is_a_container_of_one_version_on_the_network_it_is_told():
    command = latency.command(
        "http://gateway/repository/files/a.txt",
        clients=100,
        total=2000,
        headers={"Authorization": "Basic abc", "Accept": "text/plain"},
        network="megooarti_default",
    )

    assert command[:5] == ["docker", "run", "--rm", "--network", "megooarti_default"]
    assert command[5] == latency.GENERATOR == "ghcr.io/hatoo/oha:1.16.0"
    # Not drawn on a screen, and reported so that it can be read.
    assert command[6:9] == ["--no-tui", "--output-format", "json"]
    assert command[9:13] == ["-n", "2000", "-c", "100"]
    assert command[13:17] == ["-H", "Authorization: Basic abc", "-H", "Accept: text/plain"]
    assert command[-1] == "http://gateway/repository/files/a.txt"


def test_what_the_generator_reports_is_read_in_milliseconds():
    measured = latency.read("session", 2000, REPORT)

    assert (measured.p50, measured.p95, measured.p99) == (491.9, 557.6, 584.7)
    assert (measured.slowest, measured.per_second, measured.failed) == (584.6, 201.34, 0)
    assert measured.line().split() == ["session", "491.9", "557.6", "584.7", "584.6", "201", "0"]
    # The columns stand under their headings.
    assert len(measured.line()) == len(latency.HEADING)


def test_an_answer_that_is_not_what_was_asked_for_has_failed_and_so_has_one_that_never_came():
    refused = {**REPORT, "statusCodeDistribution": {"200": 1900, "401": 60, "502": 30}}

    measured = latency.read("maven metadata", 2000, refused)

    # 90 answers that were not the file, and 10 requests that were not answered at all.
    assert measured.failed == 100
    assert measured.line().split()[-1] == "100"


def test_a_server_that_answered_nothing_is_said_to_have_answered_nothing():
    silent = {
        "summary": {"successRate": 0.0, "slowest": None, "requestsPerSec": 0.0},
        "latencyPercentiles": {"p50": None, "p95": None, "p99": None},
        "statusCodeDistribution": {},
        "errorDistribution": {"connection refused": 40},
    }

    measured = latency.read("raw file", 40, silent)

    assert measured.line() == f"{'raw file':<24} no request was answered (40 failed)"


@pytest.mark.docker
def test_the_latency_script_measures_every_format_and_leaves_nothing_behind(administrator):
    status, _, created = call("POST", "/me/tokens", {"name": "latency-test"}, administrator)
    assert status == 201

    measured = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *("--url", f"http://127.0.0.1:{HTTP_PORT}"),
            *("--token", created["token"]),
            *("--network", f"{PROJECT}_default", "--inside-url", "http://gateway"),
            *("--clients", "5", "--requests", "3"),
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )

    assert measured.returncode == 0, measured.stdout + measured.stderr
    lines = measured.stdout.splitlines()
    assert lines[0] == "5 clients at once, 3 requests each, of http://gateway"
    names = [" ".join(line.split()[:-6]) for line in lines[2:]]
    assert names == [
        "raw file",
        "maven metadata",
        "npm document",
        "pypi page",
        "docker manifest",
        "maven metadata, proxy",
    ]
    assert all(line.split()[-1] == "0" for line in lines[2:]), measured.stdout  # none failed
    status, _, listed = call("GET", "/repositories", headers=administrator)
    assert not [item["name"] for item in listed["items"] if item["name"].startswith("latency-")]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (in `backend/`): `uv run pytest tests/test_latency_script.py -q`
Expected: an error while collecting: there is no `scripts/latency.py` to load.

- [ ] **Step 3: Implement**

Create `backend/scripts/latency.py`:

```python
"""How long a request for metadata takes when many clients ask at once (NFR-4).

Run from the backend/ directory, against an installation that is running, with an API
token of an administrator. Against the Compose stack of this repository:

    uv run python scripts/latency.py --url http://localhost:8000 --token mga_... \\
        --network megooarti_default --inside-url http://gateway

It makes a repository of each format, named `latency-...`, and puts one small thing
into each, as that format's clients would. Then, for each format, `--clients` clients
at once ask, `--requests` times each, for what a client asks for before anything else:
Maven's metadata of an artifact, npm's document of a package, PyPI's page of a project,
a registry's manifest by tag, a Raw file. It prints how long the answers took, and
removes what it made.

The asking is done by `oha`, a load generator, in a container of its own (Docker is
needed where this runs): a program in Python cannot ask fast enough to measure a server
and measures itself instead. `--network` is the Docker network that container joins,
and `--inside-url` the installation's address on it. Without them the container uses
the host's network and `--url`. With `--inside-url`, a Maven proxy of the
installation's own repository is made and asked as well: an answer from a proxy's
cache, which is what NFR-4 names.

The token is on the command line of that container, where whoever may list the
processes of this machine can read it: use one made for the measurement, and revoke it.

The numbers are of the machine the installation runs on, with the load generator
taking its share of it when both are on one machine. They say nothing of another.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass

import httpx

GENERATOR = "ghcr.io/hatoo/oha:1.16.0"
PREFIX = "latency"
PACKAGE = "latency-package"
JAR = "com/acme/latency/1.0/latency-1.0.jar"
MAVEN_METADATA = "com/acme/latency/maven-metadata.xml"
WHEEL = "latency_package-1.0.0-py3-none-any.whl"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"

HEADING = f"{'':<24}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}{'per s':>10}{'failed':>8}"


@dataclass(frozen=True)
class Measured:
    name: str
    # In milliseconds, of every answer; None where there was no answer at all.
    p50: float | None
    p95: float | None
    p99: float | None
    slowest: float | None
    per_second: float
    failed: int  # answers that were not 200, and requests that got none

    def line(self) -> str:
        if self.p50 is None:
            return f"{self.name:<24} no request was answered ({self.failed} failed)"
        numbers = "".join(
            f"{value:>9.1f}" for value in (self.p50, self.p95, self.p99, self.slowest)
        )
        return f"{self.name:<24}{numbers}{self.per_second:>10.0f}{self.failed:>8}"


def command(
    url: str, *, clients: int, total: int, headers: dict[str, str], network: str
) -> list[str]:
    """The load generator, as a container: `total` requests from `clients` at once."""
    said = [argument for name, value in headers.items() for argument in ("-H", f"{name}: {value}")]
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        GENERATOR,
        "--no-tui",
        "--output-format",
        "json",
        "-n",
        str(total),
        "-c",
        str(clients),
        *said,
        url,
    ]


def read(name: str, total: int, report: dict) -> Measured:
    """What the load generator reported of one address, as one line of the table."""
    answered = report.get("statusCodeDistribution") or {}
    percentiles = report.get("latencyPercentiles") or {}
    summary = report.get("summary") or {}

    def milliseconds(seconds: float | None) -> float | None:
        return None if seconds is None else round(seconds * 1000, 3)

    return Measured(
        name=name,
        p50=milliseconds(percentiles.get("p50")),
        p95=milliseconds(percentiles.get("p95")),
        p99=milliseconds(percentiles.get("p99")),
        slowest=milliseconds(summary.get("slowest")),
        per_second=summary.get("requestsPerSec") or 0.0,
        failed=total - int(answered.get("200", 0)),
    )


def measure(
    name: str, url: str, *, clients: int, requests: int, headers: dict[str, str], network: str
) -> Measured:
    total = clients * requests
    asked = subprocess.run(
        command(url, clients=clients, total=total, headers=headers, network=network),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if asked.returncode != 0:
        raise SystemExit(f"the load generator could not be run:\n{asked.stderr[-2000:]}")
    return read(name, total, json.loads(asked.stdout))


def _expect(response: httpx.Response, *statuses: int) -> httpx.Response:
    if response.status_code not in statuses:
        request = response.request
        raise SystemExit(
            f"{request.method} {request.url}: {response.status_code} {response.text[:300]}"
        )
    return response


def _npm_publish(package: str, version: str) -> dict:
    data = f"\x1f\x8b a tarball of {package}@{version}".encode()
    dist = {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": f"http://client.example/{package}/-/{package}-{version}.tgz",
    }
    return {
        "_id": package,
        "name": package,
        "dist-tags": {"latest": version},
        "versions": {version: {"name": package, "version": version, "dist": dist}},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(data).decode(),
                "length": len(data),
            }
        },
    }


async def _push_image(client: httpx.AsyncClient, repository: str) -> None:
    config = json.dumps({"architecture": "amd64", "os": "linux"}).encode()
    layer = b"\x1f\x8b a layer"
    described = []
    for data in (config, layer):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        begun = _expect(await client.post(f"/v2/{repository}/app/blobs/uploads/"), 202)
        sent = _expect(await client.patch(begun.headers["Location"], content=data), 202)
        _expect(await client.put(sent.headers["Location"], params={"digest": digest}), 201)
        described.append({"digest": digest, "size": len(data)})
    manifest = {
        "schemaVersion": 2,
        "mediaType": OCI_MANIFEST,
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json", **described[0]},
        "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", **described[1]}],
    }
    _expect(
        await client.put(
            f"/v2/{repository}/app/manifests/1.0",
            content=json.dumps(manifest).encode(),
            headers={"Content-Type": OCI_MANIFEST},
        ),
        201,
    )


async def set_up(client: httpx.AsyncClient, inside_url: str | None, token: str) -> list[tuple]:
    """Make the repositories and what is in them. Returns (name, path, headers) to ask for."""
    for format in ("raw", "maven", "npm", "pypi", "docker"):
        body = {"name": f"{PREFIX}-{format}", "format": format, "type": "hosted"}
        _expect(await client.post("/api/v1/repositories", json=body), 201)
    _expect(await client.put(f"/repository/{PREFIX}-raw/a/file.txt", content=b"a file"), 201)
    _expect(await client.put(f"/repository/{PREFIX}-maven/{JAR}", content=b"PK a jar"), 201)
    published = _npm_publish(PACKAGE, "1.0.0")
    _expect(await client.put(f"/repository/{PREFIX}-npm/{PACKAGE}", json=published), 200, 201)
    wheel = {"file": (WHEEL, b"PK a wheel", "application/octet-stream")}
    _expect(await client.post(f"/api/v1/content/{PREFIX}-pypi/upload", files=wheel), 201)
    await _push_image(client, f"{PREFIX}-docker")
    targets = [
        ("raw file", f"/repository/{PREFIX}-raw/a/file.txt", {}),
        ("maven metadata", f"/repository/{PREFIX}-maven/{MAVEN_METADATA}", {}),
        ("npm document", f"/repository/{PREFIX}-npm/{PACKAGE}", {}),
        ("pypi page", f"/repository/{PREFIX}-pypi/simple/{PACKAGE}/", {}),
        ("docker manifest", f"/v2/{PREFIX}-docker/app/manifests/1.0", {"Accept": OCI_MANIFEST}),
    ]
    if inside_url:
        proxy = {
            "name": f"{PREFIX}-maven-proxy",
            "format": "maven",
            "type": "proxy",
            "proxy": {
                "remote_url": f"{inside_url.rstrip('/')}/repository/{PREFIX}-maven",
                "remote_auth": {"type": "bearer", "secret": token},
            },
        }
        _expect(await client.post("/api/v1/repositories", json=proxy), 201)
        path = f"/repository/{PREFIX}-maven-proxy/{MAVEN_METADATA}"
        _expect(await client.get(path), 200)  # fetched once: from now on it is the cache's
        targets.append(("maven metadata, proxy", path, {}))
    return targets


async def clean_up(client: httpx.AsyncClient) -> None:
    listed = _expect(await client.get("/api/v1/repositories", params={"limit": 200}), 200)
    ours = [item for item in listed.json()["items"] if item["name"].startswith(f"{PREFIX}-")]
    # A proxy before what it is a proxy of: nothing else here depends on anything.
    for repository in sorted(ours, key=lambda item: item["type"] != "proxy"):
        _expect(await client.delete(f"/api/v1/repositories/{repository['name']}"), 204, 404)


async def run(arguments: argparse.Namespace) -> int:
    basic = base64.b64encode(f"__token__:{arguments.token}".encode()).decode()
    credential = {"Authorization": f"Basic {basic}"}
    asked_at = (arguments.inside_url or arguments.url).rstrip("/")
    how = {"clients": arguments.clients, "network": arguments.network}
    async with httpx.AsyncClient(
        base_url=arguments.url.rstrip("/"), headers=credential, timeout=60.0
    ) as client:
        await clean_up(client)  # of a run that was stopped
        failed = 0
        try:
            targets = await set_up(client, arguments.inside_url, arguments.token)
            print(
                f"{arguments.clients} clients at once, {arguments.requests} requests each, "
                f"of {asked_at}"
            )
            print(HEADING)
            for name, path, headers in targets:
                headers = {**credential, **headers}
                # Once before the clock runs: the connections' first requests are the slow ones.
                measure(name, asked_at + path, requests=1, headers=headers, **how)
                measured = measure(
                    name, asked_at + path, requests=arguments.requests, headers=headers, **how
                )
                print(measured.line())
                failed += measured.failed
        finally:
            if not arguments.keep:
                await clean_up(client)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="the installation, as this machine reaches it")
    parser.add_argument("--token", required=True, help="an API token of an administrator")
    parser.add_argument("--clients", type=int, default=100, help="how many ask at once (100)")
    parser.add_argument("--requests", type=int, default=20, help="how often each asks (20)")
    parser.add_argument("--network", default="host", help="the Docker network of the generator")
    parser.add_argument("--inside-url", help="the installation, as containers on it reach it")
    parser.add_argument("--keep", action="store_true", help="leave the repositories it made")
    return parser


if __name__ == "__main__":
    sys.exit(asyncio.run(run(build_parser().parse_args())))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (in `backend/`): `uv run pytest tests/test_latency_script.py -q`
Expected: 4 passed, 1 deselected.

Run (in `backend/`): `uv run pytest -m docker tests/test_latency_script.py -q`
Expected: 1 passed. Against the tests' stack, five clients at once: a line for each of the six things asked for, none failed, and no repository named `latency-` left.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/latency.py backend/tests/test_latency_script.py
git commit -m "feat: a script that measures how long answers take with many clients at once"
```

---

### Task 6: The scans, the measurement and the documents

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-13-release-readiness-design.md`

**Interfaces:**
- Consumes: everything Tasks 1 to 5 made.
- Produces: the README's sections on the quick start with `.env`, backup and restore, the licence, and what development runs; the spec's "Settled while building plan 11b" (L9 to L18).

- [ ] **Step 1: Look for known vulnerabilities in what is depended on**

```bash
cd backend
uv export --frozen --no-emit-project --output-file requirements.txt
uvx pip-audit --requirement requirements.txt --disable-pip
cd ../frontend
pnpm audit --prod
pnpm audit
```

Expected: `No known vulnerabilities found` for the backend (what runs and what development uses) and for what the frontend's image has. `pnpm audit` names one advisory, in `braces` under `eslint-config-next`, which has no patched version and is not in the image. Anything else is new since this plan was written: say so in the spec's row L17, and mend what can be mended. (`backend/requirements.txt` is not kept: Git does not see it.)

- [ ] **Step 2: Measure**

With the stack of the repository running (`docker compose up --build --detach --wait`) and an API token of an administrator:

Run (in `backend/`): `uv run python scripts/latency.py --url http://localhost:8000 --token <token> --network megooarti_default --inside-url http://gateway`
Expected: a table of six lines with nothing failed. The numbers are of the machine: on the one this plan was written on they were about 500 ms at the median and 2 to 3 s at the 95th percentile, 105 to 140 answers a second. If they are of another order, say so in the spec's row L16.

- [ ] **Step 3: The documents**

Change `README.md`:

````diff
@@ -11,10 +11,15 @@ repositories and the Docker registry, and a web UI (Next.js) that uses that API.
 Requires Docker with Compose.
 
 ```bash
+cp .env.example .env          # then set MEGOOARTI_DB_PASSWORD in it
 docker compose up --build --detach --wait
 curl http://localhost:8000/api/v1/status/ready
 ```
 
+Nothing starts until the database has a password of your choosing: `.env.example`
+says what else an installation may choose. `docker compose build` makes the images
+`megooarti/backend` and `megooarti/frontend`, tagged with the version.
+
 The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
 The web UI is at <http://localhost:8000>, and interactive API documentation at
 <http://localhost:8000/api/docs>. [First sign-in](#first-sign-in) says how to get in.
@@ -31,6 +36,7 @@ All configuration is by environment variable.
 | Variable | Default | Purpose |
 | --- | --- | --- |
 | `MEGOOARTI_DATABASE_URL` | required | PostgreSQL URL, for example `postgresql://user:password@host:5432/dbname` |
+| `MEGOOARTI_DATABASE_PASSWORD` | unset | The password of that URL, when it is kept apart from it. Any characters: in a URL, `@`, `/`, `#`, `?` and `%` would have to be escaped. It goes before a password in the URL |
 | `MEGOOARTI_RUN_MIGRATIONS` | `true` | When `true`, the container waits for the database and applies migrations before starting. Any other value skips both |
 | `MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS` | `60` | How long the container waits for the database before exiting with an error |
 | `MEGOOARTI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
@@ -49,7 +55,9 @@ All configuration is by environment variable.
 | `MEGOOARTI_SECRET_KEY` | generated | Key that seals stored secrets such as remote passwords; use a long random value. If unset or empty, a key is generated into `secret.key` in the data directory on first use |
 | `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` | `104857600` | Largest `npm publish` request accepted. A publish is read into memory, so this bounds what one costs |
 
-Docker Compose also reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
+Docker Compose reads `MEGOOARTI_DB_PASSWORD`, which it gives to the database and, as
+`MEGOOARTI_DATABASE_PASSWORD`, to the backend: nothing starts without it. It also
+reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
 `MEGOOARTI_DB_PORT` (default `5432`) to choose the ports published on the host. Set
 `MEGOOARTI_DB_PORT` if another PostgreSQL already uses 5432. The database port is
 published on `127.0.0.1` only. `MEGOOARTI_HTTP_PORT` is the gateway's: the backend and
@@ -190,6 +198,8 @@ curl -u admin -H 'Content-Type: application/json' -d '{
 - A path the remote does not have is remembered for `negative_cache.ttl_minutes`
   (default 1440), so the remote is not asked again for it.
 - A cached file is kept even if the remote later stops having it.
+- A connection to the remote that cannot be made is tried twice more, a moment
+  apart, before it counts as a failure: a network drops one now and then.
 - After a connection failure, or a `502`, `503`, `504` or `429` from the remote, it is
   left alone for a minute, doubling with each further failure up to an hour. Set
   `"blocked": true` to stop contacting it altogether, or `"auto_block": false` to turn
@@ -1011,6 +1021,40 @@ browser) pass through it. Towards the backend, your proxy must do what it does:
 Do not publish the backend's or the frontend's own port beside it: the session cookie
 and the content security policy assume one origin.
 
+## Backup and restore
+
+A backup is two files: the database, and the data directory, which holds the blob
+stores and the key that stored secrets are sealed with.
+
+```bash
+sh scripts/backup.sh /path/to/backup
+```
+
+Run it beside `docker-compose.yml`. Nothing is stopped. The database is dumped first
+and the files are copied after: a file is on the disk before the database names it,
+and stays for a day after nothing names it, so a copy made after the dump has every
+file the dump names. It writes `database.dump`, `data.tar` and `VERSION` into the
+directory, and names any blob store whose directory is outside the data directory:
+those files are not in the backup, and are yours to copy.
+
+To restore, into an installation that has nothing in it yet (a new machine, or after
+`docker compose down --volumes`, which destroys what is there):
+
+```bash
+cp .env.example .env          # then set MEGOOARTI_DB_PASSWORD: this installation's own
+sh scripts/restore.sh /path/to/backup
+```
+
+It refuses a database or a data directory that is not empty. Users, sessions, API
+tokens, repositories and their content are then as they were when the backup was
+made, and what was stored after it is gone. A backup of an older version is brought
+up to this one when the backend starts.
+
+Without the key (`secret.key` in the data directory, or `MEGOOARTI_SECRET_KEY` if you
+set one) a proxy's stored password cannot be read and must be entered again. Nothing
+else depends on it. If you set `MEGOOARTI_SECRET_KEY`, keep it with the backup: it is
+not in it.
+
 ## Health endpoints
 
 | Endpoint | Meaning |
@@ -1085,6 +1129,7 @@ Rules for migrations:
 Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Docker.
 
 ```bash
+cp .env.example .env          # with MEGOOARTI_DB_PASSWORD=megooarti: the tests expect it
 docker compose up --detach --wait db
 cd backend
 cp .env.example .env
@@ -1100,8 +1145,29 @@ Tests create and use the databases `megooarti_test` and `megooarti_test_migratio
 Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server.
 
 A test whose setup fails leaves what it said in `backend/.test-failures/`, one file
-for each, and the end of the run says so. The newest fifty are kept; Git does not see
-the folder.
+for each, and the end of the run says so. A test of the running stack that fails
+leaves the stack's logs there too. The newest fifty are kept; Git does not see the
+folder.
+
+The tests marked `docker` run the clients themselves against a stack built from the
+working tree: Maven, Gradle and sbt; npm, pnpm and yarn; pip, uv, poetry and twine;
+docker; a browser; and the backup and restore scripts. Their images are tagged
+`test`, and their stack has a project name and ports of its own.
+
+**Known vulnerabilities** in what is depended on are looked for with:
+
+```bash
+cd backend
+uv export --frozen --no-emit-project --output-file requirements.txt
+uvx pip-audit --requirement requirements.txt --disable-pip
+cd ../frontend
+pnpm audit --prod             # what the image has
+pnpm audit                    # and what development uses
+```
+
+**How long answers take** with many clients at once is measured by
+`backend/scripts/latency.py`, against a running installation, with a load generator
+it runs in a container. Its first lines say how.
 
 ### The web UI
 
@@ -1149,3 +1215,9 @@ at port 3000, without an API beside it.
 - **Next.js 16 is not the Next.js of earlier years.** Its documentation is in
   `frontend/node_modules/next/dist/docs/`; read the page for what you are about to
   change. `frontend/AGENTS.md` says the same to coding agents.
+
+## Licence
+
+MIT: see [LICENSE](LICENSE). Swagger UI, which draws the API's documentation page, is
+another project's and Apache-2.0: its files are in
+`backend/src/megooarti/static/swagger-ui/`, with its licence beside them.
````

Change `docs/superpowers/specs/2026-10-13-release-readiness-design.md`:

```diff
@@ -127,6 +127,21 @@ The API's version does not change: nothing that worked for a client that did wha
 | L7 | The real-client tests' proxies of public registries are not left alone after one failure (`auto_block` off), so one slow answer from the internet does not fail everything that follows it. | A test failed that way on `main`: the proxy stopped asking, and the group then answered 404 for what it had not cached. |
 | L8 | The commands that scan the dependencies of the backend and of the frontend for known vulnerabilities are written down, run once, and what they find is dealt with or recorded. | NFR-10, without CI (D2). |
 
+### Settled while building plan 11b
+
+| # | What | Why |
+| --- | --- | --- |
+| L9 | The copyright line of `LICENSE` names "The MegooArti Authors". | Whose name stands there is the owner's to say; this names nobody wrongly. |
+| L10 | The tests' stack has a password and an image tag (`test`) of its own, given in the environment, which goes before a `.env` file. | The images are now named for everybody: a stack of tests that built `megooarti/backend:0.1.0` would have replaced the one an installation on the same machine runs. |
+| L11 | Backup and restore are two scripts, `scripts/backup.sh` and `scripts/restore.sh`, and the test runs those. The database is dumped before the files are copied. Restore refuses an installation that is not empty. The backup names the blob stores it cannot have, those whose directory is outside the data directory. | A procedure that is a script is the same every time, and is what the test runs. The order is what makes the two halves fit while the installation runs: a file is written before the database names it, and kept for a day after. |
+| L12 | A connection to a remote that could not be made is tried twice more (after 0.2 s and 1 s) before it is a failure. A connection that timed out, and a request that was sent, are not tried again. | The logs L7 keeps showed what failed the client tests now and then: `ConnectError` from the backend's container to Maven Central, on a request whose neighbours succeeded. Behind a group that one dropped connection was "not there" to the client, which does not ask twice. |
+| L13 | L7's logs are kept by the same hook that keeps a failed setup: of a test marked `docker` that fails, what the backend and the gateway said. They hold the first-start administrator's password of the tests' own stack, which is removed with it. | The stack is gone when its module ends, and it was the only place that said why. |
+| L14 | sbt publishes a snapshot under one name (`sbt-library-4.1-SNAPSHOT.jar`), not Maven's dated ones, and the repository takes it. Gradle publishes a file of its own beside the POM (`.module`) and SHA-256 and SHA-512 checksums, and reads them back. Both went through without a change to the Maven format. | L5. Found by running them. |
+| L15 | The latency script runs a load generator (`oha` 1.16.0) in a container to do the asking. | Written in Python first, it could ask about 170 times a second and measured itself: it said 3 s where the generator, on the same stack, says 0.56 s. |
+| L16 | NFR-4 is not met. On a laptop (Intel i7-1165G7, 4 cores and 8 threads, Docker Desktop on Windows with 8 CPUs and 11.5 GiB), with 100 clients at once and a token, a request for cached metadata is answered in about 0.5 s at the median and 2 to 3 s at the 95th percentile, 105 to 140 a second, where NFR-4 asks 200 ms. An address that needs neither the database nor a caller's name is answered 2,100 times a second through the gateway. The backend is one process and uses one core, which is full; finding who is calling is several questions to the database for every request. | L6 measures; it does not mend. What would: more than one process, and not asking again within a few seconds who a token belongs to. Both are decisions (section 8). |
+| L17 | The dependency scan found nothing in what the backend depends on, nothing in what the frontend's image has, and one advisory in what the frontend's development uses: `braces` (GHSA-vfj7-8cjw-p6xm), under `eslint-config-next`, with no patched version. It is not in the image, and takes patterns from this repository only. | L8. |
+| L18 | The backend takes the database's password apart from its address (`MEGOOARTI_DATABASE_PASSWORD`), and Compose gives it that way. The tests' stack has a password with `@`, `/`, `#`, `?`, `%`, `&` and `$` in it. | In the address, a password that a password manager made would be read as a host or a path, and the first start would fail with words about neither. |
+
 ## 6. Documents (plan 11c)
 
 `README.md` becomes: what MegooArti is, a quick start that ends at a signed-in administrator, and a map of the guides. The rest of what it holds today moves, reorganised and checked against the product as it is.
@@ -154,6 +169,8 @@ It stays as it is. A group answers for several repositories, and a build that na
 
 ## 8. Known and left
 
+**How long answers take** (L16): NFR-4 is a "Should" and is missed by an order of magnitude. Running several processes of the backend, and remembering for a few seconds who a token belongs to, are the two changes that would bring it near; the first needs the backend proven with more than one process, the second delays a revoked token by as long as it is remembered.
+
 **Asking again for the present password** before a credential is made or changed (another user's password, a new user, an API token): today an open session of an administrator is enough for each (H19).
 
 From the reviews of plans 10a to 10c, none of which stops a release: page titles that could say more; lists of choices capped where a later page exists; a refusal's text staying after its field is edited; the generated password not announced; a proxy secret's hint that is untrue once the kind of sign-in changes; a proxy's failure state cleared by a save without a word; a notification that covers the buttons under it for some seconds; names that break every few characters at phone width; the settings form's missing heading; `repository-settings.tsx` to be split; the browser tests' complaint filter letting `409` through.
```

- [ ] **Step 4: Everything, once more**

Run (in `backend/`): `uv run ruff check . && uv run pytest -q`
Expected: no finding, and 2860 passed, 1 skipped.

Run (in `frontend/`): `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
Expected: no finding, 785 passed in 26 files, `Compiled successfully`. Nothing of the frontend changed but the licence's name in `package.json` and the labels of its image.

Run (in `backend/`): `uv run pytest -m docker -q`
Expected: 43 passed, in about thirteen minutes.

- [ ] **Step 5: Commit**

```bash
git add README.md docs
git commit -m "docs: installing with a password of one's own, backup and restore, and what plan 11b measured and settled"
```
