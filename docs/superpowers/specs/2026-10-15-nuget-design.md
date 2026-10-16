# NuGet: design

**Date:** 2026-10-15
**Plans:** 13a (hosted over V3), 13b (V3 proxies), 13c (V3 groups and search), 13d (V2, hosted and proxied), 13e (V2 in groups), 13f (the symbol server), 13g (the web UI)
**BRD:** FMT-9 (NuGet), SEC-9

## 1. Goal

.NET developers and their builds restore, push and search NuGet packages through MegooArti with `dotnet`, `nuget.exe` and Visual Studio; Windows machines install Chocolatey packages with `choco`; PowerShell installs modules with PSResourceGet. Each does so from a cache of a public feed, from an organisation's own repositories, and from one address that has both; and a debugger fetches the symbols of an organisation's own packages from the same place. MegooArti does what Nexus Repository does for NuGet (V2 and V3, hosted, proxy and group, and a symbol server), as the BRD's parity goal asks.

## 2. Scope

**In scope:**

- The format `nuget`, with hosted, proxy and group repositories (D1).
- NuGet's V3 protocol, and its V2 protocol (D1): a hosted repository and a group serve both; a proxy speaks the one its remote speaks (D2).
- Push, delete (D4), search (D5), and the deployment policy (D6).
- Symbol packages (`.snupkg`) and a symbol server (D3).
- The web UI: the format in every list, its fields, upload and the setup snippets.
- The real-client tests of section 10 (D7), and a guide.

**Out of scope:**

| What | Why |
| --- | --- |
| Unlisting, and listing again | D4: delete removes. |
| The V3 catalog (`Catalog/3.0.0`) | Restore, push and search never read it; it is what nuget.org's mirrors replicate from. |
| Legacy symbol packages (`.symbols.nupkg`) and Windows (MSF) PDBs | nuget.org takes portable PDBs in `.snupkg` only; so do the current tools. |
| V2 queries that the clients of section 10 do not send | D5. They are refused with a message that says so. |
| Package signing, and checking a package's signature | A package's signature is its author's; the clients check it. MegooArti keeps the package as it was pushed. |
| `dotnet nuget why`, vulnerability data (`VulnerabilityInfo`), the README and icon services of nuget.org | They are nuget.org's own services, not a feed's. A proxy passes on nothing of them; a client does without. |

## 3. Decisions

The product owner's:

| # | Decision | Choice |
| --- | --- | --- |
| D1 | Protocols | V3 and V2: full parity with Nexus Repository. |
| D2 | A proxy's protocol | Chosen per proxy, once, when it is made: the protocol its remote speaks, and the one it serves. |
| D3 | Symbols | A symbol server (SSQP) on hosted, proxy and group repositories, as Nexus has. |
| D4 | `dotnet nuget delete` | Removes the version and its files, as Nexus does. |
| D5 | Search | A hosted repository searches its own packages; a proxy passes the search on to its remote; a group merges its members' answers, the first member's winning for an id. For V2, a group answers only the queries the clients of D7 send. |
| D6 | Pushing a version that is there | Refused with `409`, as nuget.org does, unless an administrator allows redeploy: a hosted NuGet repository's default deployment policy is `disable_redeploy`. |
| D7 | Clients the tests run | `dotnet` (the SDKs of the two .NET LTS releases), `nuget.exe` under Mono, Chocolatey's `choco`, and `pwsh` with PSResourceGet. No other. |
| D8 | Shape of the work | One spec, a plan for each part (section 12). |

Settled here, by the designer:

| # | What | Why |
| --- | --- | --- |
| E1 | A package is read once, at push or when a proxy first fetches it: its `.nuspec`, and its SHA-512. What V3 and V2 serve of a hosted repository is written from those records, never stored. | As APT's and YUM's indexes are (4.3 of the Linux formats' spec): one record, two protocols, and nothing to keep in step. |
| E2 | An id is matched without regard to case, and a version is normalized as NuGet normalizes it (no leading zeros, no fourth part of 0, no build metadata in the path). Paths are lower case. | It is what the clients ask for, and what nuget.org serves. |
| E3 | A group serves each protocol from the members that speak it: V3 from hosted members, V3 proxies and groups; V2 from hosted members, V2 proxies and groups. A member is left out of the protocol it does not speak. | A V2 remote cannot be asked a V3 question without translating it, which Nexus does not do either. |
| E4 | A group signs and checks nothing. | Unlike the Linux formats, a NuGet feed's documents are not signed; a package's signature is its author's, and the clients check it. |
| E5 | A group writes its own registration pages for an id, and its own V2 `next` links. | Its members' pages differ in shape (inlined, or paged elsewhere), and a member's `next` link leads past the group. |

## 4. Shared parts

### 4.1 The format

`nuget` is a `Format` subclass, as npm and PyPI are, served under `/repository/<name>/`. A package has no namespace: permissions are `repository:nuget:<name>:<action>` with the usual actions. A component is an id (as the package spells it) and a normalized version (E2); its assets are its `.nupkg`, its `.nuspec`, its `.snupkg` and the PDBs of 8.

### 4.2 Addresses

| Path, under `/repository/<name>/` | What it is |
| --- | --- |
| `index.json` | V3's service index, naming the resources below with this repository's own addresses. |
| `v3/package/<id>/index.json` | The versions of an id (`PackageBaseAddress/3.0.0`). |
| `v3/package/<id>/<version>/<id>.<version>.nupkg`, `….nuspec` | A package, and its `.nuspec`. |
| `v3/registration/<id>/index.json`, `…/page/<lower>/<upper>.json`, `…/<version>.json` | Registration (`RegistrationsBaseUrl/3.6.0`: SemVer 2.0.0, gzipped). |
| `v3/search`, `v3/autocomplete` | `SearchQueryService/3.5.0`, `SearchAutocompleteService/3.5.0`. |
| `api/v2/package` | `PackagePublish/2.0.0`: push (`PUT`) and delete (`DELETE …/<id>/<version>`), for V2 and V3 clients alike. |
| `api/v2/symbolpackage` | `SymbolPackagePublish/4.9.0`: push of a `.snupkg`. |
| `` (the root), `$metadata`, `Packages()`, `Packages(Id='…',Version='…')`, `FindPackagesById()`, `Search()` | V2 (OData). |
| `package/<id>/<version>` | V2's download of a package. |
| `symbols/<name.pdb>/<key>/<name.pdb>` | The symbol server (SSQP), section 8. |

A client is given `…/<name>/index.json` for V3 and `…/<name>/` for V2; every address MegooArti writes into a document is the one the base URL gives (as for every format).

### 4.3 Sign-in

A package client signs in with an API token: as the `X-NuGet-ApiKey` header (what `dotnet nuget push -k`, `nuget.exe`, `choco push --api-key` and `Publish-PSResource -ApiKey` send) or as the password of HTTP Basic (what a `nuget.config` source's credentials, `choco source add -u -p` and a PowerShell credential send). An `X-NuGet-ApiKey` that is not a token of an enabled user is refused with `401`, as a wrong password is. Reads follow the repository's permissions, anonymous access included.

### Settled while building plan 13a

| # | What | Why |
| --- | --- | --- |
| W1 | A hosted repository's V3 documents are written from the database on each request, as npm's package documents are, and kept nowhere (in place of 5's "kept by revision"): an id's versions and registration from that id's versions; a search's page of ids is chosen, ranked and counted in the database, and only that page's versions are read. | Each document is of one id, or of one page of a search: a query or two, where a cache of every id's documents would be written again after every push. |
| W2 | A registration's pages are always inlined in its index; no page has an address of its own, and nothing is gzipped by the server. | NuGet's clients read inlined pages as they read paged ones; the gateway may compress what it sends. |
| W3 | A version's component is its normalized version in lower case, as in every address; what the package wrote is in its `.nuspec`, which the documents show. An id's first push spells it. | One version is one component whatever case a push gives it. |
| W4 | A push is taken at `api/v2/package` and `api/v2/symbolpackage` with or without a slash after them. | `dotnet nuget push` adds one to the address the service index gives. |
| W5 | A package of 4 GiB or more (ZIP64) is refused with `400 invalid_package`, with a message that says so. | Its zip directory is read where an ordinary zip has it; nuget.org takes no package of that size either. |
| W6 | `X-NuGet-ApiKey` is taken as an API token by the content route only, and only from a request without an `Authorization` header. | The JSON API takes a token as a bearer token; one header to say who calls is enough. |
| W7 | The upload API (and the web UI) takes `.nupkg` and `.snupkg` files and keeps each where a push would; packages before symbol packages. | One way of keeping a package, however it arrives. |
| W8 | `semVerLevel` is not read: every version is served to every client. | Every client of D7 sends `semVerLevel=2.0.0`. |
| W9 | Deleting a package's file in the web UI or the API deletes its version, as `dotnet nuget delete` does; its `.nuspec` cannot be deleted on its own (`409 managed_by_format`); its symbol package can. | D4: what a NuGet client would do. |
| W10 | The setup snippets are `dotnet nuget add source`, and a `nuget.config` with `%MEGOOARTI_USER%` and `%MEGOOARTI_TOKEN%`, which NuGet reads from the environment; a source over plain HTTP is marked `allowInsecureConnections="true"`, and a name that is not one an element can have is encoded as NuGet encodes it (`_x0031_`). Chocolatey's and PowerShell's, as setup and as usage, come with plan 13d, as their tests do. | V1 of the Linux formats' spec, and what each client reads. |
| W11 | Until plans 13b and 13c, a NuGet repository can only be hosted. | Each plan ends with something that works. |

### Settled by the review of plan 13a

| # | What | Why |
| --- | --- | --- |
| W12 | The guide adds the repository as a source with its credentials before it pushes, and pushes to the source by name. | `dotnet nuget push` reads the repository's `index.json` first, with the source's credentials, and sends the API key with the push alone: with anonymous access off, a push to a bare address is refused. |
| W13 | An id's version list is written from its versions alone. | It needs no more, and an id can have thousands. |
| W14 | A registration inlines its versions when there are at most 128, as nuget.org's does; beyond that its index lists pages of 64 by their bounds, each at an address of its own (`v3/registration/<id>/page/<lower>/<upper>.json`), and written from that page's versions alone (in place of W2). | An id with 5,000 versions made a registration of 24 MB on every request. |
| W15 | A search leaves out an id with no version left to show. | A version deleted between choosing the page and reading it made the search answer `500`. |
| W16 | Over plain HTTP, the setup's `dotnet` command says to use the `nuget.config`, which marks the source `allowInsecureConnections`. | .NET 9 and later refuse a plain-HTTP source that is not marked so (NU1302). |
| W17 | The first push of an id holds a lock on the id while it reads how the repository spells it. | Two first pushes in two spellings made two components, one of which the feed no longer showed. |

## 5. Hosted repositories

- **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
- **Push of a version that is there:** `409` under `disable_redeploy`, the default (D6); `allow_redeploy` replaces it; `read_only` refuses every push.
- **Push of a `.snupkg`:** `PUT api/v2/symbolpackage`, or `api/v2/package` (as older clients do). Its `.nuspec` must name a package version the repository has (`404` otherwise); it is stored beside it, and section 8 says what is read of it.
- **Delete:** `DELETE api/v2/package/<id>/<version>`, the web UI or the API removes the version and every asset of it (D4). A version that is not there is `404`.
- **V3:** the version list, registration and search are written from the records of 5's push (E1), as the repository's revision has them, and kept by revision as the Linux formats' indexes are. Registration has every version of an id inlined in pages of 64, as nuget.org's; a version's entry has its `.nuspec`'s fields, its dependency groups, `packageContent`, `published` (the time it was pushed) and `listed: true`.
- **V2:** `Packages()`, `FindPackagesById()`, `Search()` and `Packages(Id,Version)` are answered from the same records, as Atom feeds of `m:properties` with the properties the clients read (`Id`, `Version`, `NormalizedVersion`, `Title`, `Description`, `Authors`, `Tags`, `Dependencies`, `IsLatestVersion`, `IsAbsoluteLatestVersion`, `IsPrerelease`, `Published`, `PackageHash`, `PackageHashAlgorithm`, `PackageSize`, `DownloadCount` and the others of nuget.org's `$metadata`). The queries a hosted repository answers are those of 7.3.
- **Search:** over id, title, description, tags and authors, as `q` says (`id:` and `packageid:` as nuget.org reads them), with `prerelease` and `semVerLevel`; ranked with an exact id first, then the id's beginning, then the rest; `totalHits` as asked. MegooArti counts no downloads: a hosted package's download count is 0, and an order by downloads keeps the order by relevance.
- **Usage:** `dotnet add package <id> --version <version>`, `<PackageReference Include="<id>" Version="<version>" />`, `Install-Package <id> -Version <version>`, `choco install <id> --version <version>`, `Install-PSResource <id> -Version <version>`.
- **Setup** (as the Linux formats' V1): `dotnet nuget add source <address>index.json -n <name> -u "$MEGOOARTI_USER" -p "$MEGOOARTI_TOKEN" --store-password-in-clear-text`, the same as a `nuget.config` source, `choco source add -n <name> -s <address> -u … -p …`, and `Register-PSResourceRepository -Name <name> -Uri <address>index.json`.

## 6. Proxy repositories

- **Settings:** `format_config.protocol`, `v3` (the default) or `v2`, fixed after creation (D2). The remote is a V3 service index (`https://api.nuget.org/v3/index.json`) or a V2 feed's root (`https://community.chocolatey.org/api/v2/`, `https://www.powershellgallery.com/api/v2/`). `format_config.symbol_url`, optional, is a symbol server to proxy (`https://symbols.nuget.org/download/symbols`; section 8).
- **A V3 proxy** reads its remote's service index for its `PackageBaseAddress/3.0.0`, its gzipped SemVer 2.0.0 registration (`RegistrationsBaseUrl/3.6.0`, or the newest it has), and its `SearchQueryService` and `SearchAutocompleteService`. They may be on other hosts than the index (nuget.org's are). It serves a service index of its own (4.2) and rewrites the remote's addresses in what it passes on: the registration's `@id`, `registration`, `packageContent` and `items` page addresses, and search results' `@id` and `registration`. A registration page that the remote's index names elsewhere is fetched and passed on rewritten.
- **A V2 proxy** passes a client's query on as it came (its path and query string) and rewrites the remote's addresses in the Atom it answers with: `xml:base`, each entry's `id` and `content src`, its `edit-media` link, and the `next` link of a page. `$metadata` is its remote's.
- **Caching:** a `.nupkg`, `.nuspec` and `.snupkg` never change: kept for good. The service index, version lists, registration pages and V2 query answers are metadata, checked again after the metadata age; a V2 answer is kept by its whole query. Search is passed on every time and not kept. What the remote does not have is remembered (the negative cache), as for every proxy.
- **What a proxy keeps** of a package it fetched is read as a pushed one is (5), so that it can be browsed, found by MegooArti's own search and deleted.
- **Remote sign-in, blocking, and the rest** are those of every proxy.

## 7. Group repositories

### 7.1 Members and protocols

A group's members are in order. It serves V3 from those that speak V3, and V2 from those that speak V2 (E3). It signs and checks nothing (E4).

### 7.2 V3

- **Version list:** the union of the members' lists, sorted.
- **A package, its `.nuspec` or `.snupkg`:** fetched from the first member that has it.
- **Registration:** written by the group (E5): for an id, every version any member has, a version several members have taken from the first; in pages of 64, with the group's addresses.
- **Search and autocomplete:** each member is asked for its first `skip + take` results; the answers are merged in member order, the first result for an id kept, and the page asked for is cut from them. `totalHits` is the sum of the members' less the ids dropped, which is what can be known. `skip + take` is at most 3,000 (section 9).
- **Caching:** a version list and a registration are kept by the members' revisions and the proxies' kept metadata, as the Linux formats' groups are, written behind the requests one at a time (the S10 to S12 of that spec). Search is merged on each request.

### 7.3 V2

- **What a group answers:** the queries the clients of D7 send: `FindPackagesById()?id='…'`; `Packages(Id='…',Version='…')`; `Packages()` with a `$filter` of `Id eq '…'`, `tolower(Id) eq '…'`, `IsLatestVersion`, `IsAbsoluteLatestVersion` and `and` between them; `Search()` with `searchTerm`, `targetFramework`, `includePrerelease` and such a `$filter`; `$orderby` of `Id`, `Version`, `DownloadCount desc`, `Published desc` or `LastUpdated desc`; `$skip`, `$top`, `$skiptoken` and `$inlinecount`; `semVerLevel`. The plans pin the list to what the clients send, observed against a hosted repository and recorded in the tests.
- **Anything else** is refused with `400` and a message naming what is not supported: MegooArti does not pass an unknown OData query to every member and pretend to merge it.
- **Merging:** as V3's search: each member is asked for the query with `$top` and `$skip` replaced by its first `skip + top` entries, the answers merged in member order, the first entry for an id and version kept, and the page cut from them, with the group's own `next` link (E5).

## 8. The symbol server

- **At push of a `.snupkg`:** each `.pdb` in it must be a portable PDB (metadata signature `BSJB`); a Windows PDB, or a `.pdb` that is neither, is refused with `400 invalid_package`, as nuget.org refuses it. Its PDB id (a GUID and a stamp, from the `#Pdb` stream) and its checksum (SHA-256 of the file with the id's bytes zeroed, as the debug directory's `PdbChecksum` holds it) are read, and the PDB is kept as an asset of the package's version at `symbols/<name.pdb>/<GUID><stamp>FFFFFFFF/<name.pdb>`, with the name in lower case (SSQP's key for a portable PDB). Deleting the version deletes it (D4).
- **Serving:** `GET symbols/…` reads that asset under the repository's `read` permission. A client that sends `SymbolChecksum` (Visual Studio and `dotnet-symbol` do) is served the PDB only if one of the checksums it names is the PDB's; otherwise `404`, as nuget.org's symbol server answers.
- **A proxy with `symbol_url`** passes `symbols/…` on to `<symbol_url>/…` with the client's `SymbolChecksum`, and keeps what it is given for good. A proxy without one answers `404` there.
- **A group** asks its members for a `symbols/…` path in order.
- **Clients:** Visual Studio's symbol locations take `<address>symbols/`; `dotnet-symbol --authenticated-server-path <token> <address>symbols/`. The guide and the setup snippet say so.

## 9. Errors and limits

- What is read of a package is bounded: its zip's central directory at 10,000 entries, its `.nuspec` at 1 MiB, a `.snupkg`'s PDBs at 1,000 and each at 256 MiB. The zip is read from its directory; nothing is unpacked but the `.nuspec` and the PDBs, each to its bound. Beyond a bound the package is refused with `400 invalid_package`.
- A V3 search takes at most 1,000 results, and `skip + take` is at most 3,000; a V2 `$top` is at most 100, the default page. More is refused with `400`.
- A registration has 64 versions to a page.
- Paths with `..` or a backslash are refused as for every format; an id or a version that is not one (NuGet's rules) is `404` on a read and `400` on a push.

## 10. Testing

- **Unit tests** under `backend/tests/repositories/nuget/`, with packages the tests build in memory and a stand-in remote: reading `.nuspec` files and refusing broken packages at each bound; the V3 documents and the V2 feeds of a hosted repository; push, redeploy, delete; a V3 and a V2 proxy rewriting what they pass on; groups merging; the symbol server; sign-in by `X-NuGet-ApiKey`.
- **Real clients**, marked `docker`, each in its own image, against a stack built from the working tree (D7):
  - `test_nuget_client.py`, with the .NET SDKs of the two LTS releases: a package built in the test with `dotnet pack` (and its `.snupkg`), pushed to a hosted repository (and pushed again with `--skip-duplicate`), restored, found with `dotnet package search`, and deleted; a public package restored through a proxy of nuget.org; both through a group; `dotnet-symbol` fetching the package's PDB from the hosted repository and through the group.
  - `test_nuget_exe_client.py`: `nuget.exe` under Mono, installing and pushing over V3 and over V2.
  - `test_chocolatey_client.py`: Chocolatey's Linux image: `choco push`, `choco install` from a hosted repository over V3 and V2, from a V2 proxy of the community feed, and from a group.
  - `test_powershell_client.py`: `pwsh` with PSResourceGet: `Publish-PSResource` to a hosted repository, `Install-PSResource` from it and from a V2 proxy of the PowerShell Gallery.
  The clients' versions are pinned in the tests, and named in the guide.
- **Browser tests** for the format's form fields, upload and setup snippets.
- **The test of the documents** has NuGet's clients in `CLIENTS`.

## 11. Risks

| Risk | What settles it |
| --- | --- |
| V2's queries differ from client to client, and from version to version of one client. | The plans record what each client of D7 sends (7.3), and the real-client tests keep them honest; anything else is refused with a message, not answered wrongly. |
| nuget.org's search and registration are on other hosts than its service index, and change their addresses. | A V3 proxy reads them from the remote's service index (6), as clients do, and never assumes a host. |
| A popular id has thousands of versions (registration pages, a group's merge). | Pages of 64 beyond 128 versions, each written from its own versions (W14); a version list from the versions alone (W13). A search still reads every version of each id on its page: measured in plan 13c against nuget.org's largest ids. |
| `nuget.exe` under Mono, and Chocolatey on Linux, are less maintained than their Windows builds. | The tests pin images that work; if one stops being published, the plan says so and the test is replaced by the nearest client that is. |
| The PowerShell Gallery and the Chocolatey community feed rate-limit, or are slow. | The tests fetch a few small packages, as the Linux formats' tests do of their mirrors. |
| A portable PDB's checksum is not what the debugger sends. | Plan 13f checks it against `dotnet-symbol` and a PDB built by `dotnet pack`. |

## 12. Plans

| Plan | What it builds |
| --- | --- |
| 13a | The `nuget` format: reading packages, hosted repositories over V3 (service index, package contents, registration, search, push, delete), `X-NuGet-ApiKey`, the deployment policy's default, its `dotnet` tests and `docs/formats/nuget.md`. |
| 13b | V3 proxies (6). |
| 13c | V3 groups (7.2), search merged. |
| 13d | V2: served by hosted repositories, and V2 proxies (`protocol`); the `nuget.exe`, Chocolatey and PowerShell tests. |
| 13e | V2 in groups (7.3). |
| 13f | The symbol server (8), `symbol_url`, and `dotnet-symbol` in the tests. |
| 13g | The web UI: the format in every list, the form's `protocol` and `symbol_url`, upload of `.nupkg` and `.snupkg`, the setup snippets. |

Each plan ends with something that works with real clients; the API serves NuGet from 13a, and the web UI lists it from 13g.

## 13. Requirements

| BRD | Where |
| --- | --- |
| FMT-9 NuGet (V3 API; V2 where needed for proxying): hosted, proxy and group, with API-key authentication | Sections 5 to 7: V3 everywhere, V2 served and proxied (D1, D2); sign-in by `X-NuGet-ApiKey` (4.3). Symbols beyond the BRD (D3). |
| SEC-9 Clients authenticate with an API token wherever they accept a password or an API key | 4.3: the token is the NuGet API key, and the password of Basic. |
