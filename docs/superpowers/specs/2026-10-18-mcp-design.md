# MCP: design

**Date:** 2026-10-18
**Plans:** 14a (the endpoint and the read tools), 14b (the ops and admin tools), 14c (OAuth sign-in)
**BRD:** API-7 (added by this spec), SEC-8, SEC-9, CMP-5, CMP-9

## 1. Goal

AI agents work with MegooArti through the Model Context Protocol (MCP), as people work with it through the web UI and programs through the REST API. A coding agent in a developer's editor (Claude Code, Cursor, VS Code, Codex, claude.ai) finds which versions of a package the registry has, where they come from, and how to set a project up to use them; an ops agent looks after the registry: makes and changes repositories, clears a proxy's cache, deletes content, and administers users and roles. Each does only what the person who connected it may do, and less where that person says so.

## 2. Scope

**In scope:**

- An MCP endpoint at `/mcp`, served by the backend (D1), over Streamable HTTP.
- Sign-in with the API tokens there are (`mga_…`), and with OAuth 2.1 as MCP's authorization spec has it (D3).
- Read tools for packages, repositories, the caller and the system (6.1); tools for ops and administration (6.2).
- Connected apps: the OAuth approvals a user has given, shown and revoked in the web UI.
- A guide, `docs/mcp.md`.

**Out of scope:**

