# Identity and Access — Technical Design

| | |
| --- | --- |
| **Status** | Draft for review |
| **Date** | 2026-10-07 |
| **Implements** | [BRD](../../BRD.md): SEC-1 to SEC-10, SEC-19, SYS-1, API-3, API-5 (pagination convention), NFR-6, NFR-9 |
| **Builds on** | [Backend foundation plan](../plans/2026-10-07-phase1-01-backend-foundation.md) |
| **Series** | Plan 2 of 11 for Phase 1 |

## 1. Purpose

Give MegooArti its security core: who a request comes from, what that identity may do, and the administration API for managing both. Every later plan (repositories, formats, browse, UI) calls into this one to authorise its routes.

Success means:

- An administrator can sign in with the generated first-start password, is made to change it, and can then manage users, roles and settings through the REST API.
- A developer can create a personal API token and use it, in place of a password, with HTTP Basic or as a bearer token.
- Any route can declare the permission it needs in one line, and the same check works for a session, a password, a token and anonymous access.

## 2. Scope

**In scope (backend only):** users, roles, permission patterns, UI sessions with CSRF protection, personal API tokens, anonymous access, first-start administrator, failed-sign-in rate limiting, a settings store with base URL and anonymous-access settings, a pagination convention for list endpoints, and per-test database isolation.

**Out of scope:**

| Item | Where it goes |
| --- | --- |
| LDAP, OIDC, default role, authentication-source ordering | Phase 2 |
| Content selectors | Phase 2 |
| Audit log (this plan only emits log events) | Phase 2 |
| Sign-in and administration screens | Plans 9 and 10 |
| Format-specific logins (`npm login`, `docker login`, NuGet API key) | Plans 4–7, using the token check defined here |
| Enforcing `repository:…` permissions on content | Plan 3 onward; the patterns are defined here |
| Encrypting stored secrets (NFR-7) | Plan 3, which stores the first reversible secret |
| Authentication on `/api/docs` and the OpenAPI document | Left open: they describe the API's shape, not its data |

## 3. Decisions

| # | Decision | Reason |
| --- | --- | --- |
| D1 | Roles hold **permission patterns** directly; there is no table of named privilege objects. | Expresses everything SEC-3 and SEC-4 need with one table and nothing to regenerate when repositories change. |
| D2 | UI sign-in uses **server-side sessions** in PostgreSQL behind an opaque cookie. | Disabling a user or signing out takes effect at once and works across several containers. |
| D3 | Anonymous access always acts as the built-in `anonymous` user. | "Configuring" anonymous access (SEC-6) is done by editing that user's roles; a selectable anonymous user adds a setting without adding a capability. |
| D4 | An API token cannot create tokens or change a password. | Limits what a leaked token can do. |
| D5 | Built-in roles and users are created by the migration; only the administrator's initial password is set at start-up. | Static data is deterministic and versioned; the password must be random per installation. |
| D6 | In tests, each test runs inside one database transaction that is rolled back. | Fast, order-independent, and needs no production code beyond always using `app.state.sessionmaker`. |

## 4. Permission model

### 4.1 Patterns

A **permission** is what a route requires, for example `admin:users:write`. A **pattern** is what a role grants, for example `admin:users:*`.

- Both are colon-separated segments. A segment is `*` (patterns only) or matches `[A-Za-z0-9_.-]+`. Matching is case-sensitive.
- A pattern grants a permission when each of its segments is `*` or equals the permission's segment at the same position, and the pattern is **not longer** than the permission.
- A pattern shorter than the permission grants everything beneath it. So `*` grants everything, `admin` grants every administrative permission, and `repository:maven` grants every action on every Maven repository.

| Pattern | Permission | Granted |
| --- | --- | --- |
| `*` | `admin:users:write` | yes |
| `admin:users:*` | `admin:users:write` | yes |
| `admin:users:read` | `admin:users:write` | no |
| `repository:*:*:read` | `repository:maven:releases:read` | yes |
| `repository:maven` | `repository:maven:releases:delete` | yes |
| `repository:maven:releases:read:extra` | `repository:maven:releases:read` | no (pattern is longer) |

Patterns are validated for syntax only. Unknown areas are accepted so that later plans can add areas without a migration.

### 4.2 Permissions defined by this plan

