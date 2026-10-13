# MegooArti

An open-source repository and artifact proxy and manager. See the
[business requirements](docs/BRD.md) for scope and roadmap.

It is two services and a database: a backend (FastAPI) that is the REST API, the
repositories and the Docker registry, and a web UI (Next.js) that uses that API.

## Quick start

Requires Docker with Compose.

```bash
cp .env.example .env          # then set MEGOOARTI_DB_PASSWORD in it
docker compose up --build --detach --wait
curl http://localhost:8000/api/v1/status/ready
```

Nothing starts until the database has a password of your choosing: `.env.example`
says what else an installation may choose. `docker compose build` makes the images
`ghcr.io/mmhy2003/megooarti-backend` and `ghcr.io/mmhy2003/megooarti-frontend`,
tagged with the version. They are named for the project's own place in GitHub's
registry; nothing is published there yet, so they are built here.

The second command prints `{"status":"ok","checks":{"database":"ok","schema":"ok"}}`.
The web UI is at <http://localhost:8000>, and interactive API documentation at
<http://localhost:8000/api/docs>. [First sign-in](#first-sign-in) says how to get in.

Compose starts four containers: the database, the backend, the frontend, and a
gateway (nginx) that is the one published address and sends each request to the
backend or the frontend. The gateway is for development and testing. In production,
put [your own reverse proxy](#behind-your-own-reverse-proxy) in its place.

## Configuration

All configuration is by environment variable.

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

## First sign-in

On first start MegooArti creates the `admin` account with a random password, writes it
to `admin.password` in the data directory, and logs it once:

```bash
docker compose exec backend cat /var/lib/megooarti/admin.password
```

Sign in with it, as `admin`, at <http://localhost:8000>. You must then choose a new
password, after which the file is deleted. The same with `curl`:

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<the generated password>"}' \
  http://localhost:8000/api/v1/auth/login
```

The response contains a `csrf_token`. Requests that use the session cookie and change
anything must send it in an `X-CSRF-Token` header.

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
  further attempts until the window ends. A valid API token is never refused by this
  limit. Behind a reverse proxy, set `MEGOOARTI_FORWARDED_ALLOW_IPS` to the proxy's
  address; otherwise every client appears to come from the proxy and shares one limit.
- Requests without credentials can only ever be allowed `repository:` permissions,
  whatever roles the `anonymous` user holds.

The full API is described at `/api/docs`. The page is served with its own script and
stylesheet, and asks nothing of another host.

## Repositories

A **blob store** is where file content is kept; the `default` one is a directory under
the data directory. A **repository** holds files in one format. The formats so far are
`raw` (arbitrary files by path), `maven`, `npm`, `pypi` and `docker`.
A repository has one of three types: `hosted` (files you publish), `proxy` (a cache of
a remote repository) or `group` (several repositories behind one URL).

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

- **Permissions** are `repository:<format>:<name>:<action>`, where the action is `browse`
  (see what is there), `read` (download), `add` (a new path), `edit` (replace a path) or
  `delete`. For example `repository:raw:files:read`, or `repository:raw` for everything
  on every Raw repository.
- **Deployment policy** per hosted repository: `allow_redeploy`, `disable_redeploy`
  (a path can be written once) or `read_only`. A repository that is made without one
  allows redeploy, except a Maven repository for releases, which refuses it: a release
  is deployed once. Replacing a repository's settings without naming a policy keeps
  the one it has.
- **A name** is 1 to 64 letters, digits, `.`, `_` or `-`, and not `.` or `..`.
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
- A cached file is kept even if the remote later stops having it.
- A connection to the remote that cannot be made is tried twice more, a moment
  apart, before it counts as a failure: a network drops one now and then.
- After a connection failure, or a `502`, `503`, `504` or `429` from the remote, it is
  left alone for a minute, doubling with each further failure up to an hour. Set
  `"blocked": true` to stop contacting it altogether, or `"auto_block": false` to turn
  automatic blocking off. Saving the repository's settings lifts a block.
  `GET /api/v1/repositories/<name>` shows the current state and the last error under
  `status`.
- `POST /api/v1/repositories/<name>/invalidate-cache` makes the proxy check everything
  with the remote again. Changing `remote_url` or the credential does the same.
- `remote_url` must not contain a user name or password; put them in `remote_auth`.
- The remote secret is sealed before it is stored and is never returned; the API shows
  only `has_secret`. Leave `secret` out when updating to keep the stored one, unless
  the remote's scheme, host or port changes: then it must be given again. It is sent
  only to the configured remote, never to another host the remote redirects to.
- A remote on a public address is not followed when it redirects to a loopback,
  link-local or private address. Host names are not resolved for this check, so if you
  proxy remotes you do not trust, also restrict the server's outbound network access.
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

### Maven repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "releases", "format": "maven", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"},
  "format_config": {"version_policy": "release"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "snapshots", "format": "maven", "type": "hosted",
  "format_config": {"version_policy": "snapshot"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "central", "format": "maven", "type": "proxy",
  "proxy": {"remote_url": "https://repo1.maven.org/maven2"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "maven-public", "format": "maven", "type": "group",
  "group": {"members": ["releases", "snapshots", "central"]}
}' http://localhost:8000/api/v1/repositories
```

Point a project at the hosted repositories in its `pom.xml`:

```xml
<distributionManagement>
  <repository>
    <id>megooarti</id>
    <url>https://repo.example.com/repository/releases/</url>
  </repository>
  <snapshotRepository>
    <id>megooarti</id>
    <url>https://repo.example.com/repository/snapshots/</url>
  </snapshotRepository>
</distributionManagement>
```

and give Maven the credentials in `~/.m2/settings.xml`, under the same `id`:

```xml
<servers>
  <server>
    <id>megooarti</id>
    <username>ci</username>
    <password>an API token</password>
  </server>
</servers>
```

- **Version policy** (`version_policy`): `release` (default), `snapshot` or `mixed`. It
  decides which versions a repository takes, and cannot be changed after creation.
- **Layout policy** (`layout_policy`): `strict` (default) takes only paths in the Maven
  layout; `permissive` also takes other paths, as plain files.
- **Checksums are computed, never stored.** A request for `app-1.0.jar.sha1` (or `.md5`,
  `.sha256`, `.sha512`) is answered from the hash recorded for the file. A checksum that
  a client uploads is compared with the file. A wrong one is refused with `400` and
  logged as `checksum_mismatch`; the file stays. Maven itself only warns when a checksum
  upload fails, so a corrupted deploy shows in the server log, not in the build result.
- **`maven-metadata.xml` is generated** on every request from the files stored, so it is
  right after a delete and after two deploys at the same moment. What clients upload is
  accepted and discarded, except plugin prefixes, which are kept for each group.
- `latest` and `release` are the highest versions in Maven's version order, not the
  most recently deployed ones.
- **A deploying account needs `add` and `read`**, for example
  `repository:maven:releases:add` and `repository:maven:releases:read`: Maven reads a
  repository's metadata before it uploads. It does not need `edit`.
- **Maven refuses plain HTTP** to any host but `localhost` (since Maven 3.8.1). Put
  MegooArti behind HTTPS for clients on other machines.
- **A proxy** caches what it fetches. It serves the remote's `maven-metadata.xml` as
  received, and answers checksum requests from the cached file: it never asks the
  remote for a checksum file. Metadata and old-style snapshot files are checked again
  after `metadata_max_age_minutes`; release files after `content_max_age_minutes`. A
  proxy with the `release` policy does not ask its remote for snapshots.
- **A group** serves a file from the first member that has it, and merges
  `maven-metadata.xml` from every member that can answer, so one URL lists your own
  versions and the remote's. A group has no policies of its own.

To send everything Maven resolves through the group, mirror it in `~/.m2/settings.xml`:

```xml
<mirrors>
  <mirror>
    <id>megooarti</id>
    <mirrorOf>*</mirrorOf>
    <url>https://repo.example.com/repository/maven-public/</url>
  </mirror>
</mirrors>
```

Reading through a group needs `read` on the group only, for example
`repository:maven:maven-public:read`.

### npm repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-hosted", "format": "npm", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"}
}' http://localhost:8000/api/v1/repositories
```

Point npm at it and sign in. `npm login` asks for a user name and a password, and
MegooArti answers with a personal API token, which npm keeps in `~/.npmrc`:

```bash
npm config set registry https://repo.example.com/repository/npm-hosted/
npm login --auth-type=legacy
npm publish
```

In a pipeline, skip `npm login` and give npm a token directly:

```ini
registry=https://repo.example.com/repository/npm-hosted/
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```

A proxy caches the public registry, and a group puts your own packages and the public
ones behind one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-proxy", "format": "npm", "type": "proxy",
  "proxy": {"remote_url": "https://registry.npmjs.org"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-public", "format": "npm", "type": "group",
  "group": {"members": ["npm-hosted", "npm-proxy"]}
}' http://localhost:8000/api/v1/repositories
```

