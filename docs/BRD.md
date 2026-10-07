# MegooArti — Business Requirements Document

| | |
| --- | --- |
| **Document** | Business Requirements Document (BRD) |
| **Product** | MegooArti — Repository & Artifact Proxy & Manager |
| **Version** | 0.1 (draft for review) |
| **Date** | 2026-10-07 |
| **Owner** | Mohamed M. Hammad |
| **Baseline for parity** | Sonatype Nexus Repository OSS 3.x |

---

## 1. Summary

MegooArti is an open-source repository manager. It stores build artifacts that teams publish (hosted repositories), caches packages from public registries (proxy repositories), and combines both behind a single URL (group repositories). Developers and CI systems use it through their normal tools — `mvn`, `npm`, `pip`, `docker` and others — without any MegooArti-specific client.

The product goal is feature parity with Nexus Repository OSS, delivered on a FastAPI backend and a Next.js frontend, with a distinctive cyberpunk-styled UI. Parity is the long-term vision. Delivery is phased: a first release covers the core platform and five formats, and later phases add the remaining formats and administration features.

## 2. Business case

### 2.1 Problem

Teams that want a self-hosted repository manager have few open-source choices, and the established one has costs:

- Nexus Repository is a large Java application. It needs a tuned JVM, has a heavy memory footprint, and is hard for most teams to extend or debug.
- Features that modern teams treat as basic — single sign-on and per-user access tokens — are reserved for the paid edition.
- Recent Nexus Community Edition releases apply usage limits, which pushes growing teams toward a paid licence.
- The administration UI is dated and slow to navigate.

### 2.2 Opportunity

A repository manager written in Python and TypeScript is approachable for a much larger contributor base, starts from a single `docker compose up`, and can include SSO and API tokens in the open-source edition.

### 2.3 Objectives

| ID | Objective |
| --- | --- |
| OBJ-1 | Provide an open-source repository manager that existing package clients can use unmodified. |
| OBJ-2 | Reach feature parity with Nexus Repository OSS 3.x across three delivery phases. |
| OBJ-3 | Include OIDC single sign-on and personal API tokens in the open-source edition. |
| OBJ-4 | Make installation and upgrade a single-container-image operation with automatic schema migration. |
| OBJ-5 | Offer a UI with a recognisable cyberpunk identity that remains accessible in light and dark modes. |
| OBJ-6 | Keep the codebase approachable so that a contributor can add a new package format without touching the core. |

### 2.4 Success metrics

| ID | Metric | Target |
| --- | --- | --- |
| SM-1 | Client compatibility test suite (real clients run against a live instance) | 100% pass for every format in a released phase |
| SM-2 | Time from `docker compose up` on a clean host to the first package served through a proxy repository | Under 10 minutes, following only the README |
| SM-3 | Upgrade between consecutive releases | No manual database steps; migrations run automatically at container start |
| SM-4 | Accessibility | WCAG 2.1 AA contrast in both light and dark modes on every screen |
| SM-5 | Nexus OSS parity checklist (Appendix A) | 100% of Phase 1 items at the Phase 1 release, and likewise for each later phase |
| SM-6 | Format extensibility | A Phase 2 format is added without changes to core modules other than registration |

Community adoption targets (stars, installs, contributors) are deliberately not set in this version. They will be set after the Phase 1 release, when there is a baseline to measure against.

## 3. Stakeholders and personas

| Persona | Description | Primary needs |
| --- | --- | --- |
| **Platform administrator** | Installs and operates MegooArti for a team or organisation | Simple deployment, repository and storage configuration, access control, cleanup, backup, monitoring |
| **Developer** | Publishes and consumes packages from a workstation | Works with native tools, fast downloads, searchable UI, self-service API tokens |
| **CI system** | A pipeline runner (any CI product) that resolves dependencies and publishes build output | Token authentication, reliable proxy cache, predictable URLs, REST API |
| **Security / compliance reviewer** | Audits who can access and change what | Role-based access control, audit log, SSO integration |
| **Open-source contributor** | Extends or fixes MegooArti | Clear module boundaries, documented format interface, reproducible development environment |

Project stakeholders are the product owner (the maintainer) and the contributor community.

## 4. Scope

### 4.1 In scope

