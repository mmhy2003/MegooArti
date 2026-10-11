# Docker Format — Technical Design

| | |
| --- | --- |
| **Status** | Draft for review |
| **Date** | 2026-10-11 |
| **Implements** | [BRD](../../BRD.md): FMT-4, FMT-5, FMT-7, REP-12 (tag lists), SEC-9 (a token wherever a password is accepted), NFR-1 (Docker, Podman, containerd), and the Docker part of REP-1 to REP-11 |
| **Builds on** | [Storage and repositories design](2026-10-07-storage-repositories-design.md), [npm format design](2026-10-08-npm-format-design.md) (the repositories behind a group, the rule for a name a hosted repository holds), [PyPI format design](2026-10-08-pypi-format-design.md) (fetching from an address a remote names) |
| **Series** | Plans 7a, 7b and 7c of Phase 1 |

## 1. Purpose

Make MegooArti a container registry: somewhere to push a team's own images, a pull-through cache in front of Docker Hub and other registries, and one address that presents both.

Success means:

- `docker login`, `docker push` and `docker pull` work against `repo.example.com/<repository>/<image>:<tag>` with Docker, Podman and containerd, with no port per repository and no client-side workaround beyond the usual trust of the host's certificate.
- An image with several platforms is pushed and pulled as one.
- A layer is stored once, however many images use it, and disk space comes back when an image is deleted.
- An image on a public registry cannot stand in for one the team pushed.

## 2. Scope

One design, delivered as three plans.

