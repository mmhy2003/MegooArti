# Release readiness: design

**Date:** 2026-10-13
**Plans:** 11a (hardening), 11b (release mechanics), 11c (documents)
**BRD:** NFR-1, NFR-4, NFR-12, NFR-18, TC-4, TC-5; and, in part, NFR-9, NFR-10, NFR-17

## 1. Goal

Make what plans 1 to 10 built fit to be given to somebody else: close what the reviews of those plans set aside as "the server's own behaviour", prove a backup can be restored, run the clients the Maven design left for later, and say how to install, upgrade, configure and extend the product in documents a stranger can follow.

Phase 1 is then complete, with the exceptions section 2 names.

**Success looks like this:**

- An administrator who makes a Maven repository for releases, and changes nothing, cannot have a released version overwritten.
- One's own password is changed in one place, and that place asks for the present one.
- A person can follow one document from an empty machine to a running instance with their own passwords, and another from a backup to the same instance restored, and both are run by a test.
- Gradle and sbt resolve and publish as Maven does.
- The licence is in the repository and in the images.

## 2. Scope

**In scope:**

- **Plan 11a, hardening:** changes to the API and the UI's side of them (section 4).
- **Plan 11b, release mechanics:** the licence, the Compose file as an installation uses it, the images as they are built and named, backup and restore with a test, Gradle and sbt, a measurement against NFR-4, and real-client tests that survive one slow answer from a public registry (section 5).
- **Plan 11c, documents:** the guides NFR-18 names, in `docs/`, and a README that is a quick start and a map (section 6).

**Out of scope:**

| What | Why |
| --- | --- |
| CI: tests and a dependency scan run on every change | The product owner's decision, for now (D2). NFR-17 and the CI half of NFR-10 stay open. The commands CI would run are in the development guide. |
| Images published to a registry | It would be CI's work (D2). The images are built by `docker compose build` and named so that they can be pushed by hand. |
| A sidebar in place of the navigation's rows | A14: the product owner's to ask for. |
| The minors the reviews of plans 10a to 10c deferred | None stops a release. They are listed in section 8. |
| A group answering `502` when a member could not answer | Section 7. |
| A documentation site | D4. |
| Ivy on its own | sbt resolves and publishes Ivy-style through the same client; a build that uses Ivy alone is rare. |

## 3. Decisions

The product owner's:

| # | Decision | Choice |
| --- | --- | --- |
| D1 | Licence | MIT. The BRD's assumption A-1 (Apache-2.0, "pending the owner's confirmation") is replaced by it. |
| D2 | CI and published images | None for now. |
| D3 | A new hosted Maven repository for releases | Starts as "disable redeploy", as Nexus does. Snapshot and mixed repositories, and the other formats, start as "allow redeploy". Repositories that exist are not changed. |
| D4 | Shape of the documents | Guides in `docs/`, readable on GitHub; a short README. |

## 4. Hardening (plan 11a)

Each row is something a review found and set aside because it was the server's to change. Each change has tests of its own, and where the UI offers the thing, the UI follows.

