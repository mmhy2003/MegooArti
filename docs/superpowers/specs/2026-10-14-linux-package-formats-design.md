# Linux package formats: design

**Date:** 2026-10-14
**Plans:** 12a (signing keys, APT hosted and proxy), 12b (APT groups), 12c (YUM hosted and proxy), 12d (YUM groups), 12e (Alpine hosted and proxy), 12f (Alpine groups), 12g (the web UI)
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

### Settled by the review of plan 12a

| # | What | Why |
| --- | --- | --- |
| P9 | A `PUT` or `POST` of a `.deb` to a name at the root of a hosted repository is an upload to the root: the name is not kept. | `curl --upload-file x.deb .../`, the guide's own command, puts the file's name after the slash, and was answered `405`. |
| P10 | An index of a hosted repository is sent again unless the client has the same bytes (`If-None-Match`); a date (`If-Modified-Since`) is not taken to say so. | Two revisions made within one second have the same date: apt was told `304`, and kept the older index until the next change. Seen with apt on Debian 13. |
| P11 | `amd64` and `arm64` are always listed, beside the architectures of the packages. | One upload for `arm64` took `binary-amd64` away, and with it every package for `all` architectures from every amd64 machine. |
| P12 | A snapshot is one statement, which sees the database at one moment: no retry, and no `503 repository_busy`. The index files of a revision are written once, however many requests want them at once (the others wait for that one), and in a task of their own, which a request that goes away does not stop. What is kept is the newest revision of each repository, at most 256 MiB of all of them, the least recently used going first. | On 30,000 packages, ten requests after a change each wrote the index again (19 to 29 seconds each, 1.5 GiB), every revision stayed in memory, and a busy repository could answer `503` to every try. |

### Settled while building plan 12b

| # | What | Why |
| --- | --- | --- |
| Q1 | A suite that one member of a group has is that member's, as it is: the group signs that member's `Release` again, unchanged, and every other file of the suite, `by-hash/` paths included, is sent on from that member. Only a suite several members have gets a `Release` of the group's own (5.4), with `Acquire-By-Hash: no`. | apt checks every file against the `Release` it was given, and that one was checked against the remote's keys. Writing Debian's indexes again would cost seconds and memory for no gain, and the mirror's translations and `by-hash/` files would be lost. |
| Q2 | Where several members have a component and architecture, the group keeps `Packages.gz` alone; its `Release` names that and the text (`Packages`), which is not kept, with a `SHA256` list only. | Debian's `main` for amd64 is 57 MB of text and 13 MB packed: merged and packed with gzip in 2.4 seconds on the reference laptop, where xz would take most of a minute and keeping the text 57 MB of memory. apt finds an index by its text's name, and checks what it unpacks against it: without that line it did not fetch the merged index at all, as Task 5's first run showed. |
| Q3 | A merged suite does not list the architecture `all`. | Debian and Ubuntu list a package for all architectures in each architecture's `Packages` (`No-Support-for-Architecture-all: Packages`), as a hosted repository does. |
| Q4 | What a group writes of a suite is kept in the cache of 12a by the group and the suite, and by a digest of the group's key and its members' state: a hosted member's revision, a proxy member's `InRelease` and `remote_keys`. | It is written again only when one of these changes. The cache takes a digest as a revision: a different one takes the place of the last. |
| Q5 | `Format.validate_member` refuses, when a group's members are set, a proxy without `remote_keys`. A proxy whose keys are taken away later is left out when the group is asked. A member left out says why as its last error (`Left out of the group <name>: ...`), which a proxy's next success with its remote clears. | 4.5, and a group that keeps answering when a member stops being checkable. |
| Q6 | A proxy member whose remote has no `InRelease` is left out. A member whose `Packages` file fails its check is left out of that component and architecture only. | Debian, Ubuntu and their mirrors all have `InRelease`; checking `Release` against `Release.gpg` as well can come when a remote needs it. |
| Q7 | A group's members are its leaves: a group within a group gives the group its own members, not its signed indexes. | One check of each remote, by the group a client trusts. |
| Q8 | `remote_keys` is armoured text, of one or more keys, at most 1 MiB, and holds no private key. The guide makes it with `gpg --export --armor` from the distribution's keyring. | Debian's keyring is binary; a JSON field is text. |