| Plan | Contents |
| --- | --- |
| **7a** | Core changes (section 4.1); the registry API at `/v2/`; sign-in with the token flow; hosted Docker: push, pull, tags, the catalog, delete; cleaning up layers nothing uses; real client tests against a hosted repository |
| **7b** | Core changes (section 4.2); Docker proxy: a pull-through cache, with the remote's own token sign-in |
| **7c** | Docker group; real clients through a group |

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| A dedicated port or host name for one repository (FMT-6) | Phase 2. The BRD ranks it there |
| The retired image formats: Docker manifest schema 1, and registry API v1 | Not planned. Docker removed them |
| The referrers API (OCI 1.1), used to find signatures and attestations of an image | Later. It answers `404`, and clients then use tags, which work |
| Cross-repository blob mounts between two MegooArti repositories | Later. The upload proceeds as an ordinary one |
| Deleting a blob by its digest | Not planned. Layers are removed with the images that use them (section 7.5) |
| Cleanup by age or by tag pattern, and scheduled garbage collection an administrator configures | Phase 2, with cleanup policies |
| Vulnerability scanning, image signing policy | Not in the BRD's Phase 1 |
| Usage snippets, browsing image layers in the UI | Plans 8 to 10 |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | The registry API is served at `/v2/` on the host. The first part of an image's name is the repository: `/v2/<repository>/<image>/...`. The image name is everything between the repository and the last `/manifests/`, `/blobs/` or `/tags/`, and may contain slashes. | FMT-5. Docker clients only speak to `/v2/` at a host's root, so this is the only way to address repositories without a port for each. |
| D2 | A Docker repository is used only through `/v2/`. Its content is not served under `/repository/<name>/`. | One way in, with one error format and one kind of challenge. A format says where it is served. |
| D3 | Sign-in uses the registry token flow. A request without credentials is answered `401` with a `Bearer` challenge that names `/v2/token`. The client presents a user name and a password or API token there and receives a registry token, valid for five minutes, which it sends with its requests. HTTP Basic credentials and API tokens sent directly with a request are accepted too. | FMT-4 asks for token authentication, and it is what `docker login` expects. Some tools send Basic credentials without being asked. |
| D4 | A registry token is not stored. It is a sealed statement of who signed in and how. Every request that carries one loads the user, the roles and the API token again, so disabling a user or revoking a token takes effect at once. | Nothing to clean up, and no window in which a revoked credential still works. |
| D5 | Anonymous pull is granted through roles, as for every format: with anonymous access switched on, the `anonymous` user is given `read` on the repositories that are to be public. Its built-in role allows reading every repository, so an administrator who wants only some public replaces that role. A client without credentials gets a registry token for that user. | FMT-7. One place says who can read what. Chosen by the product owner over a switch on each repository. |
| D6 | A layer or image configuration is stored once in a repository, at `blobs/sha256:<hex>`, and is shared by every image in it. | Permissions are for a repository, not for an image, so every image in a repository may see every layer in it. A layer that exists is never uploaded again. |
| D7 | A manifest is stored at `manifests/<image>/sha256:<hex>`, and a tag at `tags/<image>/<tag>` as a file holding the manifest it names. The tag is a component: the image's name, and the tag as its version. | The stored file's own hash is the digest a client asks for. A tag is then a path like any other, so the deployment policy applies to it: `disable_redeploy` makes tags immutable. |
| D8 | Each manifest records the blobs and manifests it refers to. Deleting a manifest by its digest removes its tags, the manifests of its platforms that nothing else uses, and the blobs no other manifest in the repository refers to. Deleting or moving a tag removes nothing else. A blob that no manifest has referred to for a day is removed by maintenance. | Chosen by the product owner: disk space comes back without an administrator running a task. A manifest that lost its tag stays, because deployments pin images by digest. |
| D9 | An upload in progress is a row in the database and, in the blob store's temporary area, one file for each chunk, which is written once and never again. Any container can take the next chunk. The request that completes an upload removes its row first, so that no other request can find the upload, and then turns its chunks into the blob: a single chunk, which is how clients send a layer, is hashed in place and not copied; several are joined into one file. | Chunked uploads span requests, and requests reach any container. A layer of gigabytes should be written once. What is hashed must be what is stored, whatever arrives for the same upload meanwhile: a blob store addressed by content is only as good as that. |
| D10 | Only SHA-256 digests are accepted. | It is what Docker, Podman and containerd send, and what the blob store is addressed by. |
| D11 | Errors under `/v2/` use the registry's own JSON shape (`{"errors": [{"code", "message", "detail"}]}`), not MegooArti's. | Clients show the registry's codes to users. This is the one API that does not use the standard error envelope. |
| D12 | In a group, if a hosted member has an image name, only hosted members answer for it: its tags, its manifests and its blobs. A hosted member that is offline still counts. | The rule of the npm and PyPI designs, chosen again by the product owner. An image on a public registry must not stand in for one the team pushed, or add tags to it. |
| D13 | A proxy stores what it fetches in the same layout as a hosted repository. A manifest asked for by tag is checked again with the remote after `metadata_max_age_minutes`; a manifest asked for by digest, and a blob, never change. | One layout for every type, so a group can serve from any member. A digest names content. |

## 4. Changes to the core

### 4.1 For hosted Docker (plan 7a)

- **Registry tokens.** The security package can seal a statement of who signed in (the user, how, and with which API token if any) into a registry token, and read one back within its lifetime. A request's `Bearer` credential may be a registry token as well as an API token. A registry token for nobody stands for the anonymous user, and works only while anonymous access is on.
- **Where a format is served.** A format says whether it is served under `/repository/<name>/` or by the registry API. The content route refuses a repository whose format is not served there.
- **What a file refers to.** Storing a file can record the paths of other files in the repository that it refers to. The context can say which of a set of paths exist, which are still referred to, and what a file refers to; and it can remove a file as maintenance does, without a caller's permission being involved.
- **A lock a format names.** The context can serialise work on something a format names, until the transaction ends, as it already does for a path.
- **Uploads in progress.** The context can begin an upload, append to it, report its size, complete it into staged content, and abandon it. The blob store's backend gains the matching operations on a file in its temporary area.
- **Maintenance a format does.** A format can do periodic maintenance on a repository. The existing maintenance job calls it for every repository, and removes uploads abandoned for a day.
- **A migration**, for what a file refers to and for uploads in progress.

### 4.2 For proxy and group Docker (plans 7b and 7c)