| # | What | Why |
| --- | --- | --- |
| H1 | `hosted.deployment_policy` may be left out. Of a repository that is made, the server then chooses: `disable_redeploy` for a hosted Maven repository whose version policy is `release`, `allow_redeploy` otherwise. Of one that is replaced, the policy it has is kept (H17). A policy that is sent is kept as sent. The form of a new repository shows that default and follows it as format, type and version policy change, until the person chooses a policy themselves. | D3. A released version that can be replaced is a build that cannot be repeated. No migration: an administrator may have chosen "allow redeploy". |
| H2 | `PUT /users/{id}/password` for one's own account is refused with `409 own_password`. One's own password is changed at `PUT /me/password`, which asks for the present one. | One's own password has one place, and that place asks. The direct way was also how an administrator ended their own session by mistake (A22): the UI stopped offering it in plan 10b, and the API still took it. It is not a wall against a stolen session of an administrator (H19). |
| H3 | A repository, a role and a blob store cannot be created with the name `.` or `..` (`422` at `name`). Those that exist stay, and are listed without a link (A25). | A browser, a proxy and most clients take them for folders: such a repository cannot be reached at its own address. |
| H4 | The base URL cannot have a user name or a password in it (`422`), and the form says so before it is sent. | Every address the server gives out is built from it, and would carry them to every client. |
| H5 | `POST /auth/login` and `POST /auth/logout` refuse a request from another site, as every other request that changes something does (`403 cross_site_request`). | A page on another site could sign a visitor in to an account of its own choosing, and what the visitor then uploaded was the other's. |
| H6 | The API's documentation page (`/api/docs`) is served with its own script and stylesheet, from the backend. It asks nothing of another host. | It loaded Swagger UI from a public CDN: an installation without the internet had no page, and one with it ran a third party's script on its own origin. |
| H7 | The blob store called `default` cannot be deleted (`409 default_blob_store`), and the UI offers no button for it. | A repository made without naming a blob store is put in `default`, and the forms always offer it. |
| H8 | The test that fails now and then in the backend suite (a setup error in one of the security tests, seen three times, never with its output kept) is caught with its output and its cause removed. If it cannot be caught in the plan's own runs, the suite is made to keep the output of a failed setup, and the plan says so. | A suite that fails without a reason teaches people to run it twice. |

**Not changed, and said in the documents instead:**

- **Addresses built from the request's `Host`** when no base URL is set. The gateway overwrites what a client says of itself, and the installation guide says to set the base URL behind any other proxy.
- **A proxy's remote may be any address**, a loopback or a private one included. Only who may write repositories can set it, and a repository manager inside a network is there to reach hosts inside it.
- **Rebuilding an index is done in the request**, and the gateway waits ten minutes. It can be repeated: each piece is committed.
- **What the gateway itself refuses is answered with nginx's own page.** In an installation the operator's proxy stands there.

### Settled while building plan 11a

| # | What | Why |
| --- | --- | --- |
| H9 | The policy of a repository that is given none is its format's to say (`Format.default_deployment_policy`), and the service asks it. | Every way a repository is made then gets it, not only the API. |
| H10 | The form sends the policy it shows. It knows the server's rule (`policyOf`), and a table of the same cases is tested on each side. | A person should not send "whatever the server chooses" while looking at a choice. |
| H11 | One's own password is refused at the administrator's endpoint for a token too. | The endpoint asks nobody who they are, however they came. |
| H12 | A sign-in from another site is refused before the password is looked at, so it is not counted as a failed attempt. Signing out was refused already, by the guard every session has: a test now says so. | Counted, a page elsewhere could lock anybody's account by trying. |
| H13 | Swagger UI 5.33.2 is kept in `backend/src/megooarti/static/swagger-ui` with its licence, its notice and its version, byte for byte (`.gitattributes`). The page loads three files by name through a route of the API; no folder is mounted. Swagger UI is told not to ask swagger.io to validate the document. | A mounted folder is one the test of route guards cannot see into. The validator is asked for any server that is not on localhost. |
| H14 | In the list of blob stores, `default` has the words "Always kept" where the others have their button. | No button that the server would refuse (UI-2). |
| H15 | H8 was not caught where it was looked for: 25 runs of the security tests passed. A setup or a teardown that fails now leaves what it said in `backend/.test-failures/` (the newest fifty are kept), whatever becomes of the run's output; and a Compose command that fails says what Docker said, where it said only that the exit status was not zero. | The next time it happens it has a text. While this plan was built the files caught the other failure nobody had read: `docker compose build` failing once for a whole module of client tests, with no reason given. |
| H16 | The browser tests are 66: a Maven repository made by the form with nothing chosen refuses the second deploy, and the documentation page draws. The blob store test makes a repository in its own store to be refused, since `default` is no longer offered. | Section 4.2. |

### Settled by the review of plan 11a

