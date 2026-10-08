# npm Format — Technical Design

| | |
| --- | --- |
| **Status** | Draft for review |
| **Date** | 2026-10-08 |
| **Implements** | [BRD](../../BRD.md): FMT-2, REP-12 (npm), SEC-9 (`npm login`), NFR-1 (npm, pnpm, Yarn), and the npm part of REP-1 to REP-11 |
| **Builds on** | [Storage and repositories design](2026-10-07-storage-repositories-design.md), [Maven format design](2026-10-08-maven-format-design.md) (the engine hooks, `ensure_cached`, `maintain`) |
| **Series** | Plans 5a and 5b of Phase 1 |

## 1. Purpose

Make MegooArti an npm registry: somewhere to publish a team's own packages, a cache in front of registry.npmjs.org, and one URL that presents both.

Success means:

- `npm publish`, `npm install`, `npm view`, `npm dist-tag`, `npm deprecate` and `npm unpublish` work against a hosted repository with no client-side workaround.
- `npm install`, `pnpm install` and `yarn install` build a project whose dependencies all arrive through a group made of a hosted repository and a proxy of registry.npmjs.org.
- `npm login` gives the client a personal API token, and `npm logout` revokes it.
- A public package cannot take over a name the team has published privately.

## 2. Scope

One design, delivered as two plans.

| Plan | Contents |
| --- | --- |
| **5a** | Core changes (section 4.1); npm paths and version order; hosted npm: publish, package documents, dist-tags, deprecate, unpublish; sign-in endpoints; search; real `npm` tests against a hosted repository |
| **5b** | Core change for rewritten responses (section 4.2); npm proxy; npm group; real `npm`, `pnpm` and `yarn` installs through a group |

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| Abbreviated package documents (`application/vnd.npm.install-v1+json`) | A later optimisation. Clients get the full document, which npm, pnpm and Yarn accept |
| `npm audit` endpoints | Not planned for Phase 1. Installs succeed without them |
| Web login (`/-/v1/login`), two-factor prompts, `npm token`, `npm owner`, `npm access`, `npm star` | Not planned. npm falls back to the classic login when web login is absent |
| A remote that serves tarballs outside the standard path (GitHub Packages) | Later, if wanted |
| Forwarding search to the remote | Not planned: search answers from what MegooArti holds |
| Usage snippets, README rendering, search by keyword | Plan 8 |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | `npm login` is supported through the classic endpoint. It checks a user name and password exactly as HTTP Basic credentials are checked, and returns a personal API token. | The BRD requires it (FMT-2, SEC-9), and it is how most developers set up a workstation. |
| D2 | In a group, if any hosted member has a package, only hosted members answer for that package: its document and its tarballs. A hosted member that is offline still counts. | npm's namespace is flat and unverified. Merging a proxy's versions into a private name is the dependency-confusion attack, and so is serving a proxy's tarball for a version of it. |
| D3 | A publish is read into memory, up to a configured limit, and at most two are decoded at once. | The client sends the tarball base64-encoded inside one JSON document, so it cannot be streamed to disk. A limit makes the cost bounded. |
| D4 | On a hosted repository, the package document is generated on each request from the versions stored. Each version's manifest is stored on its component at publish. | The same reason as Maven's metadata: it cannot go stale or lose a version to a concurrent publish. |
| D5 | A proxy serves the remote's package document with tarball links rewritten by a streaming, byte-level substitution. It is never parsed. | These documents reach tens of megabytes. Parsing one costs hundreds of megabytes of memory per request. |
| D6 | The full package document is always served, whatever form the client asks for. | One form to generate, cache and merge. The short form is a later optimisation. |
| D7 | A published tarball must match the `shasum` and `integrity` its manifest declares. The stored manifest carries the values MegooArti computed. | A corrupted publish fails at once, and what is served can always be verified. |
| D8 | Search answers from the components MegooArti holds, matching on package name. | It is predictable, works offline, and matches what the browse API of plan 8 will show. |
| D9 | The sign-in endpoints work on every repository type. Everything that changes a package works only on hosted repositories. | Developers point npm at the group. They publish to the hosted repository. |

## 4. Changes to the core

### 4.1 For hosted npm (plan 5a)

