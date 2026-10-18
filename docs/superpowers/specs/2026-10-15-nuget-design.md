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

### Settled while building plan 13b

| # | What | Why |
| --- | --- | --- |
| X1 | A proxy's remote is a feed's service index, kept as metadata under `.remote/index.json`, a path no client asks for. Of it the proxy uses `PackageBaseAddress/3.0.0`, one registration (`3.6.0` first: SemVer 2.0.0), and search and autocomplete (`3.5.0` first); a feed without a package address or a registration is refused with `502`. The proxy's own `index.json` offers no place to push to, and no search where the feed has none. | 6: where the feed serves each resource is the feed's to say, as it is for NuGet's clients. |
| X2 | A registration the feed sends gzipped whatever it is asked for is inflated, to 32 MiB; no other document is taken gzipped. | nuget.org's registrations are stored gzipped and served so, `Accept-Encoding: identity` or not. |
| X3 | What is kept of a registration is what the feed sent; the addresses in it are made the proxy's as it is sent: each of the feed's registrations, of whatever kind, becomes the proxy's one registration, and its package address the proxy's. A page or a version's document is asked of the feed's registration by the same path. The catalog's addresses are left as they are. | A search or a dependency names any of the feed's registrations; restore never reads the catalog. |
| X4 | A package and its `.nuspec` fetched through a proxy are read as pushed ones are (`Format.describe_fetched`, a member every format has), and their version is a component spelled as its package spells its id. They are kept for the proxy's content age, as every proxy's files are: `-1` keeps them for good, as 6 says, and a package asked about again costs the feed a `304`. | One way of describing a package, however it arrives; the proxy settings are every proxy's. |
| X5 | A search and an autocomplete are passed on with the client's query as it came, and their answers are not kept: a feed that cannot be reached answers `502`. | D5: a search is the feed's. |
| X6 | `format_config.protocol` is `v3` until plan 13d (a V2 feed is refused with `422`), fixed once the proxy is made; `format_config.symbol_url` is checked as a remote's address is, and kept without its last slash. | D2, and plan 13f's symbol server. |
| X7 | Over plain HTTP, the setup's `dotnet` command marks the source with `--allow-insecure-connections`, which the .NET SDK 9 and later take, and says that .NET 8 leaves it out (in place of W16). | The .NET SDK 9 has the option; 8 does not. |
| X8 | A hosted registration with no version left to show is `404`. | Its last version may go between its two reads. |

### Settled by the review of plan 13b

| # | What | Why |
| --- | --- | --- |
| X9 | What a client asks a proxy for is asked of the feed only if it is what the feed serves there: an id NuGet takes, in lower case, then `index.json`, or a normalized version and a file (a package, its `.nuspec`, its icon); in a registration, an id's index, a version's document or a page. It is sent escaped as an address is. Anything else is `404`, and the feed is not asked. | What is asked of the feed goes with its credential: `%2e%2e`, `?` or `#` in a client's path reached the feed as a path or a query of the client's choosing. |
| X10 | A search's or an autocomplete's failure is recorded and does not count towards leaving the feed alone (`proxy.Source.blocks`). | nuget.org searches on another host: its failing blocked the proxy, and every restore of a package not yet kept failed with it. |
| X11 | NuGet Audit's vulnerability data (`VulnerabilityInfo/6.7.0`) is not passed on yet; the guide says how to keep it, with nuget.org as an audit source. Plan 13c passes it on, beside groups. | A machine whose one source is the proxy gets no audit warnings without it. |

### Settled while building plan 13c

