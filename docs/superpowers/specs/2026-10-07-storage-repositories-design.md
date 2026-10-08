# Storage and Repositories — Technical Design

| | |
| --- | --- |
| **Status** | Draft for review |
| **Date** | 2026-10-07 |
| **Implements** | [BRD](../../BRD.md): BLB-1, BLB-2, BLB-4, BLB-6, BLB-7, REP-1 to REP-12, REP-13 (cache invalidation), CMP-1, FMT-8, FMT-23, NFR-2, NFR-3, NFR-5, NFR-7, NFR-11, TSK-5 (blob compaction) |
| **Builds on** | [Identity and access design](2026-10-07-identity-access-design.md) |
| **Series** | Plans 3a and 3b of Phase 1 |

## 1. Purpose

Give MegooArti somewhere to put artifacts and a way to reach them: blob stores, repositories of three types, a format interface that later plans plug into, and the first format, Raw.

Success means:

- An administrator can create a blob store and a hosted, proxy or group repository through the REST API.
- `curl -T file https://host/repository/files/a/b.bin` stores a file of any size without memory growing with it, and `curl` gets the identical bytes back, including by range.
- A proxy repository serves a remote file, keeps serving it when the remote is down, and remembers what the remote does not have.
- A later plan can add a format by writing one class and registering it, without changing storage, security or routing code.

## 2. Scope

One design, delivered as two plans.

| Plan | Contents |
| --- | --- |
| **3a** | Blob stores (filesystem), blobs, repositories, components and assets; the format interface; hosted Raw; central authorisation for repository content; blob compaction; administration API for blob stores and hosted repositories; security hardening carried over from the plan 2 review |
| **3b** | Secret encryption; proxy repositories; group repositories; their administration |

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| S3 blob store, soft quota, integrity verification task | Phase 2 |
| Browse, search, UI upload, component and asset detail API | Plan 8 |
| Rebuilding a search index (the rest of REP-13) | Plan 8 |
| Cleanup policies, routing rules, strict content-type validation | Phase 2 |
| Writing through a group repository | Not planned (Nexus Pro feature) |
| Outbound HTTP proxy settings, trusted certificates | Phase 3 |
| Rendering hosted content inline in a browser | Later, with sandboxing, if wanted |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | Repository content lives at `/repository/{name}/{path}`. | Existing Nexus client configurations work by changing only the host. |
| D2 | When anonymous access is on, every principal is also allowed what the `anonymous` user is allowed on repositories. | Public content is public to everyone; nobody loses access by signing in. |
| D3 | Repository content is always sent as a download and never rendered. | Content is served from the same site as the administration UI; an uploaded HTML file must not run as the signed-in administrator. |
| D4 | Stored secrets are encrypted with `MEGOOARTI_SECRET_KEY` if set, otherwise with a key generated into the data directory on first start. | Works with no configuration; operators who manage keys can supply one. |
| D5 | Blobs are stored by content hash (SHA-256). Asset paths never become file paths. | Identical content is stored once, and no request path can reach the filesystem. |
| D6 | Each format is one class behind a common interface, with generic hosted, proxy and group behaviour that a format overrides only where it differs. | Adding a format changes no core code (FMT-23); Raw is the generic behaviour unchanged. |
| D7 | Authentication and authorisation for repository content happen in one place, before any format code runs. | A format cannot forget a check. |
| D8 | Reading through a group needs permission on the group only. | Matches Nexus; a group is how an administrator publishes a curated view. |
| D9 | A proxy repository downloads a missing file completely, verifies it, then serves it. | Simple and correct; streaming to the client while caching is a later optimisation. |

## 4. Blob storage

### 4.1 Model

| Table | Columns | Notes |
| --- | --- | --- |
| `blob_stores` | `id`, `name` (unique, `[A-Za-z0-9_.-]{1,64}`), `type` (`file`), `config` (JSONB), `created_at` | For `file`, `config` is `{"path": "..."}`. A relative path is under `<MEGOOARTI_DATA_DIR>/blobs/`; an absolute path is used as given |
| `blobs` | `id`, `blob_store_id`, `sha256`, `md5`, `sha1`, `sha512`, `size`, `created_at`, `unreferenced_since` (nullable) | Unique on (`blob_store_id`, `sha256`) |