### Settled by the review of plan 12b

| # | What | Why |
| --- | --- | --- |
| Q9 | A request for a group's suite gives its database connection back before it waits for the index, and the index is written with a session of its own. | Twenty clients waiting for a large suite took every connection of the pool: the writing then failed, every one of them was answered `500`, and so was the rest of the server. |
| Q10 | A group writes a `Release` of its own for every suite, a suite one member has too (in place of Q1's: that member's `Release`, unchanged). It says whose suite it is (`Origin`, `Label`, `Suite`, `Version`, `Codename`, `Changelogs`, `Description`) as its first proxy member that has the suite says it, or else as its first member does. Its `Date` does not go back while the process keeps the last one. It is valid no longer than the earliest of its members' `Valid-Until`, and a proxy member whose `Valid-Until` has passed is left out. | apt refused `update` when a second member joined a suite (its `Label` changed from the member's to the group's), kept its old lists when a member went and the `Date` went back, and a merged suite dropped Debian security's `Valid-Until`. |
| Q11 | A proxy member's `Packages` is read by its hash where its `Release` says `Acquire-By-Hash: yes`. | Read by its name, it could be the next one's while a mirror changed, and the member was then left out of the merged suite until its `InRelease` changed again. |
| Q12 | What was written while a member was left out is served for a minute (`RETRY`), and then written again; while a member the last whole index had cannot be checked, that index is kept for a minute more. | A failure that passes is no reason to lose a distribution's packages for weeks, nor to change a suite's `Release` under its clients. |
| Q13 | A request for a group's suite is given the last index kept while the next is written behind it; only the first one waits. Hosted repositories and groups each have a budget of 256 MiB in the cache. | A whole suite over two mirrors took minutes the first time (the gateway answers `504` after ten), and its 90 MB of indexes could push every hosted repository's out. |
| Q14 | A package's path in the pool must be the same file in every member of a group that has it; the guide says so. | Packages are asked of the members in order (5.4): a second hosted repository's package of the same name, version and architecture, built for another suite, would be given the first one's file. |

### Settled while building plan 12c

