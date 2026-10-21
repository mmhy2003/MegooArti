# Cleanup policies: design

**Date:** 2026-10-21
**Plans:** 16a (policies, attaching them, the preview), 16b (the run), 16c (the web UI)
**BRD:** CLN-1, CLN-2, CLN-3, REP-15, API-4 (its cleanup part)

## 1. Goal

A repository stops growing without end. An administrator writes a policy once ("cached components nobody has downloaded in 90 days", "npm pre-releases older than 30 days", "snapshots not changed in two weeks"), sees what it would remove from a repository before trusting it, and attaches it to as many repositories as it fits. Once a day, MegooArti removes what the policies attached to each repository select, by the same rules a delete through the API follows, and the space is given back by the compaction that already runs.

This is Nexus OSS's cleanup policies, with the preview Nexus keeps for its paid edition.

## 2. Scope

**In scope:**

- Cleanup policies: a name, a description, a format (one, or all), and criteria (CLN-1, CLN-2).
- Attaching policies to hosted and proxy repositories (REP-15).
- A preview of what a policy would remove from a repository, before it is saved or attached (CLN-3).
- The run: daily, one container at a time, and on demand for one repository; what each run removed, kept per repository.
- The REST API (API-4), the audit's records, the web UI, the guides.

**Out of scope:**