A migration creates the blob store `default` with path `default`. Directories are created when first written to.

No two blob stores may use the same directory, or directories one inside the other; creating one that would is refused. Stores sharing files would let compaction of one delete content the other still serves.

### 4.2 Files

```text
<store root>/content/<first 2 hex>/<next 2 hex>/<sha256>
<store root>/tmp/<random>
```

### 4.3 Writing

1. The request body is streamed in chunks to a file under `tmp/` while MD5, SHA-1, SHA-256 and SHA-512 are computed. File and hash work runs off the event loop. Memory use is bounded by the chunk size (NFR-2).
2. If the client declared `Content-Length`, or sent `X-Checksum-Md5`, `X-Checksum-Sha1` or `X-Checksum-Sha256`, the received size and hashes must match. A mismatch, or a connection that ends early, discards the temporary file and stores nothing (NFR-11).
3. In one database transaction: take a lock for that hash; move the temporary file into place if no file is there, and sync its directory so the rename survives a power loss; insert the `blobs` row or clear its `unreferenced_since`; create or update the asset. Commit.

The lock is a transaction-level advisory lock derived from the hash. Compaction takes the same lock, so a blob cannot be removed while an upload of the same content is being recorded. The check in step 3 looks at the file, not the row, so a missing file is always replaced.

### 4.4 Reading

Assets are streamed from the blob file in chunks, off the event loop. One byte range per request is supported; a request for several ranges gets the whole file.

### 4.5 Deleting and compaction

- Deleting or replacing an asset removes a reference. When the last reference to a blob goes, its `unreferenced_since` is set. This mark is an optimisation: concurrent deletes can each see the other's reference and leave none. Compaction is the source of truth, and begins each run by marking every blob that nothing uses and nothing has marked, which starts its grace period.
- **Compaction** removes blobs unreferenced for longer than a grace period (default 24 hours): under the blob's lock it re-checks that nothing references it, deletes the row, deletes the file, and commits. It also deletes files under `tmp/` older than 24 hours.
- Compaction runs inside the application on a fixed interval (default hourly). A session-level advisory lock ensures only one container runs it at a time. An interval of `0` disables it.
- A file left without a row by a crash is harmless: it is reused if the same content is uploaded again. Finding such files is the Phase 2 integrity task.

### 4.6 Metrics and deletion of a store

A blob store reports its blob count and total bytes (from the database) and the bytes available on its filesystem (BLB-4). A blob store used by any repository cannot be deleted (BLB-1). A blob store's path cannot be changed.

### 4.7 Backend interface

Blob file operations sit behind a small interface (`stage`, `commit`, `discard`, `open`, `delete`, `exists`, `usage`, `sweep_temporary`) with one implementation, filesystem. The Phase 2 S3 store is a second implementation.

## 5. Repositories, components and assets

| Table | Columns | Notes |
| --- | --- | --- |
| `repositories` | `id`, `name` (`[A-Za-z0-9_.-]{1,64}`, unique ignoring case), `format`, `type` (`hosted` / `proxy` / `group`), `online`, `blob_store_id` (null for groups), `config` (JSONB), `created_at`, `updated_at` | `name`, `format`, `type` and `blob_store_id` never change (REP-2) |
| `repository_members` | `group_id`, `member_id`, `position` | Ordered members of a group (plan 3b) |
| `components` | `id`, `repository_id`, `namespace`, `name`, `version`, `attributes` (JSONB), `created_at`, `updated_at` | Unique on (`repository_id`, `namespace`, `name`, `version`); empty string where a format has no namespace or version |
| `assets` | `id`, `repository_id`, `component_id` (nullable), `path`, `blob_id`, `content_type`, `kind`, `attributes` (JSONB), `created_by`, `created_at`, `updated_at`, `last_downloaded_at`, `last_verified_at` | Unique on (`repository_id`, `path`). `created_by` is a username, not a foreign key. `last_verified_at` is used by proxies |
| `proxy_state` | `repository_id`, `failures`, `blocked_until`, `last_error`, `last_checked_at` | Plan 3b; shared by all containers |
| `negative_cache` | `repository_id`, `path`, `expires_at` | Plan 3b |