| # | What | Why |
| --- | --- | --- |
| R1 | YUM is two plans, as APT was: 12c its hosted and proxy repositories, 12d its groups (6.4). Alpine and the web UI follow, as 12e and 12f. | A group of YUM repositories has merging and checks of its own; each plan ends with a working format. |
| R2 | The metadata is what `createrepo_c` 1.x of Fedora 44 writes, byte for byte, of the same packages. Of what a package requires it leaves out rpm's own features (`rpmlib(...)`), the package's own files that `primary.xml` lists, what the package provides itself in the same words, and repeats; of `libc.so.6` it keeps the highest version alone, last. `pre="1"` marks what is needed before the package is installed (`Requires(pre)`, `(post)`, `(pretrans)`, `(posttrans)` and the old `PreReq`). The ten newest changelog entries are kept, oldest first, and of a run of entries at one moment each is moved a second on from the one before. An attribute's characters beyond ASCII are written as character references, as libxml2 writes them. | Section 10: held against what createrepo_c wrote of two packages built for the tests and of two of Fedora 44's own. |
| R3 | The metadata files are packed with gzip, with no date or name in them, and named by their SHA-256. `<time file>` is when the package was stored, kept with it at upload; the revision and the timestamps of `repomd.xml` are the revision's time. | The same packages make the same bytes in any process: either of two processes can serve what the other's `repomd.xml` named. |
| R4 | Every directory exactly `repodata_depth` down has a `repodata/`, an empty one where it holds no package; any other `repodata/` is not found. | A machine can be set up before the first package for it is uploaded. |
| R5 | The files the last revision's `repomd.xml` named are served beside the newest revision's while the process keeps the last revision's; a process that has just started has the newest only. | 4.3 asks for both; the older revision is never written again. |
| R6 | A component's version has its epoch only when the epoch is not 0. A proxy's package is read from its file's name (`name-version-release.arch.rpm`), which has no epoch; a file of a proxy that is not a package belongs to no component. | dnf takes `name-epoch:version-release` and `name-version-release` both, and rpm shows a version so. |
| R7 | A package is uploaded with `PUT` to a path that ends in `.rpm`, is outside any `repodata/`, and is at least `repodata_depth` directories down, or it is refused with `400 invalid_path`; the upload form takes a `directory`. A source RPM is known by its lead or by its header's `SOURCEPACKAGE`. | 6.2. `curl --upload-file` to an address that ends in `/` adds the file's name. |
| R8 | In plan 12c a YUM proxy has no settings, and there are no YUM groups (the format's types are hosted and proxy): `remote_keys` and groups come together in 12d. | What has no use yet is not offered. |
| R9 | dnf 5 on Fedora 44 and dnf 4 on Rocky Linux 10 check a `repomd.xml.asc` that `pysequoia` signed with an Ed25519 key, and install `name-epoch:version-release`. | Section 11's risk, settled by plan 12c's real-client tests. |

### Settled by the review of plan 12c

| # | What | Why |
| --- | --- | --- |
| R10 | Each value of an RPM's header has bytes of its own: a header whose values overlap is refused, as rpm refuses it. A package lists at most 500,000 files and dependencies, and is read, and what is kept of it written out, in a worker thread. | A 1 MB package whose seven lists of names were said to share the same bytes became seven million entries: 35 seconds in which the server answered nobody, and then `500`. |
| R11 | A directory that had no packages keeps the files its empty `repomd.xml` named once its first package comes. | R4's machine, set up before the first upload, was given `404` for them. |
| R12 | A hosted repository's metadata is written whole after each change, and the first request after it waits: 30,000 small packages take about 16 seconds to write and 4 more to read, a repository of 5,200 packages with a million files about 7. The guide says so. Writing only what changed (each package's part kept, each directory on its own) is left until a repository needs it. | Measured by the review on the reference laptop. dnf waits 30 seconds for a server that sends nothing. |

### Settled while building plan 12d

