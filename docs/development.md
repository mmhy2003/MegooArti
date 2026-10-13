# Development

## The backend

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env          # with MEGOOARTI_DB_PASSWORD=megooarti: the tests expect it
docker compose up --detach --wait db
cd backend
cp .env.example .env
uv sync
uv run pytest                 # unit and integration tests; needs the db service
uv run pytest -m docker       # builds the image; tests it with real clients (needs internet)
uv run ruff check .
uv run ruff format --check .
uv run python -m megooarti    # serve on http://localhost:8000 using .env
```

### Tests

Tests create and use the databases `megooarti_test` and `megooarti_test_migrations`.
Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server. The tests empty the
database they are given, and refuse one whose name does not end in `_test`.

A test whose setup fails leaves what it said in `backend/.test-failures/`, one file
for each, and the end of the run says so. A test of the running stack that fails
leaves the stack's logs there too. The newest fifty are kept; Git does not see the
folder.

The tests marked `docker` run the clients themselves against a stack built from the
working tree: Maven, Gradle and sbt; npm, pnpm and yarn; pip, uv, poetry and twine;
Docker and skopeo; a browser; and the backup and restore scripts. Their images are tagged
`test`, and their stack has a project name and ports of its own.

Name the test files of one directory together on a `pytest` command line: pytest
loses the fixtures of `tests/repositories` when a file from elsewhere is named
between two of its own.

**Known vulnerabilities** in what is depended on are looked for with:

```bash
cd backend
uv export --frozen --no-emit-project --output-file requirements.txt
uvx pip-audit --requirement requirements.txt --disable-pip
cd ../frontend
pnpm audit --prod             # what the image has
pnpm audit                    # and what development uses
```

As this is written, `pnpm audit` names one advisory: `braces` (GHSA-vfj7-8cjw-p6xm),
under `eslint-config-next`, which has no patched version. It is in what development
uses, takes patterns from this repository only, and is not in the image.

**How long answers take** with many clients at once is measured by
`backend/scripts/latency.py`, against a running installation, with a load generator
it runs in a container. Its first lines say how.

## Database migrations

The schema is managed only by [Alembic](https://alembic.sqlalchemy.org/). Migration
scripts are in `backend/src/megooarti/migrations/versions/`.

Use the helper script from `backend/`:

```bash
uv run python scripts/db.py new "add users table"   # create the next revision from the models
uv run python scripts/db.py upgrade                 # apply all migrations
uv run python scripts/db.py downgrade               # revert the last migration
uv run python scripts/db.py current                 # show the database's revision
uv run python scripts/db.py history                 # list every revision
uv run python scripts/db.py check                   # fail if models and migrations differ
```

Rules for migrations:

- The database must be at head before `new` will create a revision.
- Import every new model module in `backend/src/megooarti/models.py`, or `new` will not see it.
- Review the generated script; autogenerate does not detect every change.
- Every migration needs a working `downgrade()`.
- Never edit a migration that has been released. Add a new one.

What the entrypoint does with migrations in a deployment is in
[Upgrading](upgrade.md#what-happens-to-the-database).

## The web UI

Requires Node.js 22 and [pnpm](https://pnpm.io/).

```bash
cd frontend
pnpm install
pnpm test                     # unit and component tests
pnpm lint                     # ESLint and Prettier
pnpm typecheck
pnpm build
pnpm exec playwright install chromium   # once: the browser for the tests below
```

To work on a screen, start the stack (`docker compose up --build --detach --wait`),
which serves the built UI at <http://localhost:8000>. `pnpm dev` serves the UI alone
at port 3000, without an API beside it.

- **Tests in a real browser** are in `frontend/e2e/`. They are run by
  `uv run pytest -m docker` in `backend/`, which starts a fresh stack for them: they
  begin with the first sign-in of a new installation. They sign in, change the
  password, upload through the forms, browse, search and delete, go through
  signing in and through a repository's folders by keyboard alone, check where the
  keyboard is after a screen changed, check each screen against WCAG 2.1 AA in both
  modes, and fail if the browser asked anything of another host or reported a
  violation of the content security policy.
- **A unit test fails on a text that is missing** from `messages/en.json`: in the
  browser it would be shown as its own key.
- **A colour is written in one file**, `src/styles/tokens.css`, once for each mode. A
  test fails on a colour anywhere else, and another computes the contrast of every
  text tone on every surface.
- **Text is in `messages/en.json`.** ESLint refuses text written into markup, or into
  a property that is read out (`aria-label`, `title`, `alt`, `placeholder`, and the
  `label` and `hint` of the UI's own fields).
- **The API's types are generated.** `frontend/openapi.json` is a copy of the
  backend's API document, and a backend test fails when it is out of date. After a
  change to the API:

  ```bash
  cd backend && MEGOOARTI_UPDATE_OPENAPI=1 uv run pytest tests/test_openapi_snapshot.py
  cd ../frontend && pnpm gen:api
  ```

- **Next.js 16 is not the Next.js of earlier years.** Its documentation is in
  `frontend/node_modules/next/dist/docs/`; read the page for what you are about to
  change. `frontend/AGENTS.md` says the same to coding agents.

## The API's documentation page

`/api/docs` is drawn by Swagger UI, whose files are kept in
`backend/src/megooarti/static/swagger-ui/`, so that the page asks nothing of another
host. They are those of the npm package `swagger-ui-dist`, unchanged, with its
licence, its notice, and the version in `VERSION`. To replace them, unpack another
version of the package (`npm pack swagger-ui-dist@<version>`), copy the same six
files, and write the version to `VERSION`.

## A new format

[Adding a format](adding-a-format.md) says what a format is, and what is expected of
one.