Deleting a repository deletes its components and assets; their blobs become unreferenced. Outside that, a component is removed only by code that holds the component's lock and has seen that no asset is left; the database refuses to delete a component that still has assets, so an upload into a component can never lose it to a concurrent delete of a sibling file. A repository that is a member of a group cannot be deleted until it is removed from the group.

**Asset paths** are relative, use `/` separators, and are at most 1024 bytes. A path with an empty segment, a `.` or `..` segment, a backslash, or a control character is rejected with `400 invalid_path`. Paths are case-sensitive.

`last_downloaded_at` is written at most once an hour per asset.

### 5.1 Repository settings

| Type | Settings (in `config`) |
| --- | --- |
| hosted | `deployment_policy`: `allow_redeploy` (default), `disable_redeploy`, `read_only` |
| proxy | `remote_url` (http or https); `content_max_age_minutes` (default 1440, `-1` never revalidate); `metadata_max_age_minutes` (default 1440); `negative_cache`: `enabled` (default true), `ttl_minutes` (default 1440); `remote_auth`: `type` (`none` / `basic` / `bearer`), `username`, secret; `blocked` (default false); `auto_block` (default true) |
| group | Ordered member names; members must have the group's format; a group may contain groups; cycles are rejected |
| any | `format_config`: settings the format defines and validates. Raw defines none |

## 6. The format interface

A format is a class registered under its name. It declares which repository types it supports and may override any of the following; the base class implements all of them generically.

| Hook | Generic behaviour (what Raw uses) |
| --- | --- |
| Validate `format_config` | Accept only an empty object |
| Handle a request to a hosted repository | `PUT` stores the body at the path; `GET` / `HEAD` serve it; `DELETE` removes it |
| Describe an upload as a component | Namespace is the directory, name is the file name, no version; one asset |
| Map a path to a remote URL (proxy) | `remote_url` + `/` + path |
| Say whether a path is metadata (proxy) | Never; every path uses `content_max_age_minutes` |
| Answer a request to a group | The first member, in order, that has the path |

Formats never touch tables or files. They receive a **repository context** holding the repository, the principal and a storage facade with `get(path)`, `put(path, stream, ...)`, `delete(path)` and `serve(asset, request)`. The facade enforces the deployment policy and the `add`, `edit` and `delete` permissions, so a format cannot bypass them.

`put` is the simple case: one upload, one asset. A format that publishes several files in one request uses the two halves it is made of: `stage(stream)` receives and verifies content without touching the database, and `store(path, staged)` records it inside the caller's transaction. Staging everything first and then storing everything makes the publish atomic.

Formats do not commit. The route commits once the format's handler returns, and nothing is kept if it raises.

## 7. Requests for repository content

Every method on `/repository/{name}/{path}` goes through one route:

1. **Authenticate** as in the identity design (Basic, bearer, session cookie, anonymous). A `401` here carries `WWW-Authenticate: Basic realm="MegooArti"`, which package clients expect. Cookie-authenticated requests that change state need the CSRF token, as everywhere else.
2. **Find the repository.** Unknown name: `404`.
3. **Authorise.** `GET` and `HEAD` need `repository:<format>:<name>:read`. Storing needs `add` for a new path or `edit` for an existing one; deleting needs `delete`. These three are checked by the storage facade at the moment of the operation.
4. **Check it is online.** Otherwise `503 repository_offline`.
5. **Dispatch** by type: hosted to the format's handler, proxy to the proxy engine, group to the group engine.

### 7.1 `authorize`

`authorize(principal, permission)` is the one function that decides: no principal or an anonymous one lacking the permission gives `401`; a pending password change gives `403`; an identified principal lacking it gives `403`; a permission that is not well-formed is refused. `require(permission)` becomes a thin wrapper over it. Code outside the security package never inspects a principal's patterns directly.

With D2, a principal's check for a `repository:` permission also passes if anonymous access is on and the `anonymous` user's roles grant it. Token scopes do not narrow this: it is what anyone may do without credentials.

### 7.2 Response headers for content