| Permission | Guards |
| --- | --- |
| `admin:users:read`, `admin:users:write` | Listing and viewing users; creating, editing, disabling, deleting, resetting passwords |
| `admin:roles:read`, `admin:roles:write` | Viewing roles; creating, editing, deleting |
| `admin:tokens:read`, `admin:tokens:write` | Listing and revoking other users' API tokens |
| `admin:settings:read`, `admin:settings:write` | Viewing and changing instance settings |
| `repository:<format>:<name>:<action>` | Reserved for plan 3 onward. Actions: `browse`, `read`, `add`, `edit`, `delete` |

`write` does not imply `read`; grant `admin:users:*` for both.

Changing one's own password and managing one's own tokens need no permission, only a signed-in, non-anonymous user (see D4 for the token restriction).

### 4.3 Effective permissions

A user's effective patterns are the union of the patterns of every role assigned to the user and of every role those roles contain, transitively. An API token may carry its own list of patterns (**scopes**); a request made with that token is allowed only if both the owner's patterns and the token's scopes grant the permission. A token with no scopes has the owner's full permissions.

## 5. Data model

All primary keys are UUIDs generated by the application unless stated. All timestamps are `timestamptz`.

| Table | Columns | Notes |
| --- | --- | --- |
| `users` | `id`, `username` (unique, stored lower-case, `[a-z0-9._@-]{1,64}`), `display_name` (≤128), `email` (nullable, ≤254), `password_hash` (nullable), `status` (`active` / `disabled`), `must_change_password`, `builtin`, `created_at`, `updated_at`, `last_login_at` | A user with no password hash cannot sign in with a password |
| `roles` | `id`, `name` (unique, `[A-Za-z0-9_.-]{1,64}`), `description` (≤255), `builtin` | |
| `role_permissions` | `role_id`, `pattern`; primary key on both | |
| `role_members` | `role_id`, `member_role_id`; primary key on both | "role contains member role". A change that creates a cycle is rejected |
| `user_roles` | `user_id`, `role_id`; primary key on both | |
| `sessions` | `id`, `token_hash` (unique), `csrf_token`, `user_id`, `created_at`, `last_seen_at`, `expires_at`, `ip`, `user_agent` (≤255) | `expires_at` is the absolute limit |
| `api_tokens` | `id`, `user_id`, `name` (≤100, unique per user), `token_hash` (unique), `display_prefix`, `scopes` (JSONB list, nullable), `expires_at` (nullable), `created_at`, `last_used_at` | Revoking deletes the row |
| `login_failures` | `subject` (primary key), `window_started_at`, `count` | `subject` is `user:<username>` or `ip:<address>` |

Deleting a user deletes its role assignments, sessions and tokens. Deleting a role deletes its patterns, memberships and assignments.

**Built-in rows, inserted by the migration:**

| Kind | Name | Content |
| --- | --- | --- |
| Role | `admin` | Pattern `*` |
| Role | `anonymous` | Patterns `repository:*:*:browse`, `repository:*:*:read` |
| User | `admin` | Role `admin`; no password; `must_change_password` true |
| User | `anonymous` | Role `anonymous`; no password |

Built-in roles cannot be deleted, and the `admin` role cannot be edited. Built-in users cannot be deleted. The `anonymous` user can never be given a password; its role assignments can be edited.

Settings use the existing `system_settings` table: key `base_url` (string or null, default null) and key `anonymous_access` (`{"enabled": bool}`, default disabled).

## 6. Authentication

### 6.1 Resolving a request

Each request resolves to a **principal**: the user, the effective patterns, any token scopes, and the method (`session`, `password`, `token` or `anonymous`). The order is:

1. **`Authorization` header present.** `Bearer <token>` is an API token. `Basic <user>:<secret>` is an API token if the secret starts with `mga_` (and it must belong to that user), otherwise a password. Invalid credentials are a `401`; the request never falls through to anonymous. A session cookie on the same request is ignored.
2. **Session cookie present and valid.** The principal is the session's user.
3. **Otherwise**, the built-in `anonymous` user if anonymous access is enabled, or no principal.

A route that needs a permission returns `401` when there is no principal or the principal is anonymous and lacks it, and `403` when an identified principal lacks it. A `401` from `/api/v1` carries `WWW-Authenticate: Bearer realm="MegooArti"`, which does not trigger the browser's own sign-in dialog. Repository routes in later plans set the challenge their clients expect.

A disabled user cannot authenticate by any method.

### 6.2 Passwords