| # | What | Why |
| --- | --- | --- |
| H17 | Replaced without a policy, a repository keeps the one it has. Only a repository that is made is given its format's own. A row stored without a policy is answered as `allow_redeploy`, which is what is enforced for it. | As first built, `PUT {"online": false}` gave a repository its format's default: every Maven repository for releases made before this plan turned to `disable_redeploy` when it was taken offline, and one set to `read_only` turned to `allow_redeploy` (which it also did before this plan). A row with `"hosted": {}` answered 500 for the whole list. |
| H18 | In the form of a new repository, pressing the policy that is shown makes it the person's choice, and until one is chosen a line under it says that it follows the format and the version policy. | A browser says nothing when the radio that is checked is pressed. A person who pressed "Disable redeploy" to confirm it, and then chose the version policy "Mixed" further down, sent "Allow redeploy" without having seen it change. |
| H19 | H2 is said for what it is: one place for one's own password, which asks for the present one. Whoever holds an administrator's session can still make a user or an API token without being asked. Asking for the present password before anything that makes or changes a credential is not built: it is the product owner's to decide (section 8). | The spec said that nobody changes a password without the server knowing who they are, and the review made a second administrator through an open session and set the first one's password with it. |
| H20 | The hook that keeps a failed setup never costs the run: where its folder cannot be written, the failure is in the run's output as before. The end of the run says how many were kept and where, and the README says that the folder exists. | With a file in the folder's place the whole session stopped at the first failed setup. A file nobody knows of is read by nobody. |

### 4.1 API changes

| Endpoint | Change |
| --- | --- |
| `POST /repositories`, `PUT /repositories/{name}` | `hosted.deployment_policy` optional (H1); `name` not `.` or `..` on creation (H3) |
| `PUT /users/{id}/password` | `409 own_password` for the caller's own id (H2) |
| `POST /roles`, `POST /blob-stores` | `name` not `.` or `..` (H3) |
| `PUT /settings/base-url` | `422` for an address with user information (H4) |
| `POST /auth/login`, `POST /auth/logout` | `403 cross_site_request` from another site (H5) |
| `GET /api/docs` and what it loads | served by the backend (H6) |
| `DELETE /blob-stores/default` | `409 default_blob_store` (H7) |

The API's version does not change: nothing that worked for a client that did what the UI does stops working, and API-6 asks a new version of breaking changes. H2 breaks a script that sets its own password through the administrator's endpoint; the release notes say so.

### 4.2 Tests

- Each row of 4.1 at the API, with the case just inside the rule and the one just outside it: a snapshot Maven repository and an npm one left as "allow redeploy"; a policy that is sent and kept; another user's password still set; a repository called `...` or `.a` still made; a base URL with a port and a path still taken; a sign-in from the same site, and one from a client that says nothing of where it is from (curl, a package client), still taken.
- The UI: the default policy that follows the form and stops following once chosen; the base URL refused in the form; no delete button for `default`.
- The browser suite: a Maven release repository made through the form refuses a second deploy of the same file.
- The documentation page in a real browser: it draws, and of every request the browser made, none went to another host.

## 5. Release mechanics (plan 11b)