- **Credentials in the request body.** Today the content route refuses any write without credentials before format code runs. A format can now name requests that carry credentials in their body; the route lets exactly those through without a principal. The npm format names one: `PUT -/user/org.couchdb.user:<name>`. The handler must not use the principal, and checks the credentials through the security package. For such a request the route does not look at whatever credentials a header or cookie carries, valid or not: npm sends its saved token with every request, and a token that has been revoked must not stop the next sign-in or count as a failed attempt. The route therefore receives the request's credentials unchecked, and checks them itself for every other request.
- **Signing a client in.** One function in the security package now checks a user name and a secret, for HTTP Basic and for everything else. On it the package gains two operations, reached through the context so that a format never handles the session:
  - *Issue a token:* check a user name and secret exactly as HTTP Basic credentials are checked, including throttling of failures, and refuse a user who must change their password. If the secret is itself one of the user's API tokens, return it; otherwise create a personal API token and return its value.
  - *Revoke a token:* revoke the token with a given value, only if it belongs to the caller.
- **Component attributes.** `store` can set attributes on the component a file belongs to. New read operations list a package's components with their attributes and times, and find package names matching a text. A new operation changes a component's attributes; it needs `edit` and refuses a read-only repository.
- **A response with its own `ETag`.** A response built in memory can supply its `ETag`, and is then not hashed. Such a response carries no `X-Checksum-*` headers.
- **The public address.** One helper gives the address clients use to reach a repository: the `base_url` setting if it is set, otherwise the address of the current request.
- **A size limit that says so.** A new error, `413 payload_too_large`. `maintain` answers with it rather than store a document larger than the limit it reads with.
- **A token in an address is not logged.** `npm logout` puts the token it revokes in the address. The request log and the error log write such an address with the token removed.

### 4.2 For proxy and group npm (plan 5b)

- **A stored file served through a transformation.** The context can stream a stored file through a function that rewrites it chunk by chunk. The response has the same protective headers as any content, an `ETag` derived from the file's hash and a name for the transformation, no `Content-Length`, and no ranges. Conditional requests and `HEAD` work.
- **Every repository behind a group.** The group engine can list the hosted and proxy repositories behind a group, through nested groups, in the order they are tried, each marked online or offline. A format that answers from all of them at once uses it.
- **Package names across repositories.** The search for package names can cover several repositories and lists a package once.

## 5. npm paths

A request path is classified before anything else. A package name is `name` or `@scope/name`; npm sends the latter as `@scope%2Fname`, which arrives decoded.

| Path | Kind |
| --- | --- |
| `<package>` | Package document |
| `<package>/-rev/<rev>` | Package document, for updates and removal |
| `<package>/<version or tag>` | One version's manifest |
| `<package>/-/<file>.tgz`, optionally followed by `/-rev/<rev>` | Tarball |
| `-/package/<package>/dist-tags`, optionally followed by `/<tag>` | Dist-tags |
| `-/user/org.couchdb.user:<name>`, optionally followed by `/-rev/<rev>` | Sign-in |
| `-/user/token/<token>` | Sign-out |
| `-/whoami`, `-/ping`, `-/v1/search` | As named |
| Anything else | `404` |

**Names.** Each part of a name is made of letters, digits, `.`, `_`, `~` and `-`, does not start with `.` or `_`, and the whole name is at most 214 characters. A hosted repository also requires lower case for a new package, as npm does. A proxy accepts upper case, for old packages.

**Tarballs.** A tarball's file name is the name without its scope, a hyphen, the version, and `.tgz`. Its component has the scope (without `@`) as namespace, the name without its scope as name, and that version.

**Stored paths.** A tarball is stored at its request path. A proxy stores the remote's package document at `<package>`. A hosted repository keeps a package's dist-tags in a server-maintained document at `-/package/<package>/dist-tags`.

### 5.1 Version order

`latest` falls back to the highest version, and versions are listed in order, by Semantic Versioning 2.0 precedence. A version that is not valid SemVer sorts before every valid one.

## 6. Hosted npm

| Request | Result |
| --- | --- |
| `GET`, `HEAD` package document | The generated document (6.2), or `404` |
| `GET` version or tag | That version's manifest, or `404` |
| `GET`, `HEAD` tarball | The stored file, or `404` |
| `PUT` package document with `_attachments` | Publish (6.1) |
| `PUT` package document without `_attachments` | Update (6.4) |
| `DELETE` package document (`…/-rev/<rev>`) | Remove every version (6.4) |
| `DELETE` tarball | Remove that version (6.4) |
| `GET`, `PUT`, `DELETE` dist-tags | Section 6.3 |