| What | Why |
| --- | --- |
| Tasks an administrator creates, schedules, stops (TSK-1 to TSK-3, TSK-6) | A spec of their own. Until then the run is built-in maintenance, as compaction is (TSK-5); the tasks spec makes it a task type (TSK-4's "run cleanup policies"). |
| Keeping the newest N versions, or N snapshots (TSK-4's "remove Maven snapshots") | Not a criterion of CLN-1; a task type of the tasks spec. |
| Removing untagged Docker manifests and unused layers that no cleanup touched (TSK-4) | A task type of the tasks spec. Section 7.3 covers what a cleanup itself leaves. |
| Criteria over a component's attributes (an npm deprecation, a NuGet listing) | Not in CLN-1. |
| Cleanup of group repositories | A group holds nothing of its own. |
| MCP tools for policies | Content selectors have none either; a repository's policies go through `update_repository`, which passes them on. |

## 3. Decisions

The product owner asked for Nexus OSS's cleanup policies, and left the rest to the designer. Settled here, by the designer:

| # | What | Why |
| --- | --- | --- |
| E1 | What a policy removes is a component, with every file of it. A file that belongs to no component (npm's dist-tags, Maven's metadata, PyPI's pages) is never selected. | Nexus's unit. A component half removed is broken for every client. |
| E2 | A policy's criteria are all met for a component to be selected. A component is removed when any policy attached to its repository selects it. | Nexus's rule: criteria narrow, policies add. |
| E3 | A policy must have at least one criterion. | A policy of none would select everything. |
| E4 | Deleting by cleanup has the effects of deleting through the API (each format's own: npm's dist-tags, NuGet's version, Docker's manifest, the indexes of APT, YUM and apk), but asks no permission of anyone and ignores the deployment policy (a `read_only` repository is cleaned too). | An administrator attached the policy; that is the permission. A repository kept read-only for clients is still one an administrator wants trimmed. |
| E5 | The run is built-in maintenance until the tasks spec exists: checked hourly, a repository run when a day has passed since its own last run finished. `MEGOOARTI_CLEANUP_INTERVAL_SECONDS` (86400; `0` turns the daily run off, not running one now). | TSK-5's way. Checking hourly against each repository's last run, kept in the database, means a restart does not push the next run back a day. |
| E12 | A repository is cleaned by one run at a time, in any container: an advisory lock of its own, per repository. Other repositories are cleaned meanwhile. | "Clean up now" must not wait hours on another repository's run; two containers must never clean one repository at once. |
| E6 | Every component is checked again, in the transaction that deletes it, against the policies as they are then. | A component downloaded, or re-published, between the selection and the delete is kept. |
| E7 | The space comes back when compaction removes the content nothing refers to any more, after `MEGOOARTI_BLOB_GRACE_SECONDS` (a day). | Compaction already does this, safely, for every delete. |
| E8 | A new permission area, `cleanup`: `admin:cleanup:read` and `admin:cleanup:write` for the policies. Attaching them is a repository's setting (`admin:repositories:write`); so is running one now. | As selectors have their own area and roles name them. |
| E9 | A policy's format is chosen when it is made, and does not change. | A policy attached to Maven repositories that became npm's would be attached where it cannot apply. |
| E10 | Deleting a policy detaches it from every repository, each recorded. | Detaching only ever removes less; refusing would make an administrator visit every repository first. |
| E11 | A run of one repository is recorded in the audit log once (`repository.cleaned_up`, with the count removed and the policies that selected them), not a record for each component. | A4 of the identity spec: what a repository holds is not recorded; a run an administrator configured is. |

## 4. Policies (plan 16a)

### 4.1 Records

- `cleanup_policies`: id, name (unique whatever its case, the rule of a selector's name), description (at most 255), format (a registered format's name, or `*`), the criteria (below), created and changed.
- `repository_cleanup_policies`: repository and policy, each deleted with either.

### 4.2 Criteria

Each is optional; a policy has at least one (E3).

| Criterion | Field | A component is selected when |
| --- | --- | --- |
| Not updated | `updated_days` (1 to 36500) | its newest file was last written more than that many days ago: the `modified` the API shows (the latest `updated_at` of its files). |
| Not downloaded | `downloaded_days` (1 to 36500) | no file of it was downloaded in that many days. A component never downloaded counts from when it was made. |
| Release type | `release_type` (`release` or `prerelease`) | the format calls its version a pre-release (`Format.is_prerelease`) or not. |
| Asset name | `asset_pattern` (a regular expression) | one of its files' paths matches the whole of it (`fullmatch`, the path with its leading `/`). |

- A download is the one already noted on a file (`last_downloaded_at`), at most once an hour; so "not downloaded" is to the hour.
- Release type is offered only for a format that has pre-releases: Maven (a `-SNAPSHOT` is one), npm, PyPI, NuGet, APT, YUM and apk; not Raw, Docker, or a policy of all formats. A format says so by a new `Format.has_prereleases`.
- The pattern is checked as a selector's is: at most 1,000 characters, compiled once, one that repeats a repetition refused (G14 of the identity spec), one that does not compile refused at its field.

### 4.3 Attaching

- A hosted or proxy repository holds any number of policies of its format or of all formats. A policy of another format, or a group repository, is refused at its field (`422`).
- `RepositoryOut`, `RepositoryCreate` and `RepositoryUpdate` gain `cleanup_policies`, a list of names. Left out of a `PUT`, the repository keeps the ones it has: a client that predates them does not detach them.
- A change of them is part of `repository.updated`'s record.

### 4.4 The preview (CLN-3)

- `POST /api/v1/cleanup-policies/preview`: a policy's format and criteria (saved or not), a repository's name, a page (API-5). It answers the components the policy would remove from it now, a page at a time, newest first by `modified`, each with its namespace, name, version, `modified` and its last download, and the total. Nothing is removed.
- The preview needs `admin:cleanup:read` and lists only what the caller may browse in that repository (its reach, as search and listings have it); the total counts the same.
- A repository of another format, or a group, is refused (`422`, at `repository`).

### 4.5 REST

- `GET/POST /api/v1/cleanup-policies`, `GET/PUT/DELETE /api/v1/cleanup-policies/{name}`, paged and refused as content selectors are (`404 not_found`, `409 conflict` on a taken name). `PUT` replaces all but the name and the format (`409 immutable`).
- A policy's answer includes the repositories it is attached to, by name.
- Each change is recorded: `cleanup_policy.created`, `updated`, `deleted`; a delete records each repository it is detached from as `repository.updated` (E10).

### Settled while building plan 16a

| # | What | Why |
| --- | --- | --- |
| P1 | Policies are `megooarti/cleanup/`'s: `models.py` (`CleanupPolicy`, `RepositoryCleanupPolicy`), `criteria.py`, `selection.py`, `api.py`. A policy's name is a `NewName`, unique whatever its case (`name_key`, as a repository's). | Section 4.1; one place for what 16b and 16c build on. |
| P2 | The database narrows by the days alone; the pattern and the release type are checked in Python (`Criteria.selects`), on a page of components and their files at a time. | A database's regular expressions are not Python's: the pattern G14 checks must be the one that matches. |
| P3 | A component's `modified` is the latest `updated_at` of its files; its `downloaded` is the latest `last_downloaded_at` of its files, else its `created_at`; and, where a format says it was used later (`Format.last_used`: Docker's manifest pulled by digest), that. | Section 4.2; 7.3's first point. |
| P4 | The preview orders what is selected newest first by `modified`, keeping only the page asked for while it counts them all. Its `last_downloaded` is a download, never the time a component was made. | Section 4.4: a page and the total, without holding the repository. |
| P5 | A pattern is checked by `selectors.checked_pattern`, the very check a selector's `=~` has. Its refusal is said at `asset_pattern`. | Section 4.2: as a selector's is. |
| P6 | `GET /api/v1/formats` says `has_prereleases` for each format. | Section 4.2 and 16c: the form offers release type by it. |
| P7 | A `PUT` of a policy may send its format back unchanged; another is `409 immutable`. The preview refuses a policy's own problems at their fields first, then a repository that is not there (`404`), then one of another format or a group (`422` at `repository`). | E9; 4.4. |

## 5. The run (plan 16b)

### 5.1 When

- The hourly check (E5) runs, one after another, each repository with a policy attached whose last run finished more than the interval ago, or that has never been run. A repository another container is cleaning is passed over (E12).
- `POST /api/v1/repositories/{name}/cleanup` runs that repository now, with `admin:repositories:write`, and answers `202` at once; the run goes on in the server. A run of that repository already under way, here or in another container, answers `409 cleanup_running`. A run now is that repository's last run, as a daily one is: the daily check counts from it.
- A repository's last run (when it started and ended, how many components it removed, and the error if it failed) is kept, one per repository, and shown in `GET /api/v1/repositories/{name}` as `cleanup`.
- `POST /api/v1/repositories/{name}/cleanup/preview`, with `admin:repositories:write`, answers how many components the policies attached to it would remove now: each counted once, whoever may browse them, a number and no names. It is what "Clean up now" asks with (section 6).

### 5.2 How

- The components a repository's policies select are found in the database, a page at a time, by the criteria the database can test (the days), and the pattern and the release type checked in Python on what they give (P2). A repository's components are never all held in memory.
- Each selected component is checked again and deleted in a transaction of its own (E6), through the format (E4), under the locks a delete through the API takes. A component that went in the meantime is passed over.
- One component that cannot be deleted (a format refusing it, an error) is logged with why, and the run goes on; a run that ends with failures says how many.
- Shutdown stops a run between two components; what was removed stays removed, and the next run goes on from what is left.
- Each run logs `cleanup_finished` with the repository, the count removed and the time taken.

### 5.3 Deleting without a caller

Today a delete that runs the format's own effects needs a caller with the `delete` permission; only `sweep` works without one, and it skips the format's effects. The run needs a way of its own to delete a component through the format with no caller, having the effects E4 names. Whether that is a context for maintenance, a format hook `delete_component`, or both, is the builder's, held to this: the effects of a component's delete by the run are those of its delete through `DELETE /api/v1/content/{repository}/components/{id}` (in a proxy too, where that is the cached files' removal), with Docker's one addition (7.3), and no route of a request can reach that way.

### Settled while building plan 16b

| # | What | Why |
| --- | --- | --- |
| R1 | `RepositoryContext.unattended` (keyword-only, False unless given): `delete` and `maintain(removing=True)` then check no principal and no deployment policy. Only `cleanup/run.py` passes it; a test reads the source for any other. | 5.3: every format's effects, and no route of a request can reach that way. |
| R2 | Deleting a file as the content API does is `repositories/removal.delete_file(context, path)`, used by the API and the run alike. | 5.3: the run's effects are the API's. |
| R3 | A proxy's companions are its files of no component whose path is a removed file's path followed by `.` and more (`x.whl.metadata`). A Maven proxy keeps none: it answers checksums from the cached file. | 7.2: one rule for every format. |
| R4 | `Format.cleaned_up(context, files)` follows a component's removal by a run, given its files' paths and SHA-256s as they were; the generic format does nothing. Docker drops a removed tag's manifest by its digest when no tag and no manifest names it any more. | 7.3. |
| R5 | A repository's last run is a row of `cleanup_runs` (started, finished, removed, failed, error, by): `by` the user who asked, None for the daily run. `GET /repositories/{name}` shows it as `cleanup`; a repository's audit records do not (it is not configuration). | 5.1. |
| R6 | A repository's lock is `pg_try_advisory_lock(19779, hashtext(<repository id>))`, held on a connection of its own for the run. "Clean up now" takes it in the request, and hands it to the run it starts. | E12; a 409 must be answered before the 202. |
| R7 | "Clean up now" with no policy attached, or of a group, is `409 no_cleanup_policies`. Its record names whoever asked: the run is started from the request, and keeps its context. | 5.1; E11. |
| R8 | `POST /repositories/{name}/cleanup/preview` answers `{"total": n}`, with `admin:repositories:write`. | 5.1. |
| R9 | A run gathers the ids of what its policies select (the ids alone), then removes each in a transaction of its own. Its record's `changes` are `removed` and `policies`, and `failed` where some could not be removed. | 5.2; E11. |
| R10 | Shutdown cancels runs an administrator started with the other background work: a run stops between two components, its record unfinished, and the next hourly check takes it up. | 5.2. |

## 6. The web UI (plan 16c)

- Administration, Cleanup policies, after Content selectors, with `admin:cleanup:read`: the list (name, format, criteria in words, the repositories attached), a new one at `/admin/cleanup-policies/~new`, one at `/admin/cleanup-policies/<name>`, deleted after a question that names the repositories it will be detached from.
- The form: name, description, format (chosen once), and each criterion turned on with its value; release type only for a format that has one. Beside it, the preview: a repository of the format chosen, and the components the policy would remove from it, a page at a time, with the total, refreshed as the form changes.
- A repository's settings: a Cleanup section with the policies attached, the last run (when, how many removed, or the error), and "Clean up now", which asks first, saying how many components it would remove (5.1's count). The policies of its format are offered to attach to whoever holds `admin:cleanup:read`; to others, the section shows those attached, and keeps them, as a role's row shows a selector to whoever may not read selectors (U3 of the identity spec).
- The role editor's administration areas gain `cleanup`.

## 7. Formats

### 7.1 What a component is

As each format already has it: a Maven version (a `-SNAPSHOT` with every timestamped build of it), an npm version, a PyPI release, a NuGet version (its package, its `.nuspec`, its symbols), a Docker tag, an APT, YUM or apk package version, a Raw file.

### 7.2 What goes with it

A proxy's files the format keeps for a component but that belong to none go with it: PyPI's `.metadata` beside a cached file. The builder finds the others format by format, and a format says them (it knows its own paths).

### 7.3 Docker

- A tag's last download is the newest of its own and of the manifest it names (an image pulled by digest is in use).
- A tag removed by a run takes the manifest it named, when no other tag names it and no index manifest refers to it, with the effects of deleting that manifest by its digest (its platform manifests and layers nothing else refers to). Its layers go at the next upkeep, as now. This is the run's alone: a tag deleted through the API or the registry still goes alone, as the Docker spec decided, for whoever pins by digest. Without it a Docker cleanup would give back no space; Nexus's cleanup removes the image too.
- A policy of "not updated" alone removes a tag, and its manifest, however often the image is pulled by digest: that is what the policy says. "Not downloaded" is the criterion that keeps what is pulled (above), and the guides say so.
- In a proxy, the same: a manifest removed is fetched again from the remote when asked.
- A manifest pulled by its digest alone, with no tag, is not a component (section 2: a task type).

## 8. Errors and limits

- A policy's fields are checked when saved, each refused at its field: a name, a format that does not exist, a day count out of range, a release type for a format without one, a pattern that does not compile or repeats a repetition, no criterion at all.
- Every new list is paged (API-5).
- The preview answers in the time a search does; a policy a database cannot narrow (a pattern alone) reads the repository's paths in pages.

## 9. Testing

- The criteria tested alone and together against components made in the test, with their times set: just inside and just outside each count of days, never downloaded, a pre-release in each format that has them, a pattern that matches one file of several.
- Each format's component removed by a run, and what it leaves checked as a delete through the API leaves it: npm's dist-tags no longer naming the version, a NuGet version's symbols gone, an APT index without the package, a Docker tag's manifest gone with it and kept while another tag names it.
- The run: a component touched between selection and delete is kept (E6); a read-only repository cleaned (E4); a failure on one component does not stop the others; two containers never run at once; a restart does not push the run back.
- The preview's results and total equal what a run then removes.
- The container tests (marked `docker`): a proxy of npm cleaned by "not downloaded", the client resolving afterwards from the remote again.

## 10. Plans

| Plan | What it builds |
| --- | --- |
| 16a | Policies' records, criteria, API and audit; attaching them to repositories; the preview. |
| 16b | The run: deleting through the format without a caller, the daily check, running now, the last run, Docker's and the proxies' companions. |
| 16c | The Cleanup policies screens with their preview, the repository's Cleanup section, the role editor's area. |

Each ends with something that works: 16a with a policy whose preview lists what it would remove, 16b with that removed, 16c with both on screen.

## 11. Risks

| Risk | What settles it |
| --- | --- |
| A policy removes what is still wanted. | The preview (CLN-3); "not downloaded" counting from creation; E6's second check. |
| A run takes hours on a large repository and holds the database. | A transaction per component; pages; one run at a time. |
| A crafted pattern stalls the run. | G14's refusal, as selectors. |
| A Docker image removed while pinned by digest. | Section 7.3: the manifest's downloads keep its tag. |
| The space does not come back. | Compaction, as for every delete (E7); the guides say when. |

## 12. Requirements

| BRD | Where |
| --- | --- |
| CLN-1 Criteria: last update, last download, release type, asset name | 4.2 |
| CLN-2 One format or all, attached to any number of repositories | 4.1, 4.3 |
| CLN-3 A preview before attaching | 4.4, 6 |
| REP-15 Policies attached to a repository | 4.3 |
| API-4 Cleanup policies in the API | 4.5, 5.1 |