- **A remote that asks for a token.** The remote client can answer a registry's `Bearer` challenge: fetch a token from the realm the challenge names, with the proxy's credentials if it has any, and repeat the request with it. Tokens are remembered in memory until they expire, for at most an hour, and are never stored. A token is kept for the remote and the credential it was fetched for, so every remote signs in for itself and the rules about the sign-in address are applied each time. The realm is an address the remote names, so the PyPI design's D8 applies to it in this form: it must not be an internal address unless the remote is at that host, and it must use HTTPS if the remote does. Unlike a file's address, it is given the credential, because it is where the remote says its users sign in; only a user name and password is sent there, never a stored bearer token. The host a blob is redirected to gets neither the credential nor the token.
- **What a request to a remote accepts.** A fetch can say which media types it accepts, so that a manifest is fetched in the form it was pushed in.
- **Asking without caching.** The proxy engine can fetch a small document into memory, or only ask about it, with everything it does for any fetch: the remote is not asked while it is blocked, a miss is remembered, a failure is recorded. The format reads the document and stores it itself. A miss need not be remembered, for a path that can be found at more than one address.
- **A cached file can record what it refers to**, like a stored one, before what it names has been fetched.

## 5. Names and paths

**Image names.** One or more components separated by `/`. A component is lower-case letters and digits, with single `.`, `_`, `__` or runs of `-` between them. A name is at most 255 characters with its repository.

**Repository names.** A Docker repository's name is the first component of every image's name in it, so it must be a component: a name such as `Images` or `my_.repo`, which other formats accept, is refused when the repository is created.

**Tags.** Letters, digits, `_`, `.` and `-`, not starting with `.` or `-`, at most 128 characters.

**Digests.** `sha256:` and 64 lower-case hexadecimal digits (D10).

**Requests**, under `/v2/`:

| Path | Kind |
| --- | --- |
| (nothing) | The API's base: is this a registry, and am I signed in? |
| `token` | Sign-in (section 6) |
| `_catalog` | The images a caller may read, in every Docker repository |
| `<repository>/<image>/manifests/<tag or digest>` | A manifest |
| `<repository>/<image>/blobs/<digest>` | A blob |
| `<repository>/<image>/blobs/uploads/` | Begin an upload |
| `<repository>/<image>/blobs/uploads/<upload>` | An upload in progress |
| `<repository>/<image>/tags/list` | The tags of an image |
| `<repository>/<image>/referrers/<digest>` | `404` (section 2) |

**Stored paths** are those of D6 and D7.

## 6. Signing in

| Request | Result |
| --- | --- |
| Any request under `/v2/` without credentials | `401`, with `WWW-Authenticate: Bearer realm="<public address>/v2/token",service="<host>"`, and the `scope` the request needs |
| `GET /v2/token` with HTTP Basic credentials | They are checked exactly as on any other route, with the same limits on failed attempts. `200` with a registry token and its lifetime, or `401` |
| `GET /v2/token` without credentials | A registry token for the anonymous user if anonymous access is on. Otherwise `401` |
| `GET /v2/token` with a registry token | `401`. A registry token cannot be traded for another, so none outlives its five minutes |
| A registry token on a route outside `/v2/` | `401`. It stands for a password, and the rest of the API would let it be turned into something that lasts: an API token, or a new password |
| A request with a registry token | The user, roles and API token are loaded again (D4). An expired or unreadable token is `401` with the challenge, and is not counted as a failed attempt: clients fetch a new one as a matter of course |
| A request with Basic credentials or an API token | As on any other route |
| `GET /v2/` with any valid credential | `200` |

Permission is checked on each request, against roles: `read` to pull, `add` to push something new, `edit` to move a tag, `delete` to delete. The `scope` a client asks a token for is not what decides. A caller who is signed in and may not do something gets `403 DENIED`; a caller who is not signed in, or is the anonymous user, gets `401`, so that the client asks for credentials.

The public address is the base URL setting if there is one, otherwise the address of the request. The challenge repeats nothing a client wrote unless it is a host or an image name: its values are quoted, and a header cannot carry every character.

## 7. Hosted Docker

### 7.1 Blobs

