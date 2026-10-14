# Administration

Everything here is done in the web UI, under Administration and under Account (your
name in the header), or through the API. [The web UI](web-ui.md) says what each
screen does; [The API](api.md) says how the API is called.

## Access control

Users, roles, your own API tokens and anonymous access are managed in the web UI
(Administration, and Account under your name) or through the API, as below.

- **Roles** hold permission patterns such as `admin:users:*` or
  `repository:maven:releases:read`. `*` matches one segment, and a pattern shorter than
  the permission grants everything beneath it, so `repository:maven` covers every Maven
  repository. Roles can contain other roles.
- **Personal API tokens** (`mga_…`) are created under `/api/v1/me/tokens` while signed
  in with a password. Use one as a bearer token, or as the password in HTTP Basic,
  with your user name or with the name `__token__`, which is how Python's tools send
  a token. A token can be limited to a list of patterns and can expire.
- **Anonymous access** is off by default. When turned on under `/api/v1/settings`,
  requests without credentials act as the built-in `anonymous` user. That user starts
  with the built-in `anonymous` role, which allows reading **every** repository. To
  make only some repositories public, replace that role on the `anonymous` user with
  one of your own.
- A request from a web page on another site that would change something is refused
  with `403 cross_site_request`, signing in included. If the server sits behind a
  reverse proxy on plain HTTP, set the base URL under `/api/v1/settings` so its own
  pages are recognised.
- **Your own password** is changed at `PUT /api/v1/me/password`, which asks for the
  present one. `PUT /api/v1/users/{id}/password` sets another user's, and refuses
  your own with `409 own_password`.
- Five failed sign-ins for one username, or from one address, within 15 minutes block
  further attempts until the window ends: for that name from anywhere, and for every
  name from that address. The answer is `429 too_many_attempts`, with a `Retry-After`
  header. A valid API token is never refused by this limit. Clients that reach
  MegooArti from one address share its limit, so a reverse proxy must say who they
  are: see [Installation](installation.md#behind-your-own-reverse-proxy).
- Requests without credentials can only ever be allowed `repository:` permissions,
  whatever roles the `anonymous` user holds.

The full API is described at `/api/docs`. The page is served with its own script and
stylesheet, and asks nothing of another host.

### What an administrator may be given

The built-in `admin` role holds `*`, which is everything. A role of your own can hold
a part of it. Each area below has `:read`, to see, and `:write`, to change; the
area's name alone gives both.

| Permission | What it allows |
| --- | --- |
| `admin:users` | The users: making, changing and deleting them, the roles they hold, and setting another user's password |
| `admin:roles` | The roles, and the permission patterns they hold |
| `admin:tokens` | Seeing which API tokens another user has, and revoking one. Nobody sees a token's value but its owner, once, when it is made |
| `admin:repositories` | Making, changing and deleting repositories, having a proxy check its remote again, rebuilding an index, and the keys repositories sign with |
| `admin:blobstores` | The blob stores |
| `admin:settings` | The base URL and anonymous access; to read, also what is running (`/api/v1/system/information`) |

What a repository holds is not given by these, but by `repository:` permissions:
see [Repositories](repositories.md). Whoever may change roles, or the roles a user
holds, can give out everything: give `admin:roles:write` and `admin:users:write` as
you would give `*`.

## What is running

| Endpoint | Meaning |
| --- | --- |
| `GET /api/v1/status/live` | The process is running |
| `GET /api/v1/status/ready` | The database is reachable and its schema matches this version; `503` otherwise |
| `GET /healthz` | The frontend is running (it answers `ok`) |

What is running is told to whoever may read the settings (`admin:settings:read`):

```bash
curl -u admin http://localhost:8000/api/v1/system/information
```

```json
{
  "version": "0.1.0",
  "schema": {"revision": "0007", "expected": "0007", "current": true},
  "runtime": {
    "python": "3.13.1",
    "platform": "Linux-6.6-x86_64-with-glibc2.41",
    "started_at": "2026-10-12T08:00:00Z"
  },
  "database": {"version": "PostgreSQL 17.2"}
}
```

`schema.current` is false when the database is at another revision than this version
was written for, which is also when `/api/v1/status/ready` answers `503`. Nothing of the
configuration is in it.
