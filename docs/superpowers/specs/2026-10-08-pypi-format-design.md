# PyPI Format — Technical Design

| | |
| --- | --- |
| **Status** | Draft for review |
| **Date** | 2026-10-08 |
| **Implements** | [BRD](../../BRD.md): FMT-3, REP-12 (PyPI index pages), SEC-9 (a token wherever a password is accepted), NFR-1 (twine, pip, uv, Poetry), and the PyPI part of REP-1 to REP-11 |
| **Builds on** | [Storage and repositories design](2026-10-07-storage-repositories-design.md), [Maven format design](2026-10-08-maven-format-design.md) (the engine hooks, `ensure_cached`), [npm format design](2026-10-08-npm-format-design.md) (the repositories behind a group, the rule for a name a hosted repository holds) |
| **Series** | Plans 6a and 6b of Phase 1 |

## 1. Purpose

Make MegooArti a Python package index: somewhere to upload a team's own distributions, a cache in front of pypi.org, and one URL that presents both.

Success means:

- `twine upload` publishes to a hosted repository, and `uv publish` and `poetry publish`, which send the same request, do too.
- `pip install`, `uv pip install` and `poetry install` build a project whose dependencies all arrive through a group made of a hosted repository and a proxy of pypi.org.
- An API token works the way Python tools expect: as the password, with the user name `__token__`.
- A public package cannot take over a name the team has published privately.

## 2. Scope

One design, delivered as two plans.

| Plan | Contents |
| --- | --- |
| **6a** | Core changes (section 4.1); PyPI names, paths and file names; index pages; the upload form; hosted PyPI; real `twine`, `uv publish` and `pip` tests against a hosted repository |
| **6b** | Core changes (section 4.2); reading a remote's index page; PyPI proxy; PyPI group; real `pip`, `uv` and Poetry installs through a group |

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| The JSON index (PEP 691) | A later optimisation. Every client reads the HTML index, and falls back to it when it asked for JSON |
| Metadata files (PEP 658) for files uploaded to a hosted repository | Later. A proxy passes the remote's through (section 8) |
| Yanking a release on a hosted repository (PEP 592) | Plan 8, with the browse API. No client command does it. A proxy passes the remote's marks through |
| `pip search` and the XML-RPC API | Not planned. pypi.org itself switched them off |
| The JSON project API (`/pypi/<project>/json`) | Not planned. Installers do not use it |
| Signatures (`.asc` files), attestations (PEP 740), trusted publishing | Not planned for Phase 1. An uploaded signature is accepted and discarded |
| Usage snippets, README rendering, search | Plan 8 |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | In a group, if a hosted member has a project, only hosted members answer for it: its index page and its files. A hosted member that is offline still counts. | The rule of the npm design (its D2). Python's namespace is flat and unverified, and this is where dependency confusion was first exploited. |
| D2 | HTTP Basic credentials with the user name `__token__` and an API token as the password authenticate as the token's owner, for every format. `__token__` cannot be a user's name. | It is what `uv publish --token`, Poetry's `pypi-token` and twine's documentation do. The real user name with a password or a token keeps working. |
| D3 | The HTML index (PEP 503) is the only index served, with the `data-requires-python`, `data-yanked` and metadata attributes. | pip, uv and Poetry all read it. One form to generate, read and merge. |
| D4 | A hosted repository generates a project's index page on each request from the files stored. | The reason of Maven's metadata and npm's documents: it cannot go stale or lose a file to a concurrent upload. |
| D5 | An upload is streamed to the blob store as it arrives. It is never held in memory or in a second temporary file, and has no size limit of its own. | Wheels reach gigabytes. Raw and Maven uploads are streamed and unlimited too. |
| D6 | Links in every index page are relative (`../../packages/...`). A project page is served only at its one address, `simple/<normalised name>/`; other spellings redirect there. | A page is then the same whatever host or proxy prefix the client used, so nothing depends on the base URL and its `ETag` is the same for everyone. |
| D7 | A proxy does not serve the remote's page. It reads the links out of it as it streams and writes its own page from them. | The remote's links point elsewhere, often at another host, and a page built here carries nothing the remote wrote but file names, hashes and four known attributes. |
| D8 | A proxy fetches a file from the address the remote's page gives for it, and checks it against the hash on the page. The remote's credentials are sent only to the remote's own origin. A file address on a loopback, link-local or private network is refused unless the remote itself is at that host. | pypi.org keeps its files on another host. The page is written by the remote, so what it points at is not trusted to be the same place, or a safe one. |
| D9 | A file is stored at `packages/<project>/<version>/<file name>` in every repository type, and the version is the one read from the file name. | One address for a file name wherever it is, so a group can serve it from any member, and so that the deployment policy and the `add` and `edit` permissions apply to a file name whatever version an upload declares. The layout is the one Nexus users know. |
| D10 | The root index (`simple/`) lists the projects a repository holds. A proxy lists the projects it has cached a file of, not the remote's. | pypi.org's list is tens of megabytes and installers never ask for it. |