- Hosted, proxy and group repositories for the formats listed in section 4.3.
- Blob storage on a local filesystem and on S3-compatible object storage.
- Component and asset browsing, search, upload and deletion.
- Users, roles, privileges, content selectors, and authentication through local accounts, LDAP, OIDC and personal API tokens.
- Cleanup policies, routing rules and scheduled tasks.
- Webhooks and an audit log.
- A documented REST API covering every administrative and browsing function.
- A web UI with a cyberpunk theme in light and dark modes.
- Docker-based distribution with automatic Alembic migrations at container start.

### 4.2 Out of scope

These are not planned in any phase of this BRD. Each may be reconsidered in a later revision.

| Item | Reason |
| --- | --- |
| High-availability clustering (active-active nodes) | Nexus Pro feature; large architectural cost |
| Staging, build promotion and component tagging | Nexus Pro feature |
| Repository replication between instances | Nexus Pro feature |
| Vulnerability and licence scanning of components | Separate product area |
| SAML authentication | OIDC covers the SSO need; SAML can follow on demand |
| Multi-tenancy (isolated organisations in one instance) | Not part of Nexus OSS; not needed for the target user |
| Importing data from an existing Nexus instance | Valuable, but a separate project once parity exists |
| Wire compatibility with the Nexus REST API | MegooArti defines its own REST API; only package-client protocols must be compatible |
| Groovy scripting API | Disabled by default in Nexus for security reasons; the REST API replaces it |
| A hosted (SaaS) offering | The product is self-hosted |

### 4.3 Delivery phases

| Phase | Platform features | Formats |
| --- | --- | --- |
| **1 — MVP** | Hosted, proxy and group repositories; filesystem blob store; browse, search, upload, delete; local users and role-based access control; personal API tokens; anonymous access; REST API; web UI; Docker distribution with automatic migrations | Maven, npm, PyPI, Docker, Raw |
| **2 — Operations** | S3 blob store; LDAP; OIDC single sign-on; cleanup policies; scheduled tasks; routing rules; content selectors; webhooks; audit log; metrics endpoint | NuGet, Helm, Go, APT, YUM |
| **3 — Full parity** | Email server settings; outbound HTTP proxy settings; trusted certificates; support bundle; log viewer; remaining admin parity | RubyGems, Cargo, Conan, Conda, R, Git LFS, p2, CocoaPods, Bower |

A phase is complete when every **Must** requirement assigned to it is met and SM-1 passes for its formats.

## 5. Functional requirements

Each requirement has an ID, a phase (P1, P2 or P3) and a priority: **Must**, **Should** or **Could**.

### 5.1 Repository management

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| REP-1 | An administrator can create, edit and delete repositories of type hosted, proxy and group for every supported format. | P1 | Must |
| REP-2 | Each repository has a unique name, a format, a type, an online/offline flag and an assigned blob store. Name, format, type and blob store cannot change after creation. | P1 | Must |
| REP-3 | Each repository is reachable at a stable, documented URL derived from its name. | P1 | Must |
| REP-4 | A hosted repository has a deployment policy: allow redeploy, disable redeploy, or read-only. | P1 | Must |
| REP-5 | A proxy repository has a remote URL and caches every asset it serves. | P1 | Must |
| REP-6 | A proxy repository has configurable maximum ages for cached components and cached metadata, after which it revalidates against the remote. | P1 | Must |
| REP-7 | A proxy repository has a negative cache with a configurable time-to-live, so repeated requests for missing assets do not reach the remote. | P1 | Must |
| REP-8 | A proxy repository can authenticate to its remote with a username and password or a bearer token. | P1 | Must |
| REP-9 | A proxy repository can be manually blocked, and auto-blocks when the remote is unreachable, retrying with back-off. Its status is visible in the UI and API. | P1 | Should |
| REP-10 | A proxy repository serves cached content when the remote is unavailable. | P1 | Must |
| REP-11 | A group repository has an ordered list of member repositories of the same format and resolves each request against members in that order. | P1 | Must |
| REP-12 | A group repository merges format metadata (for example Maven `maven-metadata.xml`, npm package documents, PyPI index pages) across its members. | P1 | Must |
| REP-13 | An administrator can invalidate a proxy repository's cache and rebuild a repository's search index on demand. | P1 | Should |
| REP-14 | Strict content-type validation can be enabled per repository, rejecting assets whose content does not match their declared type. | P2 | Should |
| REP-15 | A repository can have one or more cleanup policies attached (see 5.6). | P2 | Must |
| REP-16 | A proxy repository can have a routing rule attached (see 5.6). | P2 | Must |

