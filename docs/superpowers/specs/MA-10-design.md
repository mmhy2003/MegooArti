# MA-10 design: MegooColab's release strategy for MegooArti, published by GitHub Actions, with Caddy on port 80

## Goal

A release of MegooArti is made the way MegooColab's is: work lands on `develop`, and a push to `main` with a new version makes GitHub Actions test it, publish the two images to GHCR (`X.Y.Z` and `latest`, amd64 and arm64) and create the GitHub release `vX.Y.Z` from its note. An installation then pulls the published images instead of building them, and its gateway is Caddy, serving plain HTTP on port 80.

## Decisions

| # | Decision | Why |
|---|---|---|
| 1 | **Caddy serves plain HTTP only, published on host port 80.** No 443, no site address, no certificates. `MEGOOARTI_HTTP_PORT` stays (default now `80`). | Your answer. TLS stays with the operator's own proxy, as the guides say today. Rejected: keeping 8000 as the default; MegooColab's optional automatic HTTPS. |
| 2 | **Work on `develop`; `main` changes only at a release.** | Your answer. The workflow runs on every push to `main`, and refuses a push that changed the product without a new version. Rejected: releasing from PRs into `main`; releasing on a pushed tag. |
| 3 | **The Compose files stay at the root.** `docker-compose.yml` pulls the published images; a new overlay `docker-compose.build.yml` builds from the checkout. | Your answer. Least change to guides, scripts and tests. Rejected: a `deploy/` folder as in MegooColab. |
| 4 | **Release notes are `docs/releases/vX.Y.Z.md`; `CHANGELOG.md` is removed.** | Your answer. One place to write, and the same tool as MegooColab. |
| 5 | **A release is gated by the same kind of checks as MegooColab's:** the fast suites (backend `pytest` without the `docker` mark, ruff, the web UI's tests, lint, type check and build) and a start-up check of the built images. The real-client suite (`pytest -m docker`) is not run by GitHub Actions; the routine says to run it by hand before a release. | "The same strategy": MegooColab's CI does not run its browser suite either. The real-client suite needs a dozen client toolchains and the internet, and takes long. |
| 6 | **A top-level `VERSION` file is the version's source**, as in MegooColab. `backend/pyproject.toml`, `backend/src/megooarti/__init__.py` and `frontend/package.json` must equal it. | Lets `versions.py` stay almost identical to MegooColab's. |
| 7 | **The gateway's service keeps the name `gateway`.** | The guides, the tests and `latency.py` name it; only what runs in it changes. |
| 8 | **A build from the checkout is tagged `dev`, never `latest`.** | A local build must not replace a pulled release image on the same machine (the reason the tests already use the tag `test`). |

## Architecture

### 1. Gateway: Caddy in place of nginx

- `gateway/Caddyfile` replaces `gateway/nginx.conf`. One site, `:80`, with `auto_https off`.
- Routes, unchanged: `/api/*`, `/repository/*`, `/v2/*`, `/mcp*`, `/.well-known/*`, `/oauth/*` go to `backend:8000`; everything else goes to `frontend:3000`.
- Behaviour kept from nginx, each stated in the Caddyfile and checked by a test:
  - **The path goes on exactly as sent** (an npm scope's `%2f` stays encoded): no `rewrite`, `uri` or `handle_path`.
  - **`X-Forwarded-For` is appended to, never replaced.** Caddy replaces it by default, so the Caddyfile trusts every peer for this header (`trusted_proxies` covering all addresses). The backend still decides whom to believe, reading from the right, as today.
  - **`X-Forwarded-Proto` is Caddy's own scheme** (`header_up X-Forwarded-Proto {scheme}`), so a client cannot claim HTTPS. `Host` passes through unchanged (Caddy's default).
  - **No size limit, and nothing buffered:** Caddy streams request bodies by default; responses are flushed at once (`flush_interval -1`).
  - **Ten-minute wait for the backend** (`response_header_timeout`, `read_timeout` and `write_timeout` of 600 s), as nginx had.
- Compose service `gateway`: image `caddy:2`, port `"${MEGOOARTI_HTTP_PORT:-80}:80"`, the Caddyfile mounted read-only, `/data` and `/config` as tmpfs (Caddy keeps nothing here that matters), the same `/healthz` health check and the same `depends_on`.