| # | What | Why |
| --- | --- | --- |
| Y1 | A group writes its version lists, registrations, searches and autocompletes on each request from what its members have, and keeps none of them (in place of 7.2's caching). Each member keeps what it keeps: a proxy its feed's documents as metadata, a hosted repository nothing (W1). Measured through a group of a hosted repository and a proxy of nuget.org, over AWSSDK.S3 (1,570 versions): its registration took 8 s the first time, while the proxy fetched the feed's 25 pages, and 0.2 to 0.25 s after; its version list 0.04 s. | What a group keeps would change with every member's push, delete and fetch; written on request, it is right after each of them, and costs little once its members have what they keep. |
| Y2 | A group asks each member for data, not documents (`nuget/feeds.py`), with the group's own address: a hosted member writes its items with it, a proxy rewrites its feed's with it, and a group in a group is asked the same way. | No address of a member's, or of a feed's registration or packages, reaches a client of the group. The catalog's addresses are left as the feed wrote them (X3). |
| Y3 | A group's registration has every version any member has, a version several have taken from the first (by its normalized version), inlined up to 128 versions and in pages of 64 at their own addresses beyond (W14); a version's leaf is written from its item. A proxy's registration pages that its feed lists by address are fetched, if they are under the feed's registration, and kept. | 7.2 and W14; a page elsewhere is not the feed's to have the proxy ask for. |
| Y4 | A search or an autocomplete is merged as 7.2 says, each member asked for its first `skip + take` results at most 1,000 at a time; an autocomplete of an id's versions is every member's together, a prerelease only if asked for, the oldest first. | Members, nuget.org among them, take at most 1,000 results at a time, and a group may be asked for up to the 3,000th. |
| Y5 | A member that is offline, or answers `404`, `502` or `503`, gives nothing to what the group merges, as the group engine passes over it; any other error is the group's. Members are listed once for each request. | As every format's groups do. |
| Y6 | NuGet Audit's data (`VulnerabilityInfo/6.7.0`; in place of X11): a proxy offers it where its feed does, keeping the feed's index (inflated, at most 1 MiB) and each file it names (at most 64 MiB) as metadata, served at `v3/vulnerabilities/<name>.json`; a name the feed's index does not list is `404`, and the feed is not asked. A group offers the first member's index that has one, with the group's addresses, and each file from the first member that has it. A hosted repository has none. | A machine whose one source is a proxy or a group gets NuGet Audit's warnings (`NU1901` to `NU1904`) without naming nuget.org; nuget.org's files are gzipped whatever is asked, and its base file is some megabytes. |
| Y7 | A hosted repository's search over an id of 1,600 versions took 0.1 s, its registration's index 0.05 s and a page 0.1 s (measured in the unit tests' database); nuget.org's search for `awssdk` takes 2.4 to 3.5 s through a proxy or a group, its answer being 3.6 MB. | 11's risk of an id with thousands of versions, measured. |

### Settled by the review of plan 13c

| # | What | Why |
| --- | --- | --- |
| Y8 | A group asks a member that is not a group for its first `skip + take` results a page at a time (the client's `take`), or a tenth of them at a time for a page far down, and at most 1,000 at a time (in place of Y4's 1,000). | nuget.org's results each list every version of their id (3.6 MB for 20 of `awssdk`): asked for two pages at once, its answer passed the 8 MiB a proxy takes of a search, and the proxy was passed over in silence. |
| Y9 | A group in a group is asked once for all of its first `skip + take` results, and asks its own members as the outer group does. | Members are listed once for each request (Y5): asked a second time, the inner group had no members, and a page past the first 1,000 results came back empty. |
| Y10 | A group asks its members only for a package's files and NuGet Audit's files; any other path it does not write is `404`. | A member's answer to anything else would carry the member's addresses. |
| Y11 | (Replaced by H1.) An id's versions are every member's, as 7.2 says and as Nexus's NuGet groups have them: a public package of an id you push adds its versions beside yours. The guide says so, and points to nuget.org's reserved prefixes and to NuGet's package source mapping. Keeping an id pushed here from the other members, as the npm, PyPI and Docker groups do (`group.owners`), is left to a later plan, if wanted. | NuGet resolves the lowest version a range allows, which narrows what a public package can take over; a floating version, or `dotnet add package` without one, does not. |

### Settled while building plan 13d

| # | What | Why |
| --- | --- | --- |
| Z1 | A hosted repository's V2 feed is written on each request from the records of 5's push, as its V3 documents are (W1); nothing of it is kept. A version's package's size and SHA-512 are kept with the version as it is pushed, for V2's `PackageSize` and `PackageHash`; a version's `Version` is what its package wrote, its `NormalizedVersion` the normalized one. | E1: one record, two protocols. |
| Z2 | The queries a hosted repository answers are those the clients of D7 were seen to send, each recorded in `test_odata.py` (in place of 7.3's list): `nuget.exe`'s `Packages(Id='…',Version='…')`, `FindPackagesById()` and `Search()` ordered by `Id`; `choco`'s `Search()` with `$filter=IsLatestVersion` ordered by `Id,Version desc`, and `Packages()` with `(tolower(Id) eq '…') and IsLatestVersion`; PSResourceGet's `FindPackagesById()` with `Id eq '…'`, `IsLatestVersion eq true`, `IsAbsoluteLatestVersion eq true`, `NormalizedVersion` compared (`eq`, `ge`, `le` and the others) and `IsPrerelease eq false`, ordered by `NormalizedVersion desc`, and `Search()` with `startswith(Id, '…')` and `substringof('…', Tags) eq true`; with `$skip`, `$top`, `$inlinecount` and `/$count`. Anything else is `400 unsupported_query`, which names what is not answered. | 7.3: the list pinned to what the clients send. PSResourceGet's ranges, wildcards and tags are what `Find-PSResource` and `Install-PSResource -Version` send. |
| Z3 | A `$top` above 100 is answered with 100 versions and a `next` link that asks for the same with `$skip` past them, as nuget.org does (in place of 9's refusal). | PSResourceGet asks for `$top=6000` in a search by tag. |
| Z4 | A V2 client pushes with `PUT` to the repository's own address and deletes with `DELETE <id>/<version>` under it; `api/v2/package` takes both too. | `nuget.exe`, `choco` and PSResourceGet push to the address of the source they are given. |
| Z5 | V2's root is the repository's own address, and its `$metadata` names `Packages`, `Search` and `FindPackagesById` and the properties a version has. A V2 path after more than one slash is that path. | NuGet reads `$metadata` for what a feed answers; PSResourceGet adds a slash to an address that ends in one. |
| Z6 | The setup snippets give Chocolatey V2's address, and PSResourceGet V3's `index.json`, or for a proxy of a V2 feed its V2 address without its slash and `-ApiVersion v2` (W10's Chocolatey and PowerShell). A proxy of a V2 feed gives its V2 address to `dotnet` and in `nuget.config` too. A version's usage has `choco install` and `Install-PSResource`. | PSResourceGet tells V3 by `index.json` alone, and refuses an address it cannot tell unless it is told. A V2 push goes straight to the repository. |
| Z7 | A V2 proxy's root is its own; its `$metadata` is its feed's, kept. A query is passed on as it came, its path escaped as an address is and its query string as it is, and kept by both under `.remote/v2/`; a `Search()` is passed on every time and not kept (as X5). In an answer, the addresses under the feed's root as the proxy is given it, and under the root the answer names (`xml:base`), are made the proxy's: each `xml:base`, `href`, `src` and `<id>`. Only a path of V2's feed is asked of it; anything else is `404`, and the feed is not asked. | 6, and X9: the feed is asked only for what it serves. The Gallery names its root without a slash, the community feed with one. |
| Z8 | A V2 proxy fetches a package from `<feed>package/<id>/<version>`, as the redirect its feed answers with leads, and keeps it where a pushed one is (`v3/package/…`), read as a pushed one is (X4); it serves it at `package/<id>/<version>` alone. | One way of keeping and describing a package; the community feed and the Gallery redirect a download to their storage. |
| Z9 | Over plain HTTP, `choco push` needs `--force`. Over V3, `choco` reads the service index before it pushes, with the credentials of the source saved by `choco source add`: without them it sends an empty name and password again and again, which the limits on failed sign-ins then block. The guide says so. | Observed with `choco` 2.7.4. |
| Z10 | The client tests run `nuget.exe` 6.14.0, checked by its SHA-256, under `mono:6.12`; `chocolatey/choco:v2.7.4-linux`; and `mcr.microsoft.com/powershell:7.5-ubuntu-24.04`, whose PSResourceGet is 1.1.0. Through the proxies, they install `chocolatey-compatibility.extension` from the community feed and `Microsoft.PowerShell.SecretManagement` 1.1.2 from the Gallery. `choco install` on Linux puts a package's files in place and runs none of its scripts. What the client tests share is in `tests/nuget_stack.py`. | Section 10's pinned clients; packages small enough to fetch on every run. |
| Z11 | A group answers no V2 until plan 13e. | Y10: a group answers only what it writes. |

### Settled by the review of plan 13d

| # | What | Why |
| --- | --- | --- |
| Z12 | A V2 proxy asks its feed for an entry, `Packages(Id='…',Version='…')`, only if its id is one NuGet takes and its version one; anything else is `404`, and the feed is not asked (X9 for V2). | An id of `/../../secret` reached the feed as a path of the client's choosing, with the feed's credential. |
| Z13 | Each entry a V2 proxy passes on has its package at the proxy's `package/<id>/<version>`, as the entry's id says; the proxy fetches it from where the feed's entry of it says, the entry kept as any answer is (in place of Z8's `<feed>package/<id>/<version>`). | A feed may serve its packages elsewhere than `package/<id>/<version>`: Nexus at `<id>/<version>`. |
| Z14 | A V2 proxy reads a search's answer to 64 MiB, a kept answer to 16 MiB. | A search is not kept, and the Gallery answers PSResourceGet's `$top=6000` with tens of megabytes: 49 MB for all its modules. |
| Z15 | An order by download counts orders nothing, each being 0: the ids of a query of many are taken in the order of what comes after it, by id if that is the id. | Ordered by `DownloadCount desc,Id`, the ids were taken as V3's search ranks them, and a page of the order by id was cut from those read. |

### Settled while building plan 13e

| # | What | Why |
| --- | --- | --- |
| G1 | A group serves V2 from its hosted members, its V2 proxies and its groups, and V3 from its hosted members, its V3 proxies and its groups: a proxy is left out of the protocol it does not speak, and is not asked it (E3). | A V2 feed cannot be asked V3's questions, nor a V3 feed V2's. |
| G2 | A group's V2 feed is written on each request, as its V3 documents are (Y1). A query is asked of each member for its first `skip + top + 1` entries, with the group's own address: a hosted member writes them, a V2 proxy rewrites its feed's (following the feed's next pages, ten at the most, for as many as are asked), a group merges its own. They are merged in the members' order, an id's version (in lower case, normalized) kept once, the first member's; the page is cut from them, and its next link asks for the same with `$skip` past it (in place of 7.3's `$skiptoken`). | One entry more than the page says whether there is a next one; `$skip` is what the group's own next links need, and what a hosted repository's write (Z3). |
| G3 | A group's count (`/$count`, `$inlinecount=allpages`) is its members' counts less the entries dropped among those it read: a feed is asked its count with `$inlinecount=allpages`, a hosted repository counts its own. | What can be known without reading every member's every entry, as V3's `totalHits` (7.2). |
| G4 | An entry, `Packages(Id='…',Version='…')`, is the first member's that has it, with the group's address; a package at `package/<id>/<version>` is the first member's that has it, as the group engine answers. V2's root and `$metadata` are the group's own. A query that no client sends is refused by the group, before any member is asked. | 7.3, and Y10: a member's own answer would carry its addresses. |
| G5 | A group's V2 order is its members': each member orders what it gives as the query asks, and the group keeps them in the members' order. | 7.3's merging; a group cannot order a feed's entries it has not read. |
| G6 | The Chocolatey test installs, through a group of the hosted repository and the V2 proxy of the community feed, a package pushed to the hosted member and one of the community feed's. | Section 10's `choco` through a group. |

### Settled by the review of plan 13e

| # | What | Why |
| --- | --- | --- |
| G7 | A V2 query that asks for the newest version (`IsLatestVersion`, `IsAbsoluteLatestVersion`) is answered by a group with each id's newest of its members' newest, once, where the id's first entry was; the others are dropped and counted so. | Each member's newest is newest of what it has: a group of a hosted repository and a feed that both had an id listed it twice, and `choco install` without a version could take the older. |
| G8 | A query for which a member's feed still has a next page after the ten a group follows (G2), with fewer entries read than the group asks for, is refused with `400 unsupported_query`, which says to narrow it. | Past the tenth page, the feed seemed to end, its count saying otherwise. |

### Settled while building plan 13f

| # | What | Why |
| --- | --- | --- |
| S1 | A portable PDB is kept and served at `symbols/<name>/<GUID>FFFFFFFF/<name>`: its file's name in lower case, and the GUID of its PDB id as 32 hex digits in lower case, then `FFFFFFFF` (in place of 8's `<GUID><stamp>FFFFFFFF`). Its checksum is the SHA-256 of the PDB with its id's 20 bytes, the GUID and the stamp, set to 0. | SSQP's key of a portable PDB, as `dotnet-symbol` asked for Serilog's from nuget.org's symbol server, with that checksum. |
| S2 | Every `.pdb` of a symbol package's zip is read as it is pushed or uploaded, staged one at a time (at most 1,000, each at most 256 MiB). One that is not a portable PDB refuses the symbol package with `400 invalid_package`, which names it, and nothing of it is kept. Each PDB is a file of the package's version, with its checksum among its attributes. A symbol package pushed again (under `allow_redeploy`) keeps only its own PDBs; deleting a symbol package deletes its PDBs, and deleting a version every file of it (D4). | 8, and one record of what a PDB is, read once (E1). |
| S3 | `SymbolChecksum` names SHA-256 checksums (`SHA256:<hex>`, `;` between them); a PDB is served if one of them is its own, or if none is named; else `404`. | As nuget.org's symbol server answers; a debugger that names none still gets what it asks for by its key. |
| S4 | A proxy with a `symbol_url` asks `<symbol_url>/<name>/<key>/<name>` for a PDB it does not keep, sending the debugger's `SymbolChecksum` (the proxy engine sends a source's own headers with a download, `proxy.Source.headers`); what it is not given is not remembered as missing. A PDB it keeps has its checksum read from it, and a debugger that names another is answered `404` without asking. A proxy without a `symbol_url` has no symbols. A V2 proxy may have one too. | 8; a server that has no file for one checksum may have it for another. |
| S5 | HTTP Basic with no user name and an API token as the password is the token's owner, as with `__token__`; with anything else, a failed attempt counted against the address. | `dotnet-symbol --authenticated-server-path <token>` sends `:<token>`, as Azure DevOps's clients do. |
| S6 | A group asks its members in order for a PDB, as the group engine asks for any file (Y10's files a group passes on, and a PDB). | 8. |
| S7 | A repository's setup has a `Symbols` snippet: the Visual Studio setting, and `dotnet-symbol --authenticated-server-path "$MEGOOARTI_TOKEN" <address>symbols/`. | 8: the setup snippet says so. |
| S8 | The `dotnet` test installs `dotnet-symbol` 10.0.750501 through the proxy of nuget.org, and fetches the PDB of each SDK's package for its DLL from the hosted repository and through the group: the bytes its symbol package has. | Section 10's `dotnet-symbol`. |

### Settled by the review of plan 13f

| # | What | Why |
| --- | --- | --- |
| S9 | A PDB that is kept already, with the same checksum, is left as it is when another version's symbol package has it too: kept once, as a file of the version it came with, and gone with that version. | A build packed twice with two versions gives one PDB: the second symbol package was refused with `409`, which `--skip-duplicate` takes for "already there". |
| S10 | A key is matched without regard to case, and served as it is kept: its name and GUID in lower case, then `FFFFFFFF`. | Symbol servers match keys so; a debugger may ask in the module's own case. |
| S11 | A proxy's symbol server failing does not count towards leaving the proxy's remote alone (`Source(blocks=False)`, which the engine now honours for a download as for a document); the failure is recorded. | One `503` of symbols.nuget.org blocked the proxy's packages, and debuggers ask for a PDB of every module. |

### Settled while building plan 13g

| # | What | Why |
| --- | --- | --- |
| U1 | The repository form has NuGet: a hosted one's deployment policy is `disable_redeploy` until another is chosen, as the server gives one (D6); a proxy chooses its protocol once (V3, the default, or V2), shown as a fact after, and may name a symbol server, checked as a remote's address is, and sent only when one is given; a group of NuGet has its members. The remote's hint says what a V3 and a V2 feed's address is. | X6, Z6 and S4, as an administrator meets them. |
| U2 | NuGet is in every list of formats: the form's, the permissions' rows, and those that take an upload. An upload takes `.nupkg` and `.snupkg` files, several at once, and no directory: each goes where its `.nuspec` says, packages before symbol packages (W7). | W7. |
| U3 | A NuGet repository's page has the setup snippets the server gives (W10, Z6, S7): `dotnet`, `nuget.config`, Chocolatey, PowerShell and Symbols; a version's page its usage. The UI shows them as it shows every format's: it writes none of its own. | One place says how a machine is set up: the server. |
| U4 | The browser test makes a V2 proxy of NuGet in the form, and uploads to a hosted one a package and its symbol package that it writes itself (a zip of stored files, and a portable PDB), and finds the PDB at its key; then the setup snippets and their accessibility. | Section 10's browser tests. |

### Settled by the change for ids pushed into groups

| # | What | Why |
| --- | --- | --- |
| H1 | An id that a hosted repository behind a group holds (through groups in the group too, matched without regard to case) is answered for by the hosted repositories that hold it, alone, in the members' order (in place of Y11 and 7.2's union for such an id): its version list, registration, autocomplete of its versions, package, `.nuspec` and `.snupkg`, and in V2 `FindPackagesById()`, `Packages()` filtered by the id, its entry and `package/<id>/<version>`. Where every one that holds it is offline, the group answers `503 repository_offline` and asks no other member. A search over many ids, and a PDB at its key, are as before. | Ids are not verified: a public package of an id you push, by mistake or on purpose, would otherwise add versions a floating version or `dotnet add package` takes, and stand in for your repository while it is offline. The npm, PyPI and Docker groups keep a pushed name from their other members in the same way (`group.owners`). |