### 5.2 Package formats

For every format, "supported" means the format's standard clients can resolve, download and (for hosted repositories) publish packages with no MegooArti-specific configuration beyond the repository URL and credentials.

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| FMT-1 | **Maven**: hosted, proxy and group. Version policy (release, snapshot, mixed) and layout policy (strict, permissive). Checksums and `maven-metadata.xml` are generated and maintained. Timestamped snapshots are supported. | P1 | Must |
| FMT-2 | **npm**: hosted, proxy and group. Scoped packages, dist-tags, `npm login` / `npm publish` / `npm unpublish` / `npm deprecate`, and package search. Works with npm, pnpm and Yarn. | P1 | Must |
| FMT-3 | **PyPI**: hosted, proxy and group. The simple index (PEP 503), uploads from `twine`, and installs from `pip`, `uv` and Poetry. | P1 | Must |
| FMT-4 | **Docker**: hosted, proxy and group, implementing the OCI Distribution / Docker Registry V2 API, including chunked blob upload, manifest lists and token authentication. Push and pull work with Docker, Podman and containerd. | P1 | Must |
| FMT-5 | **Docker**: repositories are addressable by path (`host/repository/image:tag`) with no per-repository port. | P1 | Must |
| FMT-6 | **Docker**: a repository can optionally be bound to a dedicated port or hostname, for clients that require the registry at the host root. | P2 | Could |
| FMT-7 | **Docker**: anonymous pull can be enabled per repository. | P1 | Should |
| FMT-8 | **Raw**: hosted, proxy and group. Arbitrary files stored and served by path with HTTP `PUT`, `GET`, `HEAD` and `DELETE`. | P1 | Must |
| FMT-9 | **NuGet** (V3 API; V2 where needed for proxying): hosted, proxy and group, with API-key authentication. | P2 | Must |
| FMT-10 | **Helm**: hosted and proxy, with `index.yaml` generation. | P2 | Must |
| FMT-11 | **Go**: proxy and group, implementing the GOPROXY protocol. | P2 | Must |
| FMT-12 | **APT**: hosted and proxy, with repository metadata signing using an administrator-supplied GPG key. | P2 | Must |
| FMT-13 | **YUM**: hosted, proxy and group, with `repodata` generation at a configurable depth. | P2 | Must |
| FMT-14 | **RubyGems**: hosted, proxy and group. | P3 | Must |
| FMT-15 | **Cargo**: hosted, proxy and group, using the sparse registry protocol. | P3 | Must |
| FMT-16 | **Conan**: hosted and proxy. | P3 | Must |
| FMT-17 | **Conda**: proxy. | P3 | Must |
| FMT-18 | **R** (CRAN): hosted, proxy and group. | P3 | Must |
| FMT-19 | **Git LFS**: hosted. | P3 | Must |
| FMT-20 | **p2**: proxy. | P3 | Should |
| FMT-21 | **CocoaPods**: proxy. | P3 | Could |
| FMT-22 | **Bower**: hosted, proxy and group. | P3 | Could |
| FMT-23 | Each format is implemented behind a common format interface, so that adding a format does not require changes to repository, storage, security or search code. | P1 | Must |

### 5.3 Blob storage

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| BLB-1 | An administrator can create, view and delete blob stores. A blob store in use by a repository cannot be deleted. | P1 | Must |
| BLB-2 | A filesystem blob store writes to a configured directory. | P1 | Must |
| BLB-3 | An S3 blob store writes to a bucket on Amazon S3 or an S3-compatible service (for example MinIO), with configurable endpoint, region, prefix, credentials and encryption setting. | P2 | Must |
| BLB-4 | Each blob store reports its blob count, total size and, where the backend provides it, available space. | P1 | Must |
| BLB-5 | A blob store can have a soft quota. Exceeding it raises a warning in the UI, the health endpoint and the log; it does not block writes. | P2 | Should |
| BLB-6 | Deleting an asset marks its blob as deleted. A compaction task removes deleted blobs permanently. | P1 | Must |
| BLB-7 | Identical content in the same blob store is stored once. | P1 | Should |
| BLB-8 | Every blob's checksum is recorded at write time and can be verified by an integrity task. | P2 | Should |