| # | What | Why |
| --- | --- | --- |
| S1 | A directory one member of a group has is that member's: its `repomd.xml`, signed again with the group's key, and every file it names sent on from that member. Only a directory several members have gets metadata of the group's own. | dnf checks every file against the `repomd.xml` it was given, and a YUM `repomd.xml` says nothing of whose repository it is that could change under a client (unlike APT's `Release`, Q10). Writing Fedora's metadata again would cost seconds and memory for nothing. |
| S2 | A group merges its members' `primary.xml`, `filelists.xml` and `other.xml` by their `<package>` elements, copied as each member wrote them, without parsing a file whole, and packs what it writes with zstd. | Fedora 44's release and its updates: 1.3 GB of `filelists.xml`, merged in 17 seconds on the reference laptop with 245 MB at most in memory, 120 MB packed. Packed with gzip it would take most of a minute. dnf 5 on Fedora 44 and dnf 4 on Rocky Linux 10 read zstd. |
| S3 | A merged directory's `repomd.xml` names the three files the group wrote, and of every other kind (package groups, updates, modules) the file of the first member that has it, as that member wrote its `<data>`. The members' `*.sqlite` and zchunk forms of the three are not named. Its revision and timestamps are the newest of its members' files' timestamps. | 6.4. dnf reads the XML. Rocky's `repomd.xml` gives its release (`10.2`) as its revision, not a time; the newest timestamp makes the same bytes in any process. |
| S4 | Rocky Linux's mirrors sign their `repomd.xml` (`repomd.xml.asc`), Fedora's do not (in place of 6.4's "Fedora's and Rocky's mirrors do not"). A proxy given `remote_keys` must have a `repomd.xml.asc` that one of them made, or it is left out: a signature taken away is no reason to trust a remote less checked. | A group that skipped the check whenever the signature was missing would let whoever could change the mirror's answers skip it too. |
| S5 | A hosted member's directory that holds no packages adds nothing where another member has the directory. A group whose members have no packages in a directory serves that directory's empty metadata. | A hosted repository at depth 0 always has a `repodata/`: beside a mirror, it would turn the mirror's own into a merge for nothing. |
| S6 | What a group checks of a member, whatever the format, is in one module (`repositories/checks.py`): a proxy's `remote_keys` as a setting, leaving a member out, and the members as contexts of the writing's own session. APT's groups use it. `signing.verify_detached` checks a detached signature. | One way to leave a member out, and to say why. |
| S7 | Fedora 44 and Rocky Linux 10 have no modules: section 11's risk of a group that passes on one member's `modules` concerns older distributions only (Rocky Linux 8 and 9's AppStream). The guide says that modules are the first member's. | Fedora dropped modularity in Fedora 39, and RHEL 10 has none. |

### Settled by the review of plan 12d

| # | What | Why |
| --- | --- | --- |
| S8 | A group signs a proxy member's metadata as far as its remote signed it, and no further: with a member without `remote_keys` (Fedora's mirrors sign none), every machine must check each package's own signature (`gpgcheck=1`). The guide says so, and its example and the real-client tests do it, with the hosted packages signed by `rpmsign` and the mirrors reached over HTTPS. | 6.4's "dnf checks those signatures through a group" holds only with `gpgcheck=1`; the guide had said `gpgcheck=0`, under which whoever could change a mirror's answers could have the group vouch for their packages. |
| S9 | A proxy member whose signature does not fit its `repomd.xml`, or a file of which that `repomd.xml` names is gone or not what it says, is asked again within the same writing: its `repomd.xml` and signature fetched however new the copies, and whatever was said of them before. Only then is it left out. | The two are cached each on its own clock: after a mirror changed, a keyed proxy was left out for a day, its error blaming its keys. |
| S10 | What is written behind the requests of one group's directory or suite is written once at a time: while one writing runs, requests are given what is kept, and the next begins after it. | Each upload started another merge of the whole directory beside the last (17 seconds and 245 MB each for Fedora), and an older one that ended last took the place of a newer. |
| S11 | The last whole metadata is kept (Q12) only while a member it was written from cannot be checked, whether at its `repomd.xml` or in the merge. A member that could not be checked and was not in it is left out, and the metadata is written without it. | A member added to a group that failed its checks kept the group's hosted packages from changing until it was mended. |
| S12 | A member whose `filelists.xml` or `other.xml` cannot be read is left out of that file alone; the others' stay named. Why a member was left out is said once the writing is done, and committed at once. | The whole file went missing for every member, and the wrong member was blamed; said along the way, the member's next fetch in the same writing wiped it, and the row stayed locked for the rest of the merge. |
| S13 | A member's file packed in several streams (as `pigz` and `pbzip2` write them) is read whole; one that ends inside a stream is refused. | gzip's second stream was dropped without a word, and bzip2's and xz's answered `500`. |
| S14 | What every group keeps stays at 256 MiB (Q13). A merged directory of Fedora's release and updates takes about 120 MB, and twice that after a change while the last revision's files are kept; the guide says so. A budget of its own, or merged files kept outside memory, is left until a server needs it. | Measured by the review; the budget is the one plan 12b set. |

### Settled while building plan 12e

| # | What | Why |
| --- | --- | --- |
| T1 | apk is two plans, as APT and YUM were: 12e its hosted and proxy repositories, 12f its groups (7.4) and `remote_keys`. The web UI follows as 12g. | Each plan ends with a working format. |
| T2 | An apk repository's key is RSA, made and used with `cryptography`: 4096 bits when made, 2048 or more when imported (PEM, PKCS#1 or PKCS#8, as `abuild-keygen` makes one). An index is signed as `abuild-sign` signs one: `.SIGN.RSA.<key name>`, PKCS#1 v1.5 with SHA-1, of the index's second stream as it is packed, as Alpine signs its own. Its fingerprint is the SHA-256 of the public key. `POST .../signing-key/generate` takes no `algorithm` for an apk repository, or `rsa4096`; another is refused with `422` at `body.algorithm`. An OpenPGP key is still `ed25519` unless asked otherwise. | 4.2 and A4. |
| T3 | Each package's record is what apk-tools 3.0's `apk index` writes, byte for byte: `C`, `P`, `V`, `A`, `S`, `I`, `T`, `U`, `L`, then `o`, `m`, `t`, `c`, `k`, `D`, `p`, `i` where the package says them (7.2's list has `k`, the provider's priority, besides). `replaces` and `triggers` are not listed. `DESCRIPTION` is `MegooArti <repository>`. | Held against abuild's index of two packages built for the tests and Alpine 3.24's own index of two of its packages. |
| T4 | A package for no architecture (`noarch`) may be uploaded to any architecture's directory, and is listed there as that architecture's (in place of 7.2's "the last directory must be the package's own architecture" for these). | Alpine keeps such packages in each architecture's directory, and abuild has `apk index` rewrite them so (`--rewrite-arch`): apk asks for a package at `<repository>/<architecture>/<name>-<version>.apk`, by what the index says. |
| T5 | A package's path is `<directory>/<architecture>/<name>-<version>.apk`: a `PUT` to another name is refused with `400 invalid_path`, and the upload form stores each file under that name, whatever it is called. | An index names no file: apk asks for a package by its name and version. |
| T6 | A package's own signature is not checked, and need not be one a client trusts: apk-tools 3 on Alpine 3.23 and 3.24 installs a package that a trusted index names by its checksum. | Section 11's first apk risk, settled by plan 12e's tests. |
| T7 | abuild on Alpine 3.24 writes packages in apk-tools 2's format, and apk-tools 3.0 on Alpine 3.23 and 3.24 reads indexes in it. A package in apk-tools 3's own format (ADB) is refused, with a message that says so. | Section 11's second apk risk, settled by plan 12e's tests. |
| T8 | Every directory of a hosted repository has an `APKINDEX.tar.gz`: one without packages has an empty one. | A machine can be set up before the first package for it is uploaded. |
| T9 | In plan 12e an apk proxy has no settings, and there are no apk groups (the format's types are hosted and proxy). | What has no use yet is not offered. |

### Settled by the review of plan 12e

| # | What | Why |
| --- | --- | --- |
| T10 | A package whose `.PKGINFO` is larger than 1 MiB, has a field longer than 64 KiB (a field said many times, as `depend`, counted whole), or holds a NUL, is refused with `400 invalid_package`; and so is one whose control part's tar Python cannot read, whatever the error. | apk stops reading an index at a line longer than it holds (about 128 KiB): one package with a long description hid every package after it in its directory. A 16 KB upload made five million dependencies, and a NUL or a broken tar header answered `500`. |
| T11 | A `.PKGINFO` is read, and what is kept of it written out, in a worker thread. An index's RSA key is read when it first signs, in the worker thread that writes the indexes, and is not checked again as it was when kept. An imported key is read in a worker thread too, and may have at most 8192 bits. | Reading a 4096-bit key took a quarter of a second on the loop at every change, and a large imported key many seconds. |
| T12 | The 16 MiB bound on a package's control part holds however the bytes arrive. | At an exact boundary of the pieces, the next piece was unpacked without a bound. |

### Settled while building plan 12f

| # | What | Why |
| --- | --- | --- |
| U1 | An apk proxy's `remote_keys` are RSA public keys, PEM, one or more one after the other, as `/etc/apk/keys/*.rsa.pub` holds them; anything else, or a private key, is refused with `422` at `format_config.remote_keys`. A proxy without them cannot be a member of a group (`422` at `group.members`), as an APT proxy cannot (Q5). | 4.5 and 7.4. |
| U2 | A proxy member's index is checked as apk checks it: one of its `remote_keys` must have signed its second stream, with SHA-1 (`.SIGN.RSA.`) or SHA-256 (`.SIGN.RSA256.`). An index not signed, or signed in another way, is left out. | Alpine signs with SHA-1; abuild-sign can sign with either. |
| U3 | A directory one member has is that member's index: its second stream, as the member wrote it, signed again with the group's key. | What apk reads is what the member's own signature vouched for. |
| U4 | Where several members have a directory, the group writes an index of its own: the members' records as they wrote them, in their order, and of a name and version the first member's alone (in place of 7.4's "name, version and architecture": in one directory, a name and version is the one file apk asks for). Its `DESCRIPTION` is `MegooArti <group>`, and its files' times are 0, so that every process writes the same bytes but for the signature. | Packages are asked of the members in order: a later member's package of the same name and version could not be fetched through the group. |
| U5 | A hosted member's directory without packages adds nothing where another member has the directory, as in a YUM group (S5); a group with a hosted member serves an empty index for a directory no member has packages in. | A machine can be set up before anything is uploaded. |
| U6 | An apk group writes as YUM's do: behind the requests, one writing of a directory at a time (S10), the last whole index kept only while a member it had cannot be checked (S11), and why a member was left out said once the writing is done, and committed (S12). | The lessons of plans 12b and 12d. |

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
| apk refuses an unsigned package that a signed index vouches for. | Settled: it does not (T6). |
| apk-tools 3 reads the index or the packages differently from apk-tools 2, or the newest Alpine writes packages in the newer format. | Settled for Alpine 3.23 and 3.24 (T7): abuild writes the older format, which apk-tools 3 reads. A package in the newer one is refused, with a message that says so. |
| A Python library for OpenPGP that signs as apt and dnf verify. | Settled for apt (P1) and dnf (R9): `pysequoia`. |
| `zstd` packages need `zstandard` (Python 3.13 has no `zstd` of its own). | A dependency, added in plan 12a. |
| Merging a proxy's whole index (Debian's `Packages` is tens of megabytes) costs memory and time on the first request after a change. | Measured in plan 12b (Q2): Debian's `main` for amd64, 69,908 packages, merged and packed in 2.4 seconds, 13 MB kept; a suite one member has is not merged at all (Q1). |
| A YUM group passes on one member's `modules`: modular packages of the other members may be filtered by dnf. | Settled for Fedora 44 and Rocky Linux 10, which have none (S7); the guide says that a group passes on its first member's. |
| Keys sealed with the secret key are lost with it. | The backup guide already says to keep the secret key; it will name signing keys too. |

## 12. Plans

| Plan | What it builds |
| --- | --- |
| 12a | Signing keys (table, generation, import, the API, sealing), the revision and the index cache, the change to `describe_component`, the `apt` format's hosted and proxy repositories, its real-client tests and `docs/formats/apt.md`. |
| 12b | Groups of `apt` repositories, `remote_keys` and the checks of 4.5. |
| 12c | The `yum` format: hosted (with `repodata_depth`) and proxy, its tests and guide. |
| 12d | Groups of `yum` repositories (6.4), and `remote_keys` for a YUM proxy. |
| 12e | The `apk` format: hosted and proxy, RSA signing keys, its tests and guide. |
| 12f | Groups of `apk` repositories (7.4), and `remote_keys` for an apk proxy. |
| 12g | The web UI: the three formats in every list, the repository form's fields, the signing-key panel, the setup snippets, and the left-out members of a group. |

Each plan ends with a working format and its tests; the API serves the three formats from the plan that adds each, and the web UI lists them from 12g.

## 13. Requirements

| BRD | Where |
| --- | --- |
| FMT-12 APT: hosted and proxy, with metadata signed with an administrator-supplied GPG key | Section 5, and 4.2 with D3 (generated, or imported). Groups beyond the BRD (D4). |
| FMT-13 YUM: hosted, proxy and group, with `repodata` at a configurable depth | Section 6, 6.2's `repodata_depth`. |
| FMT-24 (new, D7) Alpine | Section 7. |
| SEC-9 Clients authenticate with an API token wherever they accept a password | apt (`auth.conf`), dnf (`username`/`password` in the `.repo` file) and apk (credentials in the repository's URL) send HTTP Basic; a token is taken as the password, as for every format. The guides say how. |