- `Content-Type` as stored; `Content-Length`; `ETag` (the SHA-256, quoted); `Last-Modified`; `Accept-Ranges: bytes`; `X-Checksum-Md5`, `X-Checksum-Sha1`, `X-Checksum-Sha256`, `X-Checksum-Sha512`.
- `Content-Disposition: attachment` with the file name; `X-Content-Type-Options: nosniff`; `Content-Security-Policy: sandbox` (D3).
- `If-None-Match` and `If-Modified-Since` give `304`. `Range` gives `206` with `Content-Range`, or `416` if it cannot be satisfied. `If-Range` is honoured with an `ETag`.

### 7.3 Hosted Raw

| Request | Result |
| --- | --- |
| `PUT path` | `201` for a new asset, `204` for a replaced one. `Content-Type` is taken from the request, else guessed from the file extension, else `application/octet-stream` |
| `GET path`, `HEAD path` | The content, or `404` |
| `DELETE path` | `204`, or `404` |
| Any other method | `405` |

With `read_only`, `PUT` and `DELETE` give `403 repository_read_only`. With `disable_redeploy`, a `PUT` to an existing path gives `409 redeploy_disabled`.

## 8. Proxy repositories (plan 3b)

Only `GET` and `HEAD` are accepted.

1. **Cached and fresh** (verified within the maximum age): serve it.
2. **Cached but stale:** ask the remote with `If-None-Match` / `If-Modified-Since`. `304` marks it verified; `200` replaces it. If the remote fails, serve the cached copy (REP-10).
3. **Not cached:** if the negative cache has the path, `404`. Otherwise download it to the blob store, verify it, record it, and serve it. A remote `404` adds the path to the negative cache. For `HEAD`, the remote is asked with `HEAD` and nothing is cached.
4. **Remote failure with nothing cached:** `502 remote_unavailable`.

- Within one process, concurrent requests for the same missing path wait for one download.
- **Blocking (REP-9):** with `auto_block`, a failure marks the repository blocked until a time that doubles with each consecutive failure, from 1 minute up to 1 hour. While blocked, the remote is not contacted. A success clears it. `blocked: true` blocks it by hand. The state is visible in the repository API.
- **Remote authentication (REP-8):** Basic or bearer, sent only to the configured remote host. The secret is encrypted at rest (D4) and never returned by the API, which reports only whether one is set.
- Outbound requests use `http` or `https` only, follow at most 5 redirects, and identify as `MegooArti/<version>`.
- **Invalidate cache (REP-13):** marks every cached asset stale and empties the negative cache for that repository.

### 8.1 Secret encryption

Secrets are encrypted with authenticated symmetric encryption (Fernet). The key is `MEGOOARTI_SECRET_KEY` when set; otherwise a key is generated at first start into `<MEGOOARTI_DATA_DIR>/secret.key`, readable only by the owner. Losing the key makes stored secrets unreadable; they must then be entered again.

## 9. Group repositories (plan 3b)

`GET` and `HEAD` only. Members are tried in order; offline members are skipped; the first that has the path answers, using its own hosted, proxy or group behaviour but without a permission check on the member (D8). If none has it, `404`. Formats that publish index files override this to merge them (REP-12); Raw has none.

### 9.1 Refinements settled while planning proxy and group repositories