- Hashed with Argon2id (library defaults). On a successful sign-in the hash is upgraded if the parameters have changed.
- Minimum 8 characters, maximum 256, and not equal to the username.
- Verification runs off the event loop. When the username is unknown, a dummy hash is verified so that timing does not reveal which usernames exist.
- Every sign-in failure returns the same message, whatever the cause: unknown user, wrong password, disabled user.

### 6.3 Sessions

- `POST /auth/login` creates a session and sets cookie `megooarti_session`: 32 random bytes, URL-safe encoded; `HttpOnly`; `SameSite=Lax`; `Path=/`; `Secure` unless `MEGOOARTI_SESSION_COOKIE_SECURE=false`. Only the SHA-256 hash is stored.
- A session is valid while it is within the idle limit since `last_seen_at` (default 60 minutes) and before `expires_at` (default 12 hours after creation). `last_seen_at` is written at most once a minute.
- Expired sessions are deleted when anyone signs in.
- Disabling or deleting a user, and resetting a user's password, deletes that user's sessions. Changing one's own password deletes one's other sessions.

### 6.4 CSRF

Each session has a random CSRF token, returned by `POST /auth/login` and `GET /auth/session`. A request authenticated by the session cookie that uses `POST`, `PUT`, `PATCH` or `DELETE` must send it in `X-CSRF-Token`; otherwise the response is `403` with code `csrf_failed`. Requests authenticated by `Authorization` header are exempt, as is `POST /auth/login`.

### 6.5 Forced password change

While `must_change_password` is true, a principal authenticated by session or password may call only `GET /auth/session`, `POST /auth/logout` and `PUT /me/password`. Anything else returns `403` with code `password_change_required`. API tokens are not affected, so automation keeps working after an administrator resets a password.

### 6.6 API tokens

- Format: `mga_` followed by 32 random bytes, URL-safe encoded (47 characters in total). The value is returned once, by the request that creates it. Only its SHA-256 hash is stored, plus the first 8 characters for display.
- Optional `expires_at` and optional `scopes` (section 4.3).
- `last_used_at` is written at most once a minute.
- Creating, listing and revoking one's own tokens requires method `session` or `password`. A token-authenticated request gets `403` with code `interactive_auth_required` (D4). The same applies to changing one's own password.

### 6.7 Rate limiting failed sign-ins

- Every failed authentication (sign-in endpoint, Basic, bearer) increments `ip:<client address>`. A failed **password** attempt also increments `user:<username>`. Token attempts never touch or consult the `user:` counter, so a locked-out username does not stop that user's automation.
- A counter covers a fixed window that starts at its first failure. Defaults: 5 failures in 900 seconds.
- Before credentials are checked, if either applicable counter has reached the limit and its window has not ended, the response is `429` with code `too_many_attempts` and a `Retry-After` header giving the seconds left.
- A successful authentication clears the counters it was checked against, so occasional mistakes by legitimate users of one address do not add up to a block.
- Failure counts are committed even though the request fails.

### 6.8 First start

At application start-up, if the schema is at head and the `admin` user has no password hash:

1. Lock the row, generate a random password, store its hash.
2. Write the password to `<MEGOOARTI_DATA_DIR>/admin.password` (owner-readable only).
3. Log one `initial_admin_password` line containing the password and the file path.

The row lock ensures only one container does this. When the `admin` user's password is next changed, the file is deleted if present. If the schema is not at head, this step is skipped with a warning; readiness already reports the problem.

## 7. REST API

All routes are under `/api/v1`, use JSON, and return errors in the standard envelope. `interactive` means method `session` or `password`.

### 7.1 Pagination convention

List endpoints accept `limit` (default 50, 1–200) and `offset` (default 0), and return:

```json
{ "items": [], "total": 0, "limit": 50, "offset": 0 }
```

Every later plan uses the same shape.

### 7.2 Endpoints

