# Releasing MegooArti

A release is a push to `main` that carries a new version. GitHub Actions tests it,
publishes the two images to GHCR, `ghcr.io/mmhy2003/megooarti-backend` and
`ghcr.io/mmhy2003/megooarti-frontend`, as `X.Y.Z` and `latest`, for amd64 and arm64,
and makes the GitHub release `vX.Y.Z` with the version's note as its text.

## Branches

Work happens on branches off `develop`, and pull requests go into `develop`. `main`
changes only at a release: every push to `main` runs the Release workflow, which
refuses a push that changed MegooArti without giving it a new version.

## Version numbers

The version is `X.Y.Z`, written in four places that must say the same: `VERSION`,
`backend/pyproject.toml`, `backend/src/megooarti/__init__.py` and
`frontend/package.json`. A release of fixes only bumps the patch (`0.1.0` to `0.1.1`),
one with something new bumps the minor (`0.1.1` to `0.2.0`), and the major goes up only
when the project's owner asks for it.

What counts as a change to MegooArti is anything under `backend/`, `frontend/` and
`gateway/`, and `docker-compose.yml`, `.env.example` and `VERSION`. A change to the
guides alone needs no new version.

## The routine

1. Bring `develop` to `main`:

   ```bash
   git switch main && git pull && git merge --no-ff origin/develop
   ```

2. Set the new version in the four places, then let the lock file and the API's
   description follow, because the description carries the version:

   ```bash
   cd backend && uv lock
   MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py && cd ../frontend && pnpm gen:api
   cd ..
   ```

3. Write the note, `docs/releases/v<version>.md`. It opens with a sentence on what the
   release is, then has `## New`, `## Improved`, `## Fixed`, `## For callers of the API`
   and `## Known issues` where they apply, and `## Upgrading` last. It has no title,
   since the release's title is GitHub's, and its links are absolute
   (`https://github.com/mmhy2003/MegooArti/blob/main/...`), since a link by path leads
   nowhere on the release's page.
4. Add exactly what the release changes:

   ```bash
   git add VERSION backend/pyproject.toml backend/uv.lock backend/src/megooarti/__init__.py \
     frontend/package.json frontend/openapi.json frontend/src docs/releases
   ```

5. Run the suites that CI does not run: the real clients, and the web UI in a browser.

   ```bash
   megoocolab-runner services run db -- sh -c 'cd backend && uv run pytest -m docker'
   megoocolab-runner services run ui -- sh scripts/ui-e2e.sh
   ```

6. Ask the release tool what it sees: `check` says whether the four places agree, and
   `plan` what the workflow will release.

   ```bash
   python tools/release/versions.py check
   python tools/release/versions.py plan
   ```

7. Commit, not with `commit -am`, which would take whatever else is changed, then push
   and follow the workflow:

   ```bash
   git commit -m "release: MegooArti X.Y.Z"
   git push origin main
   gh run watch
   ```

8. Bring the release back to `develop`:

   ```bash
   git switch develop && git merge main && git push origin develop
   ```

## What the workflow does (.github/workflows/release.yml)

1. **plan** runs `python tools/release/versions.py plan`. When `VERSION` already has its
   tag, the push releases nothing and the other jobs are skipped.
2. **tests** runs the whole of CI (`.github/workflows/ci.yml`): the backend's tests
   without the `docker` mark, ruff and `versions.py check`, and the web UI's tests, lint,
   type check and build.
3. **app**, alongside the tests, builds both images, starts the stack from them with
   `docker-compose.yml`, and asks through the gateway whether the backend is ready and
   the web UI answers. It pushes nothing.
4. **images**, once both have passed, builds each image natively on an amd64 and on an
   arm64 machine, and pushes each build by its digest.
5. **publish** tags the two platforms' builds together as `X.Y.Z` and `latest`, then
   makes the GitHub release `vX.Y.Z` with the note as its text.

When a job fails, re-run the failed jobs: the publish job finds a release already made
and leaves it, so a re-run finishes the release rather than making a second.

The plan job fails, and nothing is built, when:

- the four places do not say the same version, or `VERSION` is not `X.Y.Z`;
- something that counts as a change was changed since the last release, but `VERSION`
  still says that release;
- `VERSION` is lower than the last release, which would move servers on `latest` back;
- the version's note is missing, or is on disk but was not added to git.

## Once, after the very first release

GHCR makes a new package private. In each package's settings on GitHub,
`megooarti-backend` and `megooarti-frontend`, choose "Change visibility" and make it
public, or servers cannot pull the images without signing in.
