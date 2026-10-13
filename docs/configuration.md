# Configuration

## The backend's environment

All configuration of a deployment is by environment variable.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_DATABASE_URL` | required | PostgreSQL URL, for example `postgresql://user:password@host:5432/dbname` |
| `MEGOOARTI_DATABASE_PASSWORD` | unset | The password of that URL, when it is kept apart from it. Any characters: in a URL, `@`, `/`, `#`, `?` and `%` would have to be escaped. It goes before a password in the URL |
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
| `MEGOOARTI_SECRET_KEY` | generated | Key that seals stored secrets such as remote passwords; use a long random value. If unset or empty, a key is generated into `secret.key` in the data directory on first use |
| `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` | `104857600` | Largest `npm publish` request accepted. A publish is read into memory, so this bounds what one costs |

Docker Compose reads `MEGOOARTI_DB_PASSWORD`, which it gives to the database and, as
`MEGOOARTI_DATABASE_PASSWORD`, to the backend: nothing starts without it. It also
reads `MEGOOARTI_HTTP_PORT` (default `8000`) and
`MEGOOARTI_DB_PORT` (default `5432`) to choose the ports published on the host. Set
`MEGOOARTI_DB_PORT` if another PostgreSQL already uses 5432. The database port is
published on `127.0.0.1` only. `MEGOOARTI_HTTP_PORT` is the gateway's: the backend and
the frontend are not published. Compose passes `MEGOOARTI_SESSION_COOKIE_SECURE` on to
the backend, and sets `MEGOOARTI_FORWARDED_ALLOW_IPS` to `*` there: requests from
outside reach it only through the gateway, which writes the client's address itself
and overwrites whatever a client says of its own.

The frontend container has no configuration. It reads `PORT` (default `3000`) and
`HOSTNAME` (default `0.0.0.0`), and nothing else: it holds no secret and never calls
the backend.

`MEGOOARTI_DATABASE_URL` accepts `postgres://`, `postgresql://` and libpq-style
`?sslmode=require` URLs as handed out by managed PostgreSQL services.

If you raise `MEGOOARTI_SHUTDOWN_GRACE_SECONDS`, raise `stop_grace_period` in
`docker-compose.yml` (or your orchestrator's equivalent) to a larger value as well;
otherwise the container is killed before in-flight requests finish.

## What Compose reads

`docker-compose.yml` takes these from the environment, or from a `.env` file beside
it. `.env.example` has each with what it is for.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_DB_PASSWORD` | required | The database's password. Given to the database when it is first made, and to the backend as `MEGOOARTI_DATABASE_PASSWORD` |
| `MEGOOARTI_HTTP_PORT` | `8000` | The port the gateway is published on |
| `MEGOOARTI_DB_PORT` | `5432` | The port the database is published on, on `127.0.0.1` only |
| `MEGOOARTI_SESSION_COOKIE_SECURE` | `true` | Passed on to the backend |
| `MEGOOARTI_SECRET_KEY` | unset | Passed on to the backend if it is set |
| `MEGOOARTI_VERSION` | this version | The tag the images are built and run under |

In `.env`, a value with a `$`, a `#` or a space in it is put in single quotes, and a
single quote in it is written `\'`.

## Settings kept in the database

Two settings are an administrator's and not a deployment's. They are changed in the
web UI or through the API, by whoever holds `admin:settings:write`, and take effect
at once.

| Setting | Where | What it is |
| --- | --- | --- |
| Base URL | System page; `PUT /api/v1/settings/base-url` | The address MegooArti gives out as its own: see [Installation](installation.md#the-base-url) |
| Anonymous access | Anonymous access page; `PUT /api/v1/settings/anonymous-access` | Whether requests without credentials act as the `anonymous` user: see [Administration](administration.md#access-control) |

`GET /api/v1/settings` shows both.