Install through the group and publish to the hosted repository. In `.npmrc`:

```ini
registry=https://repo.example.com/repository/npm-public/
//repo.example.com/repository/npm-public/:_authToken=${NPM_TOKEN}
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```

and in the `package.json` of each package you publish:

```json
"publishConfig": {"registry": "https://repo.example.com/repository/npm-hosted/"}
```

- **Signing in** accepts a password, or an API token in place of the password. Each
  sign-in with a password creates a token named `npm login` and the time; it is listed
  with your other tokens and can be revoked there. `npm logout` revokes it. Failed
  attempts are limited as for any sign-in.
- **The package document is generated** on every request from the versions stored, so
  it is right after an unpublish and after two publishes at the same moment.
- **A published tarball is checked** against the `shasum` and `integrity` in its
  manifest. A publish that does not match is refused.
- **Publishing a version again** follows the deployment policy. Use `disable_redeploy`
  to get npm's own rule that a version is published once.
- **Dist-tags.** `latest` is the highest version if the version it named is removed.
- **`npm deprecate` and `npm unpublish` act on the package as it is now.** If someone
  published in between, they answer `409`; run the command again.
- **Permissions.** `npm publish` needs `add`. `npm deprecate` needs `edit`.
  `npm unpublish` needs `delete`, and `add` or `edit` as well when it removes a single
  version, because npm does that by sending the package document back.
- **A publish is read into memory**, up to `MEGOOARTI_NPM_MAX_PUBLISH_BYTES`.
- **Search** (`npm search`) finds the packages a repository holds, by name: at a proxy
  the packages it has cached, at a group those of all its members.
- `npm audit` is not supported; installs do not need it.
- **A proxy** caches what it fetches. It serves the remote's package document with the
  tarball links pointed at MegooArti, so tarballs are downloaded through it and cached
  too. A package document is checked again with the remote after
  `metadata_max_age_minutes`; a tarball after `content_max_age_minutes`.
- **A group protects the names you publish.** If a hosted member holds a package, only
  hosted members answer for it, for its document and its tarballs alike. A package on
  the public registry with the same name as one of yours cannot add a version to it or
  stand in for one (the dependency-confusion attack). While that hosted repository is
  offline the group answers `503` for the package; it does not fall back to the public
  one. To use your own build of a public package beside the public versions, publish
  it under a scope.
- **A group merges** what its hosted members hold of a package, the earlier member
  winning a version or a dist-tag both have. A package only proxies have is served
  from the proxy that has it. If several proxies have it their documents are merged in
  the members' order while they fit in 16 MiB together; the first that does not fit,
  and those after it, are left out. Merging is done again for every request, so list
  each registry once: do not add a proxy of a registry that another proxy's remote
  already includes.