### 5.4 Components, assets and search

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| CMP-1 | Stored content is modelled as components (a named, versioned package) made up of one or more assets (individual files). | P1 | Must |
| CMP-2 | A user can browse a repository as a folder tree and open any component or asset. | P1 | Must |
| CMP-3 | An asset's detail view shows its path, size, content type, checksums (MD5, SHA-1, SHA-256, SHA-512), blob store, who uploaded it, and when it was created, last updated and last downloaded. | P1 | Must |
| CMP-4 | A component's detail view shows format-specific usage snippets (for example a Maven dependency block, `npm install`, `pip install`, `docker pull`). | P1 | Should |
| CMP-5 | A user can search across all repositories they may read, by keyword, format, repository, name, group or namespace, version, and checksum. | P1 | Must |
| CMP-6 | Search offers format-specific fields (for example Maven group, artifact and classifier; npm scope; Docker image name and tag). | P1 | Should |
| CMP-7 | A user with the required privilege can upload a component through the UI for formats where that is meaningful (Maven, npm, PyPI, Raw in P1; others as their formats arrive). | P1 | Must |
| CMP-8 | A user with the required privilege can delete an asset, a component or a folder. | P1 | Must |
| CMP-9 | Browse and search results never reveal content the user has no privilege to read. | P1 | Must |

### 5.5 Security and access control

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| SEC-1 | An administrator can create, edit, disable and delete local users, and reset their passwords. | P1 | Must |
| SEC-2 | On first start, an `admin` account is created with a randomly generated password that is written to a file inside the container and to the start-up log. The administrator must change it at first sign-in. | P1 | Must |
| SEC-3 | Access is governed by privileges. Privileges are grouped into roles, roles can contain other roles, and users are assigned roles. | P1 | Must |
| SEC-4 | Privilege types cover: administrative functions by area, repository administration, and repository content actions (browse, read, add, edit, delete) scoped by format and repository, including "all formats" and "all repositories". | P1 | Must |
| SEC-5 | Built-in `admin` and `anonymous` roles exist and can be assigned like any other role. | P1 | Must |
| SEC-6 | Anonymous access can be switched on or off globally. When on, unauthenticated requests receive the privileges of a configured anonymous user. | P1 | Must |
| SEC-7 | A signed-in user can create, name, list and revoke personal API tokens. A token's value is shown once, at creation. | P1 | Must |
| SEC-8 | A personal API token can have an expiry date and can be restricted to a subset of the owner's privileges. | P1 | Should |
| SEC-9 | Package clients can authenticate with a personal API token wherever they accept a password, a bearer token or an API key (HTTP Basic, `npm login`, `docker login`, NuGet API key). | P1 | Must |
| SEC-10 | An administrator can list and revoke any user's tokens. | P1 | Must |
| SEC-11 | A content selector is a named expression over format and path. A content-selector privilege grants actions only on content the selector matches. | P2 | Must |
| SEC-12 | An administrator can configure one or more LDAP servers (connection, bind credentials, user and group mapping), test the connection, and map LDAP groups to roles. | P2 | Must |
| SEC-13 | An administrator can configure one or more OIDC providers (issuer, client credentials, scopes, claim mapping) and map a groups claim to roles. Users can sign in to the UI through a configured provider. | P2 | Must |
| SEC-14 | Users who sign in through LDAP or OIDC are created on first sign-in and can hold personal API tokens. | P2 | Must |
| SEC-15 | Authentication sources (local, LDAP, OIDC) can be enabled, disabled and ordered. | P2 | Must |
| SEC-16 | A default role can be configured that every authenticated user receives. | P2 | Should |
| SEC-17 | Authentication through a trusted reverse-proxy header can be enabled, for deployments behind an authenticating proxy. | P3 | Could |
| SEC-18 | An administrator can manage a list of trusted TLS certificates used for connections to remotes, LDAP and email servers. | P3 | Should |
| SEC-19 | Repeated failed sign-ins are rate limited. | P1 | Must |