## 5. Hosted repositories

- **Push:** `PUT api/v2/package` with the package as `multipart/form-data` (as every client sends it). The server reads the zip's central directory and its `.nuspec` (bounded, section 9): `id`, `version`, `title`, `authors`, `owners`, `description`, `summary`, `releaseNotes`, `copyright`, `language`, `tags`, `projectUrl`, `license` and `licenseUrl`, `icon` and `iconUrl`, `readme`, `requireLicenseAcceptance`, `developmentDependency`, `minClientVersion`, `packageTypes`, and `dependencies` by target framework; and the package's SHA-512. A file that is not a NuGet package, or whose `.nuspec` has no id or no valid version, is refused with `400 invalid_package`. The package is stored at `v3/package/<id>/<version>/<id>.<version>.nupkg` (lower case, E2), and its `.nuspec` beside it.
- **Push of a version that is there:** `409` under `disable_redeploy`, the default (D6); `allow_redeploy` replaces it; `read_only` refuses every push.
- **Push of a `.snupkg`:** `PUT api/v2/symbolpackage`, or `api/v2/package` (as older clients do). Its `.nuspec` must name a package version the repository has (`404` otherwise); it is stored beside it, and section 8 says what is read of it.
- **Delete:** `DELETE api/v2/package/<id>/<version>`, the web UI or the API removes the version and every asset of it (D4). A version that is not there is `404`.
- **V3:** the version list, registration and search are written from the records of 5's push (E1), as the repository's revision has them, and written on each request (W1). Registration has every version of an id, inlined up to 128 versions and in pages of 64 beyond (W14); a version's entry has its `.nuspec`'s fields, its dependency groups, `packageContent`, `published` (the time it was pushed) and `listed: true`.
- **V2:** `Packages()`, `FindPackagesById()`, `Search()` and `Packages(Id,Version)` are answered from the same records, as Atom feeds of `m:properties` with the properties the clients read (`Id`, `Version`, `NormalizedVersion`, `Title`, `Description`, `Authors`, `Tags`, `Dependencies`, `IsLatestVersion`, `IsAbsoluteLatestVersion`, `IsPrerelease`, `Published`, `PackageHash`, `PackageHashAlgorithm`, `PackageSize`, `DownloadCount` and the others of nuget.org's `$metadata`). The queries a hosted repository answers are those of 7.3.
- **Search:** over id, title, description, tags and authors, as `q` says (`id:` and `packageid:` as nuget.org reads them), with `prerelease` and `semVerLevel`; ranked with an exact id first, then the id's beginning, then the rest; `totalHits` as asked. MegooArti counts no downloads: a hosted package's download count is 0, and an order by downloads keeps the order by relevance.
- **Usage:** `dotnet add package <id> --version <version>`, `<PackageReference Include="<id>" Version="<version>" />`, `Install-Package <id> -Version <version>`, `choco install <id> --version <version>`, `Install-PSResource <id> -Version <version>`.
- **Setup** (as the Linux formats' V1): `dotnet nuget add source <address>index.json -n <name> -u "$MEGOOARTI_USER" -p "$MEGOOARTI_TOKEN" --store-password-in-clear-text`, the same as a `nuget.config` source, `choco source add -n <name> -s <address> -u … -p …`, and `Register-PSResourceRepository -Name <name> -Uri <address>index.json`.

## 6. Proxy repositories

- **Settings:** `format_config.protocol`, `v3` (the default) or `v2`, fixed after creation (D2). The remote is a V3 service index (`https://api.nuget.org/v3/index.json`) or a V2 feed's root (`https://community.chocolatey.org/api/v2/`, `https://www.powershellgallery.com/api/v2/`). `format_config.symbol_url`, optional, is a symbol server to proxy (`https://symbols.nuget.org/download/symbols`; section 8).
- **A V3 proxy** reads its remote's service index for its `PackageBaseAddress/3.0.0`, its gzipped SemVer 2.0.0 registration (`RegistrationsBaseUrl/3.6.0`, or the newest it has), and its `SearchQueryService` and `SearchAutocompleteService`. They may be on other hosts than the index (nuget.org's are). It serves a service index of its own (4.2) and rewrites the remote's addresses in what it passes on: the registration's `@id`, `registration`, `packageContent` and `items` page addresses, and search results' `@id` and `registration`. A page or a version's document is asked of the feed's registration by the same path (X3).
- **A V2 proxy** passes a client's query on as it came (its path and query string) and rewrites the remote's addresses in the Atom it answers with: `xml:base`, each entry's `id` and `content src`, its `edit-media` link, and the `next` link of a page. `$metadata` is its remote's.
- **Caching:** a `.nupkg`, `.nuspec` and `.snupkg` never change: kept for good. The service index, version lists, registration pages and V2 query answers are metadata, checked again after the metadata age; a V2 answer is kept by its whole query. Search is passed on every time and not kept. What the remote does not have is remembered (the negative cache), as for every proxy.
- **What a proxy keeps** of a package it fetched is read as a pushed one is (5), so that it can be browsed, found by MegooArti's own search and deleted.
- **Remote sign-in, blocking, and the rest** are those of every proxy.

## 7. Group repositories

### 7.1 Members and protocols

A group's members are in order. It serves V3 from those that speak V3, and V2 from those that speak V2 (E3). It signs and checks nothing (E4).

### 7.2 V3

- **Version list:** the union of the members' lists, sorted; of an id a hosted member holds, its holders' alone (H1).
- **A package, its `.nuspec` or `.snupkg`:** fetched from the first member that has it.
- **Registration:** written by the group (E5): for an id, every version any member has, a version several members have taken from the first; in pages of 64, with the group's addresses.
- **Search and autocomplete:** each member is asked for its first `skip + take` results; the answers are merged in member order, the first result for an id kept, and the page asked for is cut from them. `totalHits` is the sum of the members' less the ids dropped, which is what can be known. `skip + take` is at most 3,000 (section 9).
- **Caching:** none of the group's own: a version list, a registration and a search are written on each request from what the members keep (Y1).

### 7.3 V2

- **What a group answers:** the queries the clients of D7 send: `FindPackagesById()?id='…'`; `Packages(Id='…',Version='…')`; `Packages()` with a `$filter` of `Id eq '…'`, `tolower(Id) eq '…'`, `IsLatestVersion`, `IsAbsoluteLatestVersion` and `and` between them; `Search()` with `searchTerm`, `targetFramework`, `includePrerelease` and such a `$filter`; `$orderby` of `Id`, `Version`, `DownloadCount desc`, `Published desc` or `LastUpdated desc`; `$skip`, `$top`, `$skiptoken` and `$inlinecount`; `semVerLevel`. The plans pin the list to what the clients send, observed against a hosted repository and recorded in the tests.
- **Anything else** is refused with `400` and a message naming what is not supported: MegooArti does not pass an unknown OData query to every member and pretend to merge it.
- **Merging:** as V3's search: each member is asked for the query with `$top` and `$skip` replaced by its first `skip + top` entries, the answers merged in member order, the first entry for an id and version kept, and the page cut from them, with the group's own `next` link (E5).

## 8. The symbol server

- **At push of a `.snupkg`:** each `.pdb` in it must be a portable PDB (metadata signature `BSJB`); a Windows PDB, or a `.pdb` that is neither, is refused with `400 invalid_package`, as nuget.org refuses it. Its PDB id (a GUID and a stamp, from the `#Pdb` stream) and its checksum (SHA-256 of the file with the id's bytes zeroed, as the debug directory's `PdbChecksum` holds it) are read, and the PDB is kept as an asset of the package's version at `symbols/<name.pdb>/<GUID>FFFFFFFF/<name.pdb>` (S1), with the name in lower case (SSQP's key for a portable PDB). Deleting the version deletes it (D4).
- **Serving:** `GET symbols/…` reads that asset under the repository's `read` permission. A client that sends `SymbolChecksum` (Visual Studio and `dotnet-symbol` do) is served the PDB only if one of the checksums it names is the PDB's; otherwise `404`, as nuget.org's symbol server answers.
- **A proxy with `symbol_url`** passes `symbols/…` on to `<symbol_url>/…` with the client's `SymbolChecksum`, and keeps what it is given for good. A proxy without one answers `404` there.
- **A group** asks its members for a `symbols/…` path in order.
- **Clients:** Visual Studio's symbol locations take `<address>symbols/`; `dotnet-symbol --authenticated-server-path <token> <address>symbols/`. The guide and the setup snippet say so.

