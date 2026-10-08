# Hosted npm Repositories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `npm publish`, `install`, `view`, `dist-tag`, `deprecate` and `unpublish` work against a hosted npm repository, and `npm login` gives the client a personal API token.

**Architecture:** An `npm` format package classifies each request path with pure functions and answers through the storage facade. A publish is read into memory up to a limit, each tarball is stored as a file whose component carries the version's manifest, and the package document is generated on every request from those components. Dist-tags live in a server-maintained document. Signing in is one named request the content route lets through without credentials; the security package checks the credentials it carries exactly as it checks HTTP Basic.

**Tech Stack:** FastAPI, SQLAlchemy 2 async with asyncpg, the standard library's `json` and `base64`, pytest + pytest-asyncio, Docker (the `node:22-slim` image, for the real-client test only).

**Spec:** [docs/superpowers/specs/2026-10-08-npm-format-design.md](../specs/2026-10-08-npm-format-design.md), sections 4.1, 5, 6, 7, 8, 11, 12 and the plan 5a part of 13. Business requirements: [docs/BRD.md](../../BRD.md) FMT-2 (hosted), SEC-9, NFR-1.

## Decisions this plan settles

| # | Decision | Reason |
| --- | --- | --- |
| P1 | `authenticate_secret(db, request, username, secret)` is the one function that checks a name and a secret. HTTP Basic uses it, and so does signing a client in. | The limits on failed attempts, and the rule that a token may stand in for a password, are then the same everywhere by construction. |
| P2 | A format reaches signing in through the context (`issue_token`, `revoke_token`), never through the session. | Formats do not handle the session. |
| P3 | If the secret given at sign-in is already one of the user's tokens, that token is returned and no new one is made. | A token can stand in for a password (SEC-9); minting a second token from the first would only add tokens. |
| P4 | A version's manifest is stored in its component's attributes under `npm`, without `dist.tarball`. | The link depends on the address the client used; everything else is fixed at publish. |
| P5 | Dist-tags are judged against the versions that exist at the moment of each change, inside the tags' lock, and are read through the same rule. A tag that points at a removed version is ignored, not rewritten. | Removing a tarball needs only `delete`; it does not have to edit the tags. |
| P6 | An update (`npm deprecate`, `npm unpublish <version>`) needs `add` or `edit` before its body is read, then `edit` to deprecate and `delete` to remove. | Nobody without rights should make the server read a 100 MiB body. |
| P7 | A tarball cannot be uploaded on its own (`405`). | A version without a manifest could not be listed. |
| P8 | In this plan the npm format offers only `hosted`. Plan 5b adds `proxy` and `group`. | A proxy on the generic engine would serve the remote's document with links that bypass MegooArti. |
| P9 | The real client is driven with a token obtained by sending the request `npm login` sends. | `npm login` prompts on a terminal. The same request, then the real client with the token it produced, tests the same code. |
| P10 | Found while executing: for the request that carries credentials in its body, the route ignores credentials in a header. The content route uses a dependency that returns a refused credential instead of raising it, and raises it itself for every other request. `npm login` itself is also run, through a pseudo-terminal. | The real `npm login` failed with a revoked token saved in `.npmrc`: npm sends the saved token with the sign-in, and the route refused it before the format was asked. |

## Global Constraints

- Everything in the earlier plans' Global Constraints still applies. In particular: Alembic only; settings prefixed `MEGOOARTI_` and listed in `README.md`; the standard error envelope; services never commit; no ORM relationships; `megooarti.clock.utcnow()`; asset paths never become file paths; no database connection held while a body moves; only the security package reads `Principal.patterns`; content responses always carry `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`; formats do not commit, the route does; LF line endings; 100-character lines; ruff clean; spaced markdown table separators.
- **This plan adds no migration and no dependency.**
- **The format's name is `npm`.** Permissions are `repository:npm:<name>:<action>`.
- **Only `npm/format.py` touches the repository context.** `npm/paths.py`, `npm/semver.py` and `npm/documents.py` are pure functions: no database, no files, no clock.
- **Exactly one request is taken without credentials:** `PUT -/user/org.couchdb.user:<name>`. Its handler must not use the principal, and checks the credentials only through the context.
- **A token is never logged**, and neither is a password.
- **In-memory reads are bounded:** a sign-in or a dist-tag 16 KiB, a publish `MEGOOARTI_NPM_MAX_PUBLISH_BYTES`, a manifest 1 MiB, the stored dist-tags 1 MiB.
- **Publishing and building documents run on two worker threads of their own**, with the database connection given back before a document is built.
- A test must never contact a real network host. The Docker-marked tests are the exception, and say so.

**Working directories:** run `uv`, `pytest` and `ruff` commands in `backend/`. Run `git` and `docker` commands in the repository root. Tests need the `db` Compose service; on a machine where port 5432 is taken, set `MEGOOARTI_TEST_DATABASE_URL` as the README describes.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first. Each has a test in the task named.

1. **The request taken without credentials.** Nothing else may get through the same door: another method on the same address, a write to any other address, or a sign-in for one user that carries another's name. Failed attempts must be limited exactly as for any sign-in, and a user who must change their password gets no token (Tasks 1, 6).
2. **A publish that is not what it says:** a tarball that does not match `shasum`, `integrity` or `length`; a manifest that names another package or version; an attachment that is missing or is not base64; a body that is not JSON, is nested thousands deep, or is over the limit. Each is refused, and nothing is stored, including temporary files (Tasks 5, 6).
3. **An account with exactly one permission.** `add` publishes a new version and cannot replace one; `edit` deprecates; `delete` removes; `read` reads. None of them does another's job (Task 6).
4. **Removing what `latest` points at.** `latest` moves to the highest version left, whether the version went by `npm unpublish` or by deleting the tarball, and a later publish under another tag does not make a pre-release `latest` (Tasks 5, 6).
5. **Two publishes at the same moment,** and two dist-tag changes at the same moment. Both versions are listed and both tags are kept (Task 6).

---

### Task 1: Core: credentials in the body, and signing a client in

**Files:**
- Modify: `backend/src/megooarti/repositories/formats.py`
- Modify: `backend/src/megooarti/repositories/routes.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/security/authentication.py`
- Create: `backend/src/megooarti/security/client_login.py`
- Test: `backend/tests/repositories/test_client_login.py`

**Interfaces:**
- Consumes: `authenticate_password`, `_authenticate_token`, `tokens.create_token`, `tokens.find_token`, `client_principal`.
- Produces:
  - `Format.takes_body_credentials(method: str, path: str) -> bool` — default `False`. The content route lets a write without credentials through only when it is `True`. `path` is the path as requested, not yet normalised.
  - `await authentication.authenticate_secret(db, request, username, secret) -> tuple[User, ApiToken | None]` — raises `401` or `429`.
  - `await client_login.issue_token(db, request, username, secret, *, label) -> str` — raises `401`, `403 password_change_required` or `429`. The caller commits.
  - `await client_login.revoke_own_token(db, principal, value) -> None` — raises `404`.
  - `await context.issue_token(request, username, secret, *, label) -> str` and `await context.revoke_token(value) -> None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_client_login.py`:

```python
"""A format that signs its client in: the one request taken without credentials."""

import json

import pytest
from sqlalchemy import select
from starlette.responses import JSONResponse, Response

from megooarti.repositories import formats
from megooarti.repositories.formats import Format
from megooarti.security.models import ApiToken
from tests.accounts import PASSWORD, basic, bearer, error_code

LOGIN = "/repository/files/-/login"
FILE = "/repository/files/a.txt"


class SigningIn(Format):
    """Raw files, plus a sign-in and a sign-out address."""

    name = "raw"

    def takes_body_credentials(self, method, path):
        return method == "PUT" and path == "-/login"

    async def handle_hosted(self, context, request, path):
        if path == "-/login":
            sent = json.loads(await context.receive(request.stream(), limit=1000))
            token = await context.issue_token(
                request, sent["name"], sent["password"], label="test login"
            )
            return JSONResponse({"token": token, "principal": context.principal is not None})
        if path == "-/logout":
            await context.revoke_token(request.headers["X-Token"])
            return Response(status_code=204)
        return await super().handle_hosted(context, request, path)


@pytest.fixture
async def dana(files, make_user, monkeypatch):
    monkeypatch.setitem(formats._registry, "raw", SigningIn())
    return await make_user("dana", roles=["admin"])


async def sign_in(client, name: str = "dana", password: str = PASSWORD):
    return await client.put(LOGIN, json={"name": name, "password": password})


async def test_the_named_request_is_taken_without_credentials(client, dana):
    response = await sign_in(client)

    assert response.status_code == 200
    assert response.json()["principal"] is False
    token = response.json()["token"]
    assert (await client.put(FILE, content=b"hello", headers=bearer(token))).status_code == 201
    assert (await client.get(FILE, headers=bearer(token))).content == b"hello"


async def test_every_other_write_still_needs_credentials(client, dana):
    attempts = [
        await client.put(FILE, content=b"hello"),
        await client.post(LOGIN, json={"name": "dana", "password": PASSWORD}),
        await client.delete(LOGIN),
        await client.put("/repository/files/-/logout"),
    ]

    assert [response.status_code for response in attempts] == [401, 401, 401, 401]


async def test_a_format_that_names_no_request_takes_none(client, files, make_user):
    await make_user("dana", roles=["admin"])

    response = await sign_in(client)

    assert (response.status_code, error_code(response)) == (401, "unauthorized")


async def test_the_token_is_a_personal_api_token_named_for_the_client(client, dana, db):
    await sign_in(client)

    token = await db.scalar(select(ApiToken))

    assert token.user_id == dana.id
    assert token.name.startswith("test login 20")
    assert (token.expires_at, token.scopes) == (None, None)


async def test_wrong_credentials_get_no_token(client, dana, db):
    wrong = await sign_in(client, password="not the password")
    unknown = await sign_in(client, name="nobody")

    assert (wrong.status_code, error_code(wrong)) == (401, "unauthorized")
    assert unknown.status_code == 401
    assert await db.scalar(select(ApiToken)) is None


async def test_failed_attempts_are_limited_as_for_any_sign_in(client, dana, app):
    allowed = app.state.settings.login_max_failures

    statuses = [(await sign_in(client, password="guess")).status_code for _ in range(allowed + 1)]
    with_the_right_password = await sign_in(client)

    assert statuses == [401] * allowed + [429]
    assert (with_the_right_password.status_code, error_code(with_the_right_password)) == (
        429,
        "too_many_attempts",
    )


async def test_an_api_token_given_as_the_secret_is_returned_as_it_is(client, dana, make_token, db):
    token = await make_token(dana)

    response = await sign_in(client, password=token)
    for_someone_else = await sign_in(client, name="root", password=token)

    assert response.json()["token"] == token
    assert for_someone_else.status_code == 401
    assert len(list(await db.scalars(select(ApiToken.id)))) == 1


async def test_a_pending_password_change_blocks_the_token(
    client, files, make_user, monkeypatch, db
):
    monkeypatch.setitem(formats._registry, "raw", SigningIn())
    await make_user("newcomer", roles=["admin"], must_change_password=True)

    response = await sign_in(client, name="newcomer")

    assert (response.status_code, error_code(response)) == (403, "password_change_required")
    assert await db.scalar(select(ApiToken)) is None


async def test_a_caller_revokes_only_their_own_token(client, dana, make_user):
    await make_user("eli", roles=["admin"])
    danas = (await sign_in(client)).json()["token"]
    elis = (await sign_in(client, name="eli")).json()["token"]
    logout = "/repository/files/-/logout"

    not_theirs = await client.put(logout, headers={**bearer(elis), "X-Token": danas})
    unknown = await client.put(logout, headers={**bearer(elis), "X-Token": "mga_nothing"})
    own = await client.put(logout, headers={**bearer(danas), "X-Token": danas})

    assert (not_theirs.status_code, error_code(not_theirs)) == (404, "not_found")
    assert unknown.status_code == 404
    assert own.status_code == 204
    assert (await client.get(FILE, headers=bearer(danas))).status_code == 401
    assert (await client.get(FILE, headers=bearer(elis))).status_code == 404


async def test_basic_credentials_are_checked_the_same_way_as_before(client, dana, make_token):
    token = await make_token(dana)

    with_password = await client.get(FILE, headers=basic("dana", PASSWORD))
    with_token = await client.get(FILE, headers=basic("dana", token))
    with_another_name = await client.get(FILE, headers=basic("root", token))
    wrong = await client.get(FILE, headers=basic("dana", "wrong"))

    assert (with_password.status_code, with_token.status_code) == (404, 404)
    assert (with_another_name.status_code, wrong.status_code) == (401, 401)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_client_login.py -q`
Expected: 9 of the 10 fail. Signing in without credentials is `401`, because the route refuses it before the format is asked. `test_a_format_that_names_no_request_takes_none` passes already: it states what must stay true.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/formats.py`, add this method to `Format`, after `is_metadata`:

```python
    def takes_body_credentials(self, method: str, path: str) -> bool:
        """Whether this request carries its credentials in its body, with no header.

        The content route refuses a write without credentials before any format code
        runs, except one this says yes to. A handler for such a request must not use
        the principal, and must check the credentials through the context.
        """
        return False
```

In `backend/src/megooarti/repositories/routes.py`, replace:

```python
    elif principal is None:
        raise unauthorized(scheme="Basic")
```

with:

```python
    elif principal is None and not context.format.takes_body_credentials(request.method, path):
        raise unauthorized(scheme="Basic")
```

In `backend/src/megooarti/security/authentication.py`, add after `_authenticate_token`:

```python
async def authenticate_secret(
    db: AsyncSession, request: Request, username: str, secret: str
) -> tuple[User, ApiToken | None]:
    """The user with this name whose password, or one of whose API tokens, is `secret`.

    Returns the token too when the secret was one. Raises 401 or 429. HTTP Basic
    credentials are checked here, and so is anything else that takes a name and a
    secret, so that the limits on failed attempts are the same everywhere.
    """
    if secret.startswith(TOKEN_PREFIX):
        return await _authenticate_token(db, request, secret, username)
    return await authenticate_password(db, request, username, secret), None
```

and in `_from_header`, replace the `basic` branch with:

```python
    if scheme == "basic":
        username, secret = _decode_basic(credentials)
        user, token = await authenticate_secret(db, request, username, secret)
        method = "password" if token is None else "token"
        return await build_principal(db, user, method, token=token)
```

`backend/src/megooarti/security/client_login.py`:

```python
"""Signing a package client in: credentials go in, a token to keep comes out.

Some clients have a sign-in command (`npm login`, later `docker login`) that sends a
user name and a secret and expects a token back. The secret is checked exactly as HTTP
Basic credentials are, so the same limits on failed attempts apply.
"""

import secrets

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.security import tokens
from megooarti.security.authentication import Principal, authenticate_secret

log = structlog.get_logger(__name__)


async def issue_token(
    db: AsyncSession, request: Request, username: str, secret: str, *, label: str
) -> str:
    """A token for the user with this name and secret. Raises 401, 403 or 429.

    If the secret is already one of the user's API tokens, that token is the answer:
    the client keeps using it. Otherwise the secret is the password, and a new personal
    API token is created, named with `label` and the time. The caller commits.
    """
    user, token = await authenticate_secret(db, request, username, secret)
    if token is not None:
        return secret
    if user.must_change_password:
        # A token would let the account be used without ever changing the password.
        raise ApiError(
            403, "password_change_required", "Change your password before doing anything else."
        )
    name = f"{label} {utcnow():%Y-%m-%d %H:%M:%S} {secrets.token_hex(3)}"
    _, value = await tokens.create_token(db, user.id, name=name, expires_at=None, scopes=None)
    log.info("client_signed_in", username=user.username, token_name=name)
    return value


async def revoke_own_token(db: AsyncSession, principal: Principal, value: str) -> None:
    """Revoke the token with this value, if it is the caller's. Raises 404 otherwise."""
    token = await tokens.find_token(db, value, utcnow())
    if token is None or token.user_id != principal.user.id:
        raise ApiError(404, "not_found", "No such token.")
    await db.delete(token)
    await db.flush()
    log.info("client_signed_out", username=principal.user.username, token_name=token.name)
```

In `backend/src/megooarti/repositories/content.py`, change the security import to:

```python
from megooarti.security import client_login
from megooarti.security.authentication import Principal, authorize, unauthorized
```

and add these methods to `RepositoryContext`, after `http`:

```python
    async def issue_token(
        self, request: Request, username: str, secret: str, *, label: str
    ) -> str:
        """Sign a package client in: check a name and a secret, and return a token.

        For the request a format has named as carrying its credentials in its body.
        The secret is checked as HTTP Basic credentials are. The caller commits.
        """
        return await client_login.issue_token(self.db, request, username, secret, label=label)

    async def revoke_token(self, value: str) -> None:
        """Revoke the API token with this value, if it is the caller's."""
        if self.principal is None:
            raise unauthorized(scheme="Basic")
        await client_login.revoke_own_token(self.db, self.principal, value)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories tests/security -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests/repositories/test_client_login.py
git commit -m "feat(security): let a format sign its client in with credentials in the body"
```

---

### Task 2: Core: component attributes, staged bytes and the public address

**Files:**
- Modify: `backend/src/megooarti/repositories/content.py`
- Test: `backend/tests/repositories/test_content_components.py`

**Interfaces:**
- Consumes: `_record`, `_component`, `_lock_component`, `_pieces`, `stage`, `system.settings_store.get_setting`.
- Produces, in `megooarti.repositories.content`:
  - `ComponentInfo(version, attributes, created, modified)` — frozen dataclass.
  - `await context.store(path, staged, *, content_type=None, kind="asset", component_attributes=None)` — when given, `component_attributes` replaces the attributes of the component the file belongs to.
  - `await context.stage_bytes(data: bytes) -> StagedBlob` and `await context.discard(staged) -> None`.
  - `await context.components(namespace, name) -> list[ComponentInfo]` — the versions that have a file; `modified` is when their files last changed.
  - `await context.annotate(namespace, name, version, attributes) -> bool` — needs `edit`; refuses a read-only repository; `False` if there is no such component.
  - `await context.package_names(text, *, limit, offset) -> tuple[list[tuple[str, str]], int]` — distinct `(namespace, name)` whose name or namespace contains `text`, ignoring case, ordered; and how many there are in all.
  - `await context.public_url(request) -> str` — `<base>/repository/<name>`, where `<base>` is the `base_url` setting if set, otherwise the request's own address. No trailing slash.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/test_content_components.py`:

```python
import pytest
from sqlalchemy import select
from starlette.requests import Request

from megooarti.errors import ApiError
from megooarti.repositories import service
from megooarti.repositories.content import ComponentInfo
from megooarti.repositories.formats import ComponentKey, Format
from megooarti.repositories.models import Asset, Component
from megooarti.system.settings_store import set_setting
from tests.repositories.conftest import someone

EVERYTHING = someone("repository:raw:files")


class Packaged(Format):
    """Files at namespace/name/version/file belong to a package; others to none."""

    name = "raw"

    def describe_component(self, path):
        parts = path.split("/")
        return ComponentKey(*parts[:3]) if len(parts) == 4 else None


def request(url: str = "http://internal.example:8000/repository/files/x") -> Request:
    scheme, _, rest = url.partition("://")
    host, _, path = rest.partition("/")
    name, _, port = host.partition(":")
    scope = {
        "type": "http",
        "method": "GET",
        "scheme": scheme,
        "server": (name, int(port or 80)),
        "path": f"/{path}",
        "root_path": "",
        "headers": [(b"host", host.encode())],
    }
    return Request(scope)


async def error_of(awaitable) -> ApiError:
    with pytest.raises(ApiError) as caught:
        await awaitable
    return caught.value


@pytest.fixture
async def context(files, context_for):
    made = await context_for(files, EVERYTHING)
    made.format = Packaged()
    return made


async def store(context, path: str, content: bytes = b"x", **options):
    staged = await context.stage_bytes(content)
    return await context.store(path, staged, **options)


async def test_storing_can_describe_the_component(context, db):
    asset, created = await store(context, "acme/app/1.0/app.tgz", component_attributes={"a": 1})

    component = await db.get(Component, asset.component_id)
    assert created is True
    assert component.attributes == {"a": 1}


async def test_storing_again_replaces_the_description(context, db):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"a": 1})

    asset, created = await store(
        context, "acme/app/1.0/app.tgz", b"new", component_attributes={"a": 2}
    )
    untouched, _ = await store(context, "acme/app/1.0/app.tgz", b"newer")

    component = await db.get(Component, asset.component_id, populate_existing=True)
    assert created is False
    assert component.attributes == {"a": 2}
    assert untouched.component_id == asset.component_id


async def test_a_second_file_of_a_component_can_describe_it_too(context, db):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"a": 1})
    await store(context, "acme/app/1.0/app.sig", component_attributes={"a": 3})

    assert list(await db.scalars(select(Component.attributes))) == [{"a": 3}]


async def test_bytes_in_memory_are_staged_and_can_be_discarded(context, settings, db):
    staged = await context.stage_bytes(b"y" * 3_000_000)
    temporary = settings.data_dir / "blobs" / "default" / "tmp"

    assert staged.size == 3_000_000
    assert len(list(temporary.iterdir())) == 1
    await context.discard(staged)
    assert list(temporary.iterdir()) == []
    assert await db.scalar(select(Asset)) is None


async def test_components_lists_a_packages_versions_with_their_attributes(context):
    first, _ = await store(context, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    extra, _ = await store(context, "acme/app/1.0/app.sig")
    second, _ = await store(context, "acme/app/2.0/app.tgz", component_attributes={"n": 2})
    await store(context, "acme/other/1.0/other.tgz")
    await store(context, "elsewhere/app/1.0/app.tgz")

    held = sorted(await context.components("acme", "app"), key=lambda info: info.version)

    assert [info.version for info in held] == ["1.0", "2.0"]
    assert [info.attributes for info in held] == [{"n": 1}, {"n": 2}]
    assert held[0].modified == max(first.updated_at, extra.updated_at)
    assert held[1].modified == second.updated_at
    assert isinstance(held[0], ComponentInfo) and held[0].created <= held[0].modified
    assert await context.components("acme", "nothing") == []


async def test_annotate_changes_a_components_attributes(context, db):
    await store(context, "acme/app/1.0/app.tgz", component_attributes={"n": 1})

    changed = await context.annotate("acme", "app", "1.0", {"n": 1, "deprecated": "old"})
    missing = await context.annotate("acme", "app", "9.9", {"n": 9})

    assert (changed, missing) == (True, False)
    assert (await context.components("acme", "app"))[0].attributes == {"n": 1, "deprecated": "old"}


async def test_annotate_needs_edit_and_a_repository_that_takes_changes(db, files, context_for):
    writer = await context_for(files, EVERYTHING)
    writer.format = Packaged()
    await store(writer, "acme/app/1.0/app.tgz", component_attributes={"n": 1})
    adder = await context_for(files, someone("repository:raw:files:add"))
    await service.update_repository(
        db, files, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
    )

    forbidden = await error_of(adder.annotate("acme", "app", "1.0", {"n": 2}))
    read_only = await error_of(writer.annotate("acme", "app", "1.0", {"n": 2}))

    assert (forbidden.status_code, forbidden.code) == (403, "forbidden")
    assert (read_only.status_code, read_only.code) == (403, "repository_read_only")
    assert (await writer.components("acme", "app"))[0].attributes == {"n": 1}


async def test_package_names_finds_packages_by_name_or_namespace(context):
    for path in (
        "acme/left-pad/1.0/a.tgz",
        "acme/left-pad/2.0/a.tgz",
        "acme/right-pad/1.0/a.tgz",
        "padding/tool/1.0/a.tgz",
        "zeta/unrelated/1.0/a.tgz",
        "loose.txt",
    ):
        await store(context, path)

    names, total = await context.package_names("PAD", limit=10, offset=0)
    page, page_total = await context.package_names("pad", limit=1, offset=1)
    everything, count = await context.package_names("", limit=10, offset=0)
    literal, _ = await context.package_names("left_pad", limit=10, offset=0)

    assert names == [("acme", "left-pad"), ("acme", "right-pad"), ("padding", "tool")]
    assert total == 3
    assert (page, page_total) == ([("acme", "right-pad")], 3)
    assert (len(everything), count) == (4, 4)
    assert literal == []


async def test_the_public_address_is_the_requests_unless_one_is_configured(context, db):
    from_request = await context.public_url(request())
    await set_setting(db, "base_url", "https://packages.example/")

    configured = await context.public_url(request())

    assert from_request == "http://internal.example:8000/repository/files"
    assert configured == "https://packages.example/repository/files"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_content_components.py -q`
Expected: collection error, `cannot import name 'ComponentInfo' from 'megooarti.repositories.content'`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/content.py`, change the first SQLAlchemy import to `from sqlalchemy import delete, func, or_, select, text`, and add `from megooarti.system.settings_store import get_setting` after the storage imports.

Add after the `FileEntry` class:

```python
@dataclass(frozen=True)
class ComponentInfo:
    """One version of a package: what its component says, and when it changed."""

    version: str
    attributes: dict[str, Any]
    created: datetime
    modified: datetime
```

In `_record`, add the keyword parameter `component_attributes: dict[str, Any] | None = None` after `packaged: bool = True`. Replace:

```python
            key = self.format.describe_component(path) if packaged else None
            component_id = None if key is None else (await self._component(key)).id
            asset = Asset(
                repository_id=self.repository.id,
                component_id=component_id,
```

with:

```python
            key = self.format.describe_component(path) if packaged else None
            component = None if key is None else await self._component(key)
            if component is not None and component_attributes is not None:
                component.attributes = component_attributes
            asset = Asset(
                repository_id=self.repository.id,
                component_id=None if component is None else component.id,
```

and, in the branch for a path that already exists, replace:

```python
        await self.db.flush()
        if changed:
            await blobs.dereference(self.db, [previous], now)
        return existing, False
```

with:

```python
        if component_attributes is not None and existing.component_id is not None:
            component = await self.db.get(
                Component, existing.component_id, populate_existing=True
            )
            await self._lock_component(
                ComponentKey(component.namespace, component.name, component.version)
            )
            component.attributes = component_attributes
        await self.db.flush()
        if changed:
            await blobs.dereference(self.db, [previous], now)
        return existing, False
```

Replace `store` with:

```python
    async def store(
        self,
        path: str,
        staged: StagedBlob,
        *,
        content_type: str | None = None,
        kind: str = "asset",
        component_attributes: dict[str, Any] | None = None,
    ) -> tuple[Asset, bool]:
        """Record staged content at a path, in the caller's transaction.

        Checks permission and policy under the path lock. Never commits: the caller
        does, and a rollback undoes everything recorded here. `component_attributes`,
        when given, become the attributes of the component the file belongs to.
        """
        return await self._record(
            path,
            staged,
            content_type=content_type,
            kind=kind,
            checked=True,
            component_attributes=component_attributes,
        )
```

Add these methods to `RepositoryContext`, after `stage`:

```python
    async def stage_bytes(self, data: bytes) -> StagedBlob:
        """Stage content that is already in memory, such as a file decoded from a body."""
        return await self.stage(_pieces(data))

    async def discard(self, staged: StagedBlob) -> None:
        """Drop staged content that will not be stored after all."""
        await self.backend.discard(staged)
```

after `names`:

```python
    async def components(self, namespace: str, name: str) -> list[ComponentInfo]:
        """The versions of a package that have a file, with their attributes."""
        rows = await self.db.execute(
            select(
                Component.version,
                Component.attributes,
                Component.created_at,
                func.max(Asset.updated_at),
            )
            .join(Asset, Asset.component_id == Component.id)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
            )
            .group_by(Component.id)
        )
        return [
            ComponentInfo(version, attributes, created, changed)
            for version, attributes, created, changed in rows
        ]

    async def package_names(
        self, text: str, *, limit: int, offset: int
    ) -> tuple[list[tuple[str, str]], int]:
        """Packages whose name or namespace contains `text`, and how many there are.

        The text is matched literally and without regard to case. An empty text matches
        every package.
        """
        literal = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{literal}%"
        found = (
            select(Component.namespace, Component.name)
            .where(
                Component.repository_id == self.repository.id,
                or_(
                    Component.name.ilike(pattern, escape="\\"),
                    Component.namespace.ilike(pattern, escape="\\"),
                ),
            )
            .distinct()
        )
        total = await self.db.scalar(select(func.count()).select_from(found.subquery()))
        rows = await self.db.execute(
            found.order_by(Component.namespace, Component.name).limit(limit).offset(offset)
        )
        return [(namespace, name) for namespace, name in rows], total or 0

    async def public_url(self, request: Request) -> str:
        """The address clients use to reach this repository, without a trailing slash.

        The `base_url` setting if there is one: behind a reverse proxy the request's
        own address may not be the public one.
        """
        base = await get_setting(self.db, "base_url") or str(request.base_url)
        return f"{base.rstrip('/')}/repository/{self.repository.name}"
```

and after `maintain`:

```python
    async def annotate(
        self, namespace: str, name: str, version: str, attributes: dict[str, Any]
    ) -> bool:
        """Replace a component's attributes. False if there is no such component.

        Changing what is said about a published version needs `edit`. It is not a
        redeploy, so `disable_redeploy` does not stop it; a read-only repository does.
        """
        authorize(self.principal, self.permission("edit"), scheme="Basic")
        self._check_policy(replacing=False)
        key = ComponentKey(namespace, name, version)
        await self._lock_component(key)
        component = await self.db.scalar(
            select(Component)
            .where(
                Component.repository_id == self.repository.id,
                Component.namespace == namespace,
                Component.name == name,
                Component.version == version,
            )
            .execution_options(populate_existing=True)
        )
        if component is None:
            return False
        component.attributes = attributes
        await self.db.flush()
        return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/content.py backend/tests/repositories/test_content_components.py
git commit -m "feat(repositories): component attributes, staged bytes and the public address"
```

---

### Task 3: Core: a response with its own ETag, and the publish limit

**Files:**
- Modify: `backend/src/megooarti/repositories/serving.py`
- Modify: `backend/src/megooarti/repositories/content.py`
- Modify: `backend/src/megooarti/config.py`
- Modify: `backend/tests/repositories/test_serving.py`
- Modify: `backend/tests/repositories/test_content_reads.py`
- Modify: `backend/tests/test_config.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `serving.Servable`, `serving.plan`, `context.respond_with`.
- Produces:
  - `Servable(..., md5: str | None, sha1: str | None, sha512: str | None, ..., etag: str | None = None)` — a checksum header is sent only for a digest that is given, and `ETag` is `etag` when given, otherwise the SHA-256.
  - `context.respond_with(data, request, *, filename, content_type, last_modified, etag=None)` — with `etag`, the bytes are not hashed and no `X-Checksum-*` header is sent.
  - `Settings.npm_max_publish_bytes: int = 104857600` (`MEGOOARTI_NPM_MAX_PUBLISH_BYTES`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/repositories/test_serving.py`:

```python
def test_an_item_can_name_its_own_etag_and_leave_out_checksums():
    item = replace(ITEM, sha256="", md5=None, sha1=None, sha512=None, etag="chosen")

    made = make(item=item)
    unchanged = make(item=item, if_none_match='"chosen"')

    assert made.headers["ETag"] == '"chosen"'
    assert not [name for name in made.headers if name.startswith("X-Checksum")]
    assert made.headers["Content-Security-Policy"] == "sandbox"
    assert (unchanged.status, unchanged.byte_range) == (304, None)
```

Append to `backend/tests/repositories/test_content_reads.py`:

```python
async def test_a_response_with_its_own_etag_is_not_hashed(context):
    def respond(incoming: Request):
        return context.respond_with(
            DOCUMENT,
            incoming,
            filename="package.json",
            content_type="application/json",
            last_modified=WHEN,
            etag="known-already",
        )

    response = respond(request())
    unchanged = respond(request(if_none_match='"known-already"'))

    assert (response.status_code, response.body) == (200, DOCUMENT)
    assert response.headers["ETag"] == '"known-already"'
    assert not [name for name in response.headers if name.lower().startswith("x-checksum")]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert (unchanged.status_code, unchanged.body) == (304, b"")
```

Append to `backend/tests/test_config.py`:

```python
def test_the_npm_publish_limit(monkeypatch):
    assert Settings(_env_file=None, database_url=VALID_URL).npm_max_publish_bytes == 104857600

    monkeypatch.setenv("MEGOOARTI_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("MEGOOARTI_NPM_MAX_PUBLISH_BYTES", "2048")

    assert Settings(_env_file=None).npm_max_publish_bytes == 2048
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/test_serving.py tests/repositories/test_content_reads.py tests/test_config.py -q`
Expected: 3 failures. `Servable` has no field `etag`; `respond_with()` got an unexpected keyword argument `etag`; `Settings` has no attribute `npm_max_publish_bytes`.

- [ ] **Step 3: Implement**

In `backend/src/megooarti/repositories/serving.py`, replace the `Servable` class, `_etag` and `_base_headers` with:

```python
@dataclass(frozen=True)
class Servable:
    sha256: str
    md5: str | None
    sha1: str | None
    sha512: str | None
    size: int
    content_type: str
    last_modified: datetime
    filename: str
    # For content made for the request, whose maker already knows a value that changes
    # whenever it does. The digests are then left out instead of being computed.
    etag: str | None = None


def _etag(item: Servable) -> str:
    return f'"{item.etag or item.sha256}"'


def _base_headers(item: Servable) -> dict[str, str]:
    headers = {
        "Content-Type": item.content_type,
        "ETag": _etag(item),
        "Last-Modified": format_datetime(item.last_modified.astimezone(UTC), usegmt=True),
        "Accept-Ranges": "bytes",
        "Content-Disposition": _disposition(item.filename),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }
    digests = {"Md5": item.md5, "Sha1": item.sha1, "Sha256": item.sha256, "Sha512": item.sha512}
    headers.update({f"X-Checksum-{name}": digest for name, digest in digests.items() if digest})
    return headers
```

In `backend/src/megooarti/repositories/content.py`, replace `respond_with` with:

```python
    def respond_with(
        self,
        data: bytes,
        request: Request,
        *,
        filename: str,
        content_type: str,
        last_modified: datetime,
        etag: str | None = None,
    ) -> Response:
        """Answer a GET or HEAD with bytes made for this request.

        The same planning as for a stored file, so the headers, conditions and ranges
        are the same too. With `etag`, the caller already knows a value that changes
        whenever the bytes do: they are then not hashed here, and no checksum headers
        are sent.
        """

        def digest(algorithm: str) -> str | None:
            return None if etag is not None else hashlib.new(algorithm, data).hexdigest()

        item = serving.Servable(
            sha256=digest("sha256") or "",
            md5=digest("md5"),
            sha1=digest("sha1"),
            sha512=digest("sha512"),
            size=len(data),
            content_type=content_type,
            last_modified=last_modified,
            filename=filename,
            etag=etag,
        )
        plan = serving.plan(request.method, request.headers, item)
        if plan.byte_range is None:
            return Response(status_code=plan.status, headers=plan.headers)
        start, end = plan.byte_range
        return Response(
            content=data[start : end + 1], status_code=plan.status, headers=plan.headers
        )
```

In `backend/src/megooarti/config.py`, add after the line `secret_key: str | None = None`:

```python
    npm_max_publish_bytes: int = 100 * 1024 * 1024
```

In `README.md`, in the configuration table, add after the row for `MEGOOARTI_SECRET_KEY`:

```markdown
| `MEGOOARTI_NPM_MAX_PUBLISH_BYTES` | `104857600` | Largest `npm publish` request accepted. A publish is read into memory, so this bounds what one costs |
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories tests/test_config.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti backend/tests README.md
git commit -m "feat(repositories): responses with their own ETag; the npm publish limit"
```

---

### Task 4: npm paths and version order

**Files:**
- Create: `backend/src/megooarti/repositories/npm/__init__.py`
- Create: `backend/src/megooarti/repositories/npm/paths.py`
- Create: `backend/src/megooarti/repositories/npm/semver.py`
- Create: `backend/tests/repositories/npm/__init__.py` (empty)
- Test: `backend/tests/repositories/npm/test_paths.py`
- Test: `backend/tests/repositories/npm/test_semver.py`

**Interfaces:**
- Consumes: nothing.
- Produces, in `megooarti.repositories.npm.paths`:
  - `NpmPath(kind, package="", version="", filename="", tag="", username="", token="")` — frozen dataclass. `kind` is `document`, `version`, `tarball`, `dist_tags`, `login`, `logout`, `whoami`, `ping`, `search` or `other`. Properties `scope` (without `@`) and `name` (without its scope).
  - `classify(path: str) -> NpmPath`; `is_valid_name(package) -> bool`; `scope_of(package)`, `unscoped(package)`; `tarball_filename(package, version)`, `tarball_path(package, version)`, `dist_tags_path(package)`; `MAX_NAME_LENGTH = 214`.
- Produces, in `megooarti.repositories.npm.semver`:
  - `is_valid(version) -> bool`; `sort_key(version) -> tuple`; `sorted_versions(versions) -> list[str]`; `highest(versions) -> str | None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/npm/test_paths.py`:

```python
import pytest

from megooarti.repositories.npm import paths
from megooarti.repositories.npm.paths import NpmPath, classify

OTHER = NpmPath("other")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("left-pad", NpmPath("document", package="left-pad")),
        ("@acme/widget", NpmPath("document", package="@acme/widget")),
        ("left-pad/-rev/3-abc", NpmPath("document", package="left-pad")),
        ("@acme/widget/-rev/3-abc", NpmPath("document", package="@acme/widget")),
        ("JSONStream", NpmPath("document", package="JSONStream")),
        ("left-pad/1.3.0", NpmPath("version", package="left-pad", version="1.3.0")),
        ("left-pad/latest", NpmPath("version", package="left-pad", version="latest")),
        ("@acme/widget/2.0.0", NpmPath("version", package="@acme/widget", version="2.0.0")),
        (
            "left-pad/-/left-pad-1.3.0.tgz",
            NpmPath("tarball", package="left-pad", version="1.3.0", filename="left-pad-1.3.0.tgz"),
        ),
        (
            "@acme/widget/-/widget-2.0.0-beta.1.tgz",
            NpmPath(
                "tarball",
                package="@acme/widget",
                version="2.0.0-beta.1",
                filename="widget-2.0.0-beta.1.tgz",
            ),
        ),
        (
            "left-pad/-/left-pad-1.3.0.tgz/-rev/4-def",
            NpmPath("tarball", package="left-pad", version="1.3.0", filename="left-pad-1.3.0.tgz"),
        ),
    ],
)
def test_package_paths(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("-/ping", NpmPath("ping")),
        ("-/whoami", NpmPath("whoami")),
        ("-/v1/search", NpmPath("search")),
        ("-/user/org.couchdb.user:dana", NpmPath("login", username="dana")),
        ("-/user/org.couchdb.user:dana/-rev/1-abc", NpmPath("login", username="dana")),
        ("-/user/token/mga_abc", NpmPath("logout", token="mga_abc")),
        ("-/package/left-pad/dist-tags", NpmPath("dist_tags", package="left-pad")),
        ("-/package/left-pad/dist-tags/beta", NpmPath("dist_tags", package="left-pad", tag="beta")),
        (
            "-/package/@acme/widget/dist-tags/next",
            NpmPath("dist_tags", package="@acme/widget", tag="next"),
        ),
    ],
)
def test_registry_paths(path, expected):
    assert classify(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "-",
        "-/v1/login",
        "-/npm/v1/security/advisories/bulk",
        "-/user/org.couchdb.user:",
        "-/user/someone",
        "-/user/token",
        "-/package/left-pad",
        "-/package/@acme/dist-tags",
        "-/package/left-pad/dist-tags/a/b",
        "@acme",
        "@/widget",
        ".hidden",
        "_private",
        "has space",
        "a" * 215,
        "left-pad/-",
        "left-pad/-/other-1.3.0.tgz",
        "left-pad/-/left-pad-.tgz",
        "left-pad/-/left-pad-1.3.0.zip",
        "left-pad/-/left-pad-1.3.0.tgz/extra",
        "@acme/widget/-/@acme/widget-2.0.0.tgz",
        "left-pad/1.3.0/extra",
    ],
)
def test_everything_else_is_other(path):
    assert classify(path) == OTHER


