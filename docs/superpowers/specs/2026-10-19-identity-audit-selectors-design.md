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

### Settled while building plan 15a

| # | What | Why |
| --- | --- | --- |
| S1 | Whether MegooArti's own users sign in is a setting, `local_sign_in` (on unless set), beside `default_role`. Both are read at `GET /api/v1/settings/sign-in` and changed at `PUT /api/v1/settings/local-sign-in` and `PUT /api/v1/settings/default-role`, under `admin:security`; `GET /api/v1/settings` is unchanged. | 4.1 makes the local source no row. Whoever keeps sign-in may not be given the base URL with it, nor need it. |
| S2 | While it is off, a user of ours other than the built-in `admin` is refused as a disabled user is: sign-in, session, Basic, API tokens, OAuth. It is turned off only while `admin` is active, has a password and holds full access (`409 last_administrator`); the check of who remains counts `admin` alone then. | E1, and 4.2's "refused as a disabled user is". Nobody can lock everyone out. |
| S3 | A user's source is `users.source_id` (the spec's `source`), with `external_id`; one user per `(source_id, external_id)`. Deleting a source disables its users and ends their sessions before the key is set null; their `external_id` stays, so they are a deleted source's users, not ours, and have no password. | 4.1, 4.3. A user of a deleted source must not become one of ours by the key's going. |
| S4 | A kind of source is a `sources.Kind` (`checked`, `password`, `test`, its `secrets`, `in_browser`, `takes_passwords`) registered in `sources.KINDS`. This plan registers none: a source can be made once 15b or 15d brings its kind, and until then `kind` is refused with what there is. The tests register kinds of their own. | Section 13: LDAP and OIDC are their own plans; what they share is here. |
| S5 | A source answers a name and a password with who they are, `unknown` (the next source is asked) or `refused` (nobody else is). A user of a source is asked of their own source alone, with their identity there, and is refused if it says another. | E3: the first that knows the name decides; a wrong password is not tried against every directory. |
| S6 | A user's name is what the source says, in lower case, a character a name may not hold made `-`. Where another user has it: `name@source` (the source's name made so too), then `-2`, `-3`. `__token__` and names shaped as a token are never given. The name is brought up to date at each sign-in, as the rest is. | 4.2, and names that the users' API and HTTP Basic take. |
| S7 | Groups are matched whatever their case. A mapped role that does not exist gives nothing; the mapping's roles are checked when it is saved (`422`). | Directories differ in case; section 11. |
| S8 | Each held role records who gave it (`granted_by`: `admin` or `source`). Roles an administrator sets on a user keep a source's role the source's, so the groups still decide it at the next sign-in. | E4. |
| S9 | The default role is added to the permissions of every signed-in principal (session, password, token, OAuth), not to a visitor's. Deleting the role clears the setting. | 4.1. A setting that names nothing would say what no one has. |
| S10 | A user of a source has no password here: setting one is refused, by an administrator or by them, with `409 external_user`. | E2. |
| S11 | `POST /api/v1/auth-sources/{id}/test` takes a name and a password, or nothing, needs `admin:security:write` (it reaches out), and says whether the source answered, who it says they are and the roles the mapping would give. Nobody is made or signed in by it. | 4.3, 14: a source is tested before it is enabled. |
| S12 | `GET /api/v1/auth/sources` lists the enabled sources of a kind signed in to in the browser, by id, name and kind only, paged. | 4.3. It is open: the sign-in screen asks it before anyone signs in. |
| S13 | A source's name is 1 to 64 letters, digits, spaces, `.`, `_` and `-`, beginning with a letter or a digit; not `local`; unique whatever its case. A source is made off, and last. `PUT` replaces all but its kind; a secret left out keeps the stored one. | Shown on the sign-in screen and in `name@source`; 14's "tested before it is enabled"; E5. |
| S14 | A source that cannot be asked answers `503 source_unavailable`, naming it, and is not counted as a failed sign-in. | Section 11. A directory that is down must not lock its users out for 15 minutes. |
| S15 | The Authentication screen lists the sources, turns them on and off, moves, tests and deletes them; the form that makes or edits one comes with its kind, in 15b (OIDC) and 15d (LDAP), whose settings it shows. | A source's settings are its kind's; this plan has no kind to show. |
| S16 | A kind names the settings its secrets go with (`Kind.bound`, such as an address). A change to one keeps no stored secret: it must be sent again (`422` at `settings.<secret>`). | E5: a secret is never sent where it was not given for, by pointing a source elsewhere and pressing Test. |
| S17 | Turning a source off ends its users' sessions, and turning MegooArti's own users off ends theirs but `admin`'s, as disabling a user does; turning them on again brings none back. API tokens work again when it is on. | 4.2's "refused as a disabled user is", for good. |

