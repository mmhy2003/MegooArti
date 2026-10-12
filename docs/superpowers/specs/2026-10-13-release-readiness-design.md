# Release readiness: design

**Date:** 2026-10-13
**Plans:** 11a (hardening), 11b (release mechanics), 11c (documents)
**BRD:** NFR-1, NFR-4, NFR-12, NFR-18, TC-4, TC-5; and, in part, NFR-9, NFR-10, NFR-17

## 1. Goal

Make what plans 1 to 10 built fit to be given to somebody else: close what the reviews of those plans set aside as "the server's own behaviour", prove a backup can be restored, run the clients the Maven design left for later, and say how to install, upgrade, configure and extend the product in documents a stranger can follow.

Phase 1 is then complete, with the exceptions section 2 names.

**Success looks like this:**

- An administrator who makes a Maven repository for releases, and changes nothing, cannot have a released version overwritten.
- Nobody changes a password, their own or another's, without the server knowing they are who the session says.
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
| H1 | `hosted.deployment_policy` may be left out when a repository is created or replaced. The server then chooses: `disable_redeploy` for a hosted Maven repository whose version policy is `release`, `allow_redeploy` otherwise. A policy that is sent is kept as sent. The form of a new repository shows that default and follows it as format, type and version policy change, until the person chooses a policy themselves. | D3. A released version that can be replaced is a build that cannot be repeated. No migration: an administrator may have chosen "allow redeploy". |
| H2 | `PUT /users/{id}/password` for one's own account is refused with `409 own_password`. One's own password is changed at `PUT /me/password`, which asks for the present one. | A session left open, or a stolen cookie with its CSRF token, was enough to set a new password and so to keep the account. The UI stopped offering it in plan 10b (A22); the API still took it. |
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
- The documentation page in a real browser, with every request to another host refused: it draws.

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

From the reviews of plans 10a to 10c, none of which stops a release: page titles that could say more; lists of choices capped where a later page exists; a refusal's text staying after its field is edited; the generated password not announced; a proxy secret's hint that is untrue once the kind of sign-in changes; a proxy's failure state cleared by a save without a word; a notification that covers the buttons under it for some seconds; names that break every few characters at phone width; the settings form's missing heading; `repository-settings.tsx` to be split; the browser tests' complaint filter letting `409` through.

They are listed in the changelog's "Known issues" where a person would meet them.

## 9. Risks

| Risk | Answer |
| --- | --- |
| H1 changes what an existing script gets when it creates a Maven release repository without a policy. | That is the point of D3. The changelog says so; the policy can be sent. |
| H5 refuses a sign-in the UI makes, in some browser or behind some proxy. | The same check has guarded every other request since plan 3; the browser suite signs in through the gateway, and the unit tests cover a browser that sends `Origin` only. |
| The vendored Swagger UI ages. | It is two files with their version in a test; replacing them is one command, written in the development guide. |
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