- **Caching for a reader.** The facade has a `cache` operation that records content with no permission or policy check and the creator `proxy`. It refuses to run on anything but a proxy repository. The check that matters, `read` on the proxy or on the group in front of it, has already happened.
- **Sealed secrets by type.** The repository service accepts a remote secret only as a sealed value; the API seals it. A plain string is a programming error, not bad input.
- **A cached file outlives its remote copy.** If the remote answers `404` for a file that is already cached, the cached copy is kept and marked verified. Known gap: until the browse API of plan 8 there is no way to evict one cached file, so a file withdrawn upstream keeps being served, and invalidating the cache only re-confirms it.
- **What counts toward blocking.** Transport failures, `502`, `503`, `504` and `429`: answers that say the remote as a whole is struggling. A plain `500` is usually one broken path and does not block; neither do `401` and `403`, so a wrong credential shows up on every request. A failure counts only if the remote was not already blocked, so requests in flight during one outage count as one failure. Turning `auto_block` off lifts a block already in place, and saving a proxy's settings clears its failure record.
- **The remote URL carries no credentials.** A `remote_url` with a user name or password in it is refused; credentials belong in `remote_auth`, where they are sealed. The outbound client's own request logging is turned down, so URLs are not copied into the log.
- **A stored secret stays with its remote.** A secret that is not sent on update is kept only if the kind of credential and the remote's scheme, host and port are all unchanged. Otherwise the secret must be given again, so that someone allowed to edit a repository cannot point it at their own server and be sent a secret they were never shown.
- **A changed remote starts clean.** When a proxy's `remote_url` or credential changes, its cached files are marked stale and its negative cache is emptied.
- **No cookies.** The outbound client keeps no cookies, so a session a remote starts on an authenticated request is never replayed on a request without the credential.
- **Encoded bodies are refused.** The remote is asked for the bytes as stored. If it compresses the body anyway, nothing is cached.
- **Redirects inward are refused.** A remote on a public address that redirects to a loopback, link-local or private address written as an address is not followed, so whoever runs a remote cannot aim the server at an internal service. Names are not resolved, so a name that resolves inward is not caught; network egress rules are the complete defence. A remote that is itself internal may redirect internally.
- **A request that cannot be sent is a failure, not a crash.** A URL the client rejects, or a credential that cannot be an HTTP header, fails the request with `502` without blocking.
- **An unreadable credential is recorded.** It is logged and shown as the repository's last error, because behind a group its `502` becomes a `404`.
- **A group with no answer.** If every member lacks the path, is offline, or cannot reach its remote, the group answers `404`. A member's other errors, such as `416`, are returned as they are.
- **Cross-site writes.** A request that changes state is refused with `403 cross_site_request` if it carries `Sec-Fetch-Site: cross-site`, or, where the browser sends no fetch metadata (plain HTTP), if its `Origin` is neither the `Host` it was sent to nor the configured base URL. Browsers remember HTTP Basic credentials after the `/repository` challenge; package clients send neither header. `same-site` is accepted, so a hostile sibling subdomain is not covered.
- **A group's members are always stated.** Updating a group without its member list is refused, so that an update never empties it by omission.

## 10. Administration API

Under `/api/v1`, JSON, standard error envelope, paged lists.

| Method and path | Needs | Result |
| --- | --- | --- |
| `GET /blob-stores` | `admin:blobstores:read` | Page of blob stores with metrics |
| `POST /blob-stores` | `admin:blobstores:write` | `201`. Body: `name`, `type`, `path` |
| `GET /blob-stores/{name}` | `admin:blobstores:read` | One blob store with metrics |
| `DELETE /blob-stores/{name}` | `admin:blobstores:write` | `204`, or `409 in_use` |
| `GET /repositories` | `admin:repositories:read` | Page of repositories |
| `POST /repositories` | `admin:repositories:write` | `201`. Body: `name`, `format`, `type`, `online`, `blob_store`, and the settings for the type |
| `GET /repositories/{name}` | `admin:repositories:read` | The repository, its URL path, and for a proxy its blocking state |
| `PUT /repositories/{name}` | `admin:repositories:write` | Replaces `online` and the settings. Sending a different `format`, `type` or `blob_store` is `409 immutable` |
| `DELETE /repositories/{name}` | `admin:repositories:write` | `204`, or `409 in_use` if it is a group member |
| `POST /repositories/{name}/invalidate-cache` | `admin:repositories:write` | `204` (proxy only; plan 3b) |