### 6.1 Publish

The body is read with `receive`, up to `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` (default 100 MiB); a larger one is `413 payload_too_large`, from its `Content-Length` alone when it declares one. At most two publishes are read, decoded and stored at once; others wait their turn. Decoding runs on two worker threads of its own.

JSON that could not be stored is refused as `400 invalid_package` before anything else happens: `NaN` and the infinities, a NUL character, and half of a surrogate pair. The same applies to every JSON body these endpoints read.

The document is refused with `400 invalid_package` unless all of these hold:

- Its `name` is the package in the path, and a valid name.
- Every key of `versions` is valid SemVer, and that manifest's `name` and `version` agree with it.
- Every version has an attachment named as section 5 describes, whose `data` is valid base64.

Each tarball is then checked against its manifest: its length against `length`, its SHA-1 against `dist.shasum`, and its SHA-512 against `dist.integrity`, for whichever are given. A mismatch is `400 checksum_mismatch`.

Everything is staged first, then stored in one transaction: each tarball with its manifest as the component's attributes, and the document's `dist-tags` merged into the stored ones. The manifest is stored without `dist.tarball`, and with `dist.shasum` and `dist.integrity` as MegooArti computed them.

Storing goes through the facade, so `add`, `edit` and the deployment policy apply as for any file: publishing a version that exists is `409 redeploy_disabled`, or replaces it under `allow_redeploy`.

The answer is `201` with `{"ok": true, "id": <name>, "rev": <rev>}`.

### 6.2 The package document

Built from the package's components:

- `_id`, `name`.
- `versions`: each stored manifest, with `_id` and `dist.tarball` added. The link is the repository's public address followed by the tarball's path.
- `dist-tags`: the stored tags that point at a version that exists. If none is `latest`, `latest` is the highest version.
- `time`: `created`, `modified`, and when each version was published.
- `description`, `readme`, `license`, `repository`, `homepage`, `keywords`, `author`, `maintainers` and `bugs`, copied from the `latest` version's manifest. The `readme` is shown only here, not again with every version.
- `_rev`: a value that changes whenever the document does. An update must carry the current one (6.4).

If the package has no version, the answer is `404`. The `ETag` is the hash of the document. `Last-Modified` is `time.modified`.

### 6.3 Dist-tags

| Request | Result |
| --- | --- |
| `GET -/package/<package>/dist-tags` | The tags, as in the package document |
| `PUT …/dist-tags/<tag>` with a version as a JSON string | Sets the tag. The version must exist. `200` |
| `DELETE …/dist-tags/<tag>` | Removes the tag. `latest` cannot be removed. `200` |

Changes go through `maintain`, so they need `add` or `edit`, are refused on a read-only repository, and never overwrite each other. A package has at most 250 dist-tags. On a proxy or a group these requests are `405`.

### 6.4 Update, deprecate and unpublish

`npm deprecate` and `npm unpublish` both read the package document, change it, and send it back without attachments. Such an update needs `add` or `edit` before its body is read, as any upload does.

An update that changes anything must carry the `_rev` of the document as it is now; otherwise it is `409 conflict` and nothing changes. The client sends the whole document back, so one read before somebody else's publish would otherwise remove that publish. An update that names a version that is not stored is `400 invalid_package`, and so is a body whose `_attachments` is present but empty: both are a publish gone wrong.

The server then compares what it receives with what it holds:

- **A version whose `deprecated` text differs:** the stored manifest is changed. This needs `edit`.
- **A stored version missing from `versions`:** its tarball is deleted, which removes the version. This needs `delete`. Nothing is removed if the body has no `versions` at all.
- **`dist-tags`:** replace the stored tags, keeping only those that point at a version that still exists.

A tag that points at a version removed some other way is not rewritten; it is ignored wherever tags are read, and dropped at the next change.

Nothing else in the body is applied.

`DELETE` of a tarball removes that version, and answers `200` even if it is already gone, because npm deletes the tarball after removing the version from the document. `DELETE` of the package document removes every version and the dist-tags. Both need `delete`.

If the version `latest` pointed at is removed, `latest` becomes the highest version that remains.