## 4. Changes to the core

### 4.1 For hosted PyPI (plan 6a)

- **`__token__`.** The one function that checks a name and a secret accepts the name `__token__` with an API token, and looks the user up by the token alone. `__token__` with anything that is not a token is a failed attempt, counted as any other. Creating a user named `__token__` is refused.
- **A token where the name belongs.** An index address written as `https://<token>@host/` sends the token as the user name. A name shaped like a token is nobody's: it is refused as a failed attempt counted against the address only, it is not logged or stored, and no user can be given such a name.
- **The files of a package.** A new read operation lists every file of every version of a package in one query: its path, size, hash, the time it changed, what is recorded about the file itself, and its component's version and attributes.
- **What is recorded about a file.** Storing a file can record attributes of the file itself, beside those of its component. A page says what each file requires, and two files of one version need not agree.
- **A request for the repository itself** (`POST /repository/<name>/`) already reaches the format with an empty path, and the generic format answers `400 invalid_path` for it. Nothing changes there.
- **A dependency:** `python-multipart`, for reading an upload form as it streams.

### 4.2 For proxy and group PyPI (plan 6b)

- **Fetching from a given address.** `ensure_cached` can be told where a path is found on the remote, and what hash the content must have, instead of deriving the address from the path. The rules of D8 are enforced there: credentials only to the remote's origin, no internal address unless it is the remote's host, and content that does not match its hash is not cached (`502`).
- **A response made from several stored files.** The context can give the bytes of a stored file as a stream, and can answer a `GET` or `HEAD` with a stream whose `ETag` the caller supplies. Like a transformed response, it declares no length and serves no ranges.
- **Who holds a name behind a group.** The rule of D1 moves from the npm format into the group engine, so that npm and PyPI apply the same code.

## 5. Names, paths and files

**Names.** A project name is letters, digits, `.`, `_` and `-`, starting and ending with a letter or digit. Its normalised form (PEP 503) is lower case with every run of `.`, `_` and `-` replaced by one `-`. Components are keyed by the normalised name, with an empty namespace.

**Paths.** A request path is classified before anything else. One trailing slash is ignored.

| Path | Kind |
| --- | --- |
| (empty) | The repository itself: uploads go here |
| `simple` | Root index |
| `simple/<project>` | Project page |
| `packages/<project>/<version>/<file name>` | File |
| `packages/<project>/<version>/<file name>.metadata` | That file's metadata (PEP 658) |
| Anything else | `404` |

`<project>` in a file path is always the normalised name. A version and a file name are made of letters, digits, `.`, `_`, `+`, `!` and `-`.

**File names.** The version a file belongs to is read from its name, given its project:

- A wheel is `<name>-<version>-<tags>.whl`, at least five parts separated by hyphens; the name part must normalise to the project.
- Anything else is `<name>-<version><extension>`: the longest prefix that normalises to the project is the name, and what follows the hyphen is the version. For the old binary kinds (`.egg`, `.exe`, `.msi`) the version ends at the next hyphen.

A file whose name does not fit its project is not part of it: a hosted repository refuses the upload, and a proxy leaves it off the page. pip ignores such files too.

**Stored paths.** A file is stored at its request path. A proxy stores the remote's project page at `simple/<project>`.

## 6. Index pages

Every page is HTML5, declares `pypi:repository-version` `1.0`, and is served as `text/html` with the protective headers of any content.

**Root index.** One link for each project, `<a href="<project>/"><project></a>`, in name order.

**Project page.** One link for each file:

```html
<a href="../../packages/<project>/<version>/<file name>#sha256=<hash>" data-requires-python="&gt;=3.9"><file name></a><br>
```

The fragment names the hash a client checks the download against. `data-requires-python` is present when the file declares it, HTML-escaped. `data-yanked`, `data-core-metadata` and `data-dist-info-metadata` are present where a remote's page has them (section 8); a hosted repository does not produce them.

**Redirects.** `simple` without its slash, a project page without its slash, and a project name that is not normalised each answer `301` with a relative `Location` to the one address (D6).

