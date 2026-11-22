# MA-10 plan: MegooColab's release strategy for MegooArti, published by GitHub Actions, with Caddy on port 80

## Goal

A push to `main` that carries a new version makes GitHub Actions test MegooArti, publish both images to GHCR (`X.Y.Z` and `latest`, amd64 and arm64) and create the GitHub release `vX.Y.Z` from `docs/releases/vX.Y.Z.md`. An installation pulls those images, and Caddy is its gateway, serving plain HTTP on port 80.

## Architecture

The gateway service keeps its name `gateway`, but it now runs `caddy:2` with `gateway/Caddyfile`. Nginx and `gateway/nginx.conf` go. `docker-compose.yml` pulls `ghcr.io/mmhy2003/megooarti-{backend,frontend}:${MEGOOARTI_VERSION:-latest}`. A new overlay, `docker-compose.build.yml`, builds those images from the checkout under the tag `dev`, for development and tests. The version lives in a top-level `VERSION` file. `tools/release/versions.py` is MegooColab's tool cut down to one product, and it decides what `.github/workflows/release.yml` releases. That workflow calls `.github/workflows/ci.yml` and runs a start-up check before it pushes anything.

## Conventions every step follows

- Backend tests run from `backend/` through the runner's `db` set: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest <files>'`. Lint: `cd backend && uv run ruff check . && uv run ruff format --check .`.
- Real-client tests: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest -m docker <files>'`. They need Docker and internet access, and they bring up their own stack on port 18000 (`backend/tests/containers.py`).
- Write in the repository's own style: short comments in full sentences that say *why*, and test names that read as sentences (`test_the_gateway_...`).
- Commit messages follow the history: `feat(gateway): …`, `test(...)`, `docs: …`, `ci: …`. End each with the attribution line the build harness gives.
- Never edit `docs/superpowers/`.

## File map

| File | Change | Responsibility |
| --- | --- | --- |
| `gateway/Caddyfile` | new (replaces `gateway/nginx.conf`, which is deleted) | One `:80` site, the routes, the forwarded headers, streaming and timeouts |
| `docker-compose.yml` | modify | `gateway` on `caddy:2` with port `${MEGOOARTI_HTTP_PORT:-80}:80`; `backend` and `frontend` pull `:${MEGOOARTI_VERSION:-latest}` and have no `build:` |
| `docker-compose.build.yml` | new | Overlay: build both images from the checkout, tagged `${MEGOOARTI_VERSION:-dev}` |
| `.env.example` | modify | `#MEGOOARTI_HTTP_PORT=80`, `#MEGOOARTI_VERSION=latest` |
| `.gitattributes` | modify | `Caddyfile text eol=lf` |
| `Makefile` | modify | `make up` uses the overlay |
| `megoocolab.toml` | modify | The `ui` set adds the overlay |
| `scripts/ui-e2e.sh` | modify | `stack()` adds the overlay |
| `backend/tests/containers.py` | modify | The tests' stack uses the overlay (`COMPOSE_FILE`) |
| `VERSION` | new | `0.1.0`, the source of the version |
| `tools/release/versions.py` | new | `check` and `plan` (§A) |
| `docs/releases/v0.1.0.md` | new | The first release note (replaces `CHANGELOG.md`, which is deleted) |
| `.github/workflows/ci.yml` | new | Fast checks on push, PR and `workflow_call` (§C) |
| `.github/workflows/release.yml` | new | plan → tests + app → images → publish (§D) |
| `docs/releasing.md` | new | The release routine |
| `AGENTS.md` | new | Short rules for agents |
| `backend/tests/test_compose.py` | modify | Compose, overlay and Caddyfile checks |
| `backend/tests/test_documents.py` | modify | Reverse-proxy table against the Caddyfile; release note; `docs/releasing.md` added to the guides |
| `backend/tests/test_release.py` | modify | `VERSION` equals the other three places; `.env.example` says `latest` |
| `backend/tests/test_release_tool.py` | new | The release tool, on a temporary git repository (§B) |
| `backend/tests/test_workflows.py` | new | The workflows' text |
| `README.md`, `docs/installation.md`, `docs/configuration.md`, `docs/upgrade.md`, `docs/development.md`, `docs/api.md`, `docs/adding-a-format.md`, `docs/repositories.md`, `docs/administration.md`, `docs/formats/*.md`, `frontend/playwright.config.ts`, `backend/scripts/latency.py` | modify | Caddy, port 80, pulled images, releases |

## §A `tools/release/versions.py` (whole file)

