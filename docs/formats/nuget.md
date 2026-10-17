# NuGet repositories

What is true of every repository is in [Repositories](../repositories.md). This is
what is this format's own: .NET packages, pushed and restored with `dotnet` and
`nuget.exe`; Chocolatey's packages; and PowerShell's modules.

A hosted repository holds the packages you build, and serves them over NuGet's V3
protocol, as nuget.org does. Its address for a client is the repository's own, then
`index.json`:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "nuget-hosted", "format": "nuget", "type": "hosted"
}' http://localhost:8000/api/v1/repositories
```

On each machine that pushes to it or restores from it: the repository as a source, with
the account `dotnet` signs in with. The repository's page in the web UI gives these,
with its own address, under "Set up a machine".

```bash
dotnet nuget add source https://repo.example.com/repository/nuget-hosted/index.json \
  --name megooarti --username ci --password "$MEGOOARTI_TOKEN" \
  --store-password-in-clear-text
```

Then push to the source by its name, not by its address: `dotnet` reads the
repository's `index.json` before it pushes, with the source's credentials, and sends
the API key with the push alone.

```bash
dotnet pack -c Release
dotnet nuget push bin/Release/MegooArti.Hello.1.0.0.nupkg \
  --source megooarti --api-key "$MEGOOARTI_TOKEN"

dotnet add package MegooArti.Hello --version 1.0.0
```

Or in the project's `nuget.config`, which `dotnet` and Visual Studio both read. NuGet
puts the values of environment variables in place of `%NAME%`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <add key="megooarti" value="https://repo.example.com/repository/nuget-hosted/index.json" />
  </packageSources>
  <packageSourceCredentials>
    <megooarti>
      <add key="Username" value="%MEGOOARTI_USER%" />
      <add key="ClearTextPassword" value="%MEGOOARTI_TOKEN%" />
    </megooarti>
  </packageSourceCredentials>
</configuration>
```

The same repository serves NuGet's V2 protocol too, at its own address with nothing
after it (`https://repo.example.com/repository/nuget-hosted/`), for clients that speak
V2: `nuget.exe`, Chocolatey's `choco` and PowerShell's PSResourceGet, which speak V3
as well. A V2 client pushes to that address, and deletes under it.

```bash
# nuget.exe, here under Mono: the source with its credentials, then a push to it by name.
mono nuget.exe sources add -Name megooarti \
  -Source https://repo.example.com/repository/nuget-hosted/ \
  -Username ci -Password "$MEGOOARTI_TOKEN" -StorePasswordInClearText
mono nuget.exe push MegooArti.Hello.1.0.0.nupkg -Source megooarti -ApiKey "$MEGOOARTI_TOKEN"
mono nuget.exe install MegooArti.Hello -Version 1.0.0 -Source megooarti

# Chocolatey: --force pushes over plain HTTP, which choco otherwise refuses.
choco source add --name=megooarti \
  --source="https://repo.example.com/repository/nuget-hosted/" \
  --user="$MEGOOARTI_USER" --password="$MEGOOARTI_TOKEN"
choco push hello.1.0.0.nupkg --source="https://repo.example.com/repository/nuget-hosted/" \
  --api-key="$MEGOOARTI_TOKEN"
choco install hello --version 1.0.0
```

```powershell
# PSResourceGet: V2's address without its slash, as it adds one, and told it is V2.
# Or the repository's index.json, which it knows for V3 by itself.
Register-PSResourceRepository -Name megooarti -Trusted `
  -Uri https://repo.example.com/repository/nuget-hosted -ApiVersion v2
$credential = Get-Credential -UserName ci   # an API token as the password
Publish-PSResource -Path ./MegooArti.Hello -Repository megooarti -ApiKey $env:MEGOOARTI_TOKEN `
  -Credential $credential
Install-PSResource MegooArti.Hello -Repository megooarti -Credential $credential
```

A proxy caches a feed of V3: nuget.org, or any feed that serves NuGet's V3 protocol.
Its remote is the feed's service index:

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "nuget-org", "format": "nuget", "type": "proxy",
  "proxy": {"remote_url": "https://api.nuget.org/v3/index.json"}
}' http://localhost:8000/api/v1/repositories

