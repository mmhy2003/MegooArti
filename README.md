# MegooArti

An open-source repository and artifact proxy and manager. See the
[business requirements](docs/BRD.md) for scope and roadmap.

This repository currently contains the backend foundation: a FastAPI service with
health endpoints, structured logging and automatic database migrations. Package
formats, security and the web UI arrive in later milestones.

## Quick start

Requires Docker with Compose.

```bash
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
Interactive API documentation is at <http://localhost:8000/api/docs>.

## Configuration

All configuration is by environment variable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_DATABASE_URL` | required | PostgreSQL URL, for example `postgresql://user:password@host:5432/dbname` |
| `MEGOOARTI_RUN_MIGRATIONS` | `true` | When `true`, the container waits for the database and applies migrations before starting. Any other value skips both |
| `MEGOOARTI_DB_WAIT_TIMEOUT_SECONDS` | `60` | How long the container waits for the database before exiting with an error |
| `MEGOOARTI_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` |
| `MEGOOARTI_HOST` | `0.0.0.0` | Address the HTTP server binds to |
| `MEGOOARTI_PORT` | `8000` | Port the HTTP server listens on |
| `MEGOOARTI_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Comma-separated reverse-proxy addresses whose `X-Forwarded-*` headers are trusted |
| `MEGOOARTI_SHUTDOWN_GRACE_SECONDS` | `30` | How long in-flight requests may finish after a shutdown signal |
| `MEGOOARTI_DATA_DIR` | `/var/lib/megooarti` | Directory for files MegooArti writes. Mount a volume here |
| `MEGOOARTI_SESSION_IDLE_SECONDS` | `3600` | A UI session ends after this long without a request |
| `MEGOOARTI_SESSION_ABSOLUTE_SECONDS` | `43200` | A UI session ends this long after sign-in, whatever the activity |
| `MEGOOARTI_SESSION_COOKIE_SECURE` | `true` | Set `false` only when serving plain HTTP on a host other than `localhost` |
| `MEGOOARTI_LOGIN_MAX_FAILURES` | `5` | Failed sign-ins allowed per username and per client address in one window |
| `MEGOOARTI_LOGIN_FAILURE_WINDOW_SECONDS` | `900` | Length of that window |
| `MEGOOARTI_COMPACTION_INTERVAL_SECONDS` | `3600` | How often unused blob content is removed; `0` disables it |
| `MEGOOARTI_BLOB_GRACE_SECONDS` | `86400` | How long content is kept after nothing uses it |
| `MEGOOARTI_SECRET_KEY` | generated | Key that seals stored secrets such as remote passwords. If unset, a key is generated into `secret.key` in the data directory on first use |

Docker Compose also reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
`MEGOOARTI_DB_PORT` (default `5432`) to choose the ports published on the host. Set
`MEGOOARTI_DB_PORT` if another PostgreSQL already uses 5432. The database port is
published on `127.0.0.1` only.

`MEGOOARTI_DATABASE_URL` accepts `postgres://`, `postgresql://` and libpq-style
`?sslmode=require` URLs as handed out by managed PostgreSQL services.

