# Linux package formats: design

**Date:** 2026-10-14
**Plans:** 12a (signing keys, APT hosted and proxy), 12b (APT groups), 12c (YUM), 12d (Alpine), 12e (the web UI)
**BRD:** FMT-12 (APT), FMT-13 (YUM), SEC-9; and Alpine, which the BRD does not have yet (section 3, D7)

## 1. Goal

Debian and Ubuntu machines install through MegooArti with `apt`, Fedora and Rocky Linux machines with `dnf`, and Alpine machines with `apk`: from a cache of the public mirrors, from repositories of an organisation's own packages, and from one address that has both. NuGet follows in a spec of its own (D2).

**Success looks like this:**

- A container built in CI runs `apt-get install`, `dnf install` or `apk add` against MegooArti, and nothing is fetched twice from the internet.
- A team uploads the `.deb`, `.rpm` or `.apk` it built, and every machine that trusts the repository's key installs it, with the client's signature checks on.
- One group address serves a team's own packages and the distribution's, and a client that trusts the group's key cannot be given a package the distribution did not publish or the team did not upload.
- A client that does not trust the key a repository signs with refuses it.

## 2. Scope

**In scope:**

- Three formats, `apt`, `yum` and `apk`, each with hosted, proxy and group repositories (D1, D4).
- Signing keys for hosted repositories and groups: generated, or imported by an administrator (D3).
- Upload by the format's own path (`PUT`) and through the upload API and the web UI.
- Browse, search, delete and usage snippets, as every format has them.
- The real-client tests of section 10 (D5), and a guide for each format.

**Out of scope:**

| What | Why |
| --- | --- |
| NuGet | Its own spec, after these (D2). |
| Signing packages | A package's signature is its builder's. MegooArti signs the indexes it writes, never a package. |
| zypper, microdnf, `dput` and other publishing tools | D5. |
| Debian's "flat" repositories, source packages (`.dsc`, `Sources`), `Contents-*`, `Translation-*` that a hosted repository would write | Clients install binary packages from the standard layout. A proxy passes on whatever its remote has. |
| YUM's SQLite databases, and a hosted repository's `comps`, `modules` and `updateinfo` | dnf reads the XML. A proxy passes on what its remote has; section 7 says what a group does with them. |
| Several suites or components in one hosted APT repository | One suite and the component `main` per hosted repository (A1). Several suites are several repositories, and a group can put them behind one address. |
| A period in which an old and a new key both sign | A2. |

## 3. Decisions

The product owner's:

| # | Decision | Choice |
| --- | --- | --- |
| D1 | What the formats are for | Both: caching public mirrors, and hosting an organisation's own packages, as the BRD says. |
| D2 | Order | The Linux formats first, NuGet after them, each family with its own spec. |
| D3 | Where a signing key comes from | MegooArti generates one when a hosted repository or a group is made, and an administrator may import their own in its place. |
| D4 | Groups | All three formats have them: a group merges its members' indexes and signs them with its own key. |
| D5 | Clients the tests run | apt on Debian stable and Ubuntu LTS; dnf on Fedora and Rocky Linux; apk on the two newest Alpine releases. No other. |
| D6 | Shape of the work | One spec for the three formats, a plan for each (section 12). |
| D7 | Alpine | Added to the BRD as FMT-24: "**Alpine (apk)**: hosted, proxy and group, with the index signed by a key the administrator supplies or MegooArti generates." |

Settled here, by the designer:

| # | What | Why |
| --- | --- | --- |
| A1 | A hosted APT repository has one suite, chosen when it is made (default `stable`) and fixed after, and the component `main`. | It is what an organisation's own repository needs, and every path of the repository follows from it. |
| A2 | Replacing a key replaces it: from that moment the indexes are signed with the new key only. The web UI asks before it does so, and says that every client must install the new public key. | Signing with two keys at once is possible in APT and not in the other two; a rotation that works for one format only would be a trap. |
| A3 | The format names are `apt`, `yum` and `apk`: the names of the clients, as the BRD's FMT rows and Nexus have them. | A repository's format is what its clients speak. |
| A4 | OpenPGP keys are Ed25519 unless an administrator asks for RSA 4096 when generating, or imports another. Alpine's keys are RSA 4096. | Ed25519 is what current apt and dnf verify, and it is small and fast; RSA is there for older clients. apk knows RSA only. |