## 9. Errors and limits

- What is read of a package is bounded: its zip's central directory at 10,000 entries, its `.nuspec` at 1 MiB, a `.snupkg`'s PDBs at 1,000 and each at 256 MiB. The zip is read from its directory; nothing is unpacked but the `.nuspec` and the PDBs, each to its bound. Beyond a bound the package is refused with `400 invalid_package`.
- A V3 search takes at most 1,000 results, and `skip + take` is at most 3,000; more is refused with `400`. A V2 page is at most 100 versions, the default: a `$top` above it is answered with a page and the address of the next (Z3).
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
| A popular id has thousands of versions (registration pages, a group's merge). | Pages of 64 beyond 128 versions, each written from its own versions (W14); a version list from the versions alone (W13). A search still reads every version of each id on its page: measured in plan 13c (Y1, Y7). |
| `nuget.exe` under Mono, and Chocolatey on Linux, are less maintained than their Windows builds. | The tests pin images that work; if one stops being published, the plan says so and the test is replaced by the nearest client that is. |
| The PowerShell Gallery and the Chocolatey community feed rate-limit, or are slow. | The tests fetch a few small packages, as the Linux formats' tests do of their mirrors. |
| A portable PDB's checksum is not what the debugger sends. | Plan 13f checks it against `dotnet-symbol` and a PDB built by `dotnet pack`. |

## 12. Plans

| Plan | What it builds |
| --- | --- |
| 13a | The `nuget` format: reading packages, hosted repositories over V3 (service index, package contents, registration, search, push, delete), `X-NuGet-ApiKey`, the deployment policy's default, its `dotnet` tests and `docs/formats/nuget.md`. |
| 13b | V3 proxies (6). |
| 13c | V3 groups (7.2), search merged, and NuGet Audit's data passed on (Y6). |
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