If you raise `MEGOOARTI_SHUTDOWN_GRACE_SECONDS`, raise `stop_grace_period` in
`docker-compose.yml` (or your orchestrator's equivalent) to a larger value as well;
otherwise the container is killed before in-flight requests finish.

## First sign-in

On first start MegooArti creates the `admin` account with a random password, writes it
to `admin.password` in the data directory, and logs it once:

```bash
docker compose exec backend cat /var/lib/megooarti/admin.password
```

Sign in with it; you must then choose a new password, after which the file is deleted.

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<the generated password>"}' \
  http://localhost:8000/api/v1/auth/login
```

The response contains a `csrf_token`. Requests that use the session cookie and change
anything must send it in an `X-CSRF-Token` header.

## Access control

- **Roles** hold permission patterns such as `admin:users:*` or
  `repository:maven:releases:read`. `*` matches one segment, and a pattern shorter than
  the permission grants everything beneath it, so `repository:maven` covers every Maven
  repository. Roles can contain other roles.
- **Personal API tokens** (`mga_…`) are created under `/api/v1/me/tokens` while signed
  in with a password. Use one as a bearer token, or as the password in HTTP Basic. A
  token can be limited to a list of patterns and can expire.
- **Anonymous access** is off by default. When turned on under `/api/v1/settings`,
  requests without credentials act as the built-in `anonymous` user; change what they
  may do by editing that user's roles.
- Five failed sign-ins for one username, or from one address, within 15 minutes block
  further attempts until the window ends. A valid API token is never refused by this
  limit. Behind a reverse proxy, set `MEGOOARTI_FORWARDED_ALLOW_IPS` to the proxy's
  address; otherwise every client appears to come from the proxy and shares one limit.
- Requests without credentials can only ever be allowed `repository:` permissions,
  whatever roles the `anonymous` user holds.

The full API is described at `/api/docs`.

## Repositories

A **blob store** is where file content is kept; the `default` one is a directory under
the data directory. A **repository** holds files in one format. So far there is one
format, `raw` (arbitrary files by path). A repository has one of three types: `hosted`
(files you publish), `proxy` (a cache of a remote repository) or `group` (several
repositories behind one URL).

Create a repository, then use it with any HTTP client:

```bash
curl -u admin -H 'Content-Type: application/json' \
  -d '{"name":"files","format":"raw","type":"hosted"}' \
  http://localhost:8000/api/v1/repositories

curl -u admin -T ./build/app.tar.gz http://localhost:8000/repository/files/releases/app.tar.gz
curl -u admin -O http://localhost:8000/repository/files/releases/app.tar.gz
```

In place of a password, use an API token as the password, or send it as
`Authorization: Bearer <token>`.

- **Permissions** are `repository:<format>:<name>:<action>`, where the action is `read`,
  `add` (a new path), `edit` (replace a path) or `delete`. For example
  `repository:raw:files:read`, or `repository:raw` for everything on every Raw repository.
- **Deployment policy** per repository: `allow_redeploy` (default), `disable_redeploy`
  (a path can be written once) or `read_only`.
- **Uploads are verified.** If the client sends `Content-Length`, or an
  `X-Checksum-Md5`, `X-Checksum-Sha1` or `X-Checksum-Sha256` header, the received bytes
  must match or nothing is stored. Downloads carry the same checksum headers.
- **Downloads** support `Range`, `If-None-Match` and `If-Modified-Since`.
- **Files always download**; they are never rendered in the browser, because they are
  served from the same site as the administration API.
- **Public content.** With anonymous access on, anyone, signed in or not, may do what
  the `anonymous` user's roles allow on repositories.
- **Identical content is stored once.** Deleting a file frees its content only after
  nothing has used it for `MEGOOARTI_BLOB_GRACE_SECONDS`.
- A repository's name, format, type and blob store cannot be changed after creation.
- Each blob store needs a directory of its own: one that overlaps another store's
  directory is refused.

### Proxy repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "upstream-files", "format": "raw", "type": "proxy",
  "proxy": {
    "remote_url": "https://files.example.org/releases",
    "remote_auth": {"type": "basic", "username": "robot", "secret": "the-password"}
  }
}' http://localhost:8000/api/v1/repositories
```

- A file that is not cached is downloaded from the remote completely, checked, stored
  and then served. Later requests are served from the cache.
- A cached file is checked against the remote again after `content_max_age_minutes`
  (default 1440; `-1` never). If the remote is down, the cached copy is served.
- A path the remote does not have is remembered for `negative_cache.ttl_minutes`
  (default 1440), so the remote is not asked again for it.
- After a connection failure, a `5xx` or a `429`, the remote is left alone for a minute,
  doubling with each consecutive failure up to an hour. Set `"blocked": true` to stop
  contacting it altogether, or `"auto_block": false` to turn automatic blocking off.
  `GET /api/v1/repositories/<name>` shows the current state under `status`.
- `POST /api/v1/repositories/<name>/invalidate-cache` makes the proxy check everything
  with the remote again.
- The remote secret is sealed before it is stored and is never returned; the API shows
  only `has_secret`. Leave `secret` out when updating to keep the stored one. It is sent
  only to the configured remote, and not to another host the remote redirects to.
- A proxy repository cannot be written to.

**Back up the key.** Secrets are sealed with `MEGOOARTI_SECRET_KEY`, or with the
generated `secret.key` in the data directory. Without that key the stored secrets cannot
be read and must be entered again.

### Group repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "all-files", "format": "raw", "type": "group",
  "group": {"members": ["files", "upstream-files"]}
}' http://localhost:8000/api/v1/repositories
```

- Members are tried in order and the first that has the path answers. Offline members,
  and proxies whose remote is unavailable, are passed over.
- Reading through a group needs `read` on the group only, not on its members.
- A group may contain other groups. It cannot be written to, and a repository cannot be
  deleted while a group presents it.

## Health endpoints

| Endpoint | Meaning |
| --- | --- |
| `GET /api/v1/status/live` | The process is running |
| `GET /api/v1/status/ready` | The database is reachable and its schema matches this version; `503` otherwise |

## Database migrations

The schema is managed only by [Alembic](https://alembic.sqlalchemy.org/). Migration
scripts are in `backend/src/megooarti/migrations/versions/`.

**In a deployment**, the container entrypoint waits for the database, runs
`alembic upgrade head`, and then starts the application. If a migration fails, the
container exits with an error and the application does not start. Several containers
may start at once; a database lock ensures only one applies migrations. To run
migrations as a separate deployment step instead, set `MEGOOARTI_RUN_MIGRATIONS=false`
on the application containers and run this once per release:

```bash
docker compose run --rm -e MEGOOARTI_RUN_MIGRATIONS=true backend true
```

The `-e` flag matters: without it the one-off container inherits
`MEGOOARTI_RUN_MIGRATIONS=false` from the service and skips the migration.

**In development**, use the helper script from `backend/`:

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

## Development

Requires Python 3.13, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
docker compose up --detach --wait db
cd backend
cp .env.example .env
uv sync
uv run pytest                 # unit and integration tests; needs the db service
uv run pytest -m docker       # builds the image and tests the entrypoint
uv run ruff check .
uv run ruff format --check .
uv run python -m megooarti    # serve on http://localhost:8000 using .env
```

Tests create and use the databases `megooarti_test` and `megooarti_test_migrations`.
Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server.