| Request | Result |
| --- | --- |
| `HEAD`, `GET` blob | The stored blob, with ranges and `Docker-Content-Digest`, or `404 BLOB_UNKNOWN` |
| `DELETE` blob | `405` (section 2) |

### 7.2 Uploads

| Request | Result |
| --- | --- |
| `POST …/blobs/uploads/` | Begin. `202` with the upload's address in `Location` and `Range: 0-0` |
| `POST …/blobs/uploads/?digest=<digest>` with a body | The whole blob in one request. `201` |
| `POST …/blobs/uploads/?mount=<digest>&from=<image>` | `201` at once if the repository has the blob (D6). Otherwise an ordinary upload begins |
| `PATCH` upload | Append a chunk, streamed to disk. If `Content-Range` is sent, it must start where the upload ends, or `416`. `202` with the new `Range`. An upload takes at most 10,000 chunks; one more is `400 BLOB_UPLOAD_INVALID` |
| `GET` upload | `204` with the `Range` received so far |
| `PUT` upload `?digest=<digest>` | Append the body if there is one, then complete. The content must hash to the digest, or `400 DIGEST_INVALID` and the upload is discarded. `201` with the blob's address |
| `DELETE` upload | Abandon it. `204` |

An upload needs `add`. Completing an upload of a blob the repository already has stores nothing new. An unknown or finished upload is `404 BLOB_UPLOAD_UNKNOWN`, and an upload is finished, for every other request, from the moment one request begins to complete it.

### 7.3 Manifests

`PUT` a manifest, by tag or by digest:

1. The body is at most 4 MiB and is read into memory. It must be JSON with `schemaVersion` 2 and one of four media types: the Docker image manifest and manifest list, and the OCI image manifest and image index. The type is taken from `Content-Type`, or from the manifest's own `mediaType`.
2. Its digest is the SHA-256 of the bytes as sent. If the address names a digest, it must be that one.
3. Everything it refers to must be in the repository: for an image, its configuration and layers as blobs; for a list or index, each platform's manifest under the same image. A layer that lists external addresses (`urls`) need not be there. Otherwise `400 MANIFEST_BLOB_UNKNOWN`, naming what is missing.
4. The manifest is stored under its digest, with what it refers to (D8), unless it is there already.
5. If the address names a tag, the tag is stored, or moved. The facade applies the deployment policy and the `add` and `edit` permissions to the tag's path. A tag that already names this manifest is left as it is: clients push an image again as a matter of course, and that must not fail where tags cannot be moved.

The answer is `201` with `Location` and `Docker-Content-Digest`.

`GET` and `HEAD` return the manifest as it was pushed, with its media type and `Docker-Content-Digest`, by tag or by digest, or `404 MANIFEST_UNKNOWN`.

### 7.4 Tags and the catalog

`GET …/tags/list` answers `{"name": "<repository>/<image>", "tags": [...]}` in order, with `n` and `last` for paging and a `Link` header to the next page. An image with no tags is `404 NAME_UNKNOWN`.

`GET /v2/_catalog` lists `<repository>/<image>` for every image with a tag in every Docker repository the caller may read, with the same paging.

### 7.5 Deleting

| Request | Result |
| --- | --- |
| `DELETE` manifest by digest | The manifest goes, with every tag of that image that names it. Then, for what it referred to: a platform's manifest that has no tag and that no other manifest refers to goes the same way, and a blob that no remaining manifest in the repository refers to is removed. `202` |
| `DELETE` manifest by tag | The tag goes. Nothing else does. `202` |

Both need `delete`. Pushing a manifest and deleting one take the same lock on the repository's references, so a push never ends up referring to a blob a delete has just removed.

**Maintenance**, with the existing periodic job: a blob that no manifest refers to and that has been in the repository for a day is removed; so is an upload that has not been added to for a day. A push that stops half-way leaves nothing behind for longer than that.

## 8. Proxy Docker (plan 7b)

`GET` and `HEAD` only.

| Path | Result |
| --- | --- |
| Manifest by tag | Fetched from the remote and cached, and checked again after `metadata_max_age_minutes`, by asking the remote only for its digest |
| Manifest by digest, blob | Fetched once and cached. Checked against the digest asked for |
| Tags list | The remote's, cached as the tag-keyed manifests are |
| Catalog | The images the proxy has cached |