| Method and path | Needs | Result |
| --- | --- | --- |
| `POST /auth/login` | none | `200` with `user`, `csrf_token`, `must_change_password`; sets the cookie |
| `POST /auth/logout` | session | `204`; deletes the session and clears the cookie |
| `GET /auth/session` | none | `200` with `authenticated`, `method`, `user`, `permissions`, `must_change_password`, and `csrf_token` for a session. Never `401`; the UI starts from this call |
| `PUT /me/password` | interactive | `204`. Body: `current_password`, `new_password` |
| `GET /me/tokens` | interactive | Page of the caller's tokens (never the secret) |
| `POST /me/tokens` | interactive | `201` with the token metadata and the secret `token`. Body: `name`, optional `expires_at`, optional `scopes` |
| `DELETE /me/tokens/{token_id}` | interactive | `204` |
| `GET /users` | `admin:users:read` | Page of users |
| `POST /users` | `admin:users:write` | `201`. Body: `username`, `display_name`, optional `email`, `password`, `roles` (names), `must_change_password` (default true) |
| `GET /users/{user_id}` | `admin:users:read` | The user with role names |
| `PATCH /users/{user_id}` | `admin:users:write` | Updates any of `display_name`, `email`, `status`, `roles` |
| `DELETE /users/{user_id}` | `admin:users:write` | `204` |
| `PUT /users/{user_id}/password` | `admin:users:write` | `204`. Body: `password`, `must_change_password` (default true) |
| `GET /users/{user_id}/tokens` | `admin:tokens:read` | Page of that user's tokens |
| `DELETE /users/{user_id}/tokens/{token_id}` | `admin:tokens:write` | `204` |
| `GET /roles` | `admin:roles:read` | Page of roles |
| `POST /roles` | `admin:roles:write` | `201`. Body: `name`, `description`, `permissions` (patterns), `roles` (contained role names) |
| `GET /roles/{name}` | `admin:roles:read` | The role |
| `PUT /roles/{name}` | `admin:roles:write` | Replaces `description`, `permissions`, `roles` |
| `DELETE /roles/{name}` | `admin:roles:write` | `204` |
| `GET /settings` | `admin:settings:read` | `base_url` and `anonymous_access` |
| `PUT /settings/base-url` | `admin:settings:write` | Body: `base_url` (an `http` or `https` URL, stored without a trailing slash, or null) |
| `PUT /settings/anonymous-access` | `admin:settings:write` | Body: `enabled` |

Users are addressed by ID, roles by name. A role's name cannot be changed.

### 7.3 Error codes added

| Status | Code | When |
| --- | --- | --- |
| 401 | `unauthorized` | No valid credentials where they are required; failed sign-in |
| 403 | `forbidden` | An identified principal lacks the permission |
| 403 | `csrf_failed` | Missing or wrong `X-CSRF-Token` |
| 403 | `password_change_required` | Section 6.5 |
| 403 | `interactive_auth_required` | Section 6.6 |
| 409 | `conflict` | Duplicate username, role name, or token name |
| 409 | `builtin_protected` | Deleting a built-in user or role; editing the `admin` role; giving `anonymous` a password |
| 409 | `role_cycle` | A role would contain itself, directly or indirectly |
| 409 | `last_administrator` | Section 7.4 |
| 409 | `self_protected` | Disabling or deleting one's own account |
| 429 | `too_many_attempts` | Section 6.7 |

`ApiError` gains an optional `headers` argument for `WWW-Authenticate` and `Retry-After`.

### 7.4 Keeping an administrator

After any change to users, role assignments or roles, there must still be at least one active user with a password whose effective patterns include `*`. A change that would break this is rolled back with `409` and code `last_administrator`.

## 8. Code structure

New and changed modules under `backend/src/megooarti/`:

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `db/session.py` | Session factory on `app.state.sessionmaker`; `get_session` dependency giving one transaction per request (commit on success, roll back on error) | engine |
| `security/models.py` | ORM models for the tables in section 5 | `db.base` |
| `security/permissions.py` | Validate patterns; decide whether patterns grant a permission. Pure functions | nothing |
| `security/passwords.py` | Hash, verify, detect a needed rehash; password rules | argon2 |
| `security/tokens.py` | Generate and hash secrets; create, find, list, revoke API tokens | models |
| `security/sessions.py` | Create, find, touch, delete UI sessions | models |
| `security/throttle.py` | Record, check and clear failed sign-ins | models |
| `security/roles.py` | Role CRUD, cycle check, effective patterns of a set of roles | models, permissions |
| `security/users.py` | User CRUD, password changes, the keep-an-administrator check | models, roles, passwords |
| `security/authentication.py` | `Principal`; resolve a request to a principal; dependencies `current_principal`, `require(permission)`, `require_interactive()`; CSRF and forced-password-change checks | tokens, sessions, throttle, users |
| `security/bootstrap.py` | First-start administrator password | users, passwords |
| `security/api/auth.py`, `me.py`, `users.py`, `roles.py` | Routers for section 7.2 | services above |
| `system/settings_store.py` | Read and write `system_settings` values | system models |
| `system/settings_api.py` | Settings router | settings store |
| `pagination.py` | `limit`/`offset` parameters and the page response model | nothing |

