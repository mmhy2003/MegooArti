# External identity, the audit log, content selectors and trusted certificates: design

**Date:** 2026-10-19
**Plans:** 15a (sources and external users), 15b (OIDC), 15c (trusted certificates), 15d (LDAP), 15e (trusted header and proxies), 15f (the audit log), 15g (content selectors), 15h (content selectors in the web UI)
**BRD:** SEC-11 to SEC-18, EVT-5, EVT-6, API-4 (its P2 security part)

## 1. Goal

People sign in to MegooArti with the accounts their organisation already has: through an OIDC provider (Keycloak, Entra ID, Okta, Google), an LDAP directory (OpenLDAP, Active Directory), or an authenticating reverse proxy, their groups giving them roles. An administrator sees who changed what, and when, in an audit log nobody can edit; grants access to parts of a repository with content selectors; and has MegooArti trust the certificates of the organisation's own authorities.

## 2. Scope

**In scope:**

- Sign-in sources: local, LDAP, OIDC and a trusted header, enabled, disabled and ordered (D1, D4).
- Users created on first sign-in, refreshed at each one, their groups mapped to roles; a default role every signed-in user has.
- The client's own address taken from trusted proxies' `X-Forwarded-For`.
- Trusted TLS certificates for connections to proxies' remotes, OIDC providers and LDAP servers.
- The audit log of configuration and security changes and of sign-ins, viewed, filtered and exported, kept for a set number of days (D3).
- Content selectors and their permissions, checked everywhere content is read, written, deleted, browsed or searched (D2).
- The web UI of each, the REST API (API-4), the guides; real-client tests against Keycloak and OpenLDAP (D1).

**Out of scope:**

| What | Why |
| --- | --- |
| SAML | BRD 4.2. |
| SCIM, or any import of users before they sign in | SEC-14 is first sign-in; groups are refreshed then. |
| OIDC for package clients (a device flow) | Package clients use API tokens (SEC-9), which an OIDC user makes as anyone does. |
| Signing out of the provider when signing out here (OIDC single logout) | The session here ends; the provider's is the provider's. |
| Email servers' certificates | No email in this phase; SEC-18's list is used by them when they come. |
| Webhooks of audit events (EVT-1, EVT-2) | Their own plan; the audit's records are what they will send. |
| Content selectors over anything but a format and a path | D2: Nexus's expressions over `format` and `path`. |

## 3. Decisions

The product owner's:

| # | Decision | Choice |
| --- | --- | --- |
| D1 | Identity systems | OIDC and LDAP, tested against Keycloak and OpenLDAP in containers; Active Directory's attributes are supported and documented. |
| D2 | Content selectors | Nexus-style expressions (CSEL): `==`, `=^`, `=~`, `and`, `or`, `not`, parentheses. |
| D3 | The audit log's life | Kept a number of days an administrator sets (365 unless set), exported as JSON Lines or CSV; no record is edited or deleted through the UI or the API. |
| D4 | An external user's details | Refreshed at each sign-in; LDAP users no longer in the directory are disabled by an hourly check, which stops their tokens; OIDC users' tokens work until an administrator disables them. |
| D5 | Shape of the work | One spec, a plan for each part (section 13). |

Settled here, by the designer:

| # | What | Why |
| --- | --- | --- |
| E1 | The built-in `admin` always signs in locally, whatever sources are enabled or disabled. | Nobody can lock everyone out by misconfiguring a directory. |
| E2 | A user belongs to one source (`local`, or an LDAP, OIDC or header source), recorded with their identity there (an OIDC subject, an LDAP DN, a header's name); an external user has no local password. | A name taken by two sources must not let one sign in as the other. |
| E3 | A password is checked against the user's own source; a name nobody has yet tries each enabled LDAP source in order, the first that knows it deciding. Basic authentication follows the same rule. | SEC-15's order, without a wrong password being tried against every directory. |
| E4 | Roles given by a source's group mapping are replaced at each sign-in; roles an administrator gives by hand are kept. | Groups decide what a directory says; an administrator's own grants stay theirs. |
| E5 | Every secret of a source (an LDAP bind password, an OIDC client secret) is sealed as a proxy's secret is, and shown to nobody again. | As remotes' secrets. |
| E6 | One function decides access to content, given the repository, the path and the action: `may`. | Selectors are per path; every check must see the path, once and alike. |
| E7 | An audit record is written in the transaction of the change it records. | No change without its record, and no record of a change that was rolled back. |

## 4. Sign-in sources (plan 15a)

### 4.1 Records

- `auth_sources`: id, kind (`ldap`, `oidc`, `header`), name (shown on the sign-in screen and in the user's details), enabled, position, settings (JSON, its secrets sealed), group mapping (a list of `{group, roles}`), created and changed.
- The local source is not a row: it is always first, and can be disabled for everyone but `admin` (E1).
- `users` gains `source` (null for local; else a source's id, `ON DELETE SET NULL` disabling the user) and `external_id`; `user_roles` gains `granted_by` (`admin` or `source`).
- A setting `default_role` (a role's name, or none): added to every signed-in principal's roles, never stored on a user.

### 4.2 Sign-in

- `authenticate_password` (and Basic) is given the sources in order: a user who exists is checked against their own source; a name nobody has tries each enabled LDAP source in order (E3). A disabled source signs no one in; its users are refused as a disabled user is.
- A user signing in through an external source for the first time is created: their name from the source, made unique where it is taken by a user of another source (`name@source`), their display name and email from it, their roles from its group mapping. At each sign-in after, the same are refreshed.
- An external user may make API tokens (SEC-14), sign in to the web UI, and use OAuth (plan 14c).

### 4.3 The Authentication screen

- Under Administration: the sources in order, each enabled or disabled, moved up or down, edited and deleted (its users are disabled, and kept); the default role; for a source, a "Test" button (15b, 15d).
- REST: `GET/POST /api/v1/auth-sources`, `GET/PUT/DELETE /api/v1/auth-sources/{id}`, `PUT /api/v1/auth-sources/order`, `POST /api/v1/auth-sources/{id}/test`; `PUT /api/v1/settings/default-role`. Permissions: `admin:security:read`, `admin:security:write` (a new area).
- `GET /api/v1/auth/sources` (no sign-in needed): the enabled OIDC sources' ids and names, for the sign-in screen.

## 5. OIDC (plan 15b)

- Settings: issuer, client id, client secret (sealed), scopes (`openid profile email` and any more), the claims of the user name (`preferred_username`), the display name (`name`), the email (`email`) and the groups (`groups`), and whether a user must have a verified email.
- The provider's metadata is read from `<issuer>/.well-known/openid-configuration`, and its keys from its `jwks_uri`, each kept for an hour.
- Sign-in: the sign-in screen's "Sign in with <name>" goes to `GET /api/v1/auth/oidc/{id}/start?next=…`, which sends the browser to the provider with a state, a nonce and PKCE (S256), kept sealed in a cookie of ten minutes; `GET /api/v1/auth/oidc/{id}/callback` checks the state, trades the code at the token endpoint (with the client secret), checks the ID token (signature by the provider's keys, `iss`, `aud`, `exp`, `nonce`, at most five minutes' skew), creates or refreshes the user (4.2), starts a session as a password sign-in does, and sends the browser to `next` (as the sign-in screen's return path is checked).
- A provider's refusal (`error=access_denied`), or a token that does not check, is said on the sign-in screen, and logged; nothing is created.
- "Test" fetches the metadata and the keys, and says what was found.
- Tokens are checked with `pyjwt[crypto]` (already a dependency, through the MCP SDK).

## 6. Trusted certificates (plan 15c)

- `trusted_certificates`: id, subject, issuer, fingerprint (SHA-256), not-after, PEM, added by and when.
- The screen (Administration, Certificates): add one by pasting PEM, or by fetching what a host and port present (`POST /api/v1/certificates/fetch`, which adds nothing), then confirming its fingerprint; delete one. Permissions `admin:certificates:read` and `write`.
- Every outbound TLS connection (proxies' remotes, OIDC providers, LDAP's `ldaps://` and StartTLS) trusts the system's authorities and these. The shared HTTP client is made again when the list changes.

## 7. LDAP (plan 15d)

- Settings: the server's address (`ldap://` or `ldaps://`), StartTLS, the bind DN and password (sealed; none for an anonymous bind), the users' base DN and filter (`(uid={username})`, `(sAMAccountName={username})`; `{username}` escaped as RFC 4515 has it), the attributes of the user name, display name and email; groups from an attribute of the user (`memberOf`) or from a search (base, filter with `{dn}` or `{username}`, the group's name attribute); the group mapping. Timeouts of ten seconds.
- Sign-in: bind as the bind DN, find the one entry the filter gives (none or several is a failed sign-in), bind as that entry with the password; then read its groups. An empty password is refused before asking (an LDAP server takes it as an anonymous bind).
- "Test": connect, bind, and, with a user name given, find the entry and its groups, saying what was found; no password is tried.
- Every hour, each enabled LDAP source's users are looked up by their DN; one not found is disabled (and its tokens with it), and logged. A server that cannot be reached disables no one.
- The library is `ldap3`, called in a thread.

## 8. Trusted header and proxies (plan 15e)

- A setting `trusted_proxies`: addresses and networks (CIDR). From them only, `X-Forwarded-For`'s last address not of a trusted proxy is the client's address, for throttling, sessions and the audit log. The gateway is trusted by default where Compose runs it.
- The header source: the header of the user name (`X-Forwarded-User`), and of groups (optional, separated by commas), honoured only from a trusted proxy. A request with the header is that user's (created or refreshed as 4.2), as a session's: its changes need the same-origin check (CSRF's refusal of cross-site requests), as a cookie's do. A request with the header from any other address is refused (`401`).

## 9. The audit log (plan 15f)

- `audit_records`: id, at, actor (user name, or none), how they signed in (`session`, `password`, `token`, `oauth`, `header`, `anonymous`, `system`), address, event (`user.created`, `repository.updated`, `sign_in.failed`, …), target's kind and name, changes (JSON: each changed field's before and after; a secret is `[redacted]`), request ID. Indexed by time, actor, event and target.
- Written by `audit.record(db, event, target, changes)`, with the caller and the request from the request's context, in the transaction of the change (E7), from every route that changes configuration or security (the routes the logs name today `…_created`, `…_updated`, `…_deleted`, `password_changed`, `token_*`, `connected_app_*`, `oauth_*`, `setting_changed`, signing keys, sources, selectors, certificates), and from sign-in (succeeded, failed, throttled; by every source). MCP tools are recorded through the routes they call.
- `GET /api/v1/audit` (paged, filtered by time, actor, event and target; newest first) and `GET /api/v1/audit/export?format=jsonl|csv` (streamed, filtered alike), with `admin:audit:read`. No route edits or deletes a record.
- A setting `audit_retention_days` (365 unless set; at least 1): the hourly job removes older records.
- The screen (Administration, Audit log): the records, filtered, a page at a time, each opening to its changes; the export.

## 10. Content selectors (plans 15g, 15h)

- `content_selectors`: name, description, expression.
- An expression (D2): `format == "maven"`, `path =^ "/com/acme/"`, `path =~ "^/org/[^/]+/[^/]+/1\.0/.*$"`; `and`, `or`, `not`, parentheses; strings in double quotes with `\"` and `\\`. `path` starts with `/`. `=~` matches the whole path (Python's `re.fullmatch`, a pattern of at most 1,000 characters, compiled once). An expression is parsed when it is saved; one that does not parse is refused at its field, saying where.
- A permission `selector:<selector>:<format>:<repository>:<action>` (each part `*` allowed; the actions are the repository permission's) grants an action on a path of a repository where the selector matches.
- `may(principal, repository, path, action)` (E6): a repository permission, as now; or a selector permission whose selector matches `format` and `path`. Every check of content moves to it: reads at the content route and through groups (each member's path checked), writes, deletes, the content API's listings and files (entries a caller may not see are left out), search (results filtered by their files' paths), Docker (the path of the registry's request), and MCP's tools (through the routes).
- A repository is listed among the repositories to a caller who may browse some of it: by a repository permission, or by a selector permission that names it.
- REST: `GET/POST /api/v1/content-selectors`, `GET/PUT/DELETE /api/v1/content-selectors/{name}`, `POST /api/v1/content-selectors/preview` (an expression and paths: which match). Permissions `admin:selectors:read` and `write`. A selector a role names cannot be deleted.
- The screens (15h): Content selectors, with a preview against paths; the role editor's rows offer selector permissions.

## 11. Errors and limits

- Sign-in through an external source answers as a local one does: `401 Invalid credentials.`, throttled alike (SEC-19); what went wrong is logged and audited, not said.
- An external source that cannot be reached: `503 source_unavailable`, saying which source.
- A source's settings are checked when saved: addresses, filters with `{username}`, a mapping's roles that exist.
- Every new list is paged (API-5).

## 12. Testing

- Unit tests of each part in the repository's tests, the providers faked where a container is not needed: an OIDC provider of keys made in the test, an LDAP server answered by `ldap3`'s mock strategy.
- Containers (marked `docker`): Keycloak (a realm imported at start, a client, users and groups) for OIDC through the gateway and in the browser; OpenLDAP (users and groups loaded at start, StartTLS with a certificate of a CA made in the test, trusted through 15c) for LDAP, with Basic from a package client.
- The audit's records asserted by the tests of each change that writes one.
- `may` tested against a table of permissions, selectors, paths and actions, and every route of content tested with a selector that allows a path and refuses its neighbour.

## 13. Plans

| Plan | What it builds |
| --- | --- |
| 15a | Sources' records and screen, external users (first sign-in, refresh, group mapping), the order of password sign-in, the default role. |
| 15b | OIDC sign-in, and Keycloak in the tests. |
| 15c | Trusted certificates, and the outbound client that trusts them. |
| 15d | LDAP sign-in, the hourly check, and OpenLDAP with StartTLS in the tests. |
| 15e | The trusted header source and trusted proxies. |
| 15f | The audit log. |
| 15g | Content selectors and `may`, everywhere content is checked. |
| 15h | Content selectors' screen, and selector permissions in the role editor. |

Each plan ends with something that works: 15a with a default role and the screen, 15b with sign-in through Keycloak, and so on.

## 14. Risks

| Risk | What settles it |
| --- | --- |
| A misconfigured source locks everyone out. | E1, and a source is tested before it is enabled. |
| An LDAP filter injected through a user name. | `{username}` escaped (RFC 4515); a test with `*)(uid=*`. |
| An ID token accepted from the wrong provider, or replayed. | `iss`, `aud`, `nonce` and the keys of that provider; the state and nonce sealed per sign-in. |
| Selectors slow every read (a regex per path). | Expressions compiled once and cached by the selector's version; only a principal holding selector permissions evaluates them. |
| `X-Forwarded-For` spoofed. | Honoured from trusted proxies only, its addresses read from the right past them. |
| The audit log grows without end. | D3's retention. |

## 15. Requirements

| BRD | Where |
| --- | --- |
| SEC-11 Content selectors and their privileges | 10 |
| SEC-12 LDAP servers, tested, groups to roles | 7, 4.3 |
| SEC-13 OIDC providers, claims, groups to roles, sign-in to the UI | 5 |
| SEC-14 Users created at first sign-in, with tokens | 4.2 |
| SEC-15 Sources enabled, disabled and ordered | 4 |
| SEC-16 A default role | 4.1 |
| SEC-17 A trusted reverse-proxy header | 8 |
| SEC-18 Trusted TLS certificates for remotes and LDAP | 6 |
| EVT-5 An audit log of configuration and security changes | 9 |
| EVT-6 Viewed, filtered, exported, not edited | 9 |
| API-4 Content selectors, LDAP, OIDC, audit in the API | 4.3, 6, 9, 10 |