## 4. The shared parts

### 4.1 Formats

Each format is a `Format` subclass, as Maven, npm and PyPI are: served under `/repository/<name>/`, through the gateway's existing route. Packages have no namespace in any of the three, so permissions are `repository:<format>:<name>:<action>` with the usual actions.

The interface changes in one place: `describe_component` is given the asset's `attributes` as well as its path. A Debian package's name and version can be read from its pool path, which the server writes; an RPM's or an apk's file name cannot be split into name and version without knowing which dash is which, so those formats read them from what was kept of the package at upload.

### 4.2 Signing keys

- **One key per hosted repository and per group**, made with the repository. A proxy has none: it passes its remote's signatures on.
- **Kinds:** OpenPGP for `apt` and `yum`, RSA for `apk` (A4).
- **Stored** in a new table `signing_keys`: the repository, the kind, the algorithm, the public key, the private key sealed with the installation's secret key (as a proxy's password is), the fingerprint, and when it was made. The private key never leaves the server: no API answers with it. It is in a backup, with the database, and is useless without the secret key, which is in the data directory's backup.
- **The public key** is at a fixed path of the repository, readable by whoever may `read` the repository:
  - `apt` and `yum`: `/repository/<name>/public.key` (ASCII-armoured).
  - `apk`: `/repository/<name>/<keyname>.rsa.pub`, where `<keyname>` is `megooarti-<name>`: apk finds a key by its file name, so the file is offered under the name a client must save it as.
- **Administration:** `GET /api/v1/repositories/<name>/signing-key` (the kind, algorithm, fingerprint, public key and when it was made), `PUT` of the same path with an armoured or PEM private key to import one, and `POST /api/v1/repositories/<name>/signing-key/generate` (with `{"algorithm": "ed25519" | "rsa4096"}` for OpenPGP) for a new one. All three need `admin:repositories:read` or `:write`. An imported key must be one the format can sign with, must not be protected by a passphrase, and is refused with `422` at `body.private_key` otherwise; an OpenPGP key must be able to sign.
- **Deleting the repository** deletes its key.

### 4.3 Indexes are derived, and cached by revision

What the server derives from the packages, it does not store (as Maven's metadata and PyPI's pages are not stored):

- **At upload**, the package is read once: its control fields go into the asset's `attributes`. The file is streamed into the blob store as every upload is, and read from there; what is read of it is bounded (section 9).
- **When asked**, `Packages`, `Release`, `InRelease`, `Release.gpg`, `repomd.xml` and its signature, the `repodata/` files and `APKINDEX.tar.gz` are written from those records and signed.
- **A repository has a revision**, a number in its row that the transaction which adds, replaces or deletes one of its assets raises, with the time of that change. An index is written for one revision, and is the same for as long as the revision is: its dates are the revision's time, not the moment it was asked for. A written index is kept in the process, by repository, revision and path, so that a large repository is not read through for every request; a new revision makes the old entries unreachable.
- **One revision is one snapshot.** Everything an index names is read in the same transaction as the index, so a signed index and the files and hashes it names agree.
- **The YUM `repodata/` files carry their hash in their names**; `repomd.xml` names them. A client that fetched `repomd.xml` of one revision can fetch the files it names for as long as that revision is the newest or the one before it (both are kept).

### 4.4 Proxies

- A proxy's index files (`dists/` of APT, `repomd.xml` of YUM, `APKINDEX.tar.gz` of apk) are metadata: checked again after the proxy's metadata age, as npm's and PyPI's are. Packages never change, and neither do files whose path holds their hash (APT's `by-hash/`, YUM's `repodata/<hash>-*`): they are cached for good.
- The client checks the distribution's own signatures, as it would without MegooArti.
- **A proxy may be given its remote's public keys** (`format_config.remote_keys`: armoured OpenPGP keys for `apt` and `yum`, PEM RSA keys for `apk`). A proxy uses them only as a member of a group (4.5). They are not secret.

### 4.5 Groups

- A group merges its members' indexes and signs the result with its own key. For the same package (as each format says in sections 5 to 7), the first member that has it wins. A file is fetched from the first member that has its path.
- **A group checks what it re-signs.** A client of a group trusts the group's key and nothing else, so the group does what the client would have done:
  - an APT or apk proxy can be added to a group only if it has its remote's keys, and the group verifies the member's signed index with them before merging it;
  - a YUM proxy's keys are optional (section 6.4);
  - every index the group reads is checked against the hashes its member's signed index gives for it.