## 7. Signing in

These work on hosted, proxy and group repositories alike (D9).

| Request | Result |
| --- | --- |
| `PUT -/user/org.couchdb.user:<name>` with `{"name", "password"}` | Issues a token (4.1). `201` with `{"ok": true, "id", "token"}`. Wrong credentials are `401`; too many failures `429` |
| `DELETE -/user/token/<token>` | Revokes that token if it is the caller's. `200` |
| `GET -/whoami` | `{"username": <the caller>}` |
| `GET -/ping` | `{}` |

The sign-in body is limited to 16 KiB. A token created this way is named `npm login` with the time, has no expiry and no narrowed scope, and appears in the user's token list like any other, where it can be revoked.

`-/whoami` and `-/ping` are `GET` requests, so they need `read` on the repository like any other read.

`POST -/v1/login` is not implemented and answers `404` (or `401` without credentials), which makes npm fall back to the classic login.

## 8. Search

`GET -/v1/search?text=…&size=…&from=…` answers in npm's format: `objects`, each with a `package` holding `name`, `version` (the highest held), `description` and `date`; and `total`.

A package matches if `text` appears in its name or scope. `size` is at most 250. A hosted repository takes the description from the manifest; a proxy has none to give, and lists the packages it has cached a tarball of. A group lists every package its online members hold, once, ordered by name; a package's version and description come from a hosted member if one holds it.

## 9. Proxy npm (plan 5b)

`GET` and `HEAD` only, apart from the sign-in endpoints.

| Path | Result |
| --- | --- |
| Package document | `ensure_cached` for the package, then the cached document streamed through the link rewriter (below). Checked again with the remote after `metadata_max_age_minutes` |
| Tarball | The generic proxy behaviour, fetched from `<remote>/<package>/-/<file>` and checked again after `content_max_age_minutes` |
| Version manifest, dist-tags | `405` |
| Search | Section 8 |

The package document is requested from the remote at `<remote>/<name>`, or `<remote>/@scope%2Fname` for a scoped package.

**The link rewriter.** Every `"tarball": "<any address>/-/<file>.tgz"` in the document becomes `"tarball": "<public address of this repository>/<package>/-/<file>.tgz"`. It works on the bytes as they stream, holding back only enough to recognise a link split across two chunks. A JSON string cannot contain an unescaped quote, so the pattern cannot match inside a README. A link written with escaped slashes is left as it is, and the client then fetches that tarball from the remote directly.

## 10. Group npm (plan 5b)

`GET` and `HEAD` only, apart from the sign-in endpoints.

| Path | Result |
| --- | --- |
| Tarball | The first member that has it, among the members that answer for its package (below) |
| Package document | Below |
| Search | Section 8 |
| Version manifest, dist-tags | `405` |

**Who answers for a package.** The repositories behind the group are taken in the order they are tried, with a nested group replaced by its own members. A hosted repository has the package if it holds a version of it; a proxy has it if `ensure_cached` succeeds for its document. A proxy that is offline or cannot answer is left out, as in the Maven design.

- **A hosted repository has it (D2):** only hosted repositories answer, and proxies are not asked. If every hosted repository that has it is offline, the answer is `503 repository_offline`: the remote's package of the same name must not stand in for it.
- **No hosted repository has it:** the online proxies answer.

**The document.**

- **From hosted repositories:** the documents of those that have it are merged. Versions are the union, the earlier one winning a version both hold. Dist-tags are the union, the earlier one winning a tag, and `latest` is recomputed if the version it names is not in the result.
- **From one proxy:** that proxy's cached document is streamed through the link rewriter, with the group's address in the links.
- **From several proxies:** their documents are parsed and merged in the same way, up to 16 MiB together and two merges at a time. They are read in the order the proxies are tried, and reading stops at the first that does not fit: it and those after it are left out, so a later proxy's document never stands in for an earlier one's. One that is not a package document is left out too. Both are logged. If that leaves fewer than two, one document is streamed as above.
- **Nobody has it:** `404`.

Tarball links always name the group, so every download goes through the group. A tarball is served by the first repository that has it: among the hosted repositories if one of them has the package, otherwise among all the online proxies, whether or not a proxy's document for the package could be fetched. So a proxy listed before a hosted repository cannot serve its own file for a version the hosted repository published.

## 11. Configuration and errors added