### 5.6 Cleanup policies, routing rules and tasks

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| CLN-1 | An administrator can define cleanup policies with criteria: time since last update, time since last download, release type (release or pre-release) where the format supports it, and an asset-name pattern. | P2 | Must |
| CLN-2 | A cleanup policy applies to one format or to all formats, and can be attached to any number of matching repositories. | P2 | Must |
| CLN-3 | An administrator can preview which components a cleanup policy would remove from a given repository before attaching it. | P2 | Should |
| CLN-4 | A routing rule is a named list of path patterns in allow or block mode. When attached to a proxy repository, requests that the rule rejects are not sent to the remote. | P2 | Must |
| TSK-1 | An administrator can create, edit, enable, disable, run, stop and delete tasks. | P2 | Must |
| TSK-2 | A task runs manually, once at a set time, or on an hourly, daily, weekly, monthly or cron schedule. | P2 | Must |
| TSK-3 | Each task records its last run time, duration and result, and can notify an email address on failure once email is configured. | P2 | Should |
| TSK-4 | Task types include at least: run cleanup policies, compact a blob store, rebuild a repository's search index, verify blob integrity, remove unused Docker manifests and layers, remove incomplete Docker uploads, remove Maven snapshots, and rebuild Maven metadata. | P2 | Must |
| TSK-5 | Blob compaction and Docker upload cleanup are available in Phase 1 as built-in maintenance that runs on a fixed schedule, before the task UI exists. | P1 | Must |
| TSK-6 | Scheduled work survives a restart: a missed run executes at the next start, and a task never runs twice at the same time. | P2 | Must |

### 5.7 Webhooks and audit

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| EVT-1 | An administrator can register webhooks that send an HTTP `POST` with a JSON payload when events occur. | P2 | Must |
| EVT-2 | Global webhooks cover repository created, updated and deleted, and audit events. Repository webhooks cover component and asset created, updated and deleted in one repository. | P2 | Must |
| EVT-3 | Each webhook can have a secret; payloads are signed with HMAC-SHA256 in a request header. | P2 | Must |
| EVT-4 | Failed deliveries are retried with back-off, and recent deliveries with their outcomes are visible to administrators. | P2 | Should |
| EVT-5 | An audit log records every change to configuration and security: what changed, who changed it, when, and from which address. | P2 | Must |
| EVT-6 | Administrators can view, filter and export the audit log. Audit records cannot be edited or deleted through the UI or API. | P2 | Must |

### 5.8 REST API

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| API-1 | Every function available in the UI is available through a versioned REST API. The UI uses only this API. | P1 | Must |
| API-2 | The API is described by an OpenAPI document, and interactive API documentation is served by the application. | P1 | Must |
| API-3 | The API accepts session authentication (for the UI), HTTP Basic, and personal API tokens as bearer tokens. | P1 | Must |
| API-4 | The API covers at least: repositories, blob stores, components, assets, search, upload, users, roles, privileges, tokens and system status in P1; and content selectors, LDAP, OIDC, cleanup policies, routing rules, tasks, webhooks and audit in P2. | P1 / P2 | Must |
| API-5 | List endpoints are paginated and return errors in one consistent, documented format. | P1 | Must |
| API-6 | Breaking changes to the API require a new API version; the previous version remains available for at least one minor release. | P1 | Should |

### 5.9 System administration

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| SYS-1 | An administrator can set the instance's public base URL, used in generated links and usage snippets. | P1 | Must |
| SYS-2 | Unauthenticated liveness and readiness endpoints report whether the application is running and whether it can reach its database and blob stores. | P1 | Must |
| SYS-3 | A metrics endpoint exposes request, repository, storage and task metrics in Prometheus format, restricted to privileged users or a configured token. | P2 | Must |
| SYS-4 | A system information page shows the application version, schema revision, runtime details and blob store status. | P1 | Should |
| SYS-5 | An administrator can configure an outbound HTTP/HTTPS proxy, with exclusions, for connections to remotes. | P3 | Must |
| SYS-6 | An administrator can configure an SMTP server and send a test email. | P3 | Must |
| SYS-7 | An administrator can view recent application logs and change log levels at runtime. | P3 | Should |
| SYS-8 | An administrator can download a support bundle containing system information, configuration with secrets removed, and recent logs. | P3 | Should |
| SYS-9 | Settings that Nexus exposes as "capabilities" are provided as ordinary settings pages; a generic capabilities framework is not required. | P1 | Must |

## 6. User interface requirements