## 7. Hosted PyPI

| Request | Result |
| --- | --- |
| `POST` to the repository | Upload (7.1) |
| `GET`, `HEAD` root index | The projects held |
| `GET`, `HEAD` project page | Generated from the files stored (D4), or `404` if there are none |
| `GET`, `HEAD` file | The stored file, with ranges, or `404` |
| `DELETE` file | Remove it. Needs `delete` |
| File metadata (`.metadata`) | `404` |
| Anything else | `405`, or `404` for an unknown path |

### 7.1 Upload

The client sends `multipart/form-data` with the fields of the legacy upload API: `:action` (`file_upload`), `name`, `version`, `filetype`, the file as `content`, digests, and the rest of the package's metadata.

1. The caller needs `add` or `edit`, and the repository must not be read-only. This is checked before the body is read.
2. The body is read as it arrives (D5). The file part goes straight to the blob store's staging area. Of the other fields only those used are kept, each up to 4 KiB; the rest are read past. A form with more than 10,000 parts is refused.
3. Checks, each answering `400 invalid_package`: the action is `file_upload`; exactly one file was sent; the name is a valid project name; the version and the file name are valid; the file is a wheel (`.whl`) or a source distribution (`.tar.gz`, `.zip`); the file name fits the project (section 5).
4. If the form declares `sha256_digest` or `md5_digest`, the stored content must match (`400 checksum_mismatch`). A `blake2_256_digest` is not checked: the blob store does not compute it.
5. The file is stored at its path under the path's lock. The facade checks `add` or `edit` and the deployment policy there: with `disable_redeploy` a file that exists answers `409 redeploy_disabled`. `uv publish --check-url` passes over files the index already lists with the same hash. twine's `--skip-existing` is refused by twine itself for any index but pypi.org.
6. Its component is the project's normalised name and the version in the file's name. The component's attributes keep the name as written, the declared version and `summary`, from the last upload of that version. `requires_python` is kept with the file.

The answer is `200` with an empty body. A failed upload leaves nothing behind, in the database or in the staging area.

A signature sent with the file (`gpg_signature`) is read past: signatures are not kept.

## 8. Proxy PyPI (plan 6b)

`GET` and `HEAD` only.

**The remote.** The configured remote address is the index's root, as for Nexus: `https://pypi.org`. The project page is asked for at `<remote>/simple/<project>/`. If the configured address already ends in `/simple` or `/+simple`, it is taken to be the index itself.

| Path | Result |
| --- | --- |
| Root index | The projects this proxy has cached a file of (D10). The remote is not asked |
| Project page | `ensure_cached` for the remote's page, checked again after `metadata_max_age_minutes`. Then a page written from its links (below) |
| File | The cached file. If it is not cached: find its link in the cached page, fetch it from the address the link gives, check it against the link's hash, cache it (D8). No link, `404` |
| File metadata | The same, from the file's address with `.metadata` added, if the link has a metadata attribute. Otherwise `404` |

A cached file is never asked about again: a file on an index does not change once published.

**Reading the remote's page.** Links are read out of the page as it streams: each `<a>` with an `href`, its attributes and its text. The page is never held in memory, and nothing else on it is used. From each link:

- the file name: the last segment of the address, decoded;
- the address, resolved against the page's own;
- the hash in the fragment, if it is one the blob store computes (`sha256`, `sha512`, `sha1`, `md5`);
- `data-requires-python`, `data-yanked`, `data-core-metadata` and `data-dist-info-metadata`.

A link whose file name is not valid, or does not fit the project, is left out. A link longer than 16 KiB is not read.

**The page served** has one link for each link read, in the remote's order, pointing at this repository (section 6), with the remote's hash and those attributes. If a link has either metadata attribute, both are written, so that old and new clients find it.

## 9. Group PyPI (plan 6b)

`GET` and `HEAD` only.

**Who answers for a project** follows D1, by the rule now in the group engine: the repositories behind the group are taken in the order they are tried, nested groups replaced by their members. If a hosted repository has a file of the project, hosted repositories alone answer; if every one that has it is offline, the answer is `503 repository_offline`. Otherwise the online proxies answer.

| Path | Result |
| --- | --- |
| Root index | Every project the online repositories behind the group hold, once, in name order |
| Project page, from hosted repositories | One page listing the files of all of them. A file name two of them have is listed once, from the earlier one |
| Project page, from proxies | One page written from the links of every proxy that has the project's page, read one after another as they stream. A file name two of them have is listed once, from the earlier one. A proxy that cannot answer is left out. None, `404` |
| File, file metadata | The first repository that has it, among those that answer for its project |