| Setting | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` | `104857600` | Largest `npm publish` request accepted |

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_package` | Section 6.1; a body that is not the JSON these endpoints expect |
| 413 | `payload_too_large` | Section 6.1 |

`checksum_mismatch`, `redeploy_disabled`, `repository_read_only`, `not_found`, `method_not_allowed` and `unauthorized` are used as already defined.

There is no migration: components already have attributes.

## 12. Code structure

Under `backend/src/megooarti/`:

| File | Responsibility |
| --- | --- |
| `repositories/npm/paths.py` | Classify a path; package names; tarball file names. Pure functions |
| `repositories/npm/semver.py` | SemVer parsing and order. Pure functions |
| `repositories/npm/documents.py` | Check a publish body; build and merge package documents; dist-tag rules; search results. Pure functions |
| `repositories/npm/rewrite.py` | The streaming link rewriter. Pure |
| `repositories/npm/format.py` | The `NpmFormat` class and its handlers. The only npm file that touches the context |
| `security/client_login.py` | Issue and revoke a token for a package client |
| `repositories/content.py`, `formats.py`, `routes.py`, `serving.py` | The core changes of section 4 |

## 13. Testing

- **Pure functions** are tested directly: path classification, SemVer order against the specification's examples, publish-body checks, document building and merging, and the link rewriter with every way of splitting a link across chunks.
- **Each repository type** is tested through the HTTP API with the existing fixtures and the fake remote: every row of the tables above, permissions for each kind of change, and the sign-in endpoints including throttling.
- **Races** use real transactions: two versions published at once, and two dist-tag changes at once.
- **Real clients**, in the Docker-marked suite, which needs internet access:
  - *Plan 5a:* npm in a container publishes an unscoped and a scoped package, then runs `view`, `install`, `dist-tag`, `deprecate` and `unpublish` against a hosted repository, using a token obtained from the sign-in endpoint.
  - *Plan 5b:* npm, pnpm and Yarn 1 each install a project, from an empty cache, through a group of the hosted repository and a proxy of registry.npmjs.org. The project depends on a package published to the hosted repository and on one small public package. A package published under a name the public registry also has is listed through the group with our version only.

`npm login` prompts on a terminal. The tests send the same request npm sends and then use the token with the real client. If the client can be driven without a terminal, the test uses it directly.

## 14. Risks

| Risk | Response |
| --- | --- |
| The one unauthenticated write is a new way in. | The route lets through one exact method and path shape. The handler does nothing but hand the body to the same credential check as HTTP Basic, with the same throttling, and the body is limited to 16 KiB. |
| Every `npm login` creates a token that never expires. | Tokens are listed and revocable per user and by an administrator. `npm logout` revokes its own. An expiry policy can be added to the token settings later. |
| A publish holds up to three times its size in memory while it is decoded. | The limit bounds one publish, and two workers bound how many are decoded at once. |
| A team needs its own build of a public package alongside the public versions (D2 hides them). | Publish it under a scope. A per-group switch can be added if this proves common. |
| Taking a hosted repository offline makes the packages it holds unavailable through its groups (`503`), where a Maven group would answer from the other members. | That is D2 holding while the repository is away. The message says which state causes it. |
| The link rewriter misses a link in an unusual document. | The client fetches that tarball from the remote directly. Nothing breaks, but that download bypasses the cache. |
| Clients always receive full package documents, so a first install transfers more. | It is correct for all three clients, and they revalidate with `ETag` afterwards. Serving the short form is a later optimisation. |
| Search over many components is a scan. | Plan 8 builds the search index; this endpoint will use it. |

## 15. Requirement coverage

| Requirement | Where |
| --- | --- |
| FMT-2 hosted, proxy and group | Sections 6, 9, 10 |
| FMT-2 scoped packages | Section 5 |
| FMT-2 dist-tags | Section 6.3 |
| FMT-2 `npm login` | D1, section 7 |
| FMT-2 `npm publish`, `unpublish`, `deprecate` | Sections 6.1, 6.4 |
| FMT-2 package search | Section 8 |
| FMT-2 works with npm, pnpm and Yarn | Section 13 |
| REP-12 package documents merged across a group | Section 10 |
| SEC-9 a token wherever a password is accepted | Section 4.1 |
| NFR-1 compatibility tested with real clients | Section 13 |