### 6.1 General

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| UI-1 | The web UI is built with Next.js and covers browsing, search, upload, user self-service (profile, password, API tokens) and all administration functions of each phase. | P1 | Must |
| UI-2 | Navigation separates the browsing area (search, browse, upload) from the administration area (repositories, storage, security, system). Items a user lacks privileges for are hidden. | P1 | Must |
| UI-3 | The UI is fully usable at widths of 1024 px and above. Browsing and search are usable down to 375 px. | P1 | Should |
| UI-4 | All UI text is held in translation resources, with English as the only language shipped. | P1 | Should |
| UI-5 | Every screen has loading, empty and error states, and destructive actions require confirmation. | P1 | Must |
| UI-6 | Every screen is operable by keyboard alone and exposes correct labels to screen readers. | P1 | Must |

### 6.2 Cyberpunk theme

| ID | Requirement | Phase | Priority |
| --- | --- | --- | --- |
| UI-7 | The visual identity is cyberpunk: a neon accent palette (cyan, magenta and an acid yellow or green), glow and outline effects on interactive elements, and angular, technical shapes. | P1 | Must |
| UI-8 | Typography uses a futuristic display typeface for headings and navigation, a monospace typeface for coordinates, paths, checksums and code, and a highly legible typeface for body text and tables. | P1 | Must |
| UI-9 | The UI has a dark mode (neon accents on near-black surfaces) and a light mode (deepened, saturated accents on pale surfaces). Both are complete; neither is a fallback. | P1 | Must |
| UI-10 | The user can choose light, dark or "follow system". The choice persists across sessions, and the page never flashes the wrong mode while loading. | P1 | Must |
| UI-11 | Text and interactive elements meet WCAG 2.1 AA contrast in both modes. Where a neon accent fails contrast as text, it is used for borders, glows and icons only, and a compliant tone is used for the text. | P1 | Must |
| UI-12 | Colours, type, spacing, radii and glow effects are defined as design tokens, with one token set per mode. Components reference tokens, never literal colour values. | P1 | Must |
| UI-13 | Animation and glow effects are reduced or removed when the user's system requests reduced motion. | P1 | Must |
| UI-14 | Fonts and all other UI assets are served by MegooArti itself. The UI makes no requests to third-party hosts, so that it works in air-gapped networks. | P1 | Must |
| UI-15 | Status is never conveyed by colour alone; an icon or label always accompanies it. | P1 | Must |

## 7. Non-functional requirements

| ID | Category | Requirement | Phase | Priority |
| --- | --- | --- | --- | --- |
| NFR-1 | Compatibility | Each supported format is verified by an automated suite that runs the format's real clients against a running instance. | P1 | Must |
| NFR-2 | Performance | Uploads and downloads are streamed. Memory use does not grow with artifact size. | P1 | Must |
| NFR-3 | Performance | A single artifact of at least 10 GB can be uploaded and downloaded. | P1 | Must |
| NFR-4 | Performance | On a reference host (4 vCPU, 8 GB RAM, SSD, filesystem blob store), requests for cached metadata complete in under 200 ms at the 95th percentile with 100 concurrent clients. | P1 | Should |
| NFR-5 | Performance | HTTP range requests and conditional requests (`ETag`, `If-Modified-Since`) are supported for asset downloads. | P1 | Must |
| NFR-6 | Security | Passwords are stored with a memory-hard hash (Argon2id). API tokens are stored only as hashes. | P1 | Must |
| NFR-7 | Security | Secrets held in configuration (remote credentials, LDAP bind passwords, OIDC client secrets, S3 keys, webhook secrets) are encrypted at rest with a key supplied at deployment, and are never returned by the API. | P1 | Must |
| NFR-8 | Security | The application is designed to run behind a TLS-terminating reverse proxy and handles forwarded headers correctly. | P1 | Must |
| NFR-9 | Security | The UI is protected against cross-site request forgery and cross-site scripting; session cookies are `HttpOnly`, `Secure` and `SameSite`. | P1 | Must |
| NFR-10 | Security | Dependencies are scanned for known vulnerabilities in CI, and the container runs as a non-root user. | P1 | Must |
| NFR-11 | Reliability | An asset becomes visible only after its blob is fully written and its checksum verified. An interrupted upload leaves no partial asset. | P1 | Must |
| NFR-12 | Reliability | A documented procedure exists for backing up and restoring the database and blob stores to a consistent state. | P1 | Must |
| NFR-13 | Reliability | The application shuts down gracefully, letting in-flight requests finish within a configurable period. | P1 | Should |
| NFR-14 | Observability | Logs are structured (JSON) on standard output, and each request carries a correlation ID. | P1 | Must |
| NFR-15 | Operability | All deployment configuration is supplied through environment variables, each one documented. | P1 | Must |
| NFR-16 | Scalability | Several application containers can serve requests against one database and one shared blob store. (This is horizontal scaling for throughput, not the HA clustering excluded in 4.2.) | P2 | Should |
| NFR-17 | Maintainability | Backend and frontend code have automated unit and integration tests that run in CI on every change. | P1 | Must |
| NFR-18 | Documentation | Installation, upgrade, configuration, per-format client setup, and a "how to add a format" guide are published with each release. | P1 | Must |