- **A member whose index fails a check is left out of the merge**, with a log line (`group_member_unverified`, with the member and the reason), and the reason as the member's last error on its repository page. The group answers with the others.
- **A merged index is cached** by the revisions of its hosted members and the content hashes of its proxy members' indexes, so that it is merged again only when one of them changed.

### Settled while building plan 12a

| # | What | Why |
| --- | --- | --- |
| P1 | OpenPGP is done with `pysequoia` (Sequoia), not GnuPG: Ed25519 and RSA 4096 keys that never expire, clear and detached signatures, and keys GnuPG exported. apt on Debian 13 and Ubuntu 26.04 verifies what it signed. The wheel has Sequoia's library built in, which is LGPL-2.0-or-later; MegooArti's own code stays MIT and uses it as a library. | The risk of section 11, settled by its test. GnuPG would have been a program in the image and a process for every signature. |
| P2 | A key is made the first time it is needed (an index, the public key, or `GET .../signing-key`), not in the request that makes the repository; of two requests that find none at once, the first one's is kept. | One path for every repository, however it was made and whenever. To whoever uses it, 4.2's "made with the repository" and this cannot be told apart. |
| P3 | `InRelease` signs `Release` without its last line ending, as GnuPG does. | Sequoia would otherwise sign a blank line more than `Release` has. |
| P4 | `Packages` is written byte for byte as `dpkg-scanpackages` writes it: the control fields in the package's own order, the file and its checksums before `Section`, and a blank line after each paragraph. `Release` lists `MD5Sum` and `SHA256`. | Section 10, held against what dpkg-scanpackages 1.22 wrote of four real packages. |
| P5 | A component of a hosted repository is a package's name and its version with its epoch, read from what was kept of its `control`; a proxy's package is read from its file's name, which has no epoch. The change to `describe_component` (4.1) is in plan 12a. | `apt install name=version` needs the epoch, which the pool path does not have. |
| P6 | The revision is raised after a path's lock and before a blob's or a component's, and also when a key is replaced. A snapshot reads the revision before and after the files, and again if they differ, five times at most (then `503 repository_busy`). | Changes to one repository wait for each other in one order, and an index never names a file its revision does not have. |
| P7 | What is read of a staged upload is closed as soon as it has been read. | On Windows a file still open can be neither moved into the store nor removed. |
| P8 | The changelog gains APT when the version that has it is released. | Its first heading must be the version the code says it is. |

## 5. APT

### 5.1 Layout

The standard Debian layout:

```
dists/<suite>/InRelease
dists/<suite>/Release
dists/<suite>/Release.gpg
dists/<suite>/main/binary-<arch>/Packages      (and .gz, .xz)
pool/main/<letter>/<package>/<package>_<version>_<arch>.deb
```

`<letter>` is the package's first letter, or its first four for a name that begins with `lib`, as Debian has it.

### 5.2 Hosted