**The remote.** A registry's address, such as `https://registry-1.docker.io` or `https://ghcr.io`. For Docker Hub, an image name with one component is asked for under `library/`, as Docker does. The remote's token sign-in is done by the remote client (section 4.2), with the proxy's configured credentials if it has any.

A manifest is read before it is stored: what is not one of the four kinds, or is not the manifest whose digest was asked for, is not kept and is answered `502`. It is stored with what it refers to, as on a hosted repository, so that maintenance treats cached blobs the same way: a blob no kept manifest refers to is removed after a day, and fetched again when it is asked for.

**A tag** is refreshed by asking the remote about it (`HEAD`), which registries that count pulls do not count. If the digest it reports is the one held, nothing is fetched. A remote that reports no digest is asked for the manifest itself. While the remote cannot be asked, or once it has dropped the tag, what is held is served. So it is when the remote says the tag names something else and then does not give that manifest, which is what a registry that counts pulls does once the count is used up: asking still works, fetching does not. A manifest that a tag has just been said to name is not remembered as missing.

**A blob** is not remembered as missing: another image of the remote may have the one this image has not. `HEAD` for a blob that is not held asks the remote and fetches nothing.

**A refusal** (`401` or `403`) from the remote for an image is answered `404`: a registry says the same of an image it does not have as of one it will not show. A sign-in address that refuses the repository's credential is another matter, a fault of the whole proxy, and is answered `502` with that reason.

The remote's tag list is read page by page, up to 100 pages and 100,000 tags, and kept as one list under `lists/<image>`.

## 9. Group Docker (plan 7c)

`GET` and `HEAD` only.

**Who answers for an image** follows D12, by the rule in the group engine: the repositories behind the group in the order they are tried, nested groups replaced by their members. If a hosted repository has a tag of the image, hosted repositories alone answer for it; if every one that has it is offline, the answer is `503`. Otherwise the online proxies answer.

| Path | Result |
| --- | --- |
| Manifest, blob | The first repository that has it, among those that answer for the image |
| Tags list | The tags of every repository that answers for the image, each once, in order |
| Catalog | Every image the repositories behind the group hold, each once |

## 10. Configuration and errors added

No setting is added. One migration (section 4.1).

Errors under `/v2/` carry the registry's codes: `UNAUTHORIZED`, `DENIED`, `NAME_UNKNOWN`, `NAME_INVALID`, `MANIFEST_UNKNOWN`, `MANIFEST_INVALID`, `MANIFEST_BLOB_UNKNOWN`, `BLOB_UNKNOWN`, `BLOB_UPLOAD_UNKNOWN`, `BLOB_UPLOAD_INVALID`, `DIGEST_INVALID`, `SIZE_INVALID`, `TAG_INVALID`, `UNSUPPORTED`, `TOOMANYREQUESTS` and `UNKNOWN`. An error raised by the core in MegooArti's own shape is given the code that fits its status.

## 11. Code structure

Under `backend/src/megooarti/`:

| File | Responsibility |
| --- | --- |
| `security/registry_tokens.py` | Seal and read a registry token |
| `security/authentication.py` | Grant a registry token for a request's credentials; accept one as a `Bearer` credential |
| `repositories/docker/names.py` | Image names, tags, digests; classify a path. Pure functions |
| `repositories/docker/manifests.py` | Read a manifest; what it refers to. Pure functions |
| `repositories/docker/errors.py` | The registry's error shape and codes |
| `repositories/docker/routes.py` | The routes under `/v2/`: the base, sign-in, the catalog, and requests to a repository |
| `repositories/docker/format.py` | The `DockerFormat` class and its handlers. The only Docker file that touches the context |
| `repositories/uploads.py`, `upkeep.py`, `content.py`, `models.py`, `formats.py`, `routes.py`, `storage/backends.py`, `secrets_box.py`, `main.py` | The core changes of section 4 |

## 12. Testing