dotnet nuget add source https://repo.example.com/repository/nuget-org/index.json \
  --name nuget-org --username ci --password "$MEGOOARTI_TOKEN" \
  --store-password-in-clear-text
```

A proxy of a V2 feed, the Chocolatey community feed or the PowerShell Gallery, speaks
V2 to it and serves V2 alone: its `format_config.protocol` is `v2`, and its remote is
the feed's address. Give clients the proxy's own address, as for V2 above.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "choco-community", "format": "nuget", "type": "proxy",
  "format_config": {"protocol": "v2"},
  "proxy": {"remote_url": "https://community.chocolatey.org/api/v2/"}
}' http://localhost:8000/api/v1/repositories
```

A group is one feed of its members': a machine whose one source is the group restores
the packages you push and nuget.org's alike. Push to a hosted member, not to the group.

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "nuget-public", "format": "nuget", "type": "group",
  "group": {"members": ["nuget-hosted", "nuget-org"]}
}' http://localhost:8000/api/v1/repositories
```

- **Credentials.** A push's API key is an API token (`--api-key`, sent as
  `X-NuGet-ApiKey`); so is the password of a source's credentials. A user name and a
  password work for a source too. NuGet's clients refuse a plain-HTTP source unless it
  is marked so: `allowInsecureConnections="true"` on its line of `nuget.config`, or
  `--allow-insecure-connections` to `dotnet nuget add source` of the .NET SDK 9 and
  later (.NET 8 only warns). Use HTTPS.
- **A push** is `dotnet nuget push`, or the web UI or [the API](../api.md#uploading)
  with one or more `file` fields. What is read of a package is its `.nuspec`, at most
  1 MiB, from a zip of at most 10,000 files: the zip is never unpacked. A file that is
  not a NuGet package, or whose `.nuspec` has no id or no version NuGet takes, is
  refused with `400 invalid_package`. A package of 4 GiB or more (a ZIP64 file) is
  refused too.
- **A version is pushed once.** A hosted NuGet repository's deployment policy is
  `disable_redeploy` unless you choose another: a second push of a version answers
  `409`, which `dotnet nuget push --skip-duplicate` takes for "already there". With
  `allow_redeploy` it replaces the version.
- **Ids are matched without regard to case**, as NuGet's clients match them: the first
  push of an id spells it, and later versions are kept under that spelling. A version
  is normalized as NuGet normalizes it (`1.0` is `1.0.0`, and build metadata is left
  out). Addresses are in lower case.
- **Symbol packages** (`.snupkg`, made by `dotnet pack` with `--include-symbols
  -p:SymbolPackageFormat=snupkg`) are pushed with their package by `dotnet nuget push`,
  and kept beside it. One pushed before its package is refused with `404`.
- **Deleting** a version (`dotnet nuget delete <id> <version>`, which needs the
  `delete` permission, or the web UI) removes it and its every file: its package, its
  `.nuspec` and its symbol package. A package's `.nuspec` cannot be deleted on its own.
- **A hosted repository's feed is written from its packages** on each request: an id's
  versions, its registration (inlined up to 128 versions, then in pages of 64) and
  search. Nothing is stored but the packages, so the feed is right after every push and
  delete.
- **Search** (`dotnet package search`, and Visual Studio's Browse tab) finds an id by
  the words of its id, title, description, tags and authors; `packageid:<id>` finds one
  id exactly, and `id:<text>` the ids that contain it. Prereleases are found when they
  are asked for. A search takes at most 1,000 results, and none past the 3,000th.
  MegooArti counts no downloads.
- **A proxy's remote** is a feed's `index.json`. The proxy reads in it where the feed
  serves its packages, its registrations and its search (nuget.org searches on another
  host), and serves an `index.json` of its own, with its own addresses and no place to
  push to. A package and its `.nuspec` are kept, and read as a pushed one is, so that
  the web UI and MegooArti's search find them. An id's versions and its registration are
  checked again with the remote after `metadata_max_age_minutes`; what the proxy passes
  on of them has the feed's addresses made its own. A search is passed on to the feed
  every time, and not kept. A proxy's `format_config.protocol` is `v3`, the default;
  `format_config.symbol_url` names a symbol server to proxy, which a later version
  serves. A search that fails is said to have failed, and does not stop the proxy
  fetching packages.
- **V2's feed** answers the queries that `nuget.exe`, `choco` and PSResourceGet send:
  `FindPackagesById()`, `Packages(Id='…',Version='…')`, `Packages()` and `Search()`,
  with a `$filter` of an id, a version or a range of versions, the newest version,
  prereleases, the start of an id, words of an id or of its tags, and `and` between
  them; `$orderby`, `$skip`, `$top`, `$inlinecount` and `/$count`. A page has at most
  100 versions, and a link to the next. Another query is refused with
  `400 unsupported_query`, which names what is not answered. A package is at
  `package/<id>/<version>`. MegooArti counts no downloads: each count is 0.
- **A V2 proxy** passes a query on to its feed as it came, and gives the feed's answer
  with the feed's addresses made its own. An answer is kept by its whole query, and
  asked about again after `metadata_max_age_minutes`; a `Search()` is passed on every
  time. A version's package is at the proxy's `package/<id>/<version>`, fetched from
  where the feed's entry says; it is kept, and read as a pushed one is. The proxy serves no
  `index.json`: clients are given its V2 address. Its protocol cannot change once it
  is made.
- **A group's feed is written from its members'** on each request, in the order they
  are listed: an id's versions are every member's together, and its registration is
  the group's own, with the first member's details of a version that several members
  have (inlined up to 128 versions, then in pages of 64). A search, and autocomplete,
  ask each member and list an id once, as the first member that found it has it. A
  package, its `.nuspec` and its symbol package come from the first member that has
  them. A member that is offline, or whose feed cannot be reached, is passed over.
  Every address in what a group serves is its own.
- **A group serves V2 too**, at its own address, from its hosted members, its V2
  proxies and its groups; V3 comes from its hosted members, its V3 proxies and its
  groups. Chocolatey given a group of a hosted repository and a proxy of the community
  feed installs what you push and the feed's packages alike. A V2 query is asked of
  each member, the answers listed in the members' order, an id's version once, as the
  first member that has it has it; the group writes its own pages, and its own links
  to the next. The newest version of an id is the newest any member has. A group reads
  ten of a feed's pages for a query at the most: a page past them is refused with a
  `400` that says to narrow the query.
- **An id is every member's in a group.** A public package with the id of one you push
  adds its versions beside yours: a floating version (`1.*`) or `dotnet add package`
  without a version can take a version of nuget.org's. Give your packages a prefix
  reserved for you on nuget.org, or have machines use the hosted repository and the
  proxy as two sources, with NuGet's package source mapping
  (`<packageSourceMapping>` in `nuget.config`) naming the source each id comes from.
- **NuGet Audit** (the warnings `dotnet restore` gives for a package with a known
  vulnerability, such as `NU1903`) reads its data from a source's `index.json`. A proxy
  passes on its feed's data, nuget.org's for a proxy of nuget.org, kept and checked
  again after `metadata_max_age_minutes`; a group passes on its first member's that has
  any. A hosted repository has none: a machine whose only source is a hosted repository
  warns `NU1905`, unless `nuget.config` names a source of the data in
  `<auditSources>`.

## Clients

Tested with `dotnet` of the .NET SDKs 10 and 8: a package and its symbol package built
with `dotnet pack`, pushed with an API key, pushed again with `--skip-duplicate`,
found with `dotnet package search`, restored into a project, and deleted; and, through
a proxy of nuget.org, a package restored into a project that runs, found with
`dotnet package search`, and its newer versions listed by `dotnet list package
--outdated`; through a group of the two, a project that restores a pushed package and
one of nuget.org's and runs, both found with `dotnet package search`, and newer versions
listed; and through the proxy and through the group, NuGet Audit's warning of a package
with a known vulnerability.

Tested with `nuget.exe` 6.14 under Mono 6.12, over V2 and over V3: a package built
with `nuget pack`, pushed, installed at a version and at its newest, listed (over V2),
and deleted. With Chocolatey's `choco` 2.7.4 of its Linux image, over V2 and over V3: a
package built with `choco pack`, pushed, found with `choco search` and installed;
through a V2 proxy of the community feed, a package installed; and through a group of
the two, a pushed package found and installed, and one of the community feed's
installed. With PowerShell 7.5's
PSResourceGet 1.1, over V2 and over V3: a module published, found by a range of
versions, installed and imported; and, through a V2 proxy of the PowerShell Gallery, a
module installed.