- **Settings:** `format_config.suite`, a name of letters, digits, `.`, `_` and `-` (default `stable`), fixed after creation (A1).
- **Upload:** a `.deb` by `PUT` or `POST` to the repository's root (`curl --upload-file app_1.0_amd64.deb https://repo.example.com/repository/apt-hosted/`), or through the upload API (one or more `file` fields) and the web UI. The server reads the package's `control` file from its `control.tar` (compressed with gzip, xz, zstd or nothing), and stores the package at its pool path. A file that is not a Debian package, or whose `control` has no `Package`, `Version` or `Architecture`, is refused with `400 invalid_package`. A `PUT` to any other path is refused with `405`.
- **What is a component:** a package name and version. Each architecture's `.deb` is one of its assets. The deployment policy applies to the same name, version and architecture.
- **Architectures** are those of the uploaded packages. An `Architecture: all` package is listed under every one of them; a repository with only `all` packages lists them under `amd64` and `arm64`, so that a client finds them.
- **`Packages`** has, for each package, its `control` fields as uploaded, then `Filename`, `Size`, `MD5sum`, `SHA1`, `SHA256` and `SHA512`, sorted by name, version (Debian's ordering) and architecture. It is served uncompressed, `.gz` and `.xz`.
- **`Release`** has `Origin: MegooArti`, `Label: <repository>`, `Suite` and `Codename` (both the suite), `Date` (the revision's time), `Architectures`, `Components: main`, `Acquire-By-Hash: no`, and `MD5Sum` and `SHA256` lists of every `Packages` file. `InRelease` is it clear-signed; `Release.gpg` is its detached signature.
- **Usage:** `apt install <name>=<version>`. The repository's own snippet: fetch the key to `/etc/apt/keyrings/<repository>.asc`, and `deb [signed-by=/etc/apt/keyrings/<repository>.asc] https://repo.example.com/repository/<repository> <suite> main`.

### 5.3 Proxy

The remote is a mirror's root (`http://deb.debian.org/debian`, `http://archive.ubuntu.com/ubuntu`). Paths are passed on as they are; 4.4 says what is metadata.

### 5.4 Group

- A group serves the suites its members have. For a suite, its `Release` names the components and architectures any member has for it; each `Packages` is the merge of that file of every member that has it, the same name, version and architecture taken from the first. `Filename` stays the member's own, and `pool/` files are asked of the members in order.
- A proxy member's `InRelease` is verified with its `remote_keys`, and each `Packages` it gives is checked against the `SHA256` of that `Release` before it is merged (4.5). A proxy member reads `Packages.xz` or `Packages.gz`, whichever its `Release` names.
- The group's `Release` has `Acquire-By-Hash: no`; `by-hash/` paths are asked of the members as any path is.

## 6. YUM

### 6.1 Layout

Packages are at the paths their uploaders give them. Next to them:

```
<directory>/repodata/repomd.xml
<directory>/repodata/repomd.xml.asc
<directory>/repodata/<sha256>-primary.xml.gz
<directory>/repodata/<sha256>-filelists.xml.gz
<directory>/repodata/<sha256>-other.xml.gz
```

### 6.2 Hosted

- **Settings:** `format_config.repodata_depth`, 0 to 5 (default 0), fixed after creation. At depth 0 there is one `repodata/` at the root, for every package. At depth 2 there is one in each directory two levels down (`el9/x86_64/repodata/`), for the packages under it. A package must be uploaded at that depth or deeper, or it is refused with `400 invalid_path`.
- **Upload:** a `.rpm` by `PUT` to its path, or through the upload API and the web UI with a `directory` field. The server reads its lead and header: name, epoch, version, release, arch, summary, description, licence, URL, vendor, group, build host, source RPM, build time, installed size, the header's byte range, the dependencies (`provides`, `requires` with `pre`, `conflicts`, `obsoletes`, and the weak ones: `recommends`, `suggests`, `supplements`, `enhances`), the file list and the changelog. A file that is not an RPM is refused with `400 invalid_package`; so is a source RPM.
- **What is a component:** a name and its `epoch:version-release`. Each architecture's file is one of its assets. The deployment policy applies to the path.
- **`primary.xml`** has every package's fields as `createrepo_c` writes them, with the files in `/etc/`, in a `bin/` directory and in `/usr/lib/sendmail`; `filelists.xml` has every file; `other.xml` the changelogs (the ten newest). `repomd.xml` names the three with their checksums, sizes and the revision's time, and is signed as `repomd.xml.asc`.
- **Usage:** `dnf install <name>-<version>-<release>`. The repository's own snippet is a `.repo` file with `baseurl=` (for depth 0, or with the directory to fill in), `gpgcheck=1` or `0` as the packages are signed or not, `repo_gpgcheck=1` and `gpgkey=` the public key.

### 6.3 Proxy

The remote is a repository's base (a Fedora or Rocky mirror's `…/os/` directory): where `repodata/repomd.xml` is. Clients point `baseurl=` at the proxy; a metalink or a mirror list is not proxied.

### 6.4 Group

- For each directory in which a member has `repodata/repomd.xml`, the group writes a merged `repodata/` from the members that have that directory. The same name, epoch, version, release and arch is taken from the first. A later member's package whose path an earlier member holds with other content is left out, as it could not be fetched through the group.
- Every `repodata/` file a member gives is checked against the checksum its `repomd.xml` names. Its `repomd.xml.asc` is checked only where the proxy has `remote_keys` and the remote signs (Fedora's and Rocky's mirrors do not). A YUM proxy needs no keys to be a member: the distributions sign their packages, and dnf checks those signatures through a group as it does without one.
- `comps` (package groups), `modules` and `updateinfo` are not merged: the group's `repomd.xml` names those of its first member that has them, as that member gave them. Section 11 says what this risks.

## 7. Alpine

### 7.1 Layout

As Alpine's mirrors have it: `<any path>/<arch>/<name>-<version>.apk`, with an `APKINDEX.tar.gz` in each architecture's directory. A client lists `https://repo.example.com/repository/apk-hosted/v3.24/main` in `/etc/apk/repositories`, and apk adds `/<arch>/APKINDEX.tar.gz`.

### 7.2 Hosted

- **Upload:** an `.apk` by `PUT` to its path, or through the upload API and the web UI with a `directory` field. The last directory of the path must be the package's own architecture (`x86_64`, `aarch64`, `noarch`, …), or the upload is refused with `400 invalid_path`. The server reads the package's `.PKGINFO` (name, version, architecture, size, installed size, description, URL, licence, origin, maintainer, build date, commit, `depend`, `provides`, `install_if`) and computes the identity apk matches it by: the SHA-1 of its control part (`Q1` and base64). A file that is not an apk package in the format `abuild` writes is refused with `400 invalid_package`; one in apk-tools 3's newer package format is refused with a message that says so (section 11).
- **What is a component:** a name and version. Each architecture's file is one of its assets. The deployment policy applies to the path.
- **`APKINDEX.tar.gz`** is a signature part and a gzipped tar of `DESCRIPTION` and `APKINDEX`, whose records have the fields apk reads (`C`, `P`, `V`, `A`, `S`, `I`, `T`, `U`, `L`, `o`, `m`, `t`, `c`, `D`, `p`, `i`), signed with the repository's RSA key under the name `megooarti-<repository>.rsa.pub`.
- **Usage:** `apk add <name>=<version>`. The repository's own snippet: fetch the key to `/etc/apk/keys/megooarti-<repository>.rsa.pub`, and the line for `/etc/apk/repositories`.

### 7.3 Proxy

The remote is a mirror's root (`https://dl-cdn.alpinelinux.org/alpine`).

### 7.4 Group

For each directory, the group merges the members' `APKINDEX` (the same name, version and architecture taken from the first) and signs it with its own key. A proxy member's index is verified with its `remote_keys` (Alpine's published keys) before it is merged (4.5).

## 8. The web UI and the API

- **Every list of formats** has the three: the repository form, the permission rows, upload and search.
- **The repository form** has what each needs: a suite for a hosted APT repository; `repodata_depth` for a hosted YUM repository (both shown as text once made, beside the address); `remote_keys` for a proxy of any of the three, said to be needed for an APT or apk proxy that is to be a group's member.
- **A repository's page**, for a hosted repository or a group of the three, has a signing-key panel: the kind, algorithm, fingerprint and date; the public key to download; "Import a key" and "Generate a new key" for whoever holds `admin:repositories:write`, each asking first and saying that every client must then install the new public key (A2).
- **How to use the repository** is on its page, ready to copy (5.2, 6.2, 7.2), with the address the base URL gives.
- **A group's members** that a check left out are shown on the group's page with the reason.
- **The upload form** has each format's fields: none for APT, `directory` for YUM and apk.
- **Search** finds a package by name, version, architecture and description.
- **Deleting** goes through the format. Deleting a package's file raises the revision, and the indexes follow.

## 9. Errors and limits

- What is read of an uploaded package is bounded: a `.deb`'s `control.tar` at 16 MiB unpacked, an RPM's header at 64 MiB, an apk's control part at 16 MiB. Beyond that the package is refused with `400 invalid_package`, without the rest being read.
- A proxy member's index that a group reads is bounded at 1 GiB unpacked; beyond that the member is left out, as one that fails a check is (4.5).
- A signing key that cannot be unsealed (the secret key changed) makes the repository's indexes answer `500`, and the repository's page says that the key must be generated or imported again. This is the same as a proxy's stored password today.
- Paths with `..` or a backslash are refused as for every format.

## 10. Testing

- **Unit tests** under `backend/tests/repositories/<format>/`, with packages the tests build in memory and a stand-in remote: reading each package format, refusing broken ones at each bound, writing each index byte for byte against what the format's own tools write for the same packages (fixtures made once with `dpkg-scanpackages`, `createrepo_c` and `apk index`, and kept), signing and checking with the repository's key, the revision and the cache, groups merging and leaving out a member that fails a check.
- **Real clients**, marked `docker`, in each client's own image, against a stack built from the working tree (D5):
  - `test_apt_client.py`: apt on Debian stable and on Ubuntu LTS. A `.deb` built in the test with `dpkg-deb`, uploaded to a hosted repository and installed; a public package installed through a proxy of `deb.debian.org` and of `archive.ubuntu.com`; both through a group; `apt-get update` refusing a repository whose key it was not given.
  - `test_yum_client.py`: dnf on Fedora and on Rocky Linux, with `repo_gpgcheck=1`. An RPM built in the test with `rpmbuild`, uploaded to a hosted repository at depth 2 and installed; a public package through a proxy of a Fedora mirror and of a Rocky mirror; both through a group; dnf refusing metadata signed with another key.
  - `test_apk_client.py`: apk on the two newest Alpine releases. A package built in the test with `abuild`, uploaded and installed; a public package through a proxy of `dl-cdn.alpinelinux.org`; both through a group; apk refusing an index signed with a key it does not trust.
  The distributions' versions are pinned in the tests, and named in each format's guide.
- **Browser tests** for the signing-key panel and the new fields of the repository form, as plan 10c's are.
- **The test of the documents** has the three formats in `CLIENTS`.

## 11. Risks

| Risk | What settles it |
| --- | --- |
| apk refuses an unsigned package that a signed index vouches for. | The first real-client test of plan 12d. If so, a hosted apk repository accepts only packages signed with a key its clients trust, and its guide says so. |
| apk-tools 3 reads the index or the packages differently from apk-tools 2, or the newest Alpine writes packages in the newer format. | Plan 12d's tests on the two newest releases. If packages in the newer format are what `abuild` writes, reading them becomes part of plan 12d. |
| A Python library for OpenPGP that signs as apt and dnf verify. | Settled for apt (P1): `pysequoia`. Plan 12c's tests show dnf verifying it too. |
| `zstd` packages need `zstandard` (Python 3.13 has no `zstd` of its own). | A dependency, added in plan 12a. |
| Merging a proxy's whole index (Debian's `Packages` is tens of megabytes) costs memory and time on the first request after a change. | The merged index is cached (4.5), and plan 12b measures a merge of Debian's `main` for `amd64`. |
| A YUM group passes on one member's `modules`: modular packages of the other members may be filtered by dnf. | Plan 12c's tests with Rocky's AppStream; the guide says what a group of modular repositories does. |
| Keys sealed with the secret key are lost with it. | The backup guide already says to keep the secret key; it will name signing keys too. |

## 12. Plans

| Plan | What it builds |
| --- | --- |
| 12a | Signing keys (table, generation, import, the API, sealing), the revision and the index cache, the change to `describe_component`, the `apt` format's hosted and proxy repositories, its real-client tests and `docs/formats/apt.md`. |
| 12b | Groups of `apt` repositories, `remote_keys` and the checks of 4.5. |
| 12c | The `yum` format: hosted (with `repodata_depth`), proxy and group, its tests and guide. |
| 12d | The `apk` format: hosted, proxy and group, its tests and guide. |
| 12e | The web UI: the three formats in every list, the repository form's fields, the signing-key panel, the setup snippets, and the left-out members of a group. |

Each plan ends with a working format and its tests; the API serves the three formats from the plan that adds each, and the web UI lists them from 12e.

## 13. Requirements

| BRD | Where |
| --- | --- |
| FMT-12 APT: hosted and proxy, with metadata signed with an administrator-supplied GPG key | Section 5, and 4.2 with D3 (generated, or imported). Groups beyond the BRD (D4). |
| FMT-13 YUM: hosted, proxy and group, with `repodata` at a configurable depth | Section 6, 6.2's `repodata_depth`. |
| FMT-24 (new, D7) Alpine | Section 7. |
| SEC-9 Clients authenticate with an API token wherever they accept a password | apt (`auth.conf`), dnf (`username`/`password` in the `.repo` file) and apk (credentials in the repository's URL) send HTTP Basic; a token is taken as the password, as for every format. The guides say how. |