| What | Why |
| --- | --- |
| Making API tokens, and changing one's own password, through MCP | The identity-access spec's D4: nothing signed in with a token does either. An agent cannot give itself credentials. |
| Server settings (anonymous access, the base URL) through MCP | One wrong call opens the whole registry to anyone, or breaks every client's addresses. The web UI and the REST API keep them. |
| Uploading and publishing through MCP | Agents publish better with the native tools (`npm publish`, `dotnet nuget push`, `docker push`) and a token; a tool would carry whole packages through the model's context. |
| Blob stores: making and deleting them | Rare, and the storage spec's own checks need a person. Their usage is read (`system_status`). |
| MCP resources and prompts | Clients show them unevenly; every need of section 1 is a tool. |
| Client ID metadata documents (MCP's newer alternative to registration) | They mean fetching an address the client names, with its own risk of reaching other hosts. Registration (RFC 7591) is what the clients of 9.3 use. A later plan, if wanted. |
| Anonymous use of `/mcp` | An agent is always someone's: whoever connected it answers for what it does. |
| An audit log | EVT-5, its own plan. Each tool call is logged (8.4), for it to build on. |

## 3. Decisions

The product owner's:

| # | Decision | Choice |
| --- | --- | --- |
| D1 | Where the server runs | In the backend, mounted at `/mcp`: tools call the services the REST API calls, through the same `authorize()`. |
| D2 | Whose agents | Developers' coding agents and ops agents, from the start. |
| D3 | Sign-in | API tokens, and OAuth sign-in with a consent page. |
| D4 | What ops agents may do | Beyond the safe set (make and change repositories, a group's members, online and offline, invalidate a proxy's cache, rebuild a search index, read status): delete content, delete repositories, and administer users and roles. Each is gated by its permission, as in the REST API. |
| D5 | Shape of the tools | Eight read tools and seventeen ops and admin tools, each made for a task, not one for each REST endpoint. |
| D6 | Shape of the work | One spec, a plan for each part (section 12). |

Settled here, by the designer:

| # | What | Why |
| --- | --- | --- |
| E1 | `tools/list` shows a caller only the tools its permissions and its token's scopes could use. | A read-only token never sees the admin tools: its agent's context stays small, and it is not tempted. |
| E2 | Tools name things as people do (a repository's name, a package's format, name and version), and take a component's id only where they were given one. | An agent reasons from names; ids are what a search gives back. |
| E3 | Every tool is annotated: `readOnlyHint` for the read tools, `destructiveHint` for deletes and revocations, `idempotentHint` where a call repeated changes nothing more. | Clients ask the person before a destructive call. |
| E4 | Text written by third parties (a package's description, its authors, a README, a proxy's last error from its remote) is in fields named `…_untrusted`, never in a tool's summary text, and the server's `instructions` say so. | A public package can carry words meant for an agent (prompt injection). |
| E5 | A list gives at most 50 items unless asked for up to 200, with a cursor to the next; a result is at most 64 KiB of text, cut where it is longer, and says so. | An agent's context is small, and is read again on each turn. |
| E6 | An OAuth access token is accepted at `/mcp` only: not by the REST API, nor by any package client. | It was issued for `/mcp` (RFC 8707); a token that leaks from an agent's config reaches no more than the agent did. |

## 4. The endpoint

- `/mcp`, behind the gateway as the API is, served by the MCP Python SDK's `MCPServer` in stateless Streamable HTTP: no session is kept between requests, so any backend process answers any request.
- The server's `instructions` say what MegooArti is, what each group of tools is for, and E4.
- A request without a bearer token, or with one that is not valid, gets `401` with `WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource/mcp"` (7.1). Basic and session cookies are not accepted at `/mcp`.
- Module layout: `megooarti/mcp/` with `server.py` (the server, its mount, its instructions), `verifier.py` (5), `packages.py`, `repositories.py`, `administration.py` (the tools), `results.py` (paging, the cap, untrusted fields, errors). OAuth is `megooarti/security/oauth/` (7).

## 5. Sign-in

- The token verifier turns a bearer token into the `Principal` the REST API uses:
  - `mga_…`: an API token, as `authentication.py` reads one (its owner, its scopes, its expiry);
  - `mgo_…`: an OAuth access token (7.4), whose scopes are its approval's.
- The principal's permissions are its owner's, narrowed by its scopes, read again on each request: a user disabled, a role taken away, a token revoked or an approval revoked takes effect at the next request.
- `require_interactive` holds: a principal from either kind of token cannot make tokens or change a password, so no tool does.
- A user who must change their password may still use a token, as with the REST API.

## 6. Tools

Each tool authorizes as the REST route it stands beside does, and lists only what the caller may read (CMP-9).

### 6.1 Read tools (plan 14a)

| Tool | Arguments | What it gives |
| --- | --- | --- |
| `search_packages` | `words`, `format`, `repository`, `namespace`, `name`, `version`, `checksum`, `limit`, `cursor` | Components as `/search` finds them: repository, format, namespace, name, version, and their id. |
| `package_versions` | `format`, `name`, `namespace`, `repository` (optional) | Every version of one package in the repositories the caller may read, newest first by the format's own ordering; for each, the repositories that have it and whether each is hosted or a proxy's cache; and the newest release (not a prerelease or snapshot). |
| `package_details` | `component_id`, or `repository`, `namespace`, `name`, `version` | A version's files with their sizes, checksums and download addresses; its usage (the line for `pom.xml`, `package.json`, `requirements.txt`, a `.csproj`, a `Dockerfile`, as the web UI shows it); and `description_untrusted`. |
| `browse` | `repository`, `path`, `limit`, `cursor` | The folders and files at a path. |
| `list_repositories` | `format`, `type` | Each repository's name, format, type, address and online state; a proxy's remote and whether it is blocked. |
| `repository_details` | `name` | Its settings (no secret), a group's members in order, a proxy's state and `last_error_untrusted`, and its setup snippets: how npm, pip, Maven, Gradle, NuGet, Docker, APT, YUM and apk are set up to use it, as the web UI shows them. |
| `whoami` | — | The user, their roles, their permissions; the token's kind, scopes and expiry. |
| `system_status` | — | The version, health and readiness; each blob store's usage, to those who may read blob stores. |

### 6.2 Ops and admin tools (plan 14b)

| Tool | Permission | Hint |
| --- | --- | --- |
| `create_repository` | `admin:repositories:write` | write |
| `update_repository` (settings, a group's members, online) | `admin:repositories:write` | idempotent |
| `delete_repository` | `admin:repositories:write` | destructive |
| `invalidate_proxy_cache` | `admin:repositories:write` | idempotent |
| `rebuild_search_index` | `admin:repositories:write` | idempotent |
| `delete_component` | `repository:<format>:<name>:delete` | destructive |
| `delete_path` (a file, or a folder and all beneath it) | `repository:<format>:<name>:delete` | destructive |
| `list_users`, `user_details` | `admin:users:read` | read-only |
| `create_user`, `update_user` (roles, status, email, name) | `admin:users:write` | write, idempotent |
| `delete_user` | `admin:users:write` | destructive |
| `revoke_token` (a token, or an OAuth approval) | `admin:tokens:write` | destructive |
| `list_roles` | `admin:roles:read` | read-only |
| `create_role`, `update_role` (permissions, nested roles) | `admin:roles:write` | write, idempotent |
| `delete_role` | `admin:roles:write` | destructive |

- `user_details` gives a user's roles, their tokens (name, prefix, scopes, expiry, last used: never a value) and their OAuth approvals.
- `create_user` takes a password only as one the user must change at their first sign-in; no tool sets another password.
- `create_repository` gives a new proxy its format's public remote where none is given. The table of public remotes moves from the web form to the backend (`GET /api/v1/formats`, each format with its public remotes: not under `/repositories`, where it would be a repository's name), so that the form and the agent give the same ones.
- A tool refuses what its REST route refuses: the built-in roles and the `admin` and `anonymous` users stay as the identity-access spec has them.

## 7. OAuth (plan 14c)

MegooArti is both the authorization server and the protected resource, as MCP's authorization spec allows.

### 7.1 Discovery

- `/.well-known/oauth-protected-resource/mcp` (RFC 9728): the resource (`<base>/mcp`), its authorization server (`<base>`), the scopes it knows (7.3).
- `/.well-known/oauth-authorization-server` (RFC 8414): the issuer, the endpoints of 7.2 to 7.4, `code_challenge_methods_supported: ["S256"]`, `grant_types_supported: ["authorization_code", "refresh_token"]`, `token_endpoint_auth_methods_supported: ["none"]`.
- `<base>` is the base URL the system settings hold; without one, the server refuses OAuth with a message that says to set it.

### 7.2 Registration

- `POST /oauth/register` (RFC 7591), open, as MCP expects: a client name, redirect addresses (`https`, or `http` to a loopback address), no secret (a public client).
- At most 20 registrations an hour from one address, and a body of at most 16 KiB. A client that no approval names is deleted 30 days after it registered.

### 7.3 Authorization and consent

- `GET /oauth/authorize`: `response_type=code`, PKCE with S256 (required), a redirect address the client registered (matched exactly), `state`, and `resource` naming `<base>/mcp` (required).
- The person signs in to the web UI as they do (session, CSRF), and sees a consent page: the client's name (marked as the client's own words), its redirect host, and two choices:
  - **What it may do:** "Read what I can read" (scopes `repository:*:*:browse`, `repository:*:*:read`, `admin:*:read`) or "Everything I can do" (no scope: all the owner's permissions). Either way, never more than the owner may.
  - **For how long:** 1 day, 30 days, 90 days, or until revoked.
- Approving gives a code good for 60 seconds and once; refusing sends `error=access_denied` to the client.

### 7.4 Tokens

- `POST /oauth/token`: the `authorization_code` grant (with `code_verifier`, the same `redirect_uri` and `resource`), and the `refresh_token` grant.
- Access tokens are `mgo_` and 32 random bytes, good for 1 hour; refresh tokens are `mgf_` and 32 random bytes, good until the approval expires. A refresh token is used once: each use gives a new one, and a refresh token used a second time revokes the whole approval (reuse means it was stolen).
- Each is stored as its SHA-256 and a display prefix, as API tokens are.

### 7.5 What is stored

- `OAuthClient`: id, name, redirect addresses, registered at, from which address.
- `OAuthGrant` (an approval): user, client, scopes, expires at, created at, last used at.
- `OAuthToken`: grant, kind (access or refresh), hash, expires at, used at.
- Revoking an approval deletes it and its tokens; deleting a user deletes theirs.

### 7.6 Connected apps

- Account → Connected apps lists the caller's approvals: the client, what it may do, when it was approved and last used, when it expires, and a Revoke button.
- An administrator sees and revokes a user's approvals beside their tokens (`admin:tokens:read`, `admin:tokens:write`).
- REST: `GET /api/v1/me/connected-apps`, `DELETE /api/v1/me/connected-apps/{id}`, and `/api/v1/users/{id}/connected-apps` for administrators. They need an interactive session, as the token routes do.

## 8. Errors, limits and safety

### 8.1 Errors

- A tool that is refused or fails answers with an MCP tool error (`isError: true`) whose text is the REST error's code and message (`forbidden: …`, `not_found: …`, `validation_error: …` with each field's message). The agent reads it and can try otherwise.
- Protocol errors (a tool that does not exist, arguments that are not the tool's schema) are the SDK's own.

### 8.2 Limits

- E5's paging and cap.
- Failed sign-ins at `/mcp` count towards the throttle there is (5 failures per 900 s, per address and per user name).
- The registration limits of 7.2.

### 8.3 Untrusted text

- E4. The consent page shows the client's name as the client's own words, and its redirect host beside it.

### 8.4 Logging

- Each tool call is logged with structlog: the user, the token's prefix or the approval's id, the tool, its arguments (none of them secret), the outcome (its error code, or `ok`) and how long it took.

## 9. Testing

### 9.1 Unit tests

- Each tool through the SDK's in-memory client: what it gives; a caller refused, and allowed; `tools/list` for a read-only token, an admin token, an OAuth approval of each kind; paging and the cap; the hints; untrusted fields.
- A tool and its REST route answer alike for the same caller (a table of pairs).
- The verifier: each kind of token; expired, revoked, a user disabled, a role taken away; an OAuth token refused by the REST API and by a package client (E6).

### 9.2 OAuth tests

- Discovery documents; registration and its limits; `authorize` refusing a missing or plain PKCE, a redirect not registered, a `resource` that is not `/mcp`; a code used twice; the token grant; refresh rotation, and a refresh token used twice revoking the approval; an approval expiring; Connected apps and revoking.
- The consent page in a real browser (the browser test of the web UI).

### 9.3 Real clients

- A docker test drives the stack with the official MCP client SDK: it connects with a token, lists the tools, searches, reads a repository's setup snippets; and goes through OAuth (registration, the consent page in the browser, tokens, a tool call, a refresh).
- The guide says how Claude Code, Cursor, VS Code and claude.ai connect; the plans check each by hand once, and record what they saw.

## 10. Documentation

- `docs/mcp.md`: what MCP gives an agent; how to connect each client of 9.3, with a token and with OAuth; the tools and their permissions; the trust model (E1, E4, E6, D4 of the identity-access spec); revoking.
- `docs/api.md` and `docs/administration.md`: Connected apps, and the defaults route.

## 11. Risks

| Risk | What settles it |
| --- | --- |
| MCP's spec and its Python SDK change quickly. | The SDK is pinned; the tests go through the official client SDK, so that a change in either shows. |
| An agent is led by text in a package to call a destructive tool. | E3 makes clients ask the person; E4 keeps that text out of the summaries; a read-only approval or token never sees the tool (E1). |
| An agent's token leaks from its config. | A token's scopes and expiry, an approval's choice of what it may do and for how long; an OAuth token works at `/mcp` only (E6). |
| Open registration is abused. | 7.2's limits, and clients that no approval names are deleted. |
| An agent reads too much and fills its context. | E5. |
| Tools and REST routes drift apart. | Tools call the routes' services, through the same `authorize()`; 9.1's table of pairs. |

## 12. Plans

| Plan | What it builds |
| --- | --- |
| 14a | The endpoint (4), the verifier for API tokens (5), the read tools (6.1), E1 to E5, the logging (8.4), the guide's first part. |
| 14b | The ops and admin tools (6.2), the public remotes moved to the backend, the guide's tools. |
| 14c | OAuth (7): discovery, registration, authorization with the consent page, tokens, Connected apps; the browser and docker tests; the guide's OAuth part. |

Each plan ends with something an agent uses: 14a with a token and the read tools, 14b with the ops tools, 14c with OAuth sign-in from claude.ai.

### Settled while building plan 14a

| # | What | Why |
| --- | --- | --- |
| M1 | Each request to `/mcp` is served by a session manager of its own, made for it and stopped with it (stateless, answers in JSON). | Nothing is kept between requests (4), so nothing need outlive one: no start in the application's lifespan, and tests reach the endpoint as clients do. |
| M2 | The token is checked by `agent_principal` in `security/authentication.py`, a dependency of the `/mcp` route among `AUTHENTICATION_DEPENDENCIES` (in place of 4's `verifier.py`): `Bearer mga_…` only, else `401` with `WWW-Authenticate: Bearer`. | One place decides who calls, with the failed-sign-in throttle the REST API has (8.2); the route guard test sees the route as guarded. Plan 14c adds OAuth tokens there. |
| M3 | The SDK's check of the `Host` header against DNS rebinding is off at `/mcp`. | Every request needs a bearer token, which a browser never sends by itself; the check would refuse every name the server is reached by. |
| M4 | A tool calls the REST route functions themselves (`search_components`, `get_component`, `list_folder`, `get_repository`, …) with the caller's principal. | Their checks, their filtering of what the caller may browse, and their answers are the tools' (9.1's pairs: search and setup are tested against REST). |
| M5 | A refusal reads `Error executing tool <name>: <code>: <message>`, a field's message on a line of its own; any other failure `internal_error: Something went wrong. It has been logged.`, the error logged and not said. | The SDK names the tool first (8.1). An unexpected error's text may hold what the agent should not see. |
| M6 | MegooArti keeps no description of a package: `package_details` gives none (in place of 6.1's `description_untrusted`). The untrusted field of 14a is a proxy's `last_error_untrusted`. | Nothing records one to give; a format that records one can add it, marked so. |
| M7 | `package_versions` orders versions as each format's clients do: `Format.ordered_versions` and `Format.is_prerelease` (numbers read as numbers by default; SemVer for npm, NuGet's, Maven's, PEP 440 for PyPI, dpkg's, rpm's, apk's). Docker's tags have no order, and are listed from the one pushed or fetched last. It reads at most 2,000 copies of a package, and asks for a namespace where several have the name. | An agent asked for the newest version must not be given 1.9 before 1.10, nor a prerelease as the newest release. |
| M8 | A repository's settings and a proxy's state (`repository_details`; `list_repositories`' `remote`) need `admin:repositories:read`, as the route that gives them does. Anyone who may browse a repository gets its address, a group's members they may browse, and its setup. | Each tool authorizes as its REST route (6). |
| M9 | `package_details` takes the repository always, with `component_id`, or with `name` and `version` (and `namespace`). It describes 50 files at most. | The REST API finds a component in its repository; a version's files are a few, but a format may keep many. |
| M10 | Each call's log names the token by its id. | The principal holds the token's id; its prefix is a second lookup for every call. |
| M11 | The 64 KiB of E5 are of a result's text as the SDK writes it, indented (the agent reads it again with its structured content); a list is cut to the most items that fit, found by halving. `browse` says it cut a page (`truncated`), and its cursor takes 1,100 characters, as a path's name does. | Measured by the final review: a page of 200 entries is some 68 KB indented, 47 KB compact. |
| M12 | `package_versions` and `package_details` are of one package: never a name with `*`; with no `namespace` where several have the name, they ask which (`""` names none); of names spelled alike (Maven's `App` and `app`), the one spelled as asked. `package_details` by name finds the version by the search, among any number. | The final review: `react` beside `@types/react` could not be asked for, and `app` gave `App`'s versions with its own. |
| M13 | A group named to `search_packages` or `package_details` is refused with `not_browsable`, naming the members the caller may browse; `package_versions` gives those members' versions. | The search route leaves groups out, so a group's search found nothing and said nothing; agents are given groups' addresses by the setup snippets. |
| M14 | APT's prerelease is a `~` in the upstream version only; Maven's a qualifier after a separator or a number (`2.0M1`, `1.0rc1`), and a snapshot in any case. | A backport's revision (`1~bpo12+1`, docker-ce's `~ubuntu`) made every release a prerelease. |

### Settled while building plan 14b

| # | What | Why |
| --- | --- | --- |
| N1 | Each format says the public repository a proxy of it is made with where no remote is given (`Format.public_remotes`, by the protocol of its settings, `""` for none; `Format.public_remote(format_config)`), and `GET /api/v1/formats` gives them, with each format's types, to whoever is signed in. The web form takes them from there (in place of the form's own table). | One place says what a new proxy is given: the form and `create_repository` cannot differ (6.2). |
| N2 | A tool that changes is shown to whoever holds its REST route's permission (`holding`); `delete_component` and `delete_path`, whose permission is a repository's, to whoever may delete in some repository by their permissions, narrowed by their token's scopes, or by what is public (`may_somewhere`). Each call is still checked against its repository. | E1 for a permission that is not one string; a tool shown to someone who may delete only elsewhere is refused there, as the REST route refuses. |
| N3 | `Server._tool_input_schema` gives no schema of a tool the caller is not shown. | The SDK reads it to check a call's `Mcp-Param` headers before the call is made (the ruling of 14a's review). |
| N4 | What a tool is given that the REST route's body would refuse is refused in the same words: `validation_error`, a line for each field. | The routes are called with bodies made in the tool; their models' errors are the API's (8.1). |
| N5 | `update_repository` and `update_role` change only what is given: the rest is what there is, and a proxy's stored secret is kept unless a secret is given (the REST API's `PUT` takes them whole). `update_user`'s fields left out, or null, are not changed: an email is not cleared through MCP. | An agent that sends what it means to change does not undo the rest by leaving it out. |
| N6 | `create_user` makes a user who must change their password when they first sign in, always. | 6.2: no tool sets a password a person did not choose (D4 of the identity-access spec). |
| N7 | `delete_path` deletes a file at the path, or else everything under the folder, a thousand files at a time until there is none, each round committed; `No such file or folder.` where there is neither. `delete_component` takes a component's id, or its name and version as `package_details` does. | The REST API has a route for each; an agent names a path, as it does to `browse`. |
| N8 | `revoke_token` revokes API tokens; an OAuth approval is revoked by plan 14c's tools and screens. | There are no approvals before 14c. |
| N9 | A password or a secret given to a tool, at any depth of what it is given (`password`, `proxy.remote_auth.secret`), is written `[redacted]` in the call's log; `delete_path` takes a path with a slash at either end, and refuses one that is only slashes; `revoke_token` finds a token by its name however many its user has; the form gives a proxy chosen before `GET /formats` answered its remote when it does; the server's instructions say what the tools that change things are for. | The final review of 14b: 8.4 says no logged argument is a secret, and 14b's tools are the first given any. |

## 13. Requirements

| BRD | Where |
| --- | --- |
| API-7 (added) AI agents connect over MCP, with a token or OAuth, and do what their user may | Sections 4 to 7 |
| SEC-8 A token's expiry and narrowed privileges | 5: a token's scopes narrow an agent's tools; 7.3: an approval's |
| SEC-9 Clients sign in with a token | 5 |
| CMP-5 Search across the repositories a user may read | `search_packages`, `package_versions` (6.1) |
| CMP-9 Nothing is revealed that the user may not read | 6, E1 |