### 2. Compose: pull by default, build with an overlay

- `docker-compose.yml`: `backend` and `frontend` lose `build:`; their images are `ghcr.io/mmhy2003/megooarti-<name>:${MEGOOARTI_VERSION:-latest}`.
- `docker-compose.build.yml` (new): for `backend` and `frontend`, `image: …:${MEGOOARTI_VERSION:-dev}` and `build:` with `VERSION: ${MEGOOARTI_VERSION:-dev}`.
- Users of the overlay: `make up`, the tests' stack (`backend/tests/containers.py`), `megoocolab.toml` (`ui` set) and `scripts/ui-e2e.sh`. `tools/test-services/ui.yml` stays as it is.
- `.env.example`: `#MEGOOARTI_HTTP_PORT=80`, and `#MEGOOARTI_VERSION=latest` with a sentence on pinning a release.

### 3. Release tooling

- `VERSION` (new, `0.1.0`).
- `tools/release/versions.py`: MegooColab's file without the runner and Scoop parts. One product:
  - tag prefix `v`;
  - paths that count as a change: `backend`, `frontend`, `gateway`, `docker-compose.yml`, `.env.example`, `VERSION`;
  - `check`: the four version places agree and are `X.Y.Z`;
  - `plan`: `check`, plus the guard (a product changed since its last tag must have a higher version; never a lower one), plus the note `docs/releases/v<version>.md` must be in git. Prints `app=true|false` and `app_version=…` for `$GITHUB_OUTPUT`.
- `docs/releases/v0.1.0.md`: the text of `CHANGELOG.md`, brought up to date (images are published, there is CI, Caddy on port 80), in MegooColab's shape: an opening sentence, `## New`, then MegooArti's own `## For callers of the API` and `## Known issues`, and `## Upgrading` last.

### 4. GitHub Actions

`.github/workflows/ci.yml` (on `push`, `pull_request`, `workflow_call`; `contents: read`):

| Job | What it runs |
|---|---|
| `backend` | PostgreSQL 17 as a service; `uv sync --locked`; ruff check and format check; `uv run pytest`; `python tools/release/versions.py check` |
| `frontend` | Node 22 and pnpm; `pnpm install --frozen-lockfile`; `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm build` |

`.github/workflows/release.yml` (on push to `main`; `contents: write`, `packages: write`; concurrency group `release`, never cancelled), MegooColab's jobs without the runner:

| Job | Needs | What it does |
|---|---|---|
| `plan` | | `versions.py plan` with full history. A version that already has a tag releases nothing. |
| `tests` | `plan` | Calls `ci.yml`. |
| `app` | `plan` | Builds both images for amd64, tagged `smoke`; starts the stack from `docker-compose.yml` on port 8080 with `--pull missing`; asks `/api/v1/status/ready` and `/healthz` through Caddy; prints logs on failure; always removes the stack. |
| `images` | `plan`, `tests`, `app` | Builds each image natively on `ubuntu-latest` (amd64) and `ubuntu-24.04-arm` (arm64), with `VERSION` as build argument, pushed by digest. |
| `publish` | `plan`, `images` | Joins both digests as `X.Y.Z` and `latest`; `gh release create vX.Y.Z --target $GITHUB_SHA --title "MegooArti X.Y.Z" --notes-file docs/releases/vX.Y.Z.md`, skipped if the release exists (a re-run passes). |

### 5. Documents