def test_a_path_knows_its_scope_and_name():
    scoped = classify("@acme/widget/-/widget-2.0.0.tgz")
    plain = classify("left-pad")

    assert (scoped.scope, scoped.name) == ("acme", "widget")
    assert (plain.scope, plain.name) == ("", "left-pad")


@pytest.mark.parametrize(
    ("package", "valid"),
    [
        ("left-pad", True),
        ("@acme/widget", True),
        ("a.b_c~d", True),
        ("JSONStream", True),
        ("a" * 214, True),
        ("a" * 215, False),
        ("", False),
        ("@acme", False),
        ("@acme/", False),
        ("@acme/widget/more", False),
        (".hidden", False),
        ("@acme/_private", False),
        ("with/slash", False),
        ("ünïcode", False),
        ("percent%2f", False),
    ],
)
def test_package_names(package, valid):
    assert paths.is_valid_name(package) is valid


def test_where_things_are_stored():
    assert paths.tarball_path("left-pad", "1.3.0") == "left-pad/-/left-pad-1.3.0.tgz"
    assert paths.tarball_path("@acme/widget", "2.0.0") == "@acme/widget/-/widget-2.0.0.tgz"
    assert paths.dist_tags_path("@acme/widget") == "-/package/@acme/widget/dist-tags"
    assert classify(paths.tarball_path("@acme/widget", "2.0.0")).kind == "tarball"
    assert classify(paths.dist_tags_path("@acme/widget")).kind == "dist_tags"
```

`backend/tests/repositories/npm/test_semver.py`:

```python
from itertools import pairwise

import pytest

from megooarti.repositories.npm import semver

# The precedence example from section 11 of the specification, lowest first.
PRECEDENCE = [
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-alpha.beta",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.11",
    "1.0.0-rc.1",
    "1.0.0",
    "1.0.1",
    "1.1.0",
    "1.10.0",
    "2.0.0",
    "10.0.0",
]


@pytest.mark.parametrize(
    "version",
    ["0.0.0", "1.2.3", "10.20.30", "1.0.0-alpha", "1.0.0-0.3.7", "1.0.0-x.7.z.92", "1.0.0-x-y-z.--"]
    + ["1.0.0+20130313144700", "1.0.0-beta+exp.sha.5114f85", "1.0.0+21AF26D3----117B344092BD"],
)
def test_valid_versions(version):
    assert semver.is_valid(version) is True


@pytest.mark.parametrize(
    "version",
    ["", "1", "1.2", "1.2.3.4", "v1.2.3", "01.2.3", "1.02.3", "1.2.3-", "1.2.3-01", "1.2.3+"]
    + ["1.2.3-a..b", "1.2.3 ", "latest", "1.2.x", "١.٢.٣", "1." * 200 + "1"],
)
def test_invalid_versions(version):
    assert semver.is_valid(version) is False


def test_the_order_is_the_specifications():
    for lower, higher in pairwise(PRECEDENCE):
        assert semver.sort_key(lower) < semver.sort_key(higher), (lower, higher)


def test_sorting_is_by_precedence_not_by_text():
    shuffled = list(reversed(PRECEDENCE))

    assert semver.sorted_versions(shuffled) == PRECEDENCE
    assert semver.highest(shuffled) == "10.0.0"


def test_build_metadata_does_not_change_precedence():
    plain, built = semver.sort_key("1.0.0"), semver.sort_key("1.0.0+build.5")

    assert plain[:-1] == built[:-1]
    assert semver.sorted_versions(["1.0.0+b", "1.0.0+a", "1.0.0"]) == [
        "1.0.0",
        "1.0.0+a",
        "1.0.0+b",
    ]


def test_invalid_versions_sort_before_valid_ones_and_never_fail():
    odd = ["latest", "", "1.2", "v9.9.9", "١.٢.٣"]

    ordered = semver.sorted_versions([*odd, "0.0.1"])

    assert ordered[-1] == "0.0.1"
    assert set(ordered[:-1]) == set(odd)


def test_the_highest_of_nothing_is_nothing():
    assert semver.highest([]) is None
    assert semver.sorted_versions(["1.0.0", "1.0.0"]) == ["1.0.0"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm -q`
Expected: collection errors, `No module named 'megooarti.repositories.npm'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/npm/__init__.py`:

```python
"""The npm format."""
```

`backend/src/megooarti/repositories/npm/paths.py`:

```python
"""npm registry paths: what a request path means, and which package it names.

Pure functions. A package is `name` or `@scope/name`; everything under `-/` is the
registry's own API.
"""

import re
from dataclasses import dataclass

MAX_NAME_LENGTH = 214
_LOGIN_PREFIX = "org.couchdb.user:"
# One part of a name: URL-safe characters, not starting with a dot or an underscore.
_PART = re.compile(r"[A-Za-z0-9~-][A-Za-z0-9._~-]*")


@dataclass(frozen=True)
class NpmPath:
    """A path, classified. Fields that do not apply to its kind are left empty."""

    # document, version, tarball, dist_tags, login, logout, whoami, ping, search or other
    kind: str
    package: str = ""  # the full name: `name` or `@scope/name`
    version: str = ""  # version: the version or tag asked for; tarball: its version
    filename: str = ""  # tarball
    tag: str = ""  # dist_tags: the tag, if one is named
    username: str = ""  # login
    token: str = ""  # logout

    @property
    def scope(self) -> str:
        """The scope without its `@`, or "" for an unscoped package."""
        return scope_of(self.package)

    @property
    def name(self) -> str:
        """The name without its scope."""
        return unscoped(self.package)


_OTHER = NpmPath("other")


def scope_of(package: str) -> str:
    return package[1:].partition("/")[0] if package.startswith("@") else ""


def unscoped(package: str) -> str:
    return package.rpartition("/")[2]


def is_valid_name(package: str) -> bool:
    """Whether this can be a package name. Upper case is allowed: old packages have it."""
    if not package or len(package) > MAX_NAME_LENGTH:
        return False
    if package.startswith("@"):
        scope, slash, name = package[1:].partition("/")
        return bool(slash) and bool(_PART.fullmatch(scope)) and bool(_PART.fullmatch(name))
    return bool(_PART.fullmatch(package))


def tarball_filename(package: str, version: str) -> str:
    return f"{unscoped(package)}-{version}.tgz"


def tarball_path(package: str, version: str) -> str:
    """Where a version's tarball is stored, and requested."""
    return f"{package}/-/{tarball_filename(package, version)}"


def dist_tags_path(package: str) -> str:
    """Where a hosted repository keeps a package's dist-tags."""
    return f"-/package/{package}/dist-tags"


def _split_package(segments: list[str]) -> tuple[str, list[str]] | None:
    """The package a path starts with, and what follows it."""
    if not segments:
        return None
    count = 2 if segments[0].startswith("@") else 1
    package = "/".join(segments[:count])
    if len(segments) < count or not is_valid_name(package):
        return None
    return package, segments[count:]


def _without_revision(rest: list[str]) -> list[str]:
    """Drop a trailing `-rev/<rev>`: the revision is accepted and not used."""
    return rest[:-2] if len(rest) >= 2 and rest[-2] == "-rev" else rest


def _registry(segments: list[str]) -> NpmPath:
    if segments == ["ping"]:
        return NpmPath("ping")
    if segments == ["whoami"]:
        return NpmPath("whoami")
    if segments == ["v1", "search"]:
        return NpmPath("search")
    if segments[:1] == ["user"]:
        rest = _without_revision(segments[1:])
        if len(rest) == 1 and rest[0].startswith(_LOGIN_PREFIX):
            username = rest[0].removeprefix(_LOGIN_PREFIX)
            return NpmPath("login", username=username) if username else _OTHER
        if len(rest) == 2 and rest[0] == "token":
            return NpmPath("logout", token=rest[1])
        return _OTHER
    if segments[:1] == ["package"]:
        found = _split_package(segments[1:])
        if found is None:
            return _OTHER
        package, rest = found
        if rest == ["dist-tags"]:
            return NpmPath("dist_tags", package=package)
        if len(rest) == 2 and rest[0] == "dist-tags":
            return NpmPath("dist_tags", package=package, tag=rest[1])
    return _OTHER


def classify(path: str) -> NpmPath:
    """What a request path is."""
    segments = path.split("/")
    if segments[0] == "-":
        return _registry(segments[1:])
    found = _split_package(segments)
    if found is None:
        return _OTHER
    package, rest = found
    rest = _without_revision(rest)
    if not rest:
        return NpmPath("document", package=package)
    if rest[0] == "-":
        prefix = f"{unscoped(package)}-"
        if len(rest) != 2 or not rest[1].startswith(prefix) or not rest[1].endswith(".tgz"):
            return _OTHER
        version = rest[1][len(prefix) : -len(".tgz")]
        if not version:
            return _OTHER
        return NpmPath("tarball", package=package, version=version, filename=rest[1])
    if len(rest) == 1:
        return NpmPath("version", package=package, version=rest[0])
    return _OTHER
```

`backend/src/megooarti/repositories/npm/semver.py`:

```python
"""Semantic Versioning 2.0.0: which versions are valid, and their order.

Pure functions, written from https://semver.org/spec/v2.0.0.html.
"""

import re
from collections.abc import Iterable

_NUMBER = r"(?:0|[1-9][0-9]*)"
_IDENTIFIER = rf"(?:{_NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
_SEMVER = re.compile(
    rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})"
    rf"(?:-({_IDENTIFIER}(?:\.{_IDENTIFIER})*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
# No real version is longer, and a bound keeps the numbers small enough to compare.
_MAX_LENGTH = 256

Key = tuple


def is_valid(version: str) -> bool:
    return len(version) <= _MAX_LENGTH and _SEMVER.fullmatch(version) is not None


def sort_key(version: str) -> Key:
    """A key that orders versions by precedence. Invalid versions come before valid ones.

    Build metadata does not count. Versions equal in precedence are ordered by their
    text, so the order is always the same.
    """
    match = _SEMVER.fullmatch(version) if len(version) <= _MAX_LENGTH else None
    if match is None:
        return (0, version)
    major, minor, patch, prerelease = match.groups()
    if prerelease is None:
        ranked: tuple = (1,)  # a release comes after every pre-release of it
    else:
        # Numeric identifiers are lower than alphanumeric ones, and compare as numbers.
        ranked = (
            0,
            tuple(
                (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier)
                for identifier in prerelease.split(".")
            ),
        )
    return (1, int(major), int(minor), int(patch), ranked, version)


def sorted_versions(versions: Iterable[str]) -> list[str]:
    """Distinct versions, lowest first."""
    return sorted(set(versions), key=sort_key)