```python
"""MegooArti's release rules, for the release workflow and for whoever releases (docs/releasing.md).

    python tools/release/versions.py check     the version's four places agree
    python tools/release/versions.py plan      what needs releasing (key=value lines, for $GITHUB_OUTPUT)

One product: MegooArti, whose version is `VERSION`, kept equal to the backend's and the web UI's own. It is
released as two images and a GitHub release tagged vX.Y.Z.
"""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RELEASE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
TAG = "v"
VERSION_FILE = "VERSION"
# what MegooArti is made of: a change here since its last release needs a new version
PATHS = ["backend", "frontend", "gateway", "docker-compose.yml", ".env.example", "VERSION"]
# where else the version is written, and how it is read there
PLACES = {
    "backend/pyproject.toml": lambda text: tomllib.loads(text)["project"]["version"],
    "backend/src/megooarti/__init__.py": lambda text: re.search(
        r'^__version__ = "([^"]*)"$', text, flags=re.MULTILINE
    )[1],
    "frontend/package.json": lambda text: json.loads(text)["version"],
}


def parse(version: str) -> tuple[int, int, int] | None:
    """A release version is exactly X.Y.Z (a leading v allowed); anything else (dev, 0.1.0-dev+abc) is not one."""
    m = RELEASE.match(version.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def _read(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8").strip()


def check(root: Path) -> list[str]:
    errors = []
    version = _read(root, VERSION_FILE)
    for path, read in PLACES.items():
        said = read(_read(root, path))
        if said != version:
            errors.append(f"{path} says {said}, VERSION says {version}: they must be equal")
    if parse(version) is None:
        errors.append(f"VERSION holds {version!r}, not a release version (X.Y.Z)")
    return errors


def _last_tag(root: Path) -> str | None:
    tags = [t for t in _git(root, "tag", "--list", f"{TAG}*").split() if parse(t.removeprefix(TAG))]
    return max(tags, key=lambda t: parse(t.removeprefix(TAG)), default=None)


def guard(root: Path) -> list[str]:
    """What changed since the last release must carry a new version, and never a lower one (`latest` would
    move servers back to it)."""
    tag = _last_tag(root)
    if tag is None:
        return []
    version, released = _read(root, VERSION_FILE), tag.removeprefix(TAG)
    if (parse(version) or (0, 0, 0)) < parse(released):
        return [f"VERSION says {version}, lower than the last release {tag}"]
    if version != released:
        return []
    changed = _git(root, "diff", "--name-only", tag, "HEAD", "--", *PATHS).split()
    if changed:
        return [f"{', '.join(PATHS)} changed since {tag} but VERSION is still {released}: bump it (e.g. {changed[0]})"]
    return []


def note_path(version: str) -> str:
    return f"docs/releases/{TAG}{version}.md"


def plan(root: Path) -> dict[str, str]:
    """Whether the version still needs a release, and that version."""
    errors = check(root) + guard(root)
    version = _read(root, VERSION_FILE)
    needed = not _git(root, "tag", "--list", f"{TAG}{version}").strip()
    # added to git, not just on disk: the workflow sees only what was pushed
    if needed and not _git(root, "ls-files", "--", note_path(version)).strip():
        errors.append(f"{note_path(version)} is missing (or not added to git): every release needs its release note")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        raise SystemExit(1)
    return {"app": "true" if needed else "false", "app_version": version}


def main(argv: list[str]) -> int:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    match argv:
        case ["check"]:
            errors = check(root)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
            return 0
        case ["plan"]:
            print("\n".join(f"{k}={v}" for k, v in plan(root).items()))
            return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

(`tools/` is outside ruff's reach, because ruff runs in `backend/`. Still, keep each line within 120 characters, as written above.)

## §B `backend/tests/test_release_tool.py`: the harness and the cases

```python
"""The release tool (tools/release/versions.py), on a git repository of its own."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("versions", ROOT / "tools" / "release" / "versions.py")
versions = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(versions)


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    )


def write(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding="utf-8")


def set_version(repo: Path, version: str) -> None:
    write(repo, "VERSION", f"{version}\n")
    write(repo, "backend/pyproject.toml", f'[project]\nname = "megooarti"\nversion = "{version}"\n')
    write(repo, "backend/src/megooarti/__init__.py", f'"""MegooArti."""\n\n__version__ = "{version}"\n')
    write(repo, "frontend/package.json", json.dumps({"name": "megooarti-frontend", "version": version}))


def commit(repo: Path, message: str = "a change") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    set_version(tmp_path, "0.1.0")
    write(tmp_path, "gateway/Caddyfile", ":80 {\n}\n")
    write(tmp_path, "docs/releases/v0.1.0.md", "The first release.\n")
    commit(tmp_path, "first")
    return tmp_path
```

The cases, each a separate test:

- `test_a_release_version_is_exactly_three_numbers`: `parse("0.1.0") == (0, 1, 0)`, `parse("v1.2.3") == (1, 2, 3)`; `None` for `"dev"`, `"0.1.0-dev+abc"` and `"1.0"`.
- `test_versions_are_ordered_as_numbers`: `parse("0.10.0") > parse("0.9.0")`.
- `test_check_passes_when_the_four_places_agree`: `check(repo) == []`.
- `test_check_names_the_place_that_differs`, parametrized over the three `PLACES` keys: rewrite that one file with `0.2.0`. Exactly one error, which names the path.
- `test_check_refuses_a_version_that_is_not_a_release`: `set_version(repo, "dev")` gives an error containing `not a release version`.
- `test_before_the_first_release_there_is_nothing_to_guard`: `guard(repo) == []`.
- `test_a_change_since_the_last_release_needs_a_new_version`: tag `v0.1.0`, then write and commit `backend/app.py`. `guard` gives one error containing `backend/app.py` and `bump it`. After `set_version(repo, "0.1.1")` and a commit, `guard(repo) == []`.
- `test_the_compose_file_the_gateway_and_the_example_are_part_of_it`, parametrized over `docker-compose.yml`, `gateway/Caddyfile` and `.env.example`: after tag `v0.1.0`, a committed change to the file gives an error.
- `test_a_change_to_the_guides_needs_no_new_version`: tag `v0.1.0`, then commit `docs/installation.md`. `guard(repo) == []`.
- `test_a_version_lower_than_the_last_release_is_refused`: `git tag v0.2.0` while the files say `0.1.0`. The error contains `lower than the last release v0.2.0`.
- `test_plan_before_any_release_releases_this_version`: `plan(repo) == {"app": "true", "app_version": "0.1.0"}`.
- `test_plan_releases_nothing_for_a_version_already_tagged`: tag `v0.1.0`, and `plan(repo)["app"] == "false"`.
- `test_plan_fails_without_the_note`: `git rm` the note and commit. `pytest.raises(SystemExit)`, and `capsys` stderr contains `docs/releases/v0.1.0.md`.
- `test_plan_wants_the_note_known_to_git`: tag `v0.1.0`, `set_version(repo, "0.1.1")` and commit, then write `docs/releases/v0.1.1.md` without adding it. `plan` exits. After `git add` (staged, not committed), `plan(repo) == {"app": "true", "app_version": "0.1.1"}`.
- `test_the_command_prints_lines_for_github_output`: `monkeypatch.chdir(repo)`. `versions.main(["plan"]) == 0`, and stdout is `"app=true\napp_version=0.1.0\n"`. `versions.main(["guard"]) == 2`.

## §C `.github/workflows/ci.yml`

```yaml
name: CI

# The fast checks, on every push and pull request. The release workflow runs them too (workflow_call) before it
# publishes anything. The real-client suite (pytest -m docker) is run by hand before a release: docs/releasing.md.
on:
  push:
  pull_request:
  workflow_call:

permissions:
  contents: read

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      # what the tests expect by default (MEGOOARTI_TEST_DATABASE_URL in tests/conftest.py)
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_USER: megooarti
          POSTGRES_PASSWORD: megooarti
          POSTGRES_DB: megooarti
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U megooarti -d megooarti"
          --health-interval 2s --health-timeout 3s --health-retries 30
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --locked
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
      - run: python ../tools/release/versions.py check

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v7
      # pnpm in the version package.json names (packageManager)
      - uses: pnpm/action-setup@v4
        with:
          package_json_file: frontend/package.json
      - uses: actions/setup-node@v6
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml
      - run: pnpm install --frozen-lockfile
      - run: pnpm test
      - run: pnpm lint
      - run: pnpm typecheck
      - run: pnpm build
```

Before committing, confirm the current major version of `astral-sh/setup-uv`, `pnpm/action-setup` and `actions/setup-node`, for example with `git ls-remote --tags https://github.com/astral-sh/setup-uv | tail`. Use the newest major of each. The `actions/*` and `docker/*` versions in §D are the ones MegooColab runs today.

## §D `.github/workflows/release.yml`

```yaml
name: Release

# A push to main releases MegooArti when its version (VERSION) has no tag yet: both images on GHCR, as X.Y.Z and
# latest, for amd64 and arm64, and the GitHub release vX.Y.Z with its note from docs/releases/. A push with no new
# version releases nothing. docs/releasing.md has the routine.
on:
  push:
    branches: [main]

permissions:
  contents: write
  packages: write

concurrency:
  group: release
  cancel-in-progress: false

env:
  REGISTRY: ghcr.io/mmhy2003

jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      app: ${{ steps.plan.outputs.app }}
      app_version: ${{ steps.plan.outputs.app_version }}
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      # fails when the version's places disagree, a change was not given a new version, or the note is missing
      - id: plan
        run: python tools/release/versions.py plan >> "$GITHUB_OUTPUT"

  tests:
    needs: plan
    if: needs.plan.outputs.app == 'true'
    uses: ./.github/workflows/ci.yml

  # Builds and starts the images while the tests run. It publishes nothing: the images job below, which pushes,
  # waits for both.
  app:
    needs: plan
    if: needs.plan.outputs.app == 'true'
    runs-on: ubuntu-latest
    env:
      VERSION: ${{ needs.plan.outputs.app_version }}
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      # for this machine only, to start the stack from exactly these images before publishing them
      - name: Build for the start-up check
        uses: docker/build-push-action@v7
        with:
          context: backend
          platforms: linux/amd64
          load: true
          tags: ${{ env.REGISTRY }}/megooarti-backend:smoke
          build-args: VERSION=${{ env.VERSION }}
          cache-from: type=gha,scope=backend
          cache-to: type=gha,scope=backend,mode=max
      - uses: docker/build-push-action@v7
        with:
          context: frontend
          platforms: linux/amd64
          load: true
          tags: ${{ env.REGISTRY }}/megooarti-frontend:smoke
          build-args: VERSION=${{ env.VERSION }}
          cache-from: type=gha,scope=frontend
          cache-to: type=gha,scope=frontend,mode=max
      - name: Start the stack from the new images
        run: |
          cat > smoke.env <<EOF
          MEGOOARTI_VERSION=smoke
          MEGOOARTI_HTTP_PORT=8080
          MEGOOARTI_DB_PASSWORD=$(openssl rand -hex 16)
          EOF
          docker compose -p smoke -f docker-compose.yml --env-file smoke.env up --detach --wait --wait-timeout 300 --pull missing
          curl -fsS http://localhost:8080/api/v1/status/ready
          curl -fsS --output /dev/null http://localhost:8080/healthz
      - name: Stack logs (on failure)
        if: failure()
        run: docker compose -p smoke -f docker-compose.yml --env-file smoke.env logs --no-color
      - name: Stop the stack
        if: always()
        run: docker compose -p smoke -f docker-compose.yml --env-file smoke.env down --volumes

  # Each platform is built on a machine of its own architecture: under QEMU, MegooColab's arm64 Next.js build
  # crashed or hung. Each build is pushed by digest; publish tags them together.
  images:
    needs: [plan, tests, app]
    if: needs.plan.outputs.app == 'true'
    strategy:
      fail-fast: true
      matrix:
        include:
          - arch: amd64
            os: ubuntu-latest
          - arch: arm64
            os: ubuntu-24.04-arm
    runs-on: ${{ matrix.os }}
    env:
      VERSION: ${{ needs.plan.outputs.app_version }}
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push the backend (linux/${{ matrix.arch }})
        id: backend
        uses: docker/build-push-action@v7
        with:
          context: backend
          platforms: linux/${{ matrix.arch }}
          build-args: VERSION=${{ env.VERSION }}
          outputs: type=image,name=${{ env.REGISTRY }}/megooarti-backend,push-by-digest=true,name-canonical=true,push=true
          cache-from: type=gha,scope=backend-${{ matrix.arch }}
          cache-to: type=gha,scope=backend-${{ matrix.arch }},mode=max
      - name: Build and push the frontend (linux/${{ matrix.arch }})
        id: frontend
        uses: docker/build-push-action@v7
        with:
          context: frontend
          platforms: linux/${{ matrix.arch }}
          build-args: VERSION=${{ env.VERSION }}
          outputs: type=image,name=${{ env.REGISTRY }}/megooarti-frontend,push-by-digest=true,name-canonical=true,push=true
          cache-from: type=gha,scope=frontend-${{ matrix.arch }}
          cache-to: type=gha,scope=frontend-${{ matrix.arch }},mode=max
      - name: Keep the digests
        run: |
          mkdir -p digests
          echo "${{ steps.backend.outputs.digest }}" > digests/backend
          echo "${{ steps.frontend.outputs.digest }}" > digests/frontend
      - uses: actions/upload-artifact@v7
        with:
          name: digests-${{ matrix.arch }}
          path: digests/
          retention-days: 1

  publish:
    needs: [plan, images]
    if: needs.plan.outputs.app == 'true'
    runs-on: ubuntu-latest
    env:
      VERSION: ${{ needs.plan.outputs.app_version }}
    steps:
      - uses: actions/checkout@v7
      - uses: actions/download-artifact@v8
        with:
          pattern: digests-*
          path: digests
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Tag both platforms as one image
        run: |
          for image in backend frontend; do
            name="$REGISTRY/megooarti-$image"
            docker buildx imagetools create -t "$name:$VERSION" -t "$name:latest" \
              "$name@$(cat "digests/digests-amd64/$image")" "$name@$(cat "digests/digests-arm64/$image")"
            docker buildx imagetools inspect "$name:$VERSION"
          done
      - name: Publish the release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          # a re-run of a failed job finds the release already made
          gh release view "v$VERSION" > /dev/null 2>&1 || gh release create "v$VERSION" --target "$GITHUB_SHA" \
            --title "MegooArti $VERSION" --notes-file "docs/releases/v$VERSION.md"
```

The Dockerfiles already set `org.opencontainers.image.source` to `https://github.com/mmhy2003/MegooArti` (checked by `test_release.py`), so this workflow passes no `labels:`.

## §E `gateway/Caddyfile` (whole file; Caddy wants tabs)

```caddy
# The one address of a MegooArti installation, over plain HTTP on port 80.
#
# The API, the repositories, the registry, MCP and its OAuth go to the backend. Everything else is the web UI.
# TLS is your own reverse proxy's, in front of this or in its place: these are the rules to copy.
# docs/installation.md says what each is for.
{
	# Plain HTTP only: no certificate is asked for, and nothing listens on 443.
	auto_https off
	servers {
		# Every peer is trusted with X-Forwarded-For, so Caddy adds the address it sees at the right of what
		# came instead of replacing it. The backend reads it from the right, past the proxies an administrator
		# trusts (none, unless set): what a client wrote there itself is never believed.
		trusted_proxies static 0.0.0.0/0 ::/0
	}
}

# What both upstreams are sent, and how.
(upstream) {
	# Caddy's own scheme, never what the client says. Host goes on as the client sent it (Caddy's default).
	header_up X-Forwarded-Proto {scheme}
	# An answer goes to the client as the upstream produces it. A request body has no size limit and goes on
	# as it arrives: Caddy streams it by default.
	flush_interval -1
	# A proxy repository may wait this long for its remote.
	transport http {
		response_header_timeout 600s
		read_timeout 600s
		write_timeout 600s
	}
}

:80 {
	# No address is rewritten: the request's own path goes on exactly as it was sent. An npm scope is an
	# encoded slash and must stay one.
	@backend path /api/* /repository/* /v2/* /mcp* /.well-known/* /oauth/*
	reverse_proxy @backend backend:8000 {
		import upstream
	}
	reverse_proxy frontend:3000 {
		import upstream
	}
}
```

Caddy sorts a `reverse_proxy` that has no matcher after one that has a matcher, so everything that does not match `@backend` goes to the frontend.

## §F The reverse-proxy table test (replaces the nginx version in `test_documents.py`)

```python
def test_the_guide_sends_each_kind_of_address_where_the_gateway_sends_it():
    gateway = re.sub(r"#.*", "", read("gateway/Caddyfile"))
    matchers = {name: paths.split() for name, paths in re.findall(r"@(\w+) path (.+)", gateway)}
    routes = {}
    for matcher, host, port in re.findall(r"reverse_proxy (?:@(\w+) )?(\w+):(\d+)", gateway):
        for path in matchers[matcher] if matcher else ["everything else"]:
            routes[path.rstrip("*")] = f"{host}, port {port}"
    table = rows(read("docs/installation.md"), "## Behind your own reverse proxy")

    assert {row[0].strip("`"): row[1] for row in table} == routes
```

## Steps

### 1. Caddy replaces nginx as the gateway, on host port 80

**Files:** create `gateway/Caddyfile` (§E); delete `gateway/nginx.conf`; modify `docker-compose.yml` (`gateway` service only), `.env.example`, `.gitattributes`, `backend/tests/test_compose.py`, `backend/tests/test_documents.py`, `docs/installation.md`, `docs/configuration.md`, `docs/adding-a-format.md`, `docs/api.md` and `README.md` (the word "nginx" only).

**Tests first.** In `test_compose.py`:

- Replace `GATEWAY` with the Caddyfile's text, and add `CODE = re.sub(r"#.*", "", GATEWAY)`, which is the same text without comments.
- `test_only_the_gateway_is_published_to_the_network` expects `["${MEGOOARTI_HTTP_PORT:-80}:80"]`.
- New `test_the_gateway_is_caddy_with_its_file_and_nothing_kept`: `image == "caddy:2"`, `volumes == ["./gateway/Caddyfile:/etc/caddy/Caddyfile:ro"]`, `tmpfs == ["/data", "/config"]`, and no port mentions `443`.
- Rewrite the routes test: the `@backend path` list equals `["/api/*", "/repository/*", "/v2/*", "/mcp*", "/.well-known/*", "/oauth/*"]`, and `re.findall(r"reverse_proxy (?:(@\w+) )?([\w.-]+:\d+) \{", CODE) == [("@backend", "backend:8000"), ("", "frontend:3000")]`.
- `test_the_gateway_passes_a_path_on_exactly_as_it_was_sent`: no line of `CODE` starts, after its indentation, with `rewrite`, `uri`, `handle_path` or `strip_`.
- Parametrize `test_the_gateway_does_what_artifacts_and_package_clients_need` over `auto_https off`, `trusted_proxies static 0.0.0.0/0 ::/0`, `header_up X-Forwarded-Proto {scheme}`, `flush_interval -1`, `response_header_timeout 600s`, `read_timeout 600s` and `write_timeout 600s`, each one in `CODE`. Also check that `CODE.count("import upstream") == 2` and that `max_size`, `request_buffers` and `header_up Host` are not in `CODE`.
- Keep the `depends_on` and healthcheck tests unchanged.

In `test_documents.py`, replace the reverse-proxy table test with §F.

Run them and watch them fail: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_compose.py tests/test_documents.py'`.

**Implement.**

- The compose `gateway` service: `image: caddy:2`, ports `"${MEGOOARTI_HTTP_PORT:-80}:80"`, volume `./gateway/Caddyfile:/etc/caddy/Caddyfile:ro`, and `tmpfs: [/data, /config]` with the comment "Caddy keeps nothing here that matters: it asks for no certificate". Keep the same `depends_on` and the same `wget` healthcheck; `caddy:2` is Alpine and has wget. Update the comment above the service: plain HTTP on port 80, and TLS is your own proxy's.
- `.gitattributes`: add `Caddyfile text eol=lf`.
- `.env.example`: set the HTTP port to `#MEGOOARTI_HTTP_PORT=80`, with the comment "plain HTTP; choose another port where 80 is taken or under rootless Docker; with an address before it (`127.0.0.1:8080`) on that address only".
- `docs/configuration.md`: the default becomes `80` in the prose and in the "What Compose reads" table; the address example becomes `127.0.0.1:8080`.
- `docs/installation.md`:
  - "What runs" and "Before the first start": Caddy, port 80, and what to do when port 80 is taken or Docker is rootless.
  - "Behind your own reverse proxy": keep the table. Point at `gateway/Caddyfile`. The proxy address becomes `MEGOOARTI_HTTP_PORT=127.0.0.1:8080`. HTTPS from a proxy in front: remove the line `header_up X-Forwarded-Proto {scheme}` from `gateway/Caddyfile`, so that Caddy passes on what your proxy says (it trusts every peer), then run `docker compose up --detach --force-recreate gateway`; or set the base URL.
  - The "Either way" rules: say each one in Caddy's terms (no `rewrite`, `uri` or `handle_path`; `trusted_proxies`, without which Caddy replaces `X-Forwarded-For`; `flush_interval -1`; the transport timeouts of 600 s) and give nginx's equivalent in brackets.
- `docs/adding-a-format.md`: "add the path to the `@backend` matcher in `gateway/Caddyfile`".
- `docs/api.md` line 67: "with `502` or `504` and an empty body".
- `README.md`: "gateway (Caddy)".

Validate the Caddyfile:

```
docker run --rm -v "$PWD/gateway/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker run --rm -v "$PWD/gateway/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2 caddy fmt /etc/caddy/Caddyfile
```

The `fmt` output must equal the file.

**Pass:** the unit command above passes, ruff is clean, and the gateway's real-client tests pass through Caddy: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest -m docker tests/test_npm_client.py tests/test_docker_client.py tests/test_trusted_header.py tests/test_mcp_client.py tests/test_pypi_client.py'`. Together they cover the encoded npm scope, large uploads, Docker pushes, `X-Forwarded-For` and MCP. If one fails because of Caddy, fix the Caddyfile and do not weaken the test.

**Commit:** `feat(gateway): Caddy replaces nginx, plain HTTP on port 80`

### 2. The guides reach an installation at http://localhost

**Files:** `README.md`, `docs/installation.md`, `docs/upgrade.md`, `docs/development.md` (line 123 only), `docs/repositories.md`, `docs/administration.md`, `docs/formats/{apk,apt,docker,maven,npm,nuget,pypi,raw,yum}.md`, `frontend/playwright.config.ts`, `backend/scripts/latency.py`.

**What to change:**

- Every `http://localhost:8000` that means the installation becomes `http://localhost`, including `<http://localhost:8000>` and `/api/docs`.
- `playwright.config.ts`: change the default `baseURL` and the comment on line 10.
- `latency.py`: change the docstring example `--url http://localhost`. It has no default to change.

**Do not change:**

- `docs/development.md` line 32, `uv run python -m megooarti # serve on http://localhost:8000`, which is the backend itself.
- `backend/tests/test_container.py`, where 8000 is the container's port.
- Any `backend, port 8000` table cell.
- `docs/superpowers/`.

**Check:** `git grep -n 'localhost:8000' -- ':!docs/superpowers'` shows only `docs/development.md:32`.

**Test:** `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_documents.py tests/test_latency_script.py'` and `cd frontend && pnpm lint && pnpm typecheck`.

**Commit:** `docs: the guides reach an installation at http://localhost`

### 3. Compose pulls the published images; an overlay builds them as dev

**Files:** `docker-compose.yml`; new `docker-compose.build.yml`; `backend/tests/containers.py`, `Makefile`, `megoocolab.toml`, `scripts/ui-e2e.sh`, `.env.example`, `docs/configuration.md` (the `MEGOOARTI_VERSION` row); tests in `test_compose.py`, `test_documents.py`, `test_release.py` and `test_support.py`. `tools/test-services/ui.yml` stays as it is.

**Tests first.**

`test_compose.py`:

- `test_the_images_are_named_as_a_registry_would_hold_them`: `image == f"ghcr.io/mmhy2003/megooarti-{name}:${{MEGOOARTI_VERSION:-latest}}"`, and neither `build` nor `pull_policy` is in the service. Keep the source-label check.
- The frontend's keys are `{"image", "healthcheck"}`.
- New `test_the_build_overlay_builds_both_images_from_this_checkout_as_dev`: the overlay's services are `{"backend", "frontend"}`. Each has `image == "ghcr.io/mmhy2003/megooarti-<name>:${MEGOOARTI_VERSION:-dev}"` and `build == {"context": "./<name>", "args": {"VERSION": "${MEGOOARTI_VERSION:-dev}"}}`.
- New `test_the_tests_stack_is_built_from_this_checkout`: `ENVIRONMENT["COMPOSE_FILE"].split(os.pathsep)` equals the absolute paths of `docker-compose.yml` and `docker-compose.build.yml` at the repository root.

`test_documents.py`, in `test_everything_compose_reads_...`: `assert expected["MEGOOARTI_VERSION"] == "`latest`"`, and drop the "this version" substitution.

`test_release.py`: `"#MEGOOARTI_VERSION=latest\n" in example`.

Run them and watch them fail.

**Implement.**

- `docker-compose.yml`: drop `build:` from `backend` and `frontend`. Their images are `…:${MEGOOARTI_VERSION:-latest}`. Comment: these are the published images; `docker-compose.build.yml` builds them from the checkout instead.
- `docker-compose.build.yml`: a header comment that says what it is for and how it is used (`docker compose -f docker-compose.yml -f docker-compose.build.yml up --build --detach --wait`), and why it uses `dev` and never `latest`. Then the two services with `image` and `build` exactly as the test expects.
- `containers.py`: in `ENVIRONMENT`, `"COMPOSE_FILE": os.pathsep.join(str(REPOSITORY_ROOT / name) for name in ("docker-compose.yml", "docker-compose.build.yml"))`, with a comment that the scripts run by the tests see it too.
- `Makefile`: `up:` runs `docker compose -f docker-compose.yml -f docker-compose.build.yml up --build --detach --wait`, and its help line says "Build the images from this checkout and start the stack".
- `megoocolab.toml`: `compose = ["docker-compose.yml", "docker-compose.build.yml", "tools/test-services/ui.yml"]`.
- `scripts/ui-e2e.sh`: `-f docker-compose.yml -f docker-compose.build.yml -f tools/test-services/ui.yml`.
- `.env.example`: `#MEGOOARTI_VERSION=latest`, with "the tag of the images pulled and run: `latest` is the newest release; an exact version (`0.1.0`) pins one, and an upgrade is then changing it".
- `configuration.md`: the `MEGOOARTI_VERSION` row becomes `` `latest` `` and "The tag of the images pulled and run. The build overlay builds them as `dev` unless it is set".

Check both configurations with `MEGOOARTI_DB_PASSWORD=x docker compose config --quiet` and `MEGOOARTI_DB_PASSWORD=x docker compose -f docker-compose.yml -f docker-compose.build.yml config --quiet`.

**Pass:**

- The unit suite: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest'`.
- The whole real-client suite through Caddy: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest -m docker'`.
- The browser tests: `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh`.
- Ruff is clean.

**Commit:** `feat(compose): pull the published images; docker-compose.build.yml builds them as dev`

### 4. VERSION and the release tool

**Files:** new `VERSION` (`0.1.0` and a newline), new `tools/release/versions.py` (§A, exactly), new `backend/tests/test_release_tool.py` (§B), and `backend/tests/test_release.py`.

**Tests first:**

- §B in full.
- In `test_release.py`, add `test_the_version_file_says_the_version_first`: `(ROOT / "VERSION").read_text(encoding="utf-8").strip() == PROJECT["version"] == PACKAGE["version"] == __version__`.

Run `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_release_tool.py tests/test_release.py'` and watch it fail: the file to load is missing, and `VERSION` does not exist yet.

**Implement:** `VERSION` and `versions.py`.

**Pass:**

- The same command passes.
- `python tools/release/versions.py check` exits 0 and prints nothing.
- `python tools/release/versions.py plan` exits 1 and names `docs/releases/v0.1.0.md`; step 5 adds that note.
- Ruff is clean.

**Commit:** `feat(release): VERSION and tools/release/versions.py, MegooColab's release rules for one product`

### 5. The release note v0.1.0 replaces the changelog

**Files:** new `docs/releases/v0.1.0.md`; delete `CHANGELOG.md`; modify `backend/tests/test_documents.py`, `README.md` and `docs/upgrade.md`.

**Tests first (`test_documents.py`):**

- `DOCUMENTS = ["README.md", *GUIDES]`.
- `NOTES = sorted(p.relative_to(ROOT).as_posix() for p in (DOCS / "releases").glob("v*.md"))`.
- The variable, API-address, method-and-query and error-code tests iterate `[*DOCUMENTS, *NOTES]`. They checked the changelog before, so a note keeps that check.
- Replace `test_the_changelog_begins_with_this_version` with `test_this_version_has_its_release_note`:
  - `docs/releases/v{__version__}.md` exists;
  - it does not start with `#`, because the release title is GitHub's;
  - its `## ` headings start with `New` and end with `Upgrading`, and include `For callers of the API` and `Known issues`;
  - it holds no relative link (`](` followed by anything other than `scheme:`), because it is also the text of the GitHub release, where a link by path leads nowhere.

Watch them fail.

**Write the note:**

- An opening sentence: the first release of MegooArti, its images published for amd64 and arm64.
- `## New`: CHANGELOG's "What there is", brought up to date:
  - nine formats, as the README lists them, each with the clients its guide names;
  - signing in through LDAP and OIDC (see `docs/administration.md`);
  - images on GHCR, a Compose file that pulls them, and the Caddy gateway on port 80;
  - CI on every push.
- `## For callers of the API`: unchanged.
- `## Known issues`: unchanged, except "Not in this version". Check each item there against the format guides and drop what is no longer true: LDAP and OIDC exist now.
- `## Upgrading`: the first release, so nothing to upgrade from. A new installation: `cp .env.example .env`, set `MEGOOARTI_DB_PASSWORD`, `docker compose pull`, `docker compose up --detach --wait`, then <http://localhost>. Link the installation guide with an absolute URL, `https://github.com/mmhy2003/MegooArti/blob/main/docs/installation.md`.

Every link in the note is absolute.

**Fix the links:**

- `README.md`: the changelog link becomes "[release notes](docs/releases/)" and the GitHub releases page `https://github.com/mmhy2003/MegooArti/releases`.
- `docs/upgrade.md`: step 1 reads the version's [release note](releases/), and "the changelog of a version" becomes "a version's release note".

**Pass:**

- `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_documents.py tests/test_release_tool.py'`.
- `git add docs/releases` first, then `python tools/release/versions.py plan` prints `app=true` and `app_version=0.1.0`.
- `git grep -n CHANGELOG -- ':!docs/superpowers'` is empty.

**Commit:** `docs(release): docs/releases/v0.1.0.md replaces CHANGELOG.md`

### 6. CI on every push and pull request

**Files:** new `.github/workflows/ci.yml` (§C); new `backend/tests/test_workflows.py`.

**Tests first.** `test_workflows.py` has a module docstring that says the workflows run only on GitHub, so their text is checked here. It defines `WORKFLOWS = ROOT / ".github" / "workflows"` and a `workflow(name)` helper that `yaml.safe_load`s a file. PyYAML reads the key `on` as `True`, so the tests read `loaded[True]`, with a comment saying so. The tests:

- `test_ci_runs_on_pushes_pull_requests_and_for_the_release`: `set(ci[True]) == {"push", "pull_request", "workflow_call"}` and `ci["permissions"] == {"contents": "read"}`.
- `test_ci_runs_the_fast_suites_and_the_version_check`: the joined `run` lines of job `backend` contain `uv sync --locked`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` and `tools/release/versions.py check`, and none contains `-m docker`. Job `frontend` runs `pnpm install --frozen-lockfile`, `pnpm test`, `pnpm lint`, `pnpm typecheck` and `pnpm build`.
- `test_ci_gives_the_tests_the_database_they_expect`: the postgres service image is `postgres:17-alpine`, and its env is user, password and database `megooarti`.

Watch them fail.

**Implement:** §C, after confirming the action majors as §C says.

**Pass:**

- `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_workflows.py'`.
- `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest` reports nothing.
- Simulate the backend job locally: `megoocolab-runner services run db -- sh -c 'cd backend && uv sync --locked && uv run pytest'`. It shows that the suite needs only PostgreSQL.

**Commit:** `ci: backend and web UI checks on every push and pull request`

### 7. The release workflow publishes images and the GitHub release

**Files:** new `.github/workflows/release.yml` (§D); `backend/tests/test_workflows.py`.

**Tests first** (add to `test_workflows.py`):

- `test_only_a_push_to_main_releases_and_one_release_at_a_time`: `release[True] == {"push": {"branches": ["main"]}}`, `release["concurrency"] == {"group": "release", "cancel-in-progress": False}`, and the permissions are `contents: write` and `packages: write`.
- `test_the_release_runs_ci_and_the_start_up_check_before_pushing`: `jobs["tests"]["uses"] == "./.github/workflows/ci.yml"`; `set(jobs["images"]["needs"]) == {"plan", "tests", "app"}`; `jobs["publish"]["needs"]` includes `images`; and every job except `plan` has `if: needs.plan.outputs.app == 'true'`.
- `test_the_start_up_check_runs_the_images_just_built`: every line of release.yml that contains both `docker compose` and ` up ` also contains `--pull missing` and `-f docker-compose.yml`, and at least one such line exists.
- `test_a_rerun_finds_the_release_already_made`: `re.search(r'gh release view "v\$VERSION" > /dev/null 2>&1 \|\| gh release create "v\$VERSION"', text)`. The text also contains `--notes-file "docs/releases/v$VERSION.md"` and `--title "MegooArti $VERSION"`.
- `test_both_platforms_are_built_on_their_own_machines`: the `images` matrix `include` equals `[{"arch": "amd64", "os": "ubuntu-latest"}, {"arch": "arm64", "os": "ubuntu-24.04-arm"}]`, and the publish step tags `:$VERSION` and `:latest`.

Watch them fail.

**Implement:** §D exactly.

**arm64 check** (design: report it, do not drop arm64). From `backend/`, list the locked packages that have no Linux aarch64 wheel and no pure-Python wheel:

```
uv run python -c "import tomllib; lock = tomllib.load(open('uv.lock', 'rb')); print(sorted(p['name'] for p in lock['package'] if 'wheels' in p and not any(('aarch64' in w['url'] and 'linux' in w['url']) or w['url'].endswith('-none-any.whl') for w in p['wheels'])))"
```

If it prints any name other than `megooarti`, the arm64 backend build would need a compiler. Say so in the step's completion report, naming the packages, and leave arm64 in the matrix. Next, if QEMU is available (`docker run --privileged --rm tonistiigi/binfmt --install arm64`), build `docker buildx build --platform linux/arm64 backend` to confirm. Only the backend: the frontend is known to fail under QEMU.

**Pass:**

- `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_workflows.py'`.
- actionlint is clean.
- The start-up check works locally: build both images tagged `ghcr.io/mmhy2003/megooarti-{backend,frontend}:smoke`, run the "Start the stack" commands by hand, and see both `curl` calls succeed. Then `down --volumes`.

**Commit:** `ci: release workflow publishes both images to GHCR and the GitHub release`

### 8. docs/releasing.md and AGENTS.md

**Files:** new `docs/releasing.md`; new `AGENTS.md`; modify `backend/tests/test_documents.py` (`GUIDES` gains `"docs/releasing.md"`) and `README.md` (a Guides row: "[Releasing](docs/releasing.md) | The branches, version numbers and the release routine").

**Test first:** add the guide to `GUIDES`. The README map test and the link test fail until both files are written.

**`docs/releasing.md`**, starting with `# Releasing MegooArti`:

- `## Branches`: work happens on branches off `develop`, and PRs go into `develop`. `main` changes only at a release: every push to `main` runs the Release workflow.
- `## Version numbers`: `X.Y.Z` in `VERSION`, `backend/pyproject.toml`, `backend/src/megooarti/__init__.py` and `frontend/package.json`. A fix bumps the patch, a feature the minor, and the major goes up only when the owner asks. What counts as a change: `backend/`, `frontend/`, `gateway/`, `docker-compose.yml`, `.env.example` and `VERSION`. Docs alone need no new version.
- `## The routine`, as numbered commands:
  1. `git switch main && git pull && git merge --no-ff origin/develop`
  2. Set the version in the four places, then `cd backend && uv lock`, which brings `uv.lock` along. Then `MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py && cd ../frontend && pnpm gen:api`, because the API description carries the version.
  3. Write `docs/releases/vX.Y.Z.md`: an opening sentence, `## New`, `## Improved`, `## Fixed`, `## For callers of the API` and `## Known issues` where they apply, and `## Upgrading` last. Links are absolute.
  4. `git add VERSION backend/pyproject.toml backend/uv.lock backend/src/megooarti/__init__.py frontend/package.json frontend/openapi.json frontend/src docs/releases`
  5. Run the suites CI does not run: `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest -m docker'` and `megoocolab-runner services run ui -- sh scripts/ui-e2e.sh`.
  6. `python tools/release/versions.py check` and `python tools/release/versions.py plan`.
  7. `git commit -m "release: MegooArti X.Y.Z"` (not `commit -am`), then `git push origin main`, then `gh run watch`.
  8. `git switch develop && git merge main && git push origin develop`.
- `## What the workflow does (.github/workflows/release.yml)`: plan, tests, the start-up check, the native amd64 and arm64 builds pushed by digest, and publish (`X.Y.Z` and `latest`, and the release from the note). A re-run of a failed job finishes the release. What makes the plan job fail.
- `## Once, after the very first release`: make the two GHCR packages `megooarti-backend` and `megooarti-frontend` public (the package's settings, then "Change visibility"), or servers cannot pull them without signing in.

**`AGENTS.md`** (root, about 15 lines, starting with `# MegooArti for coding agents`): branch off `develop`; never change the version outside a release; push only when told "push"; release only when told "release"; see `docs/releasing.md` and `docs/development.md`; and the web UI's own rules are in `frontend/AGENTS.md`.

**Pass:** `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_documents.py'`; the README stays at 100 lines or fewer.

**Commit:** `docs: the release routine (docs/releasing.md) and AGENTS.md`

### 9. Guides for pulled images, the build overlay and CI

**Files:** `README.md`, `docs/installation.md`, `docs/upgrade.md`, `docs/development.md`.

**What to write:**

- **README Quick start:**

  ```
  cp .env.example .env
  docker compose pull
  docker compose up --detach --wait
  curl http://localhost/api/v1/status/ready
  ```

  Replace the paragraph about "nothing is published there yet" with one that says the images are pulled from GHCR, `latest` unless `MEGOOARTI_VERSION` pins a release, with a link to the releases page, and that building from the checkout is in Development. Keep `docker compose up` in the text, since a test looks for it, and stay within 100 lines.
- **`docs/installation.md`:**
  - The intro says the images are pulled from `ghcr.io/mmhy2003/megooarti-*`, and that the repository (or just `docker-compose.yml`, `gateway/Caddyfile` and `.env.example`) is what an installation runs from.
  - "Starting" uses `docker compose pull` and then `docker compose up --detach --wait`.
  - Move the Windows drive-letter build note to `docs/development.md`, since it concerns building.
  - Add a short "Choosing a version" paragraph: `MEGOOARTI_VERSION` pins a release.
- **`docs/upgrade.md`:** an upgrade pulls the new images and starts them on the same database and data directory. The steps:
  1. Read the note.
  2. Back up.
  3. Get the version's Compose file and Caddyfile (`git pull`, or `git checkout vX.Y.Z`); if `.env` pins `MEGOOARTI_VERSION`, change it.
  4. `docker compose pull && docker compose up --detach --wait`, then the `curl`.

  Replace the build-tag paragraph with pinning. "Going back" means starting the old pinned version after a restore.
- **`docs/development.md`:**
  - `make up` and its overlay command, which tags images `dev` and never replaces a pulled `latest`.
  - The Windows note.
  - A "Continuous integration" section: what `ci.yml` runs on every push and PR, and that the real-client suite is run by hand before a release.
  - "Releasing": a link to [docs/releasing.md](releasing.md).
  - The tests' images are tagged `test` and their stack uses the overlay.

**Pass:** `megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest tests/test_documents.py'`, and `git grep -n 'up --build' -- README.md docs/installation.md docs/upgrade.md` is empty.

**Commit:** `docs: installations pull the published images; development builds them; CI and releases`

## Final verification

```
megoocolab-runner services run db -- sh -c 'cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest'
megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest -m docker'
megoocolab-runner services run ui -- sh scripts/ui-e2e.sh
cd frontend && pnpm test && pnpm lint && pnpm typecheck && pnpm build
python tools/release/versions.py check && python tools/release/versions.py plan    # app=true, app_version=0.1.0
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest
MEGOOARTI_DB_PASSWORD=x docker compose config --quiet
git grep -n 'nginx\|localhost:8000\|CHANGELOG' -- ':!docs/superpowers'      # only docs/development.md:32 and the nginx equivalents in brackets in installation.md
```

The workflows first run for real on GitHub: CI on the first push of this branch, Release at the first release.

## Not build steps: the owner's, once (from the design)

1. Before this task's PR is merged, bring `develop` level with `main` (`git push origin origin/main:develop`) and change the PR's base to `develop`. Merged into `main`, the PR would publish 0.1.0 at once.
2. Point MegooArti's tasks at `develop` in MegooColab: `PATCH /api/projects/MA/repositories/{repo_id}` with `{"default_branch": "develop"}`.
3. After the first release, make the two GHCR packages public.