The page's `ETag` is made from what it is built from: the list of hosted files, or the hashes of the proxies' cached pages. A conditional request is answered without reading them.

## 10. Configuration and errors added

No setting is added, and no migration.

| Status | Code | When |
| --- | --- | --- |
| 400 | `invalid_package` | Section 7.1; a body that is not the form an upload sends |
| 502 | `remote_unavailable` | Section 8: a file that does not match the hash on the remote's page, or a file address that is refused |

`checksum_mismatch`, `redeploy_disabled`, `repository_read_only`, `repository_offline`, `not_found`, `method_not_allowed` and `unauthorized` are used as already defined.

## 11. Code structure

Under `backend/src/megooarti/`:

| File | Responsibility |
| --- | --- |
| `repositories/pypi/names.py` | Project names and their normal form; classify a path; file names and the version in them. Pure functions |
| `repositories/pypi/pages.py` | Write index pages; read the links of a remote's page as it streams. Pure |
| `repositories/pypi/upload.py` | Read an upload form as it streams; check what it declares. Pure |
| `repositories/pypi/format.py` | The `PypiFormat` class and its handlers. The only PyPI file that touches the context |
| `security/authentication.py`, `security/users.py` | `__token__` (section 4.1) |
| `repositories/content.py`, `routes.py`, `proxy.py`, `remote.py`, `group.py` | The core changes of section 4 |

## 12. Testing

- **Pure functions** are tested directly: names and their normal form, path classification, the version in every kind of file name, page writing with escaping, the upload form cut at every byte, and reading links from pages as the public index and others write them, cut at every byte.
- **Each repository type** is tested through the HTTP API with the existing fixtures and the fake remote: every row of the tables above, each permission, and D1 by every way in, as for npm.
- **D8** has its own tests: a file on another host, credentials not sent there, an internal address refused, and content that does not match its hash not cached.
- **Real clients**, in the Docker-marked suite, which needs internet access:
  - *Plan 6a:* in a Python container, `twine upload` publishes a wheel and a source distribution to a hosted repository with a password, and `uv publish` the next version with `__token__`; a second upload of the same files is refused, and `uv publish --check-url` passes over them; `pip install` and `uv pip install` install the wheel and run it.
  - *Plan 6b:* `pip`, `uv` and Poetry each install a project, from an empty cache, through a group of the hosted repository and a proxy of pypi.org. The project depends on the package uploaded to the hosted repository and on one small public package. A package uploaded under a name pypi.org also has is listed through the group with our files only.

## 13. Risks

| Risk | Response |
| --- | --- |
| `__token__` is a new way to present a credential, for every format. | It goes through the same function as every other credential, and a token is 256 bits of randomness. The name is reserved, so it can never also be a user. |
| A remote's page decides where a proxy fetches from (D8). | Credentials stay with the remote's origin, internal addresses are refused unless the remote is there, and the content must match the page's hash. Names are not resolved, as for redirects today: network egress rules are the complete defence. |
| A team needs its own build of a public project beside the public versions (D1 hides them). | Upload it under another name, or keep the public project in a group without the hosted repository. A per-group switch can be added if this proves common. |
| A remote writes its links in a form the reader does not recognise (a `<base>` element, links built by script). | Those files are not listed. The standard page, which pypi.org, Artifactory, Nexus and devpi all write, is read. |
| A client asks for the JSON index and gets HTML. | PEP 691 requires clients to accept that, and pip, uv and Poetry do. |
| A hosted project's page is built on every request. | It is one query, and a project with ten thousand files makes a page of about 2 MiB. Clients revalidate with `ETag`. |
| A proxy's first request for a large wheel waits for the whole download, even for a range. | It is then cached. uv asks for ranges only when a file has no metadata file, and pypi.org's wheels have one. |

## 14. Requirement coverage

| Requirement | Where |
| --- | --- |
| FMT-3 hosted, proxy and group | Sections 7, 8, 9 |
| FMT-3 the simple index (PEP 503) | Section 6 |
| FMT-3 uploads from `twine` | Section 7.1 |
| FMT-3 installs from `pip`, `uv` and Poetry | Section 12 |
| REP-12 index pages merged across a group | Section 9 |
| SEC-9 a token wherever a password is accepted | D2, section 4.1 |
| NFR-1 compatibility tested with real clients | Section 12 |