## 8. Technical constraints

These are decisions already made. Designs must conform to them.

### 8.1 Technology stack

| ID | Constraint |
| --- | --- |
| TC-1 | The backend is written in Python using FastAPI. |
| TC-2 | The frontend is written in TypeScript using Next.js. |
| TC-3 | PostgreSQL is the only supported database. |
| TC-4 | The backend and frontend are distributed as Docker images, and a Docker Compose file is provided that starts a complete working instance including PostgreSQL. |
| TC-5 | The project is released under an open-source licence (see assumption A-1). |

### 8.2 Database migrations

| ID | Constraint |
| --- | --- |
| MIG-1 | The database schema is managed only by Alembic. The application never creates or alters tables by any other means at runtime. |
| MIG-2 | Every schema change is delivered as an Alembic migration script that is committed with the code change that needs it. |
| MIG-3 | The repository contains helper scripts for the common migration operations: create a new revision, upgrade, downgrade, and show the current revision and history. |
| MIG-4 | The backend image's Docker entrypoint script waits for the database to accept connections, runs `alembic upgrade head`, and only then starts the application process. |
| MIG-5 | If a migration fails, the entrypoint exits with a non-zero status and the application does not start. |
| MIG-6 | Running the entrypoint against an up-to-date database is a no-op, so restarts are safe. |
| MIG-7 | Migrations take a database lock, so that several containers starting at once do not run the same migration concurrently. |
| MIG-8 | An environment variable can disable the automatic migration, for operators who run migrations as a separate deployment step. |
| MIG-9 | CI verifies that the migration history has a single head and that migrating an empty database to head succeeds. |
| MIG-10 | Each migration provides a downgrade path, except where data loss makes that impossible; such migrations are called out in the release notes. |
| MIG-11 | The migration history starts from the first release and is never rewritten after a release. |

## 9. Assumptions, dependencies and risks

### 9.1 Assumptions

| ID | Assumption |
| --- | --- |
| A-1 | The licence is Apache-2.0. This is a placeholder pending the owner's confirmation. |
| A-2 | "Nexus OSS parity" means the feature set of Nexus Repository OSS 3.x as summarised in Appendix A. Formats added to Nexus after this baseline are considered release by release. |
| A-3 | Operators provide TLS termination, backups of the database volume and blob storage, and monitoring infrastructure. |
| A-4 | A deployment is a single logical instance serving one organisation. |
| A-5 | MIG-3's "scripts" are developer convenience scripts wrapping Alembic commands, in addition to the migration scripts themselves. |

### 9.2 Dependencies

- Upstream public registries (Maven Central, npmjs, PyPI, Docker Hub and others) and the stability of their protocols.
- Published protocol specifications for each format, and the behaviour of each format's reference client.
- PostgreSQL, and for the S3 blob store an S3-compatible service.

### 9.3 Risks

| ID | Risk | Impact | Mitigation |
| --- | --- | --- | --- |
| R-1 | The scope of full parity is very large for an open-source project. | Delivery stalls before the product is useful. | Phase 1 is a usable product on its own; the format interface (FMT-23) lets contributors add formats in parallel. |
| R-2 | Format protocols are complex and partly undocumented (Docker, Maven metadata, npm). | Clients fail in ways unit tests do not catch. | Compatibility is tested with real clients (NFR-1), and that suite defines "done". |
| R-3 | Python throughput for large binary transfers is lower than the JVM's. | Slow pushes and pulls under load. | Streaming I/O (NFR-2), performance targets (NFR-4), horizontal scaling (NFR-16), and redirecting downloads to object storage where the backend allows. |
| R-4 | Neon colours conflict with contrast requirements, especially in light mode. | An inaccessible or unreadable UI. | Contrast is a Must (UI-11), enforced by automated checks on the design tokens. |
| R-5 | Automatic migration at start-up can fail or run concurrently. | Outage on upgrade or schema corruption. | Fail-fast (MIG-5), locking (MIG-7), opt-out (MIG-8) and CI checks (MIG-9). |
| R-6 | A repository manager is a software supply-chain target. | A compromise affects every consumer of its packages. | Security requirements in 5.5 and section 7, the audit log, dependency scanning, and a published security disclosure policy. |
| R-7 | Upstream registries change protocols or rate-limit proxies. | Proxy repositories break. | Auto-blocking and serving from cache (REP-9, REP-10); scheduled compatibility runs against live upstreams. |
| R-8 | Comparison with Nexus raises trademark concerns. | Legal exposure. | "Nexus" is used only to describe compatibility and comparison; no Sonatype branding, names or assets are used in the product. |

