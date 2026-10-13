# Repositories

What is true of every repository, whatever its format. Each format has a guide of its
own for what is its own, and for its clients:
[Maven](formats/maven.md), [npm](formats/npm.md), [PyPI](formats/pypi.md),
[Docker](formats/docker.md) and [Raw](formats/raw.md).

Repositories and blob stores are set up in the web UI (Administration) or through the
API, as here. What they hold can be browsed, searched, uploaded to and deleted from
without a package client: see [The API](api.md#browsing-and-deleting) and
[The web UI](web-ui.md).

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

## Proxy repositories

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

## Group repositories

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

A group that finds a file in none of its members answers `404`, also when one of
them could not ask its remote: a build that names several repositories then goes on
to the next. The proxy's own page, and `GET /api/v1/repositories/<name>`, say what it
last met at its remote. (A Docker group answers `502` in that case: see
[Docker](formats/docker.md).)