## 5. OIDC (plan 15b)

- Settings: issuer, client id, client secret (sealed), scopes (`openid profile email` and any more), the claims of the user name (`preferred_username`), the display name (`name`), the email (`email`) and the groups (`groups`), and whether a user must have a verified email.
- The provider's metadata is read from `<issuer>/.well-known/openid-configuration`, and its keys from its `jwks_uri`, each kept for an hour.
- Sign-in: the sign-in screen's "Sign in with <name>" goes to `GET /api/v1/auth/oidc/{id}/start?next=…`, which sends the browser to the provider with a state, a nonce and PKCE (S256), kept sealed in a cookie of ten minutes; `GET /api/v1/auth/oidc/{id}/callback` checks the state, trades the code at the token endpoint (with the client secret), checks the ID token (signature by the provider's keys, `iss`, `aud`, `exp`, `nonce`, at most five minutes' skew), creates or refreshes the user (4.2), starts a session as a password sign-in does, and sends the browser to `next` (as the sign-in screen's return path is checked).
- A provider's refusal (`error=access_denied`), or a token that does not check, is said on the sign-in screen, and logged; nothing is created.
- "Test" fetches the metadata and the keys, and says what was found.
- Tokens are checked with `pyjwt[crypto]` (already a dependency, through the MCP SDK).

### Settled while building plan 15b