### 10.1 Error codes added

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_path` | Section 5 |
| 400 | `checksum_mismatch` | Section 4.3 |
| 403 | `repository_read_only` | Section 7.3 |
| 409 | `redeploy_disabled` | Section 7.3 |
| 409 | `in_use` | A blob store with repositories; a repository in a group |
| 409 | `immutable` | Section 10 |
| 409 | `repository_cycle` | A group would contain itself |
| 416 | `range_not_satisfiable` | Section 7.2 |
| 502 | `remote_unavailable` | Section 8 |
| 503 | `repository_offline` | Section 7 |

## 11. Code structure

Under `backend/src/megooarti/`:

| Module | Responsibility |
| --- | --- |
| `storage/backends.py` | The blob backend interface and the filesystem implementation |
| `storage/models.py` | `BlobStore`, `Blob` |
| `storage/blob_stores.py` | Blob store service: create, describe with metrics, delete, backend lookup |
| `storage/blobs.py` | Stage, record, dereference and compact blobs; the per-hash lock |
| `storage/api.py` | Blob store router |
| `repositories/models.py` | `Repository`, `RepositoryMember`, `Component`, `Asset`, `ProxyState`, `NegativeCacheEntry` |
| `repositories/service.py` | Repository create, update, delete, lookup; settings validation |
| `repositories/paths.py` | Path validation |
| `repositories/content.py` | The storage facade and the repository context |
| `repositories/serving.py` | Building a content response: headers, conditional requests, ranges |
| `repositories/formats.py` | The format base class and the registry |
| `repositories/raw.py` | The Raw format |
| `repositories/routes.py` | The `/repository/{name}/{path}` route and dispatch |
| `repositories/api.py` | Repository administration router |
| `repositories/proxy.py`, `remote.py`, `group.py` | Plan 3b: proxy engine, outbound HTTP client, group engine |
| `secrets_box.py` | Plan 3b: encrypt and decrypt stored secrets |
| `maintenance.py` | The in-process periodic runner and its single-runner lock |

## 12. Configuration added

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_COMPACTION_INTERVAL_SECONDS` | `3600` | How often blob compaction runs; `0` disables it |
| `MEGOOARTI_BLOB_GRACE_SECONDS` | `86400` | How long an unreferenced blob is kept before compaction removes it |
| `MEGOOARTI_SECRET_KEY` | none | Key for encrypting stored secrets; generated into the data directory if unset (plan 3b) |

## 13. Hardening carried over from the plan 2 review

- `authorize` as in 7.1, used by `require` and by the repository route.
- A test that walks every route and fails if one outside a short allowlist has no authentication dependency.
- Tests that use real transactions for behaviour the shared test connection cannot show: an upload racing compaction of the same content, and two uploads of the same new content.

## 14. Testing

- **Blob backend:** unit tests on a temporary directory, including a body larger than the chunk size, an interrupted stream, and a hash or length mismatch.
- **Streaming:** a test uploads and downloads a body many times the chunk size and asserts it moved in bounded chunks.
- **Content responses:** table-driven tests of conditional and range requests.
- **Raw hosted:** through the in-process client: store, replace, fetch, delete, each deployment policy, each permission, anonymous access with D2, and the D3 headers.
- **Proxy and group (3b):** against a fake remote served in-process: hit, miss, stale, `304`, remote down with and without a cached copy, negative cache, blocking and back-off, credentials sent only to the remote, member order, offline members, cycles.
- **Container:** a test that uploads and downloads through the published port with an API token.

## 15. Risks

| Risk | Mitigation |
| --- | --- |
| Python throughput for large transfers | Chunked I/O off the event loop; measured against NFR-4 in plan 11; horizontal scaling later |
| D9 delays the first byte of a large uncached file | Accepted for Phase 1; revisit before the Docker format (plan 7) |
| A crash between moving a file and committing leaves an unrecorded file | Harmless and reused on re-upload; Phase 2 integrity task finds them |
| An administrator can point a proxy at an internal address | Inherent to proxying; limited to `admin:repositories:write`; only http and https |
| Losing the secret key | Documented; secrets are re-entered; backing up the data directory is part of the backup guide (plan 11) |

## 16. Requirement coverage

| Requirement | Covered by |
| --- | --- |
| BLB-1, BLB-2, BLB-4 | 4.1, 4.6, 10 |
| BLB-6 | 4.5 |
| BLB-7 | 4.3 (content-addressed) |
| REP-1, REP-2, REP-3 | 5, 7, 10 |
| REP-4 | 5.1, 7.3 |
| REP-5 to REP-10 | 8 |
| REP-11, REP-12 | 9 |
| REP-13 | 8 (invalidate cache); index rebuild in plan 8 |
| CMP-1 | 5, 6 |
| FMT-8 | 6, 7.3, 8, 9 |
| FMT-23 | 6 |
| NFR-2, NFR-3 | 4.3, 4.4 |
| NFR-5 | 7.2 |
| NFR-7 | 8.1 |
| NFR-11 | 4.3 |
| TSK-5 | 4.5 |
