# Browse, Search and Upload API — Technical Design

| | |
| --- | --- |
| **Status** | Draft for review |
| **Date** | 2026-10-11 |
| **Implements** | [BRD](../../BRD.md): CMP-1 to CMP-9, the rest of REP-13 (rebuilding the search index), API-1, API-4 (components, assets, search, upload), API-5 |
| **Builds on** | [Identity and access design](2026-10-07-identity-access-design.md) (the `browse` action), [Storage and repositories design](2026-10-07-storage-repositories-design.md) (components, assets, the facade), and the four format designs (what each format's files and components are) |
| **Series** | Plans 8a, 8b and 8c of Phase 1 |

## 1. Purpose

Give people, and the web UI that plans 9 and 10 build, a way to see what MegooArti holds and to change it without a package client: list the repositories they may use, walk a repository as folders and files, open a file or a package version, search across repositories, delete, and upload.

Success means:

- Everything the UI will show or do is one documented API call, usable with `curl` and a token.
- A repository with a million files opens as fast as one with ten, at any folder.
- Deleting something through the API leaves the repository as consistent as deleting it with the format's own client would.
- Nobody learns of content they may not browse.

## 2. Scope

One design, delivered as three plans.

| Plan | Contents |
| --- | --- |
| **8a** | The content API: repositories a caller may browse, the folder tree, file and component details, and deleting a file, a component or a folder through the format |
| **8b** | Search across repositories, the search text of a component, and rebuilding a repository's index |
| **8c** | Uploading through the API for Maven, npm, PyPI and Raw, and usage snippets for every format |

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| The web UI itself | Plans 9 and 10 |
| A merged folder tree for a group | Not planned. A group lists its members (D4) |
| Rendering a package's README; yanking a PyPI release; browsing the layers inside a Docker image | Later, with the UI, if wanted |
| Long deletes and index rebuilds as background tasks with progress | Phase 2, with scheduled tasks. Here they are done in the request, in bounded pieces |
| Uploading a Docker image through the API | Not planned. An image is pushed with a container client (CMP-7 names Maven, npm, PyPI and Raw) |
| Relevance ranking, fuzzy matching, searching inside files | Not planned (D8) |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | The API for using content is `/api/v1/content/...` and `/api/v1/search`. `/api/v1/repositories` stays the administration of repositories. | The two have different readers and different permissions. A person who may browse one repository must not need, or see, its configuration. |
| D2 | Seeing a listing or a detail needs `browse` on the repository; downloading needs `read`, as it does today; deleting needs `delete`; uploading needs `add`, or `edit` to replace. A repository the caller may not browse is answered as any other route answers a missing permission (`401` or `403`), and is left out of every list. | CMP-9. The `browse` action was reserved for this by the identity design. |
| D3 | The folder tree is computed from the paths of the files, not kept in a table of its own. `assets.path` is given byte-order collation, so the children of a folder are found by jumping through the index from one child to the next, in time that depends on the number of children shown and not on what lies beneath them. A folder listing is paged with a cursor (`after`), and has no total. | A table of folders has to be kept right on every store and delete, by every format, under concurrency; Nexus's was a lasting source of faults. A total would mean reading every child. |
| D4 | Browsing a group shows its members, each of which is browsed on its own. | Chosen by the product owner. A merged tree could show a proxy's copy of a name that the group answers from a hosted repository. |
| D5 | Deleting goes through the format: a format is asked to delete a file, or a component, and does what its own client's delete would do (Maven rebuilds metadata and checksums, npm rewrites the package document, Docker removes what only that image used). A file that is the format's own bookkeeping cannot be deleted by itself, and the answer says why (`409`). | CMP-8, and success criterion three. The generic delete of a path would leave metadata that lists what is gone. |
| D6 | Deleting a folder deletes every file under it through the same hook, at most 1,000 in one request. The answer says how many went and whether any are left, so the caller repeats. | No request runs without bound, and no task system is needed yet. |
| D7 | Deleting from a proxy removes the cached copy. It is fetched again when it is next asked for. | The known gap of the storage design: a cached file its remote has dropped could not be removed. |
| D8 | Search matches text as people type it: each word must be contained in the component's group, name, version or the format's own words for it (a description, keywords), with `*` for anything. Fields (`format`, `repository`, `namespace`, `name`, `version`) match a whole value, with `*`. A checksum matches a file exactly. Results are components, in the order of their names. | Chosen by the product owner: predictable, and close to Nexus. |
| D9 | Each component carries its search text in a column, written when the component is stored and indexed with trigrams (`pg_trgm`). | "Contains" needs a trigram index to stay fast. |
| D10 | A Docker manifest without a tag is seen in the folder tree only. Tags are what is listed as components and found by search. A format names the namespaces whose components are its own bookkeeping; they are neither listed nor found. | Chosen by the product owner. Plan 7c made every manifest a component, in a namespace of its own, so that a repository knows which images it has. |
| D11 | Rebuilding a repository's index goes through every file again: it is given to the component its path says it belongs to, and every component's search text is written again. | REP-13. It repairs what an older version stored differently, such as Docker manifests kept before they were components. |
| D12 | Uploading is one `multipart/form-data` request to `/api/v1/content/<repository>/upload`, with the fields its format needs. The format turns it into the same stores its own client's upload makes. | CMP-7. One path into a repository for each format, so the deployment policy, permissions and metadata are those of any upload. |
| D13 | A Maven upload without a POM gets a minimal one generated from its group, artifact, version and packaging, unless the caller says not to. | Chosen by the product owner. Without a POM, builds that depend on the artifact warn or fail. |
| D14 | Usage snippets are part of a component's detail, written by the format with the server's public address. | CMP-4, API-1: whoever uses the API gets them, not only the web UI. |

## 4. Changes to the core

### 4.1 For browsing and deleting (plan 8a)

- **Paths in byte order.** A migration changes `assets.path` to the `C` collation. Everything that orders by path now orders by bytes, which is what the tests and the formats already assume.
- **Walking a folder.** A query that returns the children of a folder: for each, its name, whether it is a folder or a file, and for a file its size and when it changed.
- **Details.** Queries for one file with everything CMP-3 names, for the components of a repository, and for one component with its files.
- **Deleting through the format.** A hook on a format, `delete_asset`. The generic format deletes the file. A component is deleted by deleting each of its files this way.
- **Somebody is calling.** A dependency for a route whose answer depends on what the caller may do: it needs a caller, signed in or anonymous, and leaves what they may do to the route, which asks the principal.
- **What a format keeps for itself, and where a file is fetched.** A format names the namespaces of components that are not for listing, and says at which address a stored file is downloaded.

### 4.2 For search (plan 8b)

- **Search text.** A migration adds `components.search`, the `pg_trgm` extension and a trigram index. A format hook says what a component's search text is, from its key and attributes; the generic format joins the namespace, name and version. The facade writes it when it creates or updates a component.
- **Rebuilding.** A service that walks a repository's files in order, in pieces, and does what D11 says.

### 4.3 For upload and snippets (plan 8c)

- **Two hooks on a format:** `upload`, given the fields and files of a form, and `usage`, given a component and the repository's public address.

## 5. The content API (plan 8a)

All under `/api/v1/content`. Lists use the paging of every other list, except the folder tree (D3).

| Request | Result |
| --- | --- |
| `GET /content` | The repositories the caller may browse: `name`, `format`, `type`, `online`, `url` (the address a client is given), and for a group its `members` |
| `GET /content/{repository}` | One of them |
| `GET /content/{repository}/tree?path=&after=&limit=` | The children of a folder, in the byte order of their names: `name`, `path`, `kind` (`folder` or `file`), and for a file `size`, `modified` and the `component` it belongs to. A name that is both a file and a folder is listed as each. `next` is the cursor for the following page, or null. An empty `path` is the root. A group has no tree (`409`) |
| `GET /content/{repository}/asset?path=` | One file: `path`, `size`, `content_type`, `md5`, `sha1`, `sha256`, `sha512`, `blob_store`, `created_by`, `created`, `modified`, `last_downloaded`, `last_verified` (a proxy's), its `component`, and `download`, its address on the content route or the registry |
| `DELETE /content/{repository}/asset?path=` | Delete the file through the format (D5). `204` |
| `DELETE /content/{repository}/tree?path=&after=` | Delete what is under a folder (D6). `200` with `deleted`, `skipped` (files the format keeps itself) and `next`, which is given as `after` to go on, or is null. The root cannot be deleted this way |
| `GET /content/{repository}/components?namespace=&name=` | The components that are listed (D9): `id`, `namespace`, `name`, `version`, `created`, `modified`, in the order of namespace, name and newest first |
| `GET /content/{repository}/components/{id}` | One component, with its `files` and, from plan 8c, its `usage` |
| `DELETE /content/{repository}/components/{id}` | Delete the component through the format. `204` |

**What a format does when asked to delete**, beyond removing the file:

| Format | A file | A component |
| --- | --- | --- |
| Raw | Nothing more | Its one file: in a Raw repository every file is a component, its folder the namespace |
| Maven | Nothing more: checksums and metadata are computed from the files when they are asked for, so they follow by themselves | Every file of the version |
| npm | A tarball is unpublished as `npm unpublish <name>@<version>` does, and dist-tags that named it move. A package's dist-tags cannot be deleted by themselves | The same, for that version |
| PyPI | Nothing more: pages are written from the files | Every file of the release |
| Docker | A tag is removed. A manifest is removed with its tags and what only it used, as by its digest in the registry API. A blob that a manifest refers to cannot be deleted | A tag is removed |

On a proxy, every format removes the cached file and nothing else (D7). A group has nothing to delete (`409`).

## 6. Search (plan 8b)

`GET /api/v1/search` with any of:

| Parameter | Matches |
| --- | --- |
| `q` | Each word of it is contained in the component's search text. `*` matches anything |
| `format`, `repository` | Exactly |
| `namespace`, `name`, `version` | The whole value, with `*` |
| `md5`, `sha1`, `sha256`, `sha512` | A file of the component has exactly this checksum |

The answer is a page of components, each with its repository and format, in the order of name, namespace, repository and newest first, from the repositories the caller may browse (D2). A request with nothing to search for lists everything the caller may browse. A word shorter than three characters is matched all the same, more slowly.

**Search text** of a component, lower case:

| Format | Besides namespace, name and version |
| --- | --- |
| Maven | `group:artifact:version` as one word; the POM's name and description, read when the POM is stored |
| npm | The scope and name as `@scope/name`; the description and keywords of its `package.json` |
| PyPI | The summary and keywords the upload declared |
| Docker | `image:tag`. A manifest's component has none (D10) |
| Raw | Nothing: a file's component is its folder and its name |

`POST /api/v1/repositories/{name}/rebuild-index` (an administrator's) does D11 and answers with what it changed.

## 7. Upload and usage (plan 8c)

`POST /api/v1/content/{repository}/upload`, `multipart/form-data`, on a hosted repository:

| Format | Fields |
| --- | --- |
| Raw | `directory`, and one or more `file` parts, each stored under the directory by its file name |
| Maven | `group`, `artifact`, `version`, `packaging` (default `jar`), `generate_pom` (default true), and one or more `file` parts, each with an optional `classifier` and `extension` taken from the part's name (`file`, `file.sources`, `file.pom`). A POM that is uploaded is used; checksums and metadata are written as for a deploy |
| npm | One `file`, a package tarball. Its `package.json` says what it is; it is published as `npm publish` would |
| PyPI | One or more `file` parts, wheels or source distributions. Their names say what they are; they are stored as an upload by twine would |

The answer is `201` with the components and files that were stored. The deployment policy and the `add` and `edit` permissions apply as to any upload. A Docker repository, a proxy and a group answer `409`.

**Usage** of a component, in its detail: a list of `label`, `language` and `text`.

| Format | Snippets |
| --- | --- |
| Maven | A `<dependency>` for Maven; a line for Gradle (Kotlin and Groovy) |
| npm | `npm install <name>@<version> --registry=<address>` |
| PyPI | `pip install --index-url <address>/simple/ <name>==<version>` |
| Docker | `docker pull <host>/<repository>/<image>:<tag>` |
| Raw | None: a file has its `download` address |

## 8. Errors added

`409 not_browsable` (a group's tree), `409 managed_by_format` (a file that cannot be deleted by itself, with the reason), `409 upload_not_supported`, `422 validation_error` for a form that lacks what its format needs. Everything else uses codes that exist.

## 9. Code structure

Under `backend/src/megooarti/`:

| File | Responsibility |
| --- | --- |
| `repositories/browse.py` | Walking a folder; the details of a file and a component; deleting a folder in pieces. Queries and plain values, no HTTP |
| `repositories/content_api.py` | The routes of section 5 and, later, upload |
| `repositories/search.py`, `repositories/search_api.py` | Turning what was typed into a query; the route; rebuilding an index |
| `repositories/formats.py` | The hooks: `delete_asset`, `delete_component`, `search_text`, `upload`, `usage` |
| `repositories/<format>/format.py` | Each format's own answer to the hooks |
| `security/authentication.py` | Which repositories a principal may browse |

## 10. Testing

- **The tree** is tested for what a folder shows: folders before files, names that are prefixes of one another, names with characters around `/` in byte order, a folder with thousands of children read page by page, an empty repository, a path that is a file. A test counts the statements a listing takes on a folder whose children hold many files, to hold D3.
- **Details** are tested for every field of CMP-3, for a hosted file and a proxy's.
- **Deleting** is tested for each format through the API and then through the format's own protocol: after a delete, what the client sees is what it would see had its own client deleted. Each thing that cannot be deleted by itself is tested for its refusal.
- **Permissions** are tested for each route with `browse` alone, with `read` alone, with nothing, and anonymously; lists are tested for leaving out what the caller may not browse.
- **Search** is tested for each parameter alone and together, `*` in each place, words shorter than three characters, characters that mean something in a pattern (`%`, `_`, `\`), and for never returning a component of a repository the caller may not browse.
- **Upload** is tested for each format by uploading through the API and installing with the format's own client paths (the same requests the earlier plans' tests make), and in the Docker-marked suite with the real clients.

## 11. Risks

| Risk | Response |
| --- | --- |
| Changing the collation of `assets.path` rebuilds its index, which takes time on a large installation. | Nothing has been released. The migration says so. |
| `pg_trgm` is an extension. A managed PostgreSQL may not let the application's role create it. | It is trusted since PostgreSQL 13, so a database's owner can. The README says what to do where it cannot: have an administrator create it first. |
| A folder delete or an index rebuild of a very large repository takes many requests or a long one. | Bounded pieces (D6); background tasks are Phase 2. |
| A format's delete hook and its protocol's delete could drift apart. | The hook is what the protocol's delete calls, wherever the format has one. |
| Search text is written when a component is stored, so components stored before plan 8b have none. | The migration fills it for what exists; rebuilding an index does the same on demand (D11). |
| Listing which repositories a caller may browse checks every repository. | Repositories are tens or hundreds, and the check is in memory. |

## 12. Requirement coverage

| Requirement | Where |
| --- | --- |
| CMP-1 components and assets | Sections 5, 6 |
| CMP-2 browse as a folder tree | D3, section 5 |
| CMP-3 asset details | Section 5 |
| CMP-4 usage snippets | D14, section 7 |
| CMP-5, CMP-6 search | D8, D9, section 6 |
| CMP-7 upload | D12, D13, section 7 |
| CMP-8 delete | D5, D6, D7, section 5 |
| CMP-9 nothing revealed | D2 |
| REP-13 rebuild the index | D11 |
| API-1, API-4, API-5 | Sections 5 to 7 |