## 10. Glossary

| Term | Meaning |
| --- | --- |
| **Artifact** | A file produced by a build, such as a JAR, a wheel, a tarball or a container image layer. |
| **Asset** | A single stored file inside a repository. |
| **Blob store** | The storage location (a directory or an object-storage bucket) that holds the binary content of assets. |
| **Component** | A named and versioned package made up of one or more assets. |
| **Content selector** | An expression that selects content by format and path, used to grant fine-grained access. |
| **Format** | A package ecosystem and its protocol, such as Maven, npm or Docker. |
| **Group repository** | A repository that presents several repositories of one format behind a single URL. |
| **Hosted repository** | A repository that stores artifacts published directly to it. |
| **Proxy repository** | A repository that fetches artifacts from a remote registry on demand and caches them. |
| **Realm** | A source of authentication, such as local accounts, LDAP or OIDC. |
| **Routing rule** | A list of path patterns that restricts which requests a proxy repository sends to its remote. |

## Appendix A — Nexus OSS parity checklist

This table maps Nexus Repository OSS features to MegooArti requirements. It is the basis for metric SM-5.

| Nexus OSS feature | MegooArti requirement | Phase |
| --- | --- | --- |
| Hosted, proxy and group repositories | REP-1 to REP-12 | P1 |
| Maven, npm, PyPI, Docker, Raw formats | FMT-1 to FMT-8 | P1 |
| NuGet, Helm, Go, APT, YUM formats | FMT-9 to FMT-13 | P2 |
| RubyGems, Cargo, Conan, Conda, R, Git LFS, p2, CocoaPods, Bower formats | FMT-14 to FMT-22 | P3 |
| File blob store | BLB-1, BLB-2, BLB-4, BLB-6 | P1 |
| S3 blob store, soft quota | BLB-3, BLB-5 | P2 |
| Browse, search, component and asset details | CMP-1 to CMP-6, CMP-9 | P1 |
| UI upload, delete component / asset / folder | CMP-7, CMP-8 | P1 |
| Local users, roles, privileges | SEC-1 to SEC-5 | P1 |
| Anonymous access | SEC-6 | P1 |
| Content selectors | SEC-11 | P2 |
| LDAP realm | SEC-12, SEC-15 | P2 |
| Default role | SEC-16 | P2 |
| Remote-user header authentication | SEC-17 | P3 |
| Trusted SSL certificates | SEC-18 | P3 |
| Cleanup policies | CLN-1 to CLN-3, REP-15 | P2 |
| Routing rules | CLN-4, REP-16 | P2 |
| Scheduled tasks | TSK-1 to TSK-6 | P1 / P2 |
| Webhooks | EVT-1 to EVT-4 | P2 |
| Audit | EVT-5, EVT-6 | P2 |
| REST API with interactive documentation | API-1 to API-6 | P1 / P2 |
| Base URL, status checks, system information | SYS-1, SYS-2, SYS-4 | P1 |
| Metrics | SYS-3 | P2 |
| HTTP proxy, email server, logging, support bundle | SYS-5 to SYS-8 | P3 |
| Capabilities | SYS-9 (provided as settings pages) | P1 |
| Groovy scripting API | Not provided (see 4.2) | — |

**Beyond Nexus OSS** (Pro-only in Nexus, included here):

| Feature | MegooArti requirement | Phase |
| --- | --- | --- |
| Personal API tokens | SEC-7 to SEC-10 | P1 |
| OIDC single sign-on | SEC-13, SEC-14 | P2 |
