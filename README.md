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
| `MEGOOARTI_SECRET_KEY` | generated | Key that seals stored secrets such as remote passwords; use a long random value. If unset or empty, a key is generated into `secret.key` in the data directory on first use |
| `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` | `104857600` | Largest `npm publish` request accepted. A publish is read into memory, so this bounds what one costs |

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
  in with a password. Use one as a bearer token, or as the password in HTTP Basic,
  with your user name or with the name `__token__`, which is how Python's tools send
  a token. A token can be limited to a list of patterns and can expire.
- **Anonymous access** is off by default. When turned on under `/api/v1/settings`,
  requests without credentials act as the built-in `anonymous` user. That user starts
  with the built-in `anonymous` role, which allows reading **every** repository. To
  make only some repositories public, replace that role on the `anonymous` user with
  one of your own.
- A request from a web page on another site that would change something is refused
  with `403 cross_site_request`. If the server sits behind a reverse proxy on plain
  HTTP, set the base URL under `/api/v1/settings` so its own pages are recognised.
- Five failed sign-ins for one username, or from one address, within 15 minutes block
  further attempts until the window ends. A valid API token is never refused by this
  limit. Behind a reverse proxy, set `MEGOOARTI_FORWARDED_ALLOW_IPS` to the proxy's
  address; otherwise every client appears to come from the proxy and shares one limit.
- Requests without credentials can only ever be allowed `repository:` permissions,
  whatever roles the `anonymous` user holds.

The full API is described at `/api/docs`.

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
- A cached file is kept even if the remote later stops having it.
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
- **An offline repository** can still be browsed and deleted from here. Being offline
  stops package clients, not the people who tend the repository.
- **A proxy** is browsed for what it has cached, and deleting from it removes the
  cached copy: it is fetched again when it is next asked for.
- **A group** holds nothing of its own. It lists its `members`, which are browsed one
  by one.

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
uv run pytest -m docker       # builds the image; tests it with real clients (needs internet)
uv run ruff check .
uv run ruff format --check .
uv run python -m megooarti    # serve on http://localhost:8000 using .env
```

Tests create and use the databases `megooarti_test` and `megooarti_test_migrations`.
Set `MEGOOARTI_TEST_DATABASE_URL` to use a different server.