Services are plain async functions that take an `AsyncSession`. Routers only validate input, call a service, and shape the response.

**Transaction rule:** code that must record something although the request fails (a failed sign-in count) commits explicitly before raising.

A route declares its requirement like this:

```python
@router.get("/users")
async def list_users(principal: Principal = Depends(require("admin:users:read"))): ...
```

## 9. Configuration added

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEGOOARTI_DATA_DIR` | `/var/lib/megooarti` | Directory for files MegooArti writes; holds `admin.password`. The image creates it for the non-root user and Compose mounts a volume there |
| `MEGOOARTI_SESSION_IDLE_SECONDS` | `3600` | Idle limit for UI sessions |
| `MEGOOARTI_SESSION_ABSOLUTE_SECONDS` | `43200` | Absolute limit for UI sessions |
| `MEGOOARTI_SESSION_COOKIE_SECURE` | `true` | Set `false` only for plain-HTTP deployments |
| `MEGOOARTI_LOGIN_MAX_FAILURES` | `5` | Failures allowed per window |
| `MEGOOARTI_LOGIN_FAILURE_WINDOW_SECONDS` | `900` | Length of the failure window |

## 10. Logging

Structured log events, each with the acting user where there is one: `login_succeeded`, `login_failed` (with the reason, never the password), `login_throttled`, `logout`, `password_changed`, `user_created`, `user_updated`, `user_deleted`, `role_created`, `role_updated`, `role_deleted`, `token_created`, `token_revoked`, `setting_changed`, `initial_admin_password`. Passwords and token values never appear in logs, except the one `initial_admin_password` line that SEC-2 requires.

## 11. Testing

- **Isolation (D6):** each test gets one connection with an open transaction; `app.state.sessionmaker` is bound to it in savepoint mode; the transaction is rolled back afterwards. This is the first task of the plan.
- **Speed:** tests use low-cost Argon2 parameters through a fixture.
- **Permission matching:** table-driven unit tests, including every row of the table in 4.1.
- **Services:** tested against the real database.
- **API:** tested through the in-process client, covering each row of 7.2 and each code in 7.3.
- **Security behaviours with dedicated tests:** identical failure message for unknown user and wrong password; disabled user rejected by every method; token of user A rejected under username B; CSRF required for cookie requests and not for header requests; forced password change; token cannot mint tokens; session ends when the user is disabled; expiry of sessions and tokens; throttling and its reset; keep-an-administrator; role cycles.

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| Username-based throttling lets an attacker lock a known account out for 15 minutes. | Accepted for Phase 1: the window is short, API tokens of that user are throttled only by address, and both limits are configurable. |
| The initial password is written to the log. | Required by SEC-2; it must be changed at first sign-in, after which it is useless. |
| A per-request session lookup adds a query to every UI request. | One indexed lookup; `last_seen_at` writes are limited to once a minute. |
| Savepoint-based test isolation can hide bugs that only appear across real transactions. | The container tests run against real transactions, and this plan adds one that signs in with the generated administrator password and changes it. |

## 13. Requirement coverage

| Requirement | Covered by |
| --- | --- |
| SEC-1 users | 5, 7.2 users endpoints |
| SEC-2 first-start admin | 6.8, 6.5 |
| SEC-3 privileges, roles, nested roles | 4, 5 |
| SEC-4 privilege types | 4.2 |
| SEC-5 built-in roles | 5 |
| SEC-6 anonymous access | 6.1, settings endpoints, D3 |
| SEC-7 create, list, revoke tokens; shown once | 6.6, 7.2 |
| SEC-8 token expiry and restriction | 4.3, 6.6 |
| SEC-9 token wherever a password is accepted | 6.1 (Basic and bearer; format logins in plans 4–7) |
| SEC-10 admin lists and revokes tokens | 7.2 |
| SEC-19 rate limiting | 6.7 |
| SYS-1 base URL | settings endpoints |
| API-3 session, Basic, bearer | 6.1 |
| API-5 pagination | 7.1 |
| NFR-6 Argon2id; tokens hashed | 6.2, 6.6 |
| NFR-9 CSRF; cookie flags | 6.3, 6.4 |