- `docs/releasing.md` (new): Branches; Version numbers (fix → patch, feature → minor, major when the owner asks); The routine (merge `develop` into `main`, set the versions, write the note, run `pytest -m docker`, `versions.py check` and `plan`, commit `release: MegooArti X.Y.Z`, push, merge `main` back into `develop`); What the workflow does; Once, after the very first release.
- `AGENTS.md` (new, at the root, short): work on branches off `develop`; the version never changes outside a release; push only on "push", release only on "release"; see `docs/releasing.md`.
- Updated: `README.md` (quick start is `docker compose pull`, `up`, `http://localhost`; links to the releases), `docs/installation.md` (images are pulled; Caddy; the reverse-proxy section with Caddy's rules), `docs/configuration.md`, `docs/upgrade.md` (an upgrade is `docker compose pull && docker compose up --detach --wait`; pinning `MEGOOARTI_VERSION`), `docs/development.md` (the overlay, CI, releasing), and every guide that says `localhost:8000` or names `gateway/nginx.conf` (the format guides, repositories, administration, API, MCP, adding a format). `frontend/playwright.config.ts` and `latency.py` default to `http://localhost`.
- `docs/superpowers/` is history and is not changed.

## Data and interfaces

| Variable | Before | After |
|---|---|---|
| `MEGOOARTI_HTTP_PORT` | default `8000` | default `80` |
| `MEGOOARTI_VERSION` | default `0.1.0`, the tag built and run | default `latest`, the tag pulled and run (`dev` with the build overlay) |

Published: `ghcr.io/mmhy2003/megooarti-backend` and `-frontend`, tags `X.Y.Z` and `latest`; git tag and GitHub release `vX.Y.Z`. No API, database or UI change.

## Once, by the owner

1. **Before merging this task:** bring `develop` level with `main` (`git push origin origin/main:develop`; it is a fast-forward), then change this task's PR base to `develop` on GitHub. This task's branch was cut from `main` before the setting below changed, so its PR opens against `main`. Merged into `main`, it would publish 0.1.0 at once.
2. **Point MegooArti's tasks at `develop`:** `PATCH /api/projects/MA/repositories/{repo_id}` with `{"default_branch": "develop"}` in MegooColab (the UI has no edit control for an existing repository). Tasks already started keep `main`. GitHub's default branch stays `main`.
3. **After the first release:** make the two GHCR packages public (GitHub creates them private), or servers cannot pull without signing in.

## Error handling and edge cases

- **A push to `main` without a new version:** `plan` prints `app=false` and nothing else runs. If product paths changed since the last tag, `plan` fails and names a changed file.
- **A missing or untracked release note, version places that disagree, or a version lower than the last tag:** `plan` fails with the reason; nothing is built.
- **A failed job re-run:** images are pushed by digest and the release creation is guarded, so a re-run finishes the release.
- **arm64:** the backend image has no compiler. If a dependency has no arm64 wheel, the arm64 build fails. The build stage checks this before relying on it and reports it; it does not drop arm64 by itself.
- **Port 80 taken, or rootless Docker:** set `MEGOOARTI_HTTP_PORT` (the guides say so). The tests' stacks already use their own ports.
- **What Caddy itself refuses** (backend down): `502` with an empty body, where nginx sent an HTML page. `docs/api.md` is corrected.
- **Passing HTTPS on from a proxy in front:** today's guide edits one nginx line; the new one says which Caddyfile line to remove, or to set the base URL.

## Testing

- `backend/tests/test_compose.py`, rewritten for the new files: only `db` and `gateway` are published, the gateway on `${MEGOOARTI_HTTP_PORT:-80}:80`; the image names and the `latest` default; no `build:` in the main file; the overlay builds both and defaults to `dev`; the Caddyfile's routes, its header lines, its timeouts, and no rewriting directive.
- `backend/tests/test_documents.py`: the reverse-proxy table is held against the Caddyfile; `docs/releasing.md` joins the guides; the current version has its release note (in place of the changelog test).
- `backend/tests/test_release.py`: `VERSION` equals the other three places; `.env.example` says `latest`.
- New tests of the release tool, in MegooColab's cases, on a temporary git repository: version parsing and order; `check`; the guard (no tags, a change needs a bump, a docs-only change does not, a lower version is refused); `plan` (before any release, an already tagged version, a missing note, an untracked note, a staged note).
- New tests of the workflows' text: the start-up check uses `--pull missing`; `gh release create` is guarded by `gh release view`; `release.yml` calls `ci.yml`.
- The real-client suite (`uv run pytest -m docker`, and the browser tests through `megoocolab-runner services run ui`) is run in the build stage through Caddy. It already covers what the gateway must do: npm's encoded scope, large uploads, Docker pushes, the trusted header and `X-Forwarded-For`.
- The workflows cannot run before they are on GitHub: they are checked with actionlint and the text tests. Their first real run is the first release.

## Out of scope

- HTTPS in Caddy (certificates, port 443, a site address).
- Compression in the gateway, restart policies, and any other change to how the services run.
- Running the real-client or browser suites in GitHub Actions.
- An update notice in the web UI.
- Performing the first release: that happens when you say "release".