def highest(versions: Iterable[str]) -> str | None:
    """The highest version, or None if there are none."""
    return max(versions, key=sort_key, default=None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/npm -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/npm backend/tests/repositories/npm
git commit -m "feat(npm): classify registry paths, and order versions by SemVer"
```

---

### Task 5: npm package documents

**Files:**
- Create: `backend/src/megooarti/repositories/npm/documents.py`
- Test: `backend/tests/repositories/npm/test_documents.py`

**Interfaces:**
- Consumes: `paths.tarball_path`, `paths.tarball_filename`, `semver`.
- Produces, in `megooarti.repositories.npm.documents`:
  - Exceptions `InvalidPackage` and `ChecksumMismatch`; their message completes a sentence.
  - Dataclasses `Release(version, manifest, data)`, `Upload(document, releases, tags)`, `Version(version, manifest, created, modified)`, `Rendered(data, etag, modified)`, `Update(deprecations, removals)`, `Found(name, version, description, date)`.
  - `dumps(value) -> bytes`, `loads(raw) -> Any` (raises `InvalidPackage`), `iso(moment) -> str`.
  - `read_upload(package, raw) -> Upload` — raises `InvalidPackage`, or `ChecksumMismatch("length")`.
  - `verify(manifest, *, sha1, sha256, sha512) -> None` — raises `ChecksumMismatch`.
  - `stored_manifest(manifest, *, sha1, sha512) -> dict`.
  - `is_valid_tag(tag) -> bool`; `effective_tags(stored, versions) -> dict`; `merge_tags(stored, incoming, before, after) -> dict`.
  - `document(package, versions, tags, base) -> dict | None`; `render(package, versions, tags, base) -> Rendered | None`; `manifest_of(built, wanted) -> dict | None`.
  - `update_plan(stored, sent) -> Update`; `deprecated(manifest, message) -> dict`.
  - `search_results(found, total, now) -> dict`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/repositories/npm/test_documents.py`:

```python
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from megooarti.repositories.npm import documents
from megooarti.repositories.npm.documents import (
    ChecksumMismatch,
    Found,
    InvalidPackage,
    Version,
)

TARBALL = b"\x1f\x8b not really a tarball"
SHA1 = hashlib.sha1(TARBALL).hexdigest()
SHA256 = hashlib.sha256(TARBALL).hexdigest()
SHA512 = hashlib.sha512(TARBALL).hexdigest()
INTEGRITY = "sha512-" + base64.b64encode(hashlib.sha512(TARBALL).digest()).decode()
T1 = datetime(2026, 10, 8, 10, 15, 0, 123456, tzinfo=UTC)
T2 = T1 + timedelta(hours=1)
BASE = "https://repo.example/repository/npm"


def manifest(package: str = "left-pad", version: str = "1.0.0", **extra) -> dict:
    dist = {"shasum": SHA1, "integrity": INTEGRITY, "tarball": "http://client.example/x.tgz"}
    return {"name": package, "version": version, "dist": dist, **extra}


def publish(package: str = "left-pad", version: str = "1.0.0", **changes) -> dict:
    """What `npm publish` sends for one version."""
    body = {
        "_id": package,
        "name": package,
        "dist-tags": {"latest": version},
        "versions": {version: manifest(package, version)},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(TARBALL).decode(),
                "length": len(TARBALL),
            }
        },
    }
    body.update(changes)
    return body


def read(body, package: str = "left-pad"):
    return documents.read_upload(package, json.dumps(body).encode())


def stored(version: str, when: datetime = T1, **extra) -> Version:
    kept = documents.stored_manifest(manifest(version=version, **extra), sha1=SHA1, sha512=SHA512)
    return Version(version=version, manifest=kept, created=when, modified=when)


def test_a_publish_is_read_into_its_releases():
    upload = read(publish())

    assert [release.version for release in upload.releases] == ["1.0.0"]
    assert upload.releases[0].data == TARBALL
    assert upload.releases[0].manifest["name"] == "left-pad"
    assert upload.tags == {"latest": "1.0.0"}


def test_a_scoped_publish_names_its_tarball_with_or_without_the_scope():
    as_npm_sends = read(publish("@acme/widget"), "@acme/widget")
    body = publish("@acme/widget")
    body["_attachments"] = {"widget-1.0.0.tgz": body["_attachments"]["@acme/widget-1.0.0.tgz"]}

    assert as_npm_sends.releases[0].data == TARBALL
    assert read(body, "@acme/widget").releases[0].data == TARBALL


def test_a_body_without_attachments_is_an_update():
    body = publish()
    del body["_attachments"]

    upload = read(body)

    assert upload.releases == ()
    assert upload.document["versions"].keys() == {"1.0.0"}


def with_manifest(**changes) -> dict:
    body = publish()
    body["versions"]["1.0.0"].update(changes)
    return body


def with_attachment(**changes) -> dict:
    body = publish()
    body["_attachments"]["left-pad-1.0.0.tgz"].update(changes)
    return body


@pytest.mark.parametrize(
    "body",
    [
        [],
        "a string",
        publish(name="other"),
        publish(**{"dist-tags": ["latest"]}),
        publish(**{"dist-tags": {"": "1.0.0"}}),
        publish(**{"dist-tags": {"a/b": "1.0.0"}}),
        publish(**{"dist-tags": {"latest": 1}}),
        publish(versions={}),
        publish(versions=[]),
        publish(versions={"1.0.0": "not an object"}),
        publish(versions={"1.0": manifest(version="1.0")}),
        publish(versions={"1.0.0": manifest(version="2.0.0")}),
        publish(versions={"1.0.0": manifest(package="other")}),
        publish(_attachments={"other-1.0.0.tgz": {"data": "aGk="}}),
        publish(_attachments=["left-pad-1.0.0.tgz"]),
        with_attachment(data="not base64!"),
        with_attachment(data=None),
        with_manifest(readme="x" * (1024 * 1024)),
    ],
)
def test_a_body_that_is_not_a_package_is_refused(body):
    with pytest.raises(InvalidPackage):
        read(body)


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"\xff\xfe", b"[" * 100_000],
    ids=["empty", "text", "not-utf8", "nested-too-deeply"],
)
def test_a_body_that_is_not_json_is_refused(raw):
    with pytest.raises(InvalidPackage):
        documents.read_upload("left-pad", raw)


def test_a_tarball_shorter_than_declared_is_a_mismatch():
    with pytest.raises(ChecksumMismatch, match="length"):
        read(with_attachment(length=len(TARBALL) + 1))


def test_declared_digests_are_checked():
    actual = {"sha1": SHA1, "sha256": SHA256, "sha512": SHA512}
    sha256 = "sha256-" + base64.b64encode(hashlib.sha256(TARBALL).digest()).decode()

    documents.verify(manifest(), **actual)
    documents.verify({"dist": {"shasum": SHA1.upper()}}, **actual)
    documents.verify({"dist": {"integrity": f"md5-ignored {sha256} {INTEGRITY}"}}, **actual)
    documents.verify({"dist": {}}, **actual)
    documents.verify({}, **actual)
    documents.verify({"dist": "odd"}, **actual)


@pytest.mark.parametrize(
    ("dist", "check"),
    [
        ({"shasum": "0" * 40}, "shasum"),
        ({"integrity": "sha512-" + base64.b64encode(b"\x00" * 64).decode()}, "integrity"),
        ({"integrity": "sha512-not-base64!"}, "integrity"),
        (
            {"shasum": SHA1, "integrity": "sha1-" + base64.b64encode(b"\x00" * 20).decode()},
            "integrity",
        ),
    ],
)
def test_a_wrong_digest_is_a_mismatch(dist, check):
    with pytest.raises(ChecksumMismatch, match=check):
        documents.verify({"dist": dist}, sha1=SHA1, sha256=SHA256, sha512=SHA512)


def test_the_stored_manifest_has_our_digests_and_no_link():
    sent = manifest(
        description="pads", dist={"shasum": "f" * 40, "tarball": "http://x", "fileCount": 3}
    )

    kept = documents.stored_manifest(sent, sha1=SHA1, sha512=SHA512)

    assert kept["dist"] == {"fileCount": 3, "shasum": SHA1, "integrity": INTEGRITY}
    assert (kept["description"], kept["version"]) == ("pads", "1.0.0")
    assert sent["dist"]["shasum"] == "f" * 40  # what was sent is not changed


def test_tags_shown_point_at_versions_that_exist():
    stored_tags = {"latest": "1.0.0", "beta": "2.0.0-beta.1", "old": "0.1.0"}

    shown = documents.effective_tags(stored_tags, ["1.0.0", "2.0.0-beta.1"])

    assert shown == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}
    assert list(shown)[0] == "latest"


def test_latest_falls_back_to_the_highest_version():
    assert documents.effective_tags({}, ["1.0.0", "1.2.0", "1.1.0"]) == {"latest": "1.2.0"}
    assert documents.effective_tags({"latest": "9.9.9"}, ["1.0.0"]) == {"latest": "1.0.0"}
    assert documents.effective_tags({"latest": "1.0.0"}, []) == {}


def test_merging_tags_applies_what_was_sent():
    merged = documents.merge_tags(
        {"latest": "1.0.0"}, {"beta": "2.0.0-beta.1"}, ["1.0.0"], ["1.0.0", "2.0.0-beta.1"]
    )

    assert merged == {"latest": "1.0.0", "beta": "2.0.0-beta.1"}


def test_latest_does_not_jump_to_a_prerelease_because_its_version_was_removed_earlier():
    # 2.0.0 was tagged latest and has been removed; 1.0.0 remains. A beta is published.
    merged = documents.merge_tags(
        {"latest": "2.0.0"}, {"beta": "3.0.0-beta.1"}, ["1.0.0"], ["1.0.0", "3.0.0-beta.1"]
    )

    assert merged == {"latest": "1.0.0", "beta": "3.0.0-beta.1"}


def test_the_first_publish_decides_latest():
    assert documents.merge_tags({}, {"next": "1.0.0-rc.1"}, [], ["1.0.0-rc.1"]) == {
        "latest": "1.0.0-rc.1",
        "next": "1.0.0-rc.1",
    }


def test_the_package_document():
    built = documents.document(
        "left-pad",
        [stored("1.10.0", T2, description="newer"), stored("1.9.0", T1, description="older")],
        {"latest": "1.10.0"},
        BASE,
    )

    assert (built["_id"], built["name"]) == ("left-pad", "left-pad")
    assert list(built["versions"]) == ["1.9.0", "1.10.0"]
    assert built["dist-tags"] == {"latest": "1.10.0"}
    newest = built["versions"]["1.10.0"]
    assert newest["_id"] == "left-pad@1.10.0"
    assert newest["dist"] == {
        "shasum": SHA1,
        "integrity": INTEGRITY,
        "tarball": f"{BASE}/left-pad/-/left-pad-1.10.0.tgz",
    }
    assert built["time"] == {
        "created": "2026-10-08T10:15:00.123Z",
        "modified": "2026-10-08T11:15:00.123Z",
        "1.9.0": "2026-10-08T10:15:00.123Z",
        "1.10.0": "2026-10-08T11:15:00.123Z",
    }
    assert built["description"] == "newer"  # copied from the latest version
    assert built["_rev"].startswith("2-")


def test_a_scoped_document_links_to_the_scoped_path():
    kept = documents.stored_manifest(manifest("@acme/widget"), sha1=SHA1, sha512=SHA512)
    built = documents.document("@acme/widget", [Version("1.0.0", kept, T1, T1)], {}, BASE)

    assert (
        built["versions"]["1.0.0"]["dist"]["tarball"] == f"{BASE}/@acme/widget/-/widget-1.0.0.tgz"
    )
    assert built["versions"]["1.0.0"]["_id"] == "@acme/widget@1.0.0"


def test_a_package_without_versions_has_no_document():
    assert documents.document("left-pad", [], {"latest": "1.0.0"}, BASE) is None
    assert documents.render("left-pad", [], {}, BASE) is None


def test_the_revision_changes_with_the_document():
    one = documents.document("left-pad", [stored("1.0.0")], {}, BASE)
    same = documents.document("left-pad", [stored("1.0.0")], {}, BASE)
    deprecated = documents.document("left-pad", [stored("1.0.0", deprecated="no")], {}, BASE)

    assert one["_rev"] == same["_rev"]
    assert one["_rev"] != deprecated["_rev"]


def test_rendering_gives_bytes_an_etag_and_a_time():
    rendered = documents.render("left-pad", [stored("1.0.0", T1), stored("1.1.0", T2)], {}, BASE)

    assert json.loads(rendered.data)["dist-tags"] == {"latest": "1.1.0"}
    assert rendered.etag == hashlib.sha256(rendered.data).hexdigest()
    assert rendered.modified == T2


def test_one_manifest_by_version_or_by_tag():
    built = documents.document(
        "left-pad", [stored("1.0.0"), stored("1.1.0")], {"old": "1.0.0"}, BASE
    )

    assert documents.manifest_of(built, "1.0.0")["version"] == "1.0.0"
    assert documents.manifest_of(built, "latest")["version"] == "1.1.0"
    assert documents.manifest_of(built, "old")["version"] == "1.0.0"
    assert documents.manifest_of(built, "9.9.9") is None


def test_an_update_names_what_was_deprecated_and_what_was_removed():
    held = {
        "1.0.0": {"version": "1.0.0"},
        "1.1.0": {"version": "1.1.0", "deprecated": "old"},
        "1.2.0": {"version": "1.2.0", "deprecated": "keep"},
        "2.0.0": {"version": "2.0.0"},
    }
    sent = {
        "versions": {
            "1.0.0": {"deprecated": "use 2"},
            "1.1.0": {"deprecated": ""},
            "1.2.0": {"deprecated": "keep", "description": "ignored"},
            "3.0.0": {"note": "a version we do not hold is ignored"},
        }
    }

    plan = documents.update_plan(held, sent)

    assert plan.deprecations == {"1.0.0": "use 2", "1.1.0": None}
    assert plan.removals == ("2.0.0",)


def test_an_update_that_says_nothing_about_versions_removes_nothing():
    held = {"1.0.0": {"version": "1.0.0"}}

    assert documents.update_plan(held, {}).removals == ()
    assert documents.update_plan(held, {"versions": None}).removals == ()
    assert documents.update_plan(held, {"versions": {}}).removals == ("1.0.0",)


def test_a_deprecation_message_has_a_limit():
    with pytest.raises(InvalidPackage):
        documents.update_plan({"1.0.0": {}}, {"versions": {"1.0.0": {"deprecated": "x" * 1025}}})


def test_setting_and_clearing_a_deprecation():
    kept = {"version": "1.0.0", "deprecated": "old"}

    assert documents.deprecated(kept, "new") == {"version": "1.0.0", "deprecated": "new"}
    assert documents.deprecated(kept, None) == {"version": "1.0.0"}
    assert kept == {"version": "1.0.0", "deprecated": "old"}


def test_search_results_are_in_the_shape_npm_reads():
    found = [Found("@acme/widget", "2.0.0", "A widget", T1), Found("left-pad", "1.3.0", "", T2)]

    results = documents.search_results(found, 7, T2)

    assert results["total"] == 7
    assert [entry["package"]["name"] for entry in results["objects"]] == [
        "@acme/widget",
        "left-pad",
    ]
    first = results["objects"][0]["package"]
    assert (first["version"], first["description"]) == ("2.0.0", "A widget")
    assert first["date"] == "2026-10-08T10:15:00.123Z"
    assert (first["keywords"], first["maintainers"]) == ([], [])


@pytest.mark.parametrize(
    ("tag", "valid"),
    [
        ("latest", True),
        ("next-11", True),
        ("", False),
        ("a/b", False),
        ("x" * 215, False),
        ("a\nb", False),
    ],
)
def test_tag_names(tag, valid):
    assert documents.is_valid_tag(tag) is valid
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm/test_documents.py -q`
Expected: collection error, `cannot import name 'documents' from 'megooarti.repositories.npm'`.

- [ ] **Step 3: Implement**

`backend/src/megooarti/repositories/npm/documents.py`:

```python
"""npm package documents: read what a client sends, and build what a client reads.

Pure functions: no database, no files, no clock.
"""

import base64
import binascii
import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from megooarti.repositories.npm import paths, semver

# A manifest is stored with its component and repeated in every package document.
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_DEPRECATION_LENGTH = 1024
_MAX_TAG_LENGTH = 214
# What the package document repeats at the top from the latest version's manifest.
_COPIED = (
    "description",
    "readme",
    "license",
    "repository",
    "homepage",
    "keywords",
    "author",
    "maintainers",
    "bugs",
)
# The digests a blob store computes, by the names npm's `integrity` uses.
_INTEGRITY = ("sha1", "sha256", "sha512")


class InvalidPackage(Exception):
    """What was sent is not a package this registry can take. The message says why."""


class ChecksumMismatch(Exception):
    """A tarball is not the one its manifest describes. The message names the check."""


@dataclass(frozen=True)
class Release:
    """One version in a publish: its manifest and its tarball."""

    version: str
    manifest: dict[str, Any]
    data: bytes


@dataclass(frozen=True)
class Upload:
    """A body sent to a package's address. `releases` is empty when it is an update."""

    document: dict[str, Any]
    releases: tuple[Release, ...]
    tags: dict[str, str] | None  # the dist-tags it carries, if it carries any


@dataclass(frozen=True)
class Version:
    """A stored version: its manifest, and when it was published and last changed."""

    version: str
    manifest: dict[str, Any]
    created: datetime
    modified: datetime


@dataclass(frozen=True)
class Rendered:
    """A document as bytes, with what a response needs to say about it."""

    data: bytes
    etag: str
    modified: datetime


@dataclass(frozen=True)
class Update:
    """What an update asks for, compared with what is stored."""

    deprecations: dict[str, str | None]  # version -> the new message, or None to clear it
    removals: tuple[str, ...]


@dataclass(frozen=True)
class Found:
    """One search result."""

    name: str
    version: str
    description: str
    date: datetime


def dumps(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


def loads(raw: bytes) -> Any:
    """Parse JSON a client sent. Raises InvalidPackage."""
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        raise InvalidPackage("the body is not JSON") from None


def iso(moment: datetime) -> str:
    """A time as npm writes it: 2026-10-08T10:15:00.000Z."""
    moment = moment.astimezone(UTC)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


def _tags(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidPackage("dist-tags is not an object")
    for tag, version in value.items():
        if not is_valid_tag(tag) or not isinstance(version, str):
            raise InvalidPackage(f"the dist-tag {tag!r} is not valid")
    return dict(value)


def is_valid_tag(tag: str) -> bool:
    return 0 < len(tag) <= _MAX_TAG_LENGTH and "/" not in tag and tag.isprintable()


def _attachment(attachments: dict[str, Any], package: str, version: str) -> bytes:
    """The tarball sent for a version. npm names it with the scope; others without."""
    names = (f"{package}-{version}.tgz", paths.tarball_filename(package, version))
    found = next((attachments[name] for name in names if name in attachments), None)
    if not isinstance(found, dict) or not isinstance(found.get("data"), str):
        raise InvalidPackage(f"there is no tarball for version {version}")
    try:
        data = base64.b64decode(found["data"], validate=True)
    except (binascii.Error, ValueError):
        raise InvalidPackage(f"the tarball for version {version} is not base64") from None
    length = found.get("length")
    if isinstance(length, int) and not isinstance(length, bool) and length != len(data):
        raise ChecksumMismatch("length")
    return data


def read_upload(package: str, raw: bytes) -> Upload:
    """Read and check a body sent to a package's address.

    Raises InvalidPackage, or ChecksumMismatch if a tarball is not as long as declared.
    """
    document = loads(raw)
    if not isinstance(document, dict):
        raise InvalidPackage("the body is not an object")
    if document.get("name") != package:
        raise InvalidPackage("its name is not the package it was sent to")
    tags = _tags(document.get("dist-tags"))
    attachments = document.get("_attachments")
    if not attachments:
        return Upload(document=document, releases=(), tags=tags)

    versions = document.get("versions")
    if not isinstance(attachments, dict) or not isinstance(versions, dict) or not versions:
        raise InvalidPackage("it has attachments but no versions")
    releases = []
    for version, manifest in versions.items():
        if not semver.is_valid(version):
            raise InvalidPackage(f"{version!r} is not a valid version")
        if not isinstance(manifest, dict):
            raise InvalidPackage(f"the manifest of version {version} is not an object")
        if manifest.get("name") != package or manifest.get("version") != version:
            raise InvalidPackage(f"the manifest of version {version} names something else")
        if len(dumps(manifest)) > MAX_MANIFEST_BYTES:
            raise InvalidPackage(f"the manifest of version {version} is larger than 1 MiB")
        data = _attachment(attachments, package, version)
        releases.append(Release(version=version, manifest=manifest, data=data))
    return Upload(document=document, releases=tuple(releases), tags=tags)


def _hex_of(encoded: str) -> str | None:
    try:
        return base64.b64decode(encoded, validate=True).hex()
    except (binascii.Error, ValueError):
        return None


def verify(manifest: Mapping[str, Any], *, sha1: str, sha256: str, sha512: str) -> None:
    """Check a tarball's digests against what its manifest declares. Raises ChecksumMismatch.

    Only what is declared is checked, and only in the algorithms a blob store computes.
    """
    actual = {"sha1": sha1, "sha256": sha256, "sha512": sha512}
    dist = manifest.get("dist")
    if not isinstance(dist, dict):
        return
    shasum = dist.get("shasum")
    if isinstance(shasum, str) and shasum.lower() != sha1:
        raise ChecksumMismatch("shasum")
    integrity = dist.get("integrity")
    for entry in integrity.split() if isinstance(integrity, str) else ():
        algorithm, _, encoded = entry.partition("-")
        if algorithm in _INTEGRITY and _hex_of(encoded) != actual[algorithm]:
            raise ChecksumMismatch("integrity")


def stored_manifest(manifest: Mapping[str, Any], *, sha1: str, sha512: str) -> dict[str, Any]:
    """A manifest as it is kept: without its link, and with the digests computed here."""
    dist = manifest.get("dist")
    kept = {} if not isinstance(dist, dict) else {k: v for k, v in dist.items() if k != "tarball"}
    kept["shasum"] = sha1
    kept["integrity"] = "sha512-" + base64.b64encode(bytes.fromhex(sha512)).decode()
    return {**manifest, "dist": kept}


def effective_tags(stored: Mapping[str, str], versions: Collection[str]) -> dict[str, str]:
    """The dist-tags to show: those that point at a version that exists, and `latest`.

    If nothing valid is tagged `latest`, the highest version is.
    """
    latest = stored.get("latest")
    if latest not in versions:
        latest = semver.highest(versions)
    if latest is None:
        return {}
    others = {
        tag: stored[tag] for tag in sorted(stored) if tag != "latest" and stored[tag] in versions
    }
    return {"latest": latest, **others}


def merge_tags(
    stored: Mapping[str, str],
    incoming: Mapping[str, str] | None,
    before: Collection[str],
    after: Collection[str],
) -> dict[str, str]:
    """The dist-tags to keep after a change.

    `before` and `after` are the versions that existed before it and exist after it.
    The stored tags are first made true of `before`, so that `latest` does not jump to
    a version only because the one it named was removed earlier.
    """
    merged = effective_tags(stored, before)
    merged.update(incoming or {})
    return effective_tags(merged, after)


def _shown(package: str, version: Version, base: str) -> dict[str, Any]:
    """A stored manifest as a client sees it, with its identity and its link."""
    manifest = dict(version.manifest)
    dist = manifest.get("dist")
    link = f"{base}/{paths.tarball_path(package, version.version)}"
    manifest["_id"] = f"{package}@{version.version}"
    manifest["dist"] = {**(dist if isinstance(dist, dict) else {}), "tarball": link}
    return manifest


def document(
    package: str, versions: Sequence[Version], tags: Mapping[str, str], base: str
) -> dict[str, Any] | None:
    """The package document, or None if the package has no version.

    `base` is the public address of the repository; tarball links are built on it.
    """
    if not versions:
        return None
    ordered = sorted(versions, key=lambda version: semver.sort_key(version.version))
    shown = {version.version: _shown(package, version, base) for version in ordered}
    shown_tags = effective_tags(tags, shown)
    built: dict[str, Any] = {
        "_id": package,
        "name": package,
        "dist-tags": shown_tags,
        "versions": shown,
        "time": {
            "created": iso(min(version.created for version in ordered)),
            "modified": iso(max(version.modified for version in ordered)),
            **{version.version: iso(version.created) for version in ordered},
        },
    }
    latest = shown[shown_tags["latest"]]
    built.update({field: latest[field] for field in _COPIED if field in latest})
    # It changes whenever the document does. It is accepted back and not checked.
    built["_rev"] = f"{len(shown)}-{hashlib.sha1(dumps(built)).hexdigest()[:32]}"
    return built


def render(
    package: str, versions: Sequence[Version], tags: Mapping[str, str], base: str
) -> Rendered | None:
    """The package document as bytes, or None if the package has no version."""
    built = document(package, versions, tags, base)
    if built is None:
        return None
    data = dumps(built)
    return Rendered(
        data=data,
        etag=hashlib.sha256(data).hexdigest(),
        modified=max(version.modified for version in versions),
    )


def manifest_of(built: Mapping[str, Any], wanted: str) -> dict[str, Any] | None:
    """One version's manifest from a package document, by version or by dist-tag."""
    version = built["dist-tags"].get(wanted, wanted)
    return built["versions"].get(version)


def update_plan(stored: Mapping[str, Mapping[str, Any]], sent: Mapping[str, Any]) -> Update:
    """What a document sent back without attachments changes: deprecations and removals.

    `stored` maps each version held to its manifest. Raises InvalidPackage.
    """
    versions = sent.get("versions")
    if not isinstance(versions, dict):
        return Update(deprecations={}, removals=())  # nothing is removed by saying nothing
    deprecations: dict[str, str | None] = {}
    for version, manifest in stored.items():
        theirs = versions.get(version)
        if not isinstance(theirs, dict):
            continue
        message = theirs.get("deprecated")
        new = message if isinstance(message, str) and message else None  # "" clears it
        if new is not None and len(new) > MAX_DEPRECATION_LENGTH:
            raise InvalidPackage("a deprecation message is longer than 1024 characters")
        if new != (manifest.get("deprecated") or None):
            deprecations[version] = new
    removals = tuple(version for version in stored if version not in versions)
    return Update(deprecations=deprecations, removals=removals)


def deprecated(manifest: Mapping[str, Any], message: str | None) -> dict[str, Any]:
    """A manifest with its deprecation message set, or removed."""
    changed = {key: value for key, value in manifest.items() if key != "deprecated"}
    if message is not None:
        changed["deprecated"] = message
    return changed


def search_results(found: Sequence[Found], total: int, now: datetime) -> dict[str, Any]:
    """Search results in the shape `npm search` reads."""
    objects = [
        {
            "package": {
                "name": entry.name,
                "version": entry.version,
                "description": entry.description,
                "date": iso(entry.date),
                "keywords": [],
                "maintainers": [],
                "links": {},
            },
            "score": {"final": 1, "detail": {"quality": 1, "popularity": 1, "maintenance": 1}},
            "searchScore": 1,
        }
        for entry in found
    ]
    return {"objects": objects, "total": total, "time": iso(now)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories/npm -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/megooarti/repositories/npm/documents.py backend/tests/repositories/npm/test_documents.py
git commit -m "feat(npm): read a publish, and build package documents"
```

---

### Task 6: Hosted npm repositories

**Files:**
- Create: `backend/src/megooarti/repositories/npm/format.py`
- Modify: `backend/src/megooarti/main.py`
- Create: `backend/tests/repositories/npm/conftest.py`
- Test: `backend/tests/repositories/npm/test_sign_in.py`
- Test: `backend/tests/repositories/npm/test_hosted_publish.py`
- Test: `backend/tests/repositories/npm/test_hosted_changes.py`
- Test: `backend/tests/repositories/npm/test_search.py`
- Test: `backend/tests/repositories/npm/test_races.py`

**Interfaces:**
- Consumes: everything Tasks 1 to 5 produce; `context.maintain`, `context.require_write`, `context.receive`, `context.read`, `context.release`, `context.respond`, `context.delete`.
- Produces, in `megooarti.repositories.npm.format`:
  - `NpmFormat`, registered as `"npm"`, with `types == frozenset({"hosted"})`.
  - `await registry_endpoint(context, request, parsed) -> Response | None` — sign-in, sign-out, `whoami` and `ping`; `None` for any other path. Plan 5b calls it from the proxy and group handlers.
  - `await built(context, request, package) -> tuple[list[Version], dict, str] | None` — what a hosted package's document is made of. Plan 5b's group handler uses it.
  - `await off_loop(function, *arguments)`; constants `SMALL_LIMIT`, `TAGS_LIMIT`.
  - Test helpers in `tests/repositories/npm/conftest.py`: `URL`, `create(db, name, *, hosted=None)`, `tarball_of(package, version)`, `publish_body(package, version, *, tag="latest", **manifest)`, `address(package, repository="npm")`, `publish(client, headers, package, version, **changes)`, and the fixtures `registry` and `root`.

- [ ] **Step 1: Write the test helpers**

`backend/tests/repositories/npm/conftest.py`:

```python
import base64
import hashlib

import pytest

from megooarti.repositories import service
from megooarti.repositories.models import Repository
from tests.accounts import PASSWORD, basic

URL = "/repository/npm"


async def create(db, name: str, *, hosted: dict | None = None) -> Repository:
    """A hosted npm repository, committed."""
    repository = await service.create_repository(
        db,
        name=name,
        format="npm",
        type="hosted",
        online=True,
        blob_store="default",
        hosted=hosted,
        format_config={},
    )
    await db.commit()
    return repository


def tarball_of(package: str, version: str) -> bytes:
    """Stand-in tarball bytes, different for every package and version."""
    return f"\x1f\x8b tarball of {package}@{version}".encode()


def publish_body(package: str, version: str, *, tag: str = "latest", **manifest) -> dict:
    """What `npm publish` sends for one version."""
    data = tarball_of(package, version)
    dist = {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": f"http://client.example/{package}/-/{package}-{version}.tgz",
    }
    return {
        "_id": package,
        "name": package,
        "dist-tags": {tag: version},
        "versions": {version: {"name": package, "version": version, "dist": dist, **manifest}},
        "_attachments": {
            f"{package}-{version}.tgz": {
                "content_type": "application/octet-stream",
                "data": base64.b64encode(data).decode(),
                "length": len(data),
            }
        },
    }


def address(package: str, repository: str = "npm") -> str:
    """A package's address as npm writes it: a scoped name has its slash encoded."""
    return f"/repository/{repository}/{package.replace('/', '%2f')}"


async def publish(client, headers, package: str, version: str, **changes):
    """Publish one version. Returns the response."""
    repository = changes.pop("repository", "npm")
    body = publish_body(package, version, **changes)
    return await client.put(address(package, repository), json=body, headers=headers)


@pytest.fixture
async def registry(db) -> Repository:
    return await create(db, "npm")


@pytest.fixture
async def root(make_user) -> dict[str, str]:
    await make_user("root", roles=["admin"])
    return basic("root", PASSWORD)
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/repositories/npm/test_sign_in.py`:

```python
from sqlalchemy import select

from megooarti.security.models import ApiToken
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, bearer, error_code
from tests.repositories.npm.conftest import URL

LOGIN = f"{URL}/-/user/org.couchdb.user:dana"
WHOAMI = f"{URL}/-/whoami"


def credentials(name: str = "dana", password: str = PASSWORD) -> dict:
    """What `npm login` sends."""
    return {"_id": f"org.couchdb.user:{name}", "name": name, "password": password, "type": "user"}


async def sign_in(client, name: str = "dana", password: str = PASSWORD) -> str:
    response = await client.put(
        f"{URL}/-/user/org.couchdb.user:{name}", json=credentials(name, password)
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


async def test_signing_in_gives_a_token_that_works(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    response = await client.put(LOGIN, json=credentials())

    body = response.json()
    assert response.status_code == 201
    assert (body["ok"], body["id"]) == (True, "org.couchdb.user:dana")
    assert body["token"].startswith("mga_")
    who = await client.get(WHOAMI, headers=bearer(body["token"]))
    assert (who.status_code, who.json()) == (200, {"username": "dana"})


async def test_the_token_is_one_of_the_users_tokens(client, registry, make_user, db):
    await make_user("dana", roles=["admin"])

    await sign_in(client)

    names = list(await db.scalars(select(ApiToken.name)))
    assert len(names) == 1
    assert names[0].startswith("npm login ")


async def test_an_api_token_can_be_given_as_the_password(
    client, registry, make_user, make_token, db
):
    dana = await make_user("dana", roles=["admin"])
    token = await make_token(dana)

    returned = await sign_in(client, password=token)

    assert returned == token
    assert len(list(await db.scalars(select(ApiToken.id)))) == 1  # no second token was made


async def test_wrong_credentials_are_refused(client, registry, make_user, db):
    await make_user("dana", roles=["admin"])

    wrong = await client.put(LOGIN, json=credentials(password="not the password"))
    unknown = await client.put(f"{URL}/-/user/org.couchdb.user:nobody", json=credentials("nobody"))

    assert (wrong.status_code, error_code(wrong)) == (401, "unauthorized")
    assert (unknown.status_code, error_code(unknown)) == (401, "unauthorized")
    assert list(await db.scalars(select(ApiToken.id))) == []


async def test_repeated_failures_are_throttled_like_any_sign_in(client, registry, make_user, app):
    await make_user("dana", roles=["admin"])
    allowed = app.state.settings.login_max_failures

    statuses = []
    for _ in range(allowed + 1):
        response = await client.put(LOGIN, json=credentials(password="guess"))
        statuses.append(response.status_code)
    even_the_right_one = await client.put(LOGIN, json=credentials())

    assert statuses == [401] * allowed + [429]
    assert (even_the_right_one.status_code, error_code(even_the_right_one)) == (
        429,
        "too_many_attempts",
    )


async def test_a_user_who_must_change_their_password_gets_no_token(client, registry, make_user, db):
    await make_user("dana", roles=["admin"], must_change_password=True)

    response = await client.put(LOGIN, json=credentials())

    assert (response.status_code, error_code(response)) == (403, "password_change_required")
    assert list(await db.scalars(select(ApiToken.id))) == []


async def test_a_sign_in_must_be_what_npm_sends(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    another_name = await client.put(LOGIN, json=credentials("root"))
    no_password = await client.put(LOGIN, json={"name": "dana"})
    not_json = await client.put(LOGIN, content=b"name=dana&password=x")
    not_an_object = await client.put(LOGIN, json=["dana", PASSWORD])
    too_large = await client.put(LOGIN, json={**credentials(), "padding": "x" * 20_000})

    for response in (another_name, no_password, not_json, not_an_object):
        assert (response.status_code, error_code(response)) == (400, "invalid_package")
    assert (too_large.status_code, error_code(too_large)) == (413, "payload_too_large")


async def test_signing_in_is_the_only_request_taken_without_credentials(
    client, registry, make_user
):
    await make_user("dana", roles=["admin"])
    token = await sign_in(client)

    attempts = [
        await client.put(f"{URL}/left-pad", json={"name": "left-pad"}),
        await client.put(f"{URL}/-/package/left-pad/dist-tags/beta", json="1.0.0"),
        await client.delete(f"{URL}/-/user/token/{token}"),
        await client.delete(LOGIN),
        await client.post(LOGIN, json=credentials()),
        await client.post(f"{URL}/-/v1/login", json={}),
        await client.get(LOGIN),
        await client.get(WHOAMI),
    ]

    assert [response.status_code for response in attempts] == [401] * len(attempts)
    assert (await client.get(WHOAMI, headers=bearer(token))).status_code == 200


async def test_a_sign_in_from_another_site_is_refused(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    response = await client.put(LOGIN, json=credentials(), headers={"Sec-Fetch-Site": "cross-site"})

    assert (response.status_code, error_code(response)) == (403, "cross_site_request")


async def test_signing_out_revokes_the_token(client, registry, make_user):
    await make_user("dana", roles=["admin"])
    token = await sign_in(client)

    response = await client.delete(f"{URL}/-/user/token/{token}", headers=bearer(token))

    assert (response.status_code, response.json()) == (200, {"ok": True})
    assert (await client.get(WHOAMI, headers=bearer(token))).status_code == 401


async def test_nobody_can_revoke_another_users_token(client, registry, make_user):
    await make_user("dana", roles=["admin"])
    await make_user("eli", roles=["admin"])
    danas = await sign_in(client, "dana")
    elis = await sign_in(client, "eli")

    response = await client.delete(f"{URL}/-/user/token/{danas}", headers=bearer(elis))
    unknown = await client.delete(f"{URL}/-/user/token/mga_nothing", headers=bearer(elis))

    assert (response.status_code, error_code(response)) == (404, "not_found")
    assert unknown.status_code == 404
    assert (await client.get(WHOAMI, headers=bearer(danas))).status_code == 200


async def test_whoami_needs_a_person_and_ping_does_not(client, registry, root, db):
    await set_setting(db, "anonymous_access", {"enabled": True})
    await db.commit()

    anonymous_who = await client.get(WHOAMI)
    by_password = await client.get(WHOAMI, headers=root)
    ping = await client.get(f"{URL}/-/ping", headers=root)
    written = await client.put(f"{URL}/-/ping", headers=root)

    assert anonymous_who.status_code == 401
    assert by_password.json() == {"username": "root"}
    assert (ping.status_code, ping.json()) == (200, {})
    assert ping.headers["X-Content-Type-Options"] == "nosniff"
    assert (written.status_code, error_code(written)) == (405, "method_not_allowed")


async def test_web_login_is_absent_so_that_npm_falls_back(client, registry, root):
    response = await client.post(f"{URL}/-/v1/login", json={}, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_basic_credentials_still_work_everywhere(client, registry, make_user):
    await make_user("dana", roles=["admin"])

    assert (await client.get(WHOAMI, headers=basic("dana", PASSWORD))).json() == {
        "username": "dana"
    }
```

`backend/tests/repositories/npm/test_hosted_publish.py`:

```python
import base64
import hashlib

import pytest
from sqlalchemy import func, select

from megooarti.repositories.models import Asset, Component
from megooarti.security import roles
from megooarti.system.settings_store import set_setting
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.npm.conftest import (
    URL,
    address,
    create,
    publish,
    publish_body,
    tarball_of,
)

TARBALL_URL = f"{URL}/left-pad/-/left-pad-1.0.0.tgz"


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_a_published_package_can_be_read_back(client, registry, root, db):
    published = await publish(client, root, "left-pad", "1.0.0", description="Pads on the left")

    document = await client.get(f"{URL}/left-pad", headers=root)
    tarball = await client.get(TARBALL_URL, headers=root)

    assert published.status_code == 201, published.text
    assert published.json()["ok"] is True
    body = document.json()
    assert (document.status_code, body["name"], body["_id"]) == (200, "left-pad", "left-pad")
    assert body["dist-tags"] == {"latest": "1.0.0"}
    assert body["description"] == "Pads on the left"
    manifest = body["versions"]["1.0.0"]
    data = tarball_of("left-pad", "1.0.0")
    assert manifest["dist"] == {
        "shasum": hashlib.sha1(data).hexdigest(),
        "integrity": "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        "tarball": "https://test/repository/npm/left-pad/-/left-pad-1.0.0.tgz",
    }
    assert (tarball.status_code, tarball.content) == (200, data)
    assert tarball.headers["Content-Type"] == "application/octet-stream"
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("", "left-pad", "1.0.0")
    assert "tarball" not in component.attributes["npm"]["dist"]


async def test_the_document_is_served_like_any_content(client, registry, root):
    await publish(client, root, "left-pad", "1.0.0")
    first = await client.get(f"{URL}/left-pad", headers=root)
    etag = first.headers["ETag"]

    headed = await client.head(f"{URL}/left-pad", headers=root)
    unchanged = await client.get(f"{URL}/left-pad", headers={**root, "If-None-Match": etag})
    await publish(client, root, "left-pad", "1.1.0")
    changed = await client.get(f"{URL}/left-pad", headers={**root, "If-None-Match": etag})

    assert first.headers["Content-Type"] == "application/json"
    assert first.headers["Content-Security-Policy"] == "sandbox"
    assert first.headers["X-Content-Type-Options"] == "nosniff"
    assert etag == f'"{hashlib.sha256(first.content).hexdigest()}"'
    assert "X-Checksum-Md5" not in first.headers
    assert (headed.status_code, headed.content) == (200, b"")
    assert (unchanged.status_code, unchanged.content) == (304, b"")
    assert (changed.status_code, list(changed.json()["versions"])) == (200, ["1.0.0", "1.1.0"])


async def test_a_scoped_package(client, registry, root, db):
    published = await publish(client, root, "@acme/widget", "2.0.0")

    encoded = await client.get(f"{URL}/@acme%2fwidget", headers=root)
    plain = await client.get(f"{URL}/@acme/widget", headers=root)
    tarball = await client.get(f"{URL}/@acme/widget/-/widget-2.0.0.tgz", headers=root)

    assert published.status_code == 201, published.text
    assert encoded.json() == plain.json()
    link = encoded.json()["versions"]["2.0.0"]["dist"]["tarball"]
    assert link == "https://test/repository/npm/@acme/widget/-/widget-2.0.0.tgz"
    assert tarball.content == tarball_of("@acme/widget", "2.0.0")
    component = await db.scalar(select(Component))
    assert (component.namespace, component.name, component.version) == ("acme", "widget", "2.0.0")


async def test_versions_are_listed_in_order_and_latest_follows_the_publish(client, registry, root):
    for version in ("1.10.0", "1.9.0"):
        await publish(client, root, "left-pad", version)
    await publish(client, root, "left-pad", "2.0.0-beta.1", tag="beta")

    body = (await client.get(f"{URL}/left-pad", headers=root)).json()

    assert list(body["versions"]) == ["1.9.0", "1.10.0", "2.0.0-beta.1"]
    assert body["dist-tags"] == {"latest": "1.9.0", "beta": "2.0.0-beta.1"}
    assert set(body["time"]) == {"created", "modified", "1.9.0", "1.10.0", "2.0.0-beta.1"}


async def test_the_first_version_is_latest_whatever_tag_it_was_published_with(
    client, registry, root
):
    await publish(client, root, "left-pad", "1.0.0-rc.1", tag="next")

    body = (await client.get(f"{URL}/left-pad", headers=root)).json()

    assert body["dist-tags"] == {"latest": "1.0.0-rc.1", "next": "1.0.0-rc.1"}


async def test_one_version_by_number_or_by_tag(client, registry, root):
    await publish(client, root, "left-pad", "1.0.0")
    await publish(client, root, "left-pad", "1.1.0")

    by_number = await client.get(f"{URL}/left-pad/1.0.0", headers=root)
    by_tag = await client.get(f"{URL}/left-pad/latest", headers=root)
    missing = await client.get(f"{URL}/left-pad/9.9.9", headers=root)

    assert by_number.json()["version"] == "1.0.0"
    assert by_number.json()["dist"]["tarball"].endswith("/left-pad/-/left-pad-1.0.0.tgz")
    assert by_tag.json()["version"] == "1.1.0"
    assert (missing.status_code, error_code(missing)) == (404, "not_found")


async def test_links_use_the_configured_public_address(client, registry, root, db):
    await publish(client, root, "left-pad", "1.0.0")
    await set_setting(db, "base_url", "https://packages.example/")
    await db.commit()

    body = (await client.get(f"{URL}/left-pad", headers=root)).json()

    assert body["versions"]["1.0.0"]["dist"]["tarball"] == (
        "https://packages.example/repository/npm/left-pad/-/left-pad-1.0.0.tgz"
    )


async def test_what_is_not_there_is_not_found(client, registry, root):
    for path in (
        "left-pad",
        "left-pad/1.0.0",
        "left-pad/-/left-pad-1.0.0.tgz",
        "-/nothing",
        "a/b/c",
    ):
        response = await client.get(f"{URL}/{path}", headers=root)
        assert (response.status_code, error_code(response)) == (404, "not_found"), path


async def test_publishing_a_version_again_follows_the_deployment_policy(client, db, root):
    await create(db, "npm")
    await create(db, "once", hosted={"deployment_policy": "disable_redeploy"})
    for repository in ("npm", "once"):
        await publish(client, root, "left-pad", "1.0.0", repository=repository)

    replaced = await publish(
        client, root, "left-pad", "1.0.0", repository="npm", description="again"
    )
    refused = await publish(client, root, "left-pad", "1.0.0", repository="once")

    assert replaced.status_code == 201
    document = (await client.get(address("left-pad"), headers=root)).json()
    assert document["versions"]["1.0.0"]["description"] == "again"
    assert (refused.status_code, error_code(refused)) == (409, "redeploy_disabled")


async def test_a_tarball_that_does_not_match_its_manifest_is_refused(
    client, registry, root, db, settings
):
    wrong_sha1 = publish_body("left-pad", "1.0.0")
    wrong_sha1["versions"]["1.0.0"]["dist"]["shasum"] = "0" * 40
    wrong_integrity = publish_body("left-pad", "1.0.0")
    wrong_integrity["versions"]["1.0.0"]["dist"]["integrity"] = (
        "sha512-" + base64.b64encode(b"\x00" * 64).decode()
    )
    wrong_length = publish_body("left-pad", "1.0.0")
    wrong_length["_attachments"]["left-pad-1.0.0.tgz"]["length"] = 3

    for body in (wrong_sha1, wrong_integrity, wrong_length):
        response = await client.put(f"{URL}/left-pad", json=body, headers=root)
        assert (response.status_code, error_code(response)) == (400, "checksum_mismatch")

    assert await count(db, Asset) == 0
    temporary = settings.data_dir / "blobs" / "default" / "tmp"
    assert not temporary.exists() or list(temporary.iterdir()) == []


async def test_a_publish_must_be_a_package(client, registry, root, db):
    another_name = publish_body("right-pad", "1.0.0")
    no_tarball = publish_body("left-pad", "1.0.0")
    no_tarball["_attachments"] = {"something-else.tgz": {"data": "aGk="}}
    not_a_version = publish_body("left-pad", "1.0")

    for body in (another_name, no_tarball, not_a_version, ["not", "an", "object"]):
        response = await client.put(f"{URL}/left-pad", json=body, headers=root)
        assert (response.status_code, error_code(response)) == (400, "invalid_package")
    not_json = await client.put(f"{URL}/left-pad", content=b"{", headers=root)

    assert (not_json.status_code, error_code(not_json)) == (400, "invalid_package")
    assert await count(db, Asset) == 0


async def test_a_publish_larger_than_the_limit_is_refused(client, registry, root, app, db):
    app.state.settings.npm_max_publish_bytes = 500

    response = await publish(client, root, "left-pad", "1.0.0", readme="x" * 600)

    assert (response.status_code, error_code(response)) == (413, "payload_too_large")
    assert await count(db, Asset) == 0


async def test_a_new_package_needs_a_lower_case_name(client, registry, root):
    response = await publish(client, root, "LeftPad", "1.0.0")

    assert (response.status_code, error_code(response)) == (400, "invalid_package")


async def test_a_tarball_cannot_be_uploaded_on_its_own(client, registry, root):
    response = await client.put(TARBALL_URL, content=b"raw bytes", headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
    assert response.headers["Allow"] == "GET, HEAD, DELETE"


async def test_publishing_needs_add_and_reading_needs_read(client, registry, root, make_user, db):
    await roles.create_role(db, "publishers", "", ["repository:npm:npm:add"], [])
    await roles.create_role(db, "readers", "", ["repository:npm:npm:read"], [])
    await db.commit()
    await make_user("pat", roles=["publishers"])
    await make_user("rae", roles=["readers"])
    publisher, reader = basic("pat", PASSWORD), basic("rae", PASSWORD)

    by_reader = await publish(client, reader, "left-pad", "1.0.0")
    by_nobody = await publish(client, {}, "left-pad", "1.0.0")
    by_publisher = await publish(client, publisher, "left-pad", "1.0.0")
    next_version = await publish(client, publisher, "left-pad", "1.1.0")
    again = await publish(client, publisher, "left-pad", "1.0.0")
    read_by_publisher = await client.get(f"{URL}/left-pad", headers=publisher)
    read_by_reader = await client.get(f"{URL}/left-pad", headers=reader)

    assert (by_reader.status_code, error_code(by_reader)) == (403, "forbidden")
    assert by_nobody.status_code == 401
    assert (by_publisher.status_code, next_version.status_code) == (201, 201)
    assert (again.status_code, error_code(again)) == (403, "forbidden")  # replacing needs edit
    assert read_by_publisher.status_code == 403
    assert list(read_by_reader.json()["versions"]) == ["1.0.0", "1.1.0"]


async def test_a_read_only_repository_takes_no_publish(client, db, root):
    await create(db, "frozen", hosted={"deployment_policy": "read_only"})

    response = await publish(client, root, "left-pad", "1.0.0", repository="frozen")

    assert (response.status_code, error_code(response)) == (403, "repository_read_only")


@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_other_methods_are_not_allowed(client, registry, root, method):
    response = await client.request(method, f"{URL}/left-pad", json={}, headers=root)

    assert (response.status_code, error_code(response)) == (405, "method_not_allowed")
```

`backend/tests/repositories/npm/test_hosted_changes.py`:

```python
import copy

from sqlalchemy import func, select

from megooarti.repositories import service
from megooarti.repositories.models import Asset
from megooarti.security import roles
from tests.accounts import PASSWORD, basic, error_code
from tests.repositories.npm.conftest import URL, create, publish

DOCUMENT = f"{URL}/left-pad"
TAGS = f"{URL}/-/package/left-pad/dist-tags"


async def document(client, headers, url: str = DOCUMENT) -> dict:
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def three_versions(client, root) -> None:
    for version in ("1.0.0", "1.1.0", "2.0.0"):
        response = await publish(client, root, "left-pad", version)
        assert response.status_code == 201, response.text


async def account(db, make_user, name: str, *actions: str, repository: str = "npm") -> dict:
    """A user allowed exactly these actions on a repository. Returns their headers."""
    permissions = [f"repository:npm:{repository}:{action}" for action in actions]
    await roles.create_role(db, f"role-of-{name}", "", permissions, [])
    await db.commit()
    await make_user(name, roles=[f"role-of-{name}"])
    return basic(name, PASSWORD)


async def test_dist_tags_are_listed_set_and_removed(client, registry, root):
    await three_versions(client, root)

    listed = await client.get(TAGS, headers=root)
    added = await client.put(f"{TAGS}/stable", json="1.1.0", headers=root)
    moved = await client.put(f"{TAGS}/latest", json="1.1.0", headers=root)
    after_adding = (await client.get(TAGS, headers=root)).json()
    removed = await client.delete(f"{TAGS}/stable", headers=root)

    assert (listed.status_code, listed.json()) == (200, {"latest": "2.0.0"})
    assert (added.status_code, moved.status_code, removed.status_code) == (200, 200, 200)
    assert after_adding == {"latest": "1.1.0", "stable": "1.1.0"}
    assert (await document(client, root))["dist-tags"] == {"latest": "1.1.0"}


async def test_a_tag_must_name_a_version_that_exists(client, registry, root):
    await three_versions(client, root)

    missing_version = await client.put(f"{TAGS}/beta", json="9.9.9", headers=root)
    not_a_string = await client.put(f"{TAGS}/beta", json={"version": "1.0.0"}, headers=root)
    latest = await client.delete(f"{TAGS}/latest", headers=root)
    no_package = await client.get(f"{URL}/-/package/nothing/dist-tags", headers=root)
    wrong_method = await client.delete(TAGS, headers=root)

    assert (missing_version.status_code, error_code(missing_version)) == (404, "not_found")
    assert (not_a_string.status_code, error_code(not_a_string)) == (400, "invalid_package")
    assert (latest.status_code, error_code(latest)) == (400, "invalid_package")
    assert no_package.status_code == 404
    assert (wrong_method.status_code, error_code(wrong_method)) == (405, "method_not_allowed")
    assert (await client.get(TAGS, headers=root)).json() == {"latest": "2.0.0"}


async def test_the_tags_are_kept_in_a_document_nobody_downloads(client, registry, root, db):
    await three_versions(client, root)
    await client.put(f"{TAGS}/stable", json="1.1.0", headers=root)

    kept = await db.scalar(select(Asset).where(Asset.kind == "metadata"))

    assert (kept.path, kept.component_id) == ("-/package/left-pad/dist-tags", None)
    assert await db.scalar(select(func.count()).select_from(Asset)) == 4


async def test_deprecating_changes_the_stored_manifest(client, registry, root):
    await three_versions(client, root)
    sent = await document(client, root)
    sent["versions"]["1.0.0"]["deprecated"] = "use 2.0.0"
    sent["versions"]["1.1.0"]["description"] = "edits to anything else are ignored"

    deprecated = await client.put(f"{DOCUMENT}/-rev/{sent['_rev']}", json=sent, headers=root)
    after = await document(client, root)
    sent = copy.deepcopy(after)
    sent["versions"]["1.0.0"]["deprecated"] = ""  # how npm lifts a deprecation
    lifted = await client.put(DOCUMENT, json=sent, headers=root)

    assert (deprecated.status_code, lifted.status_code) == (200, 200)
    assert after["versions"]["1.0.0"]["deprecated"] == "use 2.0.0"
    assert "description" not in after["versions"]["1.1.0"]
    assert list(after["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]
    assert "deprecated" not in (await document(client, root))["versions"]["1.0.0"]


async def test_unpublishing_one_version_as_npm_does_it(client, registry, root):
    await three_versions(client, root)
    sent = await document(client, root)
    link = sent["versions"]["2.0.0"]["dist"]["tarball"].removeprefix("https://test")
    del sent["versions"]["2.0.0"]
    sent["dist-tags"] = {"latest": "1.1.0"}

    updated = await client.put(f"{DOCUMENT}/-rev/{sent['_rev']}", json=sent, headers=root)
    tarball = await client.delete(f"{link}/-rev/anything", headers=root)

    after = await document(client, root)
    assert (updated.status_code, tarball.status_code) == (200, 200)  # already gone is fine
    assert list(after["versions"]) == ["1.0.0", "1.1.0"]
    assert after["dist-tags"] == {"latest": "1.1.0"}
    assert (await client.get(link, headers=root)).status_code == 404


async def test_removing_the_latest_version_moves_latest_to_the_highest_left(client, registry, root):
    await three_versions(client, root)

    removed = await client.delete(f"{URL}/left-pad/-/left-pad-2.0.0.tgz", headers=root)

    assert removed.status_code == 200
    assert (await document(client, root))["dist-tags"] == {"latest": "1.1.0"}
    assert (await client.get(TAGS, headers=root)).json() == {"latest": "1.1.0"}


async def test_an_update_that_omits_versions_removes_nothing(client, registry, root):
    await three_versions(client, root)

    response = await client.put(DOCUMENT, json={"name": "left-pad"}, headers=root)

    assert response.status_code == 200
    assert list((await document(client, root))["versions"]) == ["1.0.0", "1.1.0", "2.0.0"]


async def test_unpublishing_the_whole_package(client, registry, root, db):
    await three_versions(client, root)
    await client.put(f"{TAGS}/stable", json="1.0.0", headers=root)

    removed = await client.delete(f"{DOCUMENT}/-rev/anything", headers=root)
    again = await client.delete(DOCUMENT, headers=root)

    assert (removed.status_code, removed.json()) == (200, {"ok": True})
    assert (again.status_code, error_code(again)) == (404, "not_found")
    assert (await client.get(DOCUMENT, headers=root)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(Asset)) == 0


async def test_an_update_to_a_package_that_is_not_there_is_not_found(client, registry, root):
    response = await client.put(DOCUMENT, json={"name": "left-pad", "versions": {}}, headers=root)

    assert (response.status_code, error_code(response)) == (404, "not_found")


async def test_each_change_needs_its_own_permission(client, registry, root, make_user, db):
    await three_versions(client, root)
    publisher = await account(db, make_user, "pat", "read", "add")
    editor = await account(db, make_user, "eve", "read", "edit")
    remover = await account(db, make_user, "del", "read", "edit", "delete")
    reader = await account(db, make_user, "rae", "read")
    sent = await document(client, root)
    deprecating = {**sent, "versions": {**sent["versions"]}}
    deprecating["versions"]["1.0.0"] = {**sent["versions"]["1.0.0"], "deprecated": "old"}
    removing = {**sent, "versions": {k: v for k, v in sent["versions"].items() if k != "2.0.0"}}
    tarball = f"{URL}/left-pad/-/left-pad-1.1.0.tgz"

    outcomes = {
        "reader deprecates": await client.put(DOCUMENT, json=deprecating, headers=reader),
        "publisher deprecates": await client.put(DOCUMENT, json=deprecating, headers=publisher),
        "editor deprecates": await client.put(DOCUMENT, json=deprecating, headers=editor),
        "editor removes a version": await client.put(DOCUMENT, json=removing, headers=editor),
        "editor deletes a tarball": await client.delete(tarball, headers=editor),
        "editor deletes the package": await client.delete(DOCUMENT, headers=editor),
        "reader sets a tag": await client.put(f"{TAGS}/x", json="1.0.0", headers=reader),
        "publisher sets a tag": await client.put(f"{TAGS}/x", json="1.0.0", headers=publisher),
        "remover removes a version": await client.put(DOCUMENT, json=removing, headers=remover),
        "remover deletes a tarball": await client.delete(tarball, headers=remover),
    }

    assert {name: response.status_code for name, response in outcomes.items()} == {
        "reader deprecates": 403,
        "publisher deprecates": 403,
        "editor deprecates": 200,
        "editor removes a version": 403,
        "editor deletes a tarball": 403,
        "editor deletes the package": 403,
        "reader sets a tag": 403,
        "publisher sets a tag": 200,
        "remover removes a version": 200,
        "remover deletes a tarball": 200,
    }
    assert list((await document(client, root))["versions"]) == ["1.0.0"]


async def test_a_read_only_repository_takes_no_changes(client, db, root):
    repository = await create(db, "open")
    await publish(client, root, "left-pad", "1.0.0", repository="open")
    await service.update_repository(
        db, repository, online=True, hosted={"deployment_policy": "read_only"}, format_config={}
    )
    await db.commit()
    base = "/repository/open"

    attempts = [
        await client.put(
            f"{base}/left-pad", json={"name": "left-pad", "versions": {}}, headers=root
        ),
        await client.delete(f"{base}/left-pad", headers=root),
        await client.delete(f"{base}/left-pad/-/left-pad-1.0.0.tgz", headers=root),
        await client.put(f"{base}/-/package/left-pad/dist-tags/x", json="1.0.0", headers=root),
        await client.delete(f"{base}/-/package/left-pad/dist-tags/x", headers=root),
    ]

    assert [error_code(response) for response in attempts] == ["repository_read_only"] * 5
    assert (await client.get(f"{base}/left-pad", headers=root)).status_code == 200
```

`backend/tests/repositories/npm/test_search.py`:

```python
import pytest

from tests.accounts import error_code
from tests.repositories.npm.conftest import URL, publish

SEARCH = f"{URL}/-/v1/search"


@pytest.fixture
async def packages(client, registry, root) -> None:
    await publish(client, root, "left-pad", "1.0.0", description="Pads on the left")
    await publish(client, root, "left-pad", "1.3.0", description="Pads on the left, better")
    await publish(client, root, "right-pad", "0.1.0")
    await publish(client, root, "@acme/widget", "2.0.0", description="A widget")
    await publish(client, root, "unrelated", "1.0.0")


async def names(client, root, **query) -> list[str]:
    response = await client.get(SEARCH, params=query, headers=root)
    assert response.status_code == 200, response.text
    return [entry["package"]["name"] for entry in response.json()["objects"]]


async def test_search_finds_packages_by_name(client, packages, root):
    response = await client.get(SEARCH, params={"text": "pad"}, headers=root)

    body = response.json()
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert [entry["package"]["name"] for entry in body["objects"]] == ["left-pad", "right-pad"]
    assert body["total"] == 2
    first = body["objects"][0]["package"]
    assert (first["version"], first["description"]) == ("1.3.0", "Pads on the left, better")
    assert body["objects"][1]["package"]["description"] == ""


async def test_search_matches_the_scope_and_ignores_case(client, packages, root):
    assert await names(client, root, text="ACME") == ["@acme/widget"]
    assert await names(client, root, text="Widget") == ["@acme/widget"]


async def test_an_empty_search_lists_everything_a_page_at_a_time(client, packages, root):
    everything = await names(client, root)
    first_two = await names(client, root, size=2)
    the_rest = await names(client, root, size=10, **{"from": 2})

    assert everything == ["left-pad", "right-pad", "unrelated", "@acme/widget"]
    assert first_two + the_rest == everything


async def test_search_characters_are_taken_literally(client, packages, root):
    assert await names(client, root, text="%") == []
    assert await names(client, root, text="_") == []
    assert await names(client, root, text="left-pa_") == []


async def test_odd_paging_falls_back_to_the_defaults(client, packages, root):
    assert len(await names(client, root, size="many", **{"from": "-3"})) == 4
    assert len(await names(client, root, size=100000)) == 4


async def test_search_finds_nothing_in_an_empty_repository(client, registry, root):
    response = await client.get(SEARCH, params={"text": "pad"}, headers=root)

    assert (response.json()["objects"], response.json()["total"]) == ([], 0)


async def test_search_is_read_only_and_needs_read(client, packages, root):
    written = await client.put(SEARCH, json={}, headers=root)
    anonymous = await client.get(SEARCH)

    assert (written.status_code, error_code(written)) == (405, "method_not_allowed")
    assert anonymous.status_code == 401
```

`backend/tests/repositories/npm/test_races.py`:

```python
"""Changes at the same moment, which only real, concurrent transactions can show."""

import asyncio
import json

from megooarti.config import Settings
from megooarti.repositories import service
from megooarti.repositories.content import RepositoryContext, build_context
from megooarti.repositories.models import Repository
from megooarti.repositories.npm import documents, paths
from megooarti.repositories.npm.format import TAGS_LIMIT, _change_tags, _publish
from tests.repositories.conftest import someone
from tests.repositories.npm.conftest import publish_body
from tests.storage.test_races import Factory, run

PUBLISHER = someone("repository:npm:npm")


async def create_registry(factory: Factory) -> Repository:
    async with factory() as db:
        repository = await service.create_repository(
            db,
            name="npm",
            format="npm",
            type="hosted",
            online=True,
            blob_store="default",
            hosted=None,
            format_config={},
        )
        await db.commit()
        return repository


async def context_in(db, settings: Settings, repository: Repository) -> RepositoryContext:
    return await build_context(db, settings, repository, PUBLISHER)


def upload_of(version: str, tag: str) -> documents.Upload:
    body = json.dumps(publish_body("left-pad", version, tag=tag)).encode()
    return documents.read_upload("left-pad", body)


async def stored_tags(db, settings: Settings, repository: Repository) -> dict:
    context = await context_in(db, settings, repository)
    return json.loads(await context.read(paths.dist_tags_path("left-pad"), limit=TAGS_LIMIT))


def test_two_versions_published_at_once_are_both_there(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_registry(factory)

        async def publish(version: str, tag: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                await _publish(context, "left-pad", upload_of(version, tag))
                await asyncio.sleep(0.2)  # stay open while the other publish happens
                await db.commit()

        await asyncio.gather(publish("1.0.0", "latest"), publish("2.0.0-beta.1", "beta"))

        async with factory() as db:
            context = await context_in(db, settings, repository)
            held = {info.version for info in await context.components("", "left-pad")}
            assert held == {"1.0.0", "2.0.0-beta.1"}
            assert await stored_tags(db, settings, repository) == {
                "latest": "1.0.0",
                "beta": "2.0.0-beta.1",
            }

    run(empty_database, tmp_path, scenario)


def test_two_tag_changes_at_once_are_both_kept(empty_database, tmp_path):
    async def scenario(factory: Factory, settings: Settings) -> None:
        repository = await create_registry(factory)
        async with factory() as db:
            context = await context_in(db, settings, repository)
            await _publish(context, "left-pad", upload_of("1.0.0", "latest"))
            await db.commit()

        async def tag(name: str) -> None:
            async with factory() as db:
                context = await context_in(db, settings, repository)
                await _change_tags(
                    context,
                    "left-pad",
                    lambda stored, held: documents.merge_tags(stored, {name: "1.0.0"}, held, held),
                )
                await asyncio.sleep(0.2)  # hold the lock while the other waits for it
                await db.commit()

        await asyncio.gather(tag("stable"), tag("lts"))

        async with factory() as db:
            assert await stored_tags(db, settings, repository) == {
                "latest": "1.0.0",
                "stable": "1.0.0",
                "lts": "1.0.0",
            }

    run(empty_database, tmp_path, scenario)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/repositories/npm -q`
Expected: `test_races.py` does not collect (`No module named 'megooarti.repositories.npm.format'`); every other new test errors while creating its repository, because `npm` is an unknown format.

- [ ] **Step 4: Implement**

`backend/src/megooarti/repositories/npm/format.py`:

```python
"""The npm format: a registry that npm, pnpm and Yarn publish to and install from.

This is the only npm module that touches the repository context. What a path means,
whether a publish is acceptable and what a package document says come from the pure
functions beside it.

A package document is generated on each request from the versions stored, so it is
right after an unpublish and after two publishes at once. Reading a publish and
building a document are CPU-bound work whose size a client decides, so they run on two
worker threads of their own.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from megooarti.clock import utcnow
from megooarti.errors import ApiError
from megooarti.repositories.content import RepositoryContext, TooLarge
from megooarti.repositories.formats import ComponentKey, Format, register
from megooarti.repositories.npm import documents, paths, semver
from megooarti.repositories.paths import normalise_path
from megooarti.security.authentication import unauthorized

# The most that is read into memory besides a publish: a sign-in or a tag, and the tags
# kept for a package.
SMALL_LIMIT = 16 * 1024
TAGS_LIMIT = 1024 * 1024
_JSON = "application/json"
_TARBALL = "application/octet-stream"
# Where a version's manifest is kept among its component's attributes.
_MANIFEST = "npm"
_MAX_SEARCH_RESULTS = 250
# Not the default executor: that one also reads and writes blobs and checks passwords.
_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="npm-documents")

# Given the tags stored and the versions that exist, the tags to keep.
TagChange = Callable[[dict[str, str], set[str]], dict[str, str]]


async def off_loop[T](function: Callable[..., T], *arguments: Any) -> T:
    """Run document work in a worker thread, at most two at a time."""
    return await asyncio.get_running_loop().run_in_executor(_workers, function, *arguments)


def _answer(value: Any, status: int = 200) -> Response:
    """A small JSON answer. Like all content here, it is never to be rendered."""
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"}
    return Response(
        content=documents.dumps(value), status_code=status, media_type=_JSON, headers=headers
    )


def _not_found(message: str = "No such package.") -> ApiError:
    return ApiError(404, "not_found", message)


def _not_allowed(allowed: str) -> ApiError:
    return ApiError(
        405,
        "method_not_allowed",
        f"This address accepts {allowed}.",
        headers={"Allow": allowed},
    )


def _invalid(reason: object) -> ApiError:
    return ApiError(400, "invalid_package", f"The request cannot be accepted: {reason}.")


def _mismatch(check: object) -> ApiError:
    return ApiError(
        400, "checksum_mismatch", f"The tarball is not the one its manifest describes ({check})."
    )


async def _json_body(context: RepositoryContext, request: Request, limit: int) -> Any:
    """A small JSON body, read into memory."""
    raw = await context.receive(request.stream(), limit=limit)
    if raw is None:
        raise ApiError(413, "payload_too_large", "The request is larger than this address takes.")
    try:
        return documents.loads(raw)
    except documents.InvalidPackage as error:
        raise _invalid(error) from None


def _is_read(request: Request) -> bool:
    return request.method in ("GET", "HEAD")


# --- Signing in, and the registry's small endpoints ---------------------------------


async def _sign_in(context: RepositoryContext, request: Request, parsed: paths.NpmPath) -> Response:
    """`npm login`: a user name and a password in, a token out.

    This is the one request that may arrive without credentials, because it carries
    them in its body. It must not use `context.principal`.
    """
    if request.method != "PUT":
        raise _not_allowed("PUT")
    body = await _json_body(context, request, SMALL_LIMIT)
    name = body.get("name") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(name, str) or not isinstance(password, str) or name != parsed.username:
        raise _invalid("it must carry the user name in the address, and a password")
    token = await context.issue_token(request, name, password, label="npm login")
    return _answer({"ok": True, "id": f"org.couchdb.user:{name}", "token": token}, 201)


async def _sign_out(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    if request.method != "DELETE":
        raise _not_allowed("DELETE")
    await context.revoke_token(parsed.token)
    return _answer({"ok": True})


def _who(context: RepositoryContext, request: Request) -> Response:
    if not _is_read(request):
        raise _not_allowed("GET, HEAD")
    if context.principal is None or context.principal.is_anonymous:
        raise unauthorized(scheme="Basic")
    return _answer({"username": context.principal.user.username})


async def registry_endpoint(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response | None:
    """Answer for an endpoint every repository type has, or None if `parsed` is not one."""
    if parsed.kind == "login":
        return await _sign_in(context, request, parsed)
    if parsed.kind == "logout":
        return await _sign_out(context, request, parsed)
    if parsed.kind == "whoami":
        return _who(context, request)
    if parsed.kind == "ping":
        if not _is_read(request):
            raise _not_allowed("GET, HEAD")
        return _answer({})
    return None


# --- What a hosted repository holds --------------------------------------------------


def _coordinates(package: str) -> tuple[str, str]:
    """A package's namespace and name, as its components are keyed."""
    return paths.scope_of(package), paths.unscoped(package)


async def _versions(context: RepositoryContext, package: str) -> list[documents.Version]:
    """The versions of a package that are stored, each with its manifest."""
    held = await context.components(*_coordinates(package))
    return [
        documents.Version(
            version=info.version,
            manifest=info.attributes.get(_MANIFEST) or {"name": package, "version": info.version},
            created=info.created,
            modified=info.modified,
        )
        for info in held
    ]


def _read_tags(raw: bytes | None) -> dict[str, str]:
    """The dist-tags in a stored document. Anything unreadable counts as none."""
    if raw is None:
        return {}
    try:
        stored = documents.loads(raw)
    except documents.InvalidPackage:
        return {}
    if not isinstance(stored, dict):
        return {}
    return {tag: version for tag, version in stored.items() if isinstance(version, str)}


async def _stored_tags(context: RepositoryContext, package: str) -> dict[str, str]:
    try:
        return _read_tags(await context.read(paths.dist_tags_path(package), limit=TAGS_LIMIT))
    except TooLarge:
        return {}


async def _change_tags(context: RepositoryContext, package: str, change: TagChange) -> None:
    """Change a package's dist-tags under their lock.

    The versions are read inside the lock, so a tag is judged against what exists once
    every earlier change has been committed.
    """

    async def update(current: bytes | None) -> bytes | None:
        held = await context.components(*_coordinates(package))
        kept = change(_read_tags(current), {info.version for info in held})
        return documents.dumps(kept) if kept else None

    await context.maintain(
        paths.dist_tags_path(package), update, content_type=_JSON, limit=TAGS_LIMIT
    )


async def built(
    context: RepositoryContext, request: Request, package: str
) -> tuple[list[documents.Version], dict[str, str], str] | None:
    """What a hosted package's document is made of, or None if it has no version."""
    versions = await _versions(context, package)
    if not versions:
        return None
    tags = await _stored_tags(context, package)
    base = await context.public_url(request)
    await context.release()  # the work that follows needs no connection
    return versions, tags, base


# --- Reading -------------------------------------------------------------------------


async def _document(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    found = await built(context, request, parsed.package)
    if found is None:
        raise _not_found()
    rendered = await off_loop(documents.render, parsed.package, *found)
    return context.respond_with(
        rendered.data,
        request,
        filename=f"{parsed.name}.json",
        content_type=_JSON,
        last_modified=rendered.modified,
        etag=rendered.etag,
    )


async def _manifest(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    found = await built(context, request, parsed.package)
    if found is None:
        raise _not_found()
    document = await off_loop(documents.document, parsed.package, *found)
    manifest = documents.manifest_of(document, parsed.version)
    if manifest is None:
        raise _not_found("No such version.")
    return _answer(manifest)


async def _search(context: RepositoryContext, request: Request) -> Response:
    """Packages this repository holds whose name or scope contains the text."""

    def number(name: str, default: int, most: int) -> int:
        value = request.query_params.get(name, "")
        return min(int(value), most) if value.isascii() and value.isdigit() else default

    text = request.query_params.get("text", "").strip()[: paths.MAX_NAME_LENGTH]
    size = number("size", 20, _MAX_SEARCH_RESULTS)
    names, total = await context.package_names(text, limit=size, offset=number("from", 0, 10**9))
    found = []
    for scope, name in names:
        held = await context.components(scope, name)
        newest = max(held, key=lambda info: semver.sort_key(info.version))
        description = (newest.attributes.get(_MANIFEST) or {}).get("description")
        found.append(
            documents.Found(
                name=f"@{scope}/{name}" if scope else name,
                version=newest.version,
                description=description if isinstance(description, str) else "",
                date=newest.modified,
            )
        )
    return _answer(documents.search_results(found, total, utcnow()))


# --- Changing ------------------------------------------------------------------------


async def _publish(context: RepositoryContext, package: str, upload: documents.Upload) -> Response:
    """Store the versions a publish carries: every tarball first, then the records."""
    staged = []
    try:
        for release in upload.releases:
            blob = await context.stage_bytes(release.data)
            staged.append((release, blob))
            documents.verify(
                release.manifest, sha1=blob.sha1, sha256=blob.sha256, sha512=blob.sha512
            )
        held = await context.components(*_coordinates(package))
        if not held and package != package.lower():
            raise _invalid("the name of a new package must be in lower case")
    except BaseException as error:
        for _, blob in staged:
            await context.discard(blob)
        if isinstance(error, documents.ChecksumMismatch):
            raise _mismatch(error) from None
        raise

    for position, (release, blob) in enumerate(staged):
        manifest = documents.stored_manifest(release.manifest, sha1=blob.sha1, sha512=blob.sha512)
        try:
            # The facade checks `add` or `edit` and the deployment policy for each file.
            await context.store(
                paths.tarball_path(package, release.version),
                blob,
                content_type=_TARBALL,
                component_attributes={_MANIFEST: manifest},
            )
        except BaseException:
            for _, later in staged[position + 1 :]:
                await context.discard(later)
            raise

    published = {release.version for release in upload.releases}
    await _change_tags(
        context,
        package,
        lambda stored, versions: documents.merge_tags(
            stored, upload.tags, versions - published, versions
        ),
    )
    return _answer({"ok": True, "id": package, "rev": "1-0"}, 201)


async def _update(context: RepositoryContext, package: str, upload: documents.Upload) -> Response:
    """Apply a document sent back without attachments: `npm deprecate` and `npm unpublish`."""
    scope, name = _coordinates(package)
    held = {
        info.version: info.attributes.get(_MANIFEST) or {}
        for info in await context.components(scope, name)
    }
    if not held:
        raise _not_found()
    try:
        plan = documents.update_plan(held, upload.document)
    except documents.InvalidPackage as error:
        raise _invalid(error) from None

    for version, message in plan.deprecations.items():  # needs `edit`
        changed = documents.deprecated(held[version], message)
        await context.annotate(scope, name, version, {_MANIFEST: changed})
    for version in plan.removals:  # needs `delete`
        await context.delete(paths.tarball_path(package, version))

    tags = upload.tags
    if tags is not None:
        await _change_tags(
            context, package, lambda _, versions: documents.effective_tags(tags, versions)
        )
    elif plan.removals:
        await _change_tags(context, package, documents.effective_tags)
    return _answer({"ok": True, "id": package, "rev": "1-0"})


async def _write_document(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    """A document sent to a package's address: a publish, or an update."""
    # Refused before the body is read; the facade checks each operation again.
    context.require_write()
    raw = await context.receive(request.stream(), limit=context.settings.npm_max_publish_bytes)
    if raw is None:
        raise ApiError(413, "payload_too_large", "The package is larger than this server takes.")
    try:
        upload = await off_loop(documents.read_upload, parsed.package, raw)
    except documents.InvalidPackage as error:
        raise _invalid(error) from None
    except documents.ChecksumMismatch as error:
        raise _mismatch(error) from None
    if upload.releases:
        return await _publish(context, parsed.package, upload)
    return await _update(context, parsed.package, upload)


async def _unpublish(context: RepositoryContext, parsed: paths.NpmPath) -> Response:
    """Remove every version of a package, and its dist-tags."""
    package = parsed.package
    await context.delete(paths.dist_tags_path(package))  # checks `delete` before anything
    held = await context.components(*_coordinates(package))
    if not held:
        raise _not_found()
    for info in held:
        await context.delete(paths.tarball_path(package, info.version))
    return _answer({"ok": True})


async def _tarball(context: RepositoryContext, request: Request, parsed: paths.NpmPath) -> Response:
    path = paths.tarball_path(parsed.package, parsed.version)
    if _is_read(request):
        return await context.respond(path, request)
    if request.method != "DELETE":
        # A tarball arrives inside a publish, with its manifest, never on its own.
        raise _not_allowed("GET, HEAD, DELETE")
    # npm removes the version from the document first and then deletes the tarball, so
    # by now it may be gone. That is still what was asked for.
    await context.delete(path)
    return _answer({"ok": True})


async def _dist_tags(
    context: RepositoryContext, request: Request, parsed: paths.NpmPath
) -> Response:
    package, tag = parsed.package, parsed.tag
    if _is_read(request) and not tag:
        versions = {info.version for info in await context.components(*_coordinates(package))}
        if not versions:
            raise _not_found()
        return _answer(documents.effective_tags(await _stored_tags(context, package), versions))
    if request.method == "PUT" and tag:
        context.require_write()
        version = await _json_body(context, request, SMALL_LIMIT)
        if not isinstance(version, str) or not documents.is_valid_tag(tag):
            raise _invalid("a dist-tag is set by sending a version as a JSON string")
        versions = {info.version for info in await context.components(*_coordinates(package))}
        if version not in versions:
            raise _not_found("No such version.")
        await _change_tags(
            context,
            package,
            lambda stored, held: documents.merge_tags(stored, {tag: version}, held, held),
        )
        return _answer({"ok": True})
    if request.method == "DELETE" and tag:
        if tag == "latest":
            raise _invalid("the latest tag cannot be removed, only moved")
        await _change_tags(
            context,
            package,
            lambda stored, held: documents.effective_tags(
                {name: version for name, version in stored.items() if name != tag}, held
            ),
        )
        return _answer({"ok": True})
    raise _not_allowed("GET, HEAD" if not tag else "PUT, DELETE")


class NpmFormat(Format):
    name = "npm"
    # Proxy and group repositories need npm's own handling of package documents.
    types = frozenset({"hosted"})

    def describe_component(self, path: str) -> ComponentKey | None:
        """A tarball belongs to its package and version. Nothing else is part of one."""
        parsed = paths.classify(path)
        if parsed.kind != "tarball":
            return None
        return ComponentKey(parsed.scope, parsed.name, parsed.version)

    def content_type(self, path: str, declared: str | None) -> str | None:
        return _TARBALL if paths.classify(path).kind == "tarball" else declared

    def takes_body_credentials(self, method: str, path: str) -> bool:
        """`npm login` sends the user name and password in its body, with no header."""
        return method == "PUT" and paths.classify(path).kind == "login"

    async def handle_hosted(
        self, context: RepositoryContext, request: Request, path: str
    ) -> Response:
        parsed = paths.classify(normalise_path(path))
        answered = await registry_endpoint(context, request, parsed)
        if answered is not None:
            return answered
        if parsed.kind == "document":
            if _is_read(request):
                return await _document(context, request, parsed)
            if request.method == "PUT":
                return await _write_document(context, request, parsed)
            if request.method == "DELETE":
                return await _unpublish(context, parsed)
            raise _not_allowed("GET, HEAD, PUT, DELETE")
        if parsed.kind == "version":
            if not _is_read(request):
                raise _not_allowed("GET, HEAD")
            return await _manifest(context, request, parsed)
        if parsed.kind == "tarball":
            return await _tarball(context, request, parsed)
        if parsed.kind == "dist_tags":
            return await _dist_tags(context, request, parsed)
        if parsed.kind == "search":
            if not _is_read(request):
                raise _not_allowed("GET, HEAD")
            return await _search(context, request)
        raise _not_found("Nothing is served at this address.")


register(NpmFormat())
```

In `backend/src/megooarti/main.py`, add after the line that imports the Maven format:

```python
from megooarti.repositories.npm import format as _npm_format  # noqa: F401  (registers it)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/repositories -q`
Expected: all pass.

- [ ] **Step 6: Run the whole suite and the linters**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, no findings.

- [ ] **Step 7: Commit**

```bash
git add backend/src/megooarti/repositories/npm/format.py backend/src/megooarti/main.py backend/tests/repositories/npm
git commit -m "feat(npm): hosted npm repositories with publish, dist-tags, deprecate, unpublish and search"
```

---

### Task 7: npm's own client, and documentation

**Files:**
- Test: `backend/tests/test_npm_client.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: hosted npm; `tests/containers.py` (`HTTP_PORT`, `PROJECT`, `call`); the `stack` and `administrator` fixtures.
- Produces: Docker-marked tests that drive the real `npm` against the built image.

These tests run only with `pytest -m docker`. They need a Docker daemon, and internet access to pull the Node image.

- [ ] **Step 1: Write the real-client test**

`backend/tests/test_npm_client.py`:

```python
"""npm's own client against the built image.

Run with `pytest -m docker`. Besides a Docker daemon this needs internet access the
first time, to pull the Node image. Everything npm asks for comes from MegooArti.
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.containers import HTTP_PORT, PROJECT, call

pytestmark = pytest.mark.docker

IMAGE = "node:22-slim"
NETWORK = f"{PROJECT}_default"
# The backend as a container on the Compose network sees it, and as this test does.
INSIDE = "backend:8000/repository/npm-hosted/"
OUTSIDE = f"http://127.0.0.1:{HTTP_PORT}/repository/npm-hosted"
# What a publishing account gets: everything on npm repositories, and nothing else.
USERNAME = "ci"
PASSWORD = "publishes-and-unpublishes-npm-packages"
PLAIN = "megooarti-greeter"
SCOPED = "@megooarti/greeter"


def package(name: str, version: str, **fields) -> dict[str, str]:
    """The files of a package whose only export says which version it is."""
    manifest = {"name": name, "version": version, "main": "index.js", **fields}
    return {
        "package.json": json.dumps(manifest, indent=2),
        "index.js": f'module.exports = () => "hello from {name}@{version}";\n',
    }


def write(directory: Path, projects: dict[str, dict[str, str]], token: str) -> Path:
    """A directory with one sub-directory for each project, and npm's configuration."""
    directory.mkdir(parents=True)
    settings = [
        f"registry=http://{INSIDE}",
        f"//{INSIDE}:_authToken={token}",
        "update-notifier=false",
        "fund=false",
    ]
    (directory / "npmrc").write_text("\n".join(settings) + "\n", encoding="utf-8", newline="\n")
    for project, files in projects.items():
        for name, content in files.items():
            target = directory / project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
    return directory


def npm(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run a shell script in the Node image, in a copy of `directory`, beside the stack."""
    setup = "cp -r /src /work && cd /work && export NPM_CONFIG_USERCONFIG=/work/npmrc"
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        NETWORK,
        "--volume",
        f"{directory}:/src:ro",
        IMAGE,
        "sh",
        "-c",
        f"{setup} && {script}",
    ]
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )


def said(result: subprocess.CompletedProcess[str]) -> str:
    return f"exit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"


def request(method: str, path: str, token: str | None = None, body: dict | None = None):
    """A request to the repository from outside: (status, parsed JSON body or None)."""
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    sent = urllib.request.Request(
        f"{OUTSIDE}/{path}",
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(sent, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None


@pytest.fixture(scope="module")
def token(administrator) -> str:
    """A hosted npm repository, a publishing account, and a token from signing in."""
    repository = {
        "name": "npm-hosted",
        "format": "npm",
        "type": "hosted",
        "hosted": {"deployment_policy": "disable_redeploy"},
    }
    role = {"name": "npm-publishers", "permissions": ["repository:npm"]}
    user = {
        "username": USERNAME,
        "display_name": "CI",
        "password": PASSWORD,
        "roles": ["npm-publishers"],
        "must_change_password": False,
    }
    for path, body in (("/repositories", repository), ("/roles", role), ("/users", user)):
        status, _, answer = call("POST", path, body, administrator)
        assert status == 201, answer

    # The request `npm login` sends once it has asked for the name and the password.
    credentials = {"_id": f"org.couchdb.user:{USERNAME}", "name": USERNAME, "password": PASSWORD}
    status, answer = request("PUT", f"-/user/org.couchdb.user:{USERNAME}", body=credentials)
    assert status == 201, answer
    return answer["token"]


def test_npm_publishes_installs_changes_and_unpublishes(token, tmp_path):
    projects = {
        "first": package(PLAIN, "1.0.0", description="Says hello"),
        "second": package(PLAIN, "1.1.0", description="Says hello, again"),
        "scoped": package(SCOPED, "2.0.0"),
        "consumer": {
            "package.json": json.dumps(
                {
                    "name": "consumer",
                    "version": "1.0.0",
                    "private": True,
                    "dependencies": {PLAIN: "1.0.0", SCOPED: "^2.0.0"},
                }
            ),
            "main.js": f'console.log(require("{PLAIN}")(), require("{SCOPED}")());\n',
        },
    }
    work = write(tmp_path / "npm", projects, token)

    # Who we are, by the token that signing in gave.
    who = npm(work, "npm whoami && npm ping")
    assert who.returncode == 0, said(who)
    assert who.stdout.splitlines()[0] == USERNAME

    # Publish two versions of one package and one scoped package.
    published = npm(
        work,
        "(cd first && npm publish) && (cd scoped && npm publish)"
        " && (cd second && npm publish --tag next)",
    )
    assert published.returncode == 0, said(published)
    again = npm(work, "cd first && npm publish")
    assert again.returncode != 0, "a version was published twice despite disable_redeploy"

    # What the registry says about them.
    viewed = npm(work, f"npm view {PLAIN} versions dist-tags description --json")
    assert viewed.returncode == 0, said(viewed)
    about = json.loads(viewed.stdout)
    assert about["versions"] == ["1.0.0", "1.1.0"]
    assert about["dist-tags"] == {"latest": "1.0.0", "next": "1.1.0"}
    assert about["description"] == "Says hello"
    found = npm(work, "npm search megooarti --json")
    assert found.returncode == 0, said(found)
    assert {entry["name"] for entry in json.loads(found.stdout)} == {PLAIN, SCOPED}

    # Dist-tags and deprecation.
    changed = npm(
        work,
        f"npm dist-tag add {PLAIN}@1.1.0 stable && npm dist-tag ls {PLAIN}"
        f' && npm deprecate {PLAIN}@1.0.0 "use 1.1.0"',
    )
    assert changed.returncode == 0, said(changed)
    assert "stable: 1.1.0" in changed.stdout

    # Install both into a project, from an empty cache, and run them.
    installed = npm(work, "cd consumer && npm install && node main.js")
    assert installed.returncode == 0, said(installed)
    assert f"hello from {PLAIN}@1.0.0 hello from {SCOPED}@2.0.0" in installed.stdout
    assert "use 1.1.0" in installed.stderr  # npm warns that the version is deprecated

    # Remove one version, then a whole package.
    removed = npm(work, f"npm unpublish {PLAIN}@1.1.0 && npm unpublish {SCOPED} --force")
    assert removed.returncode == 0, said(removed)
    status, document = request("GET", PLAIN, token)
    assert (status, list(document["versions"])) == (200, ["1.0.0"])
    assert document["dist-tags"] == {"latest": "1.0.0"}
    assert request("GET", SCOPED.replace("/", "%2f"), token)[0] == 404

    # Signing out revokes the token npm was using.
    out = npm(work, "npm logout")
    assert out.returncode == 0, said(out)
    assert request("GET", "-/whoami", token)[0] == 401
```

- [ ] **Step 2: Run it**

Run: `uv run pytest -m docker tests/test_npm_client.py -q`
Expected: 1 passed. The first run pulls the Node image.

If it fails, the output in the assertion message shows which `npm` command failed and what the server answered. Fix the server, not the test: this test is what "compatible with npm" means.

- [ ] **Step 3: Document it**

In `README.md`, replace the first paragraph of the section `## Repositories` (it begins "A **blob store** is where") with:

```markdown
A **blob store** is where file content is kept; the `default` one is a directory under
the data directory. A **repository** holds files in one format. The formats so far are
`raw` (arbitrary files by path), `maven` and `npm` (hosted repositories only, for now).
A repository has one of three types: `hosted` (files you publish), `proxy` (a cache of
a remote repository) or `group` (several repositories behind one URL).
```

Add after the `### Maven repositories` section, before `## Health endpoints`:

````markdown
### npm repositories

```bash
curl -u admin -H 'Content-Type: application/json' -d '{
  "name": "npm-hosted", "format": "npm", "type": "hosted",
  "hosted": {"deployment_policy": "disable_redeploy"}
}' http://localhost:8000/api/v1/repositories
```

Point npm at it and sign in. `npm login` asks for a user name and a password, and
MegooArti answers with a personal API token, which npm keeps in `~/.npmrc`:

```bash
npm config set registry https://repo.example.com/repository/npm-hosted/
npm login --auth-type=legacy
npm publish
```

In a pipeline, skip `npm login` and give npm a token directly:

```ini
registry=https://repo.example.com/repository/npm-hosted/
//repo.example.com/repository/npm-hosted/:_authToken=${NPM_TOKEN}
```

- **Signing in** accepts a password, or an API token in place of the password. Each
  sign-in with a password creates a token named `npm login` and the time; it is listed
  with your other tokens and can be revoked there. `npm logout` revokes it. Failed
  attempts are limited as for any sign-in.
- **The package document is generated** on every request from the versions stored, so
  it is right after an unpublish and after two publishes at the same moment.
- **A published tarball is checked** against the `shasum` and `integrity` in its
  manifest. A publish that does not match is refused.
- **Publishing a version again** follows the deployment policy. Use `disable_redeploy`
  to get npm's own rule that a version is published once.
- **Dist-tags.** `latest` is the highest version if the version it named is removed.
- **Permissions.** `npm publish` needs `add`. `npm deprecate` needs `edit`.
  `npm unpublish` needs `delete`, and `add` or `edit` as well when it removes a single
  version, because npm does that by sending the package document back.
- **A publish is read into memory**, up to `MEGOOARTI_NPM_MAX_PUBLISH_BYTES`.
- **Search** (`npm search`) finds the packages this repository holds, by name.
- `npm audit` is not supported; installs do not need it.
- Proxy and group npm repositories are not available yet.
````

- [ ] **Step 4: Run everything**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run pytest -m docker -q`
Expected: all pass, no findings; 12 container tests.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_npm_client.py README.md
git commit -m "test(npm): publish and install with npm itself; document npm repositories"
```