| # | What | Why |
| --- | --- | --- |
| L1 | `LICENSE` (MIT) in the root; the licence named in `pyproject.toml`, `package.json` and as a label of both images; the BRD's A-1 and TC-5 say MIT. | D1, TC-5. |
| L2 | The Compose file is the installation's: the database's password, and what else an installation must choose, come from the environment or a `.env` file, with an example file that names each. Started without them, it says what is missing instead of running with a password everybody knows. Development keeps working with one command. | TC-4. The file in the repository has the password `megooarti` in it. |
| L3 | Both images are named and tagged with the version by the Compose file (`megooarti/backend:<version>`, `megooarti/frontend:<version>`), carry the OCI labels for version, licence and source, and run as a user that is not root (they do already; a test says so for both). | TC-4, NFR-10. `docker compose build` then makes what a registry would hold. |
| L4 | Backup and restore is a procedure in a guide and a test that follows it: with artifacts of each format in place, the database is dumped and the data directory copied; the instance is destroyed with its volumes; a new one is restored from the copies; every artifact is fetched again and compared, a session and a token still work, and a proxy's stored secret still opens its remote. | NFR-12. A backup nobody has restored is a hope. The data directory holds the key the secrets are encrypted with. |
| L5 | Gradle and sbt each resolve through a group, and publish a release and a snapshot to hosted repositories, in the real-client suite. | NFR-1; the Maven design left them for this plan. |
| L6 | A script measures requests for cached metadata of each format with 100 clients at once and reports the 95th percentile. Its numbers, and the machine they were taken on, are in the documents. It is not a test: the reference host of NFR-4 is not this machine. | NFR-4 (Should). |
| L7 | The real-client tests' proxies of public registries are not left alone after one failure (`auto_block` off), so one slow answer from the internet does not fail everything that follows it. | A test failed that way on `main`: the proxy stopped asking, and the group then answered 404 for what it had not cached. |
| L8 | The commands that scan the dependencies of the backend and of the frontend for known vulnerabilities are written down, run once, and what they find is dealt with or recorded. | NFR-10, without CI (D2). |

### Settled while building plan 11b

| # | What | Why |
| --- | --- | --- |
| L9 | The copyright line of `LICENSE` names "The MegooArti Authors". | Whose name stands there is the owner's to say; this names nobody wrongly. |
| L10 | The tests' stack has a password and an image tag (`test`) of its own, given in the environment, which goes before a `.env` file. | The images are now named for everybody: a stack of tests that built `megooarti/backend:0.1.0` would have replaced the one an installation on the same machine runs. |
| L11 | Backup and restore are two scripts, `scripts/backup.sh` and `scripts/restore.sh`, and the test runs those. The database is dumped before the files are copied. Restore refuses an installation that is not empty. The backup names the blob stores it cannot have, those whose directory is outside the data directory. | A procedure that is a script is the same every time, and is what the test runs. The order is what makes the two halves fit while the installation runs: a file is written before the database names it, and kept for a day after. |
| L12 | A connection to a remote that could not be made is tried twice more (after 0.2 s and 1 s) before it is a failure. A connection that timed out, and a request that was sent, are not tried again. | The logs L7 keeps showed what failed the client tests now and then: `ConnectError` from the backend's container to Maven Central, on a request whose neighbours succeeded. Behind a group that one dropped connection was "not there" to the client, which does not ask twice. |
| L13 | L7's logs are kept by the same hook that keeps a failed setup: of a test marked `docker` that fails, what the backend and the gateway said. They hold the first-start administrator's password of the tests' own stack, which is removed with it. | The stack is gone when its module ends, and it was the only place that said why. |
| L14 | sbt publishes a snapshot under one name (`sbt-library-4.1-SNAPSHOT.jar`), not Maven's dated ones, and the repository takes it. Gradle publishes a file of its own beside the POM (`.module`) and SHA-256 and SHA-512 checksums, and reads them back. Both went through without a change to the Maven format. | L5. Found by running them. |
| L15 | The latency script runs a load generator (`oha` 1.16.0) in a container to do the asking. | Written in Python first, it could ask about 170 times a second and measured itself: it said 3 s where the generator, on the same stack, says 0.56 s. |
| L16 | NFR-4 is not met. On a laptop (Intel i7-1165G7, 4 cores and 8 threads, Docker Desktop on Windows with 8 CPUs and 11.5 GiB), with 100 clients at once and a token, a request for cached metadata is answered in 0.13 to 0.6 s at the median and 2 to 3 s at the 95th percentile, 105 to 140 a second, where NFR-4 asks 200 ms. An address that needs neither the database nor a caller's name is answered 2,100 times a second through the gateway. The backend is one process and uses one core, which is full; finding who is calling is several questions to the database for every request. | L6 measures; it does not mend. What would: more than one process, and not asking again within a few seconds who a token belongs to. Both are decisions (section 8). |
| L17 | The dependency scan found nothing in what the backend depends on, nothing in what the frontend's image has, and one advisory in what the frontend's development uses: `braces` (GHSA-vfj7-8cjw-p6xm), under `eslint-config-next`, with no patched version. It is not in the image, and takes patterns from this repository only. | L8. |
| L18 | The backend takes the database's password apart from its address (`MEGOOARTI_DATABASE_PASSWORD`), and Compose gives it that way. The tests' stack has a password with `@`, `/`, `#`, `?`, `%`, `&` and `$` in it. | In the address, a password that a password manager made would be read as a host or a path, and the first start would fail with words about neither. |