- **Pure functions** are tested directly: names, tags, digests and path classification; manifests of each of the four kinds and what they refer to, and what is refused.
- **Signing in** is tested through the HTTP API: the challenge, a token for a password and for an API token, a token that has expired or been altered, a user disabled and a token revoked after the registry token was issued, the anonymous user with anonymous access on and off, and the limits on failed attempts.
- **Each repository type** is tested through the HTTP API: every row of the tables above, each permission alone, the deployment policy on tags, and every step of a push as Docker makes it, in chunks, resumed, out of order and abandoned.
- **Deleting and maintenance** are tested for what goes and what stays: a layer two images share, an image with several platforms, a blob never referred to, an upload abandoned.
- **Races** use real transactions: two chunks to one upload, a push and a delete that share a layer.
- **Real clients**, in the Docker-marked suite:
  - *Plan 7a:* the Docker client and daemon sign in, build a small image from nothing, push it, remove it locally, pull it and read its file back out of it; push it again under another tag; pull without signing in what the anonymous user may read; and are refused when they should be. A second client that uses Podman's image library copies an image with several platforms to the repository and back, and compares it. A deleted image's layers are gone from the repository.
  - *Plan 7b:* an image is pulled through a proxy of Docker Hub and run, and one through a proxy of registry.k8s.io; both are listed; with the remote blocked the image is pulled again from what was kept; a push to the proxy is refused.
  - *Plan 7c:* images are pulled through a group, and an image pushed under a name the public registry also has is the one served.

## 13. Risks

| Risk | Response |
| --- | --- |
| Docker clients refuse plain HTTP to any host but `localhost`. | MegooArti is put behind HTTPS for clients on other machines, as for Maven. The README says so. |
| The registry must be at the root of a host, at `/v2/`. A deployment under a path prefix cannot serve Docker. | The README says so. A dedicated host name (FMT-6) is the Phase 2 answer for sites that need one. |
| A registry token is valid for five minutes even if the password it was obtained with is changed. | The user's status, roles and API token are checked on every request (D4), so a disabled user or a revoked token is refused at once. A changed password is not, for at most five minutes. |
| Sealing uses the key that seals remote credentials. Losing it invalidates registry tokens in flight. | They last five minutes; clients fetch new ones. |
| Deleting an image removes layers while a push that relies on one of them is in flight. | The push and the delete take the same lock. The push is then refused with `MANIFEST_BLOB_UNKNOWN`, and the client's retry uploads the layer again. |
| An image with a platform manifest or a layer that never arrives leaves blobs behind. | Maintenance removes what nothing refers to after a day. |
| Completing an upload reads the whole layer again to hash it. | It is one sequential read of a file just written, and no copy for a layer sent in one request. Hashing as the chunks arrive would not survive a chunk reaching another container. |
| A chunk arrives for an upload while another request completes it, in the same container or another. If it could reach the file being hashed, a blob would be stored under a digest its bytes do not match, for every repository that shares the blob store. | A chunk is a file of its own that joins the upload only when it is whole, and is never written again; completing takes the upload's row and its files before reading them (D9). The late chunk is refused, and is removed by maintenance. |
| A manifest that lost its tag stays for ever unless it is deleted by digest. | That is what pinning by digest needs. Cleanup by age is Phase 2. |
| One repository's images share layers, so a caller who may read a repository can fetch any layer in it by digest. | Permissions are for a repository. Content selectors, in Phase 2, will need blobs tied to images. |

## 14. Requirement coverage

| Requirement | Where |
| --- | --- |
| FMT-4 hosted, proxy and group | Sections 7, 8, 9 |
| FMT-4 the registry API, chunked upload, manifest lists | Sections 5, 7.2, 7.3 |
| FMT-4 token authentication | D3, D4, section 6 |
| FMT-4 Docker, Podman and containerd | Section 12 |
| FMT-5 addressed by path | D1 |
| FMT-7 anonymous pull for a repository | D5 |
| REP-12 metadata merged across a group | Section 9 (tags lists) |
| SEC-9 a token wherever a password is accepted | Section 6 |
| NFR-1 compatibility tested with real clients | Section 12 |