| # | What | Why |
| --- | --- | --- |
| O1 | A kind reaches its source through `sources.Outbound`, the server's one outbound HTTP client, given to `Kind.password` and `Kind.test` first. `pyjwt[crypto]` is a dependency of the backend's own. | 15c makes that client trust the added certificates, and every kind with it. The MCP SDK's dependency could go with the SDK. |
| O2 | An OIDC source's settings: `issuer` (http or https, kept as given: a slash at its end is the provider's own, as Auth0's is), `client_id`, `client_secret` (optional: a public client signs in with PKCE alone), `scopes` (`openid profile email` unless set; `openid` always, first), the four claims (`preferred_username`, `name`, `email`, `groups` unless set) and `require_verified_email`. The secret goes with `issuer` and `client_id` (S16). | Section 5. http is for a provider on the server's own network, as Keycloak is in the tests. |
| O3 | The metadata must name the very issuer it was asked of, and have the authorization and token endpoints and `jwks_uri`. Algorithms are RS256 and authentication `client_secret_basic` where it names none; the client's ID and secret are form-encoded in Basic (RFC 6749 2.3.1). | OpenID Discovery 4.3: metadata naming another issuer is another provider's. |
| O4 | Metadata and keys are kept an hour by their address, in the process. Test asks afresh; a key ID not among the kept keys is asked for afresh once (a key rolled over). | Section 5. |
| O5 | Each source has its own redirect address, `<base URL>/api/v1/auth/oidc/{id}/callback` (the address the request came to without a base URL), given by `Kind.callback_path` and shown as `SourceOut.redirect_uri`. | Section 5's paths. A redirect address of its own keeps one provider's answer from being taken for another's. |
| O6 | What a sign-in keeps (the source, state, nonce, PKCE verifier, `next` and the redirect address) is sealed (`secrets_box.seal_at`) in the cookie `megooarti_oidc`: ten minutes, HttpOnly, SameSite=Lax, path `/api/v1/auth/oidc/`, Secure as the session's is. | Section 5. Lax: the cookie must come back with the provider's redirect, a top-level GET. |
| O7 | Both routes end at the sign-in screen: signed in, `/login?next=…&signed_in=1`, from where the UI's gate goes on to `next` if it is an address of its own; else `/login?error=<denied, failed, refused, expired or unavailable>&next=…`. Under the base URL where one is set. | One check of `next`, the UI's, which a password sign-in already uses: the server never redirects to it. |
| O8 | An ID token is taken signed with RS, PS, ES or EdDSA algorithms that the provider says it uses, never `none` or `HS*`; with `exp`, `iat`, `iss`, `aud` and `sub`; at most five minutes' skew; this sign-in's nonce; `azp` naming the client where there are several audiences; and, where the provider sends `iss` with the code (RFC 9207), this provider's. | Section 5, and 14's "an ID token accepted from the wrong provider, or replayed". |
| O9 | Who someone is: `sub` is their identity; their name is the user-name claim, else their email, else `sub`; groups are a list or one string. A source that requires a verified email refuses (`refused`) one whose `email_verified` is not true. | Section 5's claims. Google, for one, has no `preferred_username`. |
| O10 | A sign-in that fails makes nothing (rolled back), is logged as `oidc_sign_in_failed` with why, and is not counted against the sign-in limit: no password was tried. | Section 5: said and logged, nothing created. |
| O11 | A user of an OIDC source has no password here: HTTP Basic with a password is refused; their API tokens work. | E2, SEC-14. |
| O12 | The sign-in screen offers "Sign in with <name>" for each source `GET /api/v1/auth/sources` lists, with `next`, and says each `error` in words of its own; shown with `signed_in=1`, it says the browser did not keep the session. | Section 5. The screen is shown after a sign-in only when there is no session. |
| O13 | A source has a page, `/admin/authentication/{id}`, and a new one is made at `/admin/authentication/~new`, off. The form is OIDC's; a source of another kind is said to be set up through the API until its plan brings its form. A group's roles are rows of a group and a role. The secret is written, never read back. | S15. |
| O14 | The container test runs Keycloak 26.0 beside the stack, on its network as `keycloak:8080` (the issuer's name), its realm imported at start; the test reaches it at port 18080, saying `keycloak:8080` in the Host header. The person's browser is played by HTTP requests through the gateway, which post Keycloak's own sign-in form: the UI's "Sign in with" is a plain link, which Task 3's tests hold to its address. | Section 12. One name for the provider, for the backend and for the browser. |
| O15 | The provider is given 10 seconds an answer (5 to connect), not the proxies' minute. | Section 5. A person is waiting on the other side. |
| O16 | Whatever goes wrong in a sign-in ends on the sign-in screen, never a 500: a secret the server can no longer read (`unavailable`), metadata of the wrong shape (`unavailable`), a state or nonce of any characters, a cookie sealed for another use (it names what it was sealed for, `oidc`), an identity that cannot be kept (`failed`). | Section 5: said on the sign-in screen, and logged. |

## 6. Trusted certificates (plan 15c)

- `trusted_certificates`: id, subject, issuer, fingerprint (SHA-256), not-after, PEM, added by and when.
- The screen (Administration, Certificates): add one by pasting PEM, or by fetching what a host and port present (`POST /api/v1/certificates/fetch`, which adds nothing), then confirming its fingerprint; delete one. Permissions `admin:certificates:read` and `write`.
- Every outbound TLS connection (proxies' remotes, OIDC providers, LDAP's `ldaps://` and StartTLS) trusts the system's authorities and these. The shared HTTP client is made again when the list changes.

### Settled while building plan 15c

| # | What | Why |
| --- | --- | --- |
| C1 | What outbound TLS trusts is one SSL context, `remote.tls_context(pems)`: httpx's own authorities (certifi's, or those of `SSL_CERT_FILE`) and the added certificates. The shared client is built with it, and `sources.Outbound.tls` gives it to what is not HTTP (LDAP, 15d). | Section 6: the system's authorities and these, for every outbound connection. |
| C2 | The certificates are read at start, before anything goes out, and given anew when they change (`remote.trust`): new requests get a new client; the one in use finishes what it has under way, however long, and is closed at shutdown. One change is made at a time, its list read with it and given as it was kept. A list that did not change changes nothing. The server is one process, so this is the whole of it. | Section 6: the shared client is made again. Requests under way are not cut off. |
| C3 | A certificate is pasted one at a time, in PEM: an authority's or a server's own, expired or not (an expired one is kept, and shown as such). Its fingerprint is SHA-256 of its DER bytes, one record each (`409`); subject and issuer are kept as RFC 4514 says them. Who added it is kept by name. | Section 6's record. A name outlives the user. |
| C4 | Fetch connects over TLS directly (no StartTLS), without checking what is presented, for ten seconds, and answers the certificates the host sent, its own first (Python 3.13's unverified chain); a host that cannot be reached so is `502 fetch_failed`. It needs `admin:certificates:write`: it reaches out. | Section 6: fetch adds nothing; the fingerprint is checked by a person. A StartTLS server's authority is pasted. |
| C5 | Removing a certificate stops new connections trusting it; connections open are not undone. | As C2. |
| C6 | The screen is `/admin/certificates`: the list shows a fingerprint's first eight pairs; trusting a fetched certificate asks first, showing its whole fingerprint, in pairs. | Section 6: a fingerprint is confirmed before it is trusted. |
| C7 | Python 3.13's strict checks (`VERIFY_X509_STRICT`) are off for outbound TLS; OpenSSL's own checks hold. | Many organisations' own authorities sign certificates those checks refuse (BasicConstraints not critical, no Authority Key Identifier): the very authorities section 6 is for. |
| C8 | Several processes on one database (NFR-16) would each trust what they read at their start, and what they changed: a change reaches the others at their restart. | One process today; a later plan that runs several gives them a way to hear of it. |

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