### Settled by the review of plan 11b

| # | What | Why |
| --- | --- | --- |
| L19 | `backup.sh` asks first whether the database and the backend run, has tar say how it ended on a line of its own, writes beside what is in the directory and replaces it only when all of the new backup is whole, and ends with an error and the words "NOT done" otherwise. Its files are for their owner alone. A directory that is not given whole is from where the script was run. | With the backend stopped it wrote an empty `data.tar` over the last good one and said "done": Docker ends with status 1 when a service is down, which is also how tar says that a file changed. A job that ran every night would have destroyed the only copy of the files and the key, and said nothing. |
| L20 | Nothing is left out of the copy by a pattern: the folders of unfinished uploads are in it. | The pattern that left them out also left out a blob store whose directory was `cache/tmp`, without a word; after the restore its files were named and not there. |
| L21 | `restore.sh` reads both halves of the backup through before it writes, restores the database in one transaction, tells "is not empty" from "could not be looked at", and says what is left and what to do when it stops between its halves. | Given an archive it could not read, it restored the database, stopped at the files with tar's own message, and then refused the next try because the database was no longer empty. |
| L22 | The latency script removes the six repositories it makes, by name, and does not begin where one of those names is taken unless it is told to (`--replace`). | It removed every repository whose name began with `latency-`, before measuring and without asking, on whatever installation it was pointed at. |
| L23 | A test is one of the running stack if it is marked `docker`, not if the word is among its keywords. | pytest counts the names of a test's folders among its keywords, and the unit tests of the registry are in a folder called `docker`: 321 of them asked the stack for its logs when they failed. |
| L24 | The images are named for the project's own place in GitHub's registry: `ghcr.io/mmhy2003/megooarti-backend:<version>` and `...-frontend:<version>`, in place of L3's `megooarti/backend` and `megooarti/frontend`. | A short name is a place on the public registry that belongs to whoever takes it, and `docker compose pull` would have run what they put there. Where only the owner can put an image, a pull finds the owner's or none. (Having Compose build always and never fetch was tried first: every `docker compose run` then built again and wrote what the build said where the command's own words were expected, and the restore script took it for a data directory that was not empty.) |
| L25 | When the database refuses the password, the backend names where a password is given: `MEGOOARTI_DATABASE_PASSWORD`, from `MEGOOARTI_DB_PASSWORD` under Compose, or else the address; and says that a database keeps the one it was made with. | It blamed `MEGOOARTI_DATABASE_URL`, which under Compose nobody sets and which has no password in it. |
| L26 | H8 was caught, in this plan's own run of the suite: `OSError: [WinError 121] The semaphore timeout period has expired`, from a connection to the test database that Windows dropped before it was made. The fixture that opens a test's connection asks up to three times for one that fails so; what the database answers is not asked again. | It is this machine's network between Windows and a port that Docker publishes, and not the product: a remote dropped the same way is what L12 answers. |

## 6. Documents (plan 11c)

`README.md` becomes: what MegooArti is, a quick start that ends at a signed-in administrator, and a map of the guides. The rest of what it holds today moves, reorganised and checked against the product as it is.

| Guide | Holds |
| --- | --- |
| `docs/installation.md` | Requirements, Compose, the first sign-in, the base URL, behind your own reverse proxy (with the gateway's rules), TLS, what to choose before the first start |
| `docs/configuration.md` | Every environment variable (NFR-15), every setting kept in the database |
| `docs/upgrade.md` | Upgrading the images, what the entrypoint migrates, downgrade, release notes |
| `docs/backup.md` | L4's procedure, and what is lost with the secret key |
| `docs/administration.md` | Users, roles, permissions, tokens, anonymous access, repositories, blob stores, the system page |
| `docs/formats/{maven,npm,pypi,docker,raw}.md` | Per-format client setup, for each client the suite runs |
| `docs/api.md` | The API's conventions: errors, paging, authentication, where the reference is |
| `docs/development.md` | Running from source, the tests, the audit commands (L8), the working rules |
| `docs/adding-a-format.md` | The format interface, by way of the Raw format, and what the real-client suite expects |
| `CHANGELOG.md` | 0.1.0: what there is, and what a caller of the API must know (H2) |

Every command in a guide is one a test runs or was run while the guide was written; every address, variable and default is checked against the code by a test where one can be written (the variables of `Settings`, the routes the gateway sends on).

## 7. A group and a member that could not answer

A proxy whose remote fails answers `502`; a group takes that as "not here" and, if no other member has the file, answers `404` (storage design, plan 3b). A client told `404` does not try again, where one told `502` might.

It stays as it is. A group answers for several repositories, and a build that names more than one of them moves on after `404` and stops after `502`: with one member's remote down for a day, every miss would stop builds that today go on. What was asked for is logged with the member's failure, and the proxy's state is on its settings page.

## 8. Known and left

**How long answers take** (L16): NFR-4 is a "Should" and is missed by an order of magnitude. Running several processes of the backend, and remembering for a few seconds who a token belongs to, are the two changes that would bring it near; the first needs the backend proven with more than one process, the second delays a revoked token by as long as it is remembered.

**Asking again for the present password** before a credential is made or changed (another user's password, a new user, an API token): today an open session of an administrator is enough for each (H19).

From the reviews of plans 10a to 10c, none of which stops a release: page titles that could say more; lists of choices capped where a later page exists; a refusal's text staying after its field is edited; the generated password not announced; a proxy secret's hint that is untrue once the kind of sign-in changes; a proxy's failure state cleared by a save without a word; a notification that covers the buttons under it for some seconds; names that break every few characters at phone width; the settings form's missing heading; `repository-settings.tsx` to be split; the browser tests' complaint filter letting `409` through.

They are listed in the changelog's "Known issues" where a person would meet them.

## 9. Risks

| Risk | Answer |
| --- | --- |
| H1 changes what an existing script gets when it creates a Maven release repository without a policy. | That is the point of D3. The changelog says so; the policy can be sent. |
| H5 refuses a sign-in the UI makes, in some browser or behind some proxy. | The same check has guarded every other request since plan 3; the browser suite signs in through the gateway, and the unit tests cover a browser that sends `Origin` only. |
| The vendored Swagger UI ages. | It is three files with their version in a test; replacing them is one command, written in the development guide. |
| The restore test needs the Docker socket and several minutes. | It is marked `docker`, as the other real-client tests are. |
| Moving the README's content loses something. | Plan 11c's first task lists every heading of the README and where it goes; its last checks that none is left unplaced. |

## 10. Requirements

| Requirement | Where |
| --- | --- |
| NFR-1 | L5, L7 |
| NFR-4 | L6 |
| NFR-9 | H5 |
| NFR-10 | L3, L8; "in CI" open (D2) |
| NFR-12 | L4, `docs/backup.md` |
| NFR-15 | `docs/configuration.md` |
| NFR-17 | open (D2) |
| NFR-18 | section 6 |
| TC-4 | L2, L3; "distributed" by a registry open (D2) |
| TC-5 | L1 |