- **A name is protected while a hosted repository holds a version of it.**
  Unpublishing the last version gives the name back to the proxies.
- **Signing in works at every npm repository**, so `npm login` can point at the group.
  `npm publish`, `npm dist-tag`, `npm deprecate` and `npm unpublish` work at a hosted
  repository only.
- **Set the base URL** under `/api/v1/settings` when clients reach MegooArti through a
  reverse proxy. Tarball links in package documents are built on it; without it they
  follow the address of each request.
- **Clients.** Installs are tested with npm, pnpm and Yarn 1. Yarn 1 sends a token for
  an unscoped package only if `.npmrc` also says `always-auth=true`.

Reading through a group needs `read` on the group only, for example
`repository:npm:npm-public:read`.

### PyPI repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-hosted", "format": "pypi", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"}
}' http://localhost:8000/api/v1/repositories
```

Upload to the repository's address, with the slash at its end, and install from
`simple/` beneath it:

```bash
twine upload --repository-url https://repo.example.com/repository/pypi-hosted/ \
  -u __token__ -p "$MEGOOARTI_TOKEN" dist/*
uv publish --publish-url https://repo.example.com/repository/pypi-hosted/ --token "$MEGOOARTI_TOKEN"

pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-hosted/simple/ my-package
```

A proxy caches pypi.org, and a group puts your own packages and the public ones behind
one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-proxy", "format": "pypi", "type": "proxy",
  "proxy": {"remote_url": "https://pypi.org"}
}' http://localhost:8000/api/v1/repositories

curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "pypi-public", "format": "pypi", "type": "group",
  "group": {"members": ["pypi-hosted", "pypi-proxy"]}
}' http://localhost:8000/api/v1/repositories
```

Install through the group, and upload to the hosted repository:

```bash
pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-public/simple/ my-package
uv pip install --index-url https://__token__:$MEGOOARTI_TOKEN@repo.example.com/repository/pypi-public/simple/ my-package
```

For Poetry, name the group as the project's primary source and give it the token:

```toml
[[tool.poetry.source]]
name = "megooarti"
url = "https://repo.example.com/repository/pypi-public/simple/"
priority = "primary"
```

```bash
poetry config http-basic.megooarti __token__ "$MEGOOARTI_TOKEN"
```

- **Credentials** are HTTP Basic: a user name and password, a user name and a token, or
  `__token__` and a token. A token in the place of the user name
  (`https://<token>@host/`) is refused.
- **A project's page is generated** on every request from the files stored, so it is
  right after a delete and after two uploads at the same moment. It is the HTML index
  of PEP 503, with each file's `sha256` and the Python versions it requires.
- **Every spelling of a name is one project**: `My_Package`, `my.package` and
  `my-package` are stored and listed as `my-package`.
- **An upload is streamed to disk** as it arrives, whatever its size, and is checked
  against the `sha256` and `md5` digests the client sends. Wheels (`.whl`) and source
  distributions (`.tar.gz`, `.zip`) are taken; the file's name must fit its project.
  `poetry publish` sends the same request as twine, and is tested too.
- **A file name has one address in its project**, whatever version an upload declares
  for it: `packages/<project>/<version in the file name>/<file name>`.
- **Uploading a file again** follows the deployment policy. With `disable_redeploy` it
  answers `409`. `uv publish --check-url <index address>` passes over files that are
  already there; give that address its credentials, because uv does not send the
  token to it. twine's `--skip-existing` works only with pypi.org.
- **Permissions.** Uploading a new file needs `add`, replacing one `edit`, and deleting
  one (`DELETE` on its address under `packages/`) `delete`.
- Signatures sent with an upload are not kept. The JSON index (PEP 691) and yanking a
  release on a hosted repository are not available yet; pip, uv and Poetry do not
  need them.
- **A proxy** keeps the remote's page for each project and writes its own from it,
  with every link pointed at MegooArti, so files are downloaded through it and cached.
  The remote's marks for yanked files, required Python versions and metadata files
  (PEP 658) are passed on, and the metadata files themselves are fetched and cached
  like any file. A project's page is checked again with the remote after
  `metadata_max_age_minutes`. A file, once cached, is not asked about again until
  the proxy's cache is invalidated; it is then checked against the page once more.
- **The remote address** of a proxy is the index's root (`https://pypi.org`), or the
  index itself if the address ends in `/simple` (or devpi's `/+simple`).
- **A proxy fetches each file from the address the remote's page gives for it**, which
  for pypi.org is another host. If the page gives a `sha256`, `sha512`, `sha1` or
  `md5` hash for the file, the file must match it, or it is not kept (`502`); a file
  the page gives no such hash for is kept unchecked and listed without one. The
  remote's credentials are sent only to the remote's own scheme, host and port. A
  file address that is not on the public internet (loopback, link-local, private,
  however the address is written) is refused unless the remote itself is at that
  host. Host names are not resolved for this check: network egress rules are the
  complete defence.
- **A group protects the names you upload.** If a hosted member holds a project, only
  hosted members answer for it, for its page and its files alike: a project on the
  public index with the same name as one of yours cannot add a file to it or stand in
  for one (the dependency-confusion attack). While that hosted repository is offline
  the group answers `503` for the project. A name is protected while a hosted
  repository holds a file of it.
- **A group lists a project once**, from all the hosted members that hold it, or from
  all the proxies that have it. A file name two members list is taken from the earlier
  one.
- The root index (`simple/`) of a proxy lists the projects it has cached a file of,
  not the remote's; a group lists those of all its members.
- **Clients.** Installs are tested with pip, uv and Poetry; uploads with twine,
  `uv publish` and `poetry publish`.

Reading through a group needs `read` on the group only, for example
`repository:pypi:pypi-public:read`.

### Docker repositories

MegooArti is a container registry for Docker, Podman and containerd. A Docker
repository is not used under `/repository/`: container clients speak to `/v2/` at the
root of a host, and the first part of an image's name says which repository it is in.
A Docker repository's name therefore has to be one a container client can write:
lower-case letters and digits, with single `.`, `_` or `-` between them.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-hosted", "format": "docker", "type": "hosted"
}' http://localhost:8000/api/v1/repositories

docker login repo.example.com
docker tag my-app:1.0 repo.example.com/docker-hosted/team/my-app:1.0
docker push repo.example.com/docker-hosted/team/my-app:1.0
docker pull repo.example.com/docker-hosted/team/my-app:1.0
```

- **HTTPS.** Container clients refuse plain HTTP to every host but `localhost`, so
  put MegooArti behind HTTPS for clients on other machines. The registry has to be at
  the root of its host: a deployment under a path prefix cannot serve Docker. Behind a
  reverse proxy, set the base URL under `/api/v1/settings`: it is where clients are
  sent to sign in.
- **Signing in.** `docker login` takes a user name with a password or with an API
  token. The client is then given a registry token that lasts five minutes, and
  fetches a new one by itself. Disabling a user or revoking an API token takes effect
  at once; a changed password within five minutes. Tools that send HTTP Basic
  credentials or an API token with every request are accepted too. A registry token
  is taken under `/v2/` only: it cannot be used on the rest of the API.
- **Permissions.** Pulling needs `read`. Pushing needs `read` and `add`, because a
  client first asks which layers are already there; moving a tag needs `edit` as
  well, and deleting needs `delete`. For example
  `repository:docker:docker-hosted:read`.
- **Public images.** With anonymous access on, `docker pull` works without
  `docker login` wherever the `anonymous` user may read. Out of the box that is every
  repository, Docker ones included. To make only some public, take the built-in
  `anonymous` role away from the `anonymous` user and give it a role with `read` on
  those repositories, such as `repository:docker:docker-public:read`.
- **Tags that cannot be moved.** With the deployment policy `disable_redeploy`, a tag
  that exists cannot be given to another image (`409`). Pushing the image it already
  names again changes nothing and is accepted.
- **Images for several platforms** are pushed and pulled as one. Docker's and the OCI's
  manifests and manifest lists are taken; the retired schema 1 is not.
- **A layer is stored once** in a repository, however many of its images use it, and
  is not uploaded again. Whoever may read a repository may fetch any layer in it by
  its digest.
- **Uploads are streamed to disk** in the chunks the client sends, whatever the size
  of the layer, and can be resumed. A layer sent in one request, as Docker, containerd
  and Podman send it, is written once; one sent in several is joined when the upload
  completes, and may have at most 10,000 chunks. A layer must match its digest or it
  is not kept.
- **Deleting an image** is done by its digest, and removes the tags that name it and
  the layers nothing else in the repository uses. Deleting a tag removes the tag
  alone: the image can still be pulled by its digest. Docker has no command for
  either, so use the API:

  ```bash
  curl -u admin -I https://repo.example.com/v2/docker-hosted/team/my-app/manifests/1.0
  # Docker-Content-Digest: sha256:...
  curl -u admin -X DELETE https://repo.example.com/v2/docker-hosted/team/my-app/manifests/sha256:...
  ```

- **Cleaning up.** A layer that no image refers to, and an upload that was never
  finished, are removed after a day. A push that stops half-way leaves nothing behind
  for longer than that.
- **Listing.** `GET /v2/_catalog` lists the images you may read as
  `<repository>/<image>`, and `GET /v2/<repository>/<image>/tags/list` an image's tags.
- Errors under `/v2/` have the registry API's own shape, which container clients
  show: `{"errors": [{"code": "...", "message": "..."}]}`.
- Not available: the referrers API (clients fall back to tags), mounting a layer from
  another repository (it is uploaded instead), and deleting a single layer.
- **Clients.** Tested with the Docker client and daemon, whose pushes and pulls go
  through containerd's registry client, and with skopeo, which is built on the image
  library Podman uses.

A proxy is a pull-through cache of another registry:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-hub", "format": "docker", "type": "proxy",
  "proxy": {"remote_url": "https://registry-1.docker.io"}
}' http://localhost:8000/api/v1/repositories

docker pull repo.example.com/docker-hub/alpine:3
docker pull repo.example.com/docker-hub/grafana/grafana:latest
```

- **The remote address** is the registry's own, without `/v2/`: for Docker Hub
  `https://registry-1.docker.io` (not `docker.io` or `hub.docker.com`), or for example
  `https://ghcr.io`, `https://quay.io`, `https://registry.k8s.io`. On Docker Hub an
  image with a one-part name is an official image, so `alpine` is fetched as
  `library/alpine`, as Docker does.
- **Signing in to the remote.** Public registries hand out a token before they serve
  anything, usually from another host. The proxy fetches one, with the user name and
  password (or access token) in `remote_auth` if there is one, and uses it until it
  runs out. The credential is sent to the remote and to the sign-in address the remote
  names, never to the host its layers are downloaded from. A sign-in address must use
  HTTPS if the remote does, and must not be an internal address unless the remote is
  at that host.
- **A tag** is asked about again after `metadata_max_age_minutes`. Only its digest is
  asked for, which registries that count pulls do not count; the image is fetched
  again only if the tag names another one. While the remote cannot be reached, or if
  it has dropped the tag, what is held is served.
- **An image by its digest, and a layer,** are fetched once and checked against the
  digest. What does not match is not kept (`502`). They are never asked about again.
- **A manifest is read before it is kept**, so the proxy knows the layers each image
  uses. A layer that no kept manifest refers to is removed after a day, as on a hosted
  repository, and fetched again if it is asked for.
- **Tags** (`tags/list`) are the remote's, kept for `metadata_max_age_minutes`. The
  catalog lists the images that have been pulled through the proxy.
- An image the remote does not have, or will not show to the proxy's credential, is
  answered `404`. A registry says the same of both.
- Nothing can be pushed to a proxy or deleted from it through the registry API (`405`).

A group puts your own images and the public ones behind one address:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "docker-all", "format": "docker", "type": "group",
  "group": {"members": ["docker-hosted", "docker-hub"]}
}' http://localhost:8000/api/v1/repositories

docker pull repo.example.com/docker-all/team/my-app:1.0
docker pull repo.example.com/docker-all/alpine:3
```

- **A group protects the images you push.** If a hosted repository behind the group
  has an image, only hosted repositories answer for that image: its tags, its
  manifests and its layers. An image on a public registry with the same name cannot
  stand in for yours or add a tag to it (the dependency-confusion attack), whatever
  the order of the members. If the only hosted repositories that have the image are
  offline, the group answers `503` for it.
- **A name is protected while a hosted repository holds anything of the image**, with
  a tag or without. Deleting a tag withdraws a release and does not hand the name to
  a public image: the tag is then `404`, and the image is still pulled by its digest.
  The name is free again once every manifest of the image has been deleted by its
  digest.
- **Everything else** comes from the proxies behind the group, the first that has it.
  If none has it and one of them could not ask its remote, the answer is `502`, not
  `404`.
- **Tags** (`tags/list`) are those of every repository that answers for the image,
  each once. The catalog lists every image with a tag in the online repositories
  behind the group, as `<group>/<image>`.
- Push to the hosted repository, not to the group: a group takes no pushes (`405`).
  Groups can contain groups.

Reading through a group needs `read` on the group only, for example
`repository:docker:docker-all:read`.

## Browsing and deleting

What the repositories hold can be looked at and removed without a package client,
through `/api/v1/content`. It is what the web UI will use.

```bash
# The repositories you may browse, and one of them
curl -u alice https://repo.example.com/api/v1/content
curl -u alice https://repo.example.com/api/v1/content/maven-releases

# A folder, a file, and the components (packages and their versions)
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/tree?path=com/acme'
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/asset?path=com/acme/app/1.0/app-1.0.jar'
curl -u alice 'https://repo.example.com/api/v1/content/maven-releases/components?namespace=com.acme&name=app'

# Delete a file, a component, or everything under a folder
curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/asset?path=com/acme/app/1.0/app-1.0-sources.jar'
curl -u alice -X DELETE https://repo.example.com/api/v1/content/maven-releases/components/<id>
curl -u alice -X DELETE 'https://repo.example.com/api/v1/content/maven-releases/tree?path=com/acme/app'
```

- **Seeing needs `browse`** on the repository, and downloading needs `read`. Deleting
  through this API needs `browse` and `delete`, and nothing else: not the right to
  publish. The list leaves out what you may not browse, and a group names only the
  members you may browse.
- **A folder** (`tree`) lists what is directly in it, in the byte order of the names,
  each entry a `folder` or a `file`. It is read a page at a time: give the `next` of
  one answer as `after` in the following request. There is no total, because a
  folder can hold millions of entries and counting them would mean reading them. An
  empty `path` is the root, and `limit` is at most 200. A name that is both a file and
  a folder is listed as each.
- **A file** (`asset`) is described with its size, content type, four checksums, blob
  store, who stored it and when, when it was last downloaded, the component it
  belongs to, and the address to download it from.
- **A component** is a package version: a Maven artifact version, an npm package
  version, a PyPI release, a Docker tag. In a Raw repository every file is one.
  `components/<id>` lists its files.
- **How to use a component** is part of its detail: `usage` is a list of snippets,
  each with a `label`, the `language` it is written in (`xml`, `kotlin`, `groovy` or
  `shell`) and the `text` to copy. Maven gets a `<dependency>` and a line for Gradle
  in Kotlin and in Groovy, npm `npm install <name>@<version> --registry=<address>`,
  PyPI `pip install --index-url <address>simple/ <name>==<version>`, a Docker tag
  `docker pull <host>/<repository>/<image>:<tag>`. The address is the repository's
  public one (the `base_url` setting, if it is set). A Raw file has no snippet: it has
  its `download` address. Nor has a component whose name or version holds anything
  but letters, digits and `. _ + ~ / -`, or does not begin with a letter, a digit or
  `_`: the text is there to be pasted into a shell or a build file, and a name is
  chosen by whoever deployed it.
- **Deleting goes through the format**, so the repository is left as the format's own
  client would leave it. A deleted npm tarball is an unpublished version, and
  dist-tags that named it move. A deleted Docker manifest takes its tags and the
  layers nothing else uses with it; a deleted tag goes alone. Maven's metadata and
  checksums and PyPI's pages are computed from the files, so they follow by
  themselves.
- **What a format keeps for itself cannot be deleted on its own** (`409
  managed_by_format`): an npm package's dist-tags, a Docker layer that an image uses.
- **Deleting a folder** removes the files under it through the same rules, at most
  1,000 in one request. The answer says how many of them were `deleted` (what went
  with them, such as the tags and layers of a Docker manifest, is not counted), how
  many were `skipped` because the format keeps them, and gives a `next` to repeat the
  request with, as `after`, while there may be more. The root of a repository cannot
  be deleted this way.
- **An offline repository** can still be browsed, deleted from and uploaded to here.
  Being offline stops package clients, not the people who tend the repository.
- **A proxy** is browsed for what it has cached, and deleting from it removes the
  cached copy: it is fetched again when it is next asked for.
- **A group** holds nothing of its own. It lists its `members`, which are browsed one
  by one.

## Uploading

A file can be put into a hosted repository without a package client: one
`multipart/form-data` request to `/api/v1/content/<repository>/upload`, with the
fields its format needs.

```bash
# Raw: files into a directory, each under its own name
curl -u alice -F directory=docs/v1 -F file=@guide.pdf -F file=@logo.png \
  https://repo.example.com/api/v1/content/files/upload

# Maven: an artifact by its coordinates. A POM is written for it
curl -u alice -F group=com.acme -F artifact=app -F version=1.0 \
  -F file=@app.jar -F file.sources=@app-sources.jar \
  https://repo.example.com/api/v1/content/maven-releases/upload

# npm: the tarball that `npm pack` writes
curl -u alice -F file=@tool-1.0.0.tgz https://repo.example.com/api/v1/content/npm-hosted/upload

# PyPI: wheels and source distributions
curl -u alice -F file=@greeter-1.0-py3-none-any.whl -F file=@greeter-1.0.tar.gz \
  https://repo.example.com/api/v1/content/pypi-hosted/upload
```

| Format | Fields | Files |
| --- | --- | --- |
| Raw | `directory` (the root without it) | One or more `file`, each stored in the directory under its own name |
| Maven | `group`, `artifact`, `version`; `packaging` (default `jar`); `generate_pom` (default `true`) | `file` for the artifact, `file.<classifier>` for a file beside it (`file.sources`), `pom` for its POM |
| npm | `tag` (default `latest`) | One `file`: a package tarball. Its `package.json` says the name and the version |
| PyPI | `summary`, `requires_python`, `keywords`, each optional and said of every file | One or more `file`: wheels and source distributions (`.whl`, `.tar.gz`, `.zip`) |

- **The answer** is `201` with the `files` that were stored, each described as `asset`
  describes a file, and the `components` they belong to.
- **All or nothing.** If one file of a form is refused, none of them is stored, in
  the repository or in the blob store.
- **Permissions and policy are those of any upload:** `add` for a new file, `edit` to
  replace one, and the repository's deployment policy. Uploading needs no right to
  browse or to read.
- **A file must be sent as a file**, with a file name: `-F file=@app.jar`, not
  `-F file=app.jar`. A field the format does not know is refused, so a misspelt one
  is not silently ignored.
- **Maven.** The files go where a deploy would put them, and checksums and
  `maven-metadata.xml` follow by themselves. What a file is (`jar`, `war`, `tar.gz`,
  `jar.asc`) is read from the end of its own name; the rest of its name does not
  matter. Without a POM, one is written that says the group, artifact, version and
  packaging: enough for a build that depends on the artifact. None is written if the
  form sends one, if the version already has one, or with `generate_pom=false`. The
  repository's version policy applies. A snapshot (`1.0-SNAPSHOT`) is not uploaded: a
  build deploys it, and numbers it as it does. A checksum file (`.sha1`, `.md5`) is
  refused: checksums are computed from the files.
- **npm.** What is stored is what `npm publish` would store: the tarball, and the
  `package.json` inside it as the version's manifest. A package whose `package.json`
  says `"private": true` is refused, as npm refuses to publish it. The tarball may be
  as large as a publish may be (`MEGOOARTI_NPM_MAX_PUBLISH_BYTES`), and is read into
  memory to find its `package.json`, which must be among its first 100,000 files and
  256 MiB. Every other upload goes to the blob store as it arrives.
- **PyPI.** A file's name says its project and version. A source distribution's is
  read as the project, a hyphen and the version, so its version must be written
  without a hyphen (`1.0.post1`, not `1.0-1`), as current build tools write it. What
  the form does not say of a release that exists, its summary and keywords, stays as
  it was. `requires_python` is kept with each file and is not read out of it: give it
  for a package that needs a certain Python, or installers will offer the file to all.
- **Docker images are pushed** with a container client. A Docker repository, a proxy
  and a group answer `409 upload_not_supported`.
- **A form that cannot be used** answers `422 validation_error`, and its `details`
  name the field. A file that is not what its format takes answers as that format's
  own upload does (`400 invalid_package`, `400 version_policy_violation`,
  `400 invalid_path`).

## Search

`/api/v1/search` finds components in every repository you may browse.

```bash
curl -u alice 'https://repo.example.com/api/v1/search?q=commons+lang'
curl -u alice 'https://repo.example.com/api/v1/search?format=maven&namespace=com.acme&name=app*'
curl -u alice 'https://repo.example.com/api/v1/search?sha1=2ef7bde608ce5404e97d5f042f95f89f1c232871'
```

- **`q`** is matched as it reads: each word must be contained in the component's
  group, name or version, or in the words its format adds, whatever the case. `*`
  stands for anything; every other character is itself. At most ten words are looked
  at. Results are in the order of their names by bytes (capitals first), not ranked.
- **What a format adds:** for Maven `group:artifact:version` as one word; for npm
  `@scope/name` and the keywords and description of `package.json`; for PyPI the
  summary and keywords of the upload; for Docker `image:tag`. In a Raw repository a
  file is found by its folder and name. What a proxy has cached is found by its name
  and version only: descriptions and keywords are those of packages published here.
- **`namespace`, `name` and `version`** match a whole value, whatever the case, with
  `*` for anything: `name=commons*`. The namespace is a Maven group, an npm scope
  (without the `@`), a Raw file's folder.
- **`md5`, `sha1`, `sha256`, `sha512`** find the components that have a file with
  exactly that checksum, written as tools print it: in either case, and with or
  without its name in front (`sha256:...`).
- **`format` and `repository`** narrow where to look. With nothing given, everything
  you may browse is listed, a page at a time (`limit`, `offset`).
- Each result names its `repository` and has an `id`, which opens at
  `/api/v1/content/<repository>/components/<id>`.
- A Docker manifest without a tag is not found: tags are. A group is not searched;
  what is behind it is.
- **Rebuilding an index.** `POST /api/v1/repositories/<name>/rebuild-index` (for an
  administrator) goes through a repository again: every file is given to the
  component its path says it belongs to, and every component's words are written
  again. It answers with how many files and components it looked at and changed.
  Run it for each repository after upgrading to the version that added search:
  until then, what was already stored is found by its name and version only. The
  work is done in the request, a piece at a time, and takes minutes on a large
  repository. It is safe to repeat: if the request is cut off, for example by a
  reverse proxy's time limit, what was done stays done; run it again.
- Search uses PostgreSQL's `pg_trgm` extension, which the migrations create. Where
  the application's database role may not create extensions, have a database
  administrator run `CREATE EXTENSION pg_trgm` in the database before upgrading.

## The web UI

The UI is at the root of the installation's address. It has what a person who uses
the repositories needs (browsing them, search, upload and delete), a person's own
account, and everything an administrator keeps: users, roles, anonymous access,
repositories, blob stores and the installation's own settings.

- **Browsing.** A repository opens one folder at a time, with the way there as a path
  above it. Choosing a file shows everything known of it beside the folder: its size,
  type and four checksums (each with a button that copies it), who stored it and when,
  and a download link. Every folder and file has an address of its own, so a link to
  one can be shared. A group lists its members. A proxy shows what has been fetched
  through it so far.
- **A component's page** says what a package version is, lists its files, and gives
  what to paste into a build or a shell to use it (for Maven, the dependency for
  Maven and for Gradle), each with a copy button.
- **Search** is a box in the header of every screen: press `/` to reach it. The
  results page filters by format, repository, group, name and version, and by a
  file's checksum: paste an MD5, SHA-1, SHA-256 or SHA-512, and its length says which
  it is. A search is in the address, so it can be shared and gone back to. Search
  looks in hosted and proxy repositories: what a group serves is found in its members.
- **Upload** is offered for a hosted Raw, Maven, npm or PyPI repository to whoever
  may add to it, from the repository ("Upload here") and from the navigation. The
  form has the fields the format needs. Files are chosen, or dropped onto a file
  field. It shows how much has been sent, and can be stopped. What the server refuses
  about a field is said at that field, which then has the keyboard; anything else is
  said above the button. A Docker image is pushed with a container client.
- **Delete** is offered to whoever may delete in the repository. A file or one
  version is deleted after a question. A folder is deleted, with everything under
  it, only after its name is typed. Each is removed as the format's own client would
  remove it, so the indexes stay right.
- **What you may not do is not offered.** Without the permission to add there is no
  upload, without the permission to delete no delete. The server decides in every
  case: the screens only leave out what it would refuse.
- **Your account** is under your name in the header: your API tokens, your password,
  and your preferences.
  - **API tokens.** A token gets a name, an expiry (never, 30 days, 90 days, a year,
    or a day you choose) and a limit: everything you may do, only read, or the
    permissions you choose. Its secret is shown once, when it is made, with a button
    that copies it. A token is revoked from the same page.
  - **Preferences** are kept in the browser: the mode, and whether `/` goes to the
    search box. They are reached from the mode menu too, by a visitor as well.
- **Administration** is shown to whoever holds the permission to read each part.
  - **Users.** Create a user with a password you type or have generated, and tick
    the roles they hold. A user's page changes their name, email, roles and state,
    sets a new password, lists and revokes their API tokens, and deletes them after
    you type their name. Your own account cannot be disabled or deleted there, and
    your own password is changed under your account, where you are asked for the one
    you have. A built-in user cannot be deleted.
  - **Roles.** A role's permissions are rows: choose what a row is about (a
    repository, or an area of administration), then the format, repository and
    action from lists. The pattern the row makes is shown with what it grants in
    words. A pattern the lists cannot make is typed by hand, and a role that was
    written through the API opens with nothing lost. The `admin` role is shown and
    cannot be changed.
  - **Anonymous access** is one switch, which asks before it is turned on, and shows
    what someone who is not signed in may then do. If the `anonymous` user is
    disabled, nothing is given though the switch is on, and the page says so.
  - **Manage repositories** lists every repository as it is set up. A new one is made
    on one page: choose the format and the type, and the page shows what that
    combination has. A hosted repository has a deployment policy; a proxy has its
    remote, how it signs in there, how long it trusts what it cached, and what it
    does when the remote fails; a group has its members, put in order with buttons;
    a hosted or proxy Maven repository has a version policy and a layout policy.
    What cannot change later (name, format, type, blob store, version policy) is
    shown as it is and not as a field, beside the address the repository's clients
    use. A proxy's secret is typed and never shown: leave the field empty to keep
    the one that is stored. A repository's page also shows a proxy's state and last
    error, has it check everything with its remote again, rebuilds the index, and
    deletes the repository after you type its name.
  - **Blob stores** lists the stores with how many blobs each holds, their size and
    the space left, makes a new one, and deletes one that no repository uses. Its
    files stay on the disk. The store called `default` is always kept: a repository
    that names no blob store is put in it.
  - **System** shows the version, the schema's revision and whether it is the one this
    version expects, when the server started and what it runs on, the database's
    version, and the blob stores. The base URL is set there.
- **Signing in** uses the session cookie the API sets. It is marked `Secure`, so a
  browser keeps it over HTTPS, and over plain HTTP only on the machine itself
  (`localhost`). If you reach the UI over plain HTTP at another name or address,
  signing in will say that the browser did not keep the session: use HTTPS, or set
  `MEGOOARTI_SESSION_COOKIE_SECURE=false`.
- **Anonymous access.** If it is on, a visitor who is not signed in sees what the
  anonymous user may browse, and a "Sign in" button. If it is off, the sign-in screen.
- **Light and dark.** The mode switch in the header chooses light, dark, or as the
  system says. The choice is kept in the browser.
- **Nothing is fetched from anywhere else.** Fonts, icons and scripts are served by
  MegooArti itself, so the UI works in a network with no way out. The UI sends a
  strict content security policy: only its own scripts run, and it cannot be framed.
- **Keyboard and screen readers.** Every screen can be used by keyboard alone, starts
  with a link that skips to its content, and meets WCAG 2.1 AA contrast in both modes.
  When a screen changes under the keyboard (a folder is entered, a file is deleted,
  another page of results is shown), the keyboard is put at what changed. `/` reaches
  the search box from anywhere that is not a place to type, and can be turned off
  under Preferences.

## Behind your own reverse proxy

One address serves everything. Whatever stands in front must send each request to
the right service:

| Path | To | What it is |
| --- | --- | --- |
| `/api/` | backend, port 8000 | The REST API and its documentation |
| `/repository/` | backend, port 8000 | Maven, npm, PyPI and Raw repositories |
| `/v2/` | backend, port 8000 | The Docker registry |
| everything else | frontend, port 3000 | The web UI |

[gateway/nginx.conf](gateway/nginx.conf) is a complete example: it is what Compose
runs, and the real-client tests of this project (Maven, npm, pip, Docker and a
browser) pass through it. Towards the backend, your proxy must do what it does:

- **Pass the path on exactly as it was sent.** An npm scope arrives as an encoded
  slash (`@scope%2fname`) and must stay one. In nginx that means `proxy_pass` with no
  path after the address.
- **Put no limit on the size of a body** (`client_max_body_size 0`), and do not buffer
  it: an artifact can be gigabytes, and goes to the backend as it arrives
  (`proxy_request_buffering off`). Do not buffer answers either
  (`proxy_buffering off`).
- **Wait long enough.** A proxy repository may take minutes to fetch a large file
  from its remote before the first byte comes back (`proxy_read_timeout 600s`).
- **Speak HTTP/1.1 to the backend** (`proxy_http_version 1.1`), so that a body of
  unknown length can be passed on as it arrives.
- **Send `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`**, and set
  `MEGOOARTI_FORWARDED_ALLOW_IPS` on the backend to your proxy's address. The backend
  writes the addresses it gives to clients (tarball links, the registry's token
  address) from them, unless the base URL is set in the system settings.
- **Write `X-Forwarded-For` yourself, from the address you see.** Do not pass on the
  one a client sent: the backend counts failed sign-ins by that address and writes it
  to its log, and a client that could choose it could evade the limit or lock out
  somebody else's address. (`gateway/nginx.conf` sets it to `$remote_addr`. If your
  proxy is itself behind another one that you trust, pass on what that one says.)
- **Terminate TLS**, and add `Strict-Transport-Security` if you want it. The frontend
  leaves compression to you as well.

Do not publish the backend's or the frontend's own port beside it: the session cookie
and the content security policy assume one origin.

## Backup and restore

A backup is two files: the database, and the data directory, which holds the blob
stores and the key that stored secrets are sealed with.

```bash
sh scripts/backup.sh /path/to/backup
```

It backs up the installation that `docker compose` finds from the repository's
directory; if yours was started under another project name, set
`COMPOSE_PROJECT_NAME` to it. Nothing is stopped, but the database and the backend
must be running. The database is dumped first and the files are copied after: a file
is on the disk before the database names it, and stays for
`MEGOOARTI_BLOB_GRACE_SECONDS` (a day) after nothing names it, so a copy made after
the dump has every file the dump names, as long as the backup takes less than that.

It writes `database.dump`, `data.tar` and `VERSION` into the directory, readable by
their owner alone: the dump has every password's hash, and the copy has the key. A
backup that is there already is replaced only when the new one is whole; if anything
fails, the script says so, ends with an error, and leaves the old one as it was. It
names any blob store whose directory is outside the data directory: those files are
not in the backup, and are yours to copy.

To restore, into an installation that has nothing in it yet (a new machine, or after
`docker compose down --volumes`, which destroys what is there):

```bash
cp .env.example .env          # then set MEGOOARTI_DB_PASSWORD: this installation's own
sh scripts/restore.sh /path/to/backup
```

It refuses a database or a data directory that is not empty, and reads both files
through before it writes anything. Should it stop between its two halves, it says so:
what is there is then not whole, and `docker compose down --volumes` empties it for
another try. Users, sessions, API tokens, repositories and their content are then as
they were when the backup was made, and what was stored after it is gone. A backup of
an older version is brought up to this one when the backend starts.

Without the key (`secret.key` in the data directory, or `MEGOOARTI_SECRET_KEY` if you
set one) a proxy's stored password cannot be read and must be entered again. Nothing
else depends on it. If you set `MEGOOARTI_SECRET_KEY`, keep it with the backup: it is
not in it.

## Health endpoints

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

Tests create and use the databases `megooarti_test` and `megooarti_test_migrations`.
Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server.

A test whose setup fails leaves what it said in `backend/.test-failures/`, one file
for each, and the end of the run says so. A test of the running stack that fails
leaves the stack's logs there too. The newest fifty are kept; Git does not see the
folder.

The tests marked `docker` run the clients themselves against a stack built from the
working tree: Maven, Gradle and sbt; npm, pnpm and yarn; pip, uv, poetry and twine;
docker; a browser; and the backup and restore scripts. Their images are tagged
`test`, and their stack has a project name and ports of its own.

**Known vulnerabilities** in what is depended on are looked for with:

```bash
cd backend
uv export --frozen --no-emit-project --output-file requirements.txt
uvx pip-audit --requirement requirements.txt --disable-pip
cd ../frontend
pnpm audit --prod             # what the image has
pnpm audit                    # and what development uses
```

**How long answers take** with many clients at once is measured by
`backend/scripts/latency.py`, against a running installation, with a load generator
it runs in a container. Its first lines say how.

### The web UI

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

## Licence

MIT: see [LICENSE](LICENSE). Two things in the repository are other projects' and
keep their own licences, each beside its files: Swagger UI, which draws the API's
documentation page (Apache-2.0, in `backend/src/megooarti/static/swagger-ui/`), and
the three typefaces of the web UI, Oxanium, Inter and JetBrains Mono (SIL Open Font
License, in `frontend/src/fonts/`).
